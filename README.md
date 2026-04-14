# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-12 23:10

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |

---

## 🛠️ 技術スタック

| 種類 | 内容 |
|------|------|
| 言語 / FW | Python / Flask |
| テンプレート | Jinja2 |
| アイコン | Material Symbols (Google Fonts) |
| データベース | Supabase (PostgreSQL) |
| AI エンジン | Google Gemini 2.5 Flash |
| インフラ | Cloud Run (asia-northeast1) |
| コンテナ | Docker / gunicorn |

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・ルーティング・API |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `templates/base.html` | 共通レイアウト・SPAルーター |
| `templates/login.html` | ログイン画面 |
| `templates/register.html` | 施設新規登録画面 |
| `templates/top.html` | TOP画面 |
| `templates/input.html` | 記録入力・音声AI文章化 |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー |
| `templates/history.html` | モニタリング生成 |
| `templates/assessment.html` | 評価・AI報告書生成 |
| `templates/admin.html` | 管理者MENU |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（LINE風） |
| `templates/chat_room.html` | トーク個別チャット |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL） |
| `static/admin.js` | 管理者MENU用JS |
| `static/logo.png` | TASUKARUロゴ |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 本番 (Streamlit) | https://tasukaru-39.web.app |
| Cloud Run | https://tasukaru-191764727533.asia-northeast1.run.app |
| 登録ページ | https://tasukaru-191764727533.asia-northeast1.run.app/register |

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD        ← 開発者MENUのパスワード（未設定時: tasukaru-dev-2024）
```

⚠️ 環境変数を更新する際は必ず `--update-env-vars` を使用（`--set-env-vars` は既存変数が消えるので禁止）

```bash
gcloud run services update tasukaru \
  --region asia-northeast1 \
  --update-env-vars KEY="value"
```

---

## 🚀 デプロイ手順

```bash
# 1. README更新 → commit → Cloud Runデプロイ を一発で実行
python update_readme.py

# 手動でデプロイのみ実行したい場合
gcloud run deploy tasukaru \
  --source . \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated
```

---

## 📝 直近の変更履歴

- feat: バイタル機能追加（カメラ自動読み取り・アラート・再検査通知・曜日別表示・履歴閲覧） (2026-04-12)
- fix: asyncキーワード抜けによりトーク右上ボタン等が動かない問題を修正 (2026-04-12)
- fix: 管理者MENUから退出ボタンが効かない問題修正・adminLogout関数をadmin.jsに追加 (2026-04-12)
- fix: ボタンラベル「管理者終了」→「管理者MENUから退出」に変更 (2026-04-12)
- feat: Claude閲覧許可を管理者MENUから開発者MENUへ移動 (2026-04-12)
- feat: 管理者MENUと開発者MENUを分離・横並び選択UI・施設一覧/環境変数/アクティビティログ (2026-04-12)
- feat: 数秘ページをLP・B・D・S・P・M・IT・LL全8項目対応に全面刷新・TASUKARUオリジナル表現 (2026-04-12)
- fix: 数秘ページ500エラー修正（all_persons→patients変数名不一致） (2026-04-12)
- fix: SPA遷移でconst/let重複宣言エラー全8件修正・全ページスクリプトをIIFEで囲む (2026-04-12)
- fix: ケース記録カレンダー白問題を根本修正・rAF2重で描画後に初期化 (2026-04-12)
- feat: 評価の音声ファイル解析に独り言/対話モード選択を追加 (2026-04-12)
- feat: 評価メニュー追加・個別機能訓練月次評価報告書のAI自動生成・PC/スマホ対応・印刷/PDF出力 (2026-04-12)
- feat: トーク機能をLINE風に全面刷新・1:1/グループ作成・職員アイコン・既読人数表示 (2026-04-12)
- fix: ケース記録カレンダーがSPA遷移時に白くなるバグを修正・initCalendar即時実行に変更 (2026-04-12)
- feat: カレンダーに記録のある日付のドット表示を追加・/api/record_datesエンドポイント追加 (2026-04-12)

---

## 🔄 今回のcommitで変更したファイル

- `app.py` - 管理者/開発者MENU分離・評価機能・数秘ルート修正・Claude閲覧許可API
- `templates/admin.html` - 管理者/開発者選択UI・Claude閲覧許可を開発者MENUへ移動・退出ボタン修正
- `templates/dev_menu.html` - 新規追加：開発者MENU（施設一覧・環境変数・アクティビティ・Claude閲覧許可）
- `templates/numerology.html` - 全8項目対応に全面刷新
- `templates/assessment.html` - 新規追加：評価入力・AI報告書生成・独り言/対話モード選択
- `templates/chat_rooms.html` - asyncキーワード修正
- `templates/chat_room.html` - asyncキーワード修正
- `templates/base.html` - ボトムナビに「評価」追加・SPA修正（IIFE・rAF）
- `templates/daily_view.html` - カレンダー白問題修正・記録ドット表示
- `static/admin.js` - adminLogout関数追加
- `chat_tables.sql` - トーク用テーブル（要実行済み）
- `assessment_tables.sql` - 評価用テーブル（要実行済み）

---

## 🚀 Claudeへの引き継ぎメモ

新しい会話を始めるときはこのREADME.mdを貼り付けてください。
以下のファイルも一緒に共有すると素早く再開できます：
- `app.py`
- `utils.py`
- 修正したテンプレートHTML

## 🗂️ ブランチ構成

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版・本番稼働中 |
| `develop` | mainの裏操作・修正用 |
| `cloudrun` | Flask版・開発中 ← 現在作業中 |
# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-12 23:30

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |

---

## 🛠️ 技術スタック

| 種類 | 内容 |
|------|------|
| 言語 / FW | Python / Flask |
| テンプレート | Jinja2 |
| アイコン | Material Symbols (Google Fonts) |
| データベース | Supabase (PostgreSQL) |
| AI エンジン | Google Gemini 2.5 Flash |
| インフラ | Cloud Run (asia-northeast1) |
| コンテナ | Docker / gunicorn |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| Cloud Run（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 登録ページ | https://tasukaru-191764727533.asia-northeast1.run.app/register |
| 開発者MENU | https://tasukaru-191764727533.asia-northeast1.run.app/dev |

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL          ← SupabaseのProject URL
SUPABASE_KEY          ← SupabaseのAPI Key
GEMINI_API_KEY        ← Google AI StudioのAPIキー
SECRET_KEY            ← Flaskセッション暗号化キー
SENDGRID_API_KEY      ← SendGridのAPIキー
SENDGRID_FROM_EMAIL   ← 送信元メールアドレス
DEV_PASSWORD          ← 開発者MENUのパスワード（未設定時: tasukaru-dev-2024）
```

### ⚠️ 環境変数更新の注意
必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

```bash
gcloud run services update tasukaru \
  --region asia-northeast1 \
  --update-env-vars KEY="value"
```

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ |
| `templates/login.html` | ログイン画面 |
| `templates/register.html` | 施設新規登録画面 |
| `templates/top.html` | TOP画面 |
| `templates/input.html` | 記録入力・音声AI文章化 |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー |
| `templates/history.html` | モニタリング生成 |
| `templates/assessment.html` | 評価・AI報告書生成（PC/スマホ対応） |
| `templates/vitals.html` | バイタル記録（カメラ読み取り・アラート） |
| `templates/admin.html` | 管理者MENU |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（LINE風） |
| `templates/chat_room.html` | トーク個別チャット |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL 全8項目） |
| `static/admin.js` | 管理者MENU用JS |
| `static/logo.png` | TASUKARUロゴ |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 内容 | 作成済み |
|---------|------|---------|
| `facilities` | 施設情報 | ✅ |
| `staffs` | スタッフ情報・パスワードハッシュ | ✅ |
| `patients` | 利用者情報（id は bigint型） | ✅ |
| `records` | ケース記録 | ✅ |
| `admin_settings` | 管理者パスワード・設定 | ✅ |
| `chat_rooms` | トークルーム | ✅ |
| `chat_members` | トークメンバー・既読管理 | ✅ |
| `chat_messages` | トークメッセージ | ✅ |
| `invite_tokens` | スタッフ招待トークン | ✅ |
| `claude_sessions` | Claude閲覧許可トークン | ✅ |
| `blocked_devices` | ブロックスタッフ管理 | ✅ |
| `assessments` | 評価・AI報告書 | ✅ |
| `vitals` | バイタル記録 | ✅ |
| `vital_alert_settings` | バイタルアラート設定 | ✅ |
| `patient_visit_days` | 利用者の利用曜日 | ✅ |

### ⚠️ 重要：patients.id は bigint型
他のテーブルからの patient_id は UUID型と不一致になるため TEXT型で持つ

---

## 🚀 デプロイ手順

```bash
cd kaigo-ai-app
git add .
git commit -m "変更内容の説明"
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated
```

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ 施設登録・スタッフログイン・パスワードリセット（SendGrid）
- ✅ 招待リンク・QRコードによるスタッフ追加
- ✅ 記録入力（音声入力→AI文章化・写真アップロード）
- ✅ ケース記録閲覧（カレンダー付き・記録ドット表示）
- ✅ AI日誌生成・再生成
- ✅ モニタリング生成（AI）

### トーク（LINE風）
- ✅ ルーム一覧・1:1 / グループ作成
- ✅ 職員アイコン（イニシャル＋カラー自動割り当て）
- ✅ 既読人数表示（LINE仕様）
- ✅ グループメンバードロワー

### 評価
- ✅ 利用者選択・対象月設定
- ✅ PC：PDFや音声ファイルをドロップ→AI自動入力（独り言/対話モード選択）
- ✅ スマホ：音声入力・録音ファイルアップロード
- ✅ AI報告書自動生成（個別機能訓練による変化・課題と要因）
- ✅ 報告書プレビュー・編集・印刷/PDF保存

### バイタル ← 本日追加
- ✅ カメラで血圧計・体温計・パルスオキシメーターを撮影→Geminiが数値自動読み取り
- ✅ 血圧（上・下）・脈拍・体温・SpO2 を記録
- ✅ 設定値を超えると赤くアラート表示・再検査フラグ
- ✅ アラート発生時にグループトークへ自動通知
- ✅ 利用曜日設定・曜日タブで利用者を絞り込み表示
- ✅ 臨時来所の手動追加
- ✅ その日の全員バイタル一覧確認
- ✅ 利用者ごとの過去バイタル履歴閲覧（最大60件）
- ✅ アラート値・通知設定を施設ごとに変更可能

### 数秘
- ✅ LP・B・D・S・P・M・IT・LL 全8項目計算
- ✅ 名前（ヘボン式ローマ字）からD/S/P/M/IT/LLを計算
- ✅ タップで詳細パネル表示（TASUKARUオリジナル表現）
- ✅ 利用者・スタッフ両方を検索して表示

### 管理者MENU / 開発者MENU
- ✅ ログイン時に管理者/開発者を横並びボタンで選択
- ✅ 管理者MENU：利用者管理・スタッフ管理・パスワード変更・招待QR
- ✅ 開発者MENU：施設一覧・環境変数チェック・アクティビティログ・Claude閲覧許可

---

## 🏗️ アーキテクチャの重要ポイント

### SPA（シングルページアプリケーション）
- ボトムナビのページ遷移はSPAで動作（base.htmlのnavigateTo関数）
- SPAで注入されるscriptは **IIFE** で囲む → const/let の重複宣言防止
- カレンダーの初期化は **rAFを2重** にして描画後に実行
- `/admin` など一部ページはSPA非対応（通常遷移）

### スクリプトの重要ルール
```javascript
// ✅ 正しい書き方
(function(){
    window.myFunc = async function() {  // asyncを忘れずに
        const res = await fetch(...);
    };
})();
```

### パスワードハッシュ
SHA-256でハッシュ化。ログインはstaffs.password_hashまたはfacilities.admin_passwordと照合

---

## 📝 本日（2026-04-12）の変更履歴

- feat: バイタル機能追加（カメラ自動読み取り・アラート・再検査通知・曜日別表示・履歴） (2026-04-12)
- fix: 記録入力の利用者選択タップ修正・ひらがな/カタカナ検索対応 (2026-04-12)
- fix: ボトムナビを水色背景（#dbeafe）に変更 (2026-04-12)
- fix: asyncキーワード抜けによりトーク右上ボタン等が動かない問題を全修正 (2026-04-12)
- fix: 管理者MENUから退出ボタンが効かない問題修正・adminLogout関数追加 (2026-04-12)
- feat: Claude閲覧許可を管理者MENUから開発者MENUへ移動 (2026-04-12)
- feat: 管理者MENUと開発者MENUを分離・横並び選択UI (2026-04-12)
- feat: 数秘ページ全8項目対応に全面刷新・TASUKARUオリジナル表現 (2026-04-12)
- fix: SPA遷移でconst/let重複宣言エラー全8件修正・IIFEで囲む (2026-04-12)
- fix: ケース記録カレンダー白問題を根本修正（rAF2重） (2026-04-12)
- feat: 評価の音声ファイル解析に独り言/対話モード選択を追加 (2026-04-12)
- feat: 評価メニュー追加・AI報告書自動生成・PC/スマホ対応・印刷/PDF (2026-04-12)
- feat: トーク機能をLINE風に全面刷新・1:1/グループ・アイコン・既読 (2026-04-12)

