# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-12 21:00

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
| `update_readme.py` | README自動更新スクリプト |
| `templates/base.html` | 共通レイアウト・Material Symbols読み込み |
| `templates/login.html` | ログイン画面 |
| `templates/register.html` | 施設新規登録画面 |
| `templates/top.html` | TOP画面・更新履歴 |
| `templates/input.html` | 記録入力・音声AI文章化 |
| `templates/daily_view.html` | ケース記録閲覧・AI統合 |
| `templates/history.html` | モニタリング生成 |
| `templates/admin.html` | 管理者メニュー |
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

- feat: 数秘ページをLP・B・D・S・P・M・IT・LL全8項目対応に全面刷新・TASUKARUオリジナル表現 (2026-04-12)
- fix: SPA遷移でconst/let重複宣言エラー全8件修正・全ページスクリプトをIIFEで囲む (2026-04-12)
- fix: ケース記録カレンダー白問題を根本修正・rAF2重で描画後に初期化 (2026-04-12)
- feat: 評価の音声ファイル解析に独り言/対話モード選択を追加 (2026-04-12)
- feat: 評価メニュー追加・個別機能訓練月次評価報告書のAI自動生成・PC/スマホ対応・印刷/PDF出力 (2026-04-12)
- feat: トーク機能をLINE風に全面刷新・1:1/グループ作成・職員アイコン・既読人数表示 (2026-04-12)
- fix: ケース記録カレンダーがSPA遷移時に白くなるバグを修正・initCalendar即時実行に変更 (2026-04-12)
- feat: カレンダーに記録のある日付のドット表示を追加・/api/record_datesエンドポイント追加 (2026-04-12)
- fix: 未ログイン時のボトムナビを非表示に修正 (2026-04-12)
- feat: SendGridメール送信・パスワードリセット機能実装 (2026-04-12)
- fix: パスワード変更のupsertをupdate/insertに修正 (2026-04-12)
- feat: 誕生日ページから数秘タブ削除・数秘7表記・モーダル表示・数秘検索を全利用者対応 (2026-04-12)
- fix: カレンダーが表示されない問題を修正・nullチェックとフォールバック追加 (2026-04-12)
- fix: 記録入力の利用者選択クリック問題を修正 (2026-04-12)
- fix: iPhone検索候補クリックの競合問題を修正 (2026-04-12)
- fix: admin.jsを完全版に書き直し・全関数の構文エラー修正 (2026-04-12)
- docs: 本日の開発内容をREADMEに記録 (2026-04-12)
- fix: モニタリング選択・カレンダー表示の不具合修正 (2026-04-12)

---

## 🔄 今回のcommitで変更したファイル

- `app.py` - 評価ルート・generate_assessment・save_assessment・parse_assessment_file API追加
- `templates/assessment.html` - 新規追加：評価入力・AI生成・報告書プレビュー・印刷
- `templates/base.html` - ボトムナビに「評価」追加
- `assessment_tables.sql` - Supabase用テーブル追加SQL（要実行）

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
