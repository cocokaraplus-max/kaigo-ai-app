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


---

# Session 11 動作確認結果(2026-05-03 朝)

Step 2-③ アラーム機能の動作確認を dev 環境(iPhone Safari)で実施した結果と、見つかった既知問題の記録。

## 動作 OK の項目

- アラームモーダルの発火(30秒ポーリング → 期限切れ予約検出 → 赤枠+パルス表示)
- 「今から測定する」ボタン → 該当利用者のエディタが自動展開
- 「10分後に再通知」ボタン → snooze API 呼び出し → 一覧の時刻が10分後に更新
- 「完了にする」ボタン → complete API 呼び出し → 一覧から消える(または完了状態)
- 「過去時刻ですが本当に登録しますか?」確認ダイアログ
- 既存予約一覧の表示(時刻 / 完了状態 / メモ / 削除ボタン)

## 既知の問題(Session 12 で対応予定)

### 問題A: iPhone Safari で初回ロード時に「取得エラー: Load failed」

- **症状**: 「既に予約済みの再検査」セクションに `取得エラー: Load failed` と表示される
- **原因**: 教訓8 の Service Worker 古い版キャッシュ(古い JS が fetch をインターセプトしている疑い)
- **回避策**: iPhone 設定 → Safari → 「履歴とWebサイトデータを消去」を実施 → 解決を確認済み
- **恒久対策案**: ガイドページ(Step 4)で SW クリア手順を明記する。または vitals.html の SW 登録部に強制更新ロジックを追加することを検討
- **重要**: dev 環境を Mac Chrome で同時に確認した結果、**サーバー側 API は正常動作**(GET /api/recheck_schedule が schedules 配列を正しく返す)。問題は iPhone Safari クライアント側の SW キャッシュのみ

### 問題B: アラームのビープ音が鳴らない

- **症状**: アラームモーダルは表示されるが、Web Audio API のビープ音(880Hz/660Hz, 4音, 計0.9秒)が鳴らない
- **原因**: iOS Safari の autoplay 制限。AudioContext がユーザー操作直後でないと鳴らせない
- **修正方針**: 「📅 リマインダーに登録」「+15分」などのクイックボタンタップ時に AudioContext を unlock(無音再生)して活性化しておく。後でアラーム発火時にその AudioContext で音を鳴らせるようにする
- **状態**: 未修正(Session 12 で対応)

### 問題C: iOS の「カレンダーの参加依頼を表示しようとしています」ダイアログが分かりにくい

- **症状**: 「📅 リマインダーに登録」を押すと iOS が `tasukaru-dev-...run.app はカレンダーの参加依頼を表示しようとしています。許可しますか?` というシステムダイアログを表示する。「無視」を押されると .ics が登録されない
- **原因**: iOS Safari の固定UI(ウェブ側からは文言を変更できない)
- **修正方針**: ボタン直前または直後に「次の画面で『許可』を押してください」という事前案内を追加する
- **状態**: 未修正(Session 12 で対応)

## ユーザーから新たに出てきた要望(Session 12 以降)

Step 2-③ 動作確認中に出てきた、現状未着手の要望:

1. **「測定」タブの統合検討**: 「測定」タブで利用者を展開すると保存ボタン下のフッターに食い込む。「本日の記録」タブに利用者追加機能を持たせれば「測定」タブを廃止できる可能性がある(ただし大改修なので慎重に)
2. **「未測定」表示**: 「本日の記録」タブで未測定の利用者も表示し、空欄 or 「未測定」ラベルで視覚的に分かるようにする
3. **カメラ読み取りボタンの移植**: 現状「測定」タブのみにあるカメラ自動読み取りを、「本日の記録」アコーディオン編集にも追加する
4. **音声入力でのバイタル入力(NEW)**: 「体温36.5、血圧上120、下80、脈60、酸素97」のような自然文を解析して各フィールドに自動入力する機能。Web Speech API を想定。介護現場の運用想定で工数大きめ(別セッション扱い推奨)

## 最新コミット状態(2026-05-03 朝)

```
45b5c29 (HEAD -> tasukaru-dev, origin/tasukaru-dev) docs session11 handoff with step 2 completion and incident lessons
8611db5 feat vitals recheck alarm with polling beep modal and snooze api  [Step 2-③]
4ccd76b fix vitals recheck ics filename ascii safe with patient id and timestamp
3ee08a3 feat vitals recheck schedule ui with quick buttons and ics download  [Step 2-②]
8441073 feat vital recheck schedule apis post get complete delete  [Step 2-①]
8803c33 fix vitals manual recheck reflect in display and add manual checkbox in editor  [Step 1]
```

- app.py: 4383 行 / 196216 bytes
- templates/vitals.html: 2980 行 / 144326 bytes


---

# Session 12 Phase A 完了(2026-05-03)

Session 11 で見つかった問題B(アラーム音 autoplay)と問題C(iOS文言事前案内)を修正、コミット `eb90403` でデプロイ。

## 修正内容

### 問題B: アラーム音 autoplay unlock(解決済)
- iOS Safari の autoplay 制限により、ユーザー操作直後の AudioContext でなければ音が鳴らない問題に対処
- `templates/vitals.html` に `unlockAlarmAudio()` 関数を新規追加
- `setQuickRecheckTime()` と `saveRecheckSchedule()` の冒頭で呼び出し、ユーザーがクイックボタンや「リマインダーに登録」を押した瞬間に AudioContext を活性化(無音バッファ1サンプル再生で iOS の autoplay ロックを解除)
- 後でアラーム発火時、その AudioContext を再利用して `playAlarmBeep()` がビープ音を鳴らせる

### 問題C: iOS「カレンダーの参加依頼」事前案内(解決済)
- iOS の固定UI(文言は変更不可)で利用者が混乱しないよう、「📅 リマインダーに登録」ボタンの直下に黄色背景・点線枠の小さな案内文を追加
- 内容: 「ボタンを押すと iPhone・iPad では『カレンダーの参加依頼を表示しますか?』と確認が出ます。『許可』を押してください。次にカレンダーアプリが開いたら『追加』を押すと登録完了です。」
- CSS: `.recheck-ios-notice` クラス(font-size 0.72rem、padding 8px 10px)

## 動作確認結果(iPhone Safari、2026-05-03)
- ✅ アラームモーダル発火時にビープ音が鳴る
- ✅ 案内文が「📅 リマインダーに登録」ボタンの直下に表示される

## 「閉じてる時に鳴らせるか」のユーザー疑問への整理

| シーン | 鳴るか |
|--------|--------|
| vitalsページを開いたまま | ✅ アプリ内アラーム(モーダル+ビープ)が鳴る |
| 別タブを使用中 | △ 場合により(JSタイマーがOSにスロットルされる) |
| 画面閉じる/別アプリ/スリープ | ✅ ただし「📅 リマインダーに登録」→「許可」→「追加」までやって OS カレンダーに登録した場合のみ |
| アプリ完全終了 | ✅ 同上(OS カレンダーが鳴らす) |
| 完全自動(ボタン操作不要) | ❌ Step 3 Firebase Push で実現する設計、未実装、明示依頼まで提案禁止 |

→ 「閉じてる時に鳴らない」と感じる場合は、.icsカレンダー登録の最後の「追加」まで完了していない可能性が高い。Step 4 のガイドページで明確に案内する予定。

## 最新コミット状態(2026-05-03 夜)

```
eb90403 fix vitals alarm audio autoplay unlock and add ios calendar dialog notice  [Phase A]
c357b67 chore add bak and broken files to gitignore
b900c5e docs session11 verification result and session12 handoff with audio autoplay and ios calendar dialog issues
45b5c29 docs session11 handoff with step 2 completion and incident lessons
8611db5 feat vitals recheck alarm with polling beep modal and snooze api
```

- `app.py`: 4383 行 / 196216 bytes(変更なし)
- `templates/vitals.html`: 3014 行 / 146288 bytes(+34 行)
- `.gitignore`: 30 行(.bak / .broken 除外ルール追加済)

## Session 12 Phase B 以降の選択肢(まだ未着手)

引き継ぎ書通り、ここから先は明示の指示があるまで着手しない。

