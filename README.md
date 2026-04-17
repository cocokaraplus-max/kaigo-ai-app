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
| **開発URL（テスト）** | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| **GCPプロジェクト** | `tasukaru-production` |
| **Cloud Runサービス（本番）** | `tasukaru` |
| **Cloud Runサービス（開発）** | `tasukaru-dev` |
| **リージョン** | `asia-northeast1`（東京） |
| **最新リビジョン（本番）** | `tasukaru-00299-bvs`（2025-04-18時点） |
| **最新リビジョン（開発）** | `tasukaru-dev-00214-9jz`（2025-04-18時点） |

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
kaigo-ai-app/  ← ローカルMacのフォルダ名（パス: /Users/ZIMAX 1/Desktop/kaigo-ai-app）
├── app.py                    # Flaskメインアプリ（全ルート・API定義）
├── Dockerfile                # Cloud Run用コンテナ定義
├── requirements.txt          # Pythonパッケージ
├── templates/
│   ├── base.html             # 共通レイアウト（ヘッダー・ナビ）
│   ├── input.html            # 記録入力 ★音声入力改善済み（一時停止・再開・エラー強化）
│   ├── assessment.html       # AIアセスメント入力画面
│   ├── case_record.html      # ケース記録入力
│   ├── monitoring.html       # モニタリング記録
│   ├── vitals.html           # バイタル記録
│   ├── calendar.html         # カレンダー表示
│   ├── daily_view.html       # 日次記録ビュー
│   ├── board.html            # 掲示板
│   └── ...（その他多数）
└── static/
    ├── mapping.html          # 書式マッピング設定UI（スタンドアロンHTML）
    ├── help.html             # 操作マニュアル（実スクリーンショット入り・約104KB）
    ├── sw.js                 # Service Worker（オフライン対応・キャッシュ管理）
    ├── admin.js              # 管理機能JS
    ├── logo.png              # TASUKARUロゴ
    └── ...（その他静的ファイル）
