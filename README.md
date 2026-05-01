# TASUKARU介護AIアプリ 開発引き継ぎ(2026-04-30 第4セッション末)

## 📍 現在の状況サマリ

**掲示板UI大幅刷新セッション完了 + dev/本番両方デプロイ完了**。第4セッションでは、掲示板にカテゴリー機能(タブ式UI + フィルタ + 既存投稿への割当)を完全実装し、見た目も整えた。
**本番マージ + 本番Supabaseテーブル作成 + 動作確認すべて完了**。dev (`tasukaru-dev` Cloud Run) と 本番 (`tasukaru` Cloud Run) の両方で動作中。
本番URL(`tasukaru-191764727533.asia-northeast1.run.app/board`)で実ユーザー(岸本さん他)がコンパクト化された新UIで投稿確認済み。

### 第4セッションでの主な成果
1. **カレンダー色重複アラート機能を完全削除** (ユーザー要望で機能廃止)
2. **掲示板タブUI実装**: 「すべて / 未読 / カテゴリー別」のタブ式フィルタリング
3. **カテゴリー管理モーダル**: 管理者専用、追加・編集・削除・8色から選択
4. **タブデザイン**: 整列・角丸・選択中浮上・横スクロール対応(項目増えたらスワイプ)
5. **投稿時のカテゴリー選択UI**: 新規投稿/編集モーダルにチップ式選択
6. **既存投稿のカテゴリー設定**: 投稿メニューから変更可能
7. **未読カウント即時更新**: ✅トグル後にREACTIONS_DATAキャッシュ更新+再計算
8. **ヘッダー完全sticky化**: タイトル+投稿ボタン+タブ+検索バーが常時上部固定
9. **モーダル透過バグ修正**: bottom-navをモーダル開閉時に display:none で隠す
10. **Supabase RLS問題解決**: `board_categories` テーブルの RLS無効化 (devプロジェクト)
11. **選択中カテゴリータブの文字色修正**: 背景色=カテゴリー色、文字=白で視認性確保(`!important`)
12. **ヘッダーコンパクト化**: 188px → 132px (56px節約)、「掲示板」タイトルが画面上端ギリギリ
13. **box-shadow による隙間カバー**: `0 -50px 0 #f1f3f4` で sticky上部の透けを完全解消
14. **本番マージ完了**: `tasukaru-dev` → `tasukaru` ブランチ自動マージワークフローによりCloud Build/Runへデプロイ
15. **本番Supabase `board_categories` テーブル作成**: 本番のSupabaseプロジェクト `kaigo-ai-app` (`abvglnkwtdeoaazyqwyd`) にテーブル作成 + RLS無効化 + `board_posts.category_id` カラム追加

---

## 🟢 動いている機能(現在のdev)

| 機能 | 状態 |
|---|---|
| 投稿カードのタップ | ✅ |
| ︙メニュー(編集・削除) | ✅(本人のみ、is_admin判定なし) |
| 確認済み/未確認バッジ(赤字・青字) | ✅ |
| コメント・リアクション | ✅ |
| 写真ピンチズーム | ✅ |
| モーダル中央配置 | ✅ |
| 検索バー(本文・スタッフ・利用者) | ✅ |
| 利用者選択UI(投稿モーダル) | ✅ |
| 利用者紐付け表示 | ✅ |
| 掲示板を開くと chat-badge ローカル消去 | ✅(ただし他ページに戻ると復活) |

---

## 🚨 残課題:バッジ復活問題

### 現状の挙動
- 掲示板ページにいる時 → バッジ消える ✅
- TOPなど他のページに戻る → **バッジ「4」が復活する** ❌

### 真因(調査済)
- `base.html` の `checkUnreadMessages` 関数が **`/api/board/unread_count`** を呼んでいる
- このAPIは「全投稿数 - 自分が既読にした投稿数」を返す
- **「掲示板を開いただけ」では既読にならない**(投稿の詳細モーダルを開かないと board_reads に入らない仕様)
- なのでTOPから戻ると **count=4** が返って表示される

### API の動作確認結果
- `/api/unread_count` → `{"count": 0}`(全体未読、現状ゼロ)
- `/api/board/unread_count` → `{"count": 4}` ★ これが「4」の正体
- `/api/board/mark_all_read` → 404(まだ存在しない、新規作成必要)

### 解決策(次セッションで実装)

**新APIを作って「掲示板を開いた瞬間に全投稿を既読化」する**

#### 修正1: `app.py` に新API追加

`api_board_unread_count` 関数の直後(L3380付近、`# ====` セクションコメントの直前)に挿入:

```python
@app.route("/api/board/mark_all_read", methods=["POST"])
@login_required
def api_board_mark_all_read():
    """掲示板を開いた瞬間に全投稿を既読にする"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        all_posts = supabase.table("board_posts").select("id").eq("facility_code", f_code).execute()
        all_ids = [p["id"] for p in (all_posts.data or [])]
        if not all_ids:
            return jsonify({"status": "success", "count": 0})
        existing = supabase.table("board_reads").select("post_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        existing_ids = set(r["post_id"] for r in (existing.data or []))
        to_insert = [{"post_id": pid, "facility_code": f_code, "staff_name": my_name} for pid in all_ids if pid not in existing_ids]
        if to_insert:
            supabase.table("board_reads").insert(to_insert).execute()
        return jsonify({"status": "success", "count": len(to_insert)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
```

#### 修正2: `templates/board.html` に1行追加

`getElementById('chat-badge')` を含むIIFE(L1932付近)に1行追加:

```javascript
// 掲示板を開いたらbase.htmlのバッジをクリア & サーバ側で全投稿を既読化
(function() {
    var badge = document.getElementById('chat-badge');
    if (badge) badge.style.display = 'none';
    if (typeof lastUnreadCount !== 'undefined') lastUnreadCount = 0;
    // ★ サーバ側で全投稿を既読化(他ページから戻ってもバッジ復活しない)
    fetch('/api/board/mark_all_read', { method: 'POST', credentials: 'include' }).catch(function(){});
})();
```

これで TOPに戻ってもバッジは「0」のまま。新規投稿があったときだけ「1」になる。

---

## 📜 直近のコミット履歴

