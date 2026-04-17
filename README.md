# TASUKARU（たすかる）— 介護施設向けケース記録・書式自動入力アプリ

> **このREADMEは、開発の軌跡を未来の自分・AIアシスタント・チームメンバーに引き継ぐための記録です。**
> 次のセッションでClaudeに「README読んで」と言えば、すぐに文脈を理解して開発を再開できます。

---

## 🧭 作者の想いと目的

このアプリは、**介護施設のスタッフが毎月行う「書類仕事」を減らすために作られています**。

介護の現場では、利用者一人ひとりのモニタリング報告書・ケース記録・評価票などを毎月作成する必要があります。これらは内容がほぼ同じなのに、Excelの書式に手入力し直す作業が毎回発生します。スタッフは「利用者と向き合う時間」を書類に奪われています。

**TASUKARUが目指すのは：**
- AIが面談内容を聞き取って自動でアセスメントを生成する
- 一度設定しておけば、Excelの書式（施設ごとに違う）に自動で転記される
- スタッフが「書き方」ではなく「利用者の状態」を考えることに集中できる環境

つまり、**「介護記録のコピペ地獄からの解放」** がゴールです。

将来的には複数施設への展開、施設ごとのカスタマイズ、AIによる変化検知・アラートなども視野に入れています。

---

## 🔗 アクセス情報

| 項目 | 値 |
|------|-----|
| **本番URL** | https://tasukaru-191764727533.asia-northeast1.run.app |
| **開発URL** | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| **GCPプロジェクト** | `tasukaru-production` |
| **Cloud Runサービス（本番）** | `tasukaru` |
| **Cloud Runサービス（開発）** | `tasukaru-dev` |
| **リージョン** | `asia-northeast1`（東京） |
| **最新リビジョン（本番）** | `tasukaru-00299-bvs`（2025-04-18時点） |
| **最新リビジョン（開発）** | `tasukaru-dev-00209-8hb`（2025-04-18時点） |

---

## 🏗 技術スタック

| 層 | 技術 |
|-----|------|
| **バックエンド** | Python / Flask |
| **デプロイ** | Google Cloud Run（Dockerコンテナ） |
| **データベース** | Supabase（PostgreSQL） |
| **ストレージ** | GCS（`run-sources-tasukaru-production-asia-northeast1`） |
| **スプレッドシート自動入力** | Google Apps Script（GAS） |
| **フロントエンド** | HTML/CSS/JavaScript（Flaskテンプレート + 一部スタンドアロンHTML） |

---

## 📁 ファイル構成

```
~/tasukaru/
├── app.py                    # Flaskメインアプリ（全ルート・API定義）
├── Dockerfile                # Cloud Run用コンテナ定義
├── requirements.txt          # Pythonパッケージ
├── templates/                # Flaskテンプレート（Jinja2）
│   ├── base.html             # 共通レイアウト（ヘッダー・ナビ）
│   ├── assessment.html       # AIアセスメント入力画面
│   ├── mapping.html          # 書式マッピング設定（暫定）
│   ├── case_record.html      # ケース記録入力
│   ├── monitoring.html       # モニタリング記録
│   ├── vitals.html           # バイタル記録
│   ├── calendar.html         # カレンダー表示
│   ├── daily_view.html       # 日次記録ビュー
│   ├── board.html            # 掲示板
│   ├── numerology.html       # 数秘術（特殊機能）
│   └── ...（その他多数）
└── static/
    ├── mapping.html          # 書式マッピング設定UI（スタンドアロンHTML・本物）
    ├── help.html             # 操作マニュアル（実スクリーンショット入り・約104KB）
    ├── admin.js              # 管理機能JS
    ├── logo.png              # TASUKARUロゴ
    └── ...（その他静的ファイル）
```

---

## 🌐 主要ページ一覧