---

## 🚀 Claudeへの引き継ぎメモ

### 新しい会話を始めるときは
1. このREADME.mdをClaudeに貼り付ける
2. 作業するファイルも一緒に貼ると素早く再開できる
   - 修正対象のHTMLテンプレート
   - app.py（ルート追加・修正時）

### 特に重要な注意事項
1. `patients.id` は **bigint型**（UUID型ではない）→外部キーはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は既存変数が消える）
3. スクリプトはすべて **IIFE `(function(){...})();`** で囲む
4. `async/await` を使う関数には **`async`** を必ずつける
5. カレンダー初期化は **`requestAnimationFrame(() => requestAnimationFrame(init))`** で行う
6. onclick属性でのインライン関数呼び出しではなく **addEventListener** を使う（iPhone対応）

---

## 🗂️ ブランチ構成

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版） |
| `develop` | 予備 |
| `cloudrun` | Flask版・現在の本番 ← **ここで作業** |
# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-12 23:30

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |

---

## 🛠️ 技術スタック

| 種類 | 内容 |
|------|------|
| 言語 / FW | Python / Flask |
| テンプレート | Jinja2 |
| アイコン | Material Symbols (Google Fonts) |
| データベース | Supabase (PostgreSQL) |
| AI エンジン | Google Gemini 2.5 Flash |
| インフラ | Cloud Run (asia-northeast1) |
| コンテナ | Docker / gunicorn |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| Cloud Run（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 登録ページ | https://tasukaru-191764727533.asia-northeast1.run.app/register |
| 開発者MENU | https://tasukaru-191764727533.asia-northeast1.run.app/dev |

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL          ← SupabaseのProject URL
SUPABASE_KEY          ← SupabaseのAPI Key
GEMINI_API_KEY        ← Google AI StudioのAPIキー
SECRET_KEY            ← Flaskセッション暗号化キー
SENDGRID_API_KEY      ← SendGridのAPIキー
SENDGRID_FROM_EMAIL   ← 送信元メールアドレス
DEV_PASSWORD          ← 開発者MENUのパスワード（未設定時: tasukaru-dev-2024）
```

### ⚠️ 環境変数更新の注意
必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

```bash
gcloud run services update tasukaru \
  --region asia-northeast1 \
  --update-env-vars KEY="value"
```

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ |
| `templates/login.html` | ログイン画面 |
| `templates/register.html` | 施設新規登録画面 |
| `templates/top.html` | TOP画面 |
| `templates/input.html` | 記録入力・音声AI文章化 |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー |
| `templates/history.html` | モニタリング生成 |
| `templates/assessment.html` | 評価・AI報告書生成（PC/スマホ対応） |
| `templates/vitals.html` | バイタル記録（カメラ読み取り・アラート） |
| `templates/admin.html` | 管理者MENU |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（LINE風） |
| `templates/chat_room.html` | トーク個別チャット |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL 全8項目） |
| `static/admin.js` | 管理者MENU用JS |
| `static/logo.png` | TASUKARUロゴ |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 内容 | 作成済み |
|---------|------|---------|
| `facilities` | 施設情報 | ✅ |
| `staffs` | スタッフ情報・パスワードハッシュ | ✅ |
| `patients` | 利用者情報（id は bigint型） | ✅ |
| `records` | ケース記録 | ✅ |
| `admin_settings` | 管理者パスワード・設定 | ✅ |
| `chat_rooms` | トークルーム | ✅ |
| `chat_members` | トークメンバー・既読管理 | ✅ |
| `chat_messages` | トークメッセージ | ✅ |
| `invite_tokens` | スタッフ招待トークン | ✅ |
| `claude_sessions` | Claude閲覧許可トークン | ✅ |
| `blocked_devices` | ブロックスタッフ管理 | ✅ |
| `assessments` | 評価・AI報告書 | ✅ |
| `vitals` | バイタル記録 | ✅ |
| `vital_alert_settings` | バイタルアラート設定 | ✅ |
| `patient_visit_days` | 利用者の利用曜日 | ✅ |

### ⚠️ 重要：patients.id は bigint型
他のテーブルからの patient_id は UUID型と不一致になるため TEXT型で持つ

---

## 🚀 デプロイ手順

```bash
cd kaigo-ai-app
git add .
git commit -m "変更内容の説明"
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated
```

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ 施設登録・スタッフログイン・パスワードリセット（SendGrid）
- ✅ 招待リンク・QRコードによるスタッフ追加
- ✅ 記録入力（音声入力→AI文章化・写真アップロード）
- ✅ ケース記録閲覧（カレンダー付き・記録ドット表示）
- ✅ AI日誌生成・再生成
- ✅ モニタリング生成（AI）

### トーク（LINE風）
- ✅ ルーム一覧・1:1 / グループ作成
- ✅ 職員アイコン（イニシャル＋カラー自動割り当て）
- ✅ 既読人数表示（LINE仕様）
- ✅ グループメンバードロワー

### 評価
- ✅ 利用者選択・対象月設定
- ✅ PC：PDFや音声ファイルをドロップ→AI自動入力（独り言/対話モード選択）
- ✅ スマホ：音声入力・録音ファイルアップロード
- ✅ AI報告書自動生成（個別機能訓練による変化・課題と要因）
- ✅ 報告書プレビュー・編集・印刷/PDF保存

### バイタル ← 本日追加
- ✅ カメラで血圧計・体温計・パルスオキシメーターを撮影→Geminiが数値自動読み取り
- ✅ 血圧（上・下）・脈拍・体温・SpO2 を記録
- ✅ 設定値を超えると赤くアラート表示・再検査フラグ
- ✅ アラート発生時にグループトークへ自動通知
- ✅ 利用曜日設定・曜日タブで利用者を絞り込み表示
- ✅ 臨時来所の手動追加
- ✅ その日の全員バイタル一覧確認
- ✅ 利用者ごとの過去バイタル履歴閲覧（最大60件）
- ✅ アラート値・通知設定を施設ごとに変更可能

### 数秘
- ✅ LP・B・D・S・P・M・IT・LL 全8項目計算
- ✅ 名前（ヘボン式ローマ字）からD/S/P/M/IT/LLを計算
- ✅ タップで詳細パネル表示（TASUKARUオリジナル表現）
- ✅ 利用者・スタッフ両方を検索して表示

### 管理者MENU / 開発者MENU
- ✅ ログイン時に管理者/開発者を横並びボタンで選択
- ✅ 管理者MENU：利用者管理・スタッフ管理・パスワード変更・招待QR
- ✅ 開発者MENU：施設一覧・環境変数チェック・アクティビティログ・Claude閲覧許可

---

## 🏗️ アーキテクチャの重要ポイント

### SPA（シングルページアプリケーション）
- ボトムナビのページ遷移はSPAで動作（base.htmlのnavigateTo関数）
- SPAで注入されるscriptは **IIFE** で囲む → const/let の重複宣言防止
- カレンダーの初期化は **rAFを2重** にして描画後に実行
- `/admin` など一部ページはSPA非対応（通常遷移）

### スクリプトの重要ルール
```javascript
// ✅ 正しい書き方
(function(){
    window.myFunc = async function() {  // asyncを忘れずに
        const res = await fetch(...);
    };
})();
```

### パスワードハッシュ
SHA-256でハッシュ化。ログインはstaffs.password_hashまたはfacilities.admin_passwordと照合

---

## 📝 本日（2026-04-12）の変更履歴

- feat: バイタル機能追加（カメラ自動読み取り・アラート・再検査通知・曜日別表示・履歴） (2026-04-12)
- fix: 記録入力の利用者選択タップ修正・ひらがな/カタカナ検索対応 (2026-04-12)
- fix: ボトムナビを水色背景（#dbeafe）に変更 (2026-04-12)
- fix: asyncキーワード抜けによりトーク右上ボタン等が動かない問題を全修正 (2026-04-12)
- fix: 管理者MENUから退出ボタンが効かない問題修正・adminLogout関数追加 (2026-04-12)
- feat: Claude閲覧許可を管理者MENUから開発者MENUへ移動 (2026-04-12)
- feat: 管理者MENUと開発者MENUを分離・横並び選択UI (2026-04-12)
- feat: 数秘ページ全8項目対応に全面刷新・TASUKARUオリジナル表現 (2026-04-12)
- fix: SPA遷移でconst/let重複宣言エラー全8件修正・IIFEで囲む (2026-04-12)
- fix: ケース記録カレンダー白問題を根本修正（rAF2重） (2026-04-12)
- feat: 評価の音声ファイル解析に独り言/対話モード選択を追加 (2026-04-12)
- feat: 評価メニュー追加・AI報告書自動生成・PC/スマホ対応・印刷/PDF (2026-04-12)
- feat: トーク機能をLINE風に全面刷新・1:1/グループ・アイコン・既読 (2026-04-12)

---

## 🚀 Claudeへの引き継ぎメモ

### 新しい会話を始めるときは
1. このREADME.mdをClaudeに貼り付ける
2. 作業するファイルも一緒に貼ると素早く再開できる
   - 修正対象のHTMLテンプレート
   - app.py（ルート追加・修正時）

### 特に重要な注意事項
1. `patients.id` は **bigint型**（UUID型ではない）→外部キーはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は既存変数が消える）
3. スクリプトはすべて **IIFE `(function(){...})();`** で囲む
4. `async/await` を使う関数には **`async`** を必ずつける
5. カレンダー初期化は **`requestAnimationFrame(() => requestAnimationFrame(init))`** で行う
6. onclick属性でのインライン関数呼び出しではなく **addEventListener** を使う（iPhone対応）

---

## 🗂️ ブランチ構成

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版） |
| `develop` | 予備 |
| `cloudrun` | Flask版・現在の本番 ← **ここで作業** |
# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-13 10:00

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |

---

## 🛠️ 技術スタック

| 種類 | 内容 |
|------|------|
| 言語 / FW | Python / Flask |
| テンプレート | Jinja2 |
| アイコン | Material Symbols (Google Fonts) |
| データベース | Supabase (PostgreSQL) |
| AI エンジン | Google Gemini 2.5 Flash |
| インフラ | Cloud Run (asia-northeast1) |
| コンテナ | Docker / gunicorn |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 現場（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発確認用 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 開発者MENU | /dev |

---

## 🗂️ ブランチ構成・開発フロー

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版） |
| `develop` | mainの開発用 |
| `cloudrun` | Flask版・**現場本番** ← 触らない |
| `cloudrun-dev` | Flask版・**開発改善用** ← ここで作業 |

```
cloudrun-dev で開発・修正
        ↓ 動作確認OK
cloudrun にマージ → gcloud run deploy → 現場反映
```

### cloudrunへのマージコマンド
```bash
git checkout cloudrun
git merge cloudrun-dev
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated
```

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD        ← 開発者MENUのパスワード
```

### ⚠️ 環境変数更新の注意
必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

```bash
gcloud run services update tasukaru \
  --region asia-northeast1 \
  --update-env-vars KEY="value"
```

### tasukaru-devへの環境変数コピー（初回のみ）
```bash
gcloud run services describe tasukaru \
  --region asia-northeast1 --format="json" \
  | python3 -c "
import json,sys,subprocess
data=json.load(sys.stdin)
envs=data['spec']['template']['spec']['containers'][0]['env']
env_str=','.join([f\"{e['name']}={e['value']}\" for e in envs if 'value' in e])
subprocess.run(f'gcloud run services update tasukaru-dev --region asia-northeast1 --update-env-vars \"{env_str}\"',shell=True)
"
```

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ |
| `templates/login.html` | ログイン画面 |
| `templates/register.html` | 施設新規登録画面 |
| `templates/top.html` | TOP画面 |
| `templates/input.html` | 記録入力・音声AI文章化 |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー |
| `templates/history.html` | モニタリング生成 |
| `templates/assessment.html` | 評価・AI報告書生成 |
| `templates/vitals.html` | バイタル記録（カメラ読み取り・アラート） |
| `templates/calendar.html` | カレンダー（プライベート/共有・招待） |
| `templates/admin.html` | 管理者MENU |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（LINE風） |
| `templates/chat_room.html` | トーク個別チャット |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL 全8項目） |
| `static/admin.js` | 管理者MENU用JS |
| `backup_usb.sh` | USBバックアップスクリプト |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 内容 |
|---------|------|
| `facilities` | 施設情報 |
| `staffs` | スタッフ情報・パスワードハッシュ |
| `patients` | 利用者情報（**id は bigint型**） |
| `records` | ケース記録 |
| `admin_settings` | 管理者設定 |
| `chat_rooms` | トークルーム |
| `chat_members` | トークメンバー・既読管理 |
| `chat_messages` | トークメッセージ |
| `invite_tokens` | スタッフ招待トークン |
| `claude_sessions` | Claude閲覧許可トークン |
| `blocked_devices` | ブロックスタッフ管理 |
| `assessments` | 評価・AI報告書 |
| `vitals` | バイタル記録 |
| `vital_alert_settings` | バイタルアラート設定（recheck_times含む） |
| `patient_visit_days` | 利用者の利用曜日 |
| `temp_vital_patients` | 臨時バイタル利用者 |
| `calendars` | カレンダー（プライベート/共有） |
| `calendar_events` | カレンダー予定 |
| `calendar_members` | カレンダー招待メンバー |
| `staff_calendar_settings` | 職員カラー設定 |