| commit | 状態 | 内容 |
|---|---|---|
| (未push) | 計画中 | mark_all_read API + 1行追加 |
| 39d1a01 | ✅ HEAD | rollback to ed87a9c due to js syntax error |
| 5c32d32 | ❌ 壊れていた | fix board edit delete permission for owner and editors |
| 4dc9524 | ❌ ここで構文エラー混入 | fix board badge persistent clear with css important |
| ed87a9c | ✅ 最後の健全版 | feat unchecked badge and lock background scroll on modal |
| e0b8f2e | ✅ | feat update log add Ver 4.2 |
| f467f6f | ✅ | feat board patient tags and search |
| a7ef20b | ✅ | feat image viewer pinch zoom and pan |
| afb5586 | ✅ | feat board modals centered and editor permissions |
| 910ad87 | ✅ | feat board detail modal centered with dimmed nav |
| f57008b | ✅ | fix board modal z-index conflict with bottom nav |

ed87a9c → 4dc9524 の差分で **`{` を1個多く書いた**のが構文エラーの原因。
回避のため base.html 編集アプローチに切り替えて進めている。

---

## ✅ 直前のbase.html修正(push済み・動作中)

`templates/base.html` の `checkUnreadMessages` 関数(L812付近)に4行追加済み:

```javascript
async function checkUnreadMessages() {
    // 掲示板ページでは未読バッジを更新しない(掲示板を開いた時点で既読扱い)
    if (window.location.pathname === '/board') {
        var badge = document.getElementById('chat-badge');
        if (badge) badge.style.display = 'none';
        return;
    }
    try {
        // ...既存のコード(変更なし)
```

これで掲示板ページにいる間はポーリングが走らない。
ただし他ページでは引き続き `/api/board/unread_count` が呼ばれるので、TOPに戻ると「4」復活する。

---

## 📋 まだ未着手のタスク(次のチャットへ)

### 1. 🔴 最優先: バッジ完全消去
- 上記の `mark_all_read` API + `board.html` の1行追加
- これで TOPに戻ってもバッジ復活しなくなる

### 2. 🟡 操作マニュアル更新(`templates/manual.html`)
**重要**: ユーザーから「**マニュアル上部のフワフワ動くタスカルくんは絶対に削除・変更してはいけない**」との厳命あり。
- `manual.html` ファイル必要(まだアップロード未受け取り)
- 既存ガイドはとても作りこまれた状態で、新機能セクションを**追記**する形がベスト
- 追加すべきセクション: 検索機能 / 利用者紐付け / ピンチズーム / 編集削除権限

### 3. 🟡 モニタリング生成プロンプト敬語化
- `monitoring_integration.py` ファイル必要(まだアップロード未受け取り)
- 現状箇条書き口調 → ケアマネへの報告口調に
- 例:「○○様は…されていました。」「…だそうです。」「しておられました。」

### 4. 🟡 見切れアイコンの修正
- ユーザーから具体的な場所の指定が必要(マニュアル上か掲示板上か不明)
- スクショもらえると一発特定できる

---

## ⚠️ 重要な落とし穴・注意事項

1. **JS編集時はブレースバランスチェック必須**: 文字列・コメント除外で `{` `}` をPythonで厳密カウントすると、構文エラーを早期発見できる
2. **admin_settings に upsert(on_conflict) 禁止** → 42P10エラー → existing確認→update or insert パターン必須
3. **マニュアル上部のフワフワ動くタスカルくんは絶対に触らない**(ユーザー厳命)
4. **「管理者」アカウント完全廃止済み**、個人パスワードでログイン
5. **コミットメッセージで日本語半角括弧 `()` 禁止** → 英字シンプル
6. **iPhone Safariのキャッシュは強い**、`?cb=YYYYMMDDx` で確実に最新取得
7. **チャットの容量上限**でファイルアップロードできない場合あり → ブラウザJS+`raw.githubusercontent.com`+`fetch`でファイル取得可能(GitHub raw URL は ブラウザ経由のみ取得可。bash の curl は raw.githubusercontent.com が allowlist にないので 403)
8. **Cloud Shell が上限**で使えない → Mac のターミナル経由で git 操作
9. **🆕 新規テーブル作成時はRLS必ず無効化(必須セット)** ← 重要!
   - Supabase で `CREATE TABLE` した直後は **Row Level Security が有効状態で作成される場合がある**
   - そのまま放置すると **INSERT / SELECT / UPDATE が silently rejected される**(エラーメッセージなし、空の結果が返るだけ)
   - 例: 2026-04-29 に `board_comment_reads` を作成したが、RLS=true で約30回のINSERTが失敗していた
   - **必須セット**:
     ```sql
     CREATE TABLE IF NOT EXISTS your_new_table (
         id BIGSERIAL PRIMARY KEY,
         ...
     );
     -- ★ 必ず以下も実行(忘れるとINSERTが silent failure する)
     ALTER TABLE your_new_table DISABLE ROW LEVEL SECURITY;
     ```
   - 確認方法:
     ```sql
     SELECT relname, relrowsecurity FROM pg_class WHERE relname = 'your_new_table';
     -- → relrowsecurity が false であること
     ```
10. **管理者権限の認証フロー(2026-04-29 整備)**
    - 個人ログイン(施設コード+個人パスワード)→ 全員必須
    - 管理者MENU入場 = `/admin_auth` で個人パスワード再入力 + `admin_managers` リスト or `facilities.admin_email` スタッフ判定
    - `is_admin_user()` 関数: `admin_managers` に名前があるか、または `admin_email` 紐づきスタッフなら True(緊急リカバリ)
    - **超管理者(facilities.admin_email スタッフ)は常に管理者として保護**(`set_managers` で除外しても自動再追加)

---

## 🗄️ 重要なスキーマ情報

### staffs テーブル
`id, staff_name, facility_code, email, password_hash(SHA256), is_active, birth_date, icon_emoji, icon_image_url`

### facilities テーブル
`facility_code, facility_name, admin_email, admin_password(廃止予定), is_active, expires_at`

### admin_settings テーブル(**ユニーク制約なし、upsert使用禁止**)
`id, facility_code, key, value`
- `key='admin_password'`(旧仕様、廃止予定)
- `key='history_limit'`
- `key='board_editors'`(JSON配列、掲示板編集権限保持者)
- `key='admin_managers'`(JSON配列、管理者MENU入場可能者)

### board_posts テーブル
`id, facility_code, staff_name, content, image_urls(配列), audio_url, file_urls(配列), is_pinned, is_private, mention_names(配列), patient_names(配列), created_at, updated_at, visibility`

### board_reads テーブル(★今回の改修で重要)
`id, post_id, facility_code, staff_name, created_at`
- `mark_all_read` API はここに**未読分を一括 insert**