| URL | 説明 | 備考 |
|-----|------|------|
| `/top` | TOPページ（ダッシュボード） | |
| `/assessment` | AIアセスメント入力 | 面談内容を入力→AI分析 |
| `/case_record` | ケース記録入力 | |
| `/monitoring` | モニタリング記録 | |
| `/vitals` | バイタル記録 | |
| `/calendar` | カレンダー表示 | |
| `/daily_view` | 日次記録ビュー | |
| `/board` | 掲示板 | |
| `/mapping` | **書式マッピング設定** | `send_file('static/mapping.html')`で配信 |
| `/help` | **操作マニュアル** | `send_file('static/help.html')`で配信。実スクリーンショット入り |
| `/manual` | マニュアルページ | |
| `/dev` | 開発者ページ | |
| `/numerology` | 数秘術 | |

### API エンドポイント（主要なもの）
- `/api/assess` — AIアセスメント実行
- `/api/save_assessment` — アセスメント保存
- `/api/patients` — 利用者一覧取得
- `/api/save_calendar` — カレンダー保存
- `/api/tasks/*` — タスク管理系
- `/api/invite_calendar_member` — カレンダーメンバー招待

---

## 🗄 Supabase 構成

| 接続情報 | 値 |
|---------|-----|
| **URL** | `https://abvglnkwtdeoaazyqwyd.supabase.co` |
| **施設コード（デモ）** | `cocokaraplus-5526` |

### 主要テーブル

| テーブル | 内容 |
|---------|------|
| `patients` | 利用者マスタ（user_name, user_kana, care_level, birth_date, gender...） |
| `assessments` | アセスメント結果（ai_change, ai_challenge, target_month, user_name...） |
| `case_records` | ケース記録 |
| `monitoring_records` | モニタリング記録 |
| `admin_settings` | 施設ごとの設定（各種キーと値を保存） |

### ⚠️ admin_settings テーブルのカラム名（重要・ハマりやすい）

```
id, facility_code, key, value, created_at
```

**注意**: 旧ドキュメントに `setting_key` / `setting_value` と書かれている箇所があるが、
実際のカラム名は `key` / `value` が正しい。間違えると `PGRST204` エラーになる。

### Supabaseへの保存パターン（正しいカラム名）

```javascript
await fetch(cfg.supabaseUrl + '/rest/v1/admin_settings', {
  method: 'POST',
  headers: {
    'apikey': cfg.supabaseKey,
    'Authorization': 'Bearer ' + cfg.supabaseKey,
    'Content-Type': 'application/json',
    'Prefer': 'resolution=merge-duplicates'
  },
  body: JSON.stringify({
    facility_code: cfg.facilityCode,
    key: 'field_mapping',       // ← "setting_key" ではなく "key"
    value: JSON.stringify(data) // ← "setting_value" ではなく "value"
  })
});
```

---

## 📊 Google Apps Script（GAS）

| 項目 | 値 |
|------|-----|
| **GASプロジェクトURL** | https://script.google.com/u/0/home/projects/1_3CHezNwUFpBMchQv7cMWCS4qU7R_32glKcDankYrHBuLZdpqOz0OpsL/edit |
| **スプレッドシート（マスター）** | https://docs.google.com/spreadsheets/d/13fAq0ELCyq8w_bryzt-CEpKrzdDdsPyqYd-UYEqLq6Q |

### 実装済み機能（GAS）
- `fillMonitoringFromAssessment()` — モニタリング自動入力（最新）
- `fillMonitoringByMonth()` — モニタリング自動入力（月指定）
- メニュー: `モニタリング自動入力(最新)` / `モニタリング自動入力(月指定)`

---

## ✨ 書式マッピング機能の説明

### 概念
```
TASUKARU（利用者データ）  →  Excelの書式（施設ごとに異なる）
   氏名                  →  セルC10
   フリガナ              →  セルB9
   介護度                →  セルI10
   ...
```

### 仕組み
1. `/mapping` ページで「どのデータをどのセルに入れるか」を設定
2. 設定は `Supabase.admin_settings`（`key='field_mapping'`）に保存
3. GASが設定を読み取り、Excelに自動転記

