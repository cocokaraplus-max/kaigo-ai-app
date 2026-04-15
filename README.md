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
12. TOPページの自動更新関数（checkNewRecords等）は**IIFEの外**に定義する

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
- `records`テーブルに**`record_date`カラムは存在しない**（insertに含めるとエラー）

### 取説（manual.html）使用画像
```
tasukaru_top.png       → 通常・笑顔
tasukaru_sestumei.png  → 説明
tasukaru_odoroki2.png  → 驚き
tasukaru_onegai.png    → お願い
tasukaru_ooyorokobi.png → 大喜び
```

```sql
board_posts      -- 投稿本体（is_privateカラムあり）
board_comments   -- コメント
board_reactions  -- リアクション（✅👍など）
board_reads      -- 既読管理
```

---

## ファイル構成

```
kaigo-ai-app/
├── app.py（Flask メイン・全ルーティング・全API 約3100行）
├── utils.py（Gemini AI・Supabase画像/音声アップロード）
├── templates/
│   ├── base.html（SPAルーター・ボトムナビ・PWA・カメラ修正済み）
│   ├── board.html（掲示板ページ 約1060行）
│   ├── manual.html（取説 Ver.3.0）
│   ├── top.html（歯車ボタン・ユーザー設定・履歴自動更新）
│   ├── input.html（記録入力・fetch保存・redirect:manual対応）
│   ├── chat_room.html（Realtime対応・送信音付き）
│   ├── chat_rooms.html（試聴ボタン付きサウンド設定）
│   ├── assessment.html（録音モードCSS・音声保存再生）
│   ├── vitals.html（cameraStream重複修正・全員ボタン修正済み）
│   └── login.html（お名前入力欄追加済み）
└── static/
    └── sw.js（PWA Service Worker v4・バッジAPI対応）
```

---

## 完了した全作業

### ✅ 2026-04-15 更新履歴バグ修正・自動更新追加

**問題の経緯：**
- TOPページの更新履歴に先の日付を指定した記録が常に先頭に表示される問題があった
- 原因：`input_view`で`created_at`に指定日付を入れていたため

**修正内容：**
1. `app.py` / `input_view`：`created_at`を常に現在日時（`datetime.now(tokyo_tz).isoformat()`）に固定
2. `app.py` / `input_view`：`records`テーブルに存在しない`record_date`カラムへのinsertを削除（これがinsert失敗の原因だった）
3. `app.py` / `top`ルート：SELECTから`record_date`を除外（存在しないカラムでエラーになり履歴が0件になっていた）
4. `app.py` / `top`ルート：ソートを`created_at`降順から`id`降順に変更（入力順に並ぶ）
5. `templates/input.html`：`fetch`に`redirect: 'manual'`を追加し、`res.type === 'opaqueredirect'`で保存成功を正確に判定
6. `templates/top.html`：`checkNewRecords`関数を追加（30秒ごとに差分チェックして更新があれば履歴リストを自動更新）

**重要な教訓：**
- `records`テーブルに`record_date`カラムは**存在しない** → insertに含めると保存失敗
- TOPページの自動更新関数はIIFEの**外**に定義する必要がある
- `fetch`でPOSTしてサーバーがリダイレクトを返すと`res.ok=true`になるが保存失敗していることがある → `redirect: 'manual'`で正確に判定

### ✅ Supabase Realtimeによるトーク即時受信
### ✅ 評価ページに音声保存・再生機能
### ✅ TOPページにユーザー設定（歯車ボタン）
### ✅ トーク送信音追加・サウンド試聴ボタン
### ✅ バイタル画面の複数バグ修正
### ✅ カメラボタンSPA遷移バグ修正
### ✅ 通知許可ポップアップ（base.html）
### ✅ 取説（manual.html）Ver.3.0 リニューアル
### ✅ 掲示板機能追加（board.html）

---

## PENDING（未完了・次回対応）

### 🔴 最優先
- [ ] **cloudrun-devのtop.html自動更新を本番（cloudrun）にマージ**
  - `checkNewRecords`関数がIIFEの外に定義済み（cloudrun-devのみ）
  - 本番はまだ古い状態
- [ ] **掲示板にも同様の自動更新を追加**（cloudrun-devで対応予定）

### 🟡 機能追加
- [ ] メニュー並び順カスタマイズ（ユーザー設定から）
- [ ] アップデートログ表示（TOPの歯車横にベルアイコン）
- [ ] 掲示板の`is_private`投稿をapp.pyでフィルタリング（メンション外の人に非表示）

### 🟢 軽微
- [ ] 「たすかる」音声（mp3ファイルが必要）
- [ ] 利用者の曜日設定を現場で登録・確認
- [ ] サウンドテストページの削除（/sound_test）
- [ ] デバッグ用エラー詳細表示を元に戻す（app.pyのexcept節）

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| `cd: kaigo-ai-app: No such file or directory` | すでにkaigo-ai-appにいる | そのまま実行 |
| `error: Your local changes would be overwritten` | .DS_Storeが変更されている | `git stash`してから実行 |
| `INVALID_ARGUMENT` デプロイエラー | 認証切れ | `gcloud auth login`で再認証 |
| 履歴が0件になる | SELECTに存在しないカラムを指定 | カラム名を確認して削除 |
| 記録が保存されない | insertに存在しないカラムを指定 | `record_date`等をinsertから削除 |
| ターミナルが止まる | ヒアドキュメント`<< 'EOF'`が入力待ち | `Ctrl+C`で抜ける |
| Python -cコマンドが文字化け | 日本語コメントがUTF-8エラー | 日本語コメントなしのスクリプトファイルを使う |
| スクリプトファイルが開けない | パスにスペース（`ZIMAX 1`） | `~/Downloads/`に置いて`python3 ~/Downloads/xxx.py`で実行 |

---

## gcloud CLIとは

```
あなたのMac
    ↓ gcloud run deploy
Google Cloud（インターネット上のサーバー）
    ↓
Cloud Run（TASUKARUが動いている場所）
    ↓
https://tasukaru-...run.app
```

---

*最終更新：2026-04-15（更新履歴バグ修正・自動更新追加）*