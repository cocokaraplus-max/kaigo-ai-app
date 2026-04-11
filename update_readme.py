#!/usr/bin/env python3
"""
commit & deploy するたびに README.md を自動更新するスクリプト
使い方: python update_readme.py
"""
import subprocess
from datetime import datetime

def get_recent_commits(n=10):
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--pretty=format:- %s (%ad)", "--date=short"],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except:
        return "- （取得できませんでした）"

def get_changed_files():
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True
        )
        files = result.stdout.strip().split("\n")
        return "\n".join([f"- {f}" for f in files if f])
    except:
        return "- （取得できませんでした）"

def generate_readme():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    commits = get_recent_commits()
    changed = get_changed_files()

    content = f"""# 🦝 TASUKARU - 介護ケース記録アプリ

> 介護現場の「書く」負担をゼロにするAI支援ツール

最終更新: {now}

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
gcloud run deploy tasukaru \\
  --source . \\
  --region asia-northeast1 \\
  --platform managed \\
  --allow-unauthenticated
```

---

## 📝 直近の変更履歴

{commits}

---

## 🔄 今回のcommitで変更したファイル

{changed}

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
"""
    return content

if __name__ == "__main__":
    import sys

    print("📝 README.md を更新中...")
    readme = generate_readme()
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)
    print("✅ README.md を更新しました")

    # コミットメッセージはコマンドライン引数から受け取る
    # 使い方: python update_readme.py "メッセージ"
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
    else:
        msg = f"deploy: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    print(f"\n💬 コミットメッセージ: {msg}")
    print("\n📦 git add & commit...")
    subprocess.run(["git", "add", "."])
    subprocess.run(["git", "commit", "-m", msg])
    subprocess.run(["git", "push", "origin", "cloudrun"])

    print("\n🚀 Cloud Run にデプロイ中...")
    result = subprocess.run([
        "gcloud", "run", "deploy", "tasukaru",
        "--source", ".",
        "--region", "asia-northeast1",
        "--platform", "managed",
        "--allow-unauthenticated"
    ])

    if result.returncode == 0:
        print("\n✅ デプロイ完了！")
        print("🌐 https://tasukaru-191764727533.asia-northeast1.run.app")
    else:
        print("\n❌ デプロイに失敗しました。エラーを確認してください。")