### board_comment_reads テーブル(2026-04-29 追加)
`id, comment_id, facility_code, staff_name, created_at`
- UNIQUE 制約: `(comment_id, staff_name)`
- コメント未読管理用。`get_comments` API で取得時に既読化、`mark_all_read` で全コメントも既読化
- ⚠️ **作成時 RLS が有効になっていたため一時的に既読化が機能していなかった** → `ALTER TABLE board_comment_reads DISABLE ROW LEVEL SECURITY;` で解決済み

---

## 🔗 重要なリンク・タブ

- dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
- prod URL: https://tasukaru-191764727533.asia-northeast1.run.app
- Cloud Run logs(dev): https://console.cloud.google.com/run/detail/asia-northeast1/tasukaru-dev/observability/logs?project=tasukaru-production
- Cloud Build 履歴: https://console.cloud.google.com/cloud-build/builds?project=tasukaru-production&region=asia-northeast1
- Supabase Storage: https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj/storage/buckets
- Supabase SQL Editor: https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj/sql
- GitHub: https://github.com/cocokaraplus-max/kaigo-ai-app

### 動作確認済みTab(現セッション)
- tabId 661429922: 掲示板dev(現在 39d1a01 で動作中)
- tabId 661429946: Supabase SQL Editor
- tabId 661429943: Cloud Run logs(tasukaru-dev)
- tabId 661429949: 本番カレンダー
- tabId 661429937: Cloud Build 履歴

---

## 🛠️ 開発フロー(Mac経由)

Cloud Shell が上限に達して使えないため、**Mac のターミナル経由**で git 操作している:

```bash
cd ~/dev/kaigo-ai-app

# バックアップ
cp app.py app.py.bak.$(date +%Y%m%d-%H%M)
cp templates/board.html templates/board.html.bak.$(date +%Y%m%d-%H%M)
cp templates/base.html templates/base.html.bak.$(date +%Y%m%d-%H%M)

# Desktopから戻す or テキストエディタで直接編集

# 構文チェック
python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"

# push
git add <files>
git commit -m "<message>"
git push origin tasukaru-dev
```

GitリポジトリのMac側パスは `~/dev/kaigo-ai-app/` 想定。
ファイル受け渡しは `/Users/ZIMAX 1/Desktop/` 経由。

---

## 🎯 次セッションでの初手アクション

1. このREADMEを読み込む
2. **Step 1**: ユーザーに `mark_all_read` API + board.html 1行修正 を伝えて Mac で編集 & push してもらう → バッジ問題完全解決
3. **Step 2**: ユーザーから `manual.html` をアップロードしてもらう → タスカルくん死守でマニュアル更新
4. **Step 3**: ユーザーから `monitoring_integration.py` をアップロードしてもらう → 敬語プロンプト化
5. **Step 4**: 見切れアイコンの場所を聞いて修正

---

## 📂 出力ファイル状態(/mnt/user-data/outputs/)

| ファイル | サイズ | 状態 |
|---|---|---|
| `README.md` | 本書 | 引き継ぎ用 |
| `app.py` | 159,709 bytes | 古い版(編集削除権限の修正含むがpush failed版なので使わない) |
| `board.html` | 95,196 bytes | **構文エラーあり、使わない** |
| `top.html` | 35,939 bytes | Ver.4.2 追加済み(未push、ただし内容は問題なし) |
| `admin.html` | 43,037 bytes | スタッフ管理タブ拡張版 |
| `calendar.html` | 85,060 bytes | カレンダー機能(動作中) |

**重要**: 次セッションでは出力ファイルは**信用せず**、**GitHub の現在の状態**(commit `39d1a01`)を **`raw.githubusercontent.com` からブラウザJS経由で取得**して作業を始めるべき。

```javascript
// 次セッションでブラウザから現在のファイルを取得する例
fetch('https://raw.githubusercontent.com/cocokaraplus-max/kaigo-ai-app/tasukaru-dev/templates/board.html?cb=' + Date.now())
  .then(r => r.text())
  .then(t => { window.__board = t; console.log(t.length); });
```

---

## 🧠 学んだこと(教訓)

1. **大きな変更を一度に push しない** — 機能ごとに細かくcommit & push
2. **JS構文エラーは即座にスクリプト全体を無効化** — タップ反応なし、関数 undefined
3. **base.html を編集する方が board.html を編集するより安全な場合がある** — 影響範囲が広いが、行数が少ないので構文エラーリスクは低い
4. **Pythonの `re` で正規表現の網羅性に注意** — 文字列リテラル内のブレースを誤検出することあり
5. **古いコミットからの差分復活** — `git checkout <commit> -- <path>` で個別復旧可能
6. **API実装が無いから挙動が違う** という根本原因を見つけるまで時間を浪費した — 「TOPに戻るとバッジ復活」が起きるなら、サーバ側で何かのAPIを呼んでいるはず、と最初から考えるべきだった
7. **🆕 ファイル置換時は必ず配置直後に検証** — 2026-04-29 に「修正版app.pyをDLしたつもりが古い別ファイルが Desktop に残っていた」事故が発生。`cp` 直後に `wc -l` `ls -la` `grep -c "新機能名"` で **行数・サイズ・新機能の存在** をかならず確認する
8. **🆕 `git reset --hard <commit>` + `git push --force-with-lease` で安全な版に巻き戻し可能** — 中間コミットが GitHub に残っているなら、reset 先として使える
9. **🆕 Supabase 新規テーブルは RLS チェックを忘れない** — テーブル存在しても、RLS=true だと INSERT が silently 失敗する。`pg_class.relrowsecurity` を必ず確認、または最初から `ALTER TABLE ... DISABLE ROW LEVEL SECURITY;` を CREATE と同時に実行
10. **🆕 セッションフラグ(admin_authenticated 等)はログイン時にクリア** — Flask セッションはブラウザクッキーに紐づくため、別アカウントでログインしても古いフラグが残ったまま動作する → ログイン処理で明示的に `session["admin_authenticated"] = False` を入れる
11. **🆕 チェックすべき認証経路は1つではない** — 「個人ログイン」「`/api/admin_login`(旧)」「`/admin_auth`(新)」が共存していて、どこを通っているか先に Cloud Run ログで確認すべきだった
12. **🆕 デバッグログは `print(..., flush=True)` で Cloud Run logs に即出力** — `flush=True` がないと長時間バッファされてリアルタイム確認できない