### `/mapping` の実装詳細
- `app.py`: `send_file('static/mapping.html', mimetype='text/html')` で配信
- `static/mapping.html`: スタンドアロンHTML（Flaskテンプレートではない）
- **重要**: Jinja2テンプレートを通すと `{{` `}}` がエラーになるため `send_file` を使用
- JavaScriptで `window.TASUKARU_CONFIG` を参照してSupabase接続情報を取得

### `/help` の実装詳細（2025-04-18 更新）
- `app.py`: `send_file('static/help.html', mimetype='text/html')` で配信
- `static/help.html`: スタンドアロンHTML（約104KB）
- STEP1〜5の説明に**実際の画面スクリーンショット**をbase64 JPEGで埋め込み済み

#### help.htmlのスクリーンショット差し替え手順（再現方法）
1. `/mapping` ページでブラウザコンソールから `html2canvas` を読み込む
2. 各STEPの状態を再現してキャプチャ → base64データを `window._step1b64` 〜 `_step5b64` に格納
3. Supabase `admin_settings`（`key='help_images_temp'`）にJSON形式で一時保存
4. Cloud ShellのPythonスクリプトで取得 → `static/help.html` のSVGをbase64 JPEGに置換
5. デプロイ

```python
# Cloud Shellで実行するPythonスクリプト例
import json, re, os, urllib.request, subprocess

result = subprocess.check_output([
    'gcloud','run','services','describe','tasukaru-dev',
    '--region=asia-northeast1','--format=json'
], text=True)
svc = json.loads(result)
envs = svc['spec']['template']['spec']['containers'][0]['env']
env_map = {e['name']: e.get('value','') for e in envs}
SUPABASE_URL = env_map['SUPABASE_URL']
SUPABASE_KEY = env_map['SUPABASE_KEY']

req = urllib.request.Request(
    SUPABASE_URL + '/rest/v1/admin_settings?key=eq.help_images_temp&limit=1',
    headers={'apikey': SUPABASE_KEY, 'Authorization': 'Bearer ' + SUPABASE_KEY}
)
data = json.loads(urllib.request.urlopen(req).read())
imgs = json.loads(data[0]['value'])

with open(os.path.expanduser('~/tasukaru/static/help.html')) as f:
    html = f.read()

for key in ['s1','s2','s3','s4','s5']:
    html = re.sub(r'src="data:image/svg\+xml;base64,[^"]*"', f'src="{imgs[key]}"', html, count=1)

with open(os.path.expanduser('~/tasukaru/static/help.html'), 'w') as f:
    f.write(html)
print('Done:', len(html))
```

---

## 🚀 デプロイ手順

```bash
cd ~/tasukaru

# 開発環境（tasukaru-dev）へデプロイ
gcloud run deploy tasukaru-dev \
  --source . \
  --region asia-northeast1 \
  --project tasukaru-production \
  --quiet

# 本番環境（tasukaru）へデプロイ
gcloud run deploy tasukaru \
  --source . \
  --region asia-northeast1 \
  --project tasukaru-production \
  --quiet
```

### Cloud Run サービス一覧（asia-northeast1）

| サービス名 | 用途 | URL |
|-----------|------|-----|
| `tasukaru-dev` | 開発・検証 | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| `tasukaru` | 本番 | https://tasukaru-191764727533.asia-northeast1.run.app |
| `kaigo-ai-app` | 旧サービス（現在は未使用） | — |

### トークン更新（GCS操作時）
```bash
gcloud auth print-access-token > /tmp/tok.txt
```

---

## 📁 ファイル転送の方法

### Cloud ShellへのHTMLアップロード（重要）
**Claudeから直接アップロードは不可**（セキュリティ制限）。

手動手順：
1. Claudeがファイルをチャットにダウンロードリンクとして提供
2. PCにダウンロード
3. Cloud Shell Editor 左パネルのフォルダを**右クリック → Upload...**
4. ファイルを選択してアップロード
5. ターミナルでデプロイ実行

### 大容量データの転送テクニック（2025-04-18 確立）