```

---

## 🌐 主要ページ一覧

| URL | 説明 | 備考 |
|-----|------|------|
| `/top` | TOPページ（ダッシュボード） | |
| `/input` | **記録入力** | 音声入力・一時停止・再開機能付き ★改善済み |
| `/assessment` | AIアセスメント入力 | 面談内容を入力→AI分析 |
| `/case_record` | ケース記録入力 | |
| `/monitoring` | モニタリング記録 | |
| `/vitals` | バイタル記録 | |
| `/calendar` | カレンダー表示 | |
| `/daily_view` | 日次記録ビュー | |
| `/board` | 掲示板 | |
| `/mapping` | **書式マッピング設定** | `send_file('static/mapping.html')`で配信 |
| `/help` | **操作マニュアル** | 実スクリーンショット入り |

### API エンドポイント（主要なもの）
- `/api/assess` — AIアセスメント実行
- `/api/save_assessment` — アセスメント保存
- `/api/patients` — 利用者一覧取得
- `/api/transcribe` — 音声文字起こし（POST: audio_data, audio_mime）
- `/api/save_calendar` — カレンダー保存
- `/api/tasks/*` — タスク管理系

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
| `assessments` | アセスメント結果 |
| `case_records` | ケース記録 |
| `monitoring_records` | モニタリング記録 |
| `admin_settings` | 施設ごとの設定 |

### ⚠️ admin_settings テーブルのカラム名（重要・ハマりやすい）

```
id, facility_code, key, value, created_at
```

`setting_key` / `setting_value` ではなく `key` / `value` が正しい。間違えると `PGRST204` エラーになる。

---

## 📊 Google Apps Script（GAS）

| 項目 | 値 |
|------|-----|
| **GASプロジェクトURL** | https://script.google.com/u/0/home/projects/1_3CHezNwUFpBMchQv7cMWCS4qU7R_32glKcDankYrHBuLZdpqOz0OpsL/edit |
| **スプレッドシート（マスター）** | https://docs.google.com/spreadsheets/d/13fAq0ELCyq8w_bryzt-CEpKrzdDdsPyqYd-UYEqLq6Q |

### 実装済み機能（GAS）
- `fillMonitoringFromAssessment()` — モニタリング自動入力（最新）
- `fillMonitoringByMonth()` — モニタリング自動入力（月指定）

---

## 🎤 音声入力機能の仕様（2025-04-18 改善版）

### 実装ファイル
- `templates/input.html`（音声UI・JS）
- `app.py` の `/api/transcribe` エンドポイント（バックエンド文字起こし）

### 音声入力フロー
```
録音開始ボタン
    ↓ getUserMedia() でマイク取得
    ↓ MediaRecorder.start(500) ← 500ms毎にデータ確保（取りこぼし防止）
録音中（赤ボタン）
    ↓ ⏸一時停止ボタン → isPaused=true → onstopでblob保存
    ↓ ▶再開ボタン → 新しいMediaRecorderで続き録音
    ↓ ×回繰り返し可能（allAudioBlobsに累積）
録音終了ボタン
    ↓ buildFinalAudio() → 全blobを結合 → base64化
AIテキスト変換ボタン
    ↓ POST /api/transcribe {audio_data, audio_mime}
    ↓ 失敗時: 2回自動リトライ / 60秒タイムアウト
    ↓ 成功: テキストエリアに追記（上書きではなく）
```

### 改善内容（旧→新）

| 項目 | 旧 | 新 |
|------|-----|-----|
| 一時停止 | なし | ⏸ボタンで一時停止→▶で再開 |
| 複数セグメント録音 | 不可 | allAudioBlobsに累積・結合 |
| エラー表示 | `alert('AI変換に失敗しました')` のみ | 原因を画面に表示 |
| リトライ | なし | 失敗時2回自動リトライ |
| タイムアウト | なし | 60秒で自動タイムアウト |
| データ保護 | `start()` のみ | `start(500)` で500ms毎に確保 |
| テキスト | 上書き | 既存テキストに追記 |

---

## 🚀 デプロイ手順

### ローカルMac から直接デプロイ（推奨・2025-04-18 確立）

```bash
# 作業フォルダ: /Users/ZIMAX 1/Desktop/kaigo-ai-app

# テスト環境へデプロイ
gcloud run deploy tasukaru-dev \
  --source . \
  --region asia-northeast1 \
  --project tasukaru-production \
  --quiet

# 本番環境へデプロイ
gcloud run deploy tasukaru \
  --source . \
  --region asia-northeast1 \
  --project tasukaru-production \
  --quiet
```

### ローカルMac の gcloud セットアップ（初回のみ）

```bash
brew install google-cloud-sdk
gcloud auth login
gcloud config set project tasukaru-production
```

### ⚠️ 必ずテスト環境で確認してから本番に反映すること

```
コード修正（VSCode）
    ↓
git add & commit & push（GitHubにバックアップ）
    ↓
gcloud run deploy tasukaru-dev ...（テスト環境で確認）
    ↓ 問題なければ
gcloud run deploy tasukaru ...（本番環境に反映）
```

### Cloud Shell からデプロイする場合（サブ手段）

```bash
cd ~/tasukaru
git stash && git pull
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet
```

---

## 🌿 Gitブランチ構成

| ブランチ名 | 用途 |
|-----------|------|
| `tasukaru-dev` | **メイン開発ブランチ**（テスト環境） |
| `tasukaru` | **本番ブランチ** |
| `develop` | サブ開発用 |
| `main` | GitHub デフォルトブランチ |
| `cloudrun-test` | テスト用（停滞中） |

### ブランチ変更履歴（2025-04-18）
- `cloudrun-dev` → `tasukaru-dev` にリネーム
- `cloudrun` → `tasukaru` にリネーム

### GitHub Personal Access Token
- **トークン名**: `tasukaru-cloudshell`
- **有効期限**: 2026-05-18
- **スコープ**: repo
- **用途**: Cloud Shell での Git 認証

```bash
# PATが切れたら再発行して再設定
git remote set-url origin https://<PAT>@github.com/cocokaraplus-max/kaigo-ai-app.git
```

### よく使うGitコマンド

```bash
# 変更をcommit & push
git add -A
git commit -m "変更内容のメッセージ"
git push origin tasukaru-dev

# 本番ブランチにも特定ファイルを反映
git checkout tasukaru
git checkout tasukaru-dev -- templates/input.html
git commit -m "本番反映: 変更内容"
git push origin tasukaru
git checkout tasukaru-dev
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

`static/` のHTMLには `{{ }}` が含まれる場合があるため `send_file` で配信。
`templates/` に置くと Jinja2 が `{{ }}` を変数と解釈してエラーになる。

### ローカルVSCodeからCloud Shellへの大容量データ転送

ターミナルのheredocは長いスクリプトでタイムアウトする。回避策：
1. **Pythonスクリプトをファイルとしてダウンロード** → ローカルで `python3 fix_xxx.py`
2. **Supabase経由**: JSで `admin_settings` に一時保存 → Cloud Shell Pythonで取得・処理
3. **Cloud Shell Editorのアップロード**: 左パネルフォルダを右クリック → Upload

---

## 💾 バックアップ

### USB バックアップ
- **USBドライブ名**: `HIRO'sUSB`

```bash
cp -r "/Users/ZIMAX 1/Desktop/kaigo-ai-app" "/Volumes/HIRO'sUSB/TASUKARU_backup_YYYYMMDD"
```

### GitHub バックアップ
- **リポジトリ**: https://github.com/cocokaraplus-max/kaigo-ai-app
- `tasukaru-dev` ブランチが最新の開発状態

---

## 📅 開発ログ（更新履歴）

| 日付 | 内容 |
|------|------|
| 初期 | Flask + Supabase + Cloud Run の基盤構築 |
| 初期 | アセスメント・ケース記録・モニタリング・バイタル等の各種入力ページ実装 |
| 初期 | GAS連携（SupabaseのデータをGoogleスプレッドシートに自動転記） |
| 中期 | GAS: `monitoring.gs` 実装（モニタリング自動入力） |
| 2025-04-17 | `/mapping` ルート追加・`static/mapping.html` デプロイ完了 |
| 2025-04-17 | `/help` ルート追加・`static/help.html` デプロイ完了 |
| 2025-04-18 | `help.html` のSVGプレースホルダー5箇所を実際のスクリーンショットに差し替え |
| 2025-04-18 | Supabase `admin_settings` のカラム名が `key`/`value` であることを確認（旧記述修正） |
| 2025-04-18 | Cloud Run ブランチ名変更: `cloudrun-dev`→`tasukaru-dev`、`cloudrun`→`tasukaru` |
| 2025-04-18 | GitHub PAT（`tasukaru-cloudshell`、期限2026-05-18）発行・Cloud Shell Git認証設定 |
| 2025-04-18 | README.md 全面更新 |
| 2025-04-18 | **`templates/input.html` 音声入力を大幅改善** |
| | ・一時停止（⏸）→ 再開（▶）機能を追加 |
| | ・保存エラーの詳細表示（マイク権限・サーバーエラー・タイムアウト等） |
| | ・失敗時の自動リトライ（最大2回）+ 60秒タイムアウト |
| | ・500msごとのデータ確保でデータ取りこぼし防止 |
| | ・文字起こし結果をテキストエリアに追記（上書きではなく） |
| | ・テスト環境（tasukaru-dev-00212-bnc）で動作確認済み |
| 2025-04-18 | **ローカルMac（/Users/ZIMAX 1/Desktop/kaigo-ai-app）からの直接デプロイを確立** |
| | ・Google Cloud SDK（gcloud）をMacにインストール |
| | ・`gcloud auth login` で認証済み |
| | ・`gcloud config set project tasukaru-production` 設定済み |
| | ・ローカルから直接 `gcloud run deploy` でCloud Runにデプロイ可能になった |
| | ・Cloud Shellを経由せずにデプロイできるためワークフローが大幅にシンプル化 |
| | ・テスト環境デプロイ確認済み（revision: tasukaru-dev-00214-9jz） |

---

## 🔮 今後やること（PENDING）

### 優先度高
- [ ] **音声入力改善を本番（`tasukaru`）にも反映**
  ```bash
  git checkout tasukaru
  git checkout tasukaru-dev -- templates/input.html
  git commit -m "feat: voice input pause/resume + error handling"
  git push origin tasukaru
  gcloud run deploy tasukaru --source . --region asia-northeast1 --project tasukaru-production --quiet
  git checkout tasukaru-dev
  ```
- [ ] `patients` テーブルに目標関連カラム追加
  - `goal_short_func` / `goal_short_act` / `goal_short_join`（短期目標）
  - `goal_long_func` / `goal_long_act` / `goal_long_join`（長期目標）
  - 期間カラム
- [ ] `/monitoring` ページの本格実装

### 優先度中
- [ ] `assessment.html` / `manual.html` の音声入力も同様に改善
- [ ] TOPページや `/mapping` から `/help` へのリンクボタン追加
- [ ] 多施設テンプレート整備
- [ ] Supabase `admin_settings` の `key='help_images_temp'`（一時データ）を削除

### 優先度低
- [ ] タスク管理機能の拡充
- [ ] 掲示板機能の強化
- [ ] `cloudrun-test` ブランチの整理

---

## 💡 よく使うコマンド集

```bash
# ===== ローカルMacから（推奨）=====

# テスト環境デプロイ
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet

# 本番デプロイ
gcloud run deploy tasukaru --source . --region asia-northeast1 --project tasukaru-production --quiet

# USBバックアップ
cp -r "/Users/ZIMAX 1/Desktop/kaigo-ai-app" "/Volumes/HIRO'sUSB/TASUKARU_backup_$(date +%Y%m%d)"

# ===== Cloud Shell から（サブ）=====

cd ~/tasukaru
git stash && git pull
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet

# Cloud Runサービス一覧
gcloud run services list --region=asia-northeast1 --format="value(metadata.name)"

# 環境変数確認
gcloud run services describe tasukaru-dev --region=asia-northeast1 --format=json | python3 -c "
import json,sys
svc=json.load(sys.stdin)
for e in svc['spec']['template']['spec']['containers'][0]['env']:
    print(e['name'],'=',(e.get('value','') or '(secret ref)')[:30])
"
```

---

## 🔐 環境変数・秘匿情報

本番環境の環境変数はCloud Runのコンソールで管理。

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
- 技術的な重要な決定は必ず記録
- Supabaseのカラム名など「ハマりやすいポイント」は必ず残す
- 次のClaudeセッションがこのREADMEだけで即座に作業再開できる粒度で書く

---

*最終更新: 2025-04-18*
*記録者: Claude (Anthropic) + 施設担当者*