---

## 過去の引き継ぎ書(参考)

詳細は `/mnt/transcripts/journal.txt` 参照。本セッションは第3セッションで、第1・第2セッションでは:
- 音声入力一時停止/再開機能
- カレンダー UI 改善
- 評価レポート ICF視点化
- ベル更新情報追加
- 個人パスワード認証移行(管理者特例廃止)
- 写真投稿機能(Supabase Storage)
- 掲示板コメント・リアクション・既読
- 詳細モーダル + ピンチズーム
- 編集削除権限(本人 + board_editors)
- 利用者紐付け + 検索機能

を実装してきた。


---

## 🧠 第4セッションで学んだこと(追記)

13. **🆕 RLSは silently 拒否される** — Supabaseで CREATE TABLE するとデフォルトで RLS有効になる場合があり、ポリシーが無いと全 INSERT/UPDATE/DELETE が拒否される。エラーメッセージは `42501` で `new row violates row-level security policy`。確認SQL: `SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';`。同系のテーブル(他のboard_*など)とRLS設定を揃えることが重要。
14. **🆕 stacking context は z-index の階層を分断する** — 親要素に `z-index: 0` (auto以外) + `position: relative` があると、その内部の要素は親より外には z-index で勝てない。掲示板のモーダル(z-index: 99999)が `.page-wrapper`(z-index: 0) の中にあるため、外の `.bottom-nav` より上に出られなかった。解決策: モーダル開閉時に外の要素を JS で非表示化する MutationObserver パターンが安全。
15. **🆕 sticky 化は親のpaddingを考慮する** — `position: sticky` の要素を親の padding 内に配置すると、stickyしても親の上端paddingが見える。`.page-wrapper` の `padding: 1.5rem 1.2rem` を打ち消すには `margin: -1.5rem -1.2rem ... -1.2rem` で相殺し、内部に `padding: 1.5rem 1.2rem 0 1.2rem` で内部余白を再確保する。
16. **🆕 擬似要素 ::before での背景延長は危険** — `top: -100px; height: 100px` のような擬似要素で背景を伸ばすと、上方向の他要素(ヘッダー等)を覆い隠してしまう事故が起きる。マージン相殺の方が安全。
17. **🆕 sed パターンは現実のファイルとの乖離に弱い** — 私が想定したコメント文や改行を含むパターンが実ファイルと微妙に違うと一切マッチしない。「直前の行が短く、安定しているコード行」をアンカーにして、その**直後に挿入**する正規表現の方が壊れにくい。
18. **🆕 一連の修正で複数スクリプト実行する場合、確認は機械的に** — `grep -c` でキーワード出現数を測ると「適用済みかどうか」が一発でわかる。app.py の `category_id` 出現数を確認して、過去のセッションで既に修正済みだったことを発見できた。
19. **🆕 ファイルの中身を grep で確認 → スクリプト未適用が判明** という流れは強力。`raise SystemExit(1)` で止まったときファイルは無傷なので、慌てずに状態確認すれば良い。
20. **🆕 本番マージは GitHub の自動マージワークフローを確認** — リポジトリに `.github/workflows/auto-merge.yml` のような自動マージが設定されている場合、`tasukaru-dev` への push 後しばらくすると自動的に `tasukaru` にもマージされる。`git log origin/tasukaru --oneline` で `Merge branch 'tasukaru-dev' into tasukaru` のコミットを見つけて状態を確認できる。
21. **🆕 `git status` の "Changes not staged for commit" は実は既にコミット済みのことがある** — VSCodeなど他の経路で何かファイル変更を加えた場合、ターミナルで `git status` が「modified」と表示するが、実際は最新コミットに含まれていることがある。`git diff origin/<branch> -- <file>` でリモートとの真の差分を確認するのが確実。
22. **🆕 cssの `box-shadow` は擬似要素より安全** — `position: sticky` の上方向の透け対策で、擬似要素 `::before { top: -100px }` は親や周辺要素を覆い隠すリスクがある。代わりに対象要素の `box-shadow: 0 -50px 0 #color` を使うと、自分自身の影として描画されるので位置ずれ・覆い隠しが起きない。
23. **🆕 `position: sticky` の停止位置は親の padding を考慮** — 親要素に `padding: 1.5rem` がある場合、その内側に sticky を置くと「停止位置 = 親のpadding上端」になる。ピクセル単位で隙間を消すには `top: -1px` で1px食い込ませる + box-shadow で上方向にも背景を伸ばす2段構えが必要。
24. **🆕 Chrome経由で実機CSSをライブ調整できる** — `getComputedStyle` で値を取得しながら、`element.style.cssText` で即時変更を試して見栄えを確認できる。本番に反映する前に最適値を見つけられるのでデザイン調整に最適。
25. **🆕 dev と 本番でSupabaseプロジェクトが別** — TASUKARUは dev (`tasukaru-dev` プロジェクト, ID `otjevnmoycnvaxeltrtj`) と 本番 (`kaigo-ai-app` プロジェクト, ID `abvglnkwtdeoaazyqwyd`) で**別々のSupabaseプロジェクト**を使用。新しいテーブルを作成したら**両方に反映**する必要がある。dev側だけでテストして満足するとPostgRESTエラー `PGRST205 Could not find the table 'public.<table_name>' in the schema cache` で本番が壊れる。
26. **🆕 Supabase は新規テーブル作成時に RLS有効化を強く推奨** — `CREATE TABLE` 実行時に「Run without RLS / Run and enable RLS」のダイアログが出る。他の `board_*` テーブルが全部 RLS無効ならば、新テーブルも `Run without RLS` を選んで統一性を保つ。後から `ALTER TABLE ... DISABLE ROW LEVEL SECURITY;` を実行する手間も省ける。

---

## 📋 第4セッションで触ったファイル
- `app.py` — `create_post`/`update_post` に `category_id` 受付追加、`board()` ルートにカテゴリー取得処理追加
- `templates/board.html` — タブUI / カテゴリー管理 / カテゴリー選択UI / sticky化 / モーダル透過対策 / ヘッダーコンパクト化(188→132px)
- `templates/calendar.html` — 色重複アラート機能を完全削除
- `README.md` — 第4セッションの引き継ぎとして全面更新

## 📋 第4セッションでのSupabase操作
**dev環境 `tasukaru-dev` (`otjevnmoycnvaxeltrtj`):**
- `board_categories` テーブルの RLS を `DISABLE` に変更 (テーブルは過去のセッションで既に存在)

