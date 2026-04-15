# TASUKARU 開発記録 🦝

## プロジェクト概要
- **アプリ名**：TASUKARU（タスカル）
- **目的**：介護現場の記録業務をAIで自動化
- **技術スタック**：Python/Flask, Supabase(PostgreSQL), Gemini AI, Cloud Run
- **本番URL**：https://tasukaru-191764727533.asia-northeast1.run.app
- **開発URL**：https://tasukaru-dev-191764727533.asia-northeast1.run.app
- **GCPプロジェクト**：tasukaru-production（PROJECT_NUMBER: 191764727533）
- **Supabaseプロジェクト**：abvglnkwtdeoaazyqwyd（ap-northeast-1）
- **施設コード**：cocokaraplus-5526

---

## 開発ルール（必ず守ること）

1. `patients.id`は**bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は`--update-env-vars`のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて**IIFE**で囲む
4. `await`を使う関数には**`async`**を必ずつける
5. 全関数を`window.xxx`で公開する
6. `onclick`ではなく**`addEventListener`**を使う（iPhone対応）
7. Jinja2データ（PATIENTS等）は**IIFEの外**で定義する
8. 開発は`cloudrun-dev`で行い、確認後に`cloudrun`にマージ
9. sw.jsを修正したら**CACHE_VERSION**を上げる（現在v4）
10. カメラモーダルは**body直下**に移動する
11. **ZIPで書き出し**か**Pythonスクリプト**で修正を指示する
12. TOPページの自動更新関数（checkNewRecords等）は**IIFEの内側**に定義する（※重要：外に定義するとSPA遷移時にエラー）
13. モーダル・ドロワーを開くときは**ボトムナビを非表示**にする（`hideBottomNav()`/`showBottomNav()`）
14. `fetch`でPOSTする場合は`X-Requested-With: XMLHttpRequest`ヘッダーを付け、サーバーはJSONで返す

---

## ブランチ運用

```
cloudrun-dev  → 開発・確認用（tasukaru-dev）
cloudrun      → 本番用（tasukaru）
```

### デプロイコマンド

```bash
# 開発版
git add . && git commit -m "変更内容" && git push origin cloudrun-dev
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --platform managed --allow-unauthenticated

# 本番同期（.DS_Storeエラーが出たらgit stashを先に）
git stash && git checkout cloudrun && git merge cloudrun-dev && git push origin cloudrun
gcloud run deploy tasukaru --source . --region asia-northeast1 --platform managed --allow-unauthenticated && git checkout cloudrun-dev && git stash pop
```

---

## 環境変数（重要）

| キー | 説明 | 注意 |
|------|------|------|
| `SECRET_KEY` | Flaskセッション暗号化キー | **絶対に変えない**・変えるとログアウトされる |
| `SUPABASE_URL` | SupabaseプロジェクトURL | |
| `SUPABASE_KEY` | Supabase anon key | |
| `GEMINI_API_KEY` | Gemini AI APIキー | |
| `SENDGRID_API_KEY` | メール送信APIキー | |
| `SENDGRID_FROM_EMAIL` | 送信元メールアドレス | |
| `DEV_PASSWORD` | 開発者MENUパスワード | デフォルト:tasukaru-dev-2024 |

### SECRET_KEY固定コマンド（初回のみ）
```bash
gcloud run services update tasukaru-dev \
  --update-env-vars SECRET_KEY=tasukaru-fixed-2024-cocokaraplus \
  --region asia-northeast1

gcloud run services update tasukaru \
  --update-env-vars SECRET_KEY=tasukaru-fixed-2024-cocokaraplus \
  --region asia-northeast1
```

---

## パスワード管理

| 種類 | 場所 | 形式 |
|------|------|------|
| スタッフ | staffs.password_hash | SHA-256 |
| 施設管理者 | facilities.admin_password | 平文 |
| 管理者MENU | admin_settings key='admin_password' | 平文（デフォルト:8888）|
| 開発者MENU | 環境変数DEV_PASSWORD | 平文（デフォルト:tasukaru-dev-2024）|

---

## Supabaseテーブル（重要）