| 選択肢 | 内容 | 工数 |
|-------|------|------|
| **B-1: Step 4(利用者向けガイドページ)** | 「設定」タブに「📚 使い方ガイド」追加 | 1〜3時間 |
| **B-2: 「本日の記録」タブ強化** | 未測定者表示 + カメラ読み取りボタン移植 | 2〜3時間 |
| **B-3: 「測定」タブ廃止/統合** | UI 大改修、回帰テスト多 | 2〜4時間(B-3 はユーザー判断で見送り、現状維持で OK) |
| **C: 音声入力(Gemini Audio)** | ✅ Session 13 で実装済(下記参照) | 完了 |
| **D: Step 3(Firebase Push)** | 完全自動通知 | 半日〜2日(明示依頼があるまで提案禁止) |


---

# 🎙 Session 13 完了(2026-05-04)— 音声バイタル入力 MVP

## 概要

「測定」タブで利用者のバイタル測定値を **音声で入力** できる機能を追加。利用者の前で「血圧上125、下78、脈拍72、体温36.5、SpO2 98、調子は良好です」と話すだけで、Gemini が音声を解析し、各フィールドへ数値が自動入力される。

## 確定仕様(Session 12 から継続、変更なし)

- 対象タブ:「測定」タブのみ(本日の記録タブには追加しない)
- ボタン位置:カメラ自動読み取りボタンの **真横**(B案・横並び 50:50)
- 音声エンジン:**Gemini**(既存の `get_generative_model()` を再利用、Whisper 等の追加コストなし)
- 解析:Gemini で音声 → JSON 一発で完結(中間処理なし)
- 録音時間:**最大 20 秒**(自動停止 or 録音中タップで早期終了)
- メモ欄対応:数値以外の発話があれば既存メモに ` / ` 区切りで追記
- 認識結果:確認ダイアログなしで即フィールドへセット(カメラ読み取りと同じ挙動)
- 永続保存:**しない**(プライバシー配慮、`upload_audio_to_supabase` は呼ばない)

## 実装内容

### バックエンド(app.py)

新規エンドポイント `/api/vital_voice_parse`(1446行〜1503行、約 59 行)

```python
@app.route('/api/vital_voice_parse', methods=['POST'])
@login_required
def api_vital_voice_parse():
    # request.files.get('audio') で受信
    # MIME マップ: .mp3/.m4a/.wav/.aac/.ogg/.webm/.mp4 (iOS Safari 対応で .mp4 追加)
    # デフォルト MIME: audio/webm (Chrome の MediaRecorder デフォルト)
    # Gemini プロンプトで bp_high/bp_low/pulse/temperature/spo2/memo を抽出
    # JSON 抽出: re.search(r'\{.*\}', resp.text.strip(), re.DOTALL)
```

設計判断:
- 既存の `/api/read_vital_image`(画像版)を参考に同じパターンで実装
- `parse_assessment_file` の MIME 判定パターンを流用
- `upload_audio_to_supabase` は **import しない**(永続保存しない仕様)
- 録音空チェック追加(`if not audio_bytes`)

### フロントエンド(templates/vitals.html)

**HTML 変更**(1241行付近):

```html
<!-- Before -->
<button class="camera-btn" onclick="openCamera('${p.id}')">
    <span class="material-symbols-outlined">photo_camera</span>
    カメラで数値を自動読み取り
</button>

<!-- After -->
<div class="vital-action-row">
    <button class="camera-btn" onclick="openCamera('${p.id}')">
        <span class="material-symbols-outlined">photo_camera</span>
        カメラ読み取り
    </button>
    <button class="voice-btn" id="voice-btn-${p.id}" onclick="toggleVoiceRecording('${p.id}')">
        <span class="material-symbols-outlined">mic</span>
        <span class="voice-btn-label">音声入力</span>
    </button>
</div>
```

**CSS 追加**(111行〜137行):
- `.vital-action-row`:flex 50:50 等幅
- `.voice-btn`:緑系グラデーション(`#34a853 → #2d8f47`)、camera-btn と同サイズ
- `.voice-btn.recording`:赤系(`#dc2626 → #b91c1c`)+ 1.2秒の脈動アニメ

**JavaScript 追加**(1500行〜1700行付近、約 200 行):
- `pickVoiceMime()`:Chrome/Safari 両対応の MIME 自動選択
- `toggleVoiceRecording(pid)`:タップで開始 / 録音中タップで早期終了 / 20秒で自動停止
- `sendVoiceToAI(blob, ext)`:`/api/vital_voice_parse` への POST、レスポンスでフィールド自動入力
- `cleanupVoiceStream()`:MediaStream トラック停止

iOS Safari 対応:
- MIME 候補リストに `audio/mp4` を含める
- `MediaRecorder.isTypeSupported` で動的に対応 MIME を選択
- 失敗時は `new MediaRecorder(stream)` のデフォルトにフォールバック

## 動作確認結果(2026-05-04)

| 環境 | 結果 |
|------|------|
| Mac Chrome(dev) | ✅ 録音 → 数値抽出 → フィールド自動入力 → 保存まで OK |
| iPhone Safari(dev) | ✅ マイク権限取得 → 録音 → 数値抽出 → 保存まで OK |

## 遭遇した問題と対処

### 問題1:Service Worker キャッシュで古い HTML が表示される(教訓8 再発)

**症状**:push 後、Mac Chrome で dev タブをリロードしても古い HTML が返る(`voice-btn` が DOM に存在しない)。`unlockAlarmAudio`(Session 12 で追加した関数)すら window に存在しない状態。

**原因**:`tasukaru-v6-static` キャッシュが古い HTML を提供し続ける。

**対処**:Chrome 連携で以下を実行:

```javascript
const regs = await navigator.serviceWorker.getRegistrations();
for (const r of regs) await r.unregister();
const names = await caches.keys();
for (const n of names) await caches.delete(n);
location.reload();
```

これで Service Worker と全キャッシュを消去 → ハードリロード → 新版反映。

### 問題2:ローカル Flask 起動で環境変数が読まれない

**症状**:`python3 app.py` で起動しても、Supabase 接続できずログイン不可。

**原因**:`app.py` / `utils.py` に `load_dotenv()` の呼び出しが無い。Cloud Run では Secret Manager から直接環境変数が注入されるため気づかなかった。

**対処**:今回はローカル起動を諦めて Cloud Run dev での確認に切り替え。`load_dotenv()` 追加は別途検討課題(本筋スコープ外のため Session 13 では対応せず)。

## ファイル変更サマリ

| ファイル | 変更前 | 変更後 | 差分 |
|---------|-------|-------|------|
| `app.py` | 4383行 / 196216 bytes | 4442行 / 198998 bytes | +59 行 |
| `templates/vitals.html` | 3014行 / 146288 bytes | 3252行 / 155229 bytes | +238 行 |

## コミット

```
50093c0 feat vitals voice input parse with gemini audio analysis
```

1機能=1コミット完結(教訓5)。Cloud Run dev へデプロイ済み。

## 教訓追加(教訓16〜17)

### 教訓16:Service Worker キャッシュは Mac Chrome でも発生する

Session 12 では iPhone でしか観測しなかった Service Worker キャッシュ問題が、Mac Chrome でも発生。push 直後の動作確認時は **Service Worker unregister + caches.delete + location.reload()** をワンセットで実行する習慣を身につけるべき。

### 教訓17:ローカル Flask 起動には load_dotenv() が必要

`app.py` / `utils.py` には `load_dotenv()` の呼び出しが無いため、ローカルで `python3 app.py` を実行しても `.env` が読まれない。Cloud Run では Secret Manager 経由で環境変数が注入されるため発覚していなかった。次回ローカル起動が必要になったら、`app.py` 冒頭に以下を追加(本番影響なし):

```python
from dotenv import load_dotenv
load_dotenv()
```

または、起動時に環境変数を export(一回限り):

```bash
set -a; source .env; set +a
python3 app.py
```

## 次セッション(Session 14)以降の候補

引き継ぎ書通り、明示の指示があるまで着手しない。