ブラウザのJSからCloud Shellに直接大容量データを渡せない場合の回避策：
1. JSで `fetch()` を使いSupabase `admin_settings` に一時保存（`key='任意のキー名'`）
2. Cloud ShellのPythonでSupabaseからfetchして処理
3. 処理後は不要データを削除するのが望ましい

### staticファイル（スタンドアロンHTML）の注意
- `static/` 配下のHTMLは `send_file()` で配信する
- `templates/` に置くと Jinja2 が `{{ }}` を変数と解釈してエラーになる

---

## 🌿 Gitブランチ構成

| ブランチ名 | 用途 |
|-----------|------|
| `tasukaru-dev` | **メイン開発ブランチ**（Cloud Run: tasukaru-dev にデプロイ） |
| `tasukaru` | **本番ブランチ**（Cloud Run: tasukaru にデプロイ） |
| `develop` | サブ開発用 |
| `main` | GitHub デフォルトブランチ |
| `cloudrun-test` | テスト用（現在は停滞中） |

### ブランチ変更履歴（2025-04-18）
- `cloudrun-dev` → `tasukaru-dev` にリネーム（ローカル＋リモート）
- `cloudrun` → `tasukaru` にリネーム（ローカル＋リモート）

### GitHub Personal Access Token
- **トークン名**: `tasukaru-cloudshell`
- **有効期限**: 2026-05-18
- **スコープ**: repo（フルコントロール）
- **使用場所**: Cloud Shell の Git 認証

```bash
# Cloud ShellでのGit認証設定（PATが切れたら再発行して再設定）
git remote set-url origin https://<PAT>@github.com/cocokaraplus-max/kaigo-ai-app.git
```

### よく使うGitコマンド

```bash
# ブランチ確認
git branch -a

# 変更をcommit & push（開発ブランチ）
git add -A
git commit -m "変更内容のメッセージ"
git push origin tasukaru-dev

# 本番ブランチにも同じファイルを反映（特定ファイルだけ）
git checkout tasukaru
git checkout tasukaru-dev -- static/help.html
git commit -m "同じ変更内容"
git push origin tasukaru
git checkout tasukaru-dev

# ローカルのREADMEに未コミット変更がある場合
git stash
git pull
git stash pop  # ローカル変更を戻す（不要なら省略）
```

---

## 🛠 開発上の注意事項

### app.py のルート追加パターン

```python
# Flaskテンプレート（Jinja2処理あり）
@app.route('/example')
def example():
    return render_template('example.html')

# スタンドアロンHTML（Jinja2処理なし）
@app.route('/example')
def example():
    return send_file('static/example.html', mimetype='text/html')
```

### 環境変数の取得方法（Cloud Shell Python）

```python
import json, subprocess

result = subprocess.check_output([
    'gcloud','run','services','describe','tasukaru-dev',
    '--region=asia-northeast1','--format=json'
], text=True)
svc = json.loads(result)
envs = svc['spec']['template']['spec']['containers'][0]['env']
env_map = {e['name']: e.get('value','') for e in envs}
# env_map['SUPABASE_URL'], env_map['SUPABASE_KEY'] などで取得
```

---

## 📅 開発ログ（主要マイルストーン）

| 日付 | 内容 |
|------|------|
| 初期 | Flask + Supabase + Cloud Run の基盤構築 |
| 初期 | アセスメント・ケース記録・モニタリング・バイタル等の各種入力ページ実装 |
| 初期 | GAS連携（SupabaseのデータをGoogleスプレッドシートに自動転記） |
| 中期 | GAS: `monitoring.gs` 実装（モニタリング自動入力） |
| 2025-04-17 | `/mapping` ルート追加（書式マッピング設定ページ） |
| 2025-04-17 | `static/mapping.html`（30KB、ドラッグ&ドロップ対応UI）のデプロイ完了 |
| 2025-04-17 | `/help` ルート追加（操作マニュアルページ） |
| 2025-04-17 | `static/help.html`（操作マニュアル、5ステップ解説）のデプロイ完了 |
| 2025-04-18 | `help.html` のSVGプレースホルダー5箇所を実際のスクリーンショット（base64 JPEG）に差し替え |
| 2025-04-18 | Supabase `admin_settings` のカラム名が `key`/`value` であることを確認（旧記述を修正） |
| 2025-04-18 | Cloud Run `tasukaru-dev`（rev: 00209-8hb）・`tasukaru`（rev: 00299-bvs）両方にデプロイ |
| 2025-04-18 | Gitブランチ名変更: `cloudrun-dev`→`tasukaru-dev`、`cloudrun`→`tasukaru`（ローカル＋GitHub） |
| 2025-04-18 | GitHub PAT（`tasukaru-cloudshell`、期限2026-05-18）を発行・Cloud ShellのGit認証を設定 |
| 2025-04-18 | `tasukaru-dev` / `tasukaru` 両ブランチに最新 `help.html` をマージ＆push完了 |
| 2025-04-18 | README.md を全面更新（本ファイル） |

