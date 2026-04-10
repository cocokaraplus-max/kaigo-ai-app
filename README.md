# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-10 20:41

---

## 📋 アプリ概要

| 項目 | 内容 |
|------|------|
| アプリ名 | TASUKARU（タスカル） |
| 目的 | 介護現場の記録業務をAIで自動化 |
| 対象 | ITに不慣れな介護スタッフ |

---

## ✨ 主要機能

- **AI文章化** : 音声・画像から介護記録を自動生成（Gemini 1.5 Flash）
- **AI統合** : 1日の断片的な記録を1つのケース記録に統合
- **モニタリング生成** : 1ヶ月の記録を解析して要約作成
- **現場特化UI** : ひらがな検索・直感的操作・端末制限セキュリティ

---

## 🛠️ 技術スタック

| 種類 | 内容 |
|------|------|
| 言語 / FW | Python / Streamlit |
| データベース | Supabase (PostgreSQL) |
| AI エンジン | Google Gemini 1.5 Flash |
| インフラ | GitHub + Streamlit Cloud |

---

## 📁 ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | メイン・ページルーティング・ログイン処理 |
| `views.py` | 各画面の描画（TOP・入力・履歴・統合・管理） |
| `utils.py` | 共通関数・Gemini AI・クッキー管理 |
| `requirements.txt` | 使用ライブラリ一覧 |
| `update_readme.py` | README自動更新スクリプト |

---

## ⚙️ Streamlit Secrets 設定項目

```toml
SUPABASE_URL = "https://xxxxxxxxxx.supabase.co"
SUPABASE_KEY = "eyJhbGci...（anonキー・1行で）"
GEMINI_API_KEY = "AIzaSy..."
COOKIES_PASSWORD = "任意の長い文字列（一度決めたら変えない）"
```

---

## ✅ 解決済みのバグ

- `set_page_config` をファイルの先頭に移動（Streamlitのルール）
- `SUPABASE_KEY` の改行混入を `.strip()` で自動除去
- Gemini モデル名を `gemini-pro` → `gemini-1.5-flash` に修正
- `.gitignore` を作成して `secrets.toml` をGitHub非公開に設定
- `views.py` の変数名衝突（`m`）を修正

---

## 📝 直近の変更履歴

- feat: 登録メールにQRコードを添付 (2026-04-10)
- fix: メール本文のURLをtasukaru-39.web.appに変更 (2026-04-10)
- fix: ログイン・スマホ文字色修正 (2026-04-10)
- fix: スマホ文字色修正 (2026-04-10)
- fix: exception変数名を修正 (2026-04-10)
- feat: パスワードログイン・職員招待機能の基盤を追加 (2026-04-10)
- fix: 登録フローを整理 (2026-04-10)
- fix: 登録後にログイン画面へ遷移するボタンを追加 (2026-04-10)
- feat: 施設セルフ登録・メール送信機能を追加 (2026-04-10)
- feat: 施設情報の編集機能・プラン無制限選択を追加 (2026-04-10)

---

## 🔄 今回のcommitで変更したファイル

- style.css

---

## 🚀 Claudeへの引き継ぎメモ

新しい会話を始めるときはこのREADME.mdを貼り付けてください。
以下のファイルも一緒に共有すると素早く再開できます：
- `app.py`
- `views.py`
- `utils.py`