- `patients.id`は**bigint型**（外部キーはTEXT型）
- `staffs`に`icon_emoji`, `icon_image_url`カラムあり
- `patient_visit_days`に`ampm`カラムあり
- `chat_messages`は`supabase_realtime` publicationに登録済み
- `assessments`テーブルに`audio_url`カラムあり（音声保存用）
- Storageバケット：`case-photos`（写真）、`assessment-audio`（評価音声）
- `records`テーブルに**`record_date`カラムは存在しない**（insertに含めるとエラー）
- `admin_settings`の`board_editors`キー：掲示板編集権限を持つ職員名のJSON配列

### 取説（manual.html）使用画像
```
tasukaru_top.png       → 通常・笑顔
tasukaru_sestumei.png  → 説明
tasukaru_odoroki2.png  → 驚き
tasukaru_onegai.png    → お願い
tasukaru_ooyorokobi.png → 大喜び
```

```sql
board_posts      -- 投稿本体（is_privateカラムあり）
board_comments   -- コメント
board_reactions  -- リアクション（✅👍など）
board_reads      -- 既読管理
```

---

## ファイル構成

```
kaigo-ai-app/
├── app.py（Flask メイン・全ルーティング・全API 約3200行）
├── utils.py（Gemini AI・Supabase画像/音声アップロード）
├── templates/
│   ├── base.html（SPAルーター・ボトムナビ・PWA・アプリロック画面）
│   ├── board.html（掲示板ページ・Realtime対応・権限制御済み）
│   ├── admin.html（管理者MENU・掲示板編集権限設定UI追加済み）
│   ├── manual.html（取説 Ver.3.0）
│   ├── top.html（歯車ボタン・ユーザー設定・パスコードロック・履歴自動更新）
│   ├── input.html（記録入力・fetch JSON対応・長文保存対応）
│   ├── chat_room.html（Realtime対応・送信音付き）
│   ├── chat_rooms.html（試聴ボタン付きサウンド設定）
│   ├── assessment.html（録音モードCSS・音声保存再生）
│   ├── vitals.html（cameraStream重複修正・全員ボタン修正済み）
│   └── login.html（お名前入力欄追加済み）
└── static/
    └── sw.js（PWA Service Worker v4・バッジAPI対応）
```

---

## 完了した全作業

### ✅ 2026-04-15 大規模バグ修正・機能追加セッション

#### 記録入力（input.html / app.py）
- **長文保存エラーを修正**：fetchでPOSTするとサーバーの302リダイレクトを失敗と判定していた
  - `X-Requested-With: XMLHttpRequest`ヘッダーを追加
  - サーバー側をJSON応答に変更（`{"status":"success","redirect":"/daily_view?..."}`）
- `created_at`を常に現在日時に固定（記録日付を別途`record_date`に入れるとエラーになるため）
- `records`テーブルに存在しない`record_date`カラムへのinsertを削除

#### TOPページ（top.html）
- **更新履歴の自動更新**：10秒ポーリングで差分チェック→自動リフレッシュ
- **履歴クリック**：`bindHistoryClicks()`関数化し自動更新後も再バインド
- **重要な修正**：`checkNewRecords`をIIFEの**内側**に正しく配置（外に出すと`<script>`タグが二重になりJS全体が壊れる）
- **パスコードロック機能追加**（歯車 → アプリロック）
  - 4桁パスコード設定・ローカルストレージに保存
  - アプリ起動・バックグラウンドから復帰時にロック画面表示
  - 生体認証（Face ID）はWebブラウザでは正しく実装できないため廃止（PWAでホーム画面追加するとiOSがFace IDを自動適用）
- 設定モーダル・アイコンモーダル開閉時にボトムナビを非表示

#### 掲示板（board.html / app.py）
- **Realtime改善**：DELETE投稿も検知・自動リロード
- **コメントドロワー**：開閉時にボトムナビを非表示（アイコンフワフワ問題解消）
- **投稿モーダル**：開閉時にボトムナビを非表示
- **コメント数バッジ**：コメントを開いたら即消去（querySelectorAllで全一致）
- **未読バッジ（ボトムナビ）**：掲示板SPA遷移時に即クリア（navigateTo内に追加）
- **掲示板編集・削除権限の設計変更**：
  - 旧：`is_admin`（管理者フラグ）または自分の投稿
  - 新：**自分の投稿** OR **管理者MENUで権限付与された職員**のみ
  - `admin_settings`テーブルの`board_editors`キーにJSON配列で管理
  - `/api/board/set_editors` APIを新規追加
  - `admin.html`のスタッフ管理タブにペンアイコンのトグルを追加