---

## 🔮 今後やること（PENDING）

### 優先度高
- [ ] `patients` テーブルに目標関連カラム追加
  - `goal_short_func` / `goal_short_act` / `goal_short_join`（短期目標）
  - `goal_long_func` / `goal_long_act` / `goal_long_join`（長期目標）
  - 期間カラム
- [ ] `/monitoring` ページの本格実装

### 優先度中
- [ ] TOPページや `/mapping` ページから `/help` へのリンクボタン追加
- [ ] 書式マッピングUI: `mapping.html` をFlask `TASUKARU_CONFIG` と連携して施設情報を自動取得
- [ ] 多施設テンプレート整備（施設ごとに異なるExcel書式への対応）
- [ ] Supabase `admin_settings` の `key='help_images_temp'`（一時データ）を削除

### 優先度低
- [ ] タスク管理機能の拡充
- [ ] 掲示板機能の強化
- [ ] `cloudrun-test` ブランチの整理（リネームまたは削除）

---

## 💡 よく使うコマンド集

```bash
# 作業ディレクトリ
cd ~/tasukaru

# 開発デプロイ
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet

# 本番デプロイ
gcloud run deploy tasukaru --source . --region asia-northeast1 --project tasukaru-production --quiet

# ルート一覧確認
python3 -c "import re; routes=re.findall(r\"@app\.route\('([^']+)'\)\", open('app.py').read()); [print(r) for r in sorted(set(routes))]"

# app.pyのルート確認
grep -n "@app.route\|def " app.py | head -50

# GCSトークン更新
gcloud auth print-access-token > /tmp/tok.txt

# staticフォルダ確認
ls -la static/

# ビルドログ確認
gcloud builds list --limit=3 --region=asia-northeast1

# Cloud Runサービス一覧
gcloud run services list --region=asia-northeast1 --format="value(metadata.name)"

# Gitブランチ確認
git branch -a
```

---

## 🔐 環境変数・秘匿情報

本番環境の環境変数はCloud Runのコンソールで管理。

```bash
# 環境変数一覧を確認
gcloud run services describe tasukaru-dev \
  --region=asia-northeast1 \
  --format=json | python3 -c "
import json,sys
svc=json.load(sys.stdin)
for e in svc['spec']['template']['spec']['containers'][0]['env']:
    print(e['name'],'=',(e.get('value','') or '(secret ref)')[:30])
"
```

主な環境変数:
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `FACILITY_CODE`
- `SECRET_KEY`
- `DEV_PASSWORD`
- `GEMINI_API_KEY`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`

**⚠️ これらをソースコードにハードコードしないこと**

---

## 📌 このREADMEの更新ルール

- 新しい機能を追加したら「開発ログ」と「主要ページ一覧」を更新
- 完了したタスクは「今後やること」から「開発ログ」に移動
- 技術的な重要な決定（アーキテクチャ変更など）は必ず記録
- Supabaseのカラム名など「ハマりやすいポイント」は必ず残す
- 次のClaudeセッションがこのREADMEだけで即座に作業再開できる粒度で書く

---

*最終更新: 2025-04-18*
*記録者: Claude (Anthropic) + 施設担当者*