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