**本番環境 `kaigo-ai-app` (`abvglnkwtdeoaazyqwyd`):**
- `board_categories` テーブル作成 (id, facility_code, name, color, sort_order, created_by, created_at)
- `board_categories` の RLS無効化 (Run without RLS で実行)
- `board_posts` に `category_id` カラム追加 (FK to board_categories.id, ON DELETE SET NULL)
- インデックス追加: `idx_board_categories_facility`, `idx_board_posts_category`

実行SQL(本番):
```sql
CREATE TABLE IF NOT EXISTS board_categories (
  id SERIAL PRIMARY KEY,
  facility_code TEXT NOT NULL,
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT '#1a73e8',
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE board_categories DISABLE ROW LEVEL SECURITY;
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES board_categories(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_board_categories_facility ON board_categories(facility_code, sort_order);
CREATE INDEX IF NOT EXISTS idx_board_posts_category ON board_posts(category_id);
```

## 📋 次セッションでやること候補
- 段階1〜段階4以外の細かい改善(あれば)
- ユーザーフィードバック反映(実ユーザーの使用感)
- 大量のバックアップファイル(`*.bak.*`, `*.broken.*`)を `.gitignore` に追加して整理
- 古いバックアップファイルの削除(`templates/board.html.bak.20260429*` など、半月以上前のもの)
- 掲示板以外のページのUIも統一感のあるデザインに揃えるか検討
- Supabaseの dev/本番の差異を防ぐためのスキーマ管理ツール導入検討(マイグレーションファイル化)
---

# 🚨 Session 9 引き継ぎ(2026-05-01 21時頃〜) — バイタル機能 Phase 2

## 🎯 現在進行中のタスク: 再検査アラーム機能の実装

### ⚠️ 中断時の最重要事項

**この機能は段階実装の途中。** 中断したら **必ずこのセクションを読んでから再開すること**。

仕様や実装方針を勝手に変えると、ユーザーが過去の会話で決めた仕様と矛盾して **大事故** になる。

---

## 📋 アラーム機能の意思決定(確定済み・絶対変更禁止)

### ユーザーの確定要望
1. **手動「再検査必要」ボタンも残す** — 閾値内でも職員判断で再検査指示できる必要あり
2. **自動再検査マークも併存** — 異常値検出で自動表示
3. **再検査時刻指定**: 「30分後」ボタン + 直接時刻入力 **両方** 提供
4. **アラーム鳴動条件**:
   - **画面スリープ中も鳴る**(超重要)
   - 別アプリ使用中も鳴る
   - アプリ閉じてても鳴る
5. **画面アラーム形式**: 音 + 画面ダイアログで「誰の再検査か」明示
6. **介護現場の運用**: 「アプリは開いてない事が多い」

### 採用方式: **「C案」段階的実装**(ユーザー確定)

| 段階 | 内容 | 工数 | 費用 |
|------|------|------|------|
| **Step 1 (まず実施)** | 手動再検査ボタンの表示反映バグ修正 | 15分 | 無料 |
| **Step 2 (まず実施)** | .icsリマインダー連携 + アプリ内アラーム(音+ダイアログ) | 1〜2時間 | 無料 |
| **Step 3 (運用後に判断)** | Firebase Push通知で完全自動化 | 半日〜1日 | 無料(Sparkプラン) |

**重要: Step 2 まで実施 → 運用してみる → 必要ならStep 3 拡張、という段階的アプローチ**

### 検討時に却下した選択肢(蒸し返し禁止)

| 却下案 | 却下理由 |
|--------|----------|
| Web Audio APIのみ | スリープ中鳴らない |
| ブラウザ通知(Notification API) | iOS Safariで音鳴らず |
| 専用ネイティブアプリ化 | 工数膨大、ストア審査必要 |
| 完全自動化を最初から(Bを直接) | 工数大きい→運用後に拡張判断したい |

---

## 💰 費用に関する確定情報(質問対策)

### 完全無料で実装可能 ✅
- **.icsファイル生成**: 完全無料(HTML/JSのみで完結)
- **Firebase FCM Sparkプラン**: 無料、メッセージ無制限、クレカ登録不要
- **Cloud Run側追加負荷**: ほぼゼロ

### お金が発生する可能性
- **FCM Blazeプラン**(月200万メッセージ超):介護施設規模では絶対到達しない

---

## 📱 端末動作の確定情報

### .ics リマインダー連携の動作

| 項目 | iPhone | Android |
|------|---------|---------|
| .ics対応 | ✅ Safari→「リマインダー」or「カレンダー」 | ✅ Chrome→「Googleカレンダー」or標準カレンダー |
| **スリープ中アラーム** | **✅ 確実に鳴る** | **✅ 確実に鳴る**(Doze modeでもホワイトリスト) |
| 別アプリ使用中の通知 | ✅ バナー+音 | ✅ バナー+音 |

### Android機種別の注意
- **Xiaomi/HUAWEI等**: 独自電池最適化があるため、初期設定で「Googleカレンダー」を「電池最適化対象外」にする必要あり
- **Samsung等**: 独自カレンダーアプリで開く場合あり(.ics対応OK)

### 自動設定不可の制約(重要)
- **iOS/Androidのセキュリティ仕様上、ウェブアプリが勝手にカレンダー登録は禁止**
- 必ず「📅 リマインダーに登録」ボタンを職員が**1タップする必要がある**
- これは仕様上回避不可、Step 3でPush通知に拡張するまでは避けられない

---

## 🛠 Step 1 実装内容(手動再検査ボタンの反映バグ修正)

### 現状の問題
- DBの `recheck` フィールドに手動でtrueを保存しても、表示側で **`hasAnyAlert` だけで判定**している
- 手動チェックは保存されているが表示に反映されない

### 修正内容
全員確認(本日の記録)タブの異常値判定ロジック:

```javascript
// 修正前
const hasAlert = info.items.some(v => hasAnyAlert(v));

// 修正後
const hasAlert = info.items.some(v => hasAnyAlert(v) || v.recheck === true);
```

該当箇所(2箇所):
1. `loadDailyOverview` 内の patientList生成部
2. エディタの `daily-time-tab.has-alert` 判定箇所

### 編集タブの「再検査必要」チェックボックスも残す
編集フォームに以下を追加:
```html
<label>
    <input type="checkbox" id="ef-recheck-${pid}">
    再検査が必要(手動)
</label>
```
保存時に `recheck` フィールドに反映、自動判定の `hasAnyAlert` とORで判定。

