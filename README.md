# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: 2026-04-09 21:09

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

- feat: Cloud Run市販モデル向けDockerfileを最適化 (2026-04-09)
- fix: Geminiモデルを4段階フォールバックで安定化 (2026-04-09)
- fix: ケース記録タイトルを日付形式に変更・箇条書き禁止 (2026-04-09)
- fix: 503エラー時に自動リトライする機能を追加 (2026-04-09)
- fix: 音声文章化・申し送りプロンプトを修正 (2026-04-09)
- feat: 申し送り口調に変更・再生成ボタン追加 (2026-04-09)
- feat: ログイン情報を暗号化トークンでURL保持 (2026-04-09)
- feat: URLパラメータでログイン維持を実装 (2026-04-09)
- feat: 写真をSupabaseストレージに保存・ケース記録に表示 (2026-04-09)
- fix: Geminiレスポンスの.textアクセスを修正 (2026-04-09)

---

## 🔄 今回のcommitで変更したファイル

- utils.py

---

## 🚀 Claudeへの引き継ぎメモ

新しい会話を始めるときはこのREADME.mdを貼り付けてください。
以下のファイルも一緒に共有すると素早く再開できます：
- `app.py`
- `views.py`
- `utils.py`
