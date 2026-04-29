# TASUKARU介護AIアプリ 開発引き継ぎ(2026-04-29 第3セッション末)

## 📍 現在の状況サマリ

掲示板に**JS構文エラー**が混入し、復旧のため `git checkout ed87a9c` でロールバック済み。
現在は **commit `39d1a01` (rollback to ed87a9c)** が dev に push されており、**掲示板は動作中**。

その後、`base.html` のみに**「掲示板ページではポーリング停止」**の修正を1ファイル限定で実施・push 済み(動作確認済み)。
ただしこれは消極的な対策。**「TOPに戻るとバッジ復活」問題が残存**。

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