### 記録タブ(測定タブ)の「再検査必要」も同様に残す
現在の `<input type="checkbox" id="v-recheck-${pid}">` は維持。
手動 OR 自動のいずれかで `recheck=true` になる仕様。

---

## 🛠 Step 2 実装内容(.icsリマインダー連携 + アプリ内アラーム)

### 2-1. DB追加: `vital_recheck_schedules` テーブル(Supabase)

```sql
CREATE TABLE vital_recheck_schedules (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    vital_id UUID,  -- 元の異常値検出した測定のID(あれば)
    scheduled_at TIMESTAMPTZ NOT NULL,
    note TEXT,
    is_completed BOOLEAN DEFAULT false,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT
);
ALTER TABLE vital_recheck_schedules DISABLE ROW LEVEL SECURITY;
CREATE INDEX idx_recheck_schedules_lookup ON vital_recheck_schedules(facility_code, scheduled_at);
```

**重要**: 引き継ぎ書教訓3「新規Supabaseテーブル作成時はRLS必ずDISABLE」厳守

### 2-2. API追加(app.py)

- `/api/recheck_schedule` POST: 再検査予定登録
- `/api/recheck_schedule` GET: 当日の予定一覧取得
- `/api/recheck_schedule/<id>` POST(complete): 完了マーク

### 2-3. UI追加(vitals.html)

#### 異常値検出時/手動recheck時にUIを表示
```
┌─────────────────────────────────┐
│ ⚠ 池田 ヨシ 様 異常値検出       │
│ 血圧 200/150                    │
│                                 │
│ 何分後に再検査しますか?         │
│  [+15分][+30分][+1時間][+2時間] │
│  または直接時刻 [14:30]         │
│                                 │
│ [📅 リマインダーに登録]         │ ← .ics生成
│ ☑ アプリ画面でも通知(開いてる時)│
└─────────────────────────────────┘
```

#### .ics生成ロジック
```javascript
function generateICS(scheduleData) {
    const dt = new Date(scheduleData.scheduled_at);
    const dtUtc = dt.toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'');
    return `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//TASUKARU//VitalRecheck//JP
BEGIN:VEVENT
UID:${Date.now()}@tasukaru.app
DTSTAMP:${dtUtc}
DTSTART:${dtUtc}
SUMMARY:再検査:${scheduleData.user_name} 様
DESCRIPTION:${scheduleData.note || ''}
BEGIN:VALARM
TRIGGER:-PT0M
ACTION:DISPLAY
DESCRIPTION:再検査時間です
END:VALARM
END:VEVENT
END:VCALENDAR`;
}
// Blob→ダウンロードリンク
```

#### アプリ内アラーム(画面開いてる時)
- 全員確認タブ表示中、定期的に未完了の `recheck_schedules` をチェック
- scheduled_at <= now() の予定があれば → モーダル表示 + 音再生
- Web Audio API で短いビープ音(Base64埋込)
- モーダル: 「[今から測定] [10分後に再通知] [完了にする]」

### 2-4. 用語の確定

| 旧 | 新 |
|----|----|
| 再検査 | 再検査(変更なし) |
| recheck flag | 自動判定 + 手動チェック両方の OR |

---

## 🚧 Step 3(将来):Firebase Push通知

**重要**: Step 2の運用結果次第。今は手を付けない。

### Step 3 の前提条件(満たされた時のみ着手)
- Step 2 実装後、現場で「.ics登録の1タップが運用上厳しい」と判明
- ホーム画面追加(PWA化)を職員が受け入れられる体制
- iOS 16.4 以上の端末が普及している(Push通知の最低要件)

### Step 3 着手時の実装ステップ
1. Firebase プロジェクト作成(無料Sparkプラン)
2. VAPID鍵生成
3. firebase-config.js 作成
4. Service Worker 拡張(`sw.js` に push handler 追加)
5. クライアント: 通知許可取得→FCMトークン取得→DB保存
6. サーバー: push送信ジョブ(scheduled_at到来時にFCM送信)
7. iOS: PWA化必須(マニフェスト整備)、Android: 標準的に動く