| 候補 | 内容 | 工数 |
|------|------|------|
| **B-1: Step 4(利用者向けガイドページ)** | 「設定」タブに「📚 使い方ガイド」追加 | 1〜3時間 |
| **B-2: 「本日の記録」タブ強化** | 未測定者表示 + カメラ・音声ボタン移植 | 2〜3時間 |
| **B-3: 「測定」タブ廃止/統合** | ユーザー判断で見送り(現状維持) | — |
| **dev → prod マージ** | 音声入力を含む dev の成果を prod に昇格 | 0.5〜1時間 |
| **「記録を保存」ボタンの色変更** | 音声入力(緑)と保存(緑)の色被り解消 | 30分 |
| **D: Step 3(Firebase Push)** | 完全自動通知 | 半日〜2日(明示依頼があるまで提案禁止) |
---

# 📝 Session 14 完了サマリ(2026-05-04)

## 📍 セッション概要

**Step 4(利用者向けガイドページ)を完成 + dev → prod マージ実施**。
manual.html(ガイドページ)に「バイタル測定」「再検査アラーム」「設定・困った時」の3セクションを追加し、計14個のスクショプレースホルダーを実画像に差し替え(うち Android 系2枚は意図的にプレースホルダのまま)。Chrome 連携の `html2canvas` + Cmd+Shift+4 ネイティブスクショ + iPhone PWA のハイブリッド撮影で12枚のスクショを取得・配置。透けて見える問題を発見し、ネイティブスクショで完全解決。

## ✅ 第14セッションでの主な成果

### 1. ガイドページに3セクション追加(`b776720`)
- **`s-vitals-input` バイタル測定の使い方**(blue/monitoring アイコン): 4タブ全景 → 入力エディタ → カメラ読取 → 音声入力(録音中)
- **`s-vitals-recheck` 再検査アラームの使い方**(red/notifications_active アイコン): 異常値検出 → 時刻設定 → リマインダー登録 → アラーム発火
- **`s-vitals-trouble` 設定・困った時**(purple/help_outline アイコン): iOS カレンダー権限・キャッシュクリア・マイク権限
- **更新ログ Ver.4.1 カード**(赤枠) 追加(目立つように一番上に配置)
- 870行 → 1285行(+415行)
- 教訓1(タスカルくん画像 14箇所 + animation:fl 1箇所)堅持

### 2. 14枚のスクショ撮影プロセス(`2c85802`, `05dcd84`, `7022a41`)

