# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-11 11:43

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

- deploy: 2026-04-11 11:15 (2026-04-11)
- feat: 利用者管理をセレクトボックス方式に変更 (2026-04-11)
- feat: 利用者管理UIをアコーディオン方式に変更・ログインボタン文字白 (2026-04-11)
- fix: TOPボタン統一・利用者名1行表示・ケース記録閲覧に変更 (2026-04-11)
- fix: ログインボタン文字白・TOPボタン統一・テキスト修正 (2026-04-11)
- fix: ボタンデザイン修正・ログインボタン文字白に (2026-04-11)
- fix: style.css整理・ボタン固定幅で名前1行表示 (2026-04-11)
- fix: ボタンをコンパクトにして名前が1行に収まるよう調整 (2026-04-11)
- fix: 利用者名の幅を広げて2段になるのを防止 (2026-04-11)
- fix: style.cssを完全リセット・横並びCSS追加 (2026-04-11)

---

## 🔄 今回のcommitで変更したファイル

- .DS_Store
- README.md

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