### Step 3 で追加するDBカラム
```sql
ALTER TABLE patients ADD COLUMN fcm_tokens JSONB DEFAULT '[]'::jsonb;
-- または別テーブル
CREATE TABLE fcm_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT,
    user_id TEXT,  -- 職員ID
    fcm_token TEXT UNIQUE,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 📝 実装順序(再開時はこの順番厳守)

1. ✅ **Step 1**: 手動recheckの表示反映バグ修正(15分)→ push → 動作確認
2. ✅ **Step 2-1**: Supabaseに `vital_recheck_schedules` テーブル作成(RLS無効化必須)
3. ✅ **Step 2-2**: app.pyに3つのAPI追加 → push → ログでエラー出ないこと確認
4. ✅ **Step 2-3**: vitals.htmlに再検査時刻設定UI追加 → push → 動作確認
5. ✅ **Step 2-4**: .ics生成ロジック → 実機(iPhone/Android)でリマインダー登録できるか確認
6. ✅ **Step 2-5**: アプリ内アラーム(画面開いてる時)→ 動作確認
7. ⏸ **Step 3**: 運用してみて必要なら(後回し)

---

## ⚠️ 中断時の引継ぎチェックリスト

中断時、新しいチャットへ引き継ぐ時は以下を必ず明示:

- [ ] 現在Stepいくつまで完了したか
- [ ] 各Stepでpush済みコミットハッシュ
- [ ] Step 2-1 のテーブル作成済みか
- [ ] Step 3 への移行判断を保留中であること(勝手に着手しないよう警告)
- [ ] 「.icsリマインダー連携」が選択された経緯と「自動化はStep 3まで保留」という確定事項

---

# 🚨 Session 9 引き継ぎ(2026-05-01 21時頃〜) — バイタル機能 Phase 2

## 🎯 現在進行中のタスク: 再検査アラーム機能の実装

### ⚠️ 中断時の最重要事項

**この機能は段階実装の途中。** 中断したら **必ずこのセクションを読んでから再開すること**。

仕様や実装方針を勝手に変えると、ユーザーが過去の会話で決めた仕様と矛盾して **大事故** になる。

---

## 📋 アラーム機能の意思決定(確定済み・絶対変更禁止)

### ユーザーの確定要望
1. **手動「再検査必要」ボタンも残す** — 閾値内でも職員判断で再検査指示できる必要あり
2. **自動再検査マークも併存** — 異常値検出で自動表示
3. **再検査時刻指定**: 「30分後」ボタン + 直接時刻入力 **両方** 提供
4. **アラーム鳴動条件**:
   - **画面スリープ中も鳴る**(超重要)
   - 別アプリ使用中も鳴る
   - アプリ閉じてても鳴る
5. **画面アラーム形式**: 音 + 画面ダイアログで「誰の再検査か」明示
6. **介護現場の運用**: 「アプリは開いてない事が多い」

### 採用方式: **「C案」段階的実装**(ユーザー確定)

| 段階 | 内容 | 工数 | 費用 |
|------|------|------|------|
| **Step 1 (まず実施)** | 手動再検査ボタンの表示反映バグ修正 | 15分 | 無料 |
| **Step 2 (まず実施)** | .icsリマインダー連携 + アプリ内アラーム(音+ダイアログ) | 1〜2時間 | 無料 |
| **Step 3 (運用後に判断)** | Firebase Push通知で完全自動化 | 半日〜1日 | 無料(Sparkプラン) |

**重要: Step 2 まで実施 → 運用してみる → 必要ならStep 3 拡張、という段階的アプローチ**

### 検討時に却下した選択肢(蒸し返し禁止)

| 却下案 | 却下理由 |
|--------|----------|
| Web Audio APIのみ | スリープ中鳴らない |
| ブラウザ通知(Notification API) | iOS Safariで音鳴らず |
| 専用ネイティブアプリ化 | 工数膨大、ストア審査必要 |
| 完全自動化を最初から(Bを直接) | 工数大きい→運用後に拡張判断したい |

---

## 💰 費用に関する確定情報(質問対策)

### 完全無料で実装可能 ✅
- **.icsファイル生成**: 完全無料(HTML/JSのみで完結)
- **Firebase FCM Sparkプラン**: 無料、メッセージ無制限、クレカ登録不要
- **Cloud Run側追加負荷**: ほぼゼロ

### お金が発生する可能性
- **FCM Blazeプラン**(月200万メッセージ超):介護施設規模では絶対到達しない

---

## 📱 端末動作の確定情報

### .ics リマインダー連携の動作

| 項目 | iPhone | Android |
|------|---------|---------|
| .ics対応 | ✅ Safari→「リマインダー」or「カレンダー」 | ✅ Chrome→「Googleカレンダー」or標準カレンダー |
| **スリープ中アラーム** | **✅ 確実に鳴る** | **✅ 確実に鳴る**(Doze modeでもホワイトリスト) |
| 別アプリ使用中の通知 | ✅ バナー+音 | ✅ バナー+音 |

### Android機種別の注意
- **Xiaomi/HUAWEI等**: 独自電池最適化があるため、初期設定で「Googleカレンダー」を「電池最適化対象外」にする必要あり
- **Samsung等**: 独自カレンダーアプリで開く場合あり(.ics対応OK)

### 自動設定不可の制約(重要)
- **iOS/Androidのセキュリティ仕様上、ウェブアプリが勝手にカレンダー登録は禁止**
- 必ず「📅 リマインダーに登録」ボタンを職員が**1タップする必要がある**
- これは仕様上回避不可、Step 3でPush通知に拡張するまでは避けられない

---

## 🛠 Step 1 実装内容(手動再検査ボタンの反映バグ修正)

### 現状の問題
- DBの `recheck` フィールドに手動でtrueを保存しても、表示側で **`hasAnyAlert` だけで判定**している
- 手動チェックは保存されているが表示に反映されない

### 修正内容
全員確認(本日の記録)タブの異常値判定ロジック:

```javascript
// 修正前
const hasAlert = info.items.some(v => hasAnyAlert(v));

// 修正後
const hasAlert = info.items.some(v => hasAnyAlert(v) || v.recheck === true);
```

該当箇所(2箇所):
1. `loadDailyOverview` 内の patientList生成部
2. エディタの `daily-time-tab.has-alert` 判定箇所

### 編集タブの「再検査必要」チェックボックスも残す
編集フォームに以下を追加:
```html
<label>
    <input type="checkbox" id="ef-recheck-${pid}">
    再検査が必要(手動)
