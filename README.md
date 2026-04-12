# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-12 19:22

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

- feat: 誕生日ページから数秘タブ削除・数秘7表記・モーダル表示・数秘検索を全利用者対応 (2026-04-12)
- fix: カレンダーが表示されない問題を修正・nullチェックとフォールバック追加 (2026-04-12)
- fix: 記録入力の利用者選択クリック問題を修正 (2026-04-12)
- fix: iPhone検索候補クリックの競合問題を修正 (2026-04-12)
- fix: admin.jsを完全版に書き直し・全関数の構文エラー修正 (2026-04-12)
- docs: 本日の開発内容をREADMEに記録 (2026-04-12)
- fix: モニタリング選択・カレンダー表示の不具合修正 (2026-04-12)
- feat: QRコードでスタッフ招待機能を実装 (2026-04-12)
- feat: スタッフ登録・削除機能を実装 (2026-04-12)
- fix: ケース記録ページ読み込み時に記録エリアへ自動スクロール (2026-04-12)

---

## 🔄 今回のcommitで変更したファイル



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