### ⚠️ patients.id は bigint型
外部キーはTEXT型で持つ（UUID型と不一致のため）

---

## 🚀 デプロイ手順

```bash
cd kaigo-ai-app
git add .
git commit -m "変更内容の説明"
git push origin cloudrun-dev
gcloud run deploy tasukaru-dev \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated
```

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ 施設登録・スタッフログイン・パスワードリセット（SendGrid）
- ✅ 招待リンク・QRコードによるスタッフ追加
- ✅ 記録入力（音声→AI文章化・写真アップロード）
- ✅ ケース記録閲覧（カレンダー付き・記録ドット表示）
- ✅ AI日誌生成・モニタリング生成（AI）

### トーク（LINE風）
- ✅ ルーム一覧・1:1 / グループ作成・職員アイコン・既読表示

### 評価
- ✅ AI報告書自動生成・ファイルドロップ・音声入力・印刷/PDF

### バイタル
- ✅ カメラで機器を撮影→Geminiが数値自動読み取り
- ✅ 血圧（上・下）・脈拍・体温・SpO2
- ✅ アラート表示・再検査フラグ・グループトーク通知
- ✅ 再検査通知を1日複数時刻で設定可能（最大5件）
- ✅ 利用曜日設定・曜日タブ絞り込み・臨時来所追加
- ✅ 臨時追加で既存利用者も検索可能
- ✅ 同名の過去バイタルがある場合「同一人物ですか？」で紐づけ
- ✅ 全員バイタル一覧・利用者ごとの過去履歴

### カレンダー
- ✅ TimeTree風の複数カレンダー管理
- ✅ プライベート（自分だけ）/ 共有（招待メンバーのみ）
- ✅ カレンダーチップで単独/全体表示切り替え
- ✅ 月表示 / 週表示 切り替え
- ✅ シール機能（🎂📋👥🏥など24種類）
- ✅ 繰り返し設定（毎日・毎週・毎月・毎年）
- ✅ 通知設定（10分前〜1日前）
- ✅ メンバー招待・削除
- ✅ 12色から色選択

### 数秘・管理者MENU・開発者MENU
- ✅ 数秘全8項目（LP/B/D/S/P/M/IT/LL）
- ✅ 管理者/開発者MENU分離・横並び選択

---

## 🏗️ アーキテクチャの重要ポイント

### SPA
- ボトムナビはSPAで動作（base.htmlのnavigateTo関数）
- SPAで注入するscriptは **IIFE `(function(){...})();`** で囲む
- カレンダー初期化は **rAFを2重** にして描画後に実行
- `/admin` `/history` `/input` `/daily_view` などはSPA非対応（通常遷移）

### スクリプトの重要ルール
```javascript
(function(){
    // awaitを使う関数には必ずasyncをつける！
    window.myFunc = async function() { const res = await fetch(...); };
    // onclickではなくaddEventListenerを使う（iPhone対応）
    el.addEventListener('touchend', e => { e.preventDefault(); myFunc(); });
})();
```

### ボトムナビ
- アクティブ項目：アイコン＋文字ごと水色ブロック（`#dbeafe`）
- 非アクティブ：白背景・グレー文字
- 区切り：縦線 `border-right: 0.5px solid #e0e0e0`

---

## 📝 変更履歴（2026-04-13）

- fix: モニタリング利用者検索が動かない問題修正（window.公開・addEventListener対応） (2026-04-13)
- feat: カレンダーをプライベート/共有対応・メンバー招待機能追加 (2026-04-13)
- feat: カレンダー機能追加（TimeTree風・複数カレンダー・シール・繰り返し） (2026-04-13)
- feat: バイタル臨時追加で既存利用者検索対応・同名紐づけ確認 (2026-04-13)
- feat: 再検査通知を1日複数時刻で設定可能に（最大5件） (2026-04-13)
- feat: cloudrun-devブランチ作成・tasukaru-devサービス設定 (2026-04-13)

## 📝 変更履歴（2026-04-12）

- feat: バイタル機能追加（カメラ自動読み取り・アラート・再検査通知・曜日別） (2026-04-12)
- feat: ボトムナビをブロック選択スタイルに変更 (2026-04-12)
- fix: input.html toggleRecording・aiTranscribeのasync抜けを修正 (2026-04-12)
- fix: asyncキーワード抜けによりトーク右上ボタン等が動かない問題を全修正 (2026-04-12)
- fix: 管理者MENUから退出ボタン修正・adminLogout関数追加 (2026-04-12)
- feat: Claude閲覧許可を開発者MENUへ移動 (2026-04-12)
- feat: 管理者MENUと開発者MENUを分離・横並び選択UI (2026-04-12)
- feat: 数秘ページ全8項目対応・TASUKARUオリジナル表現 (2026-04-12)
- fix: SPA遷移でconst/let重複宣言エラー修正・IIFEで囲む (2026-04-12)
- feat: 評価メニュー追加・AI報告書生成 (2026-04-12)
- feat: トーク機能をLINE風に全面刷新 (2026-04-12)

---

## 🚀 Claudeへの引き継ぎメモ

### 新しい会話を始めるときは
1. このREADME.mdをClaudeに貼り付ける
2. 作業するファイルも一緒に貼ると素早く再開できる

### 特に重要な注意事項
1. `patients.id` は **bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて **IIFE** で囲む
4. `await`を使う関数には **`async`** を必ずつける
5. onclickではなく **`addEventListener`** を使う（iPhone対応）
6. 関数はすべて **`window.xxx = function`** で公開する
7. 開発は **`cloudrun-dev`** で行い、確認後に `cloudrun` にマージ
# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-13 13:00

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 現場（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発確認用 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 開発者MENU | /dev |

---

## 🗂️ ブランチ構成・開発フロー

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版） |
| `develop` | mainの開発用 |
| `cloudrun` | Flask版・**現場本番** ← 触らない |
| `cloudrun-dev` | Flask版・**開発改善用** ← ここで作業 |

```
cloudrun-dev で開発・修正
        ↓ 動作確認OK
cloudrun にマージ → gcloud run deploy → 現場反映
```

### cloudrunへのマージコマンド
```bash
git checkout cloudrun
git merge cloudrun-dev
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated && \
git checkout cloudrun-dev
```

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD        ← 開発者MENUのパスワード
```

### ⚠️ 環境変数更新の注意
必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

### tasukaru-devへの環境変数コピー（初回のみ）
```bash
gcloud run services describe tasukaru \
  --region asia-northeast1 --format="json" \
  | python3 -c "