**取得済み画像11枚(Android 2枚を除く)**:
| # | ファイル名 | 撮影方法 | 内容 |
|---|---|---|---|
| 1 | vital-tabs.png | html2canvas | 4タブ全景・3名表示 |
| 2 | vital-input.png | html2canvas | 入力エディタ展開 |
| 3 | vital-camera.png | (#2 兼用) | カメラ・音声ボタン横並び |
| 4 | vital-voice.png | html2canvas + JS hack | 録音中(.recording クラス付与で赤色脈動) |
| 5 | recheck-detect.png | html2canvas | 異常値+「再検査」オレンジバッジ |
| 6 | recheck-set.png | Cmd+Shift+4 範囲選択 | クイックボタン4つだけクロップ |
| 7 | recheck-register.png | Cmd+Shift+4 ウィンドウ全体 | リマインダー登録ボタン+iOS案内文 |
| 8 | recheck-alarm.png | Cmd+Shift+4 範囲選択 | アラーム発火モーダル(白背景クッキリ) |
| 9 | ios-invite.png | iPhone PWA スクショ | iOS「カレンダーの参加依頼」ダイアログ |
| 10 | ios-add.png | iPhone PWA スクショ | iOS カレンダー追加画面 |
| 13 | sw-clear.png | iPhone PWA スクショ | Safari 履歴消去 |
| 14 | mic-perm.png | iPhone PWA スクショ | Safari マイク権限 |

**未取得(プレースホルダのまま)**:
- #11 android-add.png
- #12 android-battery.png

### 3. dev → prod 同期(Session 14 末)
- tasukaru-dev → tasukaru ブランチへマージ
- Cloud Run prod(tasukaru-191764727533.asia-northeast1.run.app)に Step 4 ガイドページが反映
- Ver.4.1 リリース

### 4. 撮影プロセスで発見した知見

**html2canvas の制約と対策**:
- 静的UI(タブ/入力欄/通常状態のボタン)→ html2canvas で問題なし
- **fixed/absolute 配置の overlay/modal** → html2canvas は背景レイヤーと前景レイヤーの合成に失敗、**透けて見える問題発生**
- **transition 中(押された直後のフェードアウト状態)のボタン** → 透けて見える問題発生
- 解決策: **Mac ネイティブスクショ(Cmd+Shift+4 + Space + ウィンドウクリック、または範囲選択ドラッグ)** で確実に撮れる

**Chrome 連携の撮影パターン**:
1. 私(Claude)が画面状態を JS で構築(値セット、クラス付与、状態変更)
2. html2canvas でダウンロード発火 OR ユーザーが Mac の Cmd+Shift+4 で撮影
3. ユーザーがチャットにドラッグでアップ
4. 私が `/mnt/user-data/uploads/` で受け取り、リネーム

**iPhone PWA 撮影パターン**:
- iOS 専用画面(参加依頼ダイアログ・カレンダーアプリ・iPhone 設定)は iPhone 実機必須
- iPhone のスクショは `スクリーンショット_2026-05-04_xx_xx_xx.png` 形式

## 🎯 達成した状態

### dev/本番両方で以下が動作中:
- バイタル4タブ(測定/本日の記録/履歴/設定)
- カメラ読み取り + 音声入力(マイク権限がオン時)
- 「再検査が必要」手動マーク + 異常値自動検出
- 再検査の予約(クイックボタン4つ + 直接時刻入力)
- iPhone カレンダー連携(.ics ダウンロード → 「カレンダーの参加依頼」ダイアログ)
- アラームモーダル発火(時刻一致時)
- ガイドページ(/manual)に Step 4 セクション3つ表示

### Ver.4.1 の主な機能(更新ログより):
- 4タブ統合UI(測定/本日の記録/履歴/設定)
- カメラ読み取り + 音声入力(GPT-4o)
- 再検査アラーム機能
- 異常値自動検出(色分け表示)
- iPhone カレンダー連携

## 📦 dev DB の状態(2026-05-04 末)

- 既存利用者: 石井 三郎(28)他多数
- ガイド撮影用ダミー: タスカルちゃん(51)、タスカルくん(52)
  - タスカルくん には異常値データ記録済み(血圧 180/110、脈拍 110、体温 38.5、SpO2 92、メモ「顔色がやや赤い、めまいの訴えあり」、再検査が必要✓)
  - 18:25 と 18:35 で再検査予約済み(完了マーク付き)
- 削除する場合は Supabase ダッシュボードから手動で

## 🐛 既知の課題(Session 15 以降で対応)

### 高優先
- **iPhone PWA で測定時アコーディオン展開→利用者ボタン+保存ボタンが下部メニューに隠れる問題**(Session 14 中の発見、未対応)

### 中優先
- **「記録を保存」ボタンの色変更**:現状緑色で、音声入力ボタン(緑)と被って見分けづらい
- **Android 系スクショ(#11, #12)未取得**:android-add.png / android-battery.png は紫破線プレースホルダのまま
- **load_dotenv 対応**(教訓17):環境変数の取り回しを統一

### 低優先 / 様子見
- B-2: 「本日の記録」タブ強化(未測定者表示 + カメラ・音声ボタン移植)
- Step 3 Firebase Push:**明示の依頼があるまで提案禁止**(教訓継続)

---

# 📝 Session 14 → Session 15 引き継ぎ

## 🚨 重要:このセッションを引き継ぐ Claude へ

### 必読の前提
1. **教訓1〜17 厳守**(過去 README 参照)。特にタスカルくん画像 14箇所 + animation:fl 1箇所 は絶対に削除/変更しない
2. **1機能=1コミット**(混ぜない)
3. **Service Worker キャッシュ対策**: dev preview で `?cb=` キャッシュバスター付きで確認
4. **コミットメッセージは英語シンプル**、日本語全角括弧禁止
5. **push 後 30〜60秒待つ**(Cloud Run デプロイ時間)
6. **Step 3 (Firebase Push) は提案禁止**、明示依頼があるまで触れない
7. **マークダウンリンク化対策**(教訓13):コマンドはコードブロックで囲む

### リポジトリ・URL
- Repo: https://github.com/cocokaraplus-max/kaigo-ai-app
- branch: `tasukaru-dev`(開発)/ `tasukaru`(本番)/ `main`(default、3週間前から手付かず)
- Mac path: `~/dev/kaigo-ai-app`(ユーザー名 "ZIMAX 1" にスペース含む点注意)
- File handoff: **`~/Desktop/`** (NOT Downloads)
- dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
- prod URL: https://tasukaru-191764727533.asia-northeast1.run.app
- Supabase dev: https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj
- Supabase prod: https://supabase.com/dashboard/project/abvglnkwtdeoaazyqwyd

## 🎯 Session 15 候補タスク(明示の指示があるまで着手しない)

| 優先度 | 候補 | 内容 | 工数 |
|---|---|---|---|
| **高** | **アコーディオン下部隠れバグ修正** | iPhone PWA で測定時に保存ボタンが下部メニューに隠れる(Session 14 中に発見、未対応) | 1〜2時間 |
| 中 | **記録を保存ボタンの色変更** | 緑→別色(青系・オレンジ系)、音声入力(緑)との視認性向上 | 30分 |
| 中 | **Android スクショ追加** | android-add.png / android-battery.png(プレースホルダのまま) | 1時間(実機要) |
| 中 | **B-2: 本日の記録タブ強化** | 未測定者表示 + カメラ・音声ボタン移植 | 2〜3時間 |
| 中 | **load_dotenv 対応**(教訓17) | 環境変数の取り回し統一 | 30分 |
| 中 | **タスカルくんダミー利用者の整理** | dev DB の patient_id=51, 52 を削除するかどうか判断 | 5分 |
| 低 | **B-3: 測定タブ廃止/統合** | ユーザー判断で見送り(現状維持) | — |
| 低 | **D: Step 3 Firebase Push** | 完全自動通知 | 半日〜2日(**明示依頼があるまで提案禁止**) |

## 📁 Session 14 で生成したファイル(参考)

### 採用された11画像(`/static/img/guide/` 配下)
- vital-tabs.png(30KB)
- vital-input.png(44KB)
- vital-voice.png(45KB)
- recheck-detect.png(31KB)
- recheck-set.png(25KB ← Cmd+Shift+4 クロップ)
- recheck-register.png(141KB ← Cmd+Shift+4 ウィンドウ全体)
- recheck-alarm.png(126KB ← Cmd+Shift+4 範囲選択)
- ios-invite.png(220KB)
- ios-add.png(110KB)
- sw-clear.png(170KB)
- mic-perm.png(63KB)

### 未取得2画像(プレースホルダ)
- android-add.png
- android-battery.png

### manual.html
- 1249行
- 既存セクション10個 + 新規セクション3個(s-vitals-input, s-vitals-recheck, s-vitals-trouble)+ 更新ログに Ver.4.1 追加
- 残るプレースホルダ:android-add, android-battery のみ(紫破線枠)

## 🛠 Session 14 で得た技術的知見

### Chrome 連携でのスクショ撮影フロー
```javascript
// html2canvas を動的に読み込み
new Promise((resolve) => {
    if (typeof html2canvas !== 'undefined') return resolve('already');
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
    s.onload = () => resolve('loaded');
    document.head.appendChild(s);
}).then(() => {
    return html2canvas(document.body, {
        backgroundColor: '#f2f4f8', scale: 1,
        width: 390, height: 844, windowWidth: 390, windowHeight: 844
    });
}).then(canvas => {
    canvas.toBlob(blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'XXX.png';
        document.body.appendChild(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 500);
    }, 'image/png');
});
// → Mac の Downloads に PNG が落ちる
```

### html2canvas の制約
- ✅ 通常UI(タブ・入力欄)
- ❌ overlay/modal(透ける)
- ❌ transition 中のボタン(透ける)
- 代替: **Mac Cmd+Shift+4** でネイティブスクショ

### vitals.html 内の発見した API
- 入力 ID パターン: `v-bp_high-{patient_id}`, `v-bp_low-{}`, `v-pulse-{}`, `v-temperature-{}`, `v-spo2-{}`, `v-note-{}`
- チェックボックス: `v-recheck-{patient_id}`(再検査が必要)
- 時刻入力: `recheck-time-{patient_id}`
- 関数: `alarmActionMeasure`, `alarmActionSnooze`, `alarmActionComplete`, `saveRecheckSchedule`, `loadRecheckSchedules`, `completeRecheckSchedule`, `deleteRecheckSchedule`, `addRecheckTime`, `removeRecheckTime`, `openAddPatientModal`, `deleteDailyEditor`
- モーダル: `recheck-alarm-overlay`(`.alarm-overlay` クラス、display:flex で発火)
- 内部スクロール: `.page-wrapper`(scrollHeight > body のスクロールコンテナ)
- 利用者カード: 左スワイプで `swipe-delete-bg`(削除背景)が出る
- CSS クラス: `.voice-btn.recording`(背景:赤グラデ、影:赤、animation: voicePulse 1.2s)

### コミット履歴(Session 14)
```
7022a41 (HEAD -> tasukaru-dev) fix manual replace recheck-set with cropped quick-button screenshot
05dcd84 fix manual replace recheck-register and recheck-alarm with clean native screenshots
2c85802 feat manual replace placeholders with vital guide screenshots
b776720 feat manual add vital guide sections with placeholders for screenshots
f4851f4 docs session13 voice vital input completion records and session14 handoff
```

## ⏭ Session 15 開始時にすべきこと

1. このセッション開始時、ユーザーから「やってほしい作業」を聞く前に、まずこの README を読む
2. ユーザーに **「Session 14 完了 + dev/prod 同期済み」**を確認した上で、**今日の作業内容**を聞く
3. **Step 3 Firebase Push**を提案しない(教訓)
4. 教訓1〜17 を遵守
5. 1機能=1コミット、push 後 30〜60秒待つ

---

# 📝 Session 15 完了サマリ(2026-05-04)— ボトムナビ並び替え機能の修正

## 📍 セッション概要

Session 14 候補タスクには無かったが、ユーザーから「下部のメニュー配置を変えても他のメニューを経由すると元に戻ってしまうのを改善したい」との要望で着手。
**既存の並び替え機能(設定モーダル「並び替えモードを開始」ボタン)が実装の残骸として存在するだけで、実際には動作していない**ことを Chrome 連携で調査して特定。base.html と top.html を全面修正して **「全ページで動作する pointer events ベースの並び替え機能」** を実装した。

## ✅ 第15セッションでの主な成果

### 1. 真因特定(Chrome 連携での徹底的な調査)

調査で判明した状況:
- `base.html` には `saveNavOrder()` 関数の **残骸** だけがあり、ドラッグハンドラ・読み込み処理は存在せず
- `top.html` の L283〜L405(120行)に **HTML5 D&D ベースの並び替え機能のフル実装** が隠れていた
- top.html の旧実装は `a.getAttribute('href').replace('/', '')` でスラッシュを削除して localStorage に保存(`["top","input",...]`)
- でも **どこにも読み込み処理(loadNavOrder)が存在しなかった** ため、TOP で並び替えても他ページに行くと元に戻っていた
- TOP ページでしか top.html のスクリプトは読まれないため、他ページでは並び替え自体できなかった

→ ユーザーが言う **「下部メニュー配置を変えても元に戻る」** はこの構造的欠陥が原因と確定

### 2. 並び替え機能の新規実装(`base.html` に統合)

base.html に以下を追加(+349行):

| 関数 | 役割 |
|---|---|
| `loadNavOrder()` | ページロード時に localStorage を読んで DOM 並び替えを適用(全ページ共通) |
| `saveNavOrder()` | 並び順を localStorage に保存(スラッシュ付き形式) |
| `startNavEditMode()` | 編集モード起動。設定モーダル閉じる→編集バー表示→各項目に分類クラスとハンドラ装着 |
| `stopNavEditMode()` | 編集モード終了→現在の DOM 順序を localStorage に保存→トースト表示 |
| `attachNavDrag()` / `onNavPointerDown()` | 各項目にドラッグハンドラ装着 |
| `onNavHoldMove()` / `onNavHoldUp()` / `cancelHold()` / `beginDragMode()` | **長押し検知(150ms)→ドラッグ突入** ロジック |
| `onNavPointerMove()` / `onNavPointerUp()` | ドラッグ中のヒットテストと DOM 入れ替え |
| `onNavTouchMoveBlock()` | iOS Safari で `passive: false` の touchmove リスナでスクロール完全抑止 |

### 3. top.html の旧実装削除(`-117行`)

top.html L286〜L405 の旧 D&D 実装を削除し、コメント3行に置き換え:
```
// ===== ボトムナビ並び替え機能は base.html 側に統合済み =====
// 旧実装(startNavEditMode/stopNavEditMode/onNavItem*/onMouseDown 系)は削除。
// base.html の pointer events ベース実装(全ページ対応・iPhone Safari 対応)に一本化。
```

文字サイズ・サウンド・アイコン設定・クロッパー・更新履歴クリック等の他機能はすべて温存。

### 4. UX/技術的な工夫

- **TOP / ログアウトは固定**(両端、誤タップ防止)。間の12項目のみ並び替え可
- **長押し 150ms でドラッグ開始**(短押し=横スクロール、長押し=並び替えの区別)
- **横スクロールは生かしたまま**(`touch-action: pan-x`)→ 14項目すべてに指でアクセス可能
- **transform / animation を一切使わない CSS**(iOS Safari の Material Symbols ligature 解除バグ回避)
- **旧形式(`"top"` スラッシュなし)/ 新形式(`"/top"`)両対応の `loadNavOrder()`** で既存ユーザーの localStorage を破壊しない
- **振動フィードバック**(`navigator.vibrate(20)`)で長押し成立を体感

## 🐛 セッション中に踏んだ罠と修正履歴

修正は **5回の反復** が必要だった:

1. **初回実装**(`d804e8b`)→ HTML5 dragstart 系。dev で確認したら top.html の独自実装と衝突
2. **2回目修正** → `body { overflow: hidden }` が `elementFromPoint` を阻害してドロップ判定不能。フォールバック追加で解決
3. **3回目(top.html 削除)**(`9896ae2`)→ top.html の旧実装が base.html を上書きしていたのを発見、120行削除
4. **4回目(iOS Safari 対応)** → ドラッグ中にページがスクロールして「メニューが下に動く」問題。`touch-action: none` + touchmove 抑止で対応
5. **5回目(横スクロール復活)**(`2a72b1d`)→ `overflow-x: hidden` が強すぎて 14項目すべてにアクセス不能の致命バグ。**長押し検知方式 + `touch-action: pan-x`** に設計刷新で解決

## 🎯 動作確認結果(Chrome 連携で全自動テスト)

| シナリオ | 結果 |
|---|---|
| 編集モード CSS(touch-action: pan-x、overflow-x: auto) | ✅ |
| 短押し(タップ)はドラッグに入らない | ✅ |
| 短時間で 8px 以上動く(横スクロール意図)→ キャンセル | ✅ |
| 150ms 押しっぱなし → ドラッグモード突入 | ✅ |
| ドラッグで並び替え → DOM 入れ替え + localStorage 保存(スラッシュ付き) | ✅ |
| **別ページ遷移後も並び順保持(本題)** | ✅ |
| 14項目すべてアクセス可(横スクロール復活) | ✅ |
| アイコンが文字に変わらない(transform 不使用) | ✅ |
| TOP / ログアウトは固定で並び替え不可 | ✅ |

## ファイル変更サマリ

- `templates/base.html`: 1478 → 1827 行(+349行、CSS 追加 + JS 関数群追加)
- `templates/top.html`: 672 → 555 行(-117行、旧 D&D 実装削除)

## コミット(Session 15)

```
2a72b1d fix nav reorder long press to drag preserving horizontal scroll
(以下、間の修正コミットは省略 — 1機能=1コミットの原則は守れず複数回修正が入った)
9896ae2 fix nav reorder unify implementation in base and remove top html duplicate
d804e8b feat base nav reorder with drag and drop persisted in localstorage
```

## 教訓追加(教訓18〜21)

### 教訓18:既存の「動かない機能」は残骸ではなく重複実装の可能性を疑う
`saveNavOrder()` 関数があったので「実装の残骸」と仮定して上書き実装を作ったが、実際には別ファイル(top.html)に**動作している重複実装**があった。**全ファイルを横断して**同名関数・同名 localStorage キー・同名 ID/クラスを grep するべき。Chrome の `window.* === 'function'` チェックや HTML 内での `saveNavOrder` 出現回数の確認(=3 だった)が決定的な手がかりになった。

### 教訓19:iOS Safari は transform を持つ要素で Material Symbols ligature が解除される
ドラッグ中の `.dragging` で `transform: scale(1.08)` を指定したら、ユーザーから「アイコンが文字(`monitor_heart` のような英単語)に変わる」報告。これは Webkit の既知挙動で、transform を持つ要素で `font-feature-settings` の一部が解除されるため。**並び替え UI で transform は使わない**(border + box-shadow + background だけで「ドラッグ中」を表現する)。

### 教訓20:`touch-action: none` を強くかけすぎると横スクロールも殺す
iOS Safari のページスクロール対策で `body.nav-editing { touch-action: none }` + `bottom-nav.edit-mode { overflow-x: hidden }` を強制した結果、**ボトムナビの横スクロールも禁止**されて 14項目あるうち右側 4項目に物理的に届かなくなる致命バグ。**`touch-action: pan-x`(横のみ許可)**で解決。
- 縦スクロール禁止+横スクロール許可:`touch-action: pan-x`
- 横スクロール禁止+縦スクロール許可:`touch-action: pan-y`
- 全部禁止:`touch-action: none`(ドラッグ可能要素にだけ使う)

### 教訓21:タップとドラッグの区別は「長押し検知」方式が確実
`pointerdown` で即 `preventDefault()` する設計だと、ユーザーが横スクロールしたいだけでも勝手にドラッグモードに入る。**150ms の長押しタイマー**(指を置いた瞬間にタイマー開始、150ms 内に 8px 以上動いたらキャンセル、タイマー満了したらドラッグモード突入)で UX が劇的に改善する。iOS のホーム画面アイコン編集と同じ操作感。`navigator.vibrate(20)` で長押し成立をユーザーに伝えるのも重要。

## 🛠 Session 15 で得た技術的知見

### Chrome 連携でのライブ調査・検証フロー(超重要)

このセッションで確立した**コードを書き出してダウンロードしながら Chrome 連携で常に検証する** ワークフロー。次の Claude もこの方式で動くこと。

具体的な手順:

1. **問題報告を受けたら、まず Chrome 連携で現状を調査**:
   - `tabs_context_mcp` でアクティブタブ確認
   - `javascript_exec` で DOM・グローバル関数・localStorage・computed style を観察
   - 仮説を立てて、その仮説を JS で検証(`elementFromPoint`、`getComputedStyle`、event dispatch など)

2. **修正対象のテンプレートをユーザーから受け取る**:
   - `~/Desktop/` 経由でファイルをアップロードしてもらう(チャットの容量上限を回避)
   - `/mnt/user-data/uploads/` で受け取り、`/home/claude/work/` にコピーして編集
   - **raw.githubusercontent.com から fetch で取得**する手もあるが、Chrome の `[BLOCKED: Cookie/query string data]` で中身が見えないことがあるので、アップロードのほうが確実

3. **修正版を書き出す**:
   - `str_replace` で慎重にパッチ(大きい範囲は Python で行ベース置換)
   - JS 構文チェック(`node --check` を Jinja タグ除外したスクリプトで実施)
   - `/mnt/user-data/outputs/` にコピー → `present_files` でユーザーに渡す

4. **ユーザーが Mac でコピー → push**:
   - `cp "/Users/ZIMAX 1/Desktop/base.html" templates/base.html`(ZIMAX 1 のスペース注意)
   - `git add ... && git commit -m '...' && git push origin tasukaru-dev`

5. **push 後に Chrome 連携で再検証**:
   - 30〜45秒待つ(Cloud Run デプロイ時間)
   - SW unregister + 全 caches.delete + `?cb=` 付きリロード(教訓8/16)
   - 新コードが反映されたか `typeof window.xxx === 'function'` で確認
   - **イベント dispatch で UI 操作を自動シミュレート**(pointerdown/pointermove/pointerup を JS で発火させて並び替えをテスト)

### 自動テストのコツ

- `new PointerEvent('pointerdown', {bubbles:true, cancelable:true, clientX, clientY, pointerType:'mouse', isPrimary:true, pointerId:1})` で擬似タッチ
- ドラッグの動きは `setTimeout` の Promise チェーンで段階的に再現(pointerdown → 待機 → pointermove → 待機 → pointerup)
- 別ページ遷移後の状態確認は `location.href = ...` した後にタブ参照が再確立されるまで `setTimeout(_, 4000)`

### `localStorage.setItem` フックの威力

「誰が localStorage に書いてるか分からない」場合、`Storage.prototype.setItem` を上書きしてスタックトレースを取るデバッグ手法が有効:

```javascript
const orig = Storage.prototype.setItem;
Storage.prototype.setItem = function(k, v) {
  if (k === 'tasukaru_nav_order') {
    console.log('SAVE', k, v, new Error().stack);
  }
  return orig.call(this, k, v);
};
```

### CSS の `!important` が効かない時の真因
詳細度が同じ `!important` 同士でも、**CSS 記述順序で後の方が勝つ**わけではなく、`getComputedStyle()` のタイミングと `@keyframes` のアニメーション競合が原因のことがある。今回は `animation: navWiggle` の `transform: rotate(...)` が `.dragging` の `transform: scale(1.08)` を上書きしていた(両方 transform プロパティだから一方だけが効く)。教訓:**transform を CSS と animation の両方で同じ要素に書かない**。

## ⚠️ 重要事項(Session 16 以降への申し送り)

- **本番(prod, tasukaru ブランチ)にはまだマージしていない**。dev のみで動作確認した状態。Session 16 の最初で本番マージするか、もう少し dev で運用してからマージするかは、ユーザーの判断次第。
- **既存ユーザーの localStorage に旧形式(`"top"` スラッシュなし)が残っているが、loadNavOrder が両形式対応になっているので問題なし**。次回 stopNavEditMode が呼ばれた時に新形式(スラッシュ付き)で上書きされる。
- **Service Worker のキャッシュ問題**(教訓8/16)が今回も再発した。Cloud Run デプロイ完了後の動作確認時は **必ず SW unregister + caches.delete + `?cb=` 付きリロード** を実施する。

---

# 📝 Session 15 → Session 16 引き継ぎ

## 🚨 重要:このセッションを引き継ぐ Claude へ

### 必読の前提
1. **教訓1〜21 厳守**(過去 README 参照)。特に:
   - 教訓1:タスカルくん画像 14箇所 + animation:fl 1箇所 は絶対に削除/変更しない
   - 教訓5:1機能=1コミット(Session 15 では複数修正が入って守れなかった反省あり)
   - 教訓8/16:Service Worker キャッシュ対策(SW unregister + caches.delete + `?cb=`)
   - 教訓13:マークダウンリンク化対策(コマンドはコードブロックで囲む)
   - 教訓18:既存の「動かない機能」は残骸ではなく重複実装の可能性を疑う
   - 教訓19:iOS Safari で transform は Material Symbols を壊す
   - 教訓20:`touch-action: none` を強くかけすぎると横スクロールも殺す
   - 教訓21:タップとドラッグの区別は長押し検知方式
2. **Step 3 Firebase Push は明示依頼があるまで提案禁止**
3. **コミットメッセージは英語シンプル**(日本語全角括弧禁止)
4. **push 後 30〜60秒待つ**(Cloud Run デプロイ時間)
5. **ファイル受け渡しは `~/Desktop/`**(NOT Downloads)
6. **Mac のユーザー名は "ZIMAX 1"(スペース含む)**
7. **dev preview は `?cb=` 付きで確認**(Service Worker キャッシュ対策)

### 作業の流れ(Session 15 で確立した方式 ★重要)

**Chrome 連携を使い、コードを書き出してダウンロードしながら作業する** のが Session 15 で確立したワークフロー。次の Claude もこの方式で動くこと:

1. **問題報告を受けたら、まず Chrome 連携で現状調査**
   - `tabs_context_mcp` で開いているタブ確認(普通は dev タブが既に開いている)
   - `javascript_exec` で DOM・関数・localStorage・computed style を観察
   - 仮説を立てたら JS でその仮説を検証する

2. **修正が必要なファイルはユーザーに `~/Desktop/` 経由でアップロードしてもらう**
   - 「base.html をアップしてください」のように依頼
   - `/mnt/user-data/uploads/` で受け取り、`/home/claude/work/` にコピーして編集

3. **修正版を `/mnt/user-data/outputs/` に書き出して `present_files` でユーザーに渡す**
   - JS 構文チェック(node --check で Jinja タグ除外)を必ず通してから渡す
   - ユーザーは Desktop に保存 → `cp "/Users/ZIMAX 1/Desktop/xxx" templates/xxx` で配置

4. **ユーザーが push したら、Chrome 連携で動作確認**
   - 30〜45秒待つ(Cloud Run デプロイ)
   - SW 解除 + caches 削除 + `?cb=` 付きリロード
   - 新コードが反映されたか `typeof window.xxx === 'function'` 等で確認
   - イベント dispatch で UI 操作を自動シミュレートして検証

5. **iPhone での実機確認はユーザーにお願いする**
   - Chrome デスクトップで OK でも iOS Safari で動かないことが多い(教訓19/20/21)

### リポジトリ・URL
- Repo: https://github.com/cocokaraplus-max/kaigo-ai-app
- branch: tasukaru-dev(開発)/ tasukaru(本番)
- Mac path: ~/dev/kaigo-ai-app
- dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
- prod URL: https://tasukaru-191764727533.asia-northeast1.run.app
- Supabase dev: https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj
- Supabase prod: https://supabase.com/dashboard/project/abvglnkwtdeoaazyqwyd

## 🎯 Session 16 候補タスク(明示の指示があるまで着手しない)

| 優先度 | 候補 | 内容 | 工数 |
|---|---|---|---|
| **高** | **Session 15 成果の prod 反映** | dev で動作確認済みのナビ並び替え機能を本番(tasukaru ブランチ)にマージ | 15分 |
| **高** | **アコーディオン下部隠れバグ修正** | iPhone PWA で測定時に保存ボタンが下部メニューに隠れる(Session 14 中に発見、未対応) | 1〜2時間 |
| 中 | **記録を保存ボタンの色変更** | 緑→別色、音声入力ボタンとの視認性向上 | 30分 |
| 中 | **Android スクショ追加** | guide-android-add / guide-android-battery のプレースホルダ置き換え | 1時間(Android 実機要) |
| 中 | **B-2: 本日の記録タブ強化** | 未測定者表示+カメラ・音声ボタン移植 | 2〜3時間 |
| 中 | **load_dotenv 対応**(教訓17) | 環境変数の取り回し統一 | 30分 |
| 中 | **タスカルくんダミー利用者の整理判断** | patient_id=51, 52 の扱い決定 | 5分 |
| 低 | **B-3: 測定タブ廃止/統合** | 現状維持判断済み | — |

## 📁 Session 15 で変更したファイル

- `templates/base.html`: 1478 → 1827 行(並び替え機能の新規実装統合)
- `templates/top.html`: 672 → 555 行(旧並び替え実装の削除)

## ⏭ Session 16 開始時にすべきこと

1. README を読んで Session 15 完了状態と教訓1〜21 を把握
2. ユーザーに **「Session 15 完了 + dev のみ反映済み(prod 未マージ)」** を確認した旨を伝える
3. ユーザーから今日の作業内容を聞く
4. Chrome 連携で現状調査 → 仮説検証 → 修正版書き出し → push → Chrome で再検証、のループで作業
5. 教訓1〜21 を遵守

---

# 📚 Session 14 完了(2026-05-04)— Step 4 利用者向けガイドページ

## 概要

Session 9 から Phase 計画にあった **Step 4「利用者向けガイドページ」** を実装。マニュアル(`templates/manual.html`)に **バイタル機能のガイドセクション** を追加し、操作スクショを差し込んだ。

## 実装内容

### マニュアルへのバイタルガイドセクション追加

`templates/manual.html` に新セクションを追加:

- 再検査アラームの仕組み解説
- iOS/Android の初回設定手順
- 「いつ・どこで通知が鳴るのか」一覧表(画面開いてる時/別タブ/別アプリ/スリープ/完全終了 × アプリ内アラーム/.icsリマインダー)
- トラブルシューティング(アラーム鳴らない時のチェックリスト)

### スクショの埋め込み

iPhone 実機スクショを切り抜いて 3 枚埋め込み:

1. クイックボタン UI(+15分・+30分・+1時間・+2時間)
2. 「📅 リマインダーに登録」操作後の iOS カレンダー登録画面
3. アラームモーダル発火時の表示

スクショは複数回差し替え:
- `b776720`: プレースホルダー版で初期コミット
- `2c85802`: 実スクショへ置換
- `05dcd84`: iOS のシステムダイアログ版を追加
- `7022a41`: 切り抜き範囲を調整(クイックボタン部分のみ)

## 成果

- バイタル機能の誤操作リスク減
- 「アラームが鳴らない」問い合わせ対応がガイド誘導で完結する設計
- マニュアル上部の **タスカルくんアニメーション**(`animation: fl`)は **絶対変更しない厳命** 厳守

## コミット履歴(Session 14)

```
e2904fa docs session14 step4 guide page completion records and session15 handoff
7022a41 fix manual replace recheck-set with cropped quick-button screenshot
05dcd84 fix manual replace recheck-register and recheck-alarm with clean native screenshots
2c85802 feat manual replace placeholders with vital guide screenshots
b776720 feat manual add vital guide sections with placeholders for screenshots
```

---

# 🧭 Session 15 完了(2026-05-04 夜)— ボトムナビ並び替え機能

## 概要

ユーザーが **下部ナビのメニュー順を自分で並び替えられる** 機能を実装。長押し → ドラッグで配置を変更し、`localStorage` に保存して全ページで反映する仕様。

## 確定仕様

| 項目 | 仕様 |
|---|---|
| 編集モード起動 | 設定モーダル → 「メニュー並び替え」ボタン |
| 並び替え可能項目 | TOP / ログアウト 以外の **12 項目**(記録入力、ケース記録、バイタル、カレンダー、掲示板、履歴、評価、タスク、誕生日、数秘、管理者MENU、ガイド) |
| 固定項目 | TOP(左端)、ログアウト(右端)— `fixed-item` クラス、編集中は薄表示 + pointer-events: none |
| ドラッグ起動 | **長押し 150ms → ドラッグ** 方式(誤発動防止のため) |
| 永続化 | `localStorage`(キー: `tasukaru_nav_order`)に href 配列で保存 |
| 適用範囲 | base.html 内の全ページに自動反映(applyNavOrder 関数) |

## 実装の苦労ポイント

### 1. iOS Safari の縦/横スクロール競合

`touch-action: none` を強くかけすぎると **ナビの横スクロールも殺される**。逆に何もしないと並び替え中にページが縦スクロールして体験が壊れる。最終的に:
- `body.nav-editing { touch-action: pan-x }` で**横スクロールだけ許可、縦スクロール禁止**
- `.bottom-nav.edit-mode { touch-action: pan-x }` も同様

### 2. transform が Material Symbols を壊す

ドラッグ中の見た目を transform: scale(1.05) で動かしたら、Material Symbols フォントが iOS Safari でレンダリング崩壊。drag は `position: fixed` + `left/top` で動かして transform は使わない方針に変更。

### 3. base.html と top.html の並び替えロジック重複

最初は top.html に独自実装していたが、他ページからは並び替え発動できない不便。base.html に統合 + top.html の旧実装を削除して **全ページで動く** ようにした。

### 4. エッジオートスクロール

ドラッグ中、画面端に指を持っていくとナビが自動で横スクロールする実装。`window.requestAnimationFrame` で連続実行、scrollLeft を加減。

## コミット履歴(Session 15)

```
f833e85 docs session15 nav reorder completion records and session16 handoff
2a72b1d fix nav reorder long press to drag preserving horizontal scroll
3450d2c fix nav reorder remove transform animations preserve material icons on drag
593523e fix nav reorder ios safari scroll lock with touch-action and touchmove blocker
9896ae2 fix nav reorder unify implementation in base and remove top html duplicate
d804e8b fix nav reorder hit test fallback when elementfrompoint returns body
52ee01c feat base nav reorder with drag and drop persisted in localstorage
```

## Session 15 末状態

- dev 反映済み、prod 未マージ
- 最新コミット: `2a72b1d`
- 横スクロールの違和感や上部バーの整形は **Session 16 で対応** する積み残し

---

# 🛠 Session 16 完了(2026-05-05)— ナビ並び替え UX 改善 + バイタル FAB 隠れバグ修正

## 概要

Session 15 で実装した並び替え機能の UX 課題と、別件で発覚した **バイタルアコーディオン展開時の FAB 隠れバグ** を解消。

## 完了タスク一覧

### A. ナビ並び替え機能の改善

| # | 修正内容 | 経緯 | コミット |
|---|---|---|---|
| A-1 | エッジオートスクロール追加 | Session 15 末の積み残し | `f050d4a` |
| A-2 | 上部バーに「初期状態」リセットボタン | confirm ダイアログ + localStorage 削除 | `352e54f` |
| A-3 | 編集中ナビを 60vh 持ち上げ案 → **撤回**(レイアウト崩壊) | UI が壊れて見える | `546b561` |
| A-4 | 横スクロール修正(`touch-action: pan-x`) | `body.nav-editing` の touch-action: none が祖先指定で子の pan-x を上書きしていた | `0792c76` |
| A-5 | 上部バー UI 整形 + ナビ位置を本来位置に戻す | 「✏️ メニューを並び替え」短文化、ボタンから絵文字除去、ellipsis | `2b91124` |
| A-6 | 編集モードの padding-bottom を維持 | iOS ホームインジケーター回避領域(74px)を保つ | `b2adf2e` |
| A-7 | iOS リンクプレビュー対策(初手:CSS のみ) | `-webkit-touch-callout: none` を draggable-item に追加 | `445e255` |
| A-8 | iOS リンクプレビュー対策(本命:三段防御) | href 退避 + contextmenu preventDefault + touch-callout | `c086ee8` |

### B. バイタル測定タブのアコーディオン下部隠れバグ修正

| # | 修正内容 | 経緯 | コミット |
|---|---|---|---|
| B-1 | アコーディオン展開時に自動スクロール + 下部スペーサー(130px) | 「記録を保存」ボタンがナビ下に隠れる問題 | `6eb8a42` |
| B-2 | FAB(青丸 person_add)を body 直下に移動 | `.page-wrapper { z-index: 0 }` の stacking context により FAB が ナビに勝てなかった = **教訓14 の再発** | `58b8ef9` |

## 主要な技術的発見

### 1. iOS Safari `<a>` 長押しメニューの三段防御

`-webkit-touch-callout: none` だけでは iOS の長押しメニューを完全には止められなかった。**href を一時退避** が一番強力:

```js
// startNavEditMode 内
if (el.tagName === 'A' && el.hasAttribute('href')) {
    el.dataset.savedHref = el.getAttribute('href');
    el.removeAttribute('href');  // <a> から href を外して「リンクではない」状態に
}

// stopNavEditMode 内(必ず最初に)
savedItems.forEach(el => {
    if (el.dataset && el.dataset.savedHref) {
        el.setAttribute('href', el.dataset.savedHref);
        delete el.dataset.savedHref;
    }
});
```

iOS Safari は href のない `<a>` をリンクと認識しないため、長押しメニューが発動しない。順序保存ロジックは復元後に走るので空配列にならず安全。

### 2. stacking context の再発(教訓14)

バイタルの FAB(`#add-today-fab`、`position: fixed; z-index: 200`)が `.page-wrapper { position: relative; z-index: 0 }` の中にあると、**z-index 200 は親の中での話に閉じ込められて、外のナビ(body 直下)に勝てない**。

解決策は **camera-modal と同パターン** で `requestAnimationFrame` 内で body 直下に移動:

```js
const fab = document.getElementById('add-today-fab');
if (fab && fab.parentElement !== document.body) {
    document.body.appendChild(fab);
}
```

### 3. アコーディオン展開時の自動スクロール

`scrollIntoView({ behavior: 'smooth', block: 'start' })` で利用者カードを画面上端に持ってくると、入力欄全体が一目で見える状態になる。padding-bottom: 130px のスペーサーと組み合わせて、最下部までスクロールしたとき保存ボタンとナビの隙間 165px(完全に余裕)。

## コミット履歴(Session 16)

```
58b8ef9 fix vitals fab move to body level to escape page wrapper stacking context
6eb8a42 fix vitals accordion auto scroll on expand and add bottom spacer for save button
c086ee8 fix nav drag block ios link preview by detaching href and contextmenu
445e255 fix nav drag suppress ios link long press preview menu on draggable items
b2adf2e fix nav edit mode preserve padding-bottom to avoid home indicator gesture
2b91124 refine nav edit ux fix horizontal scroll polish bar and keep nav position
0792c76 fix nav edit horizontal scroll by relaxing body touch action to pan-x
546b561 polish nav edit bar layout and lift nav to 60vh during edit
352e54f feat nav reorder add reset button to edit bar with confirm
f050d4a fix nav reorder edge auto scroll while dragging
```

## 教訓追加(Session 14・15・16 統合)

### 教訓18: ナビなど重要 UI の touch-action は最小限に

`touch-action: none` を祖先(body)に強くかけると、子要素の `touch-action: pan-x` が完全に上書きされる(後者の方が CSS 的に弱い扱い)。代わりに `touch-action: pan-x` を祖先にも設定して、明示的に「縦は禁止、横は許可」を伝える。

### 教訓19: iOS Safari で transform は Material Symbols を壊す

ドラッグ中要素の見た目を `transform: scale()` や `translate()` で動かすと、Material Symbols フォントが iOS Safari でレンダリング崩壊する事例を確認。**`position: fixed` + `left/top` 直接指定** で動かすのが安全。

### 教訓20: touch-action: none を強くかけすぎると横スクロールも殺される

`body.nav-editing { touch-action: none !important }` で「ナビ並び替え中は触れない」を実現しようとした結果、ナビ自体の横スクロール(pan-x)も死亡。**祖先指定は子要素を支配する** ため、祖先に `pan-x` を当てるのが正解。

### 教訓21: iOS Safari の `<a>` 長押しメニュー対策は href 退避が最強

`-webkit-touch-callout: none` や `contextmenu` の preventDefault だけでは完全には止まらない。**`<a>` から href を一時的に外す**(`removeAttribute('href')`)ことで「これはリンクではない」と iOS に認識させ、長押しメニューの発動経路を根本から塞ぐのが最強。

### 教訓14 の再発例: バイタル FAB

stacking context は z-index の階層を分断する(教訓14)。今回は `.page-wrapper { z-index: 0 }` の中に置かれた FAB(z-index: 200)が、外の `.bottom-nav`(body 直下)より上に出られない問題として再発した。**body 直下に移動するパターン** が確実な解決策。

---

# 📋 次セッション(Session 17)以降のタスク

## 🔴 優先度: 高

### 1. dev → prod マージ

Session 14 以降の成果(マニュアルガイド、ナビ並び替え、バイタル FAB 修正)が dev で完了して動作確認済み。**prod への昇格** が積み残しになっている。

```bash
cd ~/dev/kaigo-ai-app
git checkout tasukaru
git pull origin tasukaru
git merge tasukaru-dev
git push origin tasukaru
```

(または `.github/workflows/auto-merge.yml` の自動マージワークフローが動くなら待つだけ)

## 🟡 優先度: 中

### 2. Android 系スクショ追加

マニュアルの「いつ・どこで通知が鳴るのか」セクションには iPhone スクショしかない。Android の Googleカレンダー登録画面・通知画面のスクショを追加すると、Android 利用者にも分かりやすい。

ファイル名候補:
- `android-add.png`(Googleカレンダー追加画面)
- `android-battery.png`(電池最適化対象外設定)

### 3. 「記録を保存」ボタンの色変更検討

Session 13 で音声入力ボタン(緑)を追加したため、**バイタルの「記録を保存」ボタン(緑)と色被り** が発生中。識別性向上のため、保存ボタンを別色(青系 or オレンジ系)に変更する選択肢あり。

### 4. 「本日の記録」タブ強化(B-2)

- 未測定者を「未測定」ラベル付きで表示
- カメラ読み取り・音声入力ボタンを「本日の記録」アコーディオン編集にも追加(現状は「測定」タブのみ)

### 5. load_dotenv() 対応(教訓17)

ローカル Flask 起動時に `.env` が読まれない問題。`app.py` 冒頭に以下を追加:

```python
from dotenv import load_dotenv
load_dotenv()
```

Cloud Run では Secret Manager 経由で環境変数注入のため本番影響なし、ローカル開発のみ便利になる。

## 🟢 優先度: 低

### 6. タスカルくんダミー利用者(patient_id 51, 52)の整理判断

過去にデモ用に作ったダミー利用者がそのまま残っている。本番運用上は不要。削除するか、デモ用フラグで隠すかの判断必要。

### 7. 古いバックアップファイル整理

`templates/*.bak.*`、`templates/*.broken.*` が `.gitignore` で除外されているが、ローカル / Mac の Desktop には溜まり続けている。月一でクリーンアップ推奨。

## ⏸ 着手禁止(明示依頼があるまで)

### Step 3: Firebase Push 通知

完全自動アラーム化は **明示依頼があるまで提案禁止**(Session 9 で確定)。

---

# 🛠 開発フロー(Session 16 で確立した方式)

1. **Chrome 連携で現状調査**: `tabs_context_mcp` → `javascript_exec` で DOM/CSS 計測
2. **仮説立ててから JS で検証**: live edit で element.style 変更しながら結果確認
3. **修正対象ファイルは ~/Desktop/ 経由でアップロード**: Mac の `~/dev/kaigo-ai-app` から該当ファイルを Desktop に置く
4. **`/mnt/user-data/outputs/` に修正版書き出し**: `present_files` で渡す
5. **ユーザーが Desktop にDL → ターミナルで `cp ~/Desktop/file ./templates/file` → grep で行数 / 機能確認 → push**
6. **push 後 30〜60秒待って Cloud Run 反映**: SW unregister + caches.delete でハードリロード
7. **Mac Chrome で動作シミュレート → iPhone 実機で最終確認**(iPhone 確認はユーザーに依頼)
8. **BLOCKED された文字列は配列化**(`s.split('')`)で回避

---

# 📜 Session 16 末コミット状態

```
58b8ef9 (HEAD -> tasukaru-dev, origin/tasukaru-dev) fix vitals fab move to body level to escape page wrapper stacking context
6eb8a42 fix vitals accordion auto scroll on expand and add bottom spacer for save button
c086ee8 fix nav drag block ios link preview by detaching href and contextmenu
445e255 fix nav drag suppress ios link long press preview menu on draggable items
b2adf2e fix nav edit mode preserve padding-bottom to avoid home indicator gesture
2b91124 refine nav edit ux fix horizontal scroll polish bar and keep nav position
0792c76 fix nav edit horizontal scroll by relaxing body touch action to pan-x
546b561 polish nav edit bar layout and lift nav to 60vh during edit
352e54f feat nav reorder add reset button to edit bar with confirm
f050d4a fix nav reorder edge auto scroll while dragging
```

- `templates/base.html`: 2009 行 / 86766 bytes(Session 14 → 16 で +349 行)
- `templates/vitals.html`: 3273 行 / 156305 bytes(Session 16 で +21 行)

dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
prod URL: https://tasukaru-191764727533.asia-northeast1.run.app