</label>
```
保存時に `recheck` フィールドに反映、自動判定の `hasAnyAlert` とORで判定。

### 記録タブ(測定タブ)の「再検査必要」も同様に残す
現在の `<input type="checkbox" id="v-recheck-${pid}">` は維持。
手動 OR 自動のいずれかで `recheck=true` になる仕様。

---

## 🛠 Step 2 実装内容(.icsリマインダー連携 + アプリ内アラーム)

### 2-1. DB追加: `vital_recheck_schedules` テーブル(Supabase)

```sql
CREATE TABLE vital_recheck_schedules (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    vital_id UUID,  -- 元の異常値検出した測定のID(あれば)
    scheduled_at TIMESTAMPTZ NOT NULL,
    note TEXT,
    is_completed BOOLEAN DEFAULT false,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT
);
ALTER TABLE vital_recheck_schedules DISABLE ROW LEVEL SECURITY;
CREATE INDEX idx_recheck_schedules_lookup ON vital_recheck_schedules(facility_code, scheduled_at);
```

**重要**: 引き継ぎ書教訓3「新規Supabaseテーブル作成時はRLS必ずDISABLE」厳守

### 2-2. API追加(app.py)

- `/api/recheck_schedule` POST: 再検査予定登録
- `/api/recheck_schedule` GET: 当日の予定一覧取得
- `/api/recheck_schedule/<id>` POST(complete): 完了マーク

### 2-3. UI追加(vitals.html)

#### 異常値検出時/手動recheck時にUIを表示
```
┌─────────────────────────────────┐
│ ⚠ 池田 ヨシ 様 異常値検出       │
│ 血圧 200/150                    │
│                                 │
│ 何分後に再検査しますか?         │
│  [+15分][+30分][+1時間][+2時間] │
│  または直接時刻 [14:30]         │
│                                 │
│ [📅 リマインダーに登録]         │ ← .ics生成
│ ☑ アプリ画面でも通知(開いてる時)│
└─────────────────────────────────┘
```

#### .ics生成ロジック
```javascript
function generateICS(scheduleData) {
    const dt = new Date(scheduleData.scheduled_at);
    const dtUtc = dt.toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'');
    return `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//TASUKARU//VitalRecheck//JP
BEGIN:VEVENT
UID:${Date.now()}@tasukaru.app
DTSTAMP:${dtUtc}
DTSTART:${dtUtc}
SUMMARY:再検査:${scheduleData.user_name} 様
DESCRIPTION:${scheduleData.note || ''}
BEGIN:VALARM
TRIGGER:-PT0M
ACTION:DISPLAY
DESCRIPTION:再検査時間です
END:VALARM
END:VEVENT
END:VCALENDAR`;
}
// Blob→ダウンロードリンク
```

#### アプリ内アラーム(画面開いてる時)
- 全員確認タブ表示中、定期的に未完了の `recheck_schedules` をチェック
- scheduled_at <= now() の予定があれば → モーダル表示 + 音再生
- Web Audio API で短いビープ音(Base64埋込)
- モーダル: 「[今から測定] [10分後に再通知] [完了にする]」

### 2-4. 用語の確定

| 旧 | 新 |
|----|----|
| 再検査 | 再検査(変更なし) |
| recheck flag | 自動判定 + 手動チェック両方の OR |

---

## 🚧 Step 3(将来):Firebase Push通知

**重要**: Step 2の運用結果次第。今は手を付けない。

### Step 3 の前提条件(満たされた時のみ着手)
- Step 2 実装後、現場で「.ics登録の1タップが運用上厳しい」と判明
- ホーム画面追加(PWA化)を職員が受け入れられる体制
- iOS 16.4 以上の端末が普及している(Push通知の最低要件)

### Step 3 着手時の実装ステップ
1. Firebase プロジェクト作成(無料Sparkプラン)
2. VAPID鍵生成
3. firebase-config.js 作成
4. Service Worker 拡張(`sw.js` に push handler 追加)
5. クライアント: 通知許可取得→FCMトークン取得→DB保存
6. サーバー: push送信ジョブ(scheduled_at到来時にFCM送信)
7. iOS: PWA化必須(マニフェスト整備)、Android: 標準的に動く

### Step 3 で追加するDBカラム
```sql
ALTER TABLE patients ADD COLUMN fcm_tokens JSONB DEFAULT '[]'::jsonb;
-- または別テーブル
CREATE TABLE fcm_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT,
    user_id TEXT,  -- 職員ID
    fcm_token TEXT UNIQUE,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 📝 実装順序(再開時はこの順番厳守)

1. ✅ **Step 1**: 手動recheckの表示反映バグ修正(15分)→ push → 動作確認
2. ✅ **Step 2-1**: Supabaseに `vital_recheck_schedules` テーブル作成(RLS無効化必須)
3. ✅ **Step 2-2**: app.pyに3つのAPI追加 → push → ログでエラー出ないこと確認
4. ✅ **Step 2-3**: vitals.htmlに再検査時刻設定UI追加 → push → 動作確認
5. ✅ **Step 2-4**: .ics生成ロジック → 実機(iPhone/Android)でリマインダー登録できるか確認
6. ✅ **Step 2-5**: アプリ内アラーム(画面開いてる時)→ 動作確認
7. ⏸ **Step 3**: 運用してみて必要なら(後回し)

---

## ⚠️ 中断時の引継ぎチェックリスト

中断時、新しいチャットへ引き継ぐ時は以下を必ず明示:

- [ ] 現在Stepいくつまで完了したか
- [ ] 各Stepでpush済みコミットハッシュ
- [ ] Step 2-1 のテーブル作成済みか
- [ ] Step 3 への移行判断を保留中であること(勝手に着手しないよう警告)
- [ ] 「.icsリマインダー連携」が選択された経緯と「自動化はStep 3まで保留」という確定事項


---

## 📚 Step 4: 利用者向けガイドページの作成(必須)

### 重要
Step 2 完了後、**必ず** 利用者(=介護施設の職員)向けの設定方法ガイドを実装する。
これがないと、「.icsをタップしてもどうしていいかわからない」状態になる。

### ガイドの場所
バイタルタブ → 「設定」タブの中、または **新規「ヘルプ」タブ** を追加

### ガイド内容(最低限)

#### 1. 再検査アラームの仕組みを説明
- 「異常値を検出すると、再検査時刻を設定できます」
- 「設定したらリマインダー登録ボタンを押してください」
- 「お使いの端末のアラームで通知されます(画面スリープ中もOK)」

#### 2. iOS版の初回設定手順(画像付き推奨)
- 「📅 リマインダーに登録」ボタンを押す
- ダイアログで「リマインダー」または「カレンダー」を選ぶ
- アプリ内で「追加」ボタンを押して登録完了
- 通知許可を求められたら必ず「許可」を選ぶ
- システム設定→通知→リマインダー(orカレンダー)で**サウンドON**を確認

#### 3. Android版の初回設定手順
- 「📅 リマインダーに登録」ボタンを押す
- 「Googleカレンダー」または標準カレンダーを選ぶ
- 「保存」を押して登録
- **重要**: Xiaomi/HUAWEI/OPPO等の場合
  - 設定 → アプリ → Googleカレンダー → 電池 → 「制限なし」に変更
  - これをしないとスリープ中に通知が鳴らない可能性

#### 4. トラブルシューティング
- 「アラームが鳴らない時のチェックリスト」
  - 端末のサイレントモードがOFFか?
  - 通知音量がゼロでないか?
  - リマインダー/カレンダーアプリが通知許可されているか?
  - (Android) 電池最適化対象外になっているか?
  - .icsファイルがダウンロードされなかった場合は再度ボタン押す

#### 5. 「いつ・どこで通知が鳴るのか」一覧表

| シーン | 内部アラーム | リマインダー(.ics) |
|--------|------------|-------------------|
| バイタル画面を表示中 | ✅ 鳴る | ✅ 鳴る |
| 別タブを表示中 | △ 場合により | ✅ 鳴る |
| 別アプリ使用中 | ❌ 鳴らない | ✅ 鳴る |
| 画面スリープ中 | ❌ 鳴らない | ✅ 鳴る |
| アプリ完全終了 | ❌ 鳴らない | ✅ 鳴る |

→ **だから「📅 リマインダーに登録」が重要** という説明を載せる

### 実装方針
- 静的なHTMLコンテンツでOK(Jinjaテンプレート内)
- 折りたたみアコーディオン形式(Q&A風)
- スクリーンショット画像があるとなお良い(後回しでも可)
- 「設定」タブの中に「📚 使い方ガイド」セクションを追加するのが工数最小