import json,sys,subprocess
data=json.load(sys.stdin)
envs=data['spec']['template']['spec']['containers'][0]['env']
env_str=','.join([f\"{e['name']}={e['value']}\" for e in envs if 'value' in e])
subprocess.run(f'gcloud run services update tasukaru-dev --region asia-northeast1 --update-env-vars \"{env_str}\"',shell=True)
"
```

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ・PWA・通知 |
| `templates/login.html` | ログイン画面（目のマーク付き） |
| `templates/register.html` | 施設新規登録画面 |
| `templates/top.html` | TOP画面・更新履歴 |
| `templates/input.html` | 記録入力・音声AI文章化 |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー・編集・削除 |
| `templates/history.html` | モニタリング生成 |
| `templates/assessment.html` | 評価・AI報告書生成 |
| `templates/vitals.html` | バイタル記録（カメラ読み取り・アラート・臨時追加） |
| `templates/calendar.html` | カレンダー（プライベート/共有・シール・招待） |
| `templates/manual.html` | 使い方ガイド（SVGイラスト付き） |
| `templates/admin.html` | 管理者MENU |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（検索・歯車サウンド設定） |
| `templates/chat_room.html` | トーク個別チャット |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL 全8項目） |
| `static/admin.js` | 管理者MENU用JS |
| `static/sw.js` | PWA Service Worker |
| `static/manifest.json` | PWAマニフェスト |
| `backup_usb.sh` | USBバックアップスクリプト |
| `setup_auto_backup.sh` | 自動バックアップ設定スクリプト |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 内容 |
|---------|------|
| `facilities` | 施設情報（admin_password は平文） |
| `staffs` | スタッフ情報・パスワードハッシュ（SHA-256） |
| `patients` | 利用者情報（**id は bigint型**） |
| `records` | ケース記録 |
| `admin_settings` | 管理者設定（admin_passwordもここに保存） |
| `chat_rooms` | トークルーム |
| `chat_members` | トークメンバー・既読管理（last_read_at） |
| `chat_messages` | トークメッセージ |
| `invite_tokens` | スタッフ招待トークン |
| `claude_sessions` | Claude閲覧許可トークン |
| `blocked_devices` | ブロックスタッフ管理 |
| `assessments` | 評価・AI報告書 |
| `vitals` | バイタル記録 |
| `vital_alert_settings` | バイタルアラート設定（recheck_times含む） |
| `patient_visit_days` | 利用者の利用曜日 |
| `temp_vital_patients` | 臨時バイタル利用者 |
| `calendars` | カレンダー（is_private/is_shared） |
| `calendar_events` | カレンダー予定 |
| `calendar_members` | カレンダー招待メンバー |
| `staff_calendar_settings` | 職員カラー設定 |

### ⚠️ patients.id は bigint型
外部キーはTEXT型で持つ（UUID型と不一致のため）

### パスワード管理
| 種類 | 保存場所 | 形式 |
|------|---------|------|
| スタッフのパスワード | `staffs.password_hash` | SHA-256ハッシュ |
| 施設管理者パスワード | `facilities.admin_password` | 平文 |
| 管理者MENUパスワード | `admin_settings` key='admin_password' | 平文（デフォルト:8888） |
| 開発者MENUパスワード | Cloud Run環境変数 `DEV_PASSWORD` | 平文（デフォルト:tasukaru-dev-2024） |

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ 施設登録・スタッフログイン（目のマーク付き）・パスワードリセット（SendGrid）
- ✅ 招待リンク・QRコードによるスタッフ追加
- ✅ 記録入力（音声→AI文章化・写真アップロード）
- ✅ ケース記録閲覧（カレンダー付き・記録ドット表示）
- ✅ 記録の編集・削除（自分の記録か管理者のみ・削除確認アラート）
- ✅ AI日誌生成・モニタリング生成（AI）

### トーク（LINE風）
- ✅ ルーム一覧・1:1 / グループ作成・職員アイコン・既読表示
- ✅ 検索窓（トーク名・メッセージで絞り込み）
- ✅ 歯車ボタンからサウンド設定（個人設定・端末ごとに保存）
- ✅ 未読バッジ（ボトムナビに赤い数字・30秒ごと自動更新）
- ✅ 通知サウンド5種類：🔔ポップ・🎵チャイム・📯ピコン・🦝タスカル・🔕なし

### 評価
- ✅ AI報告書自動生成・ファイルドロップ・音声入力・印刷/PDF

### バイタル
- ✅ カメラで機器を撮影→Geminiが数値自動読み取り
- ✅ 血圧（上・下）・脈拍・体温・SpO2
- ✅ アラート表示・再検査フラグ・グループトーク自動通知
- ✅ 再検査通知を1日複数時刻で設定可能（最大5件）
- ✅ 利用曜日設定・曜日タブ絞り込み
- ✅ 臨時追加で既存利用者も検索可能
- ✅ 同名の過去バイタルがある場合「同一人物ですか？」で紐づけ
- ✅ 全員バイタル一覧・利用者ごとの過去履歴

### カレンダー
- ✅ TimeTree風の複数カレンダー管理
- ✅ プライベート（自分だけ）/ 共有（招待メンバーのみ）
- ✅ カレンダーチップで単独/全体表示切り替え・月/週表示
- ✅ シール機能（24種類）・繰り返し設定・通知設定
- ✅ メンバー招待・削除

### 数秘・管理者MENU・開発者MENU
- ✅ 数秘全8項目（LP/B/D/S/P/M/IT/LL）
- ✅ 管理者/開発者MENU分離・横並び選択

### 使い方ガイド
- ✅ `/manual` でアクセス（ボトムナビ「ガイド」）
- ✅ SVGイラスト付き・全12機能の説明
- ✅ 新機能追加時はmanual.htmlにセクション追加するだけ

### PWA・オフライン対応
- ✅ Service Worker（sw.js）でオフラインキャッシュ
- ✅ ホーム画面に追加してアプリっぽく使える
- ✅ オフライン時はオレンジバナー表示
- ✅ 災害時モード（オフライン記録→ネット復旧後自動同期）
- ✅ 利用者情報をIndexedDBにキャッシュ（事前に一度オンラインで開く必要あり）

---

## 🏗️ アーキテクチャの重要ポイント

### SPA
- ボトムナビはSPAで動作（base.htmlのnavigateTo関数）
- SPAで注入するscriptは **IIFE `(function(){...})();`** で囲む
- カレンダー初期化は **rAFを2重** にして描画後に実行
- `/admin` `/history` `/input` `/daily_view` などはSPA非対応（通常遷移）

### スクリプトの重要ルール
```javascript
(function(){
    // awaitを使う関数には必ずasyncをつける！
    window.myFunc = async function() { const res = await fetch(...); };
    // 全関数をwindow.に公開する
    window.otherFunc = function() { ... };
    // onclickではなくaddEventListenerを使う（iPhone対応）
    el.addEventListener('touchend', e => { e.preventDefault(); myFunc(); });
})();
```

### ボトムナビ構成（左から順）
TOP → 記録入力 → ケース記録 → バイタル → カレンダー → モニタリング → 評価 → トーク → 誕生日 → 数秘 → ガイド → ログアウト

### 通知サウンド
- localStorageの`tasukaru_sound`キーに保存（端末ごとの個人設定）
- トークの歯車ボタンから設定（管理者MENUからは削除済み）
- base.htmlの`playNotificationSound()`関数で再生

---

## 📝 変更履歴（2026-04-13）

- feat: 管理者MENUからサウンド設定削除（トーク歯車に統合） (2026-04-13)
- feat: トークに検索窓・歯車ボタンでサウンド設定追加 (2026-04-13)
- feat: 使い方ガイド追加（/manual・SVGイラスト・全12機能） (2026-04-13)
- feat: トーク未読バッジ・通知サウンド5種類（タスカル音声含む） (2026-04-13)
- feat: PWA対応・オフラインキャッシュ・災害時モード (2026-04-13)
- fix: 更新履歴→ケース記録遷移修正・削除警告強化・削除権限チェック (2026-04-13)
- feat: カレンダーをプライベート/共有対応・メンバー招待機能 (2026-04-13)
- feat: カレンダー機能追加（TimeTree風・シール・繰り返し） (2026-04-13)
- feat: バイタル臨時追加で既存利用者検索・紐づけ・複数時刻通知 (2026-04-13)
- fix: モニタリング利用者検索修正（window公開・addEventListener） (2026-04-13)
- feat: パスワード入力欄に目のマーク追加 (2026-04-13)
- feat: cloudrun-devブランチ・tasukaru-devサービス設定完了 (2026-04-13)

## 📝 変更履歴（2026-04-12）

- feat: バイタル機能追加・ボトムナビブロック選択スタイル (2026-04-12)
- fix: input.html asyncキーワード抜け修正 (2026-04-12)
- fix: asyncキーワード抜けによる全ボタン不動作修正 (2026-04-12)
- fix: 管理者MENUから退出ボタン修正 (2026-04-12)
- feat: Claude閲覧許可を開発者MENUへ移動 (2026-04-12)
- feat: 管理者/開発者MENU分離 (2026-04-12)
- feat: 数秘ページ全8項目対応 (2026-04-12)
- feat: 評価メニュー・AI報告書生成 (2026-04-12)
- feat: トーク機能LINE風全面刷新 (2026-04-12)

---

## 🚀 Claudeへの引き継ぎメモ

### 新しい会話を始めるときは
1. このREADME.mdをClaudeに貼り付ける
2. 作業するファイルも一緒に貼ると素早く再開できる

### 特に重要な注意事項
1. `patients.id` は **bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて **IIFE** で囲む
4. `await`を使う関数には **`async`** を必ずつける
5. 全関数を **`window.xxx = function`** で公開する
6. onclickではなく **`addEventListener`** を使う（iPhone対応）
7. 開発は **`cloudrun-dev`** で行い、確認後に `cloudrun` にマージ
8. デプロイ後は必ず **`git checkout cloudrun-dev`** に戻る
# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-13 14:00

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 現場（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発確認用 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 開発者MENU | /dev |

---

## 🗂️ ブランチ構成・開発フロー

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版） |
| `develop` | mainの開発用 |
| `cloudrun` | Flask版・**現場本番** ← 触らない |
| `cloudrun-dev` | Flask版・**開発改善用** ← ここで作業 |

```
cloudrun-dev で開発・修正
        ↓ 動作確認OK
cloudrun にマージ → gcloud run deploy → 現場反映
```

### cloudrunへのマージコマンド（デプロイ後cloudrun-devに戻る）
```bash
git checkout cloudrun
git merge cloudrun-dev
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated && \
git checkout cloudrun-dev
```

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD        ← 開発者MENUのパスワード
```

### ⚠️ 環境変数更新の注意
必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

### tasukaru-devへの環境変数コピー（初回のみ）
```bash
gcloud run services describe tasukaru \
  --region asia-northeast1 --format="json" \
  | python3 -c "
import json,sys,subprocess
data=json.load(sys.stdin)
envs=data['spec']['template']['spec']['containers'][0]['env']
env_str=','.join([f\"{e['name']}={e['value']}\" for e in envs if 'value' in e])
subprocess.run(f'gcloud run services update tasukaru-dev --region asia-northeast1 --update-env-vars \"{env_str}\"',shell=True)
"
```

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API（約2500行） |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `backup_usb.sh` | USBバックアップスクリプト（HIRO'sUSB対応） |
| `setup_auto_backup.sh` | 自動バックアップ設定スクリプト |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ・PWA・通知サウンド・未読バッジ |
| `templates/login.html` | ログイン画面（目のマーク付き） |
| `templates/top.html` | TOP画面・更新履歴（addEventListener対応） |
| `templates/input.html` | 記録入力・音声AI・保存トースト・フォームクリア |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー・編集・削除（権限チェック） |
| `templates/history.html` | モニタリング生成（window公開済み） |
| `templates/assessment.html` | 評価・AI報告書生成 |
| `templates/vitals.html` | バイタル記録（カメラ読み取り・臨時追加・複数時刻通知） |
| `templates/calendar.html` | カレンダー（プライベート/共有・シール・招待） |
| `templates/manual.html` | 使い方ガイド（SVGイラスト付き・12機能） |
| `templates/admin.html` | 管理者MENU（サウンド設定は削除済み） |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（検索窓・歯車サウンド設定） |
| `templates/chat_room.html` | トーク個別チャット |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL 全8項目） |
| `templates/new_password.html` | パスワードリセット（目のマーク付き） |
| `static/admin.js` | 管理者MENU用JS |
| `static/sw.js` | PWA Service Worker（v2・POST非介入） |
| `static/manifest.json` | PWAマニフェスト |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 内容 |
|---------|------|
| `facilities` | 施設情報（admin_password は平文・expires_atに有効期限） |
| `staffs` | スタッフ情報・password_hash（SHA-256）・icon_emoji |
| `patients` | 利用者情報（**id は bigint型**） |
| `records` | ケース記録 |
| `admin_settings` | 管理者設定（key='admin_password'で管理者MENUパスワード） |
| `chat_rooms` | トークルーム |
| `chat_members` | トークメンバー・既読管理（last_read_at） |
| `chat_messages` | トークメッセージ |
| `invite_tokens` | スタッフ招待トークン |
| `claude_sessions` | Claude閲覧許可トークン |
| `blocked_devices` | ブロックスタッフ管理 |
| `assessments` | 評価・AI報告書 |
| `vitals` | バイタル記録 |
| `vital_alert_settings` | バイタルアラート設定（recheck_times: カンマ区切り複数時刻） |
| `patient_visit_days` | 利用者の利用曜日 |
| `temp_vital_patients` | 臨時バイタル利用者 |
| `calendars` | カレンダー（is_private/is_shared/owner_name） |
| `calendar_events` | カレンダー予定 |
| `calendar_members` | カレンダー招待メンバー |
| `staff_calendar_settings` | 職員カラー設定 |

### ⚠️ 重要事項
- `patients.id` は **bigint型** → 外部キーはTEXT型で持つ
- `staffs`テーブルに`icon_emoji`カラムが必要（なければALTER TABLE追加）
- `facilities.expires_at` は定期的に延長が必要（現在2027-04-13に設定済み）

### パスワード管理
| 種類 | 保存場所 | 形式 |
|------|---------|------|
| スタッフのパスワード | `staffs.password_hash` | SHA-256ハッシュ |
| 施設管理者パスワード | `facilities.admin_password` | 平文 |
| 管理者MENUパスワード | `admin_settings` key='admin_password' | 平文（デフォルト: 8888） |
| 開発者MENUパスワード | Cloud Run環境変数 `DEV_PASSWORD` | 平文（デフォルト: tasukaru-dev-2024） |

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ 施設登録・スタッフログイン（目のマーク付き）・パスワードリセット（SendGrid）
- ✅ 招待リンク・QRコードによるスタッフ追加
- ✅ 記録入力（音声→AI文章化・写真・保存完了トースト・フォーム自動クリア）
- ✅ ケース記録閲覧（カレンダー付き・記録ドット表示）
- ✅ 記録の編集・削除（自分の記録か管理者のみ・削除確認アラート）
- ✅ AI日誌生成・モニタリング生成（AI）

### トーク（LINE風）
- ✅ ルーム一覧・1:1 / グループ作成・職員アイコン・既読表示
- ✅ 検索窓（トーク名・メッセージで絞り込み）
- ✅ 歯車ボタンからサウンド設定（個人設定・localStorage保存）
- ✅ 未読バッジ（ボトムナビに赤い数字・30秒ごと自動更新）
- ✅ 通知サウンド5種類：🔔ポップ・🎵チャイム・📯ピコン・🦝タスカル・🔕なし

### 評価
- ✅ AI報告書自動生成・ファイルドロップ・音声入力・印刷/PDF

### バイタル
- ✅ カメラで機器を撮影→Geminiが数値自動読み取り
- ✅ 血圧（上・下）・脈拍・体温・SpO2
- ✅ アラート表示・再検査フラグ・グループトーク自動通知
- ✅ 再検査通知を1日複数時刻で設定可能（最大5件）
- ✅ 利用曜日設定・曜日タブ絞り込み・臨時来所追加
- ✅ 臨時追加で既存利用者も検索可能
- ✅ 同名の過去バイタルがある場合「同一人物ですか？」で紐づけ
- ✅ 全員バイタル一覧・利用者ごとの過去履歴

### カレンダー
- ✅ TimeTree風の複数カレンダー管理
- ✅ プライベート（自分だけ）/ 共有（招待メンバーのみ）
- ✅ カレンダーチップで単独/全体表示切り替え・月/週表示
- ✅ シール機能（24種類）・繰り返し設定・通知設定
- ✅ メンバー招待・削除

### 使い方ガイド
- ✅ `/manual` でアクセス（ボトムナビ「ガイド」）
- ✅ SVGイラスト付き・全12機能の説明
- ✅ 新機能追加時はmanual.htmlにセクション追加するだけ

### PWA・オフライン対応
- ✅ Service Worker v2（sw.js）- フォームPOSTは非介入
- ✅ ホーム画面に追加してアプリっぽく使える
- ✅ オフライン時はオレンジバナー表示
- ✅ 災害時モード（オフライン記録→ネット復旧後自動同期）
- ✅ 利用者情報をIndexedDBにキャッシュ

### 数秘・管理者MENU・開発者MENU
- ✅ 数秘全8項目（LP/B/D/S/P/M/IT/LL）
- ✅ 管理者/開発者MENU分離・横並び選択
- ✅ 管理者MENU：スタッフ管理・招待QR・パスワード変更・履歴件数設定

---

## 🏗️ アーキテクチャの重要ポイント

### SPA
- ボトムナビはSPAで動作（base.htmlのnavigateTo関数）
- SPAで注入するscriptは **IIFE `(function(){...})();`** で囲む
- カレンダー初期化は **rAFを2重** にして描画後に実行
- SPA非対応ページ（通常遷移）: `/admin` `/history` `/input` `/daily_view` `/numerology` `/birthday`

### スクリプトの重要ルール
```javascript
(function(){
    // awaitを使う関数には必ずasyncをつける！
    window.myFunc = async function() { const res = await fetch(...); };
    // 全関数をwindow.に公開する
    window.otherFunc = function() { ... };
    // onclickではなくaddEventListenerを使う（iPhone対応）
    el.addEventListener('touchend', e => { e.preventDefault(); myFunc(); });
})();
```

### ボトムナビ構成（左から順）
TOP → 記録入力 → ケース記録 → バイタル → カレンダー → モニタリング → 評価 → トーク → 誕生日 → 数秘 → ガイド → ログアウト

### 通知サウンド
- localStorage の `tasukaru_sound` キーに保存（端末ごとの個人設定）
- トークの歯車ボタンから設定（管理者MENUからは削除済み）
- base.htmlの `playNotificationSound()` 関数で再生

### PWA Service Worker注意事項
- sw.js の CACHE_VERSION を上げると古いキャッシュが削除される（現在 v2）
- フォームPOSTはService Worker非介入（v1の不具合を修正済み）
- デプロイ後はブラウザのキャッシュクリアが必要な場合あり

---

## 📝 変更履歴（2026-04-13）

- feat: 記録保存後にトーストポップアップ・フォーム自動クリアで次の入力へ (2026-04-13)
- fix: Service WorkerがフォームPOSTを横取りして記録保存できない問題修正 (2026-04-13)
- fix: トーク相手が選べない問題修正（icon_emojiカラムなくてもエラーにならないよう修正） (2026-04-13)
- feat: 管理者MENUからサウンド設定削除（トーク歯車に統合） (2026-04-13)
- feat: トークに検索窓・歯車ボタンでサウンド設定追加 (2026-04-13)
- feat: 使い方ガイド追加（/manual・SVGイラスト・全12機能） (2026-04-13)
- feat: トーク未読バッジ・通知サウンド5種類（タスカル音声含む） (2026-04-13)
- feat: PWA対応・Service Worker・オフラインキャッシュ・災害時モード (2026-04-13)
- fix: 更新履歴→ケース記録遷移修正・削除警告強化・削除権限チェック (2026-04-13)
- feat: カレンダーをプライベート/共有対応・メンバー招待機能 (2026-04-13)
- feat: カレンダー機能追加（TimeTree風・シール・繰り返し） (2026-04-13)
- feat: バイタル臨時追加で既存利用者検索・紐づけ・複数時刻通知 (2026-04-13)
- fix: モニタリング利用者検索修正 (2026-04-13)
- feat: パスワード入力欄に目のマーク追加 (2026-04-13)
- feat: cloudrun-devブランチ・tasukaru-devサービス設定完了 (2026-04-13)

## 📝 変更履歴（2026-04-12）

- feat: バイタル機能追加・ボトムナビブロック選択スタイル (2026-04-12)
- fix: asyncキーワード抜けによる全ボタン不動作修正（全テンプレート） (2026-04-12)
- fix: 管理者MENUから退出ボタン修正 (2026-04-12)
- feat: Claude閲覧許可を開発者MENUへ移動 (2026-04-12)
- feat: 管理者/開発者MENU分離 (2026-04-12)
- feat: 数秘ページ全8項目対応 (2026-04-12)
- feat: 評価メニュー・AI報告書生成 (2026-04-12)
- feat: トーク機能LINE風全面刷新 (2026-04-12)

---

## 🚀 Claudeへの引き継ぎメモ

### 新しい会話を始めるときは
1. このREADME.mdをClaudeに貼り付ける
2. 作業するファイルも一緒に貼ると素早く再開できる

### 特に重要な注意事項（必ず守ること）
1. `patients.id` は **bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて **IIFE** で囲む
4. `await`を使う関数には **`async`** を必ずつける
5. 全関数を **`window.xxx = function`** で公開する
6. onclickではなく **`addEventListener`** を使う（iPhone対応）
7. 開発は **`cloudrun-dev`** で行い、確認後に `cloudrun` にマージ
8. デプロイ後は必ず **`git checkout cloudrun-dev`** に戻る
9. sw.jsを修正したら **CACHE_VERSION** を上げる
10. フォームPOSTはService Worker非介入（sw.jsで対応済み）
# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-13 22:00

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 施設コード | cocokaraplus-5526 |
| GCPプロジェクト | tasukaru-production（PROJECT_NUMBER: 191764727533） |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 現場（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発確認用 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 開発者MENU | /dev |

---

## 🗂️ ブランチ構成・開発フロー

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版・触らない） |
| `cloudrun` | Flask版・**現場本番** ← 触らない |
| `cloudrun-dev` | Flask版・**開発改善用** ← ここで作業 |

```
cloudrun-dev で開発・修正
        ↓ 動作確認OK
cloudrun にマージ → gcloud run deploy → 現場反映
```

### cloudrunへのマージ＆デプロイコマンド（デプロイ後cloudrun-devに戻る）
```bash
cd kaigo-ai-app
git checkout cloudrun
git merge cloudrun-dev
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated && \
git checkout cloudrun-dev
```

### tasukaru-devへのデプロイコマンド
```bash
cd kaigo-ai-app
git add .
git commit -m "変更内容"
git push origin cloudrun-dev
gcloud run deploy tasukaru-dev \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated
```

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD        ← 開発者MENUのパスワード（デフォルト: tasukaru-dev-2024）
```

### ⚠️ 環境変数更新の注意
必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

### tasukaru-devへの環境変数コピー（初回のみ）
```bash
gcloud run services describe tasukaru \
  --region asia-northeast1 --format="json" \
  | python3 -c "
import json,sys,subprocess
data=json.load(sys.stdin)
envs=data['spec']['template']['spec']['containers'][0]['env']
env_str=','.join([f\"{e['name']}={e['value']}\" for e in envs if 'value' in e])
subprocess.run(f'gcloud run services update tasukaru-dev --region asia-northeast1 --update-env-vars \"{env_str}\"',shell=True)
"
```

---

## 📁 ファイル構成（重要ファイルのみ）

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API（約2600行） |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `requirements.txt` | flask, supabase, google-genai, gunicorn |
| `backup_usb.sh` | USBバックアップ（HIRO'sUSB対応） |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ・PWA・通知サウンド・未読バッジ |
| `templates/login.html` | ログイン（目のマーク付き） |
| `templates/top.html` | TOP・更新履歴・アイコン変更モーダル（写真クロッパー・絵文字） |
| `templates/input.html` | 記録入力・音声AI・保存トースト・フォームクリア |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー・編集・削除（権限チェック） |
| `templates/history.html` | モニタリング生成（window公開済み・IIFE外でPATIENTS定義） |
| `templates/assessment.html` | 評価・AI報告書（generateReport async済み・利用者テキスト検索） |
| `templates/vitals.html` | バイタル（カメラ読み取り・スワイプ削除・AM/PMタブ・ピンチズーム） |
| `templates/calendar.html` | カレンダー（プライベート/共有・currentWeekStart週移動対応） |
| `templates/manual.html` | 使い方ガイド（SVGイラスト付き・12機能） |
| `templates/admin.html` | 管理者MENU（サウンド設定は削除済み） |
| `templates/dev_menu.html` | 開発者MENU |
| `templates/chat_rooms.html` | トーク一覧（検索窓・歯車サウンド設定） |
| `templates/chat_room.html` | トーク個別（即時送信・差分ポーリング3秒・既読表示） |
| `templates/birthday.html` | 誕生日一覧 |
| `templates/numerology.html` | 数秘（LP/B/D/S/P/M/IT/LL・ふりがな→ローマ字自動変換） |
| `templates/new_password.html` | パスワードリセット（目のマーク付き） |
| `static/admin.js` | 管理者MENU用JS（名簿スキャン・togglePw） |
| `static/sw.js` | PWA Service Worker v3（POST非介入） |
| `static/manifest.json` | PWAマニフェスト |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 重要カラム |
|---------|-----------|
| `facilities` | facility_code, admin_password(平文), expires_at（2027-04-13設定済み） |
| `staffs` | staff_name, password_hash(SHA-256), icon_emoji, **icon_image_url**(NEW) |
| `patients` | id(**bigint型！**), user_name, user_kana, birth_date, chart_number |
| `records` | facility_code, user_name, staff_name, content, created_at |
| `admin_settings` | key='admin_password' で管理者MENUパスワード（デフォルト:8888） |
| `chat_rooms` | id, is_group, name, last_message_at |
| `chat_members` | room_id, staff_name, facility_code, last_read_at |
| `chat_messages` | room_id, facility_code, staff_name, content, created_at |
| `assessments` | facility_code, user_name, target_month, ai_change |
| `vitals` | facility_code, patient_id, measured_date, bp_high/low, pulse, temperature, spo2, recheck |
| `vital_alert_settings` | recheck_times（カンマ区切り複数時刻） |
| `patient_visit_days` | facility_code, patient_id, weekdays, **ampm**(NEW: AM/PM/BOTH) |
| `calendars` | is_private, is_shared, owner_name |
| `calendar_events` | calendar_id, event_date, sticker |

### ⚠️ 重要注意事項
- `patients.id` は **bigint型** → 外部キーはTEXT型で持つ
- `staffs.icon_image_url` → `ALTER TABLE staffs ADD COLUMN IF NOT EXISTS icon_image_url TEXT DEFAULT '';` 実行済み
- `patient_visit_days.ampm` → `ALTER TABLE patient_visit_days ADD COLUMN IF NOT EXISTS ampm TEXT DEFAULT 'BOTH';` 実行済み
- `chat_messages.facility_code` → 存在確認済み（カラムあり）
- `facilities.expires_at` → 2027-04-13に設定済み

### パスワード管理
| 種類 | 保存場所 | 形式 |
|------|---------|------|
| スタッフのパスワード | `staffs.password_hash` | SHA-256ハッシュ |
| 施設管理者パスワード | `facilities.admin_password` | 平文 |
| 管理者MENUパスワード | `admin_settings` key='admin_password' | 平文（デフォルト:8888） |
| 開発者MENUパスワード | Cloud Run環境変数 `DEV_PASSWORD` | 平文（デフォルト:tasukaru-dev-2024） |

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ ログイン（目のマーク）・パスワードリセット（SendGrid）
- ✅ 記録入力（音声→AI文章化・写真圧縮1280px/70%・保存トースト・フォーム自動クリア）
- ✅ ケース記録閲覧（カレンダー・AI日誌・編集/削除権限チェック・更新履歴→自動スクロール）
- ✅ AI日誌生成・モニタリング生成（AI）

### トーク（LINE風）
- ✅ 即時送信（楽観的UI）・差分ポーリング3秒（location.reload廃止）
- ✅ 検索窓・歯車ボタンでサウンド設定（localStorage・端末ごと個人設定）
- ✅ 未読バッジ（ボトムナビ・30秒ごと）
- ✅ 通知サウンド5種類：🔔ポップ・🎵チャイム・📯ピコン・🦝タスカル・🔕なし
- ✅ 1:1とグループどちらも他の人には見えない（chat_members管理）

### アイコン変更（TOPページ）
- ✅ TOPの自分のアイコンをタップ→編集モーダル
- ✅ 写真アップロード（ドラッグ・ピンチズーム・位置調整・円形トリミング）
- ✅ 絵文字28種類から選択
- ✅ イニシャルに戻す
- ✅ staffs.icon_emoji + staffs.icon_image_urlに保存
- ✅ トーク・バイタルなど各画面に反映

### 評価
- ✅ AI報告書自動生成（generateReport async済み）
- ✅ 利用者テキスト検索（名前・ふりがな）
- ✅ ファイルドロップ・音声入力・印刷/PDF

### バイタル
- ✅ カメラ読み取り（Gemini）・ピンチズーム対応
- ✅ カメラモーダルをbody直下に移動（iPhoneのposition:fixed問題解消）
- ✅ SPA遷移時にカメラ自動クローズ
- ✅ スワイプ削除（左スワイプ→確認アラート→曜日から削除）
- ✅ AM/PMタブ（全員・午前・午後）
- ✅ アラート・再検査フラグ・臨時追加

### カレンダー
- ✅ TimeTree風・プライベート/共有・currentWeekStart変数で週移動
- ✅ シール24種・繰り返し・通知・メンバー招待

### 使い方ガイド
- ✅ /manual（ボトムナビ「ガイド」）・SVGイラスト・12機能説明

### PWA・オフライン
- ✅ Service Worker v3（POST非介入・フォーム保存OK）
- ✅ オフライン時オレンジバナー・災害時モード
- ✅ 利用者情報IndexedDBキャッシュ

### 管理者MENU
- ✅ 利用者管理・スタッフ管理・招待QR
- ✅ 名簿写真から一括読み取り（名前・生年月日・利用曜日・AM/PM）
- ✅ パスワード変更・履歴件数設定

### 数秘
- ✅ 全8項目（LP/B/D/S/P/M/IT/LL）
- ✅ ふりがな→ヘボン式ローマ字自動変換
- ✅ 生年月日未登録時は管理者MENUへ誘導メッセージ

---

## 🏗️ アーキテクチャの重要ポイント

### SPAルーター
- ボトムナビはSPAで動作（base.htmlのnavigateTo関数）
- SPA非対応ページ（通常遷移）: `/admin` `/history` `/input` `/daily_view` `/numerology` `/birthday`
- **SPA遷移時にカメラモーダルを自動クローズ**（base.htmlのnavigateTo冒頭）
- SPAで注入するscriptは **IIFE `(function(){...})();`** で囲む

### スクリプトの鉄則
```javascript
(function(){
    // 1. awaitを使う関数には必ずasyncをつける！
    window.myFunc = async function() { const res = await fetch(...); };
    // 2. 全関数をwindow.に公開する
    window.otherFunc = function() { ... };
    // 3. onclickではなくaddEventListenerを使う（iPhone対応）
    el.addEventListener('touchend', e => { e.preventDefault(); myFunc(); });
    // 4. IIFEの外でJinja2データを定義（const/let問題を回避）
    // 例: history.htmlのHISTORY_PATIENTS、assessment.htmlのASSESS_PATIENTS
})();
```

### ボトムナビ構成（左から順）
TOP → 記録入力 → ケース記録 → バイタル → カレンダー → モニタリング → 評価 → トーク → 誕生日 → 数秘 → ガイド → ログアウト

### 通知サウンド
- localStorage `tasukaru_sound` キー（端末ごとの個人設定）
- トークの歯車ボタンから設定
- base.htmlの `playNotificationSound()` で再生

### トークの既読比較
- `str(last_read) >= msg_dt_str` で文字列比較（型不一致エラー回避済み）

### バイタルのAM/PMフィルタ
- `AMPM_DATA[p.id]` が 'AM'/'PM'/'BOTH' → 'ALL'タブ時は全員表示

---

## 💾 USBバックアップ

```bash
cd kaigo-ai-app
./backup_usb.sh
# USBは「HIRO'sUSB」に自動保存
```

---

## 📝 変更履歴（2026-04-13 主要なもの）

- fix: SPA遷移時にカメラモーダルを自動クローズ
- fix: カメラモーダルをbody直下に移動・撮影ボタン完全表示
- feat: バイタルにスワイプ削除・AM/PMタブ追加
- feat: 評価ページに利用者テキスト検索追加
- fix: 評価generateReport async追加
- feat: アイコン変更機能（写真クロッパー・絵文字・TOPページ）
- fix: トーク即時送信・差分ポーリング3秒（location.reload廃止）
- fix: トーク500エラー（chat_room関数インデント修正）
- fix: トーク既読比較の型エラー修正
- fix: カレンダー週表示の週移動修正（currentWeekStart変数）
- feat: 使い方ガイド（/manual・12機能・SVGイラスト）
- feat: PWA対応・Service Worker v3・災害時モード
- feat: 通知サウンド5種類・未読バッジ
- feat: パスワード目のマーク追加（login/admin/new_password）
- fix: モニタリング利用者検索（HISTORY_PATIENTSをIIFE外に移動）
- fix: Service WorkerがフォームPOSTを横取りする問題修正

---

## 🚀 次のClaudeへの引き継ぎメモ

### 新しい会話を始めるときは
このREADME.mdをClaudeに貼り付けるだけで再開できます。

### 特に重要な注意事項（必ず守ること）
1. `patients.id` は **bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて **IIFE** で囲む（SPA非対応ページも含む）
4. `await`を使う関数には **`async`** を必ずつける
5. 全関数を **`window.xxx`** で公開する
6. onclickではなく **`addEventListener`** を使う（iPhone対応）
7. Jinja2のデータ（PATIENTS等）は **IIFEの外** で定義する
8. 開発は **`cloudrun-dev`** で行い、確認後に `cloudrun` にマージ
9. デプロイ後は必ず **`git checkout cloudrun-dev`** に戻る
10. sw.jsを修正したら **CACHE_VERSION** を上げる（現在v3）
11. カメラモーダルは **body直下** に移動する（page-wrapperのoverflow問題）
12. SPA遷移時の後処理は **base.htmlのnavigateTo冒頭** に追加する

# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-14

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |
| GCPプロジェクト | tasukaru-production（PROJECT_NUMBER: 191764727533） |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 現場（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発確認用 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 開発者MENU | /dev |

---

## 🗂️ ブランチ構成・開発フロー

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版・触らない） |
| `cloudrun` | Flask版・**現場本番** ← 触らない |
| `cloudrun-dev` | Flask版・**開発改善用** ← ここで作業 |

```
cloudrun-dev で開発・修正
        ↓ 動作確認OK
cloudrun にマージ → gcloud run deploy → 現場反映
```

### cloudrunへのマージ＆デプロイ
```bash
cd kaigo-ai-app
git checkout cloudrun
git merge cloudrun-dev
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated && \
git checkout cloudrun-dev
```

### cloudrun-devへのデプロイ
```bash
cd kaigo-ai-app
git add .
git commit -m "変更内容"
git push origin cloudrun-dev
gcloud run deploy tasukaru-dev \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated
```

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY          ← anon/publicキー（Realtimeにも使用）
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD          ← 開発者MENUのパスワード（デフォルト: tasukaru-dev-2024）
```

⚠️ 環境変数更新は必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

---

## 📁 ファイル構成（重要ファイルのみ）

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API（約2600行） |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ・PWA・未読バッジ・Badging API |
| `templates/login.html` | ログイン画面（お名前入力欄付き） |
| `templates/top.html` | TOP画面・更新履歴・アイコン変更モーダル |
| `templates/input.html` | 記録入力・音声AI・保存トースト |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー・編集・削除 |
| `templates/chat_rooms.html` | トーク一覧（検索・歯車サウンド設定） |
| `templates/chat_room.html` | トーク個別（Supabase Realtime・吹き出しアニメーション） |
| `templates/vitals.html` | バイタル（カメラ読み取り・AM/PMタブ） |
| `templates/calendar.html` | カレンダー（TimeTree風） |
| `templates/assessment.html` | 評価・AI報告書 |
| `templates/manual.html` | 使い方ガイド |
| `static/sw.js` | PWA Service Worker v4（push/badge対応） |
| `static/manifest.json` | PWAマニフェスト |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 重要カラム |
|---------|-----------|
| `facilities` | facility_code, admin_password(平文), expires_at（2027-04-13設定済み） |
| `staffs` | staff_name, password_hash(SHA-256), icon_emoji, icon_image_url |
| `patients` | id(**bigint型！**), user_name, user_kana, birth_date, chart_number |
| `records` | facility_code, user_name, staff_name, content, created_at |
| `admin_settings` | key='admin_password' で管理者MENUパスワード（デフォルト:8888） |
| `chat_rooms` | id, is_group, name, last_message_at |
| `chat_members` | room_id, staff_name, facility_code, last_read_at |
| `chat_messages` | room_id, facility_code, staff_name, content, created_at |
| `vitals` | facility_code, patient_id, measured_date, bp_high/low, pulse, temperature, spo2 |
| `calendars` | is_private, is_shared, owner_name |
| `calendar_events` | calendar_id, event_date, sticker |

### ⚠️ 重要注意事項
- `patients.id` は **bigint型** → 外部キーはTEXT型で持つ
- `chat_messages` は **supabase_realtime publicationに登録済み** → Realtime動作中

### パスワード管理
| 種類 | 保存場所 | 形式 |
|------|---------|------|
| スタッフのパスワード | `staffs.password_hash` | SHA-256ハッシュ |
| 施設管理者パスワード | `facilities.admin_password` | 平文 |
| 管理者MENUパスワード | `admin_settings` key='admin_password' | 平文（デフォルト:8888） |
| 開発者MENUパスワード | Cloud Run環境変数 `DEV_PASSWORD` | 平文（デフォルト:tasukaru-dev-2024） |

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ ログイン（目のマーク）・**お名前任意入力（管理者パスワードでも名前設定可）**
- ✅ パスワードリセット（SendGrid）・招待リンク
- ✅ 記録入力（音声→AI文章化・写真・保存トースト）
- ✅ ケース記録閲覧（カレンダー・AI日誌・編集/削除）
- ✅ モニタリング生成（AI）

### トーク（LINE風） ← 本日大幅改善
- ✅ **Supabase Realtimeで即時受信**（🟢接続インジケーター付き）
- ✅ **吹き出しアニメーション**（ポンッと表示）
- ✅ 楽観的UI（送信後即表示）
- ✅ 差分ポーリング（Realtime失敗時のフォールバック）
- ✅ 既読表示・未読バッジ（ボトムナビ）
- ✅ 通知サウンド5種類
- ✅ 検索窓・グループ作成・メンバードロワー

### PWA・バッジ ← 本日追加
- ✅ **ホーム画面アイコンバッジ（Badging API・iOS 16.4+対応）**
- ✅ Service Worker v4（push受信・バッジ更新対応）
- ✅ オフライン時オレンジバナー・災害時モード

### バイタル
- ✅ カメラ読み取り（Gemini）・AM/PMタブ
- ✅ アラート・再検査フラグ・グループトーク通知

### カレンダー・評価・数秘・管理者MENU
- ✅ TimeTree風カレンダー・評価AI報告書
- ✅ 管理者/開発者MENU分離・名簿スキャン一括登録

---

## 🏗️ アーキテクチャの重要ポイント

### SPAルーター
- ボトムナビはSPAで動作（base.htmlのnavigateTo関数）
- SPA非対応ページ: `/admin` `/history` `/input` `/daily_view` `/numerology` `/birthday`
- SPAで注入するscriptは **IIFE `(function(){...})();`** で囲む

### スクリプトの鉄則
```javascript
(function(){
    // 1. awaitを使う関数には必ずasyncをつける
    window.myFunc = async function() { const res = await fetch(...); };
    // 2. 全関数をwindow.に公開する
    // 3. onclickではなくaddEventListenerを使う（iPhone対応）
    el.addEventListener('touchend', e => { e.preventDefault(); myFunc(); });
    // 4. Jinja2データはIIFEの外で定義
})();
```

### Supabase Realtime（chat_room.html）
```javascript
// Supabase JSライブラリをCDNから読み込み
// <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js">

// app.pyのchat_room()でSupabase情報を渡す
supabase_url = get_secret("SUPABASE_URL")
supabase_anon_key = get_secret("SUPABASE_KEY")  # anonキー
return render("chat_room.html", ..., supabase_url=supabase_url, supabase_anon_key=supabase_anon_key)
```

### PWA Badging API（base.html）
```javascript
// 未読数が変わったらバッジを更新
function updateAppBadge(count) {
    if ("setAppBadge" in navigator) {
        count > 0 ? navigator.setAppBadge(count) : navigator.clearAppBadge();
    }
    // Service Workerにも通知
    navigator.serviceWorker.controller?.postMessage({ type: "UPDATE_BADGE", count });
}
```

### ファイル修正のコツ（ターミナルコマンド）
```bash
# 特定行の確認
sed -n '950,970p' app.py

# 特定文字列の行番号を確認
grep -n "検索文字列" app.py

# 文字列の置換（Mac）
sed -i '' 's/変更前/変更後/' app.py
```

---

## 📝 変更履歴（2026-04-14）

- feat: Supabase Realtimeでトーク即時受信対応（🟢インジケーター・吹き出しアニメーション）
- feat: PWA Badging APIでホーム画面アイコンに未読バッジ表示（iOS 16.4+）
- feat: Service Worker v4（push受信・バッジ更新・フォールバックポーリング）
- feat: ログイン時に任意の名前を入力できる機能追加（管理者パスワードでも名前設定可）
- fix: chat_room.htmlのescapeHtml改行バグ修正（sendMessage動作しない問題解消）
- fix: chat_room.htmlをIIFE・addEventListener対応に全面書き直し

## 📝 変更履歴（2026-04-13）

- feat: バイタル機能・カレンダー・評価・PWA・使い方ガイド・トークLINE風刷新
- fix: asyncキーワード抜け・SPA遷移バグ・カレンダー白問題など多数修正

---

## 🚀 次のClaudeへの引き継ぎメモ

### 新しい会話を始めるときは
このREADME.mdをClaudeに貼り付けるだけで再開できます。
作業するファイルも一緒に貼ると素早く再開できます。

### ファイル修正の渡し方（優先順）
1. **ZIPで書き出し** → ドロップ＆置き換えが一番楽
2. **ターミナルコマンド（sed）** → 1〜2行の小さな修正に最適
3. VSCodeでの手動編集 → 複雑な修正

### 特に重要な注意事項（必ず守ること）
1. `patients.id` は **bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて **IIFE** で囲む
4. `await`を使う関数には **`async`** を必ずつける
5. 全関数を **`window.xxx`** で公開する
6. onclickではなく **`addEventListener`** を使う（iPhone対応）
7. Jinja2のデータ（PATIENTS等）は **IIFEの外** で定義する
8. 開発は **`cloudrun-dev`** で行い、確認後に `cloudrun` にマージ
9. デプロイ後は必ず **`git checkout cloudrun-dev`** に戻る
10. sw.jsを修正したら **CACHE_VERSION** を上げる（現在v4）
11. Pythonコードをターミナルに直接貼らない（bash構文エラーになる）
12. ターミナルコマンドを教えるときは **sedコマンド** か **ZIPファイル** で渡す

# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-14

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |
| 施設コード | cocokaraplus-5526 |
| GCPプロジェクト | tasukaru-production（PROJECT_NUMBER: 191764727533） |

---

## 🌐 アプリURL

| 環境 | URL |
|------|-----|
| 現場（本番） | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発確認用 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 開発者MENU | /dev |

---

## 🗂️ ブランチ構成・開発フロー

| ブランチ | 役割 |
|----------|------|
| `main` | Streamlit版（旧版・触らない） |
| `cloudrun` | Flask版・**現場本番** ← 触らない |
| `cloudrun-dev` | Flask版・**開発改善用** ← ここで作業 |

```
cloudrun-dev で開発・修正
        ↓ 動作確認OK
cloudrun にマージ → gcloud run deploy → 現場反映
```

### cloudrunへのマージ＆デプロイ
```bash
cd kaigo-ai-app
git checkout cloudrun
git merge cloudrun-dev
git push origin cloudrun
gcloud run deploy tasukaru \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated && \
git checkout cloudrun-dev
```

### cloudrun-devへのデプロイ
```bash
cd kaigo-ai-app
git add .
git commit -m "変更内容"
git push origin cloudrun-dev
gcloud run deploy tasukaru-dev \
  --source . --region asia-northeast1 \
  --platform managed --allow-unauthenticated
```

---

## ⚙️ 環境変数 (Cloud Run)

```
SUPABASE_URL
SUPABASE_KEY          ← anon/publicキー（Realtimeにも使用）
GEMINI_API_KEY
SECRET_KEY
SENDGRID_API_KEY
SENDGRID_FROM_EMAIL
DEV_PASSWORD          ← 開発者MENUのパスワード（デフォルト: tasukaru-dev-2024）
```

⚠️ 環境変数更新は必ず `--update-env-vars` を使う（`--set-env-vars` は既存変数が全部消えるので厳禁）

---

## 📁 ファイル構成（重要ファイルのみ）

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask メイン・全ルーティング・全API（約2600行） |
| `utils.py` | Gemini AI・Supabase画像アップロード |
| `Dockerfile` | Cloud Run用コンテナ設定 |
| `templates/base.html` | 共通レイアウト・SPAルーター・ボトムナビ・PWA・未読バッジ・Badging API |
| `templates/login.html` | ログイン画面（お名前入力欄付き） |
| `templates/top.html` | TOP画面・更新履歴・アイコン変更モーダル |
| `templates/input.html` | 記録入力・音声AI・保存トースト |
| `templates/daily_view.html` | ケース記録閲覧・カレンダー・編集・削除 |
| `templates/chat_rooms.html` | トーク一覧（検索・歯車サウンド設定） |
| `templates/chat_room.html` | トーク個別（Supabase Realtime・吹き出しアニメーション） |
| `templates/vitals.html` | バイタル（カメラ読み取り・AM/PMタブ） |
| `templates/calendar.html` | カレンダー（TimeTree風） |
| `templates/assessment.html` | 評価・AI報告書 |
| `templates/manual.html` | 使い方ガイド |
| `static/sw.js` | PWA Service Worker v4（push/badge対応） |
| `static/manifest.json` | PWAマニフェスト |

---

## 🗄️ Supabaseテーブル一覧

| テーブル | 重要カラム |
|---------|-----------|
| `facilities` | facility_code, admin_password(平文), expires_at（2027-04-13設定済み） |
| `staffs` | staff_name, password_hash(SHA-256), icon_emoji, icon_image_url |
| `patients` | id(**bigint型！**), user_name, user_kana, birth_date, chart_number |
| `records` | facility_code, user_name, staff_name, content, created_at |
| `admin_settings` | key='admin_password' で管理者MENUパスワード（デフォルト:8888） |
| `chat_rooms` | id, is_group, name, last_message_at |
| `chat_members` | room_id, staff_name, facility_code, last_read_at |
| `chat_messages` | room_id, facility_code, staff_name, content, created_at |
| `vitals` | facility_code, patient_id, measured_date, bp_high/low, pulse, temperature, spo2 |
| `calendars` | is_private, is_shared, owner_name |
| `calendar_events` | calendar_id, event_date, sticker |

### ⚠️ 重要注意事項
- `patients.id` は **bigint型** → 外部キーはTEXT型で持つ
- `chat_messages` は **supabase_realtime publicationに登録済み** → Realtime動作中

### パスワード管理
| 種類 | 保存場所 | 形式 |
|------|---------|------|
| スタッフのパスワード | `staffs.password_hash` | SHA-256ハッシュ |
| 施設管理者パスワード | `facilities.admin_password` | 平文 |
| 管理者MENUパスワード | `admin_settings` key='admin_password' | 平文（デフォルト:8888） |
| 開発者MENUパスワード | Cloud Run環境変数 `DEV_PASSWORD` | 平文（デフォルト:tasukaru-dev-2024） |

---

## 🔧 実装済み機能一覧

### 基本機能
- ✅ ログイン（目のマーク）・**お名前任意入力（管理者パスワードでも名前設定可）**
- ✅ パスワードリセット（SendGrid）・招待リンク
- ✅ 記録入力（音声→AI文章化・写真・保存トースト）
- ✅ ケース記録閲覧（カレンダー・AI日誌・編集/削除）
- ✅ モニタリング生成（AI）

### トーク（LINE風） ← 本日大幅改善
- ✅ **Supabase Realtimeで即時受信**（🟢接続インジケーター付き）
- ✅ **吹き出しアニメーション**（ポンッと表示）
- ✅ 楽観的UI（送信後即表示）
- ✅ 差分ポーリング（Realtime失敗時のフォールバック）
- ✅ 既読表示・未読バッジ（ボトムナビ）
- ✅ 通知サウンド5種類
- ✅ 検索窓・グループ作成・メンバードロワー

### PWA・バッジ ← 本日追加
- ✅ **ホーム画面アイコンバッジ（Badging API・iOS 16.4+対応）**
- ✅ Service Worker v4（push受信・バッジ更新対応）
- ✅ オフライン時オレンジバナー・災害時モード

### バイタル
- ✅ カメラ読み取り（Gemini）・AM/PMタブ
- ✅ アラート・再検査フラグ・グループトーク通知

### カレンダー・評価・数秘・管理者MENU
- ✅ TimeTree風カレンダー・評価AI報告書
- ✅ 管理者/開発者MENU分離・名簿スキャン一括登録

---

## 🏗️ アーキテクチャの重要ポイント

### SPAルーター
- ボトムナビはSPAで動作（base.htmlのnavigateTo関数）
- SPA非対応ページ: `/admin` `/history` `/input` `/daily_view` `/numerology` `/birthday`
- SPAで注入するscriptは **IIFE `(function(){...})();`** で囲む

### スクリプトの鉄則
```javascript
(function(){
    // 1. awaitを使う関数には必ずasyncをつける
    window.myFunc = async function() { const res = await fetch(...); };
    // 2. 全関数をwindow.に公開する
    // 3. onclickではなくaddEventListenerを使う（iPhone対応）
    el.addEventListener('touchend', e => { e.preventDefault(); myFunc(); });
    // 4. Jinja2データはIIFEの外で定義
})();
```

### Supabase Realtime（chat_room.html）
```javascript
// Supabase JSライブラリをCDNから読み込み
// <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js">

// app.pyのchat_room()でSupabase情報を渡す
supabase_url = get_secret("SUPABASE_URL")
supabase_anon_key = get_secret("SUPABASE_KEY")  # anonキー
return render("chat_room.html", ..., supabase_url=supabase_url, supabase_anon_key=supabase_anon_key)
```

### PWA Badging API（base.html）
```javascript
// 未読数が変わったらバッジを更新
function updateAppBadge(count) {
    if ("setAppBadge" in navigator) {
        count > 0 ? navigator.setAppBadge(count) : navigator.clearAppBadge();
    }
    // Service Workerにも通知
    navigator.serviceWorker.controller?.postMessage({ type: "UPDATE_BADGE", count });
}
```

### ファイル修正のコツ（ターミナルコマンド）
```bash
# 特定行の確認
sed -n '950,970p' app.py

# 特定文字列の行番号を確認
grep -n "検索文字列" app.py

# 文字列の置換（Mac）
sed -i '' 's/変更前/変更後/' app.py
```

---

## 📝 変更履歴（2026-04-14）

- feat: Supabase Realtimeでトーク即時受信対応（🟢インジケーター・吹き出しアニメーション）
- feat: PWA Badging APIでホーム画面アイコンに未読バッジ表示（iOS 16.4+）
- feat: Service Worker v4（push受信・バッジ更新・フォールバックポーリング）
- feat: ログイン時に任意の名前を入力できる機能追加（管理者パスワードでも名前設定可）
- fix: chat_room.htmlのescapeHtml改行バグ修正（sendMessage動作しない問題解消）
- fix: chat_room.htmlをIIFE・addEventListener対応に全面書き直し

## 📝 変更履歴（2026-04-13）

- feat: バイタル機能・カレンダー・評価・PWA・使い方ガイド・トークLINE風刷新
- fix: asyncキーワード抜け・SPA遷移バグ・カレンダー白問題など多数修正

---

## 🚀 次のClaudeへの引き継ぎメモ

### 新しい会話を始めるときは
このREADME.mdをClaudeに貼り付けるだけで再開できます。
作業するファイルも一緒に貼ると素早く再開できます。

### ファイル修正の渡し方（優先順）
1. **ZIPで書き出し** → ドロップ＆置き換えが一番楽
2. **ターミナルコマンド（sed）** → 1〜2行の小さな修正に最適
3. VSCodeでの手動編集 → 複雑な修正

### 特に重要な注意事項（必ず守ること）
1. `patients.id` は **bigint型** → patient_idはTEXT型で持つ
2. 環境変数更新は **`--update-env-vars`** のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべて **IIFE** で囲む
4. `await`を使う関数には **`async`** を必ずつける
5. 全関数を **`window.xxx`** で公開する
6. onclickではなく **`addEventListener`** を使う（iPhone対応）
7. Jinja2のデータ（PATIENTS等）は **IIFEの外** で定義する
8. 開発は **`cloudrun-dev`** で行い、確認後に `cloudrun` にマージ
9. デプロイ後は必ず **`git checkout cloudrun-dev`** に戻る
10. sw.jsを修正したら **CACHE_VERSION** を上げる（現在v4）
11. Pythonコードをターミナルに直接貼らない（bash構文エラーになる）
12. ターミナルコマンドを教えるときは **sedコマンド** か **ZIPファイル** で渡す

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
11. **ZIPで書き出し**か**ターミナルコマンド**で修正を指示する

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

# 本番同期
git stash && git checkout cloudrun && git merge cloudrun-dev && git push origin cloudrun
gcloud run deploy tasukaru --source . --region asia-northeast1 --platform managed --allow-unauthenticated && git checkout cloudrun-dev && git stash pop
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

---

## ファイル構成

```
kaigo-ai-app/
├── app.py（Flask メイン・全ルーティング・全API）
├── utils.py（Gemini AI・Supabase画像/音声アップロード）
├── templates/
│   ├── base.html（SPAルーター・ボトムナビ・PWA・未読バッジ・通知サウンド）
│   ├── chat_room.html（★Realtime対応・二重表示修正・送信音付き）
│   ├── chat_rooms.html（★試聴ボタン付きサウンド設定）
│   ├── assessment.html（★録音モードCSS・音声保存再生・保存バグ修正）
│   ├── top.html（★歯車ボタン・ユーザー設定モーダル）
│   ├── vitals.html（★cameraStream重複修正・全員ボタン点灯バグ修正）
│   ├── login.html（★お名前入力欄追加済み）
│   └── ...その他テンプレート
└── static/
    ├── sw.js（★PWA Service Worker v4・バッジAPI対応）
    └── manifest.json
```

---

## 今セッションで完了した作業

### ✅ ログイン時に名前を任意入力できる機能
- 管理者パスワードでログイン時、`login_name`入力欄に名前を入力するとその名前でログインできる

### ✅ Supabase Realtimeによるトーク即時受信
- ポーリング3秒 → Supabase WebSocketで即時受信に変更
- ルーム名横に🟡→🟢の接続状態ドット表示
- `chat_messages`テーブルをsupabase_realtime publicationに登録済み

### ✅ トーク二重表示バグ修正
- 自分のメッセージをRealtimeで受信した際の二重表示を修正

### ✅ 評価ページの録音モード選択ボタンCSS追加
- `.type-btn`と`.type-btn.active`のCSSを`assessment.html`に追加

### ✅ ホーム画面バッジ対応（PWA Badging API）
- `sw.js`にpushイベント受信・`navigator.setAppBadge()`追加
- CACHE_VERSION：v4に更新
- 動作条件：iPhone iOS 16.4以上、ホーム画面に追加済み、通知許可ON

### ✅ 評価ページに音声保存・再生機能を追加
- `utils.py`に`upload_audio_to_supabase()`関数を追加
- 音声をSupabaseの`assessment-audio`バケットに保存
- 報告書プレビューと過去の評価に音声プレイヤーを追加

### ✅ TOPページにユーザー設定を追加
- 右上に歯車ボタン追加
- 文字サイズ（90〜130%スライダー）・通知サウンド・アイコン設定をまとめた設定モーダル

### ✅ 送信音追加（Web Audio API）
- トーク送信時に「シュッ」という音が鳴る
- サウンド設定に「▶試聴」ボタンを追加

### ✅ 評価保存バグ修正
- contenteditable要素の取得を`textContent`→`innerText`に変更

### ✅ 通知許可ポップアップ追加
- base.htmlに初回のみ通知許可リクエストを追加（3秒後）

### ✅ バイタル画面のボタンが動かないバグ修正
- `vitals.html`の`cameraStream`変数が2回宣言されていたのを修正

### ✅ カメラボタンがSPA遷移で残るバグ修正
- `base.html`のnavigateTo関数でカメラモーダルを確実に閉じる処理を追加
- ページコンテンツ入れ替え後にも`camera-modal`を閉じる

### ✅ バイタル「全員」ボタンが常に点灯するバグ修正
- 初期化時に`selectAmpm('ALL')`を呼ぶように修正

---

## PENDING（未完了・次回対応）

- [ ] 「たすかる」音声（mp3ファイルが必要 → TTSmaker等で生成）
- [ ] 利用者の曜日設定を現場で登録・確認
- [ ] バイタルの動作を現場で最終確認
- [ ] サウンドテストページの削除（/sound_test）

---

## gcloud CLIとは

TASUKARUをCloud Runサーバーにデプロイするためのコマンドラインツール。

```
あなたのMac
    ↓ gcloud run deploy
Google Cloud（インターネット上のサーバー）
    ↓
Cloud Run（TASUKARUが動いている場所）
    ↓
https://tasukaru-dev-...run.app
```

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| `cd: kaigo-ai-app: No such file or directory` | すでにkaigo-ai-appにいる | そのまま実行 |
| `error: Your local changes would be overwritten` | .DS_Storeが変更されている | `git stash`してから実行 |
| `INVALID_ARGUMENT` デプロイエラー | 認証切れ | `gcloud auth login`で再認証 |
| Pylance `undefined variable` | 変数の定義順序の問題 | 変数初期化を関数の上に追加 |

---

*最終更新：2026-04-14*

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

### 掲示板テーブル（新規）
```sql
board_posts      -- 投稿本体（is_privateカラムあり）
board_comments   -- コメント
board_reactions  -- リアクション（✅👍など）
board_reads      -- 既読管理
```
- `board_posts.is_private` → TRUE=メンションした人のみ表示
- Realtime有効化済み（board_posts/board_comments/board_reactions）

---

## ファイル構成

```
kaigo-ai-app/
├── app.py（Flask メイン・全ルーティング・全API 約3100行）
│   └── 掲示板API追加：/board, /api/board/* 各種
├── utils.py（Gemini AI・Supabase画像/音声アップロード）
├── templates/
│   ├── base.html（SPAルーター・ボトムナビ・PWA・カメラ修正済み）
│   ├── board.html（★NEW 掲示板ページ 約1060行）
│   ├── chat_room.html（Realtime対応・送信音付き）
│   ├── chat_rooms.html（試聴ボタン付きサウンド設定）
│   ├── assessment.html（録音モードCSS・音声保存再生）
│   ├── top.html（歯車ボタン・ユーザー設定モーダル）
│   ├── vitals.html（cameraStream重複修正・全員ボタン修正済み）
│   └── login.html（お名前入力欄追加済み）
└── static/
    └── sw.js（PWA Service Worker v4・バッジAPI対応）
```

---

## 完了した全作業

### ✅ Supabase Realtimeによるトーク即時受信
- ポーリング → WebSocket即時受信に変更

### ✅ 評価ページに音声保存・再生機能
- utils.pyに`upload_audio_to_supabase()`追加
- assessmentsテーブルに`audio_url`カラム追加
- assessment-audioバケット作成（Supabase Storage）

### ✅ TOPページにユーザー設定（歯車ボタン）
- 文字サイズ（90〜130%スライダー）
- 通知サウンド（試聴ボタン付き）
- アイコン設定（絵文字・写真）

### ✅ トーク送信音追加・サウンド試聴ボタン
- Web Audio APIで「シュッ」音
- chat_rooms.htmlの歯車→試聴ボタン付きサウンド設定

### ✅ バイタル画面の複数バグ修正
- cameraStream重複宣言（480行目削除）
- 全員ボタンID大文字小文字不一致修正（`ampm-tab-ALL`→`ampm-tab-all`）
- 初期化時`selectAmpm('ALL')`追加

### ✅ カメラボタンSPA遷移バグ修正
- base.htmlのnavigateTo関数で`camera-modal`を確実に閉じる
- wrapper.innerHTML差し替え後にもカメラクリア処理追加

### ✅ 通知許可ポップアップ（base.html）
- 初回のみ3秒後に`Notification.requestPermission()`

### ✅ 掲示板機能（トークを完全置き換え）
- ボトムナビ「トーク」→「掲示板」に変更
- **投稿**：テキスト・写真・音声・ファイル添付
- **公開範囲**：全員に公開 / メンションした人のみ
- **メンション**：検索窓から候補ドロップダウンで選択、選択済みバッジ表示
- **コメント**：スレッド形式で返信
- **リアクション**：✅👍❤️など12種類
- **確認済み**：押した人数をバッジ表示
- **既読**：誰が見たか表示
- **編集・削除**：本人と管理者が可能（ボトムシート形式メニュー）
- **Realtime**：新着投稿をトースト通知で即時表示
- **未読バッジ**：ボトムナビにリアルタイム表示

---

## PENDING（未完了・次回対応）

- [ ] メニュー並び順カスタマイズ（ユーザー設定から）
- [ ] アップデートログ表示（TOPの歯車横にベルアイコン）
- [ ] 取扱説明書（マニュアル）の充実
- [ ] 「たすかる」音声（mp3ファイルが必要）
- [ ] 利用者の曜日設定を現場で登録・確認
- [ ] サウンドテストページの削除（/sound_test）
- [ ] 掲示板の`is_private`投稿をapp.pyでフィルタリング（メンション外の人に非表示）
- [ ] 本番（cloudrun）への最終同期

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| `cd: kaigo-ai-app: No such file or directory` | すでにkaigo-ai-appにいる | そのまま実行 |
| `error: Your local changes would be overwritten` | .DS_Storeが変更されている | `git stash`してから実行 |
| `INVALID_ARGUMENT` デプロイエラー | 認証切れ | `gcloud auth login`で再認証 |
| `--allow-unauthenticatedpython3` エラー | コマンドが繋がって貼られた | 1コマンドずつ実行する |
| Pylance `undefined variable` | 変数の定義順序の問題 | 変数初期化を関数の上に追加 |
| SyntaxError in heredoc | クォートがネストして壊れる | Pythonスクリプトファイルを作って実行する |

---

## gcloud CLIとは

TASUKARUをCloud Runサーバーにデプロイするためのコマンドラインツール。

```
あなたのMac
    ↓ gcloud run deploy
Google Cloud（インターネット上のサーバー）
    ↓
Cloud Run（TASUKARUが動いている場所）
    ↓
https://tasukaru-...run.app
```

- `git add/commit/push` = コードをGitHubに保存
- `gcloud run deploy` = そのコードをCloud Runサーバーに反映

---

*最終更新：2026-04-14*

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

### 取説（manual.html）使用画像
```
tasukaru_top.png       → 通常・笑顔（ヒーローフワフワ・挨拶・記録入力・掲示板・設定）
tasukaru_sestumei.png  → 説明（ケース記録・モニタリング・評価・カレンダー・バイタル）
tasukaru_odoroki2.png  → 驚き（ログイン・バイタル警告・災害時）
tasukaru_onegai.png    → お願い（ヒント・注意ボックス全般）
tasukaru_ooyorokobi.png → 大喜び（締め・フッター）
```
- ヒーロー画像は青背景(#1558d0)で合成済み（透過なし）
- フッター画像は背景色(#f2f4f8)で合成済み


```sql
board_posts      -- 投稿本体（is_privateカラムあり）
board_comments   -- コメント
board_reactions  -- リアクション（✅👍など）
board_reads      -- 既読管理
```
- `board_posts.is_private` → TRUE=メンションした人のみ表示
- Realtime有効化済み（board_posts/board_comments/board_reactions）

---

## ファイル構成

```
kaigo-ai-app/
├── app.py（Flask メイン・全ルーティング・全API 約3100行）
│   └── 掲示板API追加：/board, /api/board/* 各種
├── utils.py（Gemini AI・Supabase画像/音声アップロード）
├── templates/
│   ├── base.html（SPAルーター・ボトムナビ・PWA・カメラ修正済み）
│   ├── board.html（★NEW 掲示板ページ 約1060行）
│   ├── manual.html（★取説 Ver.3.0 ※要デプロイ→下記PENDING参照）
│   ├── chat_room.html（Realtime対応・送信音付き）
│   ├── chat_rooms.html（試聴ボタン付きサウンド設定）
│   ├── assessment.html（録音モードCSS・音声保存再生）
│   ├── top.html（歯車ボタン・ユーザー設定モーダル）
│   ├── vitals.html（cameraStream重複修正・全員ボタン修正済み）
│   └── login.html（お名前入力欄追加済み）
└── static/
    └── sw.js（PWA Service Worker v4・バッジAPI対応）
```

---

## 完了した全作業

### ✅ Supabase Realtimeによるトーク即時受信
- ポーリング → WebSocket即時受信に変更

### ✅ 評価ページに音声保存・再生機能
- utils.pyに`upload_audio_to_supabase()`追加
- assessmentsテーブルに`audio_url`カラム追加
- assessment-audioバケット作成（Supabase Storage）

### ✅ TOPページにユーザー設定（歯車ボタン）
- 文字サイズ（90〜130%スライダー）
- 通知サウンド（試聴ボタン付き）
- アイコン設定（絵文字・写真）

### ✅ トーク送信音追加・サウンド試聴ボタン
- Web Audio APIで「シュッ」音
- chat_rooms.htmlの歯車→試聴ボタン付きサウンド設定

### ✅ バイタル画面の複数バグ修正
- cameraStream重複宣言（480行目削除）
- 全員ボタンID大文字小文字不一致修正（`ampm-tab-ALL`→`ampm-tab-all`）
- 初期化時`selectAmpm('ALL')`追加

### ✅ カメラボタンSPA遷移バグ修正
- base.htmlのnavigateTo関数で`camera-modal`を確実に閉じる
- wrapper.innerHTML差し替え後にもカメラクリア処理追加

### ✅ 通知許可ポップアップ（base.html）
- 初回のみ3秒後に`Notification.requestPermission()`

### ✅ 取説（manual.html）Ver.3.0 リニューアル
- タスカルくんの本物スタンプ画像5種類を使用（tasukaru_top / sestumei / odoroki2 / onegai / ooyorokobi）
- ヒーロー：タスカルくんフワフワアニメ（青背景合成で透過なし）
- セクション横：Material Symbolsアイコン（lock / edit_note / monitor_heart / campaign 等）
- 吹き出し：タスカルくん画像（場面別5種類使い分け）
- フロー図：Material Symbolsアイコン付き丸番号
- 掲示板セクション追加（旧「トーク」→「掲示板」に対応済み）
- 目次：色付き丸アイコン＋スムーススクロール
- 「タスカルくん」青文字ラベル：挨拶吹き出しのみ表示


- ボトムナビ「トーク」→「掲示板」に変更
- **投稿**：テキスト・写真・音声・ファイル添付
- **公開範囲**：全員に公開 / メンションした人のみ
- **メンション**：検索窓から候補ドロップダウンで選択、選択済みバッジ表示
- **コメント**：スレッド形式で返信
- **リアクション**：✅👍❤️など12種類
- **確認済み**：押した人数をバッジ表示
- **既読**：誰が見たか表示
- **編集・削除**：本人と管理者が可能（ボトムシート形式メニュー）
- **Realtime**：新着投稿をトースト通知で即時表示
- **未読バッジ**：ボトムナビにリアルタイム表示

---

## PENDING（未完了・次回対応）

### 🔴 最優先（次回チャット冒頭でやること）
- [ ] **manual.html Ver.3.0 をデプロイ**（現在まだ古いVer.2.0が表示中）
  - outputsからダウンロードして`templates/manual.html`に置き換えてデプロイ
  - または新チャットで再生成してデプロイ
- [ ] **ヒーローのタスカルくんを新画像に差し替え**
  - ユーザーが画像をアップロードしようとしたが上限で送れず→次チャットで受け取る
  - 処理：白背景透明化→青背景(#1558d0)で合成→Base64埋め込み

### 🟡 機能追加
- [ ] メニュー並び順カスタマイズ（ユーザー設定から）
- [ ] アップデートログ表示（TOPの歯車横にベルアイコン）
- [ ] 掲示板の`is_private`投稿をapp.pyでフィルタリング（メンション外の人に非表示）
- [ ] 本番（cloudrun）への最終同期

### 🟢 軽微
- [ ] 「たすかる」音声（mp3ファイルが必要）
- [ ] 利用者の曜日設定を現場で登録・確認
- [ ] サウンドテストページの削除（/sound_test）

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| `cd: kaigo-ai-app: No such file or directory` | すでにkaigo-ai-appにいる | そのまま実行 |
| `error: Your local changes would be overwritten` | .DS_Storeが変更されている | `git stash`してから実行 |
| `INVALID_ARGUMENT` デプロイエラー | 認証切れ | `gcloud auth login`で再認証 |
| `--allow-unauthenticatedpython3` エラー | コマンドが繋がって貼られた | 1コマンドずつ実行する |
| Pylance `undefined variable` | 変数の定義順序の問題 | 変数初期化を関数の上に追加 |
| SyntaxError in heredoc | クォートがネストして壊れる | Pythonスクリプトファイルを作って実行する |

---

## gcloud CLIとは

TASUKARUをCloud Runサーバーにデプロイするためのコマンドラインツール。

```
あなたのMac
    ↓ gcloud run deploy
Google Cloud（インターネット上のサーバー）
    ↓
Cloud Run（TASUKARUが動いている場所）
    ↓
https://tasukaru-...run.app
```

- `git add/commit/push` = コードをGitHubに保存
- `gcloud run deploy` = そのコードをCloud Runサーバーに反映

---

*最終更新：2026-04-14（取説リニューアル・掲示板機能追加・バイタル修正）*