#### ベース（base.html）
- **アプリロック画面**追加：テンキーUIでパスコード入力
- **ボトムナビのz-index問題**：モーダル開閉時に`display:none`で制御（z-index調整は副作用が多いため廃止）

#### ログイン永続化（app.py）
- `session.permanent = True`（365日間セッション維持）
- `PERMANENT_SESSION_LIFETIME = timedelta(days=365)`
- `SESSION_COOKIE_SECURE = True`
- **SECRET_KEYを環境変数で固定**（これをしないとデプロイごとにログアウトされる）

### ✅ 2026-04-15（以前）更新履歴バグ修正
- TOPページ更新履歴ソートを`id`降順に変更
- Supabase Realtimeによるトーク即時受信
- 評価ページに音声保存・再生機能
- TOPページにユーザー設定（歯車ボタン）
- トーク送信音追加・サウンド試聴ボタン
- バイタル画面の複数バグ修正
- カメラボタンSPA遷移バグ修正
- 通知許可ポップアップ（base.html）
- 取説（manual.html）Ver.3.0 リニューアル
- 掲示板機能追加（board.html）

---

## PENDING（未完了・次回対応）

### 🔴 最優先
- [ ] 本番（cloudrun）の`SECRET_KEY`固定（`gcloud run services update tasukaru --update-env-vars SECRET_KEY=tasukaru-fixed-2024-cocokaraplus --region asia-northeast1`）

### 🟡 機能追加
- [ ] 掲示板の`is_private`投稿をapp.pyでフィルタリング（メンション外の人に非表示）
- [ ] メニュー並び順カスタマイズ（ユーザー設定から）
- [ ] アップデートログ表示（TOPの歯車横にベルアイコン）

### 🟢 軽微
- [ ] 「たすかる」音声（mp3ファイルが必要）
- [ ] 利用者の曜日設定を現場で登録・確認
- [ ] サウンドテストページの削除（/sound_test）
- [ ] デバッグ用エラー詳細表示を元に戻す（app.pyのexcept節）

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| `cd: kaigo-ai-app: No such file or directory` | すでにkaigo-ai-appにいる | そのまま実行 |
| `error: Your local changes would be overwritten` | .DS_Storeが変更されている | `git stash`してから実行 |
| `INVALID_ARGUMENT` デプロイエラー | 認証切れ | `gcloud auth login`で再認証 |
| 履歴が0件になる | SELECTに存在しないカラムを指定 | カラム名を確認して削除 |
| 記録が保存されない | insertに存在しないカラムを指定 | `record_date`等をinsertから削除 |
| ターミナルが止まる | ヒアドキュメント`<< 'EOF'`が入力待ち | `Ctrl+C`で抜ける |
| Python -cコマンドが文字化け | 日本語コメントがUTF-8エラー | 日本語コメントなしのスクリプトファイルを使う |
| スクリプトファイルが開けない | パスにスペース（`ZIMAX 1`） | `~/Downloads/`に置いて`python3 ~/Downloads/xxx.py`で実行 |
| デプロイ後にログアウトされる | SECRET_KEYが未固定 | `gcloud run services update`で固定する |
| モーダルの下にナビが見える | ボトムナビのz-index問題 | モーダル開閉時に`hideBottomNav()`/`showBottomNav()`を呼ぶ |
| 保存ボタンを押しても失敗する | fetchのリダイレクト判定ミス | `X-Requested-With`ヘッダーを追加・サーバーをJSON返却に変更 |

---

## gcloud CLIとは

```
あなたのMac
    ↓ gcloud run deploy
Google Cloud（インターネット上のサーバー）
    ↓
Cloud Run（TASUKARUが動いている場所）
    ↓
https://tasukaru-...run.app
```

---

*最終更新：2026-04-15（大規模バグ修正・掲示板権限・パスコードロック・ログイン永続化）*
