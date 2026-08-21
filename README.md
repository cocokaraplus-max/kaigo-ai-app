# TASUKARU 開発ドキュメント

介護記録システム「TASUKARU」の開発引き継ぎドキュメントです。
Session 56 までの完全な軌跡、技術的知見、作業方法論を記載しています。

新しいAIとのチャットを開始する際は、このREADMEと `SESSION_64_HANDOFF.md` を必ず読んでください。

---

## プロジェクト概要

| 項目 | 内容 |
|---|---|
| **プロジェクト名** | TASUKARU（助かるu） |
| **概要** | 介護施設向けケース記録・バイタル管理システム |
| **リポジトリ** | cocokaraplus-max/kaigo-ai-app |
| **ローカルパス** | /Users/ZIMAX 1/dev/kaigo-ai-app/ |
| **開発ブランチ** | tasukaru-dev |
| **本番ブランチ** | tasukaru |
| **dev URL** | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| **本番URL** | https://tasukaru-191764727533.asia-northeast1.run.app |
| **技術スタック** | Python/Flask, Supabase, Cloud Run, Jinja2 |
| **dev Supabase Project** | otjevnmoycnvaxeltrtj（facility_code: DEMO001） |
| **本番Supabase Project** | abvglnkwtdeoaazyqwyd（facility_code: cocokaraplus-5526） |
| **Cloud Run環境変数** | GEMINI_API_KEY, ANTHROPIC_API_KEY（設定済み・直接記載禁止） |
| **API Key形式** | [REDACTED_GEMINI_###] / [REDACTED_ANTHROPIC_###]（コード内には記載しない） |

---

## 生活機能チェック実施忘れアラート（案A）実装 2026-06-06  <!-- lifecheck-alert-impl-2026-06-06 -->

生活機能チェック（様式3-2）の実施忘れを検知してTOPでアラート表示する機能（案A）を新規実装。**本番反映済み**（本番マージ `1eaf299`）。

### データモデル
新テーブル `life_check_appointments`。`UNIQUE(facility_code, patient_id, target_ym)`。`status` = unassigned / scheduled / done。`calendar_event_id` は **uuid型**（本番は最初からuuid、DEVはbigint→uuidに変更済み）。

### 結合キー
`life_function_checks.patient_id` == `get_patients()` の `"id"` == `patient_profiles.id`（いずれUUID）。

### 主要ルート/API（app.py、マーカー lifecheck-alert-api-v1）
- `GET /api/life_check_alerts`：在籍者（`is_discontinued` 除外）の最新 `check_date` を見て、未評価=当月対象、前回から3か月超で対象を算出し動的補充。scheduled行の `calendar_event_id` 実在確認で予定削除を検知しunassignedに戻す（orphan-v3）。countはunassignedのみ（fix-v2）。
- `POST /api/life_check_assign`：担当者＋予定日でscheduled化。`calendar_events` へ休み連絡と同じ作法で相乗り insert（`color=#1976d2` で区別）。`prev_event_id` があれば update して二重イベント防止（fix-v2）。

### TOPカード（top.html、マーカー top-lifecheck-alert-v1）
更新期限切れ（`never_checked=false`）を主役、未着手（`never_checked=true`）を折りたたみ5件＋「他N名」。ティール系 `#00897b`。task-accordionと同じ開閉。対象0名なら非表示。

### マーカー一覧
`lifecheck-alert-api-v1` / `top-lifecheck-alert-v1` / `lifecheck-alert-fix-v2` / `lifecheck-alert-orphan-v3`。

### 検証
DEV/本番とも実機検証済み（判定4分岐・冪等・二重防止・予定削除検知・本番alerts読み取り）。本番は現在72名全員未着手（overdue 0）で正常。

### 本番マージ
`1eaf299`。

### 残タスク（次セッション）
- 案B（`/life_check` 内の利用者リストに対象者バッジ表示）未着手。同じ `/api/life_check_alerts` を流用予定。
- DEVのダミーデータ（life_function_checks 4件＋appointments行）は本番未投入・影響なし。掃除は任意。


## 生活機能チェックシート（様式3-2）実装 2026-06-06  <!-- lifecheck-impl-2026-06-06 -->

介護の生活機能チェックシート（様式3-2）を新規実装。**本番反映済み**（本番マージ `d031d95`、DB作成済み）。

### データモデルの設計判断（重要）
前任のADL=Barthel点数(integer)設計と、様式3-2の本来の4段階評価が食い違っていた。一次資料（厚労省）を確認し、項目ごとに最も情報量の多い形で持つ「理想形」に確定:
- **ADL10項目（Barthel対象）= Barthel正式区分の点数(integer)** を主データ。点数→4段階は導出可能。許容点数: 食事10/5/0、移乗15/10/5/0、整容5/0、トイレ10/5/0、入浴5/0、移動15/10/5/0、階段10/5/0、更衣10/5/0、排便10/5/0、排尿10/5/0（満点100）。
- **車椅子・IADL3・基本動作5 = 4段階レベル(text)** independent/watch/partial/full。
- 全19項目に 課題有無(_issue boolean) / 環境(_env text) / 状況メモ(_note text)。
- 紙の様式3-2もLIFE提出も施設内推移も、この1つの生データから導出する方針。

### 機能
- 入力ページ `/life_check`: 利用者検索、Barthel区分ボタン（ADL）、4段階ボタン、課題有無、環境/状況メモ、リアルタイム合計点、評価履歴。
- 基本情報の自動入力（患者マスタ優先）: 介護度/生年月日/性別。性別はマスタ表記「女性/男性/その他」に統一（patient_profilesに登録があれば自動入力）。介護度に「事業対象者」あり。
- 評価者はログイン職員名を初期値。職種は6択（管理者/生活相談員/機能訓練指導員/看護職員/介護職員/その他=自由入力）。
- 過去評価の編集・削除（本人または管理者）。編集時は利用者名含め完全復元し `.page-wrapper` を上端へスクロール。
- AI相談（補助型）: 項目ごとに観察状況を渡すと、根拠/論点整理/候補レベル/確認ポイント/記載案をJSONで返す。候補タップで選択に反映、記載案はメモに反映。回答後はアコーディオンで自動折り畳み。**最終判定は職員**。

### DBテーブル
`life_function_checks`（112カラム）。主キー `id`(uuid)、upsartキー `UNIQUE(facility_code, patient_id, check_date)`。本番にも同一スキーマを作成済み（`create_life_function_checks_full.sql`）。

### 主要ルート/API
`/life_check`（ページ） / `/api/save_life_check`（保存・Barthel点数検証） / `/api/life_check_history`（履歴） / `/api/delete_life_check`（削除・本人or管理者） / `/api/life_assist`（AI相談・補助型）。

### コミット（dev f288abd→70c5cab、本番マージ d031d95）
f288abd ルート+保存API拡張 / e0cd26f 入力UI完全版 / eaa65e1 ボタン縦積み+合計バー位置 / 95bd466 マスタ自動入力 / c183c45 編集削除+削除API / 3bee65b 評価者/職種 / d1c0df3 性別/介護度マスタ整合 / b424c5b AI相談API+UI / ff285c3 AI相談アコーディオン+編集バナー / a21109b 編集時の利用者名復元 / 70c5cab 編集スクロールを.page-wrapper対応。

### 残タスク（次セッション）
- **メニュー導線が未追加**（現状 `/life_check` はURL直打ちのみ）。base.htmlのbottom-navとmovableHrefs(3箇所)に追加が必要。
- 3か月アラート登録（保存時に+3か月をスケジュール登録、TOP表示）。
- 様式3-2の印刷出力。
- LIFE提出CSV出力（別紙Excel待ち・LIFE移行期で保留）。

## Session 56 での主な作業

### 完了したフィーチャー

#### 1. 体温一括入力のUI完成（vitals.html）
- **一時停止/再開ボタン**: `MediaRecorder.pause()/resume()` を使用
- **30秒タイマー削除**: 無制限録音に対応
- **確認ダイアログ**: 「N回目のデータとして保存します。よろしいですか？」
- **回数セレクト拡張**: 10回目まで対応
- **ボタンラベル連動**: セレクト値に応じて表示更新
- **カード自動展開**: 体温フィールド入力前に利用者カードを自動展開
- **フィールド自動クリア**: 保存後に入力値をリセット

**UI構造:**
```
[録音前] #bulk-temp-btn（オレンジ・"N回目 体温一括入力"）
         ↓
[録音中] #bulk-rec-bar（灰色バー）
    ├─ #bulk-pause-btn（一時停止/再開テキスト）
    ├─ #bulk-wave（波形アニメ）
    └─ #bulk-stop-btn（赤ボタン・停止・解析）
         ↓
[解析中] "AI解析中..."表示
         ↓
[完了] 各利用者カード展開 → 体温フィールドに自動セット
```

**技術的ポイント:**
- IIFEスコープ内の関数を `window.pauseBulkTempVoice` で公開
- BUTTON要素に変更（iOS タップ対応）
- 録音中の赤点アニメーション：一時停止時に `animation: none`

---

#### 2. カレンダー・休み連絡バグ修正（3つの修正）

**バグ1: イベントID型不一致による二重登録（修正済み）**
- **原因**: `editingEventId`（string）と `ALL_EVENTS[].id`（number）の `===` 厳密比較
- **影響**: `findIndex()` が -1 を返す → `push()` で新規追加 → 二重表示
- **修正**: `String(e.id) === String(editingEventId)` で統一
- **ファイル**: calendar.html（1070行周辺のfindIndex箇所）

**バグ2: 画面上の一時的な二重表示（修正済み）**
- **原因**: JS側の`saveEvent()`後にALL_EVENTSを古いpayloadで更新
- **影響**: リロード前は2つ表示、リロード後は1つ（DB正常）
- **修正**: String()変換強化＋二重チェック
- **症状**: iPhoneで操作直後に同じイベントが2つ見える（リロードで正常）

**バグ3: memoの日付が書き換わらない（修正済み）**
- **原因**: サーバー側でmemoを再生成しても、JSが古いpayload.memoを表示
- **処理フロー**:
  1. JS: 日付を変更してsaveEvent()を呼ぶ
  2. サーバー: calendar_events.updateとmemo再生成（新しい日付）
  3. JS: レスポンスのmemoが古い日付のまま → ALL_EVENTSが古い値で更新
- **修正**: レスポンスに `updated_memo` を含め、JS側で反映
  ```python
  # app.py 2881行
  updated_ev = supabase.table("calendar_events").select("memo").eq("id", event_id).execute()
  updated_memo = updated_ev.data[0]["memo"] if updated_ev.data else payload.get("memo", "")
  return jsonify({"status": "success", "id": event_id, "memo": updated_memo})
  ```
  ```javascript
  // calendar.html saveEvent後
  const serverMemo = data.memo !== undefined ? data.memo : payload.memo;
  ALL_EVENTS[idx] = {...ALL_EVENTS[idx], ...payload, id:editingEventId, memo:serverMemo};
  ```

---

#### 3. その他の改善

**出納帳（ledger.html）**
- 編集・削除ボタンの `box-sizing` 修正（padding含む）
- FABボタン位置: `bottom: 140px` に調整

**利用者カードUI**
- orderセレクト: `font-size: 0.7rem`, `opacity: 0.7`
- summaryHtml: `font-size: 0.68rem`, `color: #b0b8c1`

---

## AI開発スタイル（これを厳密に守ること）

### 1. コード確認フロー

すべての修正は以下の流れで行う：

```
[修正が必要] 
  ↓
[確認用Pythonスクリプト作成] 
  → 現状のコードを読み取る
  → 該当箇所を出力して確認
  ↓
[修正スクリプト作成]
  → 明確な修正ポイントをPythonで自動化
  → バックアップ自動作成
  ↓
[ダウンロード → 実行] 
  → /mnt/user-data/outputs/ から present_files で提示
  → ユーザーがダウンロードして実行
  ↓
[デプロイ]
  → git add/commit/push
```

**決して「たぶんこうなっているはず」で修正しない。必ずコードを確認してから。**

### 2. Pythonパッチスクリプト方式

```python
#!/usr/bin/env python3
import os, shutil
from datetime import datetime

FILE = "/Users/ZIMAX 1/dev/kaigo-ai-app/templates/calendar.html"
BACKUP = f"{FILE}.bak_修正内容_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(FILE, BACKUP)

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 修正
old = "古いコード"
new = "新しいコード"

if old in content:
    content = content.replace(old, new, 1)
    print("OK: 修正完了")
else:
    print("WARNING: 該当箇所が見つかりません")

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\nバックアップ: {BACKUP}")
print("\nデプロイコマンド:")
print("cd '/Users/ZIMAX 1/dev/kaigo-ai-app' && git add ... && git commit -m '...' && git push origin tasukaru-dev")
```

**重要な制約:**
- ターミナルのヒアドキュメント（`cat << 'EOF'`）は**絶対に使わない**（文字化けする）
- 日本語テキストはUnicode（`\uXXXX`）エスケープで記述
- 修正は1ファイル1つのみ（複数ファイルは別々に実行）

### 3. ブランチ・デプロイ運用

```bash
# 開発
git checkout tasukaru-dev
# ← 修正作業
git add [file]
git commit -m "fix: description"
git push origin tasukaru-dev  # 2〜3分で自動反映

# 確認（Chrome または iPhone）
# ← dev環境で動作確認

# 本番マージ（確認後）
git checkout tasukaru
git merge tasukaru-dev
git push origin tasukaru
git checkout tasukaru-dev
```

**devで「リロード」を必ずする（Service Workerキャッシュ対策）:**
```javascript
navigator.serviceWorker.getRegistrations().then(r=>r.forEach(sw=>sw.unregister()))
```
その後ページを再読み込み。

### 4. Chrome連携（Claude in Chrome）での確認

- dev環境のURLで操作テスト
- JavaScriptを直接実行してデバッグ可能
- **マイク・カメラは実際には使えない** → 音声系はiPhone実機で確認
- console.logを読み取れる
- fetchレスポンスを監視可能

### 5. バックアップファイル管理

パッチスクリプトは自動的に `.bak_XXXXX` ファイルを作成。
これらはgit管理対象外（`.gitignore`推奨）：

```
*.bak_*
app.py.bak_*
templates/*.bak_*
```

定期的に削除:
```bash
rm -f templates/*.bak_* app.py.bak_*
```

---

## プロジェクト構造

```
kaigo-ai-app/
├── app.py                       # Flaskメインアプリ（7000行超）
├── templates/
│   ├── vitals.html              # バイタル測定ページ（4100行超・最重要）
│   ├── calendar.html            # カレンダーページ
│   ├── input.html               # 記録入力ページ
│   ├── ledger.html              # 出納帳ページ
│   ├── daily_view.html          # ケース記録閲覧
│   └── base.html                # 基本テンプレート
├── static/
│   ├── sw.js                    # Service Worker（CACHE_VERSION: tasukaru-v8）
│   ├── style.css
│   └── ...
├── README.md                    # このファイル
├── SESSION_57_HANDOFF.md        # 最新セッション引き継ぎ
└── .gitignore                   # バックアップ等の除外

重要なファイルサイズ:
- vitals.html: 4100行（3-4分でデプロイ）
- app.py: 7000行（REST API・DBロジック）
- calendar.html: 2600行（IIFEラップのJSコード）
```

---

## vitals.html の技術知識（最重要）

### IIFEスコープの問題と解決策

メインスクリプトが `(function(){...})()` でラップされている理由：
- グローバルスコープの汚染防止
- 変数スコープの隔離
- 処理の順序制御

**問題**: IIFE内の関数を外部（HTMLのonclick等）から呼べない

**解決**: window に公開

```javascript
// IIFE内
const pauseBulkTempVoice = async function() { ... };
window.pauseBulkTempVoice = pauseBulkTempVoice;  // ← 公開

// HTML
<button onclick="pauseBulkTempVoice()">一時停止</button>  // ← 呼べる
```

**公開済み関数一覧（vitals.html）:**
- `toggleBulkTempVoice` - 体温一括入力の録音開始/停止
- `pauseBulkTempVoice` - 一時停止/再開
- `stopBulkTempVoice` - 録音停止
- `sendBulkTempVoice` - 音声解析送信
- `updateBulkTempLabel` - 回数セレクト変更時のラベル更新
- `pickVoiceMime` / `mimeToExt` - 音声フォーマット判定
- `cleanupBulkTempStream` / `cleanupMemoVoiceStream` - ストリーム後片付け
- `saveVital` - バイタル保存

### 体温一括入力の処理フロー（Session 56最終版）

```
【状態1: 待機中】
  表示: #bulk-temp-btn（オレンジボタン）
  ボタンテキスト: "青木様 1回目 体温一括入力" など

  ↓ ボタンクリック → toggleBulkTempVoice()

【状態2: 録音中】
  表示: #bulk-rec-bar
  構成:
    - #bulk-rec-dot: 赤点（animation: pulse）
    - #bulk-rec-lbl: "録音中"
    - #bulk-wave: 波形アニメーション
    - #bulk-pause-btn: "一時停止"ボタン
    - #bulk-stop-btn: "停止・解析"ボタン（赤）
  
  MediaRecorder.state: "recording"

  ↓ 一時停止ボタンクリック → pauseBulkTempVoice()

【状態3: 一時停止中】
  表示: #bulk-rec-bar（変更なし）
  #bulk-rec-dot: animation: none（点滅停止）
  #bulk-rec-lbl: "一時停止中"
  #bulk-pause-btn: "再開"に変更
  
  MediaRecorder.state: "paused"

  ↓ 再開ボタンクリック → pauseBulkTempVoice()

【状態4: 停止・解析中】
  表示: #bulk-rec-bar（非表示）
  メッセージ: "AI解析中..."
  
  ↓ 解析完了

【状態5: 完了】
  各利用者カード: 自動展開
  v-temperature-{id}フィールド: 自動入力
  #bulk-temp-btn: 再び表示
  状態1に戻る
```

### 重要な技術制約

- **iOS Safari**: `MediaRecorder.pause()` 非対応の場合あり（Chrome/Androidは動作確認済み）
- **無制限録音**: 30秒タイマー削除したため、手動停止まで続く
- **フィールドの自動クリア**: 保存後に `['bp_high','bp_low','pulse','temperature','spo2','note']` をリセット

---

## カレンダー・休み連絡連携の完全フロー

### 処理シーケンス

**1. 記録入力で「休み連絡」を保存（input.html → app.py /api/save_record）**

```
記録入力フォーム
├─ 利用者: 青木 利夫
├─ カテゴリ: 休み連絡
├─ 連絡者: 家族
├─ 休み期間: 2026-05-28〜2026-05-28
└─ 保存

↓ app.py /api/save_record (759行)

records テーブルに INSERT
├─ category: "休み連絡"
├─ leave_date_start: "2026-05-28"
├─ leave_date_end: "2026-05-28"
├─ leave_reporter_type: "family"
└─ content: "5月28日はお休みと家族から連絡がありました。"

↓ 同時に calendar_events テーブルに INSERT

calendar_events テーブルに INSERT
├─ title: "青木 利夫様 お休み"
├─ event_date: "2026-05-28"
├─ end_date: "2026-05-28"
├─ sticker: "🌸"
├─ color: "#ff5722"
└─ memo: "5月28日はお休みと家族から連絡がありました。"

↓ records と calendar_events をリンク

records.calendar_event_id = calendar_events.id
```

**2. カレンダーからイベント日付を変更（calendar.html → app.py /api/save_calendar_event）**

```
カレンダー表示
5/28: "青木 利夫様 お休み"

ユーザー: イベントクリック → 編集モーダル → 日付を5/30に変更 → 保存

↓ saveEvent() → fetch('/api/save_calendar_event')

サーバー処理:
1. calendar_events UPDATE
   ├─ event_date: "2026-05-30"
   ├─ end_date: "2026-05-30"
   └─ memo: "5月30日はお休みと家族から連絡がありました。"（再生成）

2. calendar_event_id で対応する records を取得

3. records UPDATE
   ├─ leave_date_start: "2026-05-30"
   ├─ leave_date_end: "2026-05-30"
   └─ content: "5月30日はお休みと家族から連絡がありました。"（再生成）

4. レスポンス
   {
     "status": "success",
     "id": "イベントID",
     "memo": "5月30日はお休みと家族から連絡がありました。"  ← 新しい日付
   }

↓ クライアント処理

JS: ALL_EVENTS を更新
const serverMemo = data.memo;
ALL_EVENTS[idx].memo = serverMemo;  ← サーバーの新しいmemoで更新
ALL_EVENTS[idx].event_date = "2026-05-30";

renderCalendar()

5/28: 空
5/30: "青木 利夫様 お休み"（1つだけ）
```

**3. カレンダーからイベント削除**

```
カレンダーから削除ボタン → API /api/delete_calendar_event

サーバー:
1. calendar_events DELETE
2. calendar_event_id でrecordsを特定
3. records.calendar_event_id = NULL
```

### バグ修正の詳細

| バグ | 原因 | 修正内容 | 修正ファイル | 修正日 |
|---|---|---|---|---|
| ID型不一致 | `editingEventId`(str) === `ALL_EVENTS.id`(num) | String()変換で統一 | calendar.html | 2026-05-20 |
| 画面二重表示 | JS側が古いpayloadでALL_EVENTS更新 | String()強化＋二重チェック | calendar.html | 2026-05-20 |
| memo日付未更新 | サーバーmemoをJS側に反映していない | レスポンスにmemo含めて反映 | app.py / calendar.html | 2026-05-20 |

---

## Service Worker & キャッシュ問題

### CACHE_VERSION

`static/sw.js` の CACHE_VERSION: `tasukaru-v8`

デプロイ後に古いバージョンがキャッシュに残ることが多い。

### 確認時のキャッシュクリア方法

**Chrome:**
```javascript
navigator.serviceWorker.getRegistrations().then(r=>r.forEach(sw=>sw.unregister()))
```
実行後、ページをリロード。

**iPhone Safari:**
設定 → Safari → 履歴とWebサイトデータを消去

---

## Cloud Runログ確認コマンド

```bash
# dev環境の直近2分のログ
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=tasukaru-dev" \
  --limit=10 --format="value(textPayload,timestamp)" \
  --project=$(gcloud config get-value project) --freshness=2m

# 本番環境のログ
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=tasukaru" \
  --limit=10 --format="value(textPayload,timestamp)" \
  --project=$(gcloud config get-value project) --freshness=2m

# 特定キーワード検索
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=tasukaru-dev AND textPayload:calendar" \
  --limit=20 --format="value(textPayload,timestamp)" \
  --project=$(gcloud config get-value project) --freshness=5m
```

---

## セッション履歴サマリー

| Session | 主な作業 | 行数 |
|---|---|---|
| 〜32 | 基盤構築（認証・記録入力・ケース記録・バイタル基本機能） | — |
| 33 | 休み連絡カテゴリ・カレンダー連携の基盤実装 | +500 |
| 34-50 | バイタル詳細機能・モニタリング・AI要約・出納帳 | +2000 |
| 51-55 | 体温一括入力（AI音声解析）基本実装・IIFEスコープ修正 | +400 |
| **56** | **体温一括入力完成（一時停止/再開・UI改善）・カレンダー休み連絡バグ修正**【現在】 | **+550** |

---

## よくあるトラブルと対処法

| 症状 | 原因 | 対処 |
|---|---|---|
| JSの変更が反映されない | Service Workerキャッシュ | SW登録解除またはiPhoneでSafariキャッシュ消去 |
| 関数がundefinedになる | IIFEスコープ | `window.xxx = function` で公開 |
| デプロイが遅い（3-4分） | vitals.htmlが4100行超 | 待つ（仕様） |
| 画面上で二重表示（リロードで正常） | JS側のALL_EVENTSのid型不一致 | String()変換で予防 |
| パッチが当たらない | 文字列が変わっている | 確認用スクリプトで現状確認 |
| ケース記録の内容が古い | Supabaseキャッシュ | ページリロード |
| iPhoneで音声が録音されない | Service Workerキャッシュ | Safariキャッシュ消去 |

---

## 次のセッションで優先すべきタスク

1. **iPhone実機確認** - 体温一括入力（一時停止/再開）・カレンダーmemo日付更新
2. **本番環境での最終テスト** - 両URL で動作確認
3. **新機能の検討** - 次のバージョン方針の決定

---

## .gitignore 推奨設定

```
# バックアップファイル
*.bak_*
app.py.bak_*
templates/*.bak_*
static/*.bak_*

# Python
__pycache__/
*.pyc
.env
venv/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
```

---

## 重要: APIキー・認証情報の取り扱い

**絶対にコードに直接記載しない:**
- GEMINI_API_KEY
- ANTHROPIC_API_KEY
- Supabase JWT
- データベース接続文字列

**Cloud Run環境変数に設定されている:**
```
GEMINI_API_KEY=[REDACTED_GEMINI_d6f9c2b1...]
ANTHROPIC_API_KEY=[REDACTED_ANTHROPIC_7e3a4f8...]
```

取得方法:
```bash
gcloud run services describe tasukaru-dev --region asia-northeast1 --format='value(spec.template.spec.containers[0].env)'
```

---

このドキュメントは Session 56 完了時点での記録です。
Session 57 以降で新しい情報が判明した場合は、このREADMEを更新してください。

---

## Session 60-61 での主な作業（書類出力テンプレート全面刷新）

### テンプレート全面刷新
- **テンプレート1（スタンダード）**: グレー・コンパクト2段に刷新（旧青デザインはcocokaraplusへ）
- **テンプレート11（ティール）**: 緑帯ヘッダー・左ボーダーライン
- **テンプレート12（アンバー）**: 茶色・2重罫線枠
- **テンプレートcocokaraplus**: 旧スタンダード（青）弊社専用、f_code=cocokaraplus-5526のみ表示
- bodyクラス制御: `{% if tmpl == 'cocokaraplus' %}tmpl-cocokaraplus{% else %}tmpl-{{ tmpl }}{% endif %}`
- CSS分離: `body.color:not([class*="tmpl-"])` でtmpl-1専用スタイルを他テンプレートに影響させない

### print_output.html 主な改善
- テンプレート選択グリッド（5×3）とグラフスタイル選択グリッドを正しく表示
- データ充足チェックを51人分個別API→一括API（`/api/check_data_bulk`）に変更（速度大幅改善）
- 各利用者に「確認」「印刷」ボタン追加（poPrintOne/poPreviewOne）
- `poTemplate`/`poChartStyle`変数宣言、`poSetTemplate`文字列対応（cocokaraplus）
- f_codeをprint_outputルートに渡し、JSでcocokaraplusカードの表示制御

### 目標テーブル構造変更
旧: `機能|内容|評価`のヘッダー行あり3列
新: ヘッダーなし4列 → `区分 | 目標内容 | 達成/一部達成/未達成 | 継続/変更`
- 変更かつ新目標あり → `└ 新目標：（内容）`行を追加
- care_level分岐: 要介護=機能/活動/参加の6行、事業対象者/要支援=短期/長期のみ
- フィールド: `short_goal_function_status/cont/new`（patient_evaluations）
- 目標内容: patient_profilesの`short_goal_function/activity/participation`から取得
- フォールバック: nullの場合は`short_goal`（旧フィールド）を使用

### モニタリング自動生成
- print_preview表示時にmonitoring_reportsが未生成の場合、バックグラウンドスレッドでAI自動生成→DBに保存
- 生成中は「モニタリングをAI生成中です。1〜2分後に再読み込みボタン」を表示
- プレビュー画面でモニタリング各カテゴリをインライン編集可能
- 編集後「保存」ボタンで`/api/save_monitoring`に反映

### タスカル君ローディング画面
- print_preview読み込み中にtasukaru_hashiru.pngのアニメーション表示
- `window.load`完了でフェードアウト
- `@media print { .no-print { display:none } }` で印刷時は非表示

### 主要バグ修正
- print_output.htmlのgitマージによる2重連結問題（複数回対応）
- poSetTemplate文字列対応（parseInt→isNaN分岐）
- app.pyのtmpl type=int→try/except文字列対応（cocokaraplus対応）
- Jinja変数`data`→`rd`/`p`の修正（print_preview.html）

---

## Session 61 次のチャットへの引き継ぎ文

以下の文章を次のチャットの冒頭にコピーしてください：

```
# TASUKARU 開発引き継ぎ

## プロジェクト基本情報
- リポジトリ: cocokaraplus-max/kaigo-ai-app
- ローカル: /Users/ZIMAX 1/dev/kaigo-ai-app/
- dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
- prod URL: https://tasukaru-191764727533.asia-northeast1.run.app
- 開発ブランチ: tasukaru-dev → 本番: tasukaru
- 技術スタック: Python/Flask, Supabase, Cloud Run, Jinja2, Gemini API

## 重要ルール（必ず守ること）
1. 日本語を含むヒアドキュメント(<< 'EOF')はSyntaxErrorになる
   → Pythonスクリプトファイルをcreate_toolで/mnt/user-data/outputs/に出力してダウンロード方式を使う
2. dev でテスト → 本番マージの順序を守る
3. APIキー・秘密情報は絶対にコードに記載しない（Cloud Run Secret Manager経由）
   → ログやコードに出力する場合は必ず [REDACTED_***] でスクランブル
4. `window.close()` 修正: `onclick="if(window.opener){window.close();}else{window.location.href='/print_output';}"`
5. gitマージ後は print_output.html / print_preview.html の破損を必ず確認
6. 変更ファイルが多い場合: まずdevにプッシュ→動作確認→本番マージの順を守る

## 効率的な作業方法
- Pythonスクリプトファイル方式: create_toolで/home/claude/fix_xxx.pyを作成→/mnt/user-data/outputs/にコピー→ダウンロードして実行
- Chrome連携でdevサイトを直接確認しながら開発
- JSエラー確認: javascript_toolで直接コンソール実行
- 複数ファイル変更: 全部まとめてgit add/commit/pushで1回のデプロイで完結
- 問題が複雑な場合: ログ確認→原因特定→最小限の変更→デプロイ確認の順

## 現在の状態（Session 61終了時点）
- git最新: `8af58d3` (tasukaru-dev, tasukaru両方)
- dev/PRODともに同期済み・動作確認済み

## 主要ファイル構成
- app.py: ~9300行（_auto_generate_monitoring関数、/api/check_data_bulk追加済み）
- templates/print_preview.html: ~1200行（care_level分岐目標テーブル、インライン編集、タスカル君ローダー）
- templates/print_output.html: ~480行（テンプレート13枚、一括API、確認/印刷ボタン）
- evaluation_helper.py: short_goal_function_status等のフィールド定義
- static/tasukaru_hashiru.png: ローディングアニメーション用

## テンプレート構成
| ID | 名前 | 特徴 | 対象 |
|---|---|---|---|
| 1 | スタンダード | グレー・コンパクト2段 | 全施設 |
| 2 | ナチュラル | 緑系 | 全施設 |
| 3 | フォーマル | 黒・太枠 | 全施設 |
| 4 | サイドバー | 紫・左帯 | 全施設 |
| 5 | ウォーム | 赤系 | 全施設 |
| 6 | チャコール | 黒背景ヘッダー | 全施設 |
| 7 | ミニマル | 細線・シンプル | 全施設 |
| 8 | カードブロック | 水色帯 | 全施設 |
| 9 | ゼブラ | 緑縞 | 全施設 |
| 10 | パープル | 紫系 | 全施設 |
| 11 | ティール | 緑帯ヘッダー・左ボーダー | 全施設 |
| 12 | アンバー | 茶色・2重枠 | 全施設 |
| cocokaraplus | 旧スタンダード（青） | 旧デザイン | cocokaraplus-5526のみ |

## PENDING（未完了・要継続）
1. 目標テーブルの表示確認（要介護利用者でのテスト未完了）
2. モニタリング自動生成の動作確認（バックグラウンドスレッド方式）
3. データ充足チェックのモニタリング列 - ケース記録ありで△表示の確認
4. print_output.htmlのpoPrintOne/poPreviewOneのwindow.open動作確認
5. テンプレート11/12のデザイン微調整（必要に応じて）
```


## デプロイ方式（2026-06-01 検証・確定）

- **GitHub自動デプロイは有効**。Cloud Buildトリガー2つが稼働中（いずれもDISABLED無し）。
  - `tasukaru-dev-auto-deploy`: `tasukaru-dev` ブランチへのpushで **dev** を自動ビルド&デプロイ
  - `rmgpgab-...-adex`: `tasukaru` ブランチへのpushで **本番** を自動ビルド&デプロイ
- **通常運用：pushするだけでよい。**
  - dev: `git push origin tasukaru-dev`
  - 本番: `git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru`
- 過去HANDOFFの「自動デプロイ無し・手動デプロイ」は誤り。前セッションで手動デプロイが割り込まれたため、自動が止まっているように見えていただけ。
- 検証証拠（2026-06-01）：SHORT_SHA `b3d14f4` `6b2eae8` `961b2de` `356e457` `bad7505` がいずれもGitHubソースでSUCCESS。
- `gcloud run deploy ... --source .` は緊急フォールバック時のみ使用。

---
## 接骨院会計モジュール 強化セッション 2026-06-09  <!-- session-2026-06-09-ledger -->

### このセッションで本番反映済み
- キャッシュレス振替フロントUI（CSV取込タブ内アコーディオン。PayPay・楽天CSVを照合→未収入金へ振替確定）
- 楽天 電子マネー（QUICPay等）CSV対応・パーサー修正（is_rakuten判定拡張・カンマ金額対応・決済方法をkindに付与。rakuten-fix-v3）
- CSV自動判定で日計表を検出し専用処理へ（接骨院モード有効施設のみ・検出は外さない優先。csv-autodetect-v1）
- 上記で @app.route/@login_required が新関数に誤付着した不具合を修正（decofix-v1）
- CSVプレビューの符号・科目名修正（allAccounts未ロードを取得・売上を+表示・科目名表示・category==='収益'判定。preview-sign-fix-v1）
- 試算表のExcel出力追加（PDFに加えExcel。SheetJSフロント生成。trial-excel-v1）
- CSV取込プレビュー�- CSV取込プレビュー�- CSV取込プレビュー�- CSV取込プレビュー�- CSV�: 0db6c76 系（csv-count-banner まで本番反映済み）

#####################################################################################################################################################�#####################################################################################################################################################�##################�)###################################################################################################################################################�######################################################################################################� ####################################################################################################################################��) ②キャッシュレス振替(PayPay##################################################################################################�み「機能実装までしばらくお待ちください」 ⑥接骨院の消し込み「同」 ⑦カード明細を税理士に伝える(システム外) ⑧スマレジ管理(システム外) ⑨試算表でPDF/Excel出力（施設別注記: キャッシュレス・カード込み試算表を出す施設／生CSVを渡す施設）

### 将来タスク
- カード内訳補完機能: Amazon注文履歴CSV「Order History.csv」（UTF-8。2026年3月にShift-JISから変更。取得は アカウントサービス→データとプライバシー→情報を要求する→注文履歴 でリクエスト、メール確認後 数時間〜数日でZIP）を取込。商品名→勘定科目を学習し次回「勘定科目は○○ですか?」と提案。カード明細と金額・日付で突合。カード下4桁フィルタ。接骨院・介護 両方の経費対象。
- 介護・接骨院の入金/請求の消し込み機能（settlement_status列・売掛金103/未収入金104が土台。接骨院消し込みは接骨院モードのみ）
- _detect_csv_format の半角「ｶﾙﾃ」対応（現在は全角カルテのみ、has_setで救済中）

### 会計設計の要点
現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現金現�費 / 405健康保険 / 406自賠責。

## jisseki_archive 過去月アーカイブ完了セッション 2026-06-29  <!-- session-2026-06-29-jisseki-archive -->
### 目的
実績集計表(/admin/jisseki)で過去11ヶ月(2025-06〜2026-04)を表示。実績集計APIはvitalsを直接集計するため過去月は全ゼロを返す。既存集計に一切触れず、新設アーカイブテーブルから過去月だけ補完表示する方式で実現。
### 新設テーブル jisseki_archive (本番DDL適用済み)
- id bigserial PK / facility_code text / year int / month int / payload jsonb / created_at,updated_at timestamptz / UNIQUE(facility_code,year,month)
- payloadに care_level_summary と service_time_summary をAPI戻り値と同一キー構造で格納
- DEVと本番で同一構造(DEV定義をinformation_schemaで確認し一致させた)
### app.py パッチ (marker: jisseki-archive-api-v1。tasukaru-dev→本番tasukaruへマージ済み)
- ヘルパ _jisseki_archive_lookup を追加(読み取り専用。facility_code+year+monthでpayload[kind]を返す)
- care_level_summary / service_time_summary 両APIの「vitals空のゼロ返し」直前に、アーカイブ参照分岐を挿入(ヒットすればpayloadを返す)
- vitalsが1件でもある月は分岐に到達せず既存無影響。現運用月は完全無影響
- 本番マージ時 app.py に3箇所コンフリクト発生→全て HEAD側空・dev側がパッチ=dev側全採用で解決。マージコミット 34d23f2
### 要介護「提供時間別」日曜分の確定 (このセッションの核心)
- 要介護ルール「日曜=7-8h、他曜日=全て3-4h」(HIRO確定)
- まもる君クラウド 要介護版 稼働表PDF 11ヶ月を画像化(pdftoppm -r 220 -png)し、介護保険内利用者計の日曜列を実測
- 要介護延べを 7-8h(日曜人日)と 3-4h(残り)に配分。各月 3-4h+7-8h=要介護保険内延べ で検算一致
- 確定値(月:3-4h/7-8h) 06:172/38 07:182/32 08:120/31 09:161/35 10:168/35 11:137/39 12:145/27 01:128/22 02:121/30 03:134/36 04:131/31
- 勝田弘子は全月で日曜利用なし(2026-04の保険内5日は全て平日)→要支援2への移行・要介護延べ162(勝田除外後)に日曜分は影響なし
### 本番展開手順(実施済み)
1. 本番Supabaseで DDL適用(01_ddl_jisseki_archive_prod.sql)
2. 本番Supabaseで 11ヶ月 冪等INSERT(06_prod_insert_cocokaraplus_11months_FINAL.sql。ON CONFLICT DO UPDATE。DEVで日曜分確定済みpayloadを正本にエクスポート)
3. app.pyパッチを本番ブランチへ: checkout tasukaru→merge tasukaru-dev→コンフリクト解決→commit→push→即 tasukaru-dev へ
4. 本番 /admin/jisseki で各月確認(介護度別・グラフ・提供時間別 3-4h/7-8h・総合事業5h未満・自費)
### 検算記録(本番投入後SELECTで全11ヶ月一致)
- kaigo: 3-4h+7-8h=延べ 全月一致 / sogo 5h未満・jihi(自費)も資料の月計と一致

## 契約書・重要事項説明書 加算拡張(ステップC)＋本番リリース セッション 2026-06-30  <!-- session-2026-06-30-keiyaku-stepC -->
### 目的
契約書・重説 自動生成(/admin/keiyaku)を「地域密着型通所介護で算定可能な主要加算を選択でき、正しい料金を自動計算」できるよう加算マスタ駆動に再設計。計算エンジン→加算追加→UI→低頻度加算の順(C-1〜C-4)で実装し、本番(tasukaru / cocokaraplus-5526)へ初リリース。契約書機能は本番初投入(これまで全コミット未マージだった)。
### 計算の芯(変更なしの確認事項)
- 単価 _tanka(area)=floor(10×(1+地域上乗せ率×人件費0.45)×100+0.5)/100。豊田市3級地=10.68円
- 月額=floor((基本+per_visit加算)×回数 + per_month加算 + 処遇改善round(月総単位×率))×単価。給付=floor(月額×(10-負担割合)/10)。自己負担=月額-給付。四捨五入は floor(x+0.5)
- 実証値: 3-4h(han)要介護3・1割・週1回=2,937円 / 7-8h(ichi)同=5,302円 / 処遇改善Ⅳなら2,843円。DEV・本番ともに実機確認済み

### C-1 計算エンジンの加算マスタ駆動化 (markers: keiyaku-addmaster-v1[render] / keiyaku-addmaster-app-v1[app])
- 加算ベタ書きを _ADD_MASTER / _KK_ADD_MASTER 駆動に。calc種別 per_visit(単位×回数) / per_month(月定額) / per_month_cap(単位×min(回数,cap)) / rate_on_total(処遇改善=月総単位×率)
- in_fee_default: True=料金表に金額反映 / False=料金表でなく加算一覧表に条件のみ記載
- 後方互換ブリッジ _add_state / _kk_add_state: 旧bool形式 adds={kunren1:True} を {on:True,in_fee:既定} に読み替え。新dict形式 {on,in_fee} も尊重
- 検証: 現状4加算(kunren1/kunren2/kagaku/shoguu)でローカル総当たり(render 69,120 / app 122,880ケース)旧ロジックと不一致ゼロ→従来完全一致を確証

### C-2 per_visit加算5種追加 (78系サービスコード表・告示で単位数確認)
- kunren1ro=76(個別Ⅰロ,Ⅰイと排他) / chuju=45(中重度者ケア体制) / ninchi=60(認知症) / nyuyoku1=40・nyuyoku2=55(入浴Ⅰ/Ⅱ排他)。全て per_visit・in_fee_default=True
- 個別機能訓練の排他グループ名を kunren_kobetsu に統一(Ⅰイ/Ⅰロ)

### C-3 設定UIのマスタ駆動化＋排他ラジオ (markers: keiyaku-c3-ui-v1[html] / keiyaku-c3-master-api-v1[app])
- settings GET 応答に add_master(label/note/group/scope/calc/units/in_fee_default/cap)を配信する _kk_add_master_public を追加
- admin_keiyaku.html: ADDS_DEF ハードコード廃止→サーバ配信マスタから加算カードを動的生成。同一group(入浴Ⅰ/Ⅱ等)は片方onで他方自動off(ラジオ動作)。排他注記は内部group名を出さず「いずれか一方のみ選択できます」

### C-4a 限度つき加算の器 (markers: keiyaku-c4-table-v1[render] / keiyaku-c4a-koukuu-app-v1[app] / keiyaku-c4-ui-v1[html])
- 口腔機能向上 koukuu1=150・koukuu2=160(per_month_cap,cap=2,排他group=koukuu,in_fee_default=False)
- 重説の加算概要文 _adds_line を加算一覧表 _adds_table に作り替え。3列(加算名/単位数・算定条件/料金表への反映)。in_fee:trueは「料金表に反映済み」、falseは「※実施月のみ算定／料金表とは別に加算」
- UI: in_fee_default=false の加算がonのとき「料金表(月額目安)に含める」トグルを表示(既定off)

### C-4b 加算拡充＋low_freq calc新設 (markers: keiyaku-c4b-adds-app-v1[app] ほか render/html)
- 追加9加算(78系で確認): eiyou_assess=50/月 / eiyou_kaizen=200・月2回限度(per_month_cap cap=2) / screening1=20・6月1回(low_freq) / renkei1=100・3月1回(low_freq,group=renkei) / renkei2=200/月(group=renkei) / adl1=30・adl2=60(group=adl) / jakunen=60/回 / soudan=13/回(※共生型のみ算定可。共生型は基本報酬93/100注記)
- 新calc low_freq: 6月/3月1回等の超低頻度。料金計算に一切関与せず一覧表専用。_add_state で low_freq は in_fee を常にFalse強制。UIもトグルを出さない
- マスタ計20加算。排他グループ kunren_kobetsu/nyuyoku/koukuu/renkei/adl
- 検証: 全calc種別で現状4加算不変・新加算in_fee=true時の増額が手計算一致・low_freqは強制で料金表に絶対載らない、をローカル＋DEV実機で確認

### 本番リリース (tasukaru: 642617a / 弊社seed投入 / アクションバー固定 ef0ee17)
- DDL不要を確認(契約書機能は admin_settings の4キー keiyaku_facility/jihi/staff/adds のみ使用。render側はDB非依存)
- tasukaru-dev→tasukaru へ ort マージ(コンフリクトなし)。契約書6ファイルのみ変更、既存機能無影響
- 本番初リリースのため facility 空→ POST /admin/keiyaku/seed (keiyaku_seed_cocokara.py の4キー投入API)で弊社初期データ投入。施設コードは session["f_code"]=cocokaraplus-5526。force保護あり
- 本番で20加算配信・料金(han2,937/ichi5,302)・重説/契約書の印刷生成を実機確認

### UI改善: アクションバー固定 (marker: keiyaku-navh-v1)
- .kk-actionbar を bottom:0 → bottom:var(--kk-nav-h,137px) でボトムナビ(.bottom-nav)の真上に固定。幅は max-width:var(--page-max-width)(実値678px本番634/ナビと一致)・box-sizing:border-box で横はみ出し解消
- kkSyncNavHeight(): .bottom-nav の高さを実測し --kk-nav-h にセット(連絡帳 --rk-nav-h と同方式)。固定値直書きを避け端末差に対応(本番ナビ134px/DEV137pxを各々正しく実測)
- .kk-wrap 下余白と .kk-toast 位置も --kk-nav-h 連動

### 単位数の確定メモ(一次ソース: 介護給付費単位数等サービスコード表 78系・告示)
- 中重度者ケア体制45/日(利用者全員可) / 認知症60/日 / 若年性認知症受入60/日 / 入浴Ⅰ40・Ⅱ55(排他,地域密着はⅡ=55) / 個別Ⅰイ56・Ⅰロ76 / 口腔機能向上Ⅰ150・Ⅱ160(月2回限度) / 栄養アセス50/月 / 栄養改善200(月2回限度) / 口腔栄養スクリーニングⅠ20(6月1回) / 生活機能向上連携Ⅰ100(3月1回)・Ⅱ200/月 / ADL維持等Ⅰ30・Ⅱ60(月) / 生活相談員配置等13/日(共生型のみ・基本報酬93/100)

### 印刷の使い方
- /admin/keiyaku 画面下部の固定バー「印刷 / PDF」ボタン→ /admin/keiyaku/print?type=種別&wari=負担割合 を別タブで開く(既定 doc=both=重説+契約書)。ブラウザ印刷(Cmd+P)で紙またはPDF保存
- doc=juyo|keiyaku|both / type=種別キー / format=html|pdf で出し分け可

### 将来の残タスク(同じマスタ駆動の枠組みで追加可能)
- サービス提供体制強化加算(区分複雑・施設共通) / 延長加算(9時間以上) / 減算(送迎・同一建物) / 共生型の基本報酬93/100調整(現状はsoudan加算の注記のみ)
- 印刷の doc 種別選択UI(現状ボタンは doc=both 固定。重説だけ/契約書だけを選べると実務的)

---

## session-2026-06-30-timecard （タイムカード/勤怠管理機能 新規実装）

機能訓練型デイサービス向けに、共用タブレットで打刻する勤怠管理機能を新規構築。Phase1（打刻・記録）→Phase2（集計・編集）→導線→本番リリース→運用改善まで一気通貫で実装。

### 確定仕様
- 共用タブレットで職員名を選んで打刻（出勤in/退勤out/休憩開始break_start/休憩終了break_end）。個人ログイン不要の公開画面 `/timecard`、ただし承認済みデバイストークン必須。
- デバイス制御は2段階: ①開発者が施設にタイムカード機能を許可（課金管理）→ ②施設管理者が自施設のデバイスを承認。
- デバイス識別はlocalStorageの乱数トークン（tcd_xxx）。職員はstaffsをfacility_code+staff_nameで識別。
- 勤怠記録は論理削除（is_deleted）。労働時間は給与根拠のためサーバ側で一元計算。

### DDL（本番適用済み, marker: timecard-ddl-v1）
- `timecard_records`（id/facility_code/staff_name/punch_type[CHECK in/out/break_start/break_end]/punched_at timestamptz/device_token/note/is_deleted/edited_by/created_at/updated_at, index 2本）
- `timecard_devices`（id/facility_code/device_token/device_label/is_active/approved_by/created_at/last_used_at, UNIQUE(facility_code,device_token)）
- `facilities.timecard_enabled boolean default false`
- 本番適用時、DDL全体を流したつもりが効いておらず確認クエリ0件→CREATE文を個別実行し直して成功した経緯あり。本番でテーブル確認（SELECT information_schema）してからコードをデプロイすること。

### 実装マーカー一覧
- `timecard-api-v1`(app.py): ヘルパ（_tc_now_jst/_tc_device_lookup/_tc_facility_enabled/_tc_staff_list/_tc_today_punches/_tc_staff_state[状態機械]）。公開ルート /timecard・/timecard/bootstrap・/timecard/punch（状態整合チェックで二重出勤や休憩入れ子崩れを拒否）・/timecard/device/request。管理者ルート /admin/timecard・/today・/devices・/device/approve・/revoke。
- `timecard.html` / `admin_timecard.html`: 公開打刻画面（base非継承の独立HTML, 緑#2f6b5e系）と管理画面（base継承, 当日一覧＋デバイス承認タブ）。
- `timecard-devtoggle-v1`(app.py) / `timecard-devtoggle-html-v1`(dev_menu.html): 開発者MENU(/dev)に施設別ON/OFFトグル。既存sekkotsu_mode_allowed(dev-sekkotsu-allow-v1)と同型。
- `timecard-monthly-v1`(app.py): /admin/timecard/monthly（職員別・日別・月合計の労働時間をサーバ計算。労働時間=(退勤-出勤)-休憩。欠損日は補完せずincomplete=true＋具体的flags、合計から除外）・/admin/timecard/report（集計画面）。_tc_compute_day全パターン単体検証済み。
- `timecard-edit-v1`(app.py)+`report-ui-v2`(admin_timecard_report.html): 管理者の打刻編集（A案=UPDATE方式、edited_by/note記録、DDL不要）。/edit・/add・/delete（論理削除）・/day。各日の鉛筆→編集モーダルで修正・追加・削除、編集で集計即再計算。
- `timecard-menu-v1`(admin.html)/`timecard-top-btn-v1`(top.html): 管理者MENUに「タイムカード（勤怠）」リンク。TOPに「タイムカードで打刻する」ボタンを承認済みデバイスのときだけJS表示（既存bootstrap再利用）。
- `timecard-hidden-icon-v1`(app.py)+`timecard-hidden-toggle-v1`(admin.html): タイムカード非表示=職員ごとに打刻画面へ出さない設定。admin_settingsのkey=timecard_hidden名前リスト（既存ledger_users/board_editorsと同型、DDL不要）。職員管理に時計アイコンのトグル。_tc_staff_listで除外。端末管理用ダミースタッフPC1/PC2を打刻画面から消すのが主目的。
  - `timecard-hidden-fix-v1`(app.py): api_toggle_timecard_hiddenで`supabase`未定義NameError→`supabase=get_supabase()`で修正（手本のtoggle_ledger_accessはグローバルsupabase参照だったが、timecard系APIは全てget_supabase()使用に統一）。
- アイコン連動: _tc_staff_listがicon_image_url(画像)>icon_emoji(絵文字)>人型👤の優先で返す。打刻画面のiconHtml()ヘルパで表示。
- `timecard-icon-v1`(timecard.html): ホーム画面追加時のアイコンにapple-touch-icon=/static/tasukaru_hashiru.png（走るアライグマ, 300x300正方形）。apple-mobile-web-app-capable等も追加。iOSはアイコンをキャッシュするため、既存アイコンを長押し削除→Safariで開き直し→ホーム画面に追加で更新。
- `timecard-devdel-v1`(app.py): /admin/timecard/device/delete（デバイス物理削除。管理情報なので物理削除可、打刻記録は別テーブルで残る）。承認画面に削除ボタン（ゴミ箱・確認ダイアログ付き）。テスト中に承認待ちデバイスが溜まる問題への対処。
- タイムカードUI仕上げ: 当日一覧→管理者MENU、月次集計→当日一覧の戻るボタン。更新ボタンに回転フィードバック。打刻画面の時計をTekoフォント(Google Fonts)のグリーンカード（時分を大きく700・秒を下に小さく・#2f6b5e白文字）に。

### 本番リリース
- DDL3点を本番Supabaseへ適用 → tasukaru へマージ（d877be2）→ デプロイ → 開発者MENUでcocokaraplus-5526のtimecard_enabled=ON。
- 運用改善（非表示トグル・アイコン連動・時計・削除ボタン・戻るボタン）も順次本番反映（733912e）。
- 本番でPC1/PC2の非表示、デバイス整理が実機で確認済み。
- 本番URL: 打刻 https://tasukaru-191764727533.asia-northeast1.run.app/timecard 、管理 /admin/timecard 、開発者MENU /dev。

### 将来構想（timecard/FUTURE_IDEA.md に記録）
1. スマホ個人打刻＋アクセス制御連動: 各職員が自分のスマホでログイン打刻し、出勤するまで業務情報（利用者情報等）を閲覧不可にゲート。自宅から個人情報が見られない状態を作る＝個人情報保護・セキュリティ強化。認証設計の根幹に関わるため別フェーズ。timecard_records(facility_code+staff_name+device_token)を土台に拡張可能。
2. 打刻漏れアラート＋その場入力: 退勤時に休憩終了漏れ→アラートで時刻入力。出勤漏れ・退勤漏れも検出して遡り入力。
3. LINE打刻連携: LINE公式/個人LINEから出退勤送信で打刻（本人アカウントのみ=代理打刻防止）。TASUKARUは既にLINE公式連携済みなので素地あり。ただし職員×LINEの紐付け設計が新規に必要。当面は共用タブレット方式を採用。

### 設計上の確定事項
- 労働時間計算: 欠損（退勤漏れ・休憩終了漏れ・出勤漏れ）は推測補完せず、incomplete=true＋具体的flagsで「要確認」表示し合計から除外。給与根拠なので機械が勝手に埋めない方針。
- 未クローズ休憩を退勤で閉じる案は、過大/過少どちらにもなり不自然なため不採用→欠損は欠損として人が直す設計に。
- アクションバー固定は既存のkkSyncNavHeight()/--kk-nav-hパターン（連絡帳--rk-nav-hと同方式）。

### 残タスク（次回）
- 実績集計表(/admin/jisseki)の年数変更ができない不具合（要調査）。
- 契約書・重要事項説明書の「印マーク」削除（現物確認後）。

## session-2026-07-01-monitoring-pdf-fix

### 概要
モニタリング報告書の印刷（PDF出力）が途中で切れる不具合の調査・修正。調査の過程で個人情報漏洩も発見・修正。最終的にサーバーサイドPDF生成＋自動フィット機能を構築し本番反映。

### 主な変更点

**印刷方式の全面刷新**
- `window.print()`（ブラウザ印刷）→ サーバーサイドPDF生成（pdfkit + wkhtmltopdf）に移行
- 新規APIエンドポイント `POST /api/monitoring_report_pdf` を追加（app.py）
- marker: `monitoring-pdf-endpoint-v1`, `monitoring-pdf-client-v1`

**印刷不具合の個別修正（判明順）**
- 余白が出ない → `@page{margin:0}` + `.page-pad`実寸パディング方式（契約書PDFと同じ技法）: `monitoring-pdf-margin-fix-v1`
- グラフが表示されない → SVGをcanvas経由でPNGに変換してから送信: `monitoring-pdf-svg-to-png-v3`
- 体力測定カードが縦積みになる → `.rep-fit-grid`をtable表示に強制変換: `monitoring-pdf-fitgrid-table-v1`
- 個別機能訓練実施による変化/課題とその要因の2カラム→縦積み・全幅表示に変更（無駄な最小高さ削減）: `monitoring-pdf-free2-stack-server-v1` / `-client-v1`

**【重要】個人情報漏洩の発見・修正**
- `reportSampleData()`(monitoring.html)内に実在の利用者名・ケアマネ事業所名がハードコードされていたことを発見
- 汎用ダミー値に置換。DEV・本番とも対応済み
- marker: `mon-sampledata-anonymize-v1`

**自動フィット機能（文章量に応じたフォント・余白の自動調整）**
- クライアント側で印刷ページ幅(733px)の隠しコンテナで高さを計測し、レベル0〜8(フォント12px〜8px)から最適なものを自動選択
- marker: `monitoring-pdf-fitlevel-client-v1`, `-server-v1`, 各`extend`/`extend2`/`extend3`/`extend4`系
- フォント名の不一致(`Hiragino Sans`/`Noto Sans JP`指定 vs 実際は`Noto Sans CJK JP`のみ導入)を発見・修正: `monitoring-pdf-font-fix-v1`
- ブラウザ計測とサーバー実レンダリングの食い違いが解消しきらないため、サーバー側で実際にPDF生成→pdfinfoでページ数確認→収まらなければfit_level昇格して再生成するループ方式に変更: `monitoring-pdf-verify-loop-v1`
- Dockerfileに`poppler-utils`(pdfinfo)を追加（poppler-utilsというパッケージ名自体をマーカー代わりに使用）
- 最終方針: 「1ページ絶対主義」をやめ、読みやすさの上限(レベル4=10.5px)までしか縮小しない。収まらない場合は体力測定グラフのみ文末(2ページ目)に移動し、テキストは1ページ目側に自然に残す: `monitoring-pdf-readable-cap-v1`
- 強制改ページを試したが3ページ化を招いたため撤回、並び替えのみ採用: `monitoring-pdf-remove-forced-break-v1`

**文字数選択UIの拡張**
- モニタリング(monitoring.html)・評価(assessment.html)ともに文字数選択肢を5段階(100/200/300/400/500)→9段階(50刻み、100〜500)に拡張
- marker: `monitoring-charlen-options-v1`, `assessment-charlen-options-v1`
- モニタリング側はボタン形式からドロップダウン形式に変更(評価ページと統一感を持たせるため): `monitoring-charlen-dropdown-v1`

### 技術的な学び（重要）
- **wkhtmltopdf(patched qt)の弱点**: CSS `@page`のmargin指定、inline SVG描画、Flexboxレイアウト。いずれも今回確立した回避パターン(`.page-pad`実寸パディング、SVG→PNG変換、table強制変換)を今後のPDF機能で最初から使うこと。
- **フォント名は必ずサーバー実機(`fc-list`)で確認する**。CSSのfont-family指定と実際にインストールされているフォント名の不一致は、PDF関連の不具合原因として真っ先に疑うべき。
- **ブラウザでの高さ計測とサーバーレンダリングは完全には一致しない**前提で設計する。「絶対に1ページに収める」より「読みやすさを保った上で自然に収まる範囲を狙う」方針の方が保守的で壊れにくい。

### 未解決・次回持ち越し
- **レイアウトエディタ構想**: ユーザーが1ページ目・2ページ目の内容を自由に手動配置できる機能。自動フィットの限界を超える本質的な解決策として提案あり。未着手。
- **Androidでバイタルのカメラが起動しない不具合**: `NotAllowedError: Permission denied`と判明(診断用パッチ`vitals-camera-error-diagnose-v1`で可視化、本番反映済み)。Chrome(Android版)使用を確認済み。Android設定側のアプリ権限、Chromeのサイト別カメラ権限(アドレスバーの鍵マーク→サイトの設定)の確認を依頼中。次回、解決したか確認からスタート。

### 開発運用上の注意（今回発生した事故）
本セッション中、commitが誤って本番ブランチ(tasukaru)に直接乗る事故が2回発生。原因はコマンド実行時のブランチ確認漏れとみられる。**commit前には必ず`git branch --show-current`でtasukaru-devにいることを確認すること。**
復旧手順: `git checkout tasukaru-dev && git cherry-pick <該当コミット> && git push origin tasukaru-dev` → `git checkout tasukaru && git reset --hard origin/tasukaru`

### 追記(2026-07-02): Androidバイタルカメラ問題 解決
前セッションで「次回持ち越し・未解決」としていたAndroid端末のカメラ起動不可(`NotAllowedError: Permission denied`)は解決。

**原因**: コードの不具合ではなく、Chromeがサイト単位で記憶していたカメラ権限が「ブロック」状態になっていた。
- 端末はChromeのブックマーク/URLから起動(PWAではない)→ PWA権限タイミング問題は除外
- Android設定→アプリ→Chrome→カメラ権限は「毎回確認」= OSレベルでは正常
- 同端末の他サイト(Google Meet等)ではカメラ正常動作 = 端末・Chrome本体は正常
- 上記3点から、TASUKARUサイト個別のカメラ権限ブロックと特定

**解決手順**: アドレスバーの鍵マーク → サイトの設定 → カメラを許可(またはサイトデータをリセット)→ 再読み込みで許可ダイアログが正常表示され、カメラ起動成功。

**今後の対応**: コード修正は不要。別端末で再発した場合も同手順で解決可能。現場マニュアル/manual.htmlのトラブルシュート項への追記は次回検討候補。

### 追記(2026-07-02): 評価メモ修正・音声ルーティング・追加利用連絡・体力体重測定改善・充足チェック表

本セッションで実装し本番反映した5件。

**1. 評価メモの患者間持ち越しバグ修正** (marker `eval-memo-reset-fix-v1`)
評価ページで、評価メモ入力後に別の利用者(データなし)を開くと前の利用者のメモが残るバグを修正。`evalResetForm()` のクリア対象配列に `eval-memo` が含まれていなかったため追加。コミット `01f6458`。

**2. 休み連絡の理由欄への音声入力修正** (marker `leave-reason-voice-target-v1` / `extra-validate-voice-v1`)
記録入力の音声入力(`inpConfirm`)が文字起こし結果を常に `content-area` に入れていたため、休み連絡カテゴリ(内容欄非表示)では理由欄に反映されなかった。書き込み先を「休み連絡→leave-reason / 追加利用連絡→extra-reason / その他→content-area」に分岐。コミット `bd30fd1`。

**3. 追加利用連絡 新機能** (marker `extra-use-*`)
休み連絡と同じ仕組み(記録入力→ケース記録→「TASUKARUケース記録連動」カレンダー→双方向同期)で追加利用連絡を新設。入力項目は日付(期間+飛び日)+理由のみ。カレンダーは青 `#1e88e5`「○○様 追加利用」、`record_id` で紐づけ。カレンダー編集/削除でケース記録も同期(編集=content再生成、削除=残日で再生成or記録削除)。
- DDL: `records` に `extra_date_start` / `extra_date_end` (date) / `extra_reason` (text) 追加。`record_categories` に「追加利用連絡」行追加(DEV sort_order=85、本番は休み連絡の隣に整列 sort_order=9、color=#1E88E5)。DEV・本番両方に適用済み。
- contentヘルパー `_build_extra_content` / `_build_extra_content_multi` 新設(`_format_leave_period` を再利用)。
- 既存の休み連絡ロジックは全て `category=="休み連絡"` でガードされているため、`category=="追加利用連絡"` の分岐を並列追加する方式で既存を一切壊さず実装。
- サーバー側 content必須バリデーション(1445行)も休み連絡のみ除外だったため追加利用連絡も除外(marker `extra-server-validate-v1`)。この修正漏れが初回保存失敗の原因だった。
- Chrome連携で保存・編集(日付変更でcontent追従)・削除(記録も削除)の双方向同期を全パターン検証済み。コミット `fd7b33d` / `ff5ca7f`。

**4. 体力・体重測定ページの改善** (fitness.html)
- 履歴編集を日付セル(`.dt`)タップのみに限定(marker `fitness-dt-only-tap-v1`)。以前は行全体(`.hist-row`)が反応していた。
- 保存し忘れアラート(marker `fitness-unsaved-alert-v1`): `fitHasUnsaved()` 判定 + `beforeunload`(離脱)+ 利用者切替/リセット時の `confirm`。
- 利用者切替時の入力欄クリア(marker `fitness-clear-on-switch-v1`): `fitClearInputs()` を新設し `fitPickPatient` / `resetFitPatient` で呼ぶ。切替時に前利用者の入力値が残る問題を解消。
- コミット `0ea4cf9` / `dbe9550`。

**5. 体力・体重 充足チェック表** (marker `fitness-check-*`)
体力・体重ページ上部に「入力」「一覧」タブを新設。一覧タブに月別の充足チェック表。
- 対象者: その月に `vitals` 実績がある利用者。実績なしで当月に休み連絡がある人は「休」。
- 状態: 測定済✓(done) / 未測定(missing) / 休(absent) / 対象外(not_target グレー)の4状態。
- 表示: 利用者名の横に体重・体力測定を並べる3列統合テーブル(marker `fitness-combined-table-v1`)。
- 体重判定: その月に `body_weights` に記録あり。
- 体力判定: 施設設定で2モード切替(`admin_settings` key=`fitness_check_settings`)。モードA=利用者ごと前回測定+3ヶ月サイクル、モードB=施設一律の測定月指定(基準月チップ選択)。
- API: `GET /api/fitness_check?year=&month=`(充足判定)、`GET/POST /api/fitness_check_settings`(サイクル設定)。DDL不要(admin_settings流用)。
- Chrome連携でタブ切替・4状態判定・3列描画・設定切替を検証済み。コミット `d6135ed` / `4a98636`。

**開発メモ**: str_replace/パッチのアンカーは実ファイルの空行まで完全一致が必須。本セッションでも fit-wrap 直後や content-section 直前、life-check-api ブロック前などで空行を含め忘れて0件エラーが複数回発生し、`cat -v -e -t` で確認して修正した。macOS の `cat` は `-A` 非対応のため `cat -v -e -t` を使用。

### 追記(2026-07-02 午後): 充足チェックuser_name修正・生活機能チェックUI改善・かな表記・戻るボタン統一

本セッション後半の作業。すべて本番反映済み。

**6. 充足チェックAPI user_nameベース修正** (marker `fitness-check-username-v1`)
本番の体力・体重充足チェックが全員「休」表示になるバグを修正。原因は `vitals.patient_id` が UUID、`patients.id` が整数で突き合わせ不一致(patient_profiles UUID系 vs legacy patients 整数系の二重テーブル問題)。DEV は偶然 vitals が整数 patient_id で動いていた。`api_fitness_check` を丸ごと user_name ベースの突き合わせに書き換え。本番確認済み: body_weights(234)/fitness_tests(145)/vitals(1299) すべて user_name が完全に埋まっている。コミット `b8b6452`。

**7. 生活機能チェック(life_check.html)UI改善** (marker `lc-ui-visibility-v1` / `lc-textarea-v1` / `lc-autogrow-restore-v1`)
記入欄が1行 input で長文が読めない問題と、選択欄・入力項目・カテゴリの視覚的区別を改善。
- カテゴリ見出し(`.lc-item-head`)をブルー帯(背景#e6f1fb+左帯#185FA5)に、`.lc-item-name` を濃青#0C447C に。
- 選択中の点数(`.lc-opt.selected`)を青→グレー強調(border#5f6368 2px+背景#f1f3f4+太字)に。カテゴリのブルーと色を分けて区別しやすく。
- 記入欄の input×2 → ラベル付き textarea×2 に変更(環境/状況・生活課題)。下部に薄い背景で分離。`lcAutoGrow`/`lcAutoGrowAll` で内容に応じ高さ自動調整。データ復元(`lcPrefillSub`)時にも高さを合わせる。
- 既存の data-env/data-note の .value 読み書きは textarea でもそのまま動くため互換。選択ロジック(JS)は無変更。
- Chrome連携で検証: カテゴリ帯 rgb(230,241,251)、選択中グレー rgb(241,243,244)/border rgb(95,99,104)/太字700、textarea 高さ 59→78px 自動拡張を確認。コミット `8bce6f8`。

**8. カナ→かな表記変更** (marker `kana-to-hira-v1`, admin.html)
新規手入力登録のラベル「カナ」→「かな」、利用者一覧検索プレースホルダー「名前・カナ・番号で絞り込み」→「名前・かな・番号で絞り込み」の表示テキスト2箇所のみ変更。CSV取込マッピングキー(`'カナ':'user_name_kana'`)やコメント・変換処理は変更しない。コミット `b525c75`。

**9. 管理者MENU戻るボタンの設置・統一** (marker `visit-back-btn-v1` / `admin-back-btn-v1`)
管理者MENU(`/admin`)配下ページに「管理者MENUに戻る」ボタンを統一デザインで設置。
- 統一デザイン: `<a href="/admin">` インラインスタイル(白背景/1.5px薄グレー枠#e0e0e0/角丸8px/グレー文字#5f6368/arrow_backアイコン+「管理者MENUに戻る」)。
- 利用管理(visit.html): 新規設置。実績集計表(admin_jisseki.html)/契約書・重要事項説明書(admin_keiyaku.html): 新規設置。タイムカード(admin_timecard.html): 既存の `.tca-back`(背景/枠なし)を統一デザインに差し替え。
- 各ページのルート: /visit, /admin/jisseki, /admin/keiyaku, /admin/timecard。戻り先は全て /admin。
- Chrome連携で4ページとも白背景/1.5px solid #e0e0e0/角丸8px を確認。コミット `b525c75`(visit) / `a1b3379`(jisseki/keiyaku/timecard)。

**メモ**: `/visit` に Chrome連携の navigate で直接アクセスすると `/admin` にリダイレクトされることがあるが、管理者MENUのリンク経由(a[href="/visit"]クリック)では正常表示。実利用は管理者MENUからの導線なので問題なし。

### 追記(2026-07-02 午後): 充足チェックuser_name修正・生活機能チェックUI改善・かな表記・戻るボタン統一

本セッション後半の作業。すべて本番反映済み。

**6. 充足チェックAPI user_nameベース修正** (marker `fitness-check-username-v1`)
本番の体力・体重充足チェックが全員「休」表示になるバグを修正。原因は `vitals.patient_id` が UUID、`patients.id` が整数で突き合わせ不一致(patient_profiles UUID系 vs legacy patients 整数系の二重テーブル問題)。DEV は偶然 vitals が整数 patient_id で動いていた。`api_fitness_check` を丸ごと user_name ベースの突き合わせに書き換え。本番確認済み: body_weights(234)/fitness_tests(145)/vitals(1299) すべて user_name が完全に埋まっている。コミット `b8b6452`。

**7. 生活機能チェック(life_check.html)UI改善** (marker `lc-ui-visibility-v1` / `lc-textarea-v1` / `lc-autogrow-restore-v1`)
記入欄が1行 input で長文が読めない問題と、選択欄・入力項目・カテゴリの視覚的区別を改善。
- カテゴリ見出し(`.lc-item-head`)をブルー帯(背景#e6f1fb+左帯#185FA5)に、`.lc-item-name` を濃青#0C447C に。
- 選択中の点数(`.lc-opt.selected`)を青→グレー強調(border#5f6368 2px+背景#f1f3f4+太字)に。カテゴリのブルーと色を分けて区別しやすく。
- 記入欄の input×2 → ラベル付き textarea×2 に変更(環境/状況・生活課題)。下部に薄い背景で分離。`lcAutoGrow`/`lcAutoGrowAll` で内容に応じ高さ自動調整。データ復元(`lcPrefillSub`)時にも高さを合わせる。
- 既存の data-env/data-note の .value 読み書きは textarea でもそのまま動くため互換。選択ロジック(JS)は無変更。
- Chrome連携で検証: カテゴリ帯 rgb(230,241,251)、選択中グレー rgb(241,243,244)/border rgb(95,99,104)/太字700、textarea 高さ 59→78px 自動拡張を確認。コミット `8bce6f8`。

**8. カナ→かな表記変更** (marker `kana-to-hira-v1`, admin.html)
新規手入力登録のラベル「カナ」→「かな」、利用者一覧検索プレースホルダー「名前・カナ・番号で絞り込み」→「名前・かな・番号で絞り込み」の表示テキスト2箇所のみ変更。CSV取込マッピングキー(`'カナ':'user_name_kana'`)やコメント・変換処理は変更しない。コミット `b525c75`。

**9. 管理者MENU戻るボタンの設置・統一** (marker `visit-back-btn-v1` / `admin-back-btn-v1`)
管理者MENU(`/admin`)配下ページに「管理者MENUに戻る」ボタンを統一デザインで設置。
- 統一デザイン: `<a href="/admin">` インラインスタイル(白背景/1.5px薄グレー枠#e0e0e0/角丸8px/グレー文字#5f6368/arrow_backアイコン+「管理者MENUに戻る」)。
- 利用管理(visit.html): 新規設置。実績集計表(admin_jisseki.html)/契約書・重要事項説明書(admin_keiyaku.html): 新規設置。タイムカード(admin_timecard.html): 既存の `.tca-back`(背景/枠なし)を統一デザインに差し替え。
- 各ページのルート: /visit, /admin/jisseki, /admin/keiyaku, /admin/timecard。戻り先は全て /admin。
- Chrome連携で4ページとも白背景/1.5px solid #e0e0e0/角丸8px を確認。コミット `b525c75`(visit) / `a1b3379`(jisseki/keiyaku/timecard)。

**メモ**: `/visit` に Chrome連携の navigate で直接アクセスすると `/admin` にリダイレクトされることがあるが、管理者MENUのリンク経由(a[href="/visit"]クリック)では正常表示。実利用は管理者MENUからの導線なので問題なし。


---

## §28 施設オンボーディング（LINE→施設自動発行→課金）— 第2段階完了（2026-07-03）

### 目的
TASUKARUを新規導入する施設を、QR→LINE友だち追加→フォーム入力→Stripe決済→施設自動発行→初回ログインまで**全自動完結**させる導線。従来のメール方式（/register）を置き換える。承認ステップなし（決済完了で即発行）。

### 重要な前提（過去の落とし穴）
- ログイン認証は `facilities.admin_password` ではなく **`staffs` テーブルの `password_hash`** で行われる。職員ゼロの施設はログイン不能（旧PAYTEST01でハマった）。
- 既存 `/register`(app.py 1301) は `facilities` に平文 `admin_password` を入れるだけで **`staffs` を作らないため実質ログインできない**。新オンボーディングはこの欠陥を構造的に解消する。

### 確定した設計
- 施設コード = 意味を持たないランダム `f`+16進10桁（例 `f7k2m9x4qp`）。施設名は `facility_name` に保持。コードから施設を推測不可＝セキュア。
- 最初の管理者職員 = フォームで「管理者のお名前」を入力させ `staffs` に作成。
- 初回ログイン = **初回設定リンク方式**（仮PWは送らない）。`/setup?token=xxx` で本人がパスワード設定。トークンは使い捨て・24時間有効。パスワードはLINEトーク履歴に残らない＝セキュア。
- 無料トライアル1ヶ月を踏襲（`trial_ends_at`＝`expires_at`＝発行+30日）。
- 施設情報入力は **LIFF**（LINEログイン済みuserIdを確実取得）で作る方針。なりすまし防止。

### この段階で実装したもの（第2段階=サーバcore、DEVのみ・本番未反映）
- **DDL（DEV Supabase適用済み）**
  - `staffs.setup_token TEXT` / `staffs.setup_token_expires TIMESTAMPTZ`
  - `facilities.onboard_id TEXT`（決済再送に対する二重発行防止キー）
- **onboard-webhook-v1**（app.py `stripe_webhook` 内）: `checkout.session.completed` で `meta.onboard_id` があれば発火。onboard_id重複チェック（冪等）→施設コード採番→`facilities` INSERT→`staffs` に管理者職員INSERT（password_hash空・setup_token発行）→`line_send_message` で本人userIdに初回設定リンク送信→`line_notify_admin` で開発者に通知。metadataで受け取る値: `onboard_id / facility_name / admin_name / line_user_id / plan / term`。
- **onboard-setup-route-v1**: `/setup`（GET=token検証しフォーム表示 / POST=8文字以上・確認一致→sha256でhash保存→setup_tokenをNULL化）。テンプレ `setup.html`（state: form/done/expired/invalid）。
- **onboard-liff-page-v1**: `/onboard`（LIFFエンドポイントの器。現状は接続確認用の空ページ）。テンプレ `onboard.html`。
- コミット `8448536`（tasukaru-dev）。DEVデプロイ・表示確認済み（`/onboard`＝器ページ表示、`/setup` token無し＝「リンクが無効です」で正しく拒否）。

### 送信インフラ（既存流用・新規環境変数不要）
- 特定userId送信 = `line_send_message(user_id, messages)`（app.py 16161、`LINE_CHANNEL_ACCESS_TOKEN`＝オンボーディング用アカウント「TASUKARU」のトークンを使用）。
- `_line_push(token, to_user_id, messages)`（app.py 344）は施設別トークン用。オンボーディングは施設非依存なので `line_send_message` 側を使用。

### 残タスク（次段階）
1. **第3段階フロント**: `/onboard` に LIFF SDK読み込み＋施設情報フォーム（施設名・管理者名）＋プラン選択＋`onboard_id`発番＋`/api/stripe/create_checkout` 連携（metadataに onboard_id/facility_name/admin_name/line_user_id/plan/term を載せる）。
2. **LIFF登録**: LINE Developers の TASUKARUチャンネルに LIFFアプリ追加→エンドポイントを `/onboard` に設定→LIFF ID取得→フロントに埋め込み。
3. **友だち追加自動返信**: line webhook の follow イベントで LIFF URL を返信。
4. **DEV通し確認**: LIFF→フォーム→テスト決済（4242）→webhook→施設発行→setupリンク受信→初回ログイン、をE2Eで確認。
5. **本番展開**: 上記3 DDL を本番Supabaseへ適用→本番マージ。
6. **将来課題**: 既存 `/register`(メール方式)の扱い（廃止 or 併存）。うちの `cocokaraplus-5526` はコード変更しない（多数テーブル・環境変数・LINE Webhook URLに埋め込み済みのため、やるなら独立の移行タスク）。


---

## §29 施設オンボーディング完成 ＋ 職員LINE紐付け・パスワード再発行（2026-07-03）

### A. 施設オンボーディング：E2E完全動作（DEV・本番未展開）

§28の続き。第3段階フロント＋メール保存まで完成し、DEVでE2E通し確認済み。

**フロー（全自動・実証済み）**
QR/LIFF URL → LINE友だち追加 → LIFFフォーム（`/onboard`, LIFF ID `2010588249-kQNvvhlg`）でuserId自動取得＋施設名・管理者名・メール入力＋プラン×支払い条件フル選択 → Stripe Checkout（サンドボックス・初月無料トライアル `trial_period_days=30`）→ 決済完了webhook → 施設自動発行（`f`+16進10桁のランダムコード）→ 管理者職員を`staffs`に自動生成 → メール保存（`facilities.contact_email` と `staffs.email` 両方）→ 初回設定リンクをTASUKARUアカウントからLINE送信 → `/setup?token=xxx`でパスワード設定 → ログイン成功。

**この日追加した実装**
- `onboard-checkout-v1`：`/api/onboard/create_checkout`（ログイン不要・LIFFフォーム専用）。既存 `create_checkout` は無傷。TERM_MAP・`STRIPE_PRICE_{PLAN}_{SUFFIX}` を流用。subscription時 `trial_period_days=30`。metadataに onboard_id/facility_name/admin_name/line_user_id/plan/term/email。
- `onboard-email-v1`：メール必須化。checkout で email 受領→metadata＋`customer_email`、webhook で `facilities.contact_email` と `staffs.email` に保存。DDL `facilities.contact_email TEXT` 追加済み（DEV）。
- `onboard.html`：LIFFフォーム（施設名・管理者名・メール・プラン3・支払い条件7）。メール欄の重複バグを修正済み。
- コミット: `287e6fe`(フォーム+checkout), `960d313`(email), `0805511`(dup email fix)。

**送信元アカウント是正（重要）**
初回設定リンク等の送信は `line_send_message`（`LINE_CHANNEL_ACCESS_TOKEN`）を使う。これを**オンボーディング用「TASUKARU」アカウント**のトークンに差し替え済み（DEV）。理由: 施設が友だち追加するのはTASUKARUなので、他アカウントのトークンでは届かない。`LINE_CHANNEL_ACCESS_TOKEN` を使う3箇所（招待・開発者通知・オンボーディング）は全てTASUKARUで正しい。

### B. 職員LINE紐付け ＋ パスワード再発行：E2E動作（DEV・本番未展開）

介護現場向け。メールに頼らず、職員が自分のLINEでパスワードを再発行できる。

**DDL（DEV適用済み）**: `staffs` に `line_user_id TEXT` / `link_code TEXT` / `link_code_expires TIMESTAMPTZ`。

**実装（`staff-line-webhook-v1` / `staff-linkcode-api-v1`, コミット `5f86328`）**
- `/line/webhook/tasukaru`：TASUKARU用webhook。署名検証は `LINE_CHANNEL_SECRET`（**TASUKARUのChannel Secretに差し替え済み**）。
  - follow → 案内メッセージ返信
  - 本文が6桁数字 → `link_code` 照合（期限内）→ `staffs.line_user_id` 保存 → 「連携しました」返信
  - 本文に「パスワード」含む＋紐付け済み → `setup_token`発行 → `/setup`リンク返信
  - それ以外 → 使い方ガイド返信
- `/api/admin/issue_link_code`：管理者が対象職員の6桁コード発行（24時間有効・session f_code 限定）。

**LINE Developers 設定（TASUKARU Messaging APIチャンネル `2010177151`）**
- Webhook URL: `https://tasukaru-dev-191764727533.asia-northeast1.run.app/line/webhook/tasukaru`
- 「Webhookの利用」ON、検証「成功」確認済み（初回タイムアウトはCloud Runコールドスタート、2回目で成功）。

**E2E確認済み**: デモ職員Aに6桁コード発行 → LINEで送信 → 連携完了 → 「パスワード」送信 → 再設定リンク受信。

### C. 次回やること（リッチメニュー方式の職員利用開始）※未実装・構想

HIRO案: TASUKARUのLINEに**リッチメニュー**を作り、管理者は「TASUKARU友だち追加リンク」を職員に送るだけ。職員はリッチメニューの「利用開始」から自分で登録（紐付け＋初回設定）。「パスワード再発行」ボタンも常設。

**本人確認は厳密方式に決定**: 施設コード＋職員名＋管理者発行の利用開始コード（＝既存の6桁 `link_code` を流用）の3点照合。

**未実装の必要パーツ**
1. `/staff_start` LIFF画面（施設コード・職員名・6桁コード入力 → userId取得）。
2. 3点照合API（一致で `line_user_id` 紐付け＋`setup_token`発行→`/setup`へ）。既存の照合ロジック（webhook 717-740行付近）と `/setup`（1439行）を流用。
3. LINE DevelopersでLIFFアプリをもう1つ追加（同じLINEログインチャンネル `2010588249` に、エンドポイント `/staff_start`）→ 新LIFF ID取得→画面に埋め込み。
4. リッチメニュー作成（画像＋ボタン領域定義、LINE側作業）。「利用開始」→ staff_start LIFF、「パスワード再発行」→ 既存フロー。
5. E2E確認 → 本番展開。

**補足（管理者の自動紐付け・未実装）**: オンボーディングで作られる管理者は決済時にuserIdが判明しているので、施設発行時に `staffs.line_user_id` へ自動保存すれば紐付け不要にできる（webhook側の軽微改修）。一般職員はリッチメニュー方式で自己紐付け。

### D. 本番展開でやること（オンボーディング＋職員紐付け、まとめて）
1. 本番Supabaseに DDL適用: `staffs.setup_token` / `setup_token_expires`、`facilities.onboard_id`、`facilities.contact_email`、`staffs.line_user_id` / `link_code` / `link_code_expires`。
2. 本番Cloud Runの環境変数: `LINE_CHANNEL_ACCESS_TOKEN`＝TASUKARUトークン、`LINE_CHANNEL_SECRET`＝TASUKARUシークレット に更新（※本番で他機能への影響を確認してから）。
3. 本番TASUKARUチャンネルのWebhook URLを本番Cloud Runの `/line/webhook/tasukaru` に設定。
4. 本番LIFFアプリのエンドポイントを本番 `/onboard`（＋将来 `/staff_start`）に。
5. `tasukaru-dev` → `tasukaru` マージ。

### メモ
- DEVテストデータは都度クリーンアップ（`WHERE onboard_id IS NOT NULL` で施設＋staffs削除）。この日のテスト施設は削除済み。
- 初回設定リンクは `https://` で送出（`request.host_url` を https 補正済み）。

---

## セキュリティ実装（2026-07-05 / Stripe本番化・申告書対応）

Stripe「セキュリティ対策措置状況申告書」対応として、以下を実装・本番リリース済み（本番HEAD `3cbc022`）。

### 認証セキュリティ
- **ログイン失敗ロック** (`login-lockout-v1`): 通常ログインの失敗を記録し10回失敗で15分ロック。テーブル `login_attempts`（`facility_code, ip, fail_count, locked_until` / UNIQUE(facility_code, ip)）。ロック単位は施設コード+IP。IPは `X-Forwarded-For` 先頭。ヘルパ `_login_client_ip / _login_is_locked / _login_record_fail / _login_clear_fail`（`login_required` 直前に定義）。
- **管理者/開発者認証のロック** (`admin-lockout-v1`): `/admin_auth` のadmin段・dev段に同じ失敗ロックを適用。ロックキーは `login_attempts` を流用し `{f_code}#admin` / `{f_code}#dev` で分離（通常ログインと巻き込まない）。旧経路 `/api/admin_login`（"8888"デフォルト・平文照合・権限チェック無しの抜け穴）を403で無効化し、管理者認証を `/admin_auth` に一本化。
- **管理者ログイン2FA** (`admin-2fa-v1`): 管理者認証にLINE経由の6桁コードによる二要素認証を必須化。テーブル `admin_2fa_codes`（`facility_code, staff_name, code_hash, expires_at, attempts` / UNIQUE(facility_code, staff_name)）。コードはSHA-256ハッシュ保存、有効期限5分・試行5回。フロー: パスワード+権限OK → line_user_id取得（未紐付けは入れない=厳格）→ コード生成・LINE送信 → `admin_2fa.html` → `/admin_2fa_verify` で照合成功 → admin_authenticated=True。送信は既存 `line_send_message`。テンプレート `templates/admin_2fa.html` 新設。
  - 注意: `admin_auth` のstaff SELECTに `line_user_id` を含める必要がある（`admin-2fa-select-fix-v1`）。

### アップロード対策
- **拡張子ホワイトリスト** (`upload-ext-guard-v1`): `@app.before_request` フックで全アップロードファイルの拡張子を一括検査。許可（画像/音声/PDF/CSV/Excel）以外を400拒否。危険拡張子（.php/.exe/.js/.html/.svg等）は二重拡張子偽装含め拒否。判定例外時はfail-open（既存機能の全滅防止）。定数 `_UPLOAD_ALLOWED_EXTS / _UPLOAD_DANGEROUS_EXTS`。既存18受け口は無改変。

### オンボーディングと2FAの整合
- **初回管理者のLINE紐付け** (`onboard-admin-line-link-v1`): `stripe_webhook` の初回管理者staffs insertに `line_user_id: ob_user_id` を追加。これが無いと新規施設の初回管理者が厳格2FAで管理者MENUに入れず詰む。
- **checkout必須化** (`onboard-line-required-v1`): `onboard_create_checkout` で `line_user_id` を必須化（空なら400 line_required）。webhook到達時にline_user_idが必ず埋まる状態を保証。
- **旧/register封鎖** (`onboard-register-retire-v1` + `onboard-register-link-v1`): 旧 `/register`（平文admin_password保存・staffs行を作らない・決済を経ず施設作成・メール前提の抜け穴、login.htmlから現役リンクされていた）を `/onboard` へのリダイレクトで無効化。login.htmlの「施設の新規登録はこちら」を `/register`→`/onboard` に付け替え。

### 脆弱性診断体制
- `pip-audit` で依存パッケージの既知脆弱性を診断（pdfkit CVE-2025-26240 を検知したが、TASUKARUは利用者入力を `_esc()` でHTMLエスケープ済みのため攻撃条件に非該当・実リスク無しと評価。修正版未リリースのため監視継続）。
- GitHub Dependabot（dependency graph / alerts / security updates / malware alerts）を有効化し、継続的・自動的な脆弱性・マルウェア検知を運用。

### 前提・運用メモ
- LINEログインチャネル「TASUKARU施設登録」を「開発中→公開」に変更済み（これが無いと開発者ロール以外は利用開始LIFFを開けず、職員・新規施設のオンボーディングが全滅する）。
- 管理者は全員LINE紐付けが必須（厳格2FA）。共用アカウント（PC1/PC2等）は施設共用端末のLINEに紐付ける方針。本番実施設で管理者ロックを10回失敗で試すと自分が締め出される（緊急解除: `UPDATE login_attempts SET fail_count=0, locked_until=NULL WHERE facility_code='cocokaraplus-5526#admin';`）。

---

## 新機能着手: 担当者会議→ICF可視化（PRO限定予定） 基盤第1歩 (2026-07-05)

### 構想
担当者会議を音声録音→文字起こし→議事録生成し、それをICF（国際生活機能分類）の枠組みに自動分類して図で可視化する新機能。「議事録作成」自体は汎用AIでもできるため、差別化の核心は**ICF分類を正確に行うこと**と**文章＋図の二本立てで理解を深め、担当者会議で拾えていない情報（＝ICF上の空白領域）を視覚的に炙り出す**こと。介護・リハのドメイン知識が参入障壁になる。
- **提供形態**: TASUKARU内の新機能。**PRO限定**（既存プラン構造でゲート予定）。
- **ICF粒度**: 最終的に**フル4桁**まで持つ方針。ただしデータ投入は段階リリース（第2レベル→第3・第4レベル）。テーブルは最初から4桁対応。

### 完了: ICFマスタ 第1・第2レベル投入 (`icf-master-l2-v1`)
- **テーブル `icf_codes`**（Supabase, DEV投入済み）: `code`(PK) / `component`(b/s/d/e) / `chapter` / `level`(1=章,2=第2) / `parent_code`(自己参照FK) / `title_ja` / `title_en` / `sort_order`。インデックス: component / parent_code / level。
- **データ**: 厚生労働省 日本語版（出典: dinf.ne.jp掲載の厚労省社会・援護局障害保健福祉部企画課版 = WHO ICF 2001, 2009用語改訂反映）から取得した実値。第1レベル30章＋第2レベル362項目＝計392行。
- **検証済み**: 第2レベル362件が厚労省公式件数と一致。構成要素別 b=122/s=64/d=127/e=79。重複なし・親コード不整合なし。d4配下階層(歩行等)の並びも確認。
- **投入方法**: git管理外（DB直接投入）。生成SQL `icf_codes_seed.sql`（CREATE TABLE + 冪等INSERT `ON CONFLICT DO UPDATE`）を Supabase SQL Editor で実行。**このSQLは手元保管必須**（本番にも同じSQLを流す必要あり。まだ本番未投入）。

### 次タスク（この機能の続き・順番）
1. **フル4桁への拡張**: 第3・第4レベルのデータ投入。dinfの完全版テキスト（第4レベルまで掲載）から同方式でパース→`icf_codes` へ追加投入。テーブルは4桁対応済みなので追加のみ。全1,443項目が最終形。
2. **本番へのマスタ投入**: `icf_codes_seed.sql`（および4桁拡張分）を本番Supabaseにも流す。
3. **会議データモデル**: `meetings`（録音・文字起こし・議事録）等の新テーブル設計。音声文字起こしは連絡帳・評価画面の既存実績を流用。
4. **AI分類フロー**: 議事録を `icf_codes` に照合してICF分類。**AIに候補を出させ人が確定**する方式（クレカ明細Amazon突合・勘定科目学習と同じ「人が承認」思想）。AIの記憶に頼らずマスタから選ばせるのが精度の鍵。
5. **画面**: 文章＋ICF図（構成要素b/s/d/e別・章別グルーピング）。空白領域＝次に確認すべき情報として可視化。
6. **PRO限定ゲート**: 既存プラン判定で機能を出し分け。

---

## ICFフル4桁化の調査メモ（2026-07-05 追記 / 重要・次回の前提）

第3・第4レベル（フル4桁）への拡張を検討し、データ源を調査した結果、以下が判明。**次回この結論から再開すること（同じ調査を繰り返さない）。**

### データ源の現実（調査結果）
- **日本語のフル4桁データはWeb上に公式公開されていない。** 厚労省HP（および dinf.ne.jp 掲載の厚労省版）は明示的に「HP上では第2レベルまで掲載」と断っている。第3・第4レベルの日本語公式データは**書籍版『ICF国際生活機能分類—国際障害分類改訂版』（中央法規出版）にのみ収録**。
- **英語のフル4桁はWHOが公開しているが、一括取得は容易でない。** WHO公式 ICF Browser（apps.who.int/classifications/icfbrowser）はJavaScript依存のブラウザアプリで直接取得不可（fetch 404）。CSV/Excelの全項目一括配布は未確認（ICD-11にはあるがICFは別）。1コードずつ辿るのは1,443項目で非現実的。ICF Core Sets等の二次配布は部分的。
- **ライセンス（重要・確認済み）**: WHO公式に「ICFは、機能・障害の評価を支援する**AIシステムの適法な学習を含め**、WHO加盟国全体での使用が公的に許可されている」と明記。ICFデータをICF分類AIに使うことはWHOが明示的に許可済み。

### 確定した方針（第3・第4レベル）
- **英語4桁マスタ（WHO由来）＋ AI暫定日本語訳 ＋ 公式フラグで区別**、というハイブリッドで持つ。
- テーブル `icf_codes` に将来追加想定のカラム: `title_ja_draft`（AI暫定訳）, `is_official`（bool: 第2レベルまで=true=厚労省公式 / 第3・4レベル=false=暫定訳・要監修）。
- **絶対原則**: AIの丸ごと翻訳を「公式マスタ」として断定しない。公式（is_official=true）と暫定訳（false）をデータ上で明確に区別し、画面でも「※暫定訳」と示す。これを崩すと「厚労省公式準拠の正確なICF」という看板が嘘になる。将来HIROが書籍版で照合して確定分を is_official=true に昇格。
- **粒度の実用性**: 複数の公式資料が「介護の担当者会議レベルは第2レベルで十分活用でき、第4レベルはリハビリ効果検証など専門用途」と明記。よって第2レベルで機能先行し、4桁は精度が要る場面で追加する方針で問題ない。

### 次回の選択肢（未着手）
- (A) 会議データモデル（`meetings` 等）＋AI分類フローの設計に進む（第2レベルマスタで機能を形にする）← 前進重視ならこちら
- (B) 英語4桁データの取得経路を腰を据えて調査（WHO Browserの内部API/データファイル特定、または信頼できる二次配布の発掘）。確実に取れる保証はないため、独立タスクとして計画的に。

---

## 担当者会議 ICF分類機能 サーバ側完成（2026-07-06 追記）

担当者会議を録音→文字起こし→議事録生成→ICF分類し、付箋ボードで可視化する機能（PRO限定予定）。サーバ側が一通り完成。次回は**フロント（録音の時間分割ロジック＋付箋ボード画面）から再開**。

### 完了（DEV投入・push済み。本番未マージ）
DB（DEV Supabaseに投入済み。本番は機能リリース時に同SQLを流す）:
- `meetings`（marker: meetings-ddl-v1）: 会議レコード。id/facility_code/patient_id(uuid,nullable)/title/meeting_date/audio_path/transcript/minutes/status/created_by。`audio_session_id`（marker: meetings-audio-session-v1）追加済み。
- `meeting_icf_links`（meetings-ddl-v1）: 付箋1枚=1行。icf_code(FK,null許容=手動メモ付箋)/source_text/note/confidence(auto|needs_review)/confirmed/board_component(b/s/d/e)/sort_order/qualifier_capacity/qualifier_performance（2軸は将来用・今NULL）。次点候補 `alt_icf_code`/`alt_reason`（meetings-icf-altcand-v1）追加済み。
- ゲート: `admin_settings` に `meetings_enabled`。DEMO001は`true`投入済み（実質限定運用。将来PROプランで解放）。**admin_settingsに(facility_code,key)のUNIQUE制約は無い**ので on conflict 不可。既存行の有無を見て insert/update を出し分ける。

API（app.py。既存流儀準拠。権限は共通ヘルパー `_meetings_gate_ok()` = login_required + meetings_enabled）:
- `/api/meeting/transcribe`（POST, meetings-transcribe-chunk-v1）: 録音チャンク1個を受け取り、`assessment-audio/{f_code}/meetings/{session_id}/{index:04d}.{ext}` に保存しつつGeminiで文字起こし。**長時間会議はフロントで時間分割（方式1）**し順次呼ぶ。保存失敗してもfail-safeで文字起こし続行。無音チャンクは空文字返す。フォーム: audio/session_id/chunk_index。音声はassessment-audioバケット流用（utils無改修）。
- `/api/meeting/summarize`（POST, meetings-transcribe-summarize-v1）: 文字起こし→ICF分類しやすい議事録生成（Gemini）。
- `/api/meeting/classify_icf`（POST, meetings-icf-classify-v1）: 議事録→ICF分類。**方式A＋次点候補**（全362件をicf_codesから動的取得しプロンプトに埋め、迷えばalt1件）。マスタ外コードは弾く（創作防止）。入力=minutes_text直POST。model=claude-sonnet-4-5。**テスト議事録で分類精度検証済み・良好**（膝の痛みb280と関節可動性b710を正しく分離、福祉用具e120まで拾う、4構成要素に分布）。ただしテストではneeds_review/altが0件→曖昧議事録での挙動は未検証。
- `/api/meeting/save`（POST, meetings-save-list-get-v1）: **案X（保存時に一括作成）**。meetings 1件insert→付箋を一括insert。patient_idはUUID検証しng時null。マスタ外コードは握りつぶさずnoteに`[未確定:xxx]`退避。
- `/api/meeting/list`（GET）: 施設の会議一覧（meeting_date→created_at降順・最大200）。
- `/api/meeting/get`（GET, meeting_id）: 会議＋付箋を読み込み（ボード復元）。他施設IDは弾く。

### 設計確定事項（次回の前提。再検討不要）
- 付箋ボードUI: b/s/d/e の4領域に付箋をドラッグ移動＋空白セルから手動追記。AI確定(塗り)と要確認(破線)を色分け。空白領域を明示（＝会議で拾えていないICF上の空白の可視化＝差別化の核心）。次点候補は付箋に「もしかして: d460?」と小さく出しワンタップで移せる想定。
- 「活動と参加(d)」は**まず1軸で機能化**（分けない）。能力/実行の2軸（ICF公式qualifier）は `qualifier_capacity`/`qualifier_performance` カラムを仕込み済みで**後付け可能**。
- 権限は施設ユーザゲート＋将来PRO。当面meetings_enabledで実質限定start。
- 音声は保存する方針（後で聞き直せる）。録音は長時間前提でフロント時間分割（5分チャンク等）→順次transcribe→連結→summarize→classify→save。session_idはフロント発行UUIDでチャンクを束ね、save時にmeetings.audio_session_idに記録。

### 次にやること
1. **フロント実装**（メイン）: 録音UI（MediaRecorderで時間分割・session_id発行・chunk_index順次送信）→ 文字起こし連結表示 → 議事録編集 → 「ICF分類」→ 付箋ボード（ドラッグ移動・追記・承認）→ 保存。会議一覧・読み込み画面。PRO限定ゲート表示。
2. 曖昧な議事録で needs_review / 次点候補(alt) の出方を検証。
3. ICF図の可視化（構成要素別・章別グルーピング、空白領域の見せ方）。

### ブランチ状態
- DEV(tasukaru-dev) HEAD = 46786f8（会議API群・DDL・READMEを含む見込み）。本番未マージ。
- 本番マージ時に必要: 本番Supabaseへ meetings系DDL（meetings_seed.sql / meetings_altcand.sql / meetings_audio_session.sql）を先に流す＋ icf_codes_seed.sql（未投入なら）＋ admin_settingsに本番施設のmeetings_enabled。

---

## 担当者会議 ICF分類機能 フロント骨格＋第4表議事録 完成（2026-07-06 追記その2）

同日その1(サーバ側完成)の続き。フロント骨格が動作確認済み、議事録が第4表準拠に格上げ。すべてDEV。本番未マージ。

### 完了（DEV push済み・動作確認済み）
- **画面** `/admin/meetings`（route marker: meetings-page-route-v1 / template: templates/admin_meetings.html）。既存admin_*流儀（base.html継承・block content・緑系デザイン・CSRFなし）。単一ページ内ステップ遷移（一覧⇔編集ビュー）。`admin_authenticated` + `_meetings_gate_ok()` の二重ガード。管理者MENUへの導線リンクはまだ未設置（当面は直URLで確認）。
- **フロントのフロー**（録音以外MCP確認済み）: 一覧(list)→新規→会議情報(タイトル/開催日/対象利用者)→録音UI(MediaRecorderで5分チャンク自動分割・session_id発行・chunk_index順次transcribe・連結)→文字起こし(編集可)→「議事録を作成」(summarize)→「ICF分類する」(classify_icf)→結果表示→「保存」(save一括)。既存会議はget で復元。
- **動作確認結果**: 新規→議事録貼付→分類13件(次点候補d540→d440も的確に出た)→保存(会議+付箋13件)→一覧反映→get復元(board_component/confidence/次点候補まで完全復元)まで一気通貫でOK。テスト会議 a96d8dad がDEMO001に1件残存(ダミー・無害)。
- **バグ修正済み**: 一覧生成のonclick属性でシングルクオート過剰エスケープ→SyntaxErrorで全JS未定義だった。data-mid属性＋addEventListener(イベント委譲)に変更して解決。`\\n`(バックスラッシュ2つ)→`\n`も2箇所修正。**教訓: Jinjaテンプレ内のJSは引用符を素直に書く。onclick属性に文字列を埋めるより data-* + イベント委譲が安全。**
- **議事録を第4表準拠に格上げ**（marker: meetings-summarize-form4-v1 / 方向C）。厚労省標準様式「第4表 サービス担当者会議の要点」の5セクション(開催情報/検討した項目/検討内容/結論(決定事項)/残された課題・次回)＋末尾に「本人の状態整理(ICF分類用)」。**最重要ルール: 正式書類のため文字起こしに無い情報(出席者氏名・開催場所・開催日)は創作せず「（記載なし）」**。MCP確認で第4表構成・創作なし・結論独立・次回開催時期抽出・ICF状態整理まで良好に生成されることを確認済み。

### 設計確定・気づき（次回の前提）
- OCR拡張の方針を決定: **会議資料(ケアプラン第1〜3表・アセスメント・主治医意見書等)をカメラ/ファイルで撮影→OCR(Gemini画像解析)→テキスト抽出→議事録生成(summarize)の入力に合流**（方向A採用）。口頭で出ない基礎情報(要介護度・既往・長期短期目標・既存サービス)でICF材料を厚くし、空白領域炙り出しの精度を上げる。既存資産 `parse_assessment_file` / `api_ledger_ocr_receipt`(Gemini画像OCR) の流儀を流用可能。まず様式を問わない汎用OCR(1枚撮って本文抽出)から。第2表専用パーサ等は後回し。
- 開催情報(日付・場所・出席者氏名)は議事録で（記載なし）になりがち→**フロントの会議情報フォームに出席者欄を足し、summarizeプロンプトに渡して実データで埋める**改善余地(後回し可)。
- 対象利用者selectは現状「選択なし」のみ(患者リスト取得を未実装)。ボード実装前後で患者リスト取得を足す。

### 次にやること（優先順）
1. **付箋ボードのドラッグUI**（メイン未実装）: b/s/d/e 4領域に付箋ドラッグ移動・空白セルから手動追記・AI確定/要確認の色分け・次点候補ワンタップ移動・承認(confirmed)。保存時に board_component/sort_order を持たせる。get復元でボード描画。
2. **会議資料OCR**（方向A）: フロントにカメラ/ファイル選択→OCR API(Gemini画像)→抽出テキストを議事録生成の入力に合流。
3. 会議情報フォームに出席者欄追加＋summarizeへ受け渡し。患者リスト取得。
4. 曖昧議事録で needs_review/次点候補の出方を検証。
5. 録音の実機確認(マイクが要る・HIRO操作。MCPでは不可)。長時間(数十分×5分チャンク)の通しテスト。
6. ICF図の可視化(構成要素別・章別グルーピング・空白領域の見せ方)。

### ブランチ状態
- DEV(tasukaru-dev) HEAD = de5e559（会議API群・DDL・フロント・第4表議事録・READMEを含む見込み）。本番未マージ。
- 本番マージ時に必要(再掲): 本番Supabaseへ meetings系DDL 3本(meetings_seed / meetings_altcand / meetings_audio_session)＋icf_codes_seed(未投入なら)＋admin_settingsに本番施設のmeetings_enabled。assessment-audioバケットを会議チャンク保存に流用中(既存バケット)。

---

## 担当者会議 アセスメントシート＋3成果物PDF出力 完成（2026-07-06 追記その4）

同日その3の続き。現場要望対応: 議事録からアセスメントシート生成、そこからICF分類、3成果物すべてPDF出力。すべてDEV・MCP動作確認済み。本番未マージ。

### 現場要望（達成済み）
「議事録作成後、そこからアセスメントシートを作成し、さらにその情報からICFを分類。3つの成果物(議事録・アセスメント・ICF分類ボード)を作れて、それぞれ印刷・PDF保存できる機能」＋「ハルシネーション絶対なし」「職員が全項目を修正・削除・追加できる」。

### 完了（DEV push済み・MCP確認済み）
- **アセスメントシート生成API** `/api/meeting/assessment`(POST, marker: meetings-assessment-api-v1): 議事録+文字起こし→課題分析標準項目23項目(令和5年改定版)をJSON配列で生成(Gemini)。**ハルシネーション対策を多層で担保**: プロンプトで創作厳禁・無い項目は必ず recorded:false / body:「（未記載）」、生成後の正規化でも body が「（未記載）」なら recorded を強制false。MCP確認: 23項目生成・基本情報系(社会保障/認定情報/じょくそう/口腔/コミュニケーション等)が創作されず正しく未記載、語られた内容は該当項目に整理、を確認。
- **アセスメント編集UI**(admin_meetings.html, meetings-assessment-v1): 23項目を**項目ごとに編集・削除・追加**。未記載項目はグレー破線表示、職員が手入力で補完(未記載↔記載でスタイル即時切替)。「＋項目を追加」で新規、各項目に削除ボタン。MCP確認: 未記載への手入力→記載化、項目追加、項目削除、すべて保存・復元まで確認。
- **DB**: `meetings.assessment`カラム追加(text, DDL meetings-assessment-v1, DEV投入済み)。項目配列のJSON文字列を保存。
- **ICF分類の入力元トグル**: 「アセスメントから分類 / 議事録から分類」を選択可(meetings-assessment-wire-v1)。classify_icf の入力を汎用化(minutes_text 無ければ source_text 使用)、プロンプトの「議事録」を「会議情報」に汎用化。saveにassessment追加。MCP確認: アセスメントから分類→11付箋生成OK。
- **3成果物PDF出力** `/api/meeting/pdf?meeting_id=xxx&type=minutes|assessment|icf`(GET, marker: meetings-pdf-v1 / makeresp-fix: meetings-pdf-makeresp-fix-v1): 方式A(pdfkit/wkhtmltopdf、既存ledger/monitoring流儀準拠)。議事録=第4表体裁、アセスメント=23項目table、ICF=モデル図6スロットをtableで静的再現。**wkhtmltopdf制約対応**: Flexbox不使用tableベース、@page margin避けbody padding。**注意: make_response は関数内で個別import必須**(トップレベルflask importに無い。既存PDF関数も同様)。フロントは各カードにPDFボタン(保存済み会議のみ表示、保存後はその場に留まりPDF可)。MCP確認: 3タイプとも200・正しい%PDF・妥当サイズ(議事録26KB/アセス90KB/ICF25KB)。**レイアウト目視はHIRO実機確認が必要**(MCPはバイナリ生成成功までしか見えない)。

### 設計確定事項
- アセスメント様式=課題分析標準項目23項目(令和5年改定)。基本情報9項目+課題分析14項目+特記。
- 編集方式=案A(JSON構造、項目ごと編集/削除/追加)。案B(ベタテキスト)は不採用。
- ハルシネーション絶対なし=最優先要件。未記載を明示し職員が補完。人が承認思想。
- PDF=方式A(サーバpdfkit)で3成果物統一。ICFボードはFlexNGなのでtable静的版。

### 次にやること
1. **アセスメントPDFのレイアウト目視確認**(HIRO実機。文字化け・表崩れ・モデル図配置)。必要なら微調整。
2. **分類AIの活動/参加自動振り分け**(任意・精度向上、これまで通り保留可)。
3. **会議資料OCR**(方向A): カメラ/ファイル→Gemini画像OCR→議事録/アセスメント生成の入力に合流。既存 parse_assessment_file / api_ledger_ocr_receipt 流用。
4. アセスメント項目の振り分け精度微調整(意欲低下/睡眠が「これまでの生活」に入る等の軽微なズレ。プロンプト調整で改善可)。
5. 会議情報フォームに出席者欄追加。患者リスト取得。管理者MENU導線リンク設置。実機ドラッグ/録音確認。

### ブランチ状態
- DEV(tasukaru-dev) HEAD = bdc0a0e。本番未マージ。
- 本番マージ時に必要(再掲・更新): 本番Supabaseへ meetings系DDL 5本(meetings_seed / meetings_altcand / meetings_audio_session / meetings_board_slot / meetings_assessment)＋icf_codes_seed(未投入なら)＋admin_settingsに本番施設のmeetings_enabled。assessment-audioバケットを会議チャンク保存に流用中。wkhtmltopdf・日本語フォントはイメージ導入済み。
- テスト会議数件がDEMO001に残存(ダミー・無害)。

---

## 担当者会議 PDF出力・音声・導線 大幅拡張（2026-07-06 追記その5）

同日その4の続き。3成果物PDF出力の実装後、実際の会議音声で通しテストし、多数の改善を実施。すべてDEV・MCP確認済み。本番未マージ。DEV HEAD = 65cd50f。

### 完了（DEV push済み・MCP確認済み）

**PDF makeresp修正（marker: meetings-pdf-makeresp-fix-v1）**: 3成果物PDFが `make_response is not defined` で500。トップレベルflask importに make_response が無く、既存PDF関数は各関数内で個別importしていた。同様に関数内importを追加して解決。

**音声ファイルアップロード（フロントのみ）**: 録音カードに「音声ファイル」ボタン追加。既にある会議音声を選択→Web Audio APIでデコード→5分ごとに時間分割→各チャンクをWAV化→既存 transcribe API へ順次送信（サーバ改修不要）。長時間音声も安全。実際の会議音声で文字起こし成功。

**ICF図PDFリッチ化（marker: meetings-pdf-rich-icf-v1）**: コードのみ表示→icf_codesマスタを引いて名称付き（b114 見当識機能）に。スロット別の色付き付箋（画面ボードと同配色）、分類根拠テキスト表示。あわせて**PDFキャッシュバグ修正**: 別会議のPDFに前の会議の内容が出る問題。フロントでPDF URLにタイムスタンプ `_t=Date.now()` 付与＋サーバでno-cacheヘッダー（Cache-Control: no-store...）。出席者オブジェクト形式 {name,role} 対応（marker: meetings-pdf-attendees-fix-v1、「役職（氏名）」形式、氏名不明は役職のみ）。

**議事録3スタイルPDF（A/B/C）**: 議事録を構造化データ(minutes_struct)で持ち、3レイアウトに流し込む。
- 案A=ヘッダー表＋見出し区切り(バランス・スッキリ)、案B=決定事項を番号強調(ビジネス)、案C=公的様式風の罫線(フォーマル)。visualizerでモック3案提示しHIROが選択→3スタイル選択式に決定。
- DB: `meetings.minutes_struct`(text, DDL marker: meetings-minutes-struct-v1, DEV投入済み)。
- **構造化の作り方(重要)**: 当初 summarize が Gemini で構造化JSONも生成する方式(marker: meetings-minutes-struct-api-v1)だったが、長い会議(20585字)で議事録生成に43-45秒かかりタイムアウト/500発生。→ **コード解析方式に変更**(marker: meetings-minutes-struct-parse-v1): `_mtg_parse_minutes_struct(text)` が第4表議事録本文の「■見出し」をパースして構造化dict生成。Gemini再生成不要で速度は本文生成のみに。
- **重大バグと修正(教訓)**: パーサ関数定義を `@app.route` と `def api_meeting_summarize` の間に挿入してしまい、デコレータがパーサに付いて全summarizeが500に。→ パーサをデコレータの前へ移動(marker: meetings-minutes-struct-parse-fix-v1)。**教訓: デコレータとdefの間に関数を挿入してはいけない**。
- save/get で minutes_struct 保存・復元(marker: meetings-minutes-struct-save-v1)。フロントは議事録カードにA/B/C 3ボタン(保存済み+議事録ありで表示)、mtgPdf(type,style)。
- MCP確認: 20585字で200・items4/conclusions4・構造化OK。3スタイルとも200・正しいPDF。

**3点まとめてPDF（marker: meetings-pdf-all-v1）**: type=all で議事録・アセスメント・ICF図を1つのPDFに(page-break区切り)。各ビルダーの<body>中身を `_mtg_pdf_extract_body()` で抽出し連結。3成果物揃うと緑の「まとめてPDF」ボタン表示。実際の会議音声で3点入りPDF生成成功。

**タスカルくんローディング**: 議事録作成中(43秒)、議事録カードにタスカルくんが左右に走り真ん中に書類が積み上がるアニメ表示(mtgTskOverlay)。既存の `static/tasukaruカラー.png` を影絵処理(filter:brightness(0) opacity(0.5))で流用。ケース記録カテゴリ変更のタスカルくん歩行アニメと同トーン。mtgSummarize 実行中だけ is-active。

**ICF図PDF 1枚化（marker: meetings-pdf-icf-fit-v1）**: 付箋が多い実会議でICF図が崩れた(3列に大量付箋で潰れ)。付箋総数に応じてフォント/padding/根拠長を自動縮小(density: ≤12/≤20/≤30/それ超)、@page A4 landscape(横向き)、列幅固定33.33%＋word-break折り返し、根拠テキストを密度に応じ短縮。**単独ICF図PDFには効くが、まとめPDF(type=all)内のICFには未反映**(まとめは縦向き固定でICFビルダーの@page landscapeが無視される。次回対応)。

**ボトムメニュー修正・導線追加（base.html）**:
- 連絡帳(/renraku)が並び替え対象から漏れていたのを修正(movableHrefs 3箇所に追加、marker: nav-renraku-movable-v1)。
- 担当者会議の入り口「記録・ICF分類」をボトムメニューに追加(href=/admin/meetings, groupsアイコン, marker: nav-meetings-v1)。並び替え対象にも追加(movableHrefs 3箇所に /admin/meetings)。**現状は全施設に表示**(PRO制限は次回)。

### 重要な教訓（今回得た）
- **デコレータとdefの間に関数を挿入禁止**(元関数のデコレータが新関数に付き500)。パーサ挿入で実際に発生。
- パッチのアンカーに日本語を含めるとエンコード差異でマッチ0件になりやすい→**ASCII行(markerコメント/純英数字行)を小さいアンカーに**。大きな塊は空行有無でも失敗。
- 冪等パッチを2回実行すると2回目ALREADY_APPLIED。git commitは1回目の変更を拾うので問題なし(HIROが2回貼りがちだが害なし)。
- **議事録生成が43秒かかるのはモデルでなく処理量**(20585字入力8000字切り+3000字出力)。既にgemini-2.5-flash使用中。構造化をコード化しても本体生成時間は不変。タイムアウト対策/UX(タスカルくん)で緩和。utils.py get_generative_model は全機能共通なので変更は全機能影響。
- 「できない/変わってない」は手順・未保存・キャッシュ・未実装が原因のことが多い。MCPで実際に叩いて切り分ける(例: 3スタイルボタンは保存済み+議事録ありでのみ表示)。

### 次にやること（PENDING）
1. **[要対応] PDF出力の使い勝手改善(次回まとめて)**:
   (a) **まとめPDF内のICF崩れ**: type=all のICFにも1枚化(横向き/自動縮小)を反映。ただしwkhtmltopdfは1PDF内で向き混在が苦手→ICFだけ別PDF化して結合、またはまとめ全体を横向き、等の設計判断が要る。
   (b) **文字サイズ選択(小/標準/大)**: 未実装。「数行だけ次ページに溢れる」対策。PDF生成前にサイズ選択→パラメータで反映。
   (c) **一括印刷時も議事録スタイル(A/B/C)選択**: 現状 type=all は議事録スタイルA固定。選べるようにする。
2. **[報告済み・未対応] 対象利用者selectが選択できない**: 患者リスト取得が未実装(selectが空)。
3. **[報告済み・未対応] 一覧から会議記録を削除できない**: 削除機能未実装。
4. **担当者会議のPRO制限**: 開発者MENU(dev_menu.html)にオン/オフトグル追加(既存 toggleTimecard 等のパターン: /api/dev/toggle_meetings + 一覧に meetings_enabled)。ボトムの「記録・ICF分類」を meetings_enabled=true の施設だけ表示(base.htmlに施設フラグのコンテキスト受け渡しが必要)。本番マージ前に必須。
5. アセスメント項目の振り分け精度微調整(軽微)。分類AIの活動/参加自動振り分け(任意)。会議情報フォームに出席者欄追加。実機ドラッグ/録音確認(MCP不可)。

### ブランチ状態
- DEV(tasukaru-dev) HEAD = 65cd50f。本番未マージ。
- 本番マージ時に必要(更新): 本番Supabaseへ meetings系DDL(meetings_seed/altcand/audio_session/board_slot/assessment/**minutes_struct**)＋icf_codes_seed(未投入なら)＋admin_settingsに本番施設の meetings_enabled。wkhtmltopdf・日本語フォント導入済み。tasukaruカラー.png は static に既存。
- **本番マージ前に必須**: PRO制限(導線を meetings_enabled 施設のみ表示)。現状は全施設にボトム「記録・ICF分類」が出る。
- テスト会議が DEMO001 に複数残存(ダミー・無害)。

---

## 担当者会議 PDF仕上げ（まとめPDF結合・ICF横向き・議事録8スタイル）（2026-07-06 追記その6）

同日その5の続き。まとめPDFのICF崩れ解消、議事録デザイン拡張。すべてDEV・MCP確認済み。本番未マージ。DEV HEAD = 4dd6778。

### 完了（DEV push済み・MCP確認済み）

**まとめPDF(type=all)を結合方式に変更（marker: meetings-pdf-all-merge-v1）**: 従来は3成果物のbodyを1HTMLに連結して1回のwkhtmltopdfで生成→ICFの横向きが効かず崩れた。→ **議事録+アセスメント(縦) と ICF図(横) を別々にPDF生成し結合**する方式に。
- `_mtg_pdf_render(html_str, landscape=False)`: pdfkit生成。landscape=Trueで options に orientation:Landscape(marker: meetings-pdf-landscape-opt-v1)。
- `_mtg_pdf_merge(pdf_bytes_list)`: **堅牢版(marker: meetings-pdf-merge-robust-v1)**。pdfunite(poppler-utils, 依存追加なし) → PyMuPDF(fitz) → 先頭のみ、の順にフォールバック。**重要教訓**: fitz(PyMuPDF)はローカルMacには有るが本番Cloud Runイメージには無い(`No module named 'fitz'`で500)。requirements未記載。pdfuniteは poppler(既存, pdfinfo使用実績あり)に含まれ本番で使える。
- all分岐: 縦PDF(議事録+アセス, page-break)＋横PDF(ICF)を生成→結合。後段共通pdfkitは `_combined_pdf` 有り時スキップ。MCP確認: type=all 200・約298KB。実機でICFが横向きページで崩れず出ることをHIRO確認済み。

**ICF図PDF 横向き化（marker: meetings-pdf-landscape-opt-v1）**: CSSの @page landscape だけでは wkhtmltopdf は縦のまま。**options に orientation:Landscape が必須**。単独ICF図PDF(type=icf)も共通options に icf判定で Landscape 追加。まとめPDF内ICFも landscape=True。HIRO実機で横向き確認済み。

**議事録8スタイル（A〜H）（marker: meetings-pdf-minutes-styles2-v1 / styles-ah-v1）**: 既存A/B/Cに D/E/F/G/H を追加。
- A スッキリ(表+見出し) / B ビジネス(決定事項番号強調) / C フォーマル(公的様式罫線) / D サイドバー(左に濃緑情報帯・高級感) / E カード(決定事項強調・ダッシュボード風) / F タイムライン(縦ライン+ドットで議事を追う) / G エグゼクティブ(セリフ体見出し・ローマ数字Ⅰ-Ⅳ・モノトーン・格調) / H モダンミニマル(余白・細アクセント・大きな01-03番号・英語ラベルMEMBERS/AGENDA/DECISIONS/NOTES)。
- 全スタイル wkhtmltopdf対応(tableベース・Flexbox不使用)。visualizerでモック提示しHIRO選択。
- style バリデーションを2箇所とも a-h に拡張(marker: meetings-pdf-styles-ah-v1)。
- フロント: 議事録カードに8スタイルの `<select id="mtgStyleSelect">`。議事録PDFボタン・まとめPDFボタン両方が選択スタイルを使う。MCP確認: a-h 8スタイルとも200、まとめPDFも style指定で200。
- **HIRO実機のレイアウト目視は要確認**(特に D の濃緑背景ベタ塗りが wkhtmltopdf で出るか、G のセリフ体/ローマ数字、H の大番号)。モックと差異あれば調整。

### 重要な教訓（今回得た）
- **本番(Cloud Run)とローカルでインストール済みライブラリが違う**。ローカルで `import fitz` が通っても本番に無いことがある。PDF結合等は依存追加不要な poppler コマンド(pdfunite)を第一候補にし、フォールバックを重ねると堅牢。
- **wkhtmltopdf の用紙向きは CSS @page でなく options の orientation で決まる**。
- 日本語を含むアンカーはマッチ0になりやすい→ ASCII行(`if style == "c":` 等)を小アンカーに。

### 次にやること（PENDING）
1. **[着手予定] 対象利用者selectが選択できない**: 患者リスト取得が未実装(selectが空)。次はこれに着手。
2. **[報告済み・未対応] 一覧から会議記録を削除できない**: 削除機能未実装。
3. **文字サイズ選択(小/標準/大)**: 未実装。「数行だけ次ページに溢れる」対策。PDF生成前にサイズ選択→ベースフォントに反映。
4. **担当者会議のPRO制限**: 開発者MENU(dev_menu.html)にオン/オフトグル追加(既存 toggleTimecard パターン: /api/dev/toggle_meetings + 一覧に meetings_enabled)。ボトム「記録・ICF分類」を meetings_enabled=true の施設だけ表示(base.htmlに施設フラグのコンテキスト受け渡し要)。**本番マージ前に必須**(現状 全施設にボトム表示)。
5. 議事録8スタイルの実機レイアウト目視・微調整。アセスメント項目の振り分け精度微調整(軽微)。分類AIの活動/参加自動振り分け(任意)。実機ドラッグ/録音確認(MCP不可)。

### ブランチ状態
- DEV(tasukaru-dev) HEAD = 4dd6778。本番未マージ。
- 本番マージ時に必要(更新): 本番Supabaseへ meetings系DDL(seed/altcand/audio_session/board_slot/assessment/minutes_struct)＋icf_codes_seed(未投入なら)＋admin_settingsに本番施設 meetings_enabled。wkhtmltopdf・日本語フォント・poppler(pdfunite/pdfinfo)導入済み。tasukaruカラー.png は static に既存。**PyMuPDF(fitz)は本番未インストールだが pdfunite フォールバックで動作**。
- **本番マージ前に必須**: PRO制限(導線を meetings_enabled 施設のみ表示)。
- テスト会議が DEMO001 に複数残存(ダミー・無害)。

---

## 担当者会議 利用者検索UI・見出し強調（2026-07-06 追記その7）

同日その6の続き。対象利用者の検索UI化、議事録見出しの強調、検索候補の重なり修正。すべてDEV・確認済み。本番未マージ。DEV HEAD = 27c8888。

### 完了（DEV push済み）

**対象利用者を検索UIに（記録入力と同じ操作感）**: 当初selectドロップダウンにしたが、利用者数が多く(DEMO001で52名)選びにくい→ **検索ボックス+候補リスト+選択バッジ**に変更(assessment.htmlの利用者検索UIと同方式)。
- データは既存API `/api/patients_cache`(get_patients返却: id=patient_profiles.id UUID, user_name, patient_number, user_kana等)を流用。サーバ改修不要。
- `mtgLoadPatients()` が起動時に配列 `mtgPatientList`(id/name/kana/no) を先読み。`mtgFilterPatients(q)` が名前/ふりがな/番号で絞り込み(50件制限)、`mtgSelectPatient(id)` で hidden input(#mtgPatient) にUUID保持+緑バッジ表示、`mtgClearPatient()` でクリア、`mtgShowPatientById(id)` で保存済み会議を開いた時にバッジ復元。候補外クリックで閉じる。
- save は従来通り hidden #mtgPatient の値(UUID)を patient_id として送るので変更不要。mtgOpen は `await mtgLoadPatients()` 後に `mtgShowPatientById(m.patient_id)`。startNew は `mtgClearPatient()`。

**検索候補が下のカードに潜る問題を修正(z-index)**: 候補ドロップダウンが次のカード(録音カード等)の下に隠れた。→ 会議情報カードに `id=mtgInfoCard; position:relative; z-index:50`、候補リスト `.mtg-pcands` を z-index:1000 に。会議情報カード全体を後続カード(static)より前面にし、その中の候補を最前面に。**注意: 他画面の検索(記録入力/評価/生活機能check等, eval-candidates等)でも同種の潜り込みが起きている可能性あり。必要なら各画面で同様のz-index対応が要る(未対応)。**

**議事録スタイルの見出しを強調(marker: meetings-pdf-heading-emph-v1)**: 各セクション見出しを太く大きく(D-H)。D `.body .sh` 10.5→12.5pt / E `.ebox .bt` 10.5→12.5pt・`.ecards .cl` 8.5→10pt / F `.tl .h` 10→12.5pt / G `.gsh` 11.5→13.5pt+bold / H `.hdec` 8.5→11pt+bold・`.hlb` 8→9.5pt+bold。数値のみ変更。**A/B/Cは既に見出しが太字+罫線のため未変更**(必要なら追加強調可)。

### 次にやること（PENDING）
1. **文字サイズ選択(小/標準/大)**: 未実装。「数行だけ次ページに溢れる」対策。PDF生成前にサイズ選択→ベースフォントに反映。styleと同様に fontsize パラメータをサーバで受けCSSに反映。
2. **[報告済み・未対応] 一覧から会議記録を削除できない**: 削除機能未実装。
3. **担当者会議のPRO制限(本番マージ前必須)**: 開発者MENU(dev_menu.html)にオン/オフトグル追加(既存 toggleTimecard パターン: /api/dev/toggle_meetings + 一覧に meetings_enabled)。ボトム「記録・ICF分類」を meetings_enabled=true の施設だけ表示(base.htmlに施設フラグのコンテキスト受け渡し要)。現状 全施設表示。
4. **他画面の検索候補z-index**: 記録入力/評価等でも候補が潜るなら対応。
5. 議事録8スタイル・見出し強調の実機レイアウト目視。A/B/Cの見出し強調(任意)。アセスメント項目振り分け精度微調整(軽微)。分類AIの活動/参加自動振り分け(任意)。実機ドラッグ/録音確認(MCP不可)。

### ブランチ状態
- DEV(tasukaru-dev) HEAD = 27c8888。本番未マージ。
- 本番マージ時に必要(更新): 本番Supabaseへ meetings系DDL(seed/altcand/audio_session/board_slot/assessment/minutes_struct)＋icf_codes_seed(未投入なら)＋admin_settingsに本番施設 meetings_enabled。wkhtmltopdf・日本語フォント・poppler(pdfunite/pdfinfo)導入済み。tasukaruカラー.png は static に既存。PyMuPDF(fitz)は本番未インストールだが pdfunite フォールバックで動作。
- **本番マージ前に必須**: PRO制限(導線を meetings_enabled 施設のみ表示)。
- テスト会議が DEMO001 に複数残存(ダミー・無害)。

---

## 【開発ログ】2026-07-09〜10 勤怠フルセット＋前半6件 本番反映

### 前半6件（本番リリース済み）
生活機能チェック緊急修正3件 / 担当者会議 本番整備 / 勉強会・会議議事録(staff_meetings) / マインドマップ(markmap) / 録音の中断対策(Wake Lock, static/rec_keepalive.js) / タスク編集・削除(管理者・作成者・担当者の3者可, commit fca8369)

### 勤怠フルセット（本番反映済み。commit 7b08771→b4845d6）
- タイムカードUX (timecard.html, marker timecard-ux-v1): 休憩/退勤に確認ダイアログ、職員一覧30秒自動更新、手動リロード
- 休暇の記録 (db/staff_leave.sql, staff_leave_days, marker staff-leave-api-v1): 7区分(有給/振替休/忌休/欠勤/休み/半休/時間休)、振替休は振替元日付(substitute_for)保持。API群 /admin/timecard/leave/{types,list,set,delete}。本番Supabase DDL投入済み
- 休暇の管理UI (admin_timecard_report.html, marker staff-leave-ui-v1): 打刻編集モーダルに休暇区分プルダウン＋振替元日付
- 事業所設定 (admin_settings key=timecard_config, marker timecard-config-v1/role_splits): 勤務区切時刻(work_split_times)・サービス提供時間(service_times)・枠時間(half/full_slot_hours)・兼務マップ(role_splits)。API /admin/timecard/config
- 設定UI (marker timecard-config-ui-v1): 「勤務設定」ボタン→モーダル。区切時刻/提供時間可変リスト/枠時間/兼務(職員×役職×割合)入れ子編集
- 参考様式4 実績出力 (templates/youshiki_kinmu.xlsx同梱, openpyxl, marker youshiki-export-v1): /admin/timecard/youshiki?year=&month= が.xlsx返す。介護保険課の監査用(社労士向けタイムカードCSV出力とは別物)
- 出力ボタン (marker youshiki-btn-v1): 月次レポートに「様式で出力」
- 実績表記 (marker youshiki-jisseki-v1): タイトル「勤務予定」→「勤務実績」、月表記を出力年月に自動更新(令和=西暦-2018)
- フォント色統一 (marker youshiki-color-v1): 数値=黒(FF000000)、休暇文字=赤(FFFF0000)。テンプレの元赤字も打ち消し
- 勤怠集計PDF (marker timecard-pdf-v1): /admin/timecard/report_pdf をpdfkit/wkhtmltopdfでサーバー生成。window.print()が印刷に飛んでPDF保存できない問題を解消。列幅固定(table-layout:fixed, marker timecard-pdf-colfix-v1)で全職員の列位置を揃える

### 様式4 転記ロジック（確定・検証済み）
各職員×各日: (1)休暇あれば様式表記文字(打刻より優先) (2)打刻あれば勤務区切時刻(12:30)で午前/午後に二分し、各側の在席時間(休憩差し引かず in→out区間のみ)を上限4で数える(4以上→4、満たなければ0.5刻み実時間) (3)平日(月〜金)→半日型シート、日曜→1日型シート(枠8)、土曜空欄 (4)月1〜28日をD〜AE列。氏名は全角/半角スペース除去で照合。半日型: 午前=1単位目/午後=2単位目。兼務(同名が役職違いで複数行)はrole_splitsのratioで各役職行に配分。管理者行(単位見出し前のR10)への午前午後配分は今後微調整。御社: 平日半日・日曜1日固定、正社員8:30-17:30、区切12:30

### 設定モーダルのボトムナビ対応（教訓の再確認）
ボトムナビ実測134px。--tc-nav-hにJS実測値をセット→モーダルmax-height:calc(100vh - var(--tc-nav-h) - 32px)で画面内に収め内部スクロール(marker timecard-config-navfix2-v1)。固定値直書きは端末差で破綻するため必ず実測方式。

### 次回の発展タスク（勤怠）
1. 打刻フロー組込(退勤時に半休/時間休選択、翌出勤日に前休み入力※先に出勤ボタン)
2. 次月勤務予定入力＋LINE連携(毎月中旬にLINEで休み予定フォーム)
3. 兼務の管理者行への午前午後配分微調整
4. タイムカードCSV/Excel出力(社労士向け給与計算、様式とは別物)

---

## 【開発ログ】2026-07-10 参考様式4 D8起点日付ズレ修正

### 症状
/admin/timecard/youshiki の出力(kinmu_YYYYMM.xlsx)で、日付欄・曜日欄が出力対象月と無関係に固定表示(半日型=令和7年12月始まり/1日型=令和8年12月始まり)。毎月ズレる。加えて1日型シートのタイトルが M2「（令和X年Y月分）」/ Q2「実績」に分裂し、半日型「勤務実績（令和X年Y月分）」と不統一。

### 原因
テンプレ(templates/youshiki_kinmu.xlsx)は D8 に固定日付、E8以降が =D8+1 連鎖、D9以降が =TEXT(D8,"aaa") で曜日自動計算という構造。しかし youshiki-jisseki-v1 のタイトル置換ループは D8 を一切書き換えていなかったため、テンプレ固定の12月始まりがそのまま出力されていた。1日型タイトルは元テンプレでセルが割れており、正規表現 （令和\d+年\d+月分） が連続1セルにしか当たらず M2 が置換されなかった。

### 修正 (marker youshiki-d8-fix-v1, commit a8c7fd6→本番 87a49d6)
タイトル置換ループ直後・転記ループ直前に、全シート一括で以下を実施:
- _ys_d1 = _ys_date(year, month, 1) を wb.sheetnames 全シートの D8 に代入 → E8以降(=D8+1)/D9以降(=TEXT)が日付・曜日とも毎月自動追従。半日型・1日型どちらも対応。手動修正不要化。
- 1日型の分裂タイトルを明示修正: Q2 が「実績」を含む場合 M2="勤務実績"+_ys_month_str, Q2=None で半日型と統一。

### 検証
2026-07出力で両シート D8=2026-07-01, 日付 1(水)〜28(火), 日曜=5/12/19/26 が転記ロジック(_ys_date().weekday()==6)と一致。month=8で 8/1(土)始まりに自動追従することも確認しキャッシュ切り分け済み(ブラウザキャッシュで旧xlsxを掴む事象あり→URLに nocache パラメータ or スーパーリロードで回避)。

### 教訓
openpyxl は数式セルのキャッシュ値を再計算しないが、起点セル(D8)を書き換えれば Excel/LibreOffice側で開いた際に =D8+1 / =TEXT() 連鎖が正しく再計算される。日付シートは「起点1セルをコードで上書き」設計にすればテンプレ固定値によるズレを根絶できる。テンプレ側のD8固定値は直さない(対象月変更で再発するため)。DEV確認時はブラウザキャッシュに注意。

---

## 【開発ログ】2026-07-10 参考様式4修正・タスカル音声・打刻フロー・休憩カウントダウン・リッチメニュー自動復旧

### 参考様式4 D8起点日付ズレ修正 (youshiki-d8-fix-v1, 本番反映済み)
症状: /admin/timecard/youshiki 出力で日付欄・曜日欄が対象月と無関係に固定(半日型=令和7年12月/1日型=令和8年12月始まり)。1日型タイトルがM2/Q2に分裂。
原因: タイトル置換ループがD8(起点日付)を書き換えていなかった。テンプレ固定の12月がそのまま出力。
修正: タイトル置換直後に全シートのD8を_ys_date(year,month,1)で上書き→E8以降(=D8+1)/D9以降(=TEXT)が日付・曜日とも毎月自動追従。1日型タイトルも明示統一。
教訓: openpyxlは数式セルを再計算しないが、起点セル(D8)を書けばExcel/LibreOffice側で=D8+1連鎖が正しく再計算される。テンプレ固定値は直さない(月変更で再発)。

### タスカル音声のネズミ声化 (本番反映済み)
- soundTasukaru を「タスクッ！」/Kyoko/rate1.6/pitch2.0 のネズミ声に (mouse→squash→kyoko と調整)
- 真因バグ修正: 試聴ボタンでポロロン(電子音)が鳴る問題。top.html の playSound(type) に旧「tasukaru=440/554/659Hz」電子音が残存し、各preview-btnに直addEventListenerされてbase.htmlのsoundTasukaruより優先発火していた。oscillator.startのスタックトレースで特定 (top-tasukaru-voice-v1)。
- 連打で声が低くなる問題対策: ss.speaking/pending中は無視+cancel後150ms待ち (antichoke2)
- 教訓: 音の発生源特定は AudioContext.createOscillator の start をフックして console.trace が最速。base.htmlだけ見て回り道した。

### 打刻フロー組込 (timecard-leave-self-api-v1, leave-modals-*, in-modal-*, 本番反映済み)
職員本人がタブレットから休暇を登録する導線。管理者API(/admin/timecard/leave/set)とは別レイヤーで、打刻と同じdevice token認証の公開API /timecard/leave/self (直近30日制限・在籍照合) と /timecard/leave/self_check (未打刻日検出+today_leaveフラグ) を新設。
- 退勤時: 「通常退勤/半休で退勤/時間休で退勤」3択モーダル。半休/時間休なら退勤打刻+当日休暇登録。
- 出勤時: 「通常出勤/午前半休/午前の時間休」モーダル。出勤打刻は通常記録し半休/時間休なら当日登録。
- 休み明け: 出勤打刻後に未打刻日があれば完全必須モーダル(全日一括適用+個別指定, 振替休は振替元日付入力必須)。
- 退勤スキップ(案A): 当日すでに休暇登録済み(午前半休で出勤等)なら退勤モーダルを出さず通常退勤。
- Chrome連携でE2E全項目テスト済み(出勤/午前半休/案A/対照/振替休substitute_for保存)。

### 休憩カウントダウン (timecard-break-countdown-*, break-list-countdown-v1, top-break-countdown-v1, 本番反映済み)
DDL: timecard_records に planned_break_min 列追加。
- 休憩開始ボタン→10〜90分(5分刻み)選択モーダル→planned_break_min付きで打刻。
- 打刻画面の休憩中表示に「開始時刻+残り時間」カウントダウン(超過はマイナス赤)。
- 職員一覧カードにも休憩残りを表示(一覧に戻ると消える問題を解消)。
- 本人TOPに休憩残りバナー(/timecard/my_break APIをJSで叩く、ログイン名=staff_name前提)。
- _tc_active_break(punches): 最後のbreak_startがbreak_end前なら{started_at,planned_min}を返す。bootstrap/punch/my_breakで共用。
- Chrome連携でテスト済み(選択モーダル/カウントダウン毎秒減少/超過ロジック/一覧表示)。

### 職員リッチメニュー消失の復旧+自動復旧 (richmenu-autocheck-v1, 本番反映済み)
症状: TASUKARUアカウント(@599oxawd)の職員用リッチメニュー(利用開始/パスワード再発行/アプリ改善依頼)が消えた。LINE Official Account ManagerのGUIリストには元々出ない(Messaging API設定のため)。API上もデフォルト0件=完全消失。
- コードにリッチメニュー操作は元々無い→LINE側で消えた(手動操作等)。今日の作業とは無関係。
- 手動復旧スクリプト scripts/restore_richmenu.py を常備。LINE_CHANNEL_ACCESS_TOKENを環境変数で渡し(画面非表示)、既存全削除→作成→画像アップロード→デフォルト設定。冪等。certifi対応(Mac Python3.14のSSL証明書問題回避)。
- 画像を static/richmenu/staff_menu.png としてリポジトリに配置。
- 自動復旧: webhook(line_webhook_tasukaru)入口で _ensure_richmenu() を呼ぶ。admin_settings(cocokaraplus-5526, key=richmenu_last_check)で24hガード。デフォルトメニューが消えていたら static画像で自動再作成→デフォルト設定。try/exceptでwebhook本体に影響させない。
- リッチメニュー定義: 2500x843横3分割。左=uri(liff 2010588249-eVxq4tL5), 中=message"パスワード", 右=message"アプリ改善依頼"。
- 復旧確認済み(LINEアプリで表示OK)。今後消えても職員がLINEを使えば1日以内に自動復旧、または restore_richmenu.py で即復旧可能。

### 次回の発展タスク(勤怠、継続)
1. 打刻フローの実運用フィードバック反映
2. 兼務の管理者行への午前午後配分微調整(様式4)
3. タイムカードCSV/Excel出力(社労士向け給与計算、様式とは別物)
4. 担当者会議の残タスク(フォントサイズ選択/会議記録削除/PROゲート)

---

## 【開発ログ】2026-07-12 請求額計算モジュール（レク費精算）新規実装 <!-- session-2026-07-12-rec-expense -->

おでかけ（レクリエーション）の費用を利用者ごとに割り勘・精算するモジュール。完全独立。
フラグ `admin_settings.rec_expense_enabled = 'true'` の施設のみ表示（cocokaraplus-5526 / DEMO001 に seed 済み）。
DEV・本番とも反映済み。

### 画面 / ルート
- `GET /rec_expense` → `templates/rec_expense.html`（一覧 → 1画面編集、請求額はライブ更新）
- ナビは `can_rec_expense`（context_processor）で制御。フラグ無効の施設は `/top` へリダイレクト。

### API（すべて `_rec_guard()` でフラグ判定、403）
| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/rec/events?month=YYYY-MM` | 一覧（請求合計・差額つき） |
| POST | `/api/rec/events` | 新規作成（空の場所ブロックを1つ自動生成） |
| GET/PUT/DELETE | `/api/rec/event/<id>` | 取得 / 全置換保存 / 論理削除 |
| GET | `/api/rec/participants?date=` | **その日のバイタルにいる利用者**（`api_renraku_list` と同ロジック） |
| GET | `/api/rec/staff?date=` | **その日のタイムカードに打刻のある職員**（出勤スタッフ） |
| GET | `/api/rec/patients` | 利用者一覧（参加者の手動追加用。検索はクライアント側） |
| POST | `/api/rec/calc` | 保存前プレビュー計算（DBに触らない） |
| GET/POST | `/api/rec/cars`, PUT/DELETE `/api/rec/car/<id>` | 車マスタCRUD |
| GET | `/api/rec/config` | 施設住所（出発地の既定値）/ maps_enabled |
| POST | `/api/rec/distance` | Google Routes API で走行距離を自動取得 |

### DDL（`db/rec_outing_all.sql` が本番投入用の統合版・冪等）
- `rec_events` … facility_code, event_date, **title**, staff_names(jsonb), participants(jsonb), **cars(jsonb)**, memo, is_deleted
  - `cars` = `[{car_id, name, fuel_km_per_l, distance_km, fuel_price_per_l, origin, round_trip, waypoints}]`
- `rec_places` … event_id, place_name, sort_order
- `rec_expenses` … **place_id は nullable**（車費用は場所に紐づかない）, event_id, kind, label, amount,
  **details(jsonb)**, excluded(jsonb), **target_id(uuid)**, target_name, is_car, car_meta(jsonb), sort_order
  - `details` = `[{name, unit_price, qty}]`（明細。あれば amount = Σ(単価×個数) をサーバが上書き）
  - `car_meta` = `{car_index, type: gas|parking|highway}`
- `rec_cars` … 車マスタ（facility_code, name, fuel_km_per_l, is_active）
- 追補DDL: `db/rec_outing.sql`(v3.1) / `db/rec_outing_cars.sql`(v4) / `db/rec_outing_details.sql`(v5)

### 計算仕様（`_rec_calc`）
- 費用3タイプ: `split`(割り勘) / `flat`(一律加算) / `individual`(個別、`target_id`で対象者指定)
- 割り勘・一律は参加者全員が既定。項目ごとに `excluded` で除外指定。
- **丸めは「費用ごと」に10円単位で切り上げ**（`REC_ROUND_UNIT = 10`）。
  - 内訳の各行(`share_billed`)の合計 = その人の請求額。**繰上げ行は無い**。
  - 例: 1,000円を3人 → 各340円（実費1,000 / 請求1,020 / 差額20円）
  - 単位を変えるなら `REC_ROUND_UNIT` の1箇所のみ。
- 差額（＝集めすぎ）= 請求合計 − 実費合計。画面では「差額徴収額（繰上げ分）」と表示。
- `calc.per_person[].breakdown` に「誰に・どの場所の・どの項目を・いくら」を返す（請求内訳マトリクスの元データ）。

### 車・距離
- 複数台対応。車1台につき ガソリン/駐車/高速 の費用行がぶら下がる（＝台数分）。
- **ガソリン代はサーバが常に再計算**（距離 ÷ 燃費 × 単価）。手入力は採用しない。
  - `_rec_gas_amount` は **Decimal + ROUND_HALF_UP**。float だと `23.0/10*175 = 402.49999999999994` で402円になり、電卓と1円ずれた（gasround-v1で修正、正しくは403円）。
- 距離は **Google Routes API**（`directions/v2:computeRoutes`）。Directions APIはレガシーのため不使用。
  - キーは Secret Manager `GOOGLE_MAPS_API_KEY` → Cloud Run 環境変数。フロントには出さない。標準ライブラリ urllib で叩く（requestsは requirements.txt に無いため）。
  - 出発地の既定値は `facilities.facility_address`。立ち寄り先は1行1か所で入力（空なら場所ブロックの場所名を使う）。往復/片道の切替あり。
  - 距離0のままだとガソリン代が黙って0円になるため、警告を出す（gaswarn-v1）。

### 自動取込
- **参加者** … その日の `vitals`（`measured_date`）にいる利用者。`patient_profiles.id` で突合。
- **出勤スタッフ** … その日の `timecard_records` に打刻がある `staff_name`（JST日境界＝UTC前日15:00〜当日15:00）。出勤/退勤の別は問わない。
- どちらも **「追加」ではなく「置換」**。日付を変えると自動で読み込み直す（新規は確認なし、保存済みは confirm）。参加者から外れた人は費用の `excluded` / `target_id` からも掃除する。

### UI
- 請求額は **利用者 × 費用項目のマトリクス**。横スクロール、利用者名を左固定・請求合計を右固定。
  - ハマり: **CSS Grid の子は既定 `min-width:auto`** のため中の表が広いと列ごと膨らみ、`overflow-x` が効かず右固定列が画面外に見切れた。`.rec-edit-grid > * { min-width:0 }` で解決。
  - ハマり: TASUKARU は `--page-max-width`(既定480px)の固定幅カラム。**ビューポート幅のメディアクエリは効かない**ので `@container` を使う。
- 保存すると入力欄（おでかけの情報 / 場所ごとの費用 / 車）が**アコーディオンで畳まれる**。見出しに要約を表示。
- `alert()` は拡張機能の操作をブロックし体験も悪いので、画面内トーストに置換（削除確認の `confirm` のみ残す）。

### パッチ（適用順。すべて冪等・`app.py.bak_*` 自動バックアップ）
1. `patch_rec_expense_api_v1.py` … コアAPI
2. `patch_rec_expense_ui_v1.py` … ページルート + base.html ナビ（movableHrefs 3箇所含む）
3. `patch_rec_expense_car_v2.py` … 車（v1ブロックをv2に丸ごと置換）
4. `patch_rec_maps_v3.py` … 距離自動取得
5. `patch_rec_waypoints_v31.py` … 経由地を明示保存
6. `patch_rec_gas_round_v1.py` … ガソリン代の丸め（Decimal）
7. `patch_rec_details_v4.py` … 明細 + 請求内訳
8. `patch_rec_savecalc_place_v1.py` … 保存直後の内訳に場所名
9. `patch_rec_gas_warn_v1.py` … 距離未入力の警告
10. `patch_rec_staff_timecard_v1.py` … 出勤スタッフ自動取込
11. `patch_rec_round_item_v5.py` … 丸めを費用ごと10円単位に
12. `patch_rec_rename_v1.py` … 表示名「レク費精算」→「請求額計算」

### 次回の発展タスク
1. **レシート読み込み**（撮影 → OCR → 明細（品名・単価・個数）に自動入力）
2. 個別/一律も10円切り上げしている点の運用確認（実費ぴったり請求したい場合は割り勘のみ丸める設計に変更可）
3. 立替者（どの職員が払ったか）の記録と、職員ごとの立替精算
4. 請求書・集金リストのPDF/Excel出力

---

## 【開発ログ】2026-07-13 送迎モジュール新規実装／利用終了の扱い／契約書・重説の整備 <!-- session-2026-07-13-soge -->

### 1. 送迎モジュール（新規）

住所から週次の送迎表を自動生成し、当日は打刻し、月末に運行記録表を出すところまで。

#### 画面

| 画面 | パス | できること |
|---|---|---|
| 車両マスタ | 管理者MENU | 車名・ナンバー・利用者席数・車いす席数・車いす最大台数 |
| 送迎設定 | 管理者MENU | 単位数(1/2)・目標時間・上限時間・乗降時間・車いす乗降時間 |
| 配車 | `/soge` | 曜日タブ・自動生成・付箋ドラッグ（順番／車間移動）・車の増減・利用者の臨時追加・保存＝翌週へ学習 |
| 運行 | `/soge/run` | 車両タブ・出発/到着打刻（2度押し防止）・時刻修正・休み・帰着・臨時便 |
| 運行記録表 | `/soge/print?month=YYYY-MM` | 車両ごと月間・横スクロール・立寄順＋矢印・備考入力・A4横印刷/PDF |

#### DDL（すべて投入済み: DEV / 本番）

- `db/vehicles.sql` — rec_cars に plate_no / capacity / note
- `db/soge_settings.sql` — soge_settings（unit_count, trips jsonb, mid_dropoff_first）
- `db/soge_geocode.sql` — soge_geocode。**住所は保存せず、ハッシュ + 座標のみ**
- `db/soge_seats.sql` — rec_cars.soge_seats / wheelchair_seats / wheelchair_max、patient_profiles.is_wheelchair
- `db/soge_routes.sql` — soge_routes（曜日×便の確定順＝学習の実体）／ soge_days（その日の1便1台）／ soge_stops（打刻の単位）
- `db/soge_time.sql` — soge_settings に target/max/stop/stop_wc minutes、soge_route_time（所要時間キャッシュ）

#### 自動生成の考え方（marker順）

1. `soge-geocode-v1` — 利用者住所 → 座標。Geocoding API。**住所そのものは DB に残さない**
2. `soge-week-v1` — 方位角順に並べ、席数を守って車へ配る
3. `soge-peak-seats-v1` — 中間便は「1単位目を降ろしてから2単位目を迎える」ので、同時乗車は `max(送り人数, 迎え人数)`。合計ではない
4. `soge-time-v1` — 本当の制約は席数でなく「事業所に戻るまでの時間」。Routes API で実測し、目標超えなら台数を増やす
5. `soge-balance-v1` — 台数を増やしたら**席数の比で配分し直す**。貪欲に詰めると先頭の車が満席のままで時間が減らない。端数は最大剰余方式
6. `soge-routeopt-v1` — 立ち寄り順を**最近傍＋2-opt**で最短化（Google は呼ばない）。送り→迎えの順序は維持
7. `soge-trip-target-v1` — 便の仕事量で目標を自動調整。送りだけ/迎えだけ=1本、混在（中間便）=2本 → **中間便は 60分/上限80分**
8. `soge-refine-v1` — 時間の長い車から空いている車へ1人ずつ移してならす。試行錯誤は「直線1kmあたり何分」の概算で行い、**決まってから1回だけ実測**（API 呼び出しを増やさない）

#### 本番実測（月曜・対象23名・キャラバン8席/タント3席/セレナ7席）

| 便 | 目標 | 実測見込み |
|---|---|---|
| 迎え便 | 30/40分 | 37 / 16 / 40分 |
| 中間便 | **60/80分** | 55 / 25 / 58分 |
| 送り便 | 30/40分 | 33 / 25 / 43分 |

現場実測「迎え30〜40分」「中間便は3台で60分」と一致。乗降時間は現場の実態に合わせ **1分/人**（車いす5分）。

#### 学習

`/soge` で保存すると `soge_routes` に「曜日×便×車の確定順」が入り、翌週の初期値になる。当日データ（`soge_days` / `soge_stops`）は**運行画面を最初に開いたときに1回だけ**作られ、以後は週次表を直しても当日には影響しない（走り出したあとに表が変わると事故になるため）。

#### 臨時便（`soge-extra-v1`）

早退・遅刻・通院など。`trip_key = extra1, extra2…`、`vehicle_no = 91, 92…` で既存の一意制約と衝突させない。**臨時便に入れた人は同じ日の他の便から自動で外す**（二重送迎の防止）。ただし**打刻済みの立ち寄りは消さない**。

#### ハマったところ

- **ドラッグが固まる** — つまんでいる `⠿` が付箋の中にあるのに、ドラッグ中に付箋を `display:none` にしていた。要素が消えた瞬間にポインター追跡が切れ `pointerup` が届かない。→ 元の付箋は薄く残し、監視を `window` に付ける
- **iOSで見出しだけ巨大化** — 表が画面より広いと Safari の text autosizing が働く。→ `text-size-adjust: 100%`
- **記録表を別タブで開くとログインが切れる** — ホーム画面起動のPWAでは `target="_blank"` が外部ブラウザになり Cookie が渡らない。→ 同じタブで開く

### 2. 利用終了の扱い（`patient-active-v1`）

`discontinued_date`（利用終了日）と `is_discontinued`（中止フラグ）の2列があったが、**`is_discontinued` はどの画面からも設定できず実質いつも false**、かつ送迎は `is_discontinued` しか見ていなかった。そのため終了日を入れた人が送迎表に出続けていた。

- `patient_active_on(p, date)` を新設し、送迎の対象者・座標変換・臨時追加候補・請求額計算の参加者候補を全部そこに通す
- **終了日“当日”までは出る**（最終利用日まで送迎するため）、翌日から出ない
- 利用者基本情報の「利用終了日」の横に **「利用中止にする」/「利用を再開する」** ボタン
- 過去の記録・検索には手を触れていない

### 3. 「第N週のみ」を実際に効かせる（`visit-nth-apply-v1`）

`nth_per_day` は保存されるだけで**どこも見ていなかった**。第2火曜だけの人が毎週火曜に出ていた。

- 送迎の当日データ生成で、その日に当たらない人の立ち寄りを作らない
- バイタルの「今日来る人」で、当たらない曜日を `NONE` として下流へ渡す（画面側は無改修）
- 予定日判定 `_visit_is_planned_weekday` / 月別予定にも適用
- **`/soge` の配車画面（曜日テンプレート）には残す** — 日付を持たないので、そこで消すと第2火曜の並び順を編集できなくなる。付箋の「第N」バッジで見分ける

### 4. 契約書・重要事項説明書（`keiyaku-fix-v1` / `keiyaku-sign-v1` / `keiyaku-duplex-v1`）

- **押印廃止** — ㊞ を全削除、「署名押印」→「署名」
- **単独印刷** — ボタンを「重説 / 契約書 / 一式」の3つに。サーバは元から `doc=juyo|keiyaku|both` に対応していて、画面が both 固定だっただけ
- **両面印刷対応** — 一式PDFで、重説だけ先にPDF化してページ数を数え、奇数なら白紙を1枚挟む。`page-break-before: right` は wkhtmltopdf が無視することがあるため、実測して挟む。ページ数は `pdfminer.six`（既存依存）
- **記入枠を拡大** — 署名欄はラベルを文字幅ぶんに詰め、書く欄を最大化。ページ幅いっぱいの下線をやめ、書く欄の下だけに線。「様」は氏名欄の右端にそろえる。緊急時連絡先は案内文字を細い列に切り出し、残りを全部記入枠に
- **苦情担当** — 電話番号が担当者の間に挟まっていたので表にし、「苦情受付電話番号」を独立行に。受付と対応を1行に統合

### セキュリティ・プライバシー

- `soge_geocode` は**住所を保存しない**。住所ハッシュと座標のみ。住所は Google へサーバ側から送るだけでログにも残さない
- 本番データの書き換えは、必ず事前に SQL を提示して承認を得てから実行する
- **本番では書き込みを伴うテストを行わない**（打刻などは DEV で。本番は読み取り確認のみ）

### 次タスク

1. 送迎の実運用開始 → 出てきた不具合の修正
2. ~~運行記録表に住所を載せるかの判断~~ → **載せない**と決定（2026-07-13 追記の開発ログ参照）
3. 走行距離(odo)のアプリ入力（現状は記録表の手書き欄）
4. レシート読み込み（OCR → 請求額計算の明細に自動入力）

---

## 【開発ログ】2026-07-13(2) 運行記録表の氏名縦積み修正／住所の見せ方を確定 <!-- session-2026-07-13-soge-print -->

送迎の実運用で最初に出た不具合。**本番反映済み**。

### 1. 運行記録表で氏名が1文字ずつ縦に折り返る（`soge-print-noaddr-v1`）

- 原因: 印刷CSSが `.sp-tbl { width:100%; white-space:normal }`。紙は横に流せないので折り返す設定にしていたが、
  立ち寄り列が押しつぶされ、**日本語の氏名がセル幅で1文字ずつ改行**されていた。
- 修正: **折り返して良いのは「人と人の間」だけ**。`.sp-s`・`.sp-s .nm` は画面でも紙でも `nowrap` を維持する。
- 教訓: 「表全体を `white-space: normal` にする」は日本語では縦積みを招く。折り返しの単位を要素で区切ってから normal にする。

### 2. 住所は運行記録表に載せない（判断）

一度は記録表にも住所を出し、幅スライダー（`soge-print-adw-v1`）まで付けたが、
**紙は運転手が見るものではない**ので不要と判断し、まるごと撤去（`soge-print-noaddr-v1`）。
紙に住所が出ないぶん、個人情報の扱いも軽くなる。記録表は氏名＋到着時刻のみ・1段4人に戻した。

### 3. 運行画面の住所が「…」で切れて読めない（`soge-run-addr2-v1`）

- サーバ: `_soge_addr_short()` で **都道府県を落として市から**（同一県内の利用者しかいないので情報は落ちない）。
- 画面: `.sr-addr` を1行 `nowrap`+ellipsis → **最大2行のクランプ**（`-webkit-line-clamp:2`）。
  3行目からは …。行が伸びないよう住所だけ 0.70→0.66rem・行間1.2。
- 住所を出すのは **運行画面（/soge/run）だけ**。

### DEV確認用のダミーデータ

- `db/soge_dummy_dev.sql` … 2026-07の運行・立ち寄り（架空の氏名12名）
- `db/soge_dummy_dev_addr.sql` … **住所付きのダミー利用者**（新規）。
  既存ダミーの `patient_id` は `md5('dummy-'||氏名)::uuid` なので、同じUUIDで `patient_profiles` を作れば住所が紐づく。
  `patient_number` が `DUMMY-%` なので一括削除できる。**DEV専用。本番では実行しない。**
- 見終わったら消すこと（削除SQLは各ファイルの冒頭コメント）。

### パッチ（適用順）

1. `patch_soge_print_addr_v1.py` … 縦積み修正＋記録表に住所（※2で撤去）
2. `patch_soge_print_adw_v1.py` … 住所幅つまみ（※2で撤去）
3. `patch_soge_print_noaddr_v1.py` … 記録表から住所とつまみを撤去（**縦積み対策は維持**）
4. `patch_soge_run_addr2_v1.py` … 運行画面の住所を市から・2行クランプ

---

## 【開発ログ】2026-07-13(3) 走行距離（メーター）のアプリ入力 <!-- session-2026-07-13-soge-odo -->

**本番反映済み。ただし既定はオフ**（`odo_enabled=false`）なので、本番の見た目は今までどおり。

### 施設ごとのトグル（`soge-odo-v1`）

走行距離を記録するかは事業所で分かれるので、機能ごと オン/オフ できるようにした。

- 設定: 管理者MENU >「送迎設定」>「走行距離（メーター）を記録する」（`soge_settings.odo_enabled`、既定 false）
- 入力: 運行画面（`/soge/run`）の **便ごと**に「出発㎞ / 帰着㎞」。走行㎞は差で表示。
  **次の便の出発㎞には前の便の帰着㎞が薄字（placeholder）で出る**（打ち直しを減らす）
- 記録表: `/soge/print` に「出発㎞ / 帰着㎞ / 走行㎞」の列。ここでも直せる
- 保存は既存の `PUT /api/soge/run/day` に `odo_start` / `odo_end` を足しただけ（桁ミス防止に範囲チェック）
- 走行距離は列に持たず、`odo_end - odo_start` をその都度計算する

### DDL（`db/soge_odo.sql`。DEV / 本番とも投入済み）

```sql
alter table soge_settings add column if not exists odo_enabled boolean not null default false;
alter table soge_days add column if not exists odo_start integer;
alter table soge_days add column if not exists odo_end integer;
```

（`soge_days.odo_start/odo_end` は元のDDLに含まれていたが、コードからは一切使っていなかった）

### 送迎設定の保存を alert → トーストに（`soge-settings-toast-v1`）

`saveSogeSettings()` が `alert()` を使っており、**Chrome拡張の自動操作がそこで止まって動作確認ができなかった**。
admin.html にトーストが無かったので、この画面用に小さいものを1つ足して置換。
admin.html には他にも alert が残っている（今回は影響範囲を広げないため触っていない）。

### 次タスク

1. ~~レシート読み込み~~ → 実装済み（下記）
2. 送迎の実運用フィードバック
3. admin.html に残る alert の掃除（自動確認が止まるため、見つけ次第トーストへ）

---

## 【開発ログ】2026-07-13(4) レシート読み取り（OCR）→ 請求額計算の明細に自動入力 <!-- session-2026-07-13-rec-ocr -->

### 実装（`rec-receipt-ocr-v1`）

- **OCR基盤は新設しない**。出納帳の領収書OCR（`/api/ledger/ocr_receipt`）と同じ
  `utils.get_generative_model()`（google-genai / Gemini）を使う。欲しいものだけが違う
  （あちらは 合計・税・支払方法、こちらは **品名・単価・個数の明細**）。
- API: `POST /api/rec/ocr`（`_rec_guard` でフラグ施設のみ）
  → `{vendor, date, total, items:[{name, unit_price, qty}], image_url}`
  - プロンプトで **小計 / 合計 / 消費税 / お預り / お釣り / 値引き / ポイントは items に入れさせない**
  - 「品名 ×3 900」のように行合計しか無い行は 単価 = 行合計 ÷ 個数
- UI: 費用行ごとに「レシート読取」→ スマホならカメラが開く → 明細に追加。
  **項目名が空なら店名を入れる**。金額は明細の合計をサーバが再計算（既存 rec-expense-details-v4）。
- 画像: Supabase Storage に保存し `rec_expenses.receipt_url` に URL。「レシートを見る」は同じタブで開く（PWA対策）。
  **出納帳の `receipts` テーブルには入れない**（あちらの「未仕訳の領収書」一覧に混ざるため）。

### DDL（`db/rec_receipt.sql`。DEV / 本番とも投入済み）

```sql
alter table rec_expenses add column if not exists receipt_url text;
```

### 明細行が読めない問題（`rec-detail-row2-v1`）

レシートから入った品名が空に見えた。真因は OCR ではなく **CSS**。
`.rec-dt-row` が1行の flex で、単価(74px)+個数(74px)+小計(64px)+×ボタン が固定幅のため、
480px 幅のカラムでは品名(`flex:1; min-width:0`)が**ほぼ0幅まで潰れて**いた（文字は入っていた）。
→ 品名を上段にフル幅、単価×個数を下段の2段組みに。

### 検証

DEVで、ページ内の canvas にレシートを描いて `/api/rec/ocr` に直接POSTして確認（実物のレシートが手元に無くても検証できる）。
品目4件のみ抽出・単価/個数正しい・小計/税/お預り/お釣りは混ざらない・合計一致・画像URL返却、まで確認済み。

### 教訓

- **「値が入っていない」と「値が見えない」は別**。まず幅を疑う。TASUKARU は 480px 固定カラムなので、
  固定幅の入力欄を横に並べると可変幅の欄が潰れる。
- Cloud Build が「ビルドを実行できませんでした: INTERNAL / 0個のステップ」で落ちることがある。
  **これはGCP側の一時障害**でコードは無関係。空コミットで再トリガーすれば通る。

---

## 【開発ログ】2026-07-13(5) 引き出しメニュー（全画面のアイコン一覧） <!-- session-2026-07-13-drawer -->

ボトムナビの導線が増えすぎたので、**どの画面からも出せるアイコンの引き出し**を作った。
ボトムナビは残したまま（消すと各画面のレイアウトが崩れる。下記「次タスク」参照）。

### 個人設定の土台（`staff-settings-v1`）

これまで個人設定は全部 localStorage で、端末を変えると消えていた。
`staff_settings(facility_code, staff_name, key, value)` を新設（`db/staff_settings.sql`）。
API は `GET/PUT /api/me/setting`。受け付けるキーは `STAFF_SETTING_KEYS` のホワイトリストのみ。

### メニュー定義の一元化（`top-grid-v1`）

`app.py` の `MENU_ITEMS`（href / icon / label / 表示条件）。表示条件は既存の判定
（`inject_can_ledger` / `is_rec_expense_enabled` / `inject_is_dev_user`）をそのまま呼ぶので、
ボトムナビと食い違わない。**ボトムナビ（base.html のハードコード）は今回いじっていない**
（現在地のハイライトが各画面の `{% block nav_xxx %}` に依存していて、作り替えると壊れる範囲が広い）。
新しい導線を足すときは MENU_ITEMS にも1行足すこと。

### 引き出し（`app-drawer-v1` 〜 `app-drawer-width-v1`）

- 取っ手をドラッグ、またはタップで開く。**指に追従**し、離した位置（35%）でスナップ。
  背景はブラー、アイコンは1つずつ立ち上がる。
- **出る向きは4方向**（左 / 右 / 上 / 下）。歯車 > メニューの引き出し で選ぶ（個人設定 `drawer_side`）。
  下から出すときはボトムナビの高さを**JSで実測**して CSS 変数 `--dw-nav-h` に入れる（固定値は端末差で破綻する）。
- **自由配置**。4列のマス目で、空きマスに好きに置ける（上詰めにならない）。長押し450msでプルプル → ドラッグ。
  アイコンの上に落とすと入れ替え。配置は個人設定 `top_layout`（JSON）。
- **アイコンの色**を1つずつ変更（パレット12色＋自由色＋既定に戻す）。`top_layout.colors` に保存。
- PCでは**アプリの列幅（`--page-max-width`）の中に収める**（`--dw-gap` で計算）。

### ハマったところ（全部 iOS）

1. **画面端のスワイプで開く → OSの「戻る」が発動**。端の数十pxは OS が先に取り、Web からは奪えない。
   → 端スワイプは**廃止**。取っ手を**端から18px内側**に置き、その上の指の動きだけを
   `touch-action:none` + `preventDefault` で捕まえる。8px では指が OS の帯に入り、当たり外れが出た。
2. **長押しすると URL のプレビューが出てドラッグできない**。アイコンが `<a href>` だったため。
   → **href を持たせない**（`<div role="button">`）。iOS は「リンクではない」と判断してプレビューを出さない。
   ボトムナビの並び替えも同じ手を使っていた。
3. **タップしても画面が開かない**。真因は `spaNav()` が**中身が空の関数**で、実際の遷移は `<a href>` 任せだったこと。
   href を外した瞬間に遷移する人がいなくなった。→ `location.href` で自分で飛ぶ。
4. **長押しと同時にドラッグ開始は無理**。その瞬間 iOS はもう選択ジェスチャーを始めている。
   → iPhone と同じく **長押し＝プルプルに入るだけ**。移動は指を置き直してから。
5. **アイコンを動かすと引き出しごと閉じる**。引き出しの「外向きに払って閉じる」判定が横取りしていた。
   → 編集中／ドラッグ中は閉じる判定を止める。
6. **遷移先が下端までスクロールされる**。引き出しは body 末尾にあり、その中のボタンを押したまま遷移すると
   ブラウザが最後に触った位置を復元しようとする。→ 遷移前に印を付け、次のページで先頭に戻す。
7. **フォルダは廃止**（`app-drawer-simplify-v1`）。中身を重ねて表示するしかなく、下のマス目が隠れて
   出し入れが直感に反した。作ってしまったフォルダは読み込み時にほどいてアイコンに戻す。

### DDL（`db/staff_settings.sql`）

```sql
create table if not exists staff_settings (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null, staff_name text not null,
  key text not null, value text,
  updated_at timestamptz not null default now()
);
create unique index if not exists uq_staff_settings on staff_settings (facility_code, staff_name, key);
```

### 追記（同日）: 下記「ボトムナビを隠す」は実装済み。次タスク1は完了。

### 次タスク

1. **ボトムナビを隠せるようにする**（個人設定）。ただし今のボトムナビは
   `base.html` の `padding-bottom: max(74px, safe-area + 50px)` や、各画面の固定要素
   （保存バー・FAB・`--tc-nav-h` の実測モーダル）、`manual.html` / `patient_profile.html` /
   `vitals.html` の `padding-bottom` の前提になっている。**消すとそれらが崩れる**ので、
   「ナビの高さを見ている箇所を変数（`--nav-h`）に置き換える」→「隠す設定を個人単位で足す」の順で進める。
2. 管理者が施設共通の既定レイアウトを作る（`admin_settings.top_layout`）。
3. `movableHrefs`（ボトムナビ並び替えのホワイトリスト）が3箇所コピペのまま。MENU_ITEMS に寄せたい。

---

## 【開発ログ】2026-07-13(6) ボトムナビを隠せるように／引き出しの仕上げ <!-- session-2026-07-13-navhide -->

### ボトムナビを隠す（`nav-hide-v1` 〜 `v4`）

歯車 >「下のメニューバー」>「メニューバーを隠す」。個人設定（`staff_settings.nav_hidden`）。
隠すと引き出し（端の取っ手）が唯一の導線になる。

**設計の核心: ナビの高さを共通変数 `--nav-h` に寄せた**

これまでナビの高さは各画面に固定値で直書きされていた（131 / 136 / 140 / 152 / 200 / 220px …）。
そのまま消すと、下部の保存バー・FAB・トースト・余白が「ナビ跡地」に浮く。

- `:root` に `--nav-raw`（JSの実測値）と
  `--nav-h: max(var(--nav-raw), calc(env(safe-area-inset-bottom) + 10px))` を置く。
  **セーフエリアの下限**を CSS 側で噛ませるのがポイント（`env()` は JS の setProperty では書けない）。
- 実測は `measureNav()` の**1か所だけ**。画面別変数（`--rk-nav-h` / `--kk-nav-h` / `--tc-nav-h` /
  `--lc-nav-h` / `--dw-nav-h`）は `:root` で `var(--nav-h)` を既定にした。
- 隠すのは **CSS**（`body.nav-off .bottom-nav { display:none !important }`）。
  既存コードに `nav.style.display = ''` でナビを復活させる箇所が複数ある
  （設定モーダル・ベル・掲示板・タスク）ため、インラインで隠すと戻されてしまう。

**ハマったところ（これが一番の教訓）**

`0` と「未設定」は別物。
各画面の実測関数を「隠しているときは 0px を入れる」に直したら（v2）、
**0px が :root の安全な既定（`--lc-nav-h: var(--nav-h)`）を上書きしてしまい**、
合計バーがホームインジケータ帯に沈んだ。
→ v4 で「隠しているときは **値を入れず removeProperty する**」に修正。
元々あった `if (h > 0)` ガードや `if (!navH) navH = 90;` も同種のバグ源だった
（0 を捨てる → 前の 137px が残る／0 を 90px に読み替える）。

対象: `life_check.html` / `renraku.html` / `admin_keiyaku.html` / `admin_timecard_report.html`。
固定値を変数化した画面: `patient_profile.html` / `vitals.html` / `daily_view.html` /
`ledger.html` / `manual.html` / `base.html`(page-wrapper)。

### 引き出しの仕上げ

- `app-drawer-color-v1` … アイコンの色を1つずつ変更（パレット12色＋自由色＋既定に戻す）。`top_layout.colors`。
- `app-drawer-width-v1` … PC で引き出しがブラウザ幅いっぱいに出ていた。
  アプリは `--page-max-width` の中央カラムなので、`--dw-gap` を計算して**カラムの中に収める**。
- `app-drawer-perside-v1` … **向き（左/右/上/下）ごとに配置と取っ手の位置を別々に記憶**。
  `top_layout` は `{ v:2, sides:{...}, colors:{...} }`。旧形式は今の向きの配置として引き継ぐ。色は向き共通。
- `nav-hide-v3` … 取っ手を**長押しで端に沿って移動**できる（下部の保存バー・LINE送信・合計バーと衝突するため）。
  位置は向きごとに `drawer_pos`（JSON）。
- `app-drawer-2stage-v1` → **`app-drawer-2stage-off-v1` で撤回**。半開き→全開の2段階は使いにくかった。
  取っ手を引く／タップで**一発で全開**に戻した（半開きのCSSは死んだまま残してある）。
- `tc-cfg-width-v1` … 勤怠の勤務設定モーダルが中身に押し広げられて左右にブレていた。
  横は切って縦だけスクロール、Flex の子に `min-width:0`（請求額計算のマトリクスと同じ罠）。

### 個人設定のキー（`staff_settings`）

`nav_hidden`（true/false） / `drawer_side`（left/right/top/bottom） / `drawer_pos`（向きごとのJSON） /
`top_layout`（配置＋色のJSON） / `top_style`（未使用・TOPグリッド時代の名残）

### 次タスク

1. 管理者が施設共通の既定レイアウトを作る（`admin_settings.top_layout`）。
2. `movableHrefs`（ボトムナビ並び替えのホワイトリスト）が3箇所コピペのまま。`MENU_ITEMS` に寄せたい。
3. ナビを隠した状態での全画面チェック（今回は TOP / 記録入力 / バイタル / 出納帳 / 連絡帳 /
   生活機能CHECK / 契約書 / 勤怠 を確認済み）。

### 追記: 引き出しのバッジ（`drawer-badge-v1`、本番反映済み）

ナビを隠すと未読に気づけないので、引き出しのアイコンにもバッジを出す。

- 掲示板 … 既存 `/api/board/unread_count`
- ケース記録 … 既存 `/api/records/unread_count`
- タスク … **新設** `/api/tasks/open_count`（自分あて＋全体タスクの未完了。作成しただけのものは数えない）

**件数は既存のポーリング（`checkUnreadMessages`）に相乗りする**。別々に数えるとナビと引き出しで数字がズレる。
引き出しのグリッドは JS で作り直すので、`window.DW_BADGES` に件数を覚えておき、
`render()` のたびに `applyBadges()` で当て直す（DOMに書いた数字は再描画で消えるため）。
DDL 不要。

---

## 【開発ログ】2026-07-14 契約書・重説を4系統に拡張（予防／生活支援／保険外） <!-- session-2026-07-14-keiyaku-cat -->

地域密着型通所介護しか作れなかった契約書・重説を、要支援・事業対象者向けにも広げた。

### 系統（category）

サービス種別（`keiyaku_facility.service` の各要素）に `category` を持たせた。**DDL不要**（JSON拡張のみ）。
**未設定は `chiiki` とみなす**ので、既存施設は無改修で今までどおり動く。

| category | 文書 | 料金 | 加算 |
|---|---|---|---|
| `chiiki` | 重説＋契約書22条（従来） | 要介護1〜5 × 時間区分 | 介護のマスタ |
| `yobo` | 重説＋契約書22条 | 要支援1/2 の月額包括 | 科学的介護推進40＋処遇改善のみ |
| `seikatsu` | 重説＋契約書22条 | 週1/週2 × 送迎あり/なし | なし |
| `hokengai` | **契約書兼重説の1枚** | 自由な単価行 | なし |

### 文面（`_localize`）

docx を突き合わせたところ、地域密着型・予防・生活支援は **構成が同じで呼び方が違うだけ**
（22条・七章。予防版の第15条(2) も現物は同文のまま）。条文セットを3つ持たず、
レンダリングの最後に呼び方を差し替える。置換は長い語から当てる
（「地域密着型通所介護計画」が「地域密着型通所介護」に食われるため）。
保険外だけは構造が別物なので `render_hokengai()` を別に作った。

### 料金（豊田市の単位数表マスタで検証）

- **予防**（マスタ A6）: 要支援1 = 1,798単位 / 要支援2 = 3,621単位（月額包括）。
  総単位 =（基本単位 ＋ 加算単位）×（1＋処遇改善率）。加算は **科学的介護推進体制40のみ**。
  **運動器機能向上(225)・事業所評価(120)は令和6年3月末で終了しており算定できない**（マスタの有効期間で確認）。
  処遇改善は介護と同じ区分（Ⅱロ = 12.5%）。
  → 要支援1: 2,068単位 = 22,086円（1割 2,209円）／要支援2: 4,119単位 = 43,991円（1割 4,400円）。
  現物の重説（21,392円）は処遇改善が旧率(5.9%)だった頃の数字。1円まで合わせたいときは総額を手入力で上書きできる。
- **生活支援**（マスタ A7）: 週1 送迎あり1,530 / なし1,202、週2 送迎あり3,002 / なし2,359単位。
  総額 = floor(単位 × 単価)、1割 = ceil(総額 × 0.1)、**2割・3割は1割額の2倍・3倍**。
  ※ 総額×0.2 で出すと現物と1円ずれる（週2送迎あり: 6,413 ≠ 6,414）。**現物の作りに合わせる**。
  御社の重説の12マスすべてと一致することを検算済み。週2回程度は要支援2のみ（表に注記）。
- **保険外**: 単価行を `名称|金額` で自由に。既定は 10分以内1,000円／外出等1時間4,000円。

### あわせて直したバグ

`render_print_html` が `if st not in ("han","ichi"): st = "han"` としており、
**画面から追加した種別（t3, t4…）で印刷すると黙って半日型の内容が出ていた**。
種別が service に在れば通すように修正。

### 加算の出し分け（`keiyaku-kasan-cat-v1`）

重説の「各種加算の概要」が介護のマスタをそのまま出しており、
**予防の重説に要介護の加算（個別機能訓練Ⅰ/Ⅱ 等）が載っていた**。系統別に出し分けた（生活支援は非表示）。

### 参照

- [豊田市 総合事業](https://www.city.toyota.aichi.jp/kenkoiryo/korei/1002981/1035884.html)
- 単位数表マスタ（令和8年6月〜）CSV。A6=介護予防通所、A7=生活支援通所。

### 次タスク

1. 予防・生活支援の職員配置／提供サービスの文が系統固有（予防「運動器の機能向上」、生活支援「軽体操や趣味活動等」）。
   現状は種別の「サービス内容」欄で調整。必要なら系統別の既定文を持たせる。
2. 事業所種類・指定番号が facility 直下の単一値。系統ごとに別番号が要るなら service 側へ移す。

---

## 【開発ログ】2026-07-14(2) 記録充足チェック／ボトムナビ廃止 <!-- session-2026-07-14-record-check -->

### 1. 記録充足チェック（`/record_check`）

**やりたかったこと**: その日に来ている利用者について、カテゴリごとの記録が何件入っているかを数字で見て、
「書き忘れ」をその場で見つけて、その場で書き始められるようにする。

- **来ている人の判定** … その日に `vitals` がある利用者。連絡帳・請求額計算と同じ判定（判定を増やすと必ずズレる）。
- **カテゴリ** … `record_categories`（施設ごと）。登録に無いカテゴリの記録は「その他」に寄せる。
- **`records` に patient_id は無い**。`user_name`（テキスト）で突き合わせる。日付は `created_at` の JST 日境界。
- **導線は「ケース記録」の上のタブ 1 本だけ**。ドロワーにもアイコンを置いたが、入口が 2 つになるので削除した。
- 数字クリック → その人のケース記録（`/daily_view?date&user`）。**0 件クリック → `/input?user=`**（利用者を検索欄に入れた状態で開く。
  候補の確定まではやらない。誤爆すると別人の記録になる）。

**表の作り（ここで何度もやり直した）**

- 横が広い → 見出しを**縦書き**（`writing-mode: vertical-rl`）にして列幅を 34px に。番号＋凡例方式は「いちいち確認しないと分からない」と却下。
- 縦書きの帯が隣の列と重なった → `table-layout: fixed` + `colgroup` で列幅を決める。収まらないときは**重ねずに横スクロール**。
- 列ごとに**カテゴリ色の帯**（0件 `08` / 1件以上 `1c` のアルファ）。記録ゼロの人の行は赤下地が勝つ（`!important`）。
- **文字が右に寄る** → 縦書きは行が右→左に流れるので、1行だけの短い名前は帯の右端に貼りつく。
  帯を flex にして水平センター、揃えは上（`align-items: flex-start`）。
- **固定（sticky）が効かない** → `overflow-x:auto` を付けた時点でそこがスクロールの箱になり、`sticky top` の基準が画面ではなくその箱になる。
  箱に高さが無いと貼りつく先が無い。**箱に `max-height` を与えて縦横ともその中でスクロール**させたら上（カテゴリ）も左（氏名）も固定できた。
  `-webkit-overflow-scrolling:touch` は iOS で sticky を壊すので外した。

**ハマり**: 「充足」タブが無反応。`goRecordCheck()` を IIFE の中に書いていて `onclick` から見えなかった。`window.goRecordCheck` に公開して解決。

マーカー: `record-check-v1` / `record-check-tab-v1` / `record-check-link-v1` / `record-check-vhead-v1..v3`
DDL: **不要**（既存テーブルの読み取りのみ）

### 2. ボトムナビ（下のメニューバー）を廃止 <!-- nav-remove-v1 -->

引き出し（ドロワー）に一本化。`<nav class="bottom-nav">` と、その設定（メニュータップ時の動作／メニュー並び順／
バーを隠すトグル／ナビカラー）を削除した。

- **ログアウトはバーの中にしか無かった** → ユーザー設定（歯車）の中へ移設。ドロワーは `MENU_ITEMS` から作るが、そこにログアウトは無い。
- **ナビ関連の JS 関数は残してある**（`hideBottomNav` / `showBottomNav` / `loadNavOrder` / `startNavEditMode` …）。
  tasks.html などが呼んでいるので消すと落ちる。どれも `.bottom-nav` が無ければ何もしない作り。
- `--nav-raw` の既定値を `134px` → `0px` に。下端の余白は `:root` の下限（セーフエリア + 10px）が担保する。
  **ここで `0` を入れる場所を間違えると、バーがホームインジケータに沈む**（nav-hide-v4 の教訓）。

### 3. 引き出しの向きボタンの表示バグ <!-- drawer-side-paint-v1 -->

歯車の「上下左右」が、読み込み直後だけ「右から」に戻って見えた（動きは正しい）。
設定モーダルの JS が `document.body.dataset.drawerSide` を読むが、**そこに書き込むのはページ下部の引き出し JS**。
設定側が先に走るので必ず空 → `|| 'right'` に落ちていた。サーバの `drawer_side` を起点にし、`DOMContentLoaded` で塗り直す。

### 4. ブランチについての注意（重要・事故りかけた）

**本番ブランチは `tasukaru`。`main` は 2026-04 で止まった残骸**（app.py 101行）。
`main` にマージしようとして app.py / utils.py / README.md が全面コンフリクトした。`git merge --abort` で復旧。

```bash
# 本番マージ（正）
git checkout tasukaru && git pull origin tasukaru
git merge tasukaru-dev && git push origin tasukaru
git checkout tasukaru-dev
```

### 本番反映

`ca1aa0c`（tasukaru）。DDL は `staff_settings` / `rec_expenses.receipt_url` /
`soge_settings.odo_enabled` / `soge_days.odo_start` すべて適用済みを確認。

### 次タスク

1. レシート OCR の実運用での精度確認（**レシートを取っておく**）、送迎の走行距離入力の使用感。
2. DEV のダミー利用者データ削除（`db/soge_dummy_dev*.sql`）。
3. 管理者が施設の既定ドロワー配置を決められるように（今は個人設定のみ）。
4. admin.html に残る `alert()` の掃除（Chrome 拡張の自動操作をブロックするため）。

### 追記: 記録充足チェックの「固定」でハマった3段（2026-07-14）<!-- record-check-stick -->

「横に引っぱると氏名の列まで付いてくる」。原因は**3つ別々**で、順に潰した。

1. **表の幅（`record-check-stick-v4`）— これが真因**
   `table.rc { width:100% }` だった。列幅の合計（104 + 34×カテゴリ数 + 36）が画面より広いとき、
   `table-layout: fixed` は **箱を広げず、中身だけはみ出させる**。枠（`.rc-wrap`）は「溢れていない」と
   判断して横スクロールを作らず、**代わりにページ側が動いていた**。sticky は「いちばん近いスクロールの箱」を
   基準にするので、箱が動いていない以上、貼りつきようがない。
   → `width: max-content; min-width: 100%`。これで初めて枠が横スクロールの箱になる。

2. **JS で追従させようとして失敗（`record-check-stick-v4` → `v5` で撤回）**
   sticky を諦めて「スクロール量ぶん `transform` でセルを動かす」方式にしたが、
   **iOS は慣性スクロール中の `scroll` イベントが遅れて出る**ため追従が間に合わず、
   指を離すまでセルが取り残されて「表が分割して動く」ように見えた。
   **スクロールに 1 フレームでも遅れる方式は iOS では必ず破綻する。** sticky に戻した。

3. **iOS のバウンド（`record-check-bounce-v6`）**
   強く払うとゴムのように弾む（ラバーバンド）。バウンド中はスクロール位置が範囲の外に出るので、
   貼りついた要素もその分だけ動く。sticky では止められない。
   → `overscroll-behavior: none`。**`contain` では止まらない**（あれは「親へスクロールを伝えない」だけ）。

教訓: **PC の Chrome で sticky が効いていても、iOS で効いているとは限らない。
ただし「iOS の sticky が壊れている」と決めつける前に、まず“枠が本当にスクロールしているか”を疑う。**

---

## 【開発ログ】2026-07-14(3) 生活機能CHECK：BIシートを「点数だけ」に簡素化 <!-- session-2026-07-14-lc-bi-simple -->

**本番反映済み**（`fae993f`）。DDL 不要。変更は `templates/life_check.html` のみ。

### なぜ

`/life_check` は要介護向けの **様式3-2** を基準に作ったので、ADL10項目それぞれに
「課題(有/無)」「AI相談」「環境」「状況・生活課題」が付いている。
要支援・事業対象者に使う **紙のBIシート** は 評価項目 / 点数 / 得点 / 合計 だけ。
現場では詳しすぎて手が止まるので、BIモードでは付属欄を出さないことにした。

### 実装（`lc-bi-simple-v1`）

- シート種別トグル（`sheet_mode` = full / bi）は 2026-06 に実装済み。BIでは
  「車椅子・IADL・基本動作（4段階）」カードを隠していた。今回そこに **ADL各項目の付属欄** を足した。
- `body.lc-bi` を `lcSetMode()` で付け外し。CSS で
  `#lc-adl-area` 内の `.lc-sub` / `.lc-textfields` / `.lc-assist` を `display:none`。
- **DOM からは消さない。** 保存(`lcCollect`)・編集復元(`lcPrefill`)・リセット(`lcResetForm`)が
  `[data-env]` / `[data-note]` / `.lc-issue button` を直接 querySelector しているため、
  消すと周辺のJSを全部直すことになる。隠すだけなら値は空のまま保存されるだけで済む。
- **個々の要素に style を当てず body のクラスにした理由**: ADL項目は `lcBuildInputs()` が
  JSで後から描画する。再描画のたびに当て直す方式は当て忘れが必ず出る。
- 介護度が 事業対象者 / 要支援1 / 要支援2 なら自動でBIモード（既存 `lcModeFromCareLevel`）。
- 基本情報カードと「総合所見・特記事項」はBIでも残す（記録として持っておきたいため）。
- 過去に full で保存した記録を開けば `sheet_mode` が復元されるので、従来どおり全項目が出る。

---

## 【開発ログ】2026-07-14(4) 写真販売モジュール（管理番号・注文・請求・入稿ZIP） <!-- session-2026-07-14-photo-sales -->

行事写真を利用者に販売する仕組み。撮影→注文→請求→プリント入稿→仕分けまでを通す。
**既定OFF。開発者MENUのトグルで施設ごとに許可**（弊社のみON。タイムカードと同じ二段構え）。

### 画面 / API（マーカー `photo-sales-*`）

- `/photo` … タブレット注文。行事を選び、利用者を選び、写真タップで枚数±。タップのたびに保存。
  選択中の利用者を上部に sticky で貼る（誰の注文か見失わない）。
- `/photo/admin` … 行事作成・**ドラッグ&ドロップ取り込み**（スマホはタップでカメラロール）・単価・一覧・集計・入稿ZIP・仕分けリスト。
- 請求額計算に「写真」タブ（`photo-sales-rec-tab-v1`）… 利用者ごとに 注文番号・枚数・請求額。読み取り専用。
- `/photo/sheet`（`photo-sales-sheet-v1`）… 仕分けリスト（印刷）。管理番号順＋利用者別。
- API: `/api/photo/albums`(GET/POST) `/album_close` `/price` `/upload` `/list` `/delete` `/order` `/summary`、`/photo/export`(ZIP)。
- 開発者MENUトグル `/api/dev/toggle_photo_sales`（`photo-sales-devtoggle-v1`、`facilities.photo_sales_enabled`）。

### 管理番号を絶対に間違えない設計（ここが肝）

- 番号は**サーバだけが採番**。クライアントから番号を受け取る口を作らない。
- 採番手順: ①DBに行を作って番号を確保 → ②Storageへ上げる → ③URLを書き戻す。
  `unique(album_id, seq)` で同時アップの衝突を物理的に防ぎ、落ちたら seq+1 で再試行。上げ損ねた番号は捨てる。
- **番号は再利用しない**。写真の削除は論理削除（`is_deleted`、欠番のまま）。使い回すと別人の写真が届く事故になる。
- Storageのファイル名も管理番号と同じ。画面・DB・ZIP・CSVで同じ文字列。
- 集計は `_photo_summary()` の1箇所だけ。画面・請求タブ・ZIP・仕分けが必ず同じ数字になる。

### 入稿はしまうまプリント前提（`photo-sales-no-v2` / `zip-v3`）

- キタムラのネット注文はアップ後にサイト独自番号を振り、元ファイル名も出ないので、
  「どのサムネが何番か」を人が照合して枚数を打つ工程が生まれる（一番間違える）。これを避ける。
- **しまうまは銀塩プリントの裏に「お客様のファイル名（半角英数）」を印字する** → 届いた写真の裏に管理番号が出る。
  そこで **管理番号を英数字のみ**（`A001005`。ハイフン等の記号は裏印字で落ちる）に変更。
- ZIPは**枚数ぶん複製**（3枚なら `A001005a/b/c.jpg`、1枚は素の `A001005.jpg`）。
  サイトでは「L判・1枚」で一括設定するだけ＝枚数入力も照合も工程ごと消える。複製の連番は英字suffix
  （数字だと裏印字で番号と一体化して読めない）。
- 届いたら裏の番号で `/photo/sheet`（管理番号順）を引いて封筒へ。番号順に積まれて届くので上から処理できる。
- **注意: 銀塩プリントを選ぶ（NEWデジタルプリントは裏印字なし）。配送受取（店頭受取は裏印字仕様が変わる）。**

### DDL（`db/photo_sales.sql`。DEV適用済 / 本番は要適用）

`facilities.photo_sales_enabled`（既定false）＋ `photo_albums` / `photos` / `photo_orders`。
単価は `admin_settings.photo_unit_price`（手動upsert）。単価は注文行に写し取る（後で変えても確定請求は動かない）。

### 検証（Chrome/DEV, DEMO001）

採番連番・注文・集計・ZIP（複製とファイル名）・仕分けリスト・請求タブ、すべて数字一致を確認。
テストデータは削除済み（空アルバム「A001 花見」のみ残置）。

### ハマり

- 仕分けリストが500（`photo-sales-sheet-v2`）。Jinjaで `b.items` は dict の `.items()` メソッドを拾う → `b["items"]` で回避。

### 本番手順

1. 本番Supabaseで `db/photo_sales.sql` を実行。
2. `tasukaru` へマージ・デプロイ。
3. 開発者MENUで `cocokaraplus-5526` の「写真販売」をON（または `update facilities set photo_sales_enabled=true where facility_code='cocokaraplus-5526';`）。

### 次タスク（将来）

- 顔認証で「その人が写っている写真だけ」抽出。`photos` に `photo_faces`（写真×人物）を足して注文画面にフィルタを足す形で今の作りに乗る。実運用が回ってから着手。

---

## 【開発ログ】2026-07-15 議事録を新デザイン統一・要約強化・必ず1ページ <!-- session-2026-07-15-minutes-redesign -->

会議記録（担当者会議／勉強会・職員会議）の議事録が「長すぎて読む気にならない」という声を受けて、
要約の質・レイアウト・分量を作り直した。**本番反映済み**（`c06014a`）。DDL 不要。

### 担当者会議（第4表）

- **立場ごとに項目を分けて生成**（`meetings-speaker-sections-v1`）: 本人の希望／家族の意向／ケアマネの提案／施設の提案。
  会話の羅列ではなく、各立場の発言を1つにまとめてから短く要約する。パーサー `_mtg_parse_minutes_struct` に
  `wish` / `family` / `cm_proposal` / `facility_proposal` / `state_icf` を追加。
- **検討内容は上の4項目とは別に生成**。擦り合わせの流れと合意点だけを2〜3文で。結論と一字一句同じにしない。
- プロンプトで「1〜2文」「言い換えの繰り返し・前置き・修飾を削る」「雑談は入れない」を明示。

### 勉強会・職員会議（`staff-minutes-*`）

- 立場分けは無し（関係者が本人・家族ではないため）。議題／議論の内容／決定事項／ToDo／その他を簡潔に。
- 議論の内容は議題ごとの箇条書きではなく短い要約文に。

### PDF（`meetings-minutes-unified-v1` / `staff-minutes-unified-v1`）

- **8スタイルを1つの新デザインに統一**。`style` 引数（a〜h）は互換のため残すが、どれを選んでも同じ
  「タイトル→氏名強調→開催情報→検討した項目→(4項目の枠)→検討内容→結論→残された課題→ICF1行」の1枚レイアウト。
  旧8スタイルの分岐コードは return より後ろに残置（デッドコードだが無害）。
- **必ず1ページに収める**（`meetings-pdf-onepage-v1`）: `_mtg_pdf_render_fit()` が zoom=1.0 で描き、2ページ以上なら
  zoom を 0.06 ずつ下げて描き直す（下限 0.60）。**中身は削らず縮尺だけで収める**ので網羅性は保たれる。
  ページ数判定は fitz→pypdf でフォールバック。議事録PDF（担当者会議 minutes / all の議事録部分 / 勉強会）に適用。
- デザインは Imagine モックで HIRO と数往復して確定（ヘッダー控えめ・タイトル「サービス担当者会議の記録」・
  4項目は1列ずつ枠囲み・フッター無し）。

### 重要な注意

- **新デザイン・新要約は「これから新規生成した議事録」だけに反映される**。過去に保存済みの議事録は
  旧 `minutes_struct`（話者欄なし）のままなので旧レイアウト・旧文章で出る。「変わっていない」と見えたら
  まず新規生成で確認すること。

### 検証（Chrome/DEV）

担当者会議・勉強会とも 要約→保存→PDF生成 で **1ページ**・新デザイン・話者分けを確認。テスト議事録2件は DEV に残置。

---

## 【開発ログ】2026-07-15(2) 掲示板の全既読ボタンが消えた不具合 <!-- session-2026-07-15-board-markallread -->

**本番反映済み**（`0b88346`）。`templates/board.html` のみ。DDL 不要。

### 症状と原因（`board-markallread-fix-v1`）

- 2026-07-14 のボトムナビ廃止（メニュー刷新）で、掲示板ヘッダーの「全既読」ボタンが出なくなった。
- 真因: `updateUnreadCount()` が未読バッジは更新するのに、**全既読ボタン枠の表示/非表示制御が失われていた**。
  枠は `display:none` のまま誰も表示に戻さない状態だった。
- あわせて `id="board-mark-all-read-wrap"` が **2箇所に重複**（ヘッダー内の実ボタン＋sticky外の空div）。
  `getElementById` は先頭を返すので実害は出ていなかったが、事故の元なので空の重複を撤去した。

### 修正

- `updateUnreadCount()` で `count > 0` のときだけヘッダーの全既読ボタンを表示（0件なら隠す）。
- 押下時は既存 `/api/board/mark_all_read` で全既読化しボタンも隠す（既存ロジックのまま）。

---

## 【開発ログ】2026-07-15(3) TOPの目標変更アラートで軸別変更が漏れる不具合 <!-- session-2026-07-15-goal-alert -->

**本番反映済み**（`fd58516`）。`app.py` の `/api/goal_check` のみ。DDL 不要。

### 症状

評価で目標を変更したのに、TOPの「目標変更アラート」に乗らない人がいた（本番・6月評価で4名）。

### 原因（`goal-alert-peraxis-fix-v1`）

アラートは `patient_evaluations` の **集約列だけ**（`training_goal` / `short_goal_new` / `long_goal_new`）を見ていた。
だが評価フォームは目標を **軸別の列**（`short_goal_function_new` / `_activity_new` / `_participation_new`、long も同様）にも保存し、
各軸に `*_cont`（「変更」/「継続」）フラグを持つ。**要介護の評価は軸別列に目標を入れる**ため、
軸別だけ変更した人は集約列が空で、アラートから漏れていた。

### 修正

検出条件を広げた:
- 集約列＋**軸別の新目標6列**のいずれかに2文字以上のテキストがあれば変更。
- または `*_cont`（集約2＋軸別6）のいずれかが「変更」なら変更（継続はカウントしない）。
- 表示テキストが空でフラグだけの場合は「（目標を変更）」と出す。

### 検算（本番CSV・読み取りのみ）

2026-06 の評価68名で、旧ロジック3名 → 新ロジック7名。差の**4名がこれまで漏れていた人**で、
いずれも軸別 new 列に目標が入り `*_function/activity/participation_cont = 変更` になっていた（＝原因確定）。

### 仕様（変更なし）

表示期間は従来どおり「変更月の翌月10日まで」。今日(7/15)時点では6月分は期間外で出ないが、7月以降の変更からは漏れない。

---

## 【開発ログ】2026-07-15(4) 休み連絡の記録を消してもカレンダーが消えない不具合 <!-- session-2026-07-15-record-cal-delete -->

**本番反映済み**（`1e0bcb2`）。`app.py` の `/api/delete_record` のみ。DDL 不要。

### 症状

ケース記録で休み連絡を登録するとカレンダーにも「◯◯様 お休み」が出る。だが**ケース記録を削除してもカレンダー側が残った**。
編集・削除は双方向のはずだが、片方向（記録→カレンダー）の削除同期が抜けていた。

### 原因（`record-cal-delete-sync-v1`）

`api_delete_record` が `records` を消すだけで、連動する `calendar_events` を消していなかった。
カレンダー側の削除（`api_delete_calendar_event`）は記録側を同期していた（逆方向はOK）ので、記録→カレンダーだけが漏れていた。

### 修正

記録削除時に、その記録が生成したカレンダーイベントも消す:
- `calendar_events.record_id == 記録id` でまとめて削除（**複数日の休みは複数イベントだが全て record_id で紐づく**ので一括で消える）。
- 旧データ対策として `records.calendar_event_id`（先頭イベント）経由でも1件削除。
- カレンダーの delete API を介さず**直接 delete** するので、記録側を巻き込む再帰は起きない。
- カレンダー削除に失敗しても記録削除は続行（孤児イベントは残るが記録は消える）。
- 休み連絡だけでなく追加利用連絡（同じく record_id で紐づく）にも効く。

### 検証（Chrome/DEV）

- 単日: 休み連絡作成→カレンダー1件→記録削除→**0件**。
- 複数日(飛び日3日): 作成→カレンダー3件(全て同一 record_id)→記録削除→**0件**。
- 逆方向（カレンダー編集・削除→記録同期）は既存のまま維持。

---

## 【開発ログ】2026-07-15(5) タイムカード各種：休憩カウントダウン復旧・並び順・休暇備考 <!-- session-2026-07-15-timecard -->

タイムカード機能で複数の不具合・要望をまとめて対応。**すべて本番反映済み**。

### 1. 休憩カウントダウンが出ない（本番DDL未適用）

- 原因: 本番 `timecard_records` に **`planned_break_min` 列が無かった**（DEVのみ適用されていた）。
  列が無いと休憩開始の insert が失敗し、カウントダウンも出ない。`select("*")` 側は壊れず insert だけ落ちていた。
- 対処: 本番で `alter table timecard_records add column if not exists planned_break_min integer;` を実行。
- あわせて **有給の staff_leave_days テーブルは本番に存在**（information_schema で確認）＝有給側はDB問題ではなかった。

### 2. 休憩カウントダウンの表示改善（`break-countdown-display-v2`）

- 職員カードに残り時間が出ない → `_tcAfterPunchOk` が打刻直後に `state`だけ更新し `break_info` を更新していなかった。
  一覧カードは `s.break_info` を見るので出なかった。→ `hit.break_info = j.break_info` を追加。
- 表示: **入った時間は小さく・残り時間を大きく**（老眼対応）。TOPバナーは全部横並び（「休憩中」角丸＋開始時刻＋残り特大）。
  職員カードは開始時刻〜残り時間を横並び・大きめ。超過は赤。
- TOPバナーの「しばらく出ない」対策（`timecard-top-break-refresh-v1`）: visibilitychange / pageshow / focus / 60秒間隔で `/timecard/my_break` を取り直す。

### 3. 職員カードの並び順が毎回変わる → 手動並べ替え（`timecard-staff-order-v1`）

- 原因: `_tc_staff_list` が `staffs` を **order 無し**で取得していたため並びが不定。
- 対処: 「保存した順→名前順」で必ず同じ並びに。保存順は `admin_settings(timecard_staff_order)`（JSON配列）。
  管理者MENU→タイムカード管理→**「並び順」タブ**で↑↓して保存。API `GET/POST /api/admin/timecard_staff_order`（管理者のみ）。
- Chrome/DEVで 逆順保存→反映→名前順に戻す まで検証。

### 4. 振替休なのに夕方の勉強会に出た等の経緯を記録できない（`timecard-leave-note-v1`）

- 打刻時にモーダルが出なかった日や経緯を、**本人が打刻画面から後から登録・修正**できるようにした。
  打刻画面に「休暇・備考の登録／修正」ボタン→モーダル（日付=過去30日 / 区分 / 振替元 / 備考）。最近30日の登録一覧をタップで読込・修正。
- API: `/timecard/leave/self` に `note` を追加保存（`staff_leave_days.note` は既存列）。一覧取得 `/timecard/leave/self_list` を新設。
- **月次タイムカード出力（様式4）**: 表の下に「■ 備考一覧（日付・職員・区分・備考＋振替元）」を追記。半日型・1日型の両シートに出る。印刷にも残る。
  様式本体のセルは崩さず、`ws.max_row + 2` から下に追記。
- Chrome/DEVで 管理者登録→様式Excel生成→sheet2/3に備考一覧が入ることを openpyxl(zip)で確認。テストデータは削除済み。
- 追記(`prominent-v2`): 様式Excelの備考一覧は説明文の下（49行目付近）で見落としやすかったので、**赤字・太字・下地色・区切り**で目立たせた。位置=`max_row+3`。
- 追記(`timecard-leave-note-report-v1`): **社労士向けの勤怠集計PDF（`/admin/timecard/report_pdf`）にも職員ごとの「備考」欄**を追加。
  各職員の打刻表の下に赤字「備考」→「日付　区分：備考（振替元:○/○）」。`_tc_build_monthly_data` は打刻の無い職員も含むので、
  **打刻ゼロで備考だけの職員も表示**（skip条件を `not days and not notes` に変更）。Chrome/DEVでPDFテキスト抽出で確認。
  → 備考は「様式4Excel末尾の備考一覧」と「勤怠集計PDFの職員ごと備考」の2箇所に出る。

## 【開発ログ】2026-07-16 利用者情報ハブ（見る/入力・家系図・ICF付箋・病歴タイムライン・数秘・AI性質/ICF生成） <!-- patient-hub-v1 -->

既存の利用者情報ページ `/patient-info`（`patient_info_integration.py`＝ケアプラン）を拡張し、**検索した利用者の全履歴を1ページで見る/入力できるハブ**を新規実装。バックエンドは別モジュール `patient_hub_integration.py`（`register_patient_hub_routes(app)` を app.py で登録）。**全施設向け**。マーカー `patient-hub-v1`。

### 目的・方針
- 基本情報（既往歴・家族構成・職歴・趣味嗜好・好き嫌い）の入力を**この1ページに集約**（「どっちに入れる？」を無くす）。既往歴/家族構成は既存 `patient_profiles` の列をそのまま流用（データ移行ゼロ）。旧・編集ページ側の該当欄は今後撤去予定。
- 1ページ内に **「見る／入力」タブ**。選択利用者はタブを変えても保持＝ページ移動なし。「見る」の各カードの✏️で「入力」へジャンプ。

### データ（DDL: `db/patient_hub.sql`＋`db/patient_hub_icf_polarity.sql`。冪等。**本番適用必須**）
- `patient_profiles` に列追加: `job_history / hobbies / likes / dislikes`。
- `patient_family_members`（家系図: sex `m/f`, relation_role `self/spouse/child/parent/sibling/other`, is_self/is_deceased/is_cohabiting/age/sort_order）。
- `patient_medical_events`（病歴タイムライン: event_ym, label, detail, severity, source `manual/record_ai`, status `candidate/approved/dismissed`）。承認済みのみ表示、AI候補は承認/却下。
- `patient_icf_stickies`（ICF付箋: zone `body/activity/participation/environment/personal/unsorted`, text, icf_code, **polarity `can/cannot`**, source_meeting_id）。
- `patient_personality_cache`（AI性質: traits(JSON文字列), summary, source_count。1利用者1行upsert）。

### 主なAPI（`/api/patient-hub/*`。キーは facility_code + patient_profile_id=patient_profiles.id）
- `get`（基本情報＋家族＋病歴(承認/候補)＋ICF＋性質＋数秘をまとめて返す）/ `save-basic` / `family/save`（一括置換）/ `medical/add` `medical/set-status`（承認/却下/削除）/ `medical/scan`（記録からAIで病歴候補=candidate）/ `icf/save`（一括置換）/ `icf/import`（議事録の付箋を取り込み）/ `icf/generate`（記録からAIで「できる/できない」ICF案を返す・**保存はしない**）/ `personality/generate` / `hobby-ocr`（趣味嗜好シートOCR。レシートOCRと同じ Gemini）。

### 実装の勘所
- **数秘**は既存の誕生日会ロジックと同じライフパスナンバー（1-9,11,22,33）をモジュール内 `_calc_numerology` に再実装＋傾向辞書。
- **家系図**は続柄で世代を判定して SVG を自動レイアウト（親→本人/配偶者/兄弟→子）。本人=二重枠、故人=×(赤)、性別 ○/□（不明=ひし形）、同居=点線枠、婚姻・親子=線。エディタ（続柄・性別・年齢・同居・故人）で即プレビュー。
- **ICF付箋**は pointer イベントで自作ドラッグ（iOSの sticky/慣性破綻を避けるため HTML5 DnD は不使用）。⠿ハンドルでつまむ→`elementFromPoint` で領域判定。文字は contenteditable、`board.addEventListener` の委譲でイベント処理（再描画で listener を失わない）。
- **できる/できない**: 付箋に `polarity`。できない=赤。「見る」では領域見出しに「（できないこと有り）」注記。どの領域に不足があるか一目で分かる。
- **議事録取り込み**: `meetings.patient_id`(=patient_profiles.id) で直近会議を特定→`meeting_icf_links` を取り込み。領域は **board_slot(配置スロット: bs/activity/participation/environment/personal/health) 優先 → board_component(構成要素 b/s/d/e) → icf_code から構成要素** の順で判定（b/s→心身機能, d→活動, e→環境）。
- **AI生成(B)**: `icf/generate` は記録を読んで5領域＋できる/できない で ICF案を返すだけ（DB保存しない）。フロントがボードに追加→職員が確認・修正・ドラッグ→「ICF付箋を保存」で確定。議事録音声側(A)への できないこと分類は今後の拡張余地。

### 検証（Chrome/DEV・DEMO001）
- get/保存/家族/病歴(手入力・承認・AI候補)/ICF(追加・領域移動・保存・できる/できない=赤)/議事録取り込み(実データ25枚→心身8・活動14・環境3に振り分け)/AI性質(122件から生成)/AI-ICF生成(16項目・できる8/できない8) を確認。`icf/generate` は保存しないこと(dbIcfCount=0)も確認。
- ダミー利用者「検証ハブ 花子(No.ZZ999)」で全カードの見た目を確認（数秘4/病歴/家系図/ICF赤）。**DEV限定**（本番Supabaseには存在しない）。テストデータは削除済み。

### 追記(A): 担当者会議のICF分類に「できる/できない」を追加 <!-- patient-hub-v1-A -->
議事録の音声/アセスメント→ICF分類（`/api/meeting/classify_icf`, Claude）で、各項目に **polarity(can/cannot)** を付与。"できないこと"も必ず拾う指示。DDL: `db/meeting_icf_polarity.sql`（`meeting_icf_links.polarity`。**本番適用必須**）。
- 会議保存(`/api/meeting/save`)で polarity 永続化。`admin_meetings.html` の付箋ボードで **できない=赤＋「できない」バッジ＋できる/できないトグル**（承認・needs_review の色分けと併存、承認緑は保持）。
- ハブの議事録取り込み(`icf/import`)が polarity を読んで利用者ページでも **できない=赤**。
- 検証(DEV): 分類が polarity を返す(できる/できない判定も的確)／使い捨て会議を保存→取り込みで cannot が赤で入る／ボードのトグルで can↔cannot 反転 を確認。使い捨て会議はDEVでSQL削除。
- なお `icf/generate`(B・記録からAI生成) も同じ polarity を返し、ボードに追加→保存の運用。A(会議由来)とB(記録由来)の両方から できない=赤 が入る。

---

## 会社インフラ整備（Apple法人登録の準備）＋ 管理者パスワード復旧 2026-07-23  <!-- infra-apple-enroll-2026-07-23 -->

### 0. 本番一括プッシュ（完了）
- DEV(`tasukaru-dev`)に溜めた**15コミットを本番(`tasukaru`)へcherry-pickでまとめて反映**。本番tip = `dd7f9a2`。
- 既に本番へcherry-pick済みのkeiyaku系4件(pagebreak-v1/v2, cityarea, margin)は**スキップ**（`git cherry`で判定）。
- base.htmlの `2d1365c`(壊れ) + `04ca065`(修復) ペアは `cherry-pick -n` で**1コミットに束ねて**適用。
- 事前に全ファイル3-wayマージ(競合0)で安全確認。diffstat = 511挿入 / 35削除。

### 1. 会社ドメイン & メール（Apple法人登録の必須要件）
- **ドメイン**: `lifeplusllc.com`（お名前.com、お名前ID 50066893）。ネームサーバー = `01〜04.dnsv.jp`（DNSレコード設定利用のため切替済み）。更新期限 2027/07/22。**自動更新の維持に注意**（切れるとメール/サイト停止）。
- **メール**: Zoho Mail（Mail ライト 5GB、約¥1,680/年、**日本DC=zoho.jp**）。管理者=`hiro@lifeplusllc.com`。管理コンソール `mailadmin.zoho.jp` / Webメール `mail.zoho.jp`。復旧連絡先=`cocokaraplus@gmail.com`。**受信テスト成功済み**。
- **お名前.com(dnsv.jpゾーン)に設定済みのDNS**:
  - TXT(所有権) `zoho-verification=zb86175109.zmverify.zoho.jp`（ホスト=@）
  - MX `mx.zoho.jp`(10) / `mx2.zoho.jp`(20) / `mx3.zoho.jp`(50)
  - SPF(TXT) `v=spf1 include:zoho.jp ~all`
  - A `75.2.60.5`（@、Netlify会社サイト用）
  - CNAME `www` → `chic-gelato-adeb36.netlify.app`
  - **DKIM：未設定（任意・後日）** → `mailadmin.zoho.jp` → ドメイン → DKIM で生成しTXT追加。
- **注意**: MX(受信)とA(サイト)はapexで共存OK。SPFは**1本のみ**（`v=spf1 -all`の重複を作らない）。GoogleパブリックDNS(8.8.8.8)は反映が非常に遅いので、確認はZoho/Netlify側の検証で行う。

### 2. 会社紹介サイト（Apple審査のWebサイト要件）
- **Netlify**(無料)にHTML1枚をデプロイ。プロジェクト `chic-gelato-adeb36` / URL `chic-gelato-adeb36.netlify.app`。独自ドメイン `lifeplusllc.com`(Primary) + `www`(→primaryへリダイレクト)。
- 内容: 合同会社LIFE PLUS / 代表 岸本洋幸 / 〒471-0832 愛知県豊田市丸山町7-49-6 / 事業=介護施設向けSaaS「TASUKARU」/ 連絡先 hiro@lifeplusllc.com。
- Aレコード反映後にNetlifyがSSL自動発行 → `https://lifeplusllc.com` 公開（反映待ち・最大24h）。

### 3. Apple Developer Program（法人登録）— 進行中・残タスク
- 種別=**法人（Individualではない）**。LIFE PLUS LLC は登記済み合同会社。
- **D-U-N-S番号 発行済み**（メール受領）。Appleに入れる**法人名・住所はD-U-N-Sの登録表記と完全一致**させること（不一致で審査停止）。発行直後はApple側反映に数日かかる場合あり。
- 仕事用メール=`hiro@lifeplusllc.com`。$99/年はHIRO本人が決済。
- **残**: Apple法人フォーム送信 → 審査 → 承認後 **APNs .p8 発行** → 再検査アラームのプッシュ通知実装へ。

### 4. 管理者ログイン/パスワード運用（現場対応で判明・重要）
- **スタッフのパスワードは SHA-256 ハッシュ保存**（`staffs.password_hash` = `hashlib.sha256(pw).hexdigest()`）。**元パスワードは復元不可＝リセットのみ**。
- Supabase SQLでのリセット（pgcrypto、アプリのSHA-256と一致）:
  `update staffs set password_hash = encode(digest('新PW','sha256'),'hex') where facility_code='cocokaraplus-5526' and staff_name='<名前>';`
- **管理者MENUは admin-2fa-v1: LINE連携必須 + LINEに届く2FAコード**。**LINE未連携アカウント(PC1/PC2等の共有端末アカウント)は管理者MENUに入れない**。
- 運用: 現場の管理業務は**LINE連携済みの本人アカウント**でログイン（例: `宇佐美友理` を管理者に追加済み）。共有アカウントで他人(例:代表)でログインすると個人カレンダー/タスクが表示される点に注意。
- **PC1/PC2 は is_active=false で無効化**（論理削除・過去記録は保持）。
- 参考: パスワード再設定は `/reset_password`(メール) や LINEで「パスワード」送信(setup_token)でも可能。管理者UIに個人PW再設定ボタンは無い（再作成 or SQL）。


---

## 充足チェック機能追加（月間版＋職員ごとのカスタム）2026-07-24  <!-- record-check-suite-2026-07-24 -->

- **monitoring-check-v1**: モニタリングに「月間 記録充足チェック」を追加（`/monitoring_check`）。その月に来所(=バイタルあり)した利用者×カテゴリの記録件数を表示、0件=赤。月ピッカーで対象月切替。導線は `monitoring.html` 上部のリンク。テンプレ `monitoring_check.html`。本番反映済み。
- **record-check-view-v1**: 日次(`/record_check`)・月間(`/monitoring_check`)の両方に「表示設定」パネルを追加。
  - カテゴリを**職員ごとにドラッグ&ドロップで並び替え**（個人キー `rc_cat_order`）。
  - 「未記入あり」判定の**対象カテゴリを個人で選択**（個人キー `rc_gap_cats`、チェックしたカテゴリのみ判定・赤強調の対象）。
  - 保存は `staff_settings`（個人設定 = 他職員に影響しない）経由。`/api/me/setting`（PUT）。`STAFF_SETTING_KEYS` に2キー追加。
  - 共通ヘルパー `_rc_staff_view(supabase, f_code, my_name, cats)` が並び順と対象フラグ(`target`)を適用。0セルの赤は対象カテゴリのみ、対象外は薄グレー(`zeromut`/`zero`)。
  - `record_categories`(name,color,sort_order) は施設共通のマスタ。並び順(sort_order)は触らず、表示順だけ個人設定で上書き。
  - 本番反映済み(cherry-pick `67972bc`)。

---

## 事前アセスメント（第1〜3段）＋初回BI連携＋介護度履歴＋ICF一本化 2026-07-27  <!-- assess-suite-2026-07-27 -->

本セッションで事前アセスメント一式・介護度まわり・ICF運用を整備し、**2回に分けて本番反映済み**（本番 `eeb0af8` と `4a61721`）。

### 事前アセスメント / フェイスシート（担当者会議の隣タブ）
- ルート `/admin/assessment_sheet`（`assessment_sheet.html`）。mtg-tabs に「事前アセスメント」タブ（担当者会議のすぐ隣）。サブタブ: アセスメント①/②/フェイスシート/初回BI。
- 保存/読込: `/api/assessment/save|load`。INSERT専用バケット対策の**バージョンJSON** `assess/<pid>/<pid>.vN.json`（バケットは `case-photos` を流用）。`_assess_vpath/_assess_next_version/_assess_load/_assess_save`。
- ADL/IADLは4段階色分け（自立=青#1a73e8／見守り=緑#12b76a／一部介助=橙#f79009／全介助=赤#e5484d）。全欄オートグロー（`makeExpandable`/`autoGrow`/`growAll`、サブタブ切替でも `growAll` 再計算）。利用者選択は記録入力と同じ検索ピッカー。
- **第2段OCR** `/api/assessment/ocr`（`assess-ocr-v1`）: ケアマネ書類の写真をGeminiで読取→各項目・ADL・家族構成・基本プロフィールへ正規化（`_assess_normalize`）。家族はジェノグラムへ（`/api/patient-hub/family/save`）。和暦→西暦。ハルシネーション禁止。
- **第3段 音声** `/api/assessment/voice`（`assess-voice-v1`）: 面談録音(MediaRecorder/webm)→Gemini音声解析→OCRと同じ`_assess_normalize`で反映＋transcript表示。音声は永続保存しない。プロンプトは `_assess_extract_prompt("doc"/"voice")` で共通化。
- **聞き取りガイド**（`assess-guide-v1`）: 録音開始で自動オープン。1問ずつ表示＋手動「前へ/次へ」＋進捗、「一覧」切替＆ジャンプ。ADL/IADLの問いは4段階ボタン付きで押すと実アセスメント値を即セット（`guidePick`→`setLevel`）。質問文38問はたたき台（現場で編集可）。

### 初回BI（生活機能チェック/Barthel）の同時入力（`assess-bi-v1`）
- 事前アセスメント内「初回BI」タブ。ADL重複項目を**対応表で自動反映**（`biApplyFromAssessment`）、BI固有のトイレ動作・階段昇降は「追加で確認」バッジで手入力。合計/100点を自動計算。保存 `/api/save_life_check`（`life_function_checks`、キー=facility_code+patient_id+check_date）→閲覧・修正は生活機能チェック(BI)画面。
- **4段階→Barthel（見守り=自立寄り）**: 3段階(10/5/0)=自立/見守り→10・一部→5・全→0／2択(5/0)=自立/見守り→5・介助→0／4段階(15/10/5/0 移乗・歩行)=自立→15・見守り→10・一部→5・全→0。入浴は出入り/洗身の重い方を採用。起き上がり/立ち上がりは基本動作(basic_situp_level/basic_standup_level)へ。

### 介護度（適用開始日・変更履歴・評価連携）
- `patient_profile.html`（`clh-front-v2`）: 介護度変更時に**適用開始日をカレンダー入力**（認定開始日/本日を初期値、旧文字プロンプト置換）。**変更履歴**を時系列表示。認定有効期間を介護度の隣へ配置。
- 履歴API `/api/patient/care_level_history`（`clh-history-view-v1`）。記録は既存 `_record_care_level_history`＋`care_level_history`（facility_code, patient_id, care_level, valid_from）。
- 評価の介護度自動セットを**対象月時点**へ（`evaluation_helper.py` `clh-dateaware-v1` `get_initial_care_classification`）: care_level_historyの月末時点→区分。過去月は当時の介護度。無ければ現在値→前回評価にフォールバック。

### ジェノグラム
- 故人表記を**塗りつぶし＋「死」**へ（`patient_info.html` `drawSym`、旧✕から標準表記、凡例更新）。

### ICF運用の一本化（`icf-per-record-off-v1`）
- 記録入力ごとの「ICFに追記しますか？」ポップアップと先読み提案を**廃止**（`input.html`、保存後は通常の記録一覧へ遷移）。TOPの「ICF追記の未確認」バナーも**常時非表示**（`top.html`）。
- ICF作成は利用者情報ICF「入力」タブに一本化。ボタン文言を「**ケース記録からICFを取り込む（AI・できる/できない）**」へ（`/api/patient-hub/icf/generate` は `records` を最新200件読取してAI整理）。

### UI整形
- 上部mtg-tabsを**2段表示**（担当者会議・/ICF、事前/アセスメント、勉強会・/会議議事録）。`word-break:keep-all`＋明示改行でカタカナ1文字落ちを解消（3画面統一）。
- アセスメント②サブタブが初期非表示で高さ0に潰れる不具合を修正（`abb580a`）。

### 検証（DEV）
- OCR: 模擬書類で36項目反映・ADL色分け・家族4名(故人含む)抽出。音声: UI/ガード確認（実録音は要実機）。初回BI: 反映→点数化(見守り=自立寄り)→`life_function_checks`保存(70点・basic動作含む)。介護度: カレンダー・履歴・対象月時点連携。ガイド: 1問ずつ送り・ADL/IADLボタンで実値セット・一覧切替。

## モニタリング生成の相対日付を実日付・実月へ置換 2026-07-28  <!-- reldate-normalize-v1 -->

モニタリング報告書をケース記録から生成する際、「今日／本日／昨日／一昨日／先月／先々月／今月」等の相対表現が実日付・実月に置き換わらない不具合を修正。原因は、この置換がAIプロンプトではなく Python 側の文字列置換（旧 `_replace_kyouha`）で行われ、対象が「今日」の変種だけに限定されていたこと（かつ印刷プレビューの自動生成には置換処理が無かった）。3層で確定的に対処し、AI任せにせず誤変換・ハルシネーションを回避する。

### 1) 入力（記録本文）の正規化 — `_normalize_relative_dates(content_text, created_at)`（app.py）
各記録の作成日(`created_at`, Asia/Tokyo)基準で、今日/本日→◯月◯日、昨日→前日、一昨日・おととい→2日前、先月→前月「◯月」、先々月→2か月前「◯月」、今月→当月「◯月」へ置換。長い語（一昨日・先々月）を先に処理。旧 `_replace_kyouha` は撤去。

### 2) AI生成文の抑止 — `BASE_PROMPT`（app.py）
生成ボタン `api_generate_monitoring` と印刷プレビュー自動生成 `_auto_generate_monitoring` の両プロンプトに「相対表現は使わず◯月◯日／◯月で書く」ルールを明記。

### 3) 出力の後処理 — `_strip_relative_month_terms(text, year, month)`（app.py）
プロンプト指示だけではAIがまれに地の文で「今月」等を使うため、生成文の**月単位**の相対表現（今月/先月/先々月/来月/再来月）を報告対象月基準で実月へ確定的に置換。日単位は記録本文側で実日付化済みのため対象外（「本日ご報告いたします」等の報告行為の語を誤変換しない）。full/カテゴリ別/印刷プレビュー自動生成の3経路に適用。

### 適用経路
生成ボタン `/api/generate_monitoring`（full・カテゴリ別）と印刷プレビュー自動生成 `_auto_generate_monitoring`。

### 検証
- 単体: 月跨ぎ（7/1の昨日→6月30日）・年跨ぎ（1月の先月→12月・先々月→11月）・2月境界（3/1の昨日→2月28日）・UTC→JST・created_at空の素通り・未対象語（明日/誕生日）の不変。後処理は4月→今月=4月/先月=3月/先々月=2月/来月=5月、1月→先月=12月、日単位「本日ご報告」不変。
- DEV実機（岡田 清 2026-04・本日6件を含む91記録・まとめて1本）: 記録由来の相対表現は出力ゼロ。プロンプト適用後の複数回生成で地の文の「今月」も出力段で「4月」へ置換され、記録由来の日付は「4月4日」「4月18日」等に実日付化されることを確認。

## 利用者基本情報の曜日がバイタルに出ない問題の修正 2026-07-28  <!-- patient-int-link-fix-v1 -->

利用者基本情報で利用曜日を設定してもバイタル画面に反映されない不具合を修正。

### 原因
曜日データ `patient_visit_days` は `patients`（整数ID＝patient_int_id）をキーに持つ一方、基本情報は `patient_profiles`（UUID）側で、両者は**氏名(user_name)の完全一致でのみ紐づく**（`get_patients` の `patient_int_id = pt_id_map.get(name)`）。氏名一致に失敗して整数IDが引けないと、(a) 基本情報画面の `PATIENT_ID` が null になり `if(!PATIENT_ID) return` で**無言で保存されない**、(b) バイタル側も曜日を引けず（`renderPatientList` は当日 NONE を非表示）に出ない。氏名一致が壊れる主因は「改名（patients側が未同期）」「旧データ/取込で patients 行が無い」「表記ゆれ」「同姓同名」。

### 修正（app.py / patient_profile.html, marker `patient-int-link-fix-v1`）
- `/patient_profile` を開いた時点で、対応する `patients` 行が無ければ `_ensure_patient_row` で自動作成し `PATIENT_ID` を必ず用意（旧データ救済）。
- `/api/admin/patient/save` の更新経路で氏名変更を検知し、`patients` 側の氏名も同名へ更新（改名で橋が切れないよう同期）。更新後に patients 行が無ければ作成。
- `patient_profile.html` の曜日/第N週トグルは `PATIENT_ID` が無いとき見た目を元に戻し「基本情報を一度保存してください」と警告（無言失敗の解消）。

### 補足
新規追加・保存新規・一括取込の各経路は既に `_ensure_patient_row` で patients 行を作成済み。将来的には氏名ではなく安定IDでの結合が理想だが、影響範囲が大きいため今回は対症で再発防止に留める。


## 勤怠集計表をグリッド化し「休み申告」を反映＋画面に休み表示/登録編集 2026-08-03  <!-- timecard-leave-grid-v1 -->

タイムカードの「休み申告」データ（`staff_leave_days`）を、実際の勤怠出力（勤怠集計表PDF）と管理画面の勤怠集計に反映。

### 背景・調査
- 休み申告は `staff_leave_days`（`leave_type`＝paid/substitute/condolence/absence/off/half/hourly/cancel、`substitute_for`＝振替元、`note`＝経緯メモ）。入力は職員本人（打刻画面 `/timecard/leave/self`・過去30日以内）と管理者（編集モーダル `/admin/timecard/leave/set`）。
- 反映状況（着手前）: 様式4xlsx `/admin/timecard/youshiki`・給与payroll出力 `/admin/timecard/export/payroll/*` は反映済み。一方、勤怠集計表PDF `/admin/timecard/report_pdf` は**備考(noteあり)のみ**、画面の勤怠集計 `/admin/timecard/monthly`(admin_timecard_report.html)・simple出力は**打刻のみで休みは非表示**だった。いただいたグリッド型PDF（職員×日付・色ラベル・空欄=公休）は当時コードに無く、目標デザインだった。

### 主な変更（app.py / templates/admin_timecard_report.html, marker `timecard-leave-grid-v1`）
- 休みをマージする `_tc_merge_leaves_into_monthly` を新設。`_tc_build_monthly_data` と `admin_timecard_monthly` の両経路で、各日dictに `leave`（区分/ラベル/振替元/note）を付与し、打刻の無い休暇日も days に追加、職員dictに `leaves` 一覧を付与（画面・PDFで同一データ源）。
- 勤怠集計表PDF `report_pdf` を **職員×日付グリッド（A4横）** に刷新（`_tc_report_grid_html` / `_tc_grid_cell` / `_tc_leave_style` を新設、pdfkitオプションをLandscape化）。有給=緑・振替休=青・欠勤=赤ほかを色ラベル、公休は空欄、施設合計・月合計・備考・凡例、打刻要確認は⚠。
- セル表記は上段「〇時〇分〜〇時〇分（休憩〇分）」（`_tc_fmt_time_jp` を新設）＝**太字で強調**、下段「〇時間〇分勤務」は控えめ。
- 画面(admin_timecard_report.html)は従来のコンパクト表記のまま、休みの色ラベル表示（`leaveChip` / `LV_COLOR`）と、各職員の「日付を選んで編集（打刻・休み登録）」導線を追加。記録の無い日/職員でも編集モーダルを開いて休み登録・変更・削除が可能（`.tcr-al-btn`）。

### 検証・リリース
- サンプルデータでPDFをwkhtmltopdf生成し、色ラベル・振替元・公休空欄・上段強調・月合計・備考・凡例を目視確認。app.py=py_compile通過、テンプレJS=node --check通過、render単体テストで休みチップ/編集導線/記録なし職員パネルを確認。
- dev(`tasukaru-dev`) 583c987→5796802、本番(`tasukaru`)マージ feb285a。GitHub push→Cloud Build自動デプロイ。
- 対象外（従来通り）: simple勤怠出力（CSV/Excel）は打刻のみ。将来必要なら同マージmapで休暇列を追加可能。


## 勤怠集計表をCSVでも出力（個人別対応）2026-08-03  <!-- timecard-grid-csv-v1 -->

タイムカードの記録をPDFだけでなくCSVでも出せるようにした。施設全体・職員ごと（個人別）の両方に対応。

### 背景
- 既存の個人別CSVは「給与出力」→勤怠実績(simple)→CSV→職員ごと で出せたが、**休み申告/休暇の列が無い**（simpleは打刻のみ）。payroll CSVには休暇区分列あり。
- 要望は「勤怠集計表（グリッド）と同じ内容をCSVで、個人個人それぞれも出せるように」。→ 集計表グリッドをそのままCSV化する方針を採用（ユーザー選択）。

### 主な変更（app.py / templates/admin_timecard_report.html, marker `timecard-grid-csv-v1`）
- 新ルート `GET /admin/timecard/export/grid/csv`（`pay_export_grid_csv`）。PDFグリッドと同一データ源 `_tc_build_monthly_data`（休み申告マージ済み）を使用し、1日〜末日を全日出力。列＝職員名/日付/曜日/出勤/退勤/休憩(分)/実働(分)/実働(時間)/区分/振替元/備考/打刻異常＋職員ごと【合計】行。区分＝有給・振替休・欠勤等のラベル、登録なしの休みは「公休」。cp932エンコード（Excel互換）。
- `_pay_resolve_params`/`_pay_filter_scope` を流用し `scope=all/staff`＋`staff_name` で 施設全体/職員ごと を切替。ファイル名 `kintai_shukei_YYYYMM[_職員名].csv`。
- レポート画面（admin_timecard_report.html）に「PDFで保存」の隣へ **「CSVで保存」ボタン** と専用モーダル（施設全体/職員ごと選択、職員セレクトは `window._tcrStaff` を流用）を追加。

### 検証・リリース
- app.py=py_compile通過（ローカル＋デバイス両方）、テンプレJS=node --check通過。
- DEV実機(`tasukaru-dev`)で確認済み: 「CSVで保存」ボタン表示、施設全体CSV(2026/7)=200・CSV・12列・全日×5名＋合計5行=161行、職員ごと(デモ職員A)=33行に絞り込み、公休/有給/振替も出力。モーダルの施設全体/職員ごと切替＋氏名セレクト表示もOK。
- リリース: dev `2991f75`→`072ea2c`、本番(`tasukaru`)マージ `782bcdf`→`0e5e54c`。本番実機でもボタン表示＋エンドポイント200・12列を確認（件数のみ確認、個人データ本文は取得せず）。GitHub push→Cloud Build自動デプロイ。

## 職種登録／様式の施設別動的転記・看護職員／勤務予定の本人制限／キャッシュ対策／保存UX 2026-08-13  <!-- staff-role-youshiki-suite-2026-08-13 -->

**DEV・本番とも反映済み（完了）**。詳細な引き継ぎは `SESSION_64_HANDOFF.md` を参照。

### やったこと
- **職員登録に職種を追加（Phase1）**: `staffs` に `job_title`/`job_title2`/`employment_type`（DDL本番・DEV適用済み）。管理者MENU→職員管理で職種（管理者/生活相談員/介護職員/機能訓練指導員/看護師/その他）・兼務職種・勤務形態(A〜D)を登録。`api_add_staff`＋新規 `api_update_staff_job`。
- **参考様式4の施設別・動的転記（Phase2）**: `templates/youshiki_kinmu.xlsx` の**ハードコード職員名（情報漏えい源）を撤去**し汎用化（赤フォント→既定色・枠線修正・**看護職員セクション新設**）。出力時に各施設の職種登録から氏名を役職行へ動的転記。行不足は自動挿入（`_ys_insert_rows_shift` が結合セルも追従）。半日型=2単位/1日型=1単位、値は時間・黒字、看護師→看護職員、兼務は両役職に出力。marker `youshiki-roster-v2` / `型別-svc-hours-v2`。
- **勤務予定入力の本人制限**: 管理者以外は本人のみ表示・保存・既定・コピー。`/api/shift/month|week|save|default|copy` に `is_admin_user` 判定。marker `shift-self-only-v1`。
- **静的JSキャッシュ対策**: `app.py` に `static_v(path)`（内容md5で `?v=` 付与）を追加し、実テンプレ6箇所を置換。旧JSキャッシュで新UIが出ない事象の恒久対策。marker `static-cachebust-v1`。
- **職種／誕生日の保存UX**: 保存中スピナー＋成功トースト、保存後はリロードせずその場更新（管理者MENUトップに戻らない）。`showJobToast`/`_ensureSpinStyle`、小見出し `sjt-`/`sbt-`。

### コミット
DEV `tasukaru-dev`: `55c9e27`→`b4e2646`→`2e8f07a`→`1155963`→`dd5824c`→`89d498d`→`9cfbab9`。
本番 `tasukaru`: `7990749`（前半5件マージ）→`8bca8b3`（保存UX2件マージ）。

## Apple Developer Program 法人登録の再開・申請完了 2026-08-17  <!-- apple-enroll-submitted-2026-08-17 -->

### 経緯（7/23 に止まっていた理由が判明）
- 7/23 に法人登録を開始していたが、**「勤務先メールアドレスの確認」工程で中断**していた。
  Apple が `hiro@lifeplusllc.com` に送る**有効期限10分のワンタイムコード**を入力できないまま失効し、手続きが消えていた。
  （7/23 は Zoho メール開設当日。受信設定の最中でコード受け取りが間に合わなかったとみられる）
- そのため developer.apple.com/account には「今すぐ登録」ボタンが出たまま＝**申請なし**の状態だった。

### 重要な整理（次回混乱しないために）
- **`hiro@lifeplusllc.com` は Apple ID ではない。**登録フォームに入れる「**勤務先メールアドレス（work email）**」。
  → このアドレスでパスワード再設定を試すと「Appleアカウントが有効ではない」と出る。正常。
- **Apple ID は別物**。developer.apple.com にサインインしているアカウントがそれ。**このApple IDがアカウント責任者になる**（後から変更は手間）。
  → ★次回のために `developer.apple.com/account` →「プロファイル」で確認したメールアドレスをここに追記すること。
- D-U-N-S 番号の申請は Apple ID 不要（メールアドレスだけ）。だから「Apple からメールは届くのに Apple ID は無い」という状態が起こりうる。

### 登録に使った情報
- 法人名: `LIFE PLUS, LIMITED LIABILITY COMPANY`（**D-U-N-S の登録表記と完全一致させること**。不一致で審査停止）
- **D-U-N-S 番号: 692505882**（機密ではなく法人識別番号。控えてよい）
- 住所: 〒471-0832 愛知県豊田市丸山町7-49-6
- 勤務先メール: `hiro@lifeplusllc.com`（Zoho / mail.zoho.jp）
- 会社サイト: `https://lifeplusllc.com`（Netlify・Apple審査のWebサイト要件用）

### 現在の状態（2026-08-17）
- **申請送信済み → Apple の確認待ち（審査中）**。
- 画面表示：「法的な契約に対して署名権限をお持ちであることが確認できたら、登録完了までの手順をEメールでお送りします」
- **Enrollment ID（登録ID）= `WAVNW2S5G6`**（2026-08-17 取得）。サポート照会に必須。
  ※登録IDは機密ではない（申請を特定するための整理番号）。控えて共有してよい。
  ※一方で **ワンタイム確認コード・パスワード・APIキーは絶対に貼らない/転送しない**。
- developer.apple.com/account の表示：「**現在登録を処理しています。あなたの登録IDは WAVNW2S5G6 です。**」
  → この表示が出ていれば申請は生きている（7/23 は「今すぐ登録」のままだった＝申請なし）。

### 次にやること / 注意点
1. **D-U-N-S 登録の電話番号に Apple から確認の電話が来ることがある。取り逃すと審査が止まる**（7/23と同じ失敗パターン）。
2. 承認まで **2〜4週間**が目安。**2026-09-中旬**を過ぎても連絡が無ければ、
   developer.apple.com/support →「Membership and Account」→「Program Enrollment」→ **電話（折り返し）**で照会。
   Webフォームより明らかに速い。Enrollment ID を伝える。
3. **重複申請・先行しての $99 支払いはしない**（二重登録で遅延する）。
4. 承認 → 案内メールに従い **$99/年を支払い** → 登録完了 → **APNs `.p8` 発行** → 再検査アラームのプッシュ通知実装へ。
5. 進捗は developer.apple.com/account で随時確認できる（審査中の表示になる）。

### 待機中に無料で進められること
- **iPhone 実機インストール**（審査不要・費用ゼロ）: Xcodeで実機に入れて、ネイティブ通知とオフライン災害モードを検証。
  `tasukaru-app/ios/App/App.xcodeproj` に **DEVELOPMENT_TEAM = BB7M7M88HC** / Bundle ID `jp.lifeplus.tasukaru` が設定済み。
- **Android 内部テスト**（Google Play は $25 支払い済み・追加費用なし）: `npx cap add android` → 内部テストで最大100人に配布。
- アイコン一式・表示名・起動画面の整備（Claude 担当）。

### セキュリティ上の注意（今回の学び）
- Apple の**ワンタイム確認コードは他人に見せない／転送しない**（10分で失効するが本人確認そのもの）。
- 新規ドメイン取得後、「あなたのサイトに重大なエラーがあります」系の**営業スパム／フィッシング**が届く。
  （例: `Major Errors in Lifeplusllc...` / `LIFE PLUSのウェブサイト...`）→ **開かず削除・リンクを踏まない**。

## バイタル「本日の利用者を追加」が効かない問題の解決＋日付単位の臨時追加 2026-08-18  <!-- vital-daily-include-2026-08-18 -->

### ★ 最重要：本番の施設コードは `cocokaraplus-5526`（`cocokaraplus` ではない）
今回の調査で `facility_code = 'cocokaraplus'` を条件にした診断SQLを使い、**「0件」という結果を3回続けて誤った証拠として扱った**。
条件が合わず0件だっただけで、実際にはデータが存在していた。原因究明が大幅に遠回りになった。
→ **診断SQLを書く前に必ず施設コードを確認する。**
```sql
select facility_code, count(*) from patient_profiles group by 1 order by 2 desc;
```

### ★ 利用者IDが2系統ある（混同するとデータが迷子になる）
| 用途 | 使うID | 型 | 例 |
|---|---|---|---|
| 画面の利用者一覧 / `vital_daily_excludes` / `vital_daily_includes` | `patient_profiles.id` | **UUID** | `06d9dcf6-a0c1-…` |
| `patient_visit_days`（曜日設定） / `vitals` | `patients.id` | **整数** | `13` |

- `get_patients()` は両方返す：`id`（profiles/UUID）と `patient_int_id`（patients/整数）。
- 曜日設定UIは `{{ p.patient_int_id or p.id }}` を送る（正しい）。
- **バイタルの追加モーダルは `p.id`（UUID）を送っていた**（誤り）→ 誰も読まない孤児行を量産していた（本番で9件確認）。

### ★ `nth_per_day`（第N週指定）は表示直前に強制上書きする
`/vitals` は画面を組む直前に次を実行する。**DBに何が入っていても関係なく非表示になる。**
```python
if not visit_nth_ok(p["nth_per_day"], _today_wd, today):
    p["weekdays"] = str(p["weekdays"]).replace(str(_today_wd), "")
    apd[str(_today_wd)] = "NONE"
```
→ 「追加したのに出ない」の**主因**。曜日設定を書き換えるアプローチでは絶対に解決しない。

### 発端と実データ
現場から「バイタルで本日の利用者を追加しても表示されない。追加した端末では一時的に出るがリロードで消える。他端末では最初から出ない」との報告。
対象は長松軒茂子さん（`patients.id = 13`）。本番の実データは次のとおりだった。
```
weekdays     = "24"                    → 火曜・木曜
ampm_per_day = {"2":"AM", "4":"AM"}    → どちらも午前のみ
nth_per_day  = {"2": 2}                → 火曜は「第2火曜」だけ
```
報告日 2026-08-18 は**第3火曜**（8/4=第1, 8/11=第2, 8/18=第3）。よって表示直前に `NONE` へ上書きされ、何度追加しても出なかった。
なお入力済みのバイタル値は `vitals` に正常保存されており、表示されないだけでデータ欠損は無かった。

### 対応（3コミット・すべて本番反映済み）
1. **`vital-add-today-fix-v1`**（本番 `a8b5945`）
   `weekdays` に今日の曜日が既にあるとサーバーが `ampm_per_day` を更新せず success を返す詰み状態を修正。
   モーダルの「本日表示中」判定を一覧と同じ基準にそろえ、JS側で `'NONE'` が上書きされないバグも修正。
   （実在する不具合だが**主因ではなかった**）
2. **`vital-add-id-fix-v1`**（本番 `64521a0`）
   追加モーダルが送る UUID を氏名経由で `patients.id` に解決。
   （これも実在する不具合だが**主因ではなかった**）
3. **`vital-daily-include-v1`**（本番 `83f6aef`）★本命
   **「本日の利用者を追加」を曜日の恒久設定ではなく【その日だけ】の記録に変更。あわせて 午前／午後／終日 の3択を追加。**

### `vital-daily-include-v1` の設計
- 新テーブル **`vital_daily_includes`**（DDL: `db/vital_daily_includes.sql`）。**DEV・本番とも作成済み**。
- `patient_id` は**画面と同じUUID**で持つ（`vital_daily_excludes` と同じ）。ID不一致が構造的に起きない。
- 判定を1か所に集約（`templates/vitals.html` の `todayStateOf()`）:
  ```
  今日だけ削除 ＞ 今日だけ追加(AM/PM/ALL) ＞ 曜日の設定(第N週含む)
  ```
  **その日だけの指定が最優先**なので、第N週指定も確実に上書きできる。
- 追加処理は `patient_visit_days` を**一切触らない** → 臨時追加が翌週以降に持ち越されない
  （旧実装は曜日を恒久追加していたため、体験・臨時利用の人が毎週出続けていた）。
- 新規「臨時」利用者は `patient_profiles` に作る（旧実装は `patients` にしか作らず、リロードで消えていた）。
- 日付切替時は `/api/vital_includes?date=` で取り直す。
- テーブル未作成でも表示は落ちない（追加時のみ明示エラー）。

### DEVでの実地検証（2026-08-18・全項目合格）
3択UIが出る（既定=終日）／追加すると一覧に出る／**リロードしても残る**／午前指定が効く（午後タブで非表示）／翌週に持ち越さない（翌火曜0件）。
本番でも現場が「消えずに追加できています」と確認。

### 孤児データについて（未処理・急がない）
`patient_id` が UUID の `patient_visit_days` 行が本番に9件ある。読まれないだけで害は無いため削除していない。
整理する場合は**中身を確認してから**。
```sql
select vd.* from patient_visit_days vd
left join patients p on p.facility_code = vd.facility_code and p.id::text = vd.patient_id::text
where vd.facility_code = 'cocokaraplus-5526' and p.id is null;
```

### 教訓
1. **診断SQLが「0件」でも、まず条件が正しいかを疑う**（特に facility_code）。
2. **コードだけで原因を断定しない。** 今回は実データを見るまで3回外した。早い段階でデータを取りに行くべきだった。
3. 「表示されない」系は、**書き込み先**と**読み取り元**のIDが一致しているかを最初に確認する。
4. 表示直前の上書き処理（`nth_per_day` のような）はDBをいくら直しても勝てない。**判定の優先順位を1か所に集約する**設計にする。

### 同日のその他の作業
- **音声入力のハルシネーション対策**（本番反映済み）: `halluc-guard-v2/v3`・`asr-homophone-v1`・`asr-name-hint-v2`・`asr-name-kanji-v5`。詳細は `SESSION_65_HANDOFF.md`。
- **上部トーストのセーフエリア対応**（`toast-safearea-v1`・DEVのみ・7箇所）: iPhoneのカメラに「保存しました！」が隠れる問題。
- **計画書・利用者情報シートの読み取り**（`sheet-ocr-v1/v2`・DEVのみ）: 基本情報6欄＋ICF付箋を複数枚まとめて読み取る。**`v2` の再検証が未実施**。

## Apple Developer Program 法人登録 完了（契約同意・$99支払い済み）2026-08-18  <!-- apple-enroll-paid-2026-08-18 -->

### 経過
- 2026-08-17 法人フォーム送信 → 登録ID **`WAVNW2S5G6`**（「現在登録を処理しています」表示）
- 2026-08-18 10:15 Apple から「登録手続きを完了してください」メール（`noreply-appledev@email.apple.com`）
  → 使用許諾契約（Apple Developer Program License Agreement）が発行される
- 2026-08-18 **使用許諾契約に同意・$99/年の支払いを完了**

### ★ 確定した値（次回のために必ず参照）
| 項目 | 値 |
|---|---|
| **Team ID（法人）** | **`6AX82WT38B`** ※契約書PDFのファイル名から判明 |
| Team ID（旧・無料Apple IDの個人チーム） | `BB7M7M88HC` ※Xcodeプロジェクトに設定済み。**法人チームへ切替が必要** |
| 登録ID（Enrollment ID） | `WAVNW2S5G6` |
| D-U-N-S番号 | `692505882` |
| 法人名 | `LIFE PLUS, LIMITED LIABILITY COMPANY` |
| 勤務先メール（Apple IDではない） | `hiro@lifeplusllc.com`（Zoho / mail.zoho.jp） |
| Bundle ID | `jp.lifeplus.tasukaru` |
| **Apple ID（アカウント責任者）** | ★未記録。`developer.apple.com/account` →「プロファイル」で確認して追記すること |

### 注意点
- **支払い後もD-U-N-S登録の電話番号にAppleから確認の電話が来ることがある。** 取り逃すと止まる。
- 支払い直後はアカウントが有効化されるまで時間がかかる場合がある（数時間〜48時間程度）。
- **年会費は自動更新。** 更新が止まると配布中のアプリが配信停止になる。ドメイン(`lifeplusllc.com`・更新期限2027/07/22)と
  Zohoメールもあわせて自動更新を維持すること。

### 次にやること（順番）
1. アカウントが有効になったことを `developer.apple.com/account` で確認（メンバーシップが表示される）。
2. **Xcodeの署名を法人チームへ切替**：`tasukaru-app/ios/App/App.xcodeproj` の
   `DEVELOPMENT_TEAM` を `BB7M7M88HC` → `6AX82WT38B` に変更（Xcode の Signing & Capabilities から選び直す）。
3. **App ID(Bundle ID `jp.lifeplus.tasukaru`)を Certificates, Identifiers & Profiles で登録**し、
   **Push Notifications capability を有効化**。
4. **APNs認証キー（`.p8`）を発行**（Keys → 新規 → Apple Push Notifications service）。
   - **`.p8` は1度しかダウンロードできない。** 紛失したら再発行になるので確実に保管する。
   - Key ID と Team ID (`6AX82WT38B`) も控える。**`.p8` の中身はチャット等に貼らない。**
5. 再検査アラームのプッシュ通知実装へ。
6. その後、非公開App配信(Unlisted)またはCustom App Distributionで施設スタッフへ配布。

### 契約について（参考・法的助言ではない）
- Apple Developer Program License Agreement は**交渉不可の定型契約**。全登録者が同一のものに同意する。
- TASUKARU は無料アプリ＋Stripeでの法人契約のため、アプリ内課金の別契約（Schedule 2）は現時点で不要の見込み。
- 介護記録は要配慮個人情報を含むため、Appleのプライバシー要件と国内の個人情報保護法の**両方**の遵守が必要。
  判断が必要な場面は専門家に相談すること。

---

## 再検査アラーム通知が【無音】だった件と、アラーム音の切替実装 2026-08-18  <!-- recheck-alarm-sound-v2 -->

### 症状
バイタルの再検査予約の通知が iPhone に**届くが音が鳴らない**。現場からは
「通知がポロンと控えめになるだけ。TASUKARUのときだけはしっかりアラームを鳴らしたい」との要望。

### 原因（7月からずっと壊れていた）
`templates/vitals.html` の `ln.schedule()` に `sound:'default'` を指定していた。
**Capacitor の `sound` は「アプリバンドル内のファイル名」を指定する項目**であり、
`default` という名前のファイルは存在しない。存在しないファイル名を指定すると
iOS は標準音にフォールバックせず**完全に無音**になる。
当初これを「マナーモードのせい」と誤診したが、それは誤り。

- `sound` の指定を外す → iOS の標準通知音が鳴る（`recheck-sound-fix-v1`）
- 長いアラーム音にしたい → `.wav` をアプリバンドルに入れて `sound:'ファイル名.wav'`

### 集中モード貫通
`interruptionLevel:'timeSensitive'` を指定（`recheck-timesensitive-v1`）。
Xcode 側で **「Time Sensitive Notifications」capability** の追加が必要。**Appleへの申請は不要**。
※消音（マナー）モードまで貫通させるには `critical` が必要で、こちらは **Appleへの申請と承認が必要**。
iOS 側の通知設定画面では「時間指定通知」ではなく**「即時通知」**というラベルで表示される。

### 用意したアラーム音（4種・各20秒 / 44.1kHz 16bit mono）
`_alarm_sounds/` に生成スクリプト（`gen_alarm2.py` / `gen_alarm3.py`）付きで保管。

| 記号 | ファイル | 音の性格 |
|---|---|---|
| A | `alarm_chime.wav` | やさしいチャイム |
| B | `alarm_soft.wav` | やわらかい二音 |
| C | `alarm_monitor.wav` | 患者モニター風 |
| D | `alarm_nursecall.wav` | ナースコール風（**既定**） |

iOS の通知音は**最長30秒**。それを超えると標準音に置き換えられる。

### 切替の実装（recheck-alarm-sound-v2）
`templates/vitals.html`。

- `RC_SOUNDS` に4音を定義。`_rcSound()` / `_rcSetSound()` で **`localStorage['rc_alarm_sound']` に端末ごと保存**。
  施設共通ではなく端末ごとにしたのは、DBのスキーマ変更（`vital_alert_settings` への列追加）を伴わず、
  夜勤・日勤で好みが違っても各自で選べるため。
- 本番の再検査スケジュールと15秒テスト通知の**両方**が `sound:_rcSound()` を参照する。
- UIは**アプリ内のみ**表示。画面上部の「🔔 通知を許可 / テスト」ボタンの下にプルダウンを置いた
  （`rc-alarm-panel`）。ブラウザでは音が確認できないため出さない。
- 選択を変えたら `checkRecheckAlarms()` を呼び、予約済み通知を**同じ通知idで上書きスケジュール**して
  新しい音に差し替える。

### 【重要】Xcode 側の作業（これをしないと無音のまま）
4つの `.wav` は `tasukaru-app/ios/App/App/` にコピー済み。Xcode で:

1. 左のファイル一覧の **`App` グループ**（青いプロジェクト直下の `App` フォルダ）に4ファイルをドラッグ
2. **「Copy items if needed」にチェック**、**Add to targets: `App` にチェック**
3. `App` ターゲット → **Build Phases → Copy Bundle Resources** に4ファイルが並んでいることを確認
4. アプリを再インストール

**バンドルに入っていないファイル名を指定すると iOS は無音**になる。4つとも入れること。

### Xcodeへの .wav 追加でハマった点（2026-08-18 実作業メモ）
- `tasukaru-app/ios/App/App/` に置いたファイルを **File → Add Files** すると、Xcode 16 のダイアログの
  Action が既定で **「Copy files to destination」**になっており、同名ファイルが既にあるため
  **`alarm_chime 2.wav` のように「 2」付きでコピー**されてしまう。この名前ではコードの
  `sound:'alarm_chime.wav'` と一致せず**無音**になる。
  → Action を **「Reference files in place」** に変え、**Targets の `App` にチェック**して Finish する。
- ダイアログの **Targets のチェックは既定で外れている**。外れたまま追加すると
  Copy Bundle Resources に入らず、やはり無音になる。
- Downloads など**リポジトリ外のファイルを追加すると `project.pbxproj` に絶対パスで記録される**
  （`path = "/Users/.../Downloads/alarm_chime.wav"; sourceTree = "<absolute>"`）。
  Downloads を整理した瞬間にビルドが壊れるため、`path = App/alarm_chime.wav; sourceTree = "<group>"`
  に修正済み。バックアップは `App.xcodeproj/project.pbxproj.bak_20260818`。
- 左の一覧が「⚠️ 問題一覧」になっていると Add Files の入れ先が見えない。
  **左上の一番左の📁アイコン**でファイル一覧に切り替えること。
- Xcode の **「Update to recommended settings」は実行しない**。
  `Enable User Script Sandboxing` が Capacitor のビルドスクリプトを壊すことがある。

**結果：4音とも iPhone で鳴ることを実機確認済み（2026-08-18）。**

---

## 掲示板に投稿できない（空投稿・見えない投稿）2026-08-18  <!-- board-empty-post-incident-2026-08-18 -->

現場から「掲示板に投稿が全くできない。画像も何もかも投稿できない。投稿するまでの操作はできるが投稿されていない」と報告。
調べた結果、**別々の2つの不具合が同時に起きていた**。

### 不具合① 空投稿（本命）: ServiceWorker が POST の body を落としていた

**症状**：掲示板に「投稿者名と時刻だけ・本文なし・カテゴリ未分類・画像なし」のカードが並ぶ。

**原因**：`static/sw.js`（2026-08-05 更新）の fetch ハンドラが、非GETリクエストを
`event.respondWith(fetch(event.request.clone()))` で**送り直していた**。
iOS（ホーム画面PWA / Safari）では、この送り直しで **multipart/form-data の body が丸ごと失われる**ことがある。
サーバ側では `request.form` / `request.files` が空になり、`api_board_create_post` は
`content=""` / `image_urls=[]` / `category_id=None` のまま insert に成功してしまう。
つまり **「投稿は成功したが中身が空」** という最悪の壊れ方をしていた。

**修正（`sw-post-passthrough-v1`）**：オンライン時は `event.respondWith` を使わず、
SW が非GETに一切介入しない。オフライン時のみ `/api/*` と `/input` をキューに積む。
`CACHE_VERSION` を `tasukaru-v31` → `tasukaru-v32` に更新。

```js
if (event.request.method !== 'GET') {
    if (navigator.onLine === false &&
        (url.pathname.startsWith('/api/') || url.pathname === '/input')) {
        event.respondWith(networkFirstWithOfflineQueue(event.request));
    }
    return;   // オンライン時はブラウザにそのまま送らせる
}
```

**併せて追加（`board-empty-post-guard-v1`）**：`api_board_create_post` で、本文・画像・音声・PDF が
**すべて空**なら保存せず 400 を返す。空投稿が二度と DB に入らないようにする保険。
Cloud Run のログに `[board] empty post blocked ... ct=... len=...` を出す。

### 不具合② 誰にも見えない投稿: 「メンションのみ」＋宛先ゼロ

**症状**：投稿は保存されているのに、投稿者本人以外の誰にも表示されない。

**原因**：投稿モーダルの公開範囲で「メンションのみ」を選び、宛先スタッフを1人も選ばずに投稿すると
`is_private = true` / `mention_names = []` になる。`/board` の可視判定は

```python
if p.get("is_private"):
    if my_name in (p.get("mention_names") or []) or p.get("staff_name") == my_name:
        posts.append(p)
```

なので、**宛先が空 = 投稿者本人しか見えない**投稿が成立してしまっていた。

**影響範囲は41件。** 最も古いのは id 67（2026年春頃）。つまりこの不具合は**数ヶ月前から続いていた**。
「投稿したのに誰も見てくれない」という現場の感覚はずっと正しかった。

**修正（`board-empty-mention-fix-v1`）**：
- `app.py`：`is_private and not mentions` なら `is_private = False` に倒す（サーバ側の最終防波堤）
- `templates/board.html`：投稿前に確認ダイアログを出す／`openPostModal()` で毎回「全員に公開」へリセット

**既存データの復旧**（実行済み・41件が全員に見えるようになった）：

```sql
update board_posts set is_private = false
where facility_code = 'cocokaraplus-5526'
  and is_private = true
  and (mention_names is null or mention_names::text in ('[]', 'null'));
```

### 調査でやってしまった遠回り（次回のために）

- **最初に「保存は動いている」と結論づけたのが誤り。** DBの直近40件を見て content が入っていたので
  正常と判断したが、**壊れた投稿は現場が削除済み**で、id 342〜348 が欠番になっていただけだった。
  **欠番＝壊れた投稿の痕跡**であり、これを見た時点で気づくべきだった。
- **決め手は現場のスクリーンショット。** 「名前だけ・未分類・本文なし」のカードが写った1枚で、
  「サーバに届いた時点で中身が空」と確定できた。**推測を重ねる前に画面を1枚もらうのが最短。**
- **「2件です」と断言して実際は41件だった。** id 336〜400 の範囲しか見ていないのに全体を語った。
  範囲を限定して調べたら、結論も範囲を明示すること。
- ブラウザから DEV / 本番へ直接 `fetch` で投稿して検証する方法が有効だった。
  ただし `/board?partial=1` は JSON（`\uXXXX` エスケープ）で返るので、
  日本語で検索するときは `JSON.parse` してから探すこと。

### 検証結果（DEV・本番とも合格 2026-08-18）

| 検証項目 | 結果 |
|---|---|
| ServiceWorker が v32・修正入り | ✅ |
| 中身が空の投稿 → 保存されず 400 | ✅ |
| 通常の投稿（本文あり） | ✅ 保存・表示 |
| 「メンションのみ」で宛先ゼロ | ✅ 全員公開に倒れて表示される |
| 画像つきの投稿 | ✅ 保存・画像URL付与 |

### 現場への周知（必須）

**アプリを一度完全に終了して開き直すこと。** ServiceWorker は古いものが端末に残り続けるため、
これをしないと修正版に入れ替わらない。

### 再検査アラームの「音なし」追加（`recheck-alarm-mute-v1`）

同時に `templates/vitals.html` のアラーム音の選択肢に「音なし（表示のみ）」を追加した。
Capacitor iOS は `sound` を渡さなければ `content.sound` を設定しないため、**通知は出るが無音**になる
（`LocalNotificationsPlugin.swift`: `if let sound = notification["sound"] as? String { content.sound = ... }`）。
選択値が `'none'` のときは `sound` キー自体を付けずに `schedule()` する。

---

## カレンダー予定のローカル通知＋全画面の「今日の予定」 2026-08-18  <!-- cal-notify-v1 -->

現場の要望：「カレンダーに入れた予定を、TASUKARUを閉じていても通知してほしい」。
再検査アラームと同じ **Capacitor のローカル通知**で実現した。**APNsもAppleへの申請も不要**
（iOS本体に予約を渡すので、アプリを完全終了していても鳴る）。

### 設計でいちばん重要な判断
通知の**予約はアプリを開いたときにしか入らない**。TOPページだけに置くと
「TOPを必ず経由する」前提になってしまうため、**`templates/base.html`（全ページ共通）に置いた**。
主要ページはすべて base.html を継承しているので、どの画面を開いても予約が同期される。
※ユーザーからの「必ずTOPを経由する仕様にしないと意味がない」という指摘で気づいた。

### サーバ側 `app.py`
- `GET /api/my_upcoming_events?days=N`（既定2＝今日＋明日）を新規追加
- 可視判定は `calendar_view()` と同じ（自分が作成／招待されている／施設の共有）
- **繰り返しはサーバ側で展開する。** DBに未来の行が無いため。
  `_cal_occurrence_start(ev, day)` が calendar.html の `__calcRepeatOccurrences()` と同じ規則を再現
  （daily/weekly/monthly/yearly、`repeat_until`、複数日またぎ、月末31日の非存在日）
- 取得は3クエリの和集合：(a) 期間内に始まる (b) `end_date` が期間に掛かる (c) `repeat_type != none`

### 端末側 `templates/base.html`
`cal-notify-v1`（`window.CAL_NOTIFY` に sync / getSound / setSound / isOn / setOn / test / requestPerm）
- 通知idは **1000000000 以上の名前空間**を使う。再検査アラーム（小さいid）と衝突させないため
- **`getPending()` で自分の名前空間のidだけ取り消す。** 再検査の予約には触らない
- `notify_before` が 0（＝通知なし）の予定は予約しない。過去になる通知も予約しない
- 終日・時刻なしの予定は **9:00 を基準**に `notify_before` を引く
- **最大55件**（iOSの保留中ローカル通知は1アプリ64件。再検査と共用するため余裕を残す）
- 音は `localStorage['cal_alarm_sound']`（端末ごと）。既定は `alarm_chime.wav`
  （再検査の既定 `alarm_nursecall.wav` と区別するため）。`'none'` のときは **sound キーごと付けない**
- ページを開くたびにポップアップが出ると鬱陶しいので、**通知許可はここでは要求しない**（`checkPermissions` のみ）

`cal-today-bar-v1`（全画面共通の「今日の予定」の細い帯）
- 予定0件の日は帯ごと出さないので、普段の画面の見た目は変わらない
- TOPページは `.user-info` の下へ移し既定で開く。他画面は既定で閉じる
- **貼り付く見出し（`position:sticky` かつ `top<=0`）のある画面では、その見出しの下へ移す。**
  掲示板でこれに気づかず、帯が `board-sticky-stack` の `::before` に塗りつぶされて見えなかった。
  **`elementFromPoint` は擬似要素を返さない**ので「当たっている＝見えている」と誤診しかけた。
  見えているかの確認はスクリーンショットで行うこと
- 5分だけ sessionStorage にキャッシュ（ページ遷移のたびにAPIを叩かない）

### `templates/calendar.html`
- アプリ内のみ、通知のON/OFF・音5種・15秒テストのパネルを表示（ブラウザでは音を確認できないので出さない）
- 予定の保存／削除の直後に `window.__calAfterChange()` で予約を取り直す

### 未対応・注意
- **他端末で今日追加された予定は、その端末でアプリを開くまで予約されない**（設計上の制約）
- **カレンダーの「通知」の初期値は「通知なし」のまま**（ユーザー判断。鳴らしたいものだけ選ぶ運用）。
  本番で確認したところ、今日6件・明日5件のうち通知設定ありは1件だけだった
- **iPhone実機での鳴動確認は未実施。** ブラウザでの検証までは合格

### DEVでの検証結果（2026-08-18・すべて合格）
API応答／繰り返し展開（7/28の1行が8/18として返る）／可視カレンダーの絞り込み／
TOP・掲示板・バイタルでの表示／0件時は非表示／
通知予約の中身（**`window.Capacitor` を偽物に差し替えて `schedule()` の引数を直接のぞいた**）／
「通知なし」「過去」「音なし」「OFF」の分岐／再検査の予約に触らないこと

---

## 休暇区分に「お盆休み」「正月休み」を追加 2026-08-19  <!-- leave-obon-newyear-v1 -->

コードは `obon` / `newyear`。**次の5か所すべてを揃えないと動かない。**

| ファイル | 場所 | 内容 |
|---|---|---|
| `app.py` | `_LEAVE_TYPES` | 大元。**ここに無いコードはサーバが弾く** |
| `app.py` | `_tc_leave_style` | 集計表のマスの色（お盆＝水色 / 正月＝紅梅色） |
| `app.py` | `_YS_LEAVE_FORM` | 様式Excelの印字。**両方とも「休」**（マスが狭いため。ユーザー判断） |
| `templates/timecard.html` | `TC_LEAVE_LABELS` | 打刻画面のプルダウン |
| `templates/admin_timecard_report.html` | `<select>` と `LV_COLOR` | 管理者の勤怠集計表 |

- 休暇区分を触るときは **`condolence` で grep するのが早い**（忌休のコードが5か所すべてに出てくる）
- `_to_delete/` とリポジトリ直下の `patch_leave_*.py` は過去の作業スクリプトの残骸。直す必要はない
- **TASUKARUに給与計算の機能は無い。** あるのは社労士向けの勤怠出力まで。
  「正社員は減給なし／パート・アルバイトはそのままお休み」の線引きは、
  出力された区分名と職員マスタの雇用形態を見て施設側・社労士が判断する
- DEVで保存できることを確認済み（Supabase側に値の制限は無かった）

---

## 作業環境のメモ 2026-08-19  <!-- env-note-2026-08-19 -->

- **Macを新しくした。** ローカルパスが `/Users/ZIMAX 1/dev` → **`/Users/ZIMAX/dev`** に変わった
  （半角スペースと「1」が無くなった。過去のREADMEのコマンドをそのまま貼ると動かない）
- この日は `device_bash` が起動せず、`device_stage_files` / `device_commit_files` も
  ブリッジ未接続で使えない時間帯があった。**ファイルの添付・ダウンロードも失敗した**
- **そのとき有効だった手段：`python3 -c '...'` の1行コマンドをユーザーに貼ってもらう。**
  - 日本語は `\uXXXX` エスケープにして、**コマンド全体をASCIIだけにする**
  - シェルは**シングルクォートで囲む**（中のPython文字列はダブルクォートを使う。
    アンカーにシングルクォートを含めないこと）
  - `assert s.count(a)==1` を必ず入れる。見つからなければ**ファイルに触れずに止まる**
  - **ただし長すぎるコマンドはチャットを通る途中で壊れる。** 1600字は通り、11000字は壊れた。
    長い文章を入れたいときはコマンドにせず、**VSCodeに直接貼り付けてもらうのが確実**
  - AI側で同じ内容を実際に実行して動作確認してから渡すこと
- ヒアドキュメント（`cat << EOF`）を使わない方針は今も有効

---
## 「今日の予定」の帯をTOPページだけに出す 2026-08-20  <!-- cal-today-bar-toponly-v1 -->

**完了・本番反映済み（2026-08-20）。**

### 経緯
`cal-today-bar-v1` では「今日の予定」の細い帯を**全画面共通**（`base.html`）に出していた。
実装中にユーザーから「必ずTOPページを経由する仕様にしないと意味がない」という指摘があり、
TOPを開かなくても目に入るようにしたためである。

その後**現場から「今日の予定はTOPページに表示するだけでいい」**という声が返ってきたので、
現場の声を優先してTOP限定に戻した。

### 変更（`templates/base.html` の1か所だけ）
`cal-today-bar-v1` のスクリプト内 `load()` の冒頭に1行足しただけ。

```js
  async function load(){
    // cal-today-bar-toponly-v1: 現場の要望で「今日の予定」の帯はTOPページだけに出す。
    //   通知の予約(cal-notify-v1)は全ページのままなので、どの画面を開いても予約は入る。
    if(!isTopPage()) return;
    bindToggle();
```

`isTopPage()` は同じスクリプト内に既にある（`location.pathname` が `''` または `/top` かを見る関数）。
TOP以外では帯のDOMも出ず、`/api/my_upcoming_events` も叩かなくなる。

### 【重要】絶対にやってはいけないこと
**通知の予約処理（`cal-notify-v1`）を `base.html` から動かさないこと。**
帯の表示と通知の予約は同じ `base.html` に入っているが、**役割がまったく違う**。

| 機能 | 置き場所 | 理由 |
|---|---|---|
| 通知の予約（`cal-notify-v1`） | **全ページのまま** | 予約はアプリを開いたときしか入らない。TOPだけにすると「TOPを開かないと鳴らない」に逆戻りする |
| 「今日の予定」の帯（`cal-today-bar-v1`） | **TOPだけ** | 現場の要望。見た目の話なのでTOPで足りる |

「TOP限定にする」という言葉に引きずられて通知側まで触ると、**アプリを閉じていても鳴るという
この機能の一番の価値が消える。**

### 検証（DEV・本番とも合格）
`/top` で帯が出る／`/board` `/vitals` `/calendar` で帯が出ない／TOP以外では
`my_upcoming_events` が呼ばれない。

---
# 2026-08-20 の作業  <!-- session-68-2026-08-20 -->

この日は **カレンダーと勤務予定をつなぐ**方向で5件を入れた。すべてDEV検証済み。
以下、次に触るAIが同じ判断をやり直さずに済むよう、**なぜそうしたか**まで残す。

## 0. この日の作業環境（先に読むこと）

- Macは新しいほうに移行済み。パスは **`/Users/ZIMAX/dev/kaigo-ai-app`**（スペースなし）。
  README内の古いコマンドにある `"/Users/ZIMAX 1/dev/..."` はもう存在しない。
- **`device_bash`（Mac側のシェル）は起動しない。** 「Workspace unavailable」で失敗する。
  ただし **`device_stage_files` / `device_commit_files` は動く。**
  → AIはファイルを直接読めるし、直接書き戻せる。**git だけユーザーに実行してもらう**流れで滞りなく進んだ。
- **AIがファイルを書き戻したら、必ず先に `git add` → `git commit` をしてもらうこと。**
  コミットせずに `git checkout` すると
  `error: Your local changes to the following files would be overwritten by checkout` で止まる。
  この日1回起きた。ユーザーを混乱させるので、書き戻しとコミットは必ずセットで案内する。
- **Cloud Run のデプロイは4〜6分かかることがある。** 「3〜5分」で見に行くとまだ古いままのことが多い。
  デプロイ完了の判定は、ページのHTMLにマーカー文字列が入ったかを見るのが確実。

```js
// 例：ブラウザのコンソールから。マーカーが入れば新しい版が出ている
const h = await fetch('/calendar',{credentials:'same-origin'}).then(r=>r.text());
h.includes('shift-cal-line-v1');
```

- Claude in Chrome の拡張は**不安定**だった。`Tab no longer exists` /
  `Couldn't determine which page this action targets` が頻発する。
  **`tabs_context_mcp` を呼び直して、返ってきた tabId をすぐ使う**と通る。
  同じ操作を3回試して駄目なら深追いせず、ユーザーにスクリーンショットを頼むほうが速い。

## 1. 「今日の予定」の帯をTOPページだけに（`cal-today-bar-toponly-v1`）— 完了・本番反映済み

`templates/base.html` の `load()` の冒頭に `if(!isTopPage()) return;` を足しただけ。

**通知の予約（`cal-notify-v1`）は base.html のまま動かしていない。**
帯（見た目）と通知の予約（機能）は同じファイルにあるが役割が違う。
予約はアプリを開いたときにしか入らないので、TOP限定にすると
「TOPを開かないと鳴らない」に逆戻りする。**ここを混同しないこと。**

## 2. カレンダーに勤務予定の「線」（`shift-cal-line-v1`）— 完了・本番反映済み

現場の要望「勤務予定を入れたらカレンダーにも出したい／片方を直したらもう片方も直る」への答え。

### いちばん重要な設計判断：勤務を calendar_events に**コピーしない**

最初は「勤務予定 → カレンダーの予定として複製し、双方向に同期する」案を検討したが採らなかった。
複製すると同期のズレを永久に気にする作りになる。
代わりに **`staff_shift_plan` をそのまま読んで線として描くだけ**にした。

- データが1つしか無いので、**カレンダーと勤務予定が食い違うことが原理的に起きない**
- 勤務予定を直せば線もすぐ変わる。「双方向同期」は**そもそも同期が要らない**形で満たした
- カレンダーの予定件数が増えない（本番は1日3件＋αで既に埋まっている。ここに勤務を足したら破綻していた）

### 見た目の決まり（ユーザー判断）

- **線は1日1本だけ。色は【自分が】出勤(緑 `#00897b`)か休み(オレンジ `#ef6c00`)か。**
- **職員ごとの色分けはしない。** 検討はしたが却下。
  現在の施設は6人だが、他の事業所に売るときは職員が多い。人数が増えると色が破綻する。
  線1本方式なら職員が何人でも見た目が変わらない（押したときの一覧が長くなるだけ）。
- 線の右端の小さい数字はその日の**出勤人数**。誰が出ているかは線を押して確認する。
- 押すと下からシートが出て、その日の**全員の勤務**（出勤は時刻つき／休みも一覧）が見える。
  自分の行には青枠と「自分」バッジ。閲覧は施設の全員に開放（ユーザー判断）。
  **編集側の本人限定（`shift-self-only-v1`）は従来どおりで、そこは変えていない。**

### 実装メモ

| 場所 | 内容 |
|---|---|
| `app.py` `_shift_month_map()` | その月の全職員の勤務を `{日付: {work:[{name,start,end}], off:[名前]}}` で返す |
| `app.py` `GET /api/shift/calendar_month` | 上を返す。`me` に自分が `work`/`off` かを添える（線の色に使う） |
| `templates/calendar.html` `window.SHIFT_LINE` | 取得・キャッシュ・線のHTML・シート・チップの切替 |

- **`staff_shift_plan` に行が無い日は `staff_shift_defaults` の曜日パターンで補う。**
  この補い方は `templates/kinmu_yotei.html` の `effDay()` と**同じ規則にすること**。
  ずれると画面ごとに違う勤務が出る。
- **`weekdays` は月曜起点。** `kinmu_yotei.html` の `wdOf()` が `(getUTCDay()+6)%7` のため。
  Python の `date.weekday()` も月曜0なのでそのまま使える。**ここを日曜起点と間違えると全部ずれる。**
- **線の onclick では必ず `event.stopPropagation()` する。**
  しないとセルの `onCellClick()` も走って予定一覧モーダルまで開く。
- **チップ `#shift-chip` に `data-id` を付けてはいけない。**
  `toggleCalendar()` が `.cal-chip[data-id]` を回して `activeCalIds` に無いものを inactive にするため、
  付けると他のカレンダーを操作するたびに勝手に消える。
- 線のON/OFFは `localStorage['cal_shift_line_on']`（端末ごと）。
- 線は5pxしかなく指で押しづらいので `::after` で上下3pxずつ当たり判定を広げてある。

### DEV検証（全項目合格）

線の色と人数／シートの中身／勤務予定を変えたら線も変わること／既存の予定クリック（一覧モーダル・編集）が
無傷なこと／月・週の切替／前月・翌月への移動／チップでのON/OFF。

## 3. 勤務予定の休みを勤怠の休み記録へ（`shift-leave-sync-v1`）— 完了・本番反映済み

現場の要望「休んだ後に出勤するとタイムカードで休みの種類を聞かれる。事前に入れておきたい」。

**なぜ効くか：** タイムカードの催促（`timecard_leave_self_check`）は
**`staff_leave_days` に行が無い日**を探しているだけ。先に入れておけば催促の対象から外れる。

### ★★ 絶対に壊してはいけないルール ★★

**タイムカードや勤怠集計表で【手で入れた休み】には、勤務予定から絶対に触らない。**

- 手入力の行は `staff_leave_days.source = 'manual'`（過去データは `NULL`）
- 勤務予定が作った行だけ `source = 'shift_plan'`。**更新・削除してよいのはこれだけ。**
- **勤務予定は「月まるごと保存」される**（30日分の cells が毎回飛んでくる）。
  この判定が無いと、勤務予定を保存するたびに現場が手で入れた休みが消える。**業務が壊れる。**

DEVで検証済み：手入力の忌休がある日を勤務予定で「有給」にして保存しても、
さらに「出勤」に戻しても、**忌休のまま一切変わらない。**

### 仕様

- 選べる区分は**一日休む7種**のみ：`paid` 有給 / `substitute` 振替休 / `condolence` 忌休 /
  `absence` 欠勤 / `off` 休み / `obon` お盆休み / `newyear` 正月休み
  （`_SHIFT_LEAVE_TYPES` に定義）
- **半休 `half` / 時間休 `hourly` / 対象外 `cancel` は出さない。**
  半休と時間休は「その日は出勤している」扱いで、勤務予定の「休み」と意味が食い違うため。
- **区分を選ばずに「休み」だけにした日は、何も登録しない。** 従来どおりタイムカードで聞かれる。
  勝手に区分が入る事故を避けるため（ユーザー判断）。
- **週コピー（`/api/shift/copy`）では区分をコピーしない。**
  「先週が有給だったから今週も有給」は明らかに違う。休み(status)だけ複製する。
- 区分の表示名は `/api/shift/leave_types` 経由で **`app.py` の `_LEAVE_TYPES` ひとつだけ**から取る。
  画面に直書きしない（休暇区分を足したときにそこだけ古くなるため。`leave-obon-newyear-v1` の教訓）。
- `/api/shift/save` は、対象範囲の既存の休み記録を**1回だけ**まとめて取ってからループする。
  セルごとに問い合わせると1ヶ月保存で30往復増える。

## 4. 既定の勤務時間を曜日ごとに（`shift-weekday-times-v1`）— 完了（本番はDDL待ち）

パートは「火は9-15、金は13-18」のように曜日で時間が違うため。

- `staff_shift_defaults.weekday_times (jsonb)` を追加。**月曜起点の7要素** `[{"start","end"}, ...]`
- **`start_time` / `end_time` は消さずに残す。** 古いデータや他の画面がまだ参照している。
  保存時は「チェックが入っている最初の曜日」の時間をそこに入れて後方互換を保つ（サーバ・画面とも同じ規則）。
- **曜日別が未設定の曜日は従来の共通時間に落ちる。** よって既存の設定は何も変わらない（DEVで確認済み）。
- 既定モーダルは「曜日ごとにチェック＋開始〜終了」の7行。
  **チェックを外した行は薄くするだけで、入れた時間は消さない**（また出勤に戻したとき使えるように）。
- 「すべて同じ時間にそろえる」ボタン＝チェックが入っている最初の曜日の時間を全曜日にコピー。

## 5. 勤務予定→カレンダーの戻る導線（`kinmu-back-to-cal-v1`）— 完了（本番未反映）

`templates/kinmu_yotei.html` の一番上に「← カレンダーに戻る」。
カレンダー側の「勤務予定を入力する」と同じ配色にして、対の導線だと分かるようにした。

## 6. この日に適用したDDL（本番の適用状況に注意）

```sql
-- shift-leave-sync-v1 : DEV・本番とも適用済み
alter table staff_shift_plan  add column if not exists leave_type text;
alter table staff_leave_days  add column if not exists source     text;

-- shift-weekday-times-v1 : DEVのみ適用済み。★本番は未適用★
alter table staff_shift_defaults add column if not exists weekday_times jsonb;
```

**本番へ出す順番を間違えないこと。DDL → デプロイ。**
列が無い状態で新しいコードが動くと `staff_shift_defaults` の upsert が失敗し、
**既定の設定が保存できなくなる。**

## 7. 見つけた既存バグ（今回とは無関係・未修正）

カレンダー画面のコンソールに、**以前からずっと**このエラーが出ている。

```
[CalendarBarConnect] error, fallback to original bars:
TypeError: Cannot read properties of undefined (reading 'top')
```

`templates/calendar.html` の `__calendarBarConnectRun()` 内の `run()` で、
`var gridRect = grid.getBoundingClientRect();` の**宣言が、それを使う `allCells.forEach` より後ろにある**。
var の巻き上げで `gridRect` が `undefined` のまま `gridRect.top` を読んで毎回落ちている。
try/catch で握りつぶされ「元のバー表示」にフォールバックしているため画面は壊れないが、
**複数日にまたがる予定を1本につなげる表示は、本番でもずっと効いていない。**

直すのは `var gridRect = ...` を forEach の前に移すだけ。ただし**複数日の予定の見た目が変わる**ので、
ユーザーに確認してから触ること（この日は報告のみで手を付けていない）。

## 8. 次にやること

1. **`shift-weekday-times-v1` の本番反映**（本番DDL → merge → push）。`kinmu-back-to-cal-v1` も一緒に入る。
2. **iPhone実機でのカレンダー通知の鳴動確認**（`cal-notify-v1`。まだ未実施）。
   実機アプリの接続先は **DEV**（`tasukaru-app/www/index.html` の `REMOTE` がDEVのURL）なので、
   実機テストはDEVで行うことになる。
3. **本番の勤務予定の実運用チェック。**
   本番のカレンダーには 8/10〜8/15 に「お盆休み」の予定が入っているが、
   **勤務予定表は出勤のまま**なので線は緑で出ている。
   勤務予定側で「休み＋お盆休み」を一括適用すれば、線もオレンジになり勤怠の休み記録にも入る。
   この機能の使いどころとして現場に案内するとよい。
4. **職員ごとの「既定の曜日パターン」が未設定だと全員が月〜金出勤として線が出る。**
   本番で線が実態と違う職員がいたら、その人の既定を設定してもらうのが早い。
5. その先は `SESSION_67_HANDOFF.md` の「3. 次にやること → 残タスク」の1〜9へ。

---
# 【設計】利用者セルフ評価（タブレット）  <!-- self-eval-design-2026-08-20 -->

**※第1段・第2段は実装済み（DEV検証済み・本番未反映）。実際に作って分かったことは
`self-eval-impl-2026-08-20` の節にある。両方読むこと。**

現場からの依頼：**評価のときに、利用者本人にタブレットで答えてもらう。**
2026-08-20 にユーザーと設計を詰め、そのまま第1段・第2段を実装した。
ここは「なぜそう設計したか」。実装の詳細と、作って分かった落とし穴は `self-eval-impl-2026-08-20` にある。

## 1. 何を作るか

利用者の**長期目標・短期目標**をもとにAIが質問を作り、利用者がタブレットで
**10段階の達成度**と**その理由**を答える。答えは職員が確認してから確定し、
そこで得られた新しい情報を**ICF付箋にフィードバック**する。
毎月くり返すことで、その利用者の情報が濃くなっていく。

## 2. 全体の流れ

```
[職員] 利用者を選ぶ
   ↓  AIが質問を作る（材料は「4.」を参照）
[職員] 質問を確認・修正 ……………………… ★途中保存できる
   ↓  開始 → タブレットを渡す（ここから利用者モード＝「5.」）
[利用者] 1問ずつ回答 ……………………………… ★1問ごとに自動保存（中断→再開できる）
   ↓  最後まで答えると status='answered'
   「ご回答ありがとうございました。」の表示でロック。解除コードを入れるまで何もできない
   ↓
   ┌──────────────────────┐
   │ 確認待ち  3件  ←一覧に出る │
   └──────────────────────┘
   ↓
[職員] 確認画面 ……………………………………… ★途中保存できる
   ・回答一覧（0〜10 と理由）／音声は再生と文字起こし
   ・AIが「今回わかったこと」をICF付箋の候補として提示
   ↓  採否を選んで確定 → status='confirmed'
   採用した付箋が ICFボードに載る
```

**★の3か所すべてに途中保存を入れること。**
ユーザーからの強い要望：「一旦保存できないと、次に他の作業ができなくなる」。
どこで中断しても他の作業に移れて、戻れば続きから再開できること。

## 3. 状態は3つだけ

| status | 意味 | 見え方 |
|---|---|---|
| `draft` | 利用者が回答している途中 | 「回答中」。職員が引き取れる |
| `answered` | 回答は終わった。**まだ確定していない** | **確認待ちの一覧に件数が出る。ここが要** |
| `confirmed` | 職員が目を通して確定した | 評価・モニタリングの材料として使える |

**`answered` のまま放置されないことが肝。**
既存の充足チェック（`/monitoring_check`, `record-check-suite-2026-07-24`）と同じ考え方で、
件数が目に入る場所に出す。

## 4. 質問をどう作るか（AI生成）

**材料はこの優先順で使う。**

| # | 材料 | 置き場所 | 何に使うか |
|---|---|---|---|
| 1 | 短期・長期目標（ICF3軸） | `patient_profiles.short_goal` / `long_goal` / `*_function` / `*_activity` / `*_participation` | 質問の骨格 |
| 2 | ICF付箋の**できない** | `patient_icf_stickies` (`polarity='cannot'`) | どの場面を掘るか |
| 3 | ICF付箋の**できる** | `patient_icf_stickies` (`polarity='can'`) | **どう聞くか**（前提を間違えない） |
| 4 | 環境の付箋 | `patient_icf_stickies` (`zone='environment'`) | 誰の手があったかを聞く |
| 5 | 趣味・好き・職歴 | `patient_profiles.hobbies` / `likes` / `job_history` | 「参加」の質問に使う |
| 6 | 病歴の直近 | `patient_medical_events` (`status='approved'`) | 「〜のあと変わったことは」 |
| 7 | 性質（AI推測） | `patient_personality_cache` | 言い回しの調整 |

### なぜ「できる」付箋が重要か（DEVの実例）

デモ利用者「青木 利夫」の付箋には `can:歩行器で50m歩行できる` と
`cannot:ズボンの着脱に一部介助が必要` がある。
目標が「トイレまで自分で行けるようになる」だとすると、

- 目標だけから作ると → 「トイレまで自分で行けるようになりましたか」（はい/いいえで終わる）
- 材料を見て作ると →
  - 「**歩行器を使って**、トイレまで行けましたか」（歩行器が使えることを知っている）
  - 「トイレで**ズボンの上げ下ろし**は ご自分でできましたか」（つまずく箇所を特定して聞く）
  - 「ご家族に手伝ってもらう場面はありましたか」（`can:家族の協力が得られる` から）

**「できる」ことを知らずに聞くと、できない前提の失礼な質問になる。** ここは必ず渡すこと。

### 抜けている領域を検知する

青木さんは `zone='participation'` の付箋が**0枚**だった。
ICF3軸で目標を持っている以上、評価も3軸で拾いたい。
**付箋が無い領域があれば「参加についての質問を足しますか？」と職員に提案する。**

### 質問文の決まり

- 一文一義。二重否定を使わない。専門用語（ADL・IADL・移乗など）を使わない
- 敬語。「〜できましたか」「〜になりましたか」
- 生成した質問は**必ず職員が確認してから**利用者に見せる。
  AIは事実誤認や失礼な聞き方を混ぜることがある。**そのまま出さない。**

## 5. ★★ 利用者モード（キオスク）— ここが一番重要 ★★

**利用者にタブレットを渡している間、他の画面へ行けないようにする。**
放置すると他の利用者の個人情報（ケース記録・掲示板）に到達できてしまう。
**画面を隠すだけでは防げない。** アドレスバーにURLを直打ちされたら素通りする。

### 第1層：サーバ側でロックする（これが本命）

開始時にセッションへ印を付け、**`before_request` ですべてのリクエストを止める。**

```python
# 許可するのはこれだけ。他は全部拒否
_KIOSK_ALLOW = ('/self-eval', '/api/self-eval', '/static/')

@app.before_request
def _kiosk_guard():
    if not session.get('kiosk_eval_id'):
        return
    p = request.path
    if p.startswith(_KIOSK_ALLOW):
        return
    # APIなら403、画面ならロック画面へ戻す
    if p.startswith('/api/'):
        return jsonify({"status": "error", "message": "利用者モード中です"}), 403
    return redirect('/self-eval/locked')
```

これがあれば、**アドレスバーに `/board` と打っても、別タブでTASUKARUを開いても開けない。**
第3層（端末）を破られても、TASUKARUの中の情報には到達できない。**必ず入れること。**

### 第2層：画面側

- 下のメニューもハンバーガーも出さない（`base.html` を継承しない専用テンプレートにする）
- ブラウザの「戻る」を `history.pushState` でトラップして評価画面から出さない
- 終わったら **「ご回答ありがとうございました。」の表示でロック**（ユーザー判断）。
  解除コードを入れるまで何もできない。利用者がさらに操作する余地を残さない
- **3分間操作がなければ自動でロック画面へ**（利用者が席を立った場合）

### 第3層：端末そのもの（アプリでは実装できない）

利用者がホームボタンでTASUKARU自体を抜けることは、Webアプリからは止められない。
**タブレットのOS機能で塞ぐ。運用手順として現場に案内する。**

- **iPad：アクセスガイド**（設定 → アクセシビリティ → アクセスガイド）。
  ホームまたは電源ボタン3回押しで開始。そのアプリから抜けられなくなり、パスコードでのみ解除
- Android：画面のピン留め

### 解除コード（ユーザー判断：施設共通の4桁）

- 管理者が設定画面で決める4桁。職員全員が覚えられ、利用者の前でも安全に入力できる
- **職員のログインパスワードは絶対に使わない。** 利用者の目の前で入力することになる
- **平文で保存しない。** ハッシュ化して `facilities` に持つ
- **試行回数を制限する**（4桁は総当たりが容易）。例：10回間違えたら60秒待たせる
- 解除したら誰がいつ解除したかをログに残す

## 6. ICFへのフィードバック（既存の仕組みに乗せる）

**新しい承認画面を作らない。** 既にあるものを使う。

- `icf_pending` テーブル ＝ ICF付箋の承認待ち
- `GET /api/patient-hub/icf/pending` で一覧、`POST /api/patient-hub/icf/pending/resolve` で approve/reject
- 承認すると `patient_icf_stickies` に入る。**重複判定 `_icf_dedup_key`（icf_code + polarity + text）が既にあるので同じ付箋は増えない**

評価の確認画面で職員が採否を決め、採用したものを付箋にする。
**二段階承認にしない**（現場の手間が増えるだけ）。重複判定だけは必ず通すこと。

例：「デイで他の方と話す機会は増えましたか」→「増えた。将棋の相手ができた」

- 候補：`participation` / `can` / 「他の利用者と将棋を通じた交流がある」
- 候補：`personal` / 「将棋が趣味」

承認すればICFボードに載り、**次の月の質問はその付箋も踏まえて作られる。**

## 7. 高齢者が迷わないUI（モックで合意済み）

- **10段階をそのまま出さない。** まず大きな3つ（できなかった／少しできた／できた）を選び、
  押したら「その中でどのくらいか」を3〜4個から選ぶ。**選択肢は常に3〜4個、結果は0〜10で取れる**
- 達成度は**円の塗り具合**で表す（白い円／半分／塗りつぶし）。**絵文字は使わない**
  （ユーザーから「子供っぽい」と指摘があった。大人向けの落ち着いた配色にすること）
- ひらがなだらけにしない。**適度に漢字を使う。** 高齢の方はむしろ漢字のほうが速く読める
- 1画面1問。質問文は約31px、ボタンは高さ100px前後
- **「読み上げる」ボタン**（`speechSynthesis`、`lang='ja-JP'`, `rate=0.85`）。追加費用なし
- 色だけで意味を伝えない（図・言葉・数字・色の4つで表す）
- **「とばす」を必ず用意する。** 書くのが負担な方に無理をさせない。とばした分は職員が後で聞く
- **選んだだけでは進まない。**「次へ」を押して初めて進む（触れただけで進むと不安になる）
- 「あと何問か」を常に出す
- 「できた」を選んだ場合は理由を聞かずに次へ進む（できている人に理由を聞くのは負担）
- 理由は「自分で書く／声で話す／とばす」の3択

## 8. データ設計（DDL・未適用）

```sql
-- 1回の実施＝1行
create table if not exists patient_self_evaluations (
  id                 uuid primary key default gen_random_uuid(),
  facility_code      text not null,
  patient_profile_id text not null,
  user_name          text,
  target_ym          text,                        -- 'YYYY-MM'
  status             text not null default 'draft', -- draft/answered/confirmed
  started_by         text,
  started_at         timestamptz default now(),
  answered_at        timestamptz,
  confirmed_by       text,
  confirmed_at       timestamptz,
  staff_note         text,
  created_at         timestamptz default now(),
  updated_at         timestamptz default now()
);
create index if not exists idx_pse_fac_status
  on patient_self_evaluations (facility_code, status);

-- 質問と回答（1問＝1行）
create table if not exists patient_self_eval_answers (
  id               uuid primary key default gen_random_uuid(),
  facility_code    text not null,
  evaluation_id    uuid not null,
  seq              integer not null,
  question         text not null,     -- 職員が確認・修正したあとの質問文
  goal_kind        text,              -- 'short' / 'long'
  icf_zone         text,              -- body/activity/participation/environment/personal
  source_note      text,              -- どの材料から作ったか（職員向け。利用者には出さない）
  score            integer,           -- 0〜10。未回答は null
  choice           text,              -- 'no' / 'mid' / 'ok'
  reason_mode      text,              -- 'write' / 'voice' / 'skip'
  reason_text      text,
  reason_audio_url text,
  answered_at      timestamptz,
  created_at       timestamptz default now(),
  updated_at       timestamptz default now()
);
create index if not exists idx_psea_eval on patient_self_eval_answers (evaluation_id, seq);

-- タブレットの解除コード（ハッシュで保存。平文で持たない）
alter table facilities add column if not exists kiosk_pin_hash text;
```

**適用は DEV → 本番の順。デプロイより先にDDL。**

## 9. 作る順番（3段階に分ける）

1. **第1段** — 質問生成＋利用者の回答＋**途中保存**＋**利用者モード（5.）**＋「確認待ち」の表示。
   これだけで現場は回る。**利用者モードは第1段に必ず含めること**（後回しにすると個人情報が漏れる）
2. **第2段** — 職員の確認画面＋ICF付箋へのフィードバック（6.）
3. **第3段** — 評価画面・モニタリング生成への反映、印刷

## 10. まだ決めていないこと

- 音声で答えた分をその場で文字にするか、録音を保存して職員が聞くか、両方か
- 回答結果を `patient_evaluations`（月次評価）にどう反映するか
- モニタリングのAI生成の材料に含めるか
- 印刷（利用者・家族に見せる形）が要るか
- 対象月をどう決めるか（評価月＝当月固定か、選べるようにするか）


---
# 利用者セルフ評価 実装メモ（第1段・第2段 完了）  <!-- self-eval-impl-2026-08-20 -->

設計は1つ上の `self-eval-design-2026-08-20` を先に読むこと。
ここには**実際に作って動かして分かったこと**を書く。

**状態：第1段・第2段ともDEVで検証済み。★本番は未反映★**

## 1. ファイル構成

| ファイル | 中身 |
|---|---|
| `self_eval_integration.py` | サーバ側すべて（`app.py` に足さずモジュールを分けた。app.pyは既に31,900行） |
| `templates/self_eval.html` | 職員側（一覧・質問の確認・回答の確認・ICF・次の目標） |
| `templates/self_eval_run.html` | 利用者側の回答画面。**`base.html` を継承しない**（ナビを出さないため） |
| `templates/self_eval_locked.html` | ロック画面（解除コード入力） |
| `db/self_eval.sql` | DDL |
| `app.py` | `register_self_eval_routes(app)` の2行だけ |

## 2. 適用したDDL（DEVのみ。★本番は未適用★）

```sql
-- 本体
create table if not exists patient_self_evaluations (...);
create table if not exists patient_self_eval_answers (...);
create table if not exists facility_kiosk_pins (...);
-- 第2段で追加（次の目標の案の途中保存用）
alter table patient_self_evaluations add column if not exists next_goal_draft text;
```

`db/self_eval.sql` に本体3つが入っている。`next_goal_draft` は後から足したので、
**本番へ出すときは `db/self_eval.sql` ＋ 上の alter を両方流すこと。**
Supabaseが「RLSを有効にするか」と聞いてきたら **「Run and enable RLS」**（緑）を選ぶ。
`_rls_fix.py`（2026-08）でサーバはservice_role接続に変更済みなので、RLS有効でも動く。

## 3. ★利用者モード（キオスク）の実装 — ここが要

`self_eval_integration.py` の `_kiosk_guard()`（`@app.before_request`）。

```python
_KIOSK_ALLOW_EXACT = (
    "/self-eval/run", "/self-eval/locked",
    "/api/self-eval/questions", "/api/self-eval/answer",
    "/api/self-eval/finish", "/api/self-eval/unlock",
)
_KIOSK_ALLOW_PREFIX = ("/static/",)
```

**★【完全一致】で持つこと。前方一致にしてはいけない。**
最初 `("/self-eval", "/api/self-eval", "/static/")` の前方一致で書いたところ、

- `/self-eval`（職員の一覧＝**利用者名がずらりと並ぶ画面**）が素通り
- `/api/self-eval/kiosk-pin/set`（解除コードの再設定）も素通り

という穴が開いていた。DEVで実際に叩いて見つけた。**必ず完全一致で書くこと。**

### DEVでの実測（2026-08-20・合格）

| 利用者モード中にアクセス | 結果 |
|---|---|
| `/board` `/top` | `/self-eval/locked` へリダイレクト |
| `/self-eval`（職員の一覧） | `/self-eval/locked` へリダイレクト |
| `/api/patients_cache` | 403 |
| `/api/self-eval/list` | 403 |
| `/api/self-eval/kiosk-pin/set` | 403 |
| `/self-eval/run` `/api/self-eval/questions` | 200（許可） |

解除後は元どおり全部通る。

### 解除コード
- 施設共通の4桁。`facility_kiosk_pins.pin_hash` に `sha256(facility_code + ':' + pin)` で保存。**平文で持たない**
- 10回間違えると60秒待たせる（プロセス内カウンタ。厳密でなくてよい）
- **職員が誤ってPCで「タブレットを渡す」を押しても復旧できる。**
  解除コードを入れるか、それも分からなければブラウザのCookieを消せばログアウトされて戻る
  （その場合もTASUKARUの中身は見えないままなので安全）

## 4. AIに投げるときの勘所（実際に失敗して直した記録）

**質問の生成（`/api/self-eval/create`）**

最初に出た質問にはこんな不良があった。プロンプトに悪い例つきで禁止を書いて直した。

| 出てしまったもの | なぜ駄目か |
|---|---|
| 「歩行器を使わずに歩いてみたいですか」 | **希望を聞く質問**。0〜10の達成度で答えられない |
| 「今日、他の方とお話しできましたか」 | **期間がぶれる**。1か月の振り返りなのに「今日」 |

→ 「達成度で答えられる質問だけ」「期間は【この1か月】に統一」を悪い例つきで明記した。

**ICF付箋の候補（`/api/self-eval/icf-suggest`）**

最初の版は**まったく使い物にならなかった**。

- 書き換え候補が0件。代わりに「入浴に見守りが必要」(cannot)が残ったまま
  「自分で体を洗える」(can)を**新規追加**しようとした＝矛盾した board になる
- 「他者との会話機会に介助が必要」のような**質問文をひっくり返しただけ**の付箋を7件も出した

→ **考える順番を強制**して直した。

```
手順1. まず「いま貼ってある付箋」を1枚ずつ見る
手順2. その付箋に対応する質問が回答の中にあるか探す
        例：付箋『入浴に見守りが必要』←→ 質問『お風呂で体を洗えましたか』
手順3. 対応する質問の達成度が【8以上】なら updates に入れて can に書き換える
        text も自然な日本語に直す（『入浴に見守りが必要』→『入浴を自分でできる』）
        4〜7 はまだ支障が残っているので書き換えない
手順4. 【最後に】既存では表せない新しい情報だけを stickies に入れる
```

あわせて「stickies に入れてはいけないもの」を悪い例つきで列挙した。
**この順番を崩すと、AIは点数から機械的に付箋を作り始める。**

直した結果（同じデータ）：書き換え1件が正しく出て、新規は7件→3件に減った。

**次の目標（`/api/self-eval/next-goal`）**

- 達成度8以上の項目があるときだけ動く
- **3案のうち必ず1案は『参加』へ広げる**ようプロンプトで強制している。
  介護では活動ができたら参加へ広げるのが本筋で、
  「歩ける」の次が「もっと歩ける」だけでは生活が広がらないため
- `tone` で作り直せる：`easier` / `concrete` / `longer`
- **作った案は `next_goal_draft` に保存**する。職員が他の仕事に呼ばれても消えない

## 5. ★途中保存（ユーザーが最も重視した点）

「一旦保存できないと、次に他の作業ができなくなる」という要望。3か所すべてに入れた。

| どこ | どう保存するか |
|---|---|
| 質問の確認・修正 | `/api/self-eval/questions/save`（「下書きを保存」ボタン） |
| 利用者の回答 | **1問ごとに** `/api/self-eval/answer`。中断しても**未回答の最初の質問から再開**する |
| 職員のメモ | `/api/self-eval/staff-note` |
| 次の目標の案 | `next_goal_draft`。開き直すと「前回つくった案が残っています」と出る |

## 6. 状態の流れ（実装どおり）

```
draft ──[利用者が最後まで回答]──> answered ──[職員が確定]──> confirmed
                                     ↑
                        ここで一覧の「確認待ち N件」に出る
```

`answered` のまま放置されないよう、**件数を画面の一番上に常に出している**（0件なら灰色）。

## 7. 残っている改善点（急がない）

1. **次の目標の提案が、達成した項目の続きになりにくい。**
   入浴を達成したのに、提案3件が全部「歩行・移動」だった。
   既存の cannot 付箋に引っ張られるため。「達成できた項目の続きを必ず1案入れる」を足せば直る
2. **音声の回答は「録音した」ことしか記録していない。** 文字起こしは未実装
3. 確定した評価をあとから編集する導線が無い（いまは確定したら読むだけ）
4. 対象月は作成時の当月固定。選べない

## 8. ★第4段（既存の評価との接続）— 実装済み・DEV検証済み

**既存の評価（`patient_evaluations`）との繋ぎ方。二極化も置き換えもしない。**

### 決めたこと
**セルフ評価は「評価の入力欄」ではなく「評価を書くための材料」に位置づける。**

理由は3つ。
1. **制度上、評価は専門職が行うもの。** 「訓練による変化」は機能訓練指導員が書く欄で、
   本人の主観だけでは埋まらない。**本人の声は評価そのものではなく、評価の根拠**
2. **入力経路を2つにすると必ず食い違う。**
   勤務予定と手入力の休みで実際に起きた問題と同じ。同じ項目に2つの入口を作らない
3. **繋ぎ先がすでにある。** `/api/evaluation/ai_fill` が
   `source_data` から「訓練による変化」「課題とその要因」を生成する仕組みを持っている

### 実装の方向

```
セルフ評価を確定
   ↓ 回答が整形されて patient_evaluations.source_data に【追記】される
     （職員が入れた記録・文字起こしと並ぶ。上書きしない）
   ↓
職員が評価画面で「AIで生成」を押す
   ↓ 本人の声も踏まえた文章が出る
   訓練による変化 / 課題とその要因
   ↓ 職員が読んで直して確定 ← 専門職の判断はここに残る
```

### 本人にしか答えられない3項目
`patient_evaluations` には **`satisfaction`（満足度）/ `service_appropriateness`（サービスの適切さ）
/ `new_requests_exist`（新たな要望の有無）** がある。
これらは本来ご本人に聞くべき項目で、いまは職員が推測で埋めている可能性が高い。
**セルフ評価で直接聞いて、そのまま埋める。** ここが一番きれいに繋がる。

「訓練による変化」も本人に聞ける形にできる。
例：「この1か月で、体を動かすのが前より楽になりましたか」→ 達成度で答えられる。

### 現場的な価値（ユーザーの狙い）
実地指導で「本人の意向をどのように確認したか」を問われたとき、
**いつ・どんな質問をして・本人が何と答えたか**が日付つきで残る。
評価が「書類のための作業」から「本人と一緒に振り返る場」に変わる。

### 実装したもの（2026-08-20）

#### (1) 毎回かならず聞く共通質問4問（`_COMMON_QUESTIONS`）

**★AIに作らせない。** 評価に必ず要る項目なので、サーバ側で固定して足している。
目標由来の質問は6問までに抑え、そのあとに共通4問。**合計10問**。

| goal_kind | 質問 | 対応する評価の欄 |
|---|---|---|
| `change` | この1か月で、体を動かすのが 前より楽になりましたか | 訓練による変化の材料 |
| `satisfy` | いまの デイサービスに 満足していますか | `satisfaction` |
| `fit` | いまの サービスの内容は ご自身に合っていると思いますか | `service_appropriateness` |
| `free` | これから してみたいことや、困っていることは ありますか | `new_requests_exist` / `_detail` |

**`free` だけ答え方が違う。** 達成度で答えられないので、回答画面では3択を出さず
そのまま「自分で書く／声で話す／とばす」を出す（`self_eval_run.html` の `isFree()`）。
見出しも「さいごに おたずねします」に変わる。

#### (2) 評価の元データへの取り込み（`POST /api/self-eval/to-evaluation`）

- `patient_evaluations.source_data` に **`【ご本人の回答】` の見出しつきで追記**する
- **★上書きしない。** 職員が書いた元データの後ろに足すだけ（DEVで確認済み）
- **★評価の行が無ければ作らない。** 必須項目が空の中途半端な評価を勝手に作らないため。
  代わりに `need_eval: true` を返して「先に評価画面で評価を作ってください」と案内する
- 2回目以降は `already: true` を返して「もう一度追加しますか？」と確認する（`force` で強行）

#### (3) 満足度など3欄の自動入力

セルフ評価の0〜10を、既存の評価の選択肢 **○△×** に直して入れる。
（`assessment.html` の選択肢はこの3つしかない。8以上=○ / 4〜7=△ / 0〜3=×）

| 評価の欄 | 入る値 |
|---|---|
| `satisfaction` サービスへの満足度 | ○ 満足 / △ やや / × 不満 |
| `service_appropriateness` サービス内容の適切性 | ○ 適切 / △ 概ね / × 要見直し |
| `new_requests_exist` 新規希望・要望 | あり / なし |
| `new_requests_detail` 希望・要望の詳細 | 本人が書いた文章そのまま |

**★職員がすでに入れている欄には触らない。空のときだけ埋める。**
勤務予定と休みのときと同じ考え方（手入力が常に勝つ）。

**★「してみたいこと」をとばした場合、「なし」とは入れない。**
とばしたのは「無い」ではなく「答えたくない・分からない」。
勝手に「なし」にすると事実と違う記録になる。空のままにして職員が面談で確認する。

### DEVでの検証結果（2026-08-20・すべて合格）

- 質問が10問（目標6＋共通4）になること、`free` の質問だけ3択が出ないこと
- 評価が無い月に取り込もうとすると `need_eval` で止まること
- 取り込み後、**職員が先に書いていた元データが残っていること**
- `satisfaction=○` `service_appropriateness=○` `new_requests_exist=あり`
  `new_requests_detail=「また畑仕事をやりたい」` が入ること
- **もう一度取り込むと `filled` が空になること**（＝すでに値がある欄に触っていない）


## 9. 次にやること

**第1段・第2段・第4段まで実装済み。DEVで検証済み。★本番は未反映★**

1. **本番反映**（DDL → merge → push）。DDLは2つ:
   - `db/self_eval.sql`
   - `alter table patient_self_evaluations add column if not exists next_goal_draft text;`
   Supabaseが聞いてきたら **「Run and enable RLS」**（緑）。
2. **第3段：印刷**（本人・家族に見せる形）。まだ手つかず
3. ICF 3軸の status 欄（`short_goal_activity_status` 等）も自動で埋められそう。
   選択肢は「達成 / 一部達成 / 未達成 / 目標継続」（`assessment.html` の 2071行付近）。
   セルフ評価は `goal_kind`(short/long) と `icf_zone` を持っているので対応づけできる。
   **ただし職員の判断を上書きしないこと。空のときだけ。**
4. 「7. 残っている改善点」の1〜4


## 10. ★本番の実データで見つかった問題と対策（2026-08-20 夜）

**DEVのデモデータでは1つも出なかった。現場の実データで試して初めて出た。**
次に同じことをするときは、**必ず本番の実データで何人か試すこと。**

### (1) AIが目標に無いことを勝手に聞いた ← 最も深刻

実際に起きたこと。目標欄が **「活動量増、家事」「転倒注意」「散歩」** のような
**短い言葉だけ**で、ICF付箋も0件だった利用者。AIが想像で具体化していた。

| 目標 | AIが作った質問 | 問題 |
|---|---|---|
| 活動量増、家事 | トイレまで行けましたか | トイレは目標に無い |
| 活動量増、家事 | 身支度をすることができましたか | 目標に無い |
| 転倒注意 | 足元がしっかりしていると感じられましたか | 目標から離れている |

**原因は2つ。**
1. 「6問以上8問以下」と指示していたため、材料不足を想像で埋めていた
2. 「目標に無いことを聞くな」と書いていなかった

**対策**（`_build_prompt` の後半）
- 上の実例をそのまま悪い例として書いた
- **トイレ・入浴・着替え・食事などの動作をAIから持ち出すことを禁止。**
  ただし ICF付箋にあれば使ってよい（実際に確認された事実なので）
- **「数合わせで質問を作らない。目標が2つなら2〜3問で十分」** に変更

### (2) 選択肢が質問に合っていなかった

「**いまのデイサービスに満足していますか**」に対して、
選択肢が「**できなかった／少し できた／できた**」だった。答えになっていない。

**対策**（`self_eval_run.html` の `CHOICE_SETS`）
質問の種類（`goal_kind`）ごとに選択肢の言い方を変える。

| goal_kind | 選択肢 | 2段目（0〜10の深掘り） |
|---|---|---|
| （目標由来） | できなかった／少し できた／できた | **出す** |
| `change` | 変わらない／少し 楽になった／楽になった | 出さない |
| `satisfy` | 満足していない／どちらとも いえない／満足している | 出さない |
| `fit` | 合っていない／どちらとも いえない／合っている | 出さない |

**満足度などは3段階で十分**（既存の評価も ○△× の3段階）。
3択を押した時点で点数を 2 / 5 / 9 に確定させ、深掘りを出さない。利用者の負担も減る。

### (3) 質問の語尾がそろわない

「他の方とお話しする**機会はありましたか**」→「できた」では答えにならない。
**プロンプトで指示してもAIは完全には従わなかった**（実測）。

**対策：プロンプト＋サーバ側の機械的な置換の二段構え**（`_fix_tail`）
- 「機会はありましたか」「ことはありましたか」等 → 「ことができましたか」
- **置換するのは誤解の余地がない言い回しだけ。** 無理に直すと日本語が壊れる
- 取りこぼしは職員が直す。**確認画面に「文の終わりが〜できましたかになっているか」と明示**

### (4) 似た質問が並ぶ

「トイレまで歩けましたか」「食堂まで歩けましたか」「廊下を歩けましたか」のように、
同じ動作を場所を変えて何度も聞いていた。高齢の方は「さっきも聞かれた」と混乱する。
→ プロンプトに悪い例つきで「まとめて1問にする」を追加。

### (5) スマホでの表示崩れ

- 画面の一番上が**時計・電波表示と重なって切れていた**
  → `body` の padding に `env(safe-area-inset-top)` を足した
- フッターの案内文が**縦書きのように潰れ、「次へ」が画面外**に出ていた
  → `@media (max-width:700px)` で案内文を隠し、ボタンを画面内に収めた
- 職員画面の解除コード欄で「設定する」ボタンが画面外に出ていた → 縦積みにした

### (6) 足りなかった機能：削除

**間違えて作った評価を消せなかった。** 現場では必ず起きる。
→ `POST /api/self-eval/delete` を追加。回答も一緒に消す。
確定済み（confirmed）は**管理者のみ**（記録として残すべきもの）。
利用者モード中は許可URLに入れていないので届かない。

### (7) 読み上げの改善

端末の**日本語の声を明示的に選ぶ**ようにした（Kyoko / Otoya / Google日本語）。
指定しないと機械的な声や英語の声で読まれることがある。
`speechSynthesis.onvoiceschanged` で選び直す（声の一覧は非同期で用意される）。
速度は 0.82。記号（「」〜・）は読み上げないよう整形する。

### (8) ★未対応：ペンでの手書き入力

**利用者はタブレットでフリック入力ができない。** これは機能不全に近い。
「自分で書く」を **canvas で手書き → 画像として保存** に変える必要がある。

必要な作業（次回）
- `alter table patient_self_eval_answers add column if not exists reason_image_url text;`
- canvas（ペン・指の両対応）→ PNG → サーバへ → Supabase Storage → URL を保存
- 職員の確認画面で画像を表示する
- 当面の運用：**職員が代わりに入力する**、または「声で話す」を使う

★この宿題は 2026-08-21 に対応済み。下の「11.」を読むこと。

---

## 11. 読み上げ・手書き・聞き取りモード（2026-08-21）

前節(10)の「(7)読み上げ」「(8)未対応：ペンでの手書き」への回答と、
現場から追加で出た「職員が聞き取るモード」。3つとも同じ日に入れた。

### (1) 読み上げを Google Cloud Text-to-Speech に替えた  <!-- self-eval-tts-v1 -->

ブラウザ標準の読み上げ（`speechSynthesis`）は、端末の声を選び直しても
**機械的なまま**だった。高齢の方に聞かせるには足りない、というのが現場の判断。

- `requirements.txt` に `google-cloud-texttospeech==2.27.0`
- `POST /api/self-eval/tts` … Neural2-B / `speaking_rate=0.92` / MP3
- 認証は **Cloud Run のサービスアカウント（ADC）**。鍵ファイルは置かない
- Google Cloud 側で **Cloud Text-to-Speech API を有効化**しておくこと
  （プロジェクト: TASUKARU-production）
- 同じ文は**プロセス内に300件までキャッシュ**する。再デプロイで消えてよい
- 料金：Neural2 は月100万文字まで無料。質問1問50文字なら桁がちがう

★**失敗しても画面は壊れない。** 画面側が失敗を検知して、
　従来のブラウザ読み上げ（`speakLocal`）に戻す。API未有効でも運用は続く。
　この作りにしておかないと、課金停止や権限のズレで**現場が止まる**。

### (2) ペンでの手書き入力  <!-- self-eval-pen-v1 -->

**利用者はタブレットのフリック入力ができない。** 前節(8)の宿題。
「自分で書く」を、紙に書くのと同じ **canvas での手書き → 画像保存** に変えた。

DDL（列名は設計時の `reason_image_url` から変更した。理由は下記）
```sql
alter table patient_self_eval_answers
  add column if not exists reason_image_path text;
```

★**公開URLにしなかった。** ここは設計を変えた点。
　手書きの中身は本人が書いた**要配慮個人情報**。`get_public_url()` を使うと
　URLを知っている人なら誰でも見られる。だからDBには**保管場所のパスだけ**を持ち、
　表示は職員ログインが要る `/self-eval/reason-image/<設問ID>` を通す。
　列名を `..._url` ではなく `..._path` にしたのは、あとで読む人が
　「URLが入っている」と誤解しないため。

| 追加したもの | 何をする |
|---|---|
| `POST /api/self-eval/answer-image` | 手書きPNGを受け取り Storage へ。★キオスク許可URL |
| `GET /self-eval/reason-image/<id>` | 職員に画像を見せる。★ログイン必須・キオスクからは開けない |
| `POST /api/self-eval/answer-ocr` | AIに手書きを読ませる。**保存はしない** |
| `POST /api/self-eval/answer-reason` | 職員が直した文字を保存する |

- 保存先は既存の **`case-photos` バケット流用**（新設すると権限設定をやり直しになる）。
  パスは `{施設コード}/self-eval/{評価ID}/{設問ID}.png`
- 受け取り側で **PNGの先頭8バイトを確認**し、2MBを超えたら弾く
- **他人の設問に書き込めないよう、evaluation_id と施設コードで必ず突き合わせる**
- 画面側：`pointerdown/move/up` なのでペン・指・マウスのどれでも動く。
  `touch-action:none` が無いと、指で書いたときに画面ごとスクロールする
- 線は「点の並び」で保持する。画面の向きが変わっても描き直せる
- 書き出しは**白い紙を敷いてから線を写す**。透明のままだと端末によって真っ黒に見える
- 保存に失敗しても「次へ」は止めない。**手書きは補足で、点数のほうが本体**

★AIに渡すときの扱い
　手書きがあって、まだ職員が文字にしていない状態では
　「**手書きで回答あり（内容は不明）**」とだけ伝える。
　中身が分からないのに、AIに想像で埋めさせない。前節(1)の失敗と同じ轍。

★AIの読み取りは**必ず職員が直してから保存**する。手書きは必ず読み違える。
　`answer-ocr` は返すだけで保存しない。保存は `answer-reason`（職員が押す）。

### (3) 実機で出た表示崩れ ← 組み方そのものの問題  <!-- self-eval-fit-v1 -->

**「できた」を選ぶと上にずれて質問文が切れ、下に戻しても戻らない。」**

原因は `body` を **上下中央ぞろえ（flex + align-items:center）** にしていたこと。
中身が画面より高くなると、**はみ出した上側だけが取り戻せなくなる**。
これはこの組み方の弱点で、スクロール位置をいじっても直らない。

対策は2つ。両方入れた。

1. **画面自体をスクロールさせない。** `html,body{overflow:hidden}` にして
   `.tab{max-height:100%}`。スクロールするのは `.body` の中だけ。
   上の名前・進捗と下の「次へ」は常に見える
2. **3択を選んだら3択を1行にたたむ**（`fold()` / `unfold()` / `unpick()`）。
   3択と10段階を同時に出すと、そもそも縦に長すぎた。
   「できた ○ ／ 選び直す」の1行に変え、質問文が画面から追い出されないようにした

`scrollIntoView` は**やめた**。スクロールで解決しようとしたのが遠回りだった。

### (4) 職員が聞き取って入力するモード  <!-- self-eval-interview-v1 -->

現場からの追加依頼。**タブレットを渡せない方が必ずいる。**
画面操作が難しい、目が見えにくい、手がふるえる、その日の体調。

これまではそういう方の評価を職員が頭の中で考えて書いていた。
本当の困りごとは「**何を聞けばよいかが職員によってばらつく**」ことだった。

→ **利用者モードと同じ質問**を職員の画面に順番に出す。
　 職員が読み上げて聞き、聞いた答えをその場で入れる。

| 追加したもの | 何をする |
|---|---|
| `GET /self-eval/interview?id=` | 聞き取り画面（`self_eval_interview.html`） |
| `POST /api/self-eval/answer-staff` | 1問ぶん保存。`reason_mode='staff'` |
| `POST /api/self-eval/finish-staff` | 聞き取り終了 → `status='answered'` |

★**キオスクの許可URLに入れない。** 職員が自分の端末で使うもの。
　利用者モード中のタブレットから開こうとしてもロック画面に戻る。

★**保存先も質問も利用者モードと同じ。** だから、そのあとの
　ICFへの反映・次の目標づくり・既存評価への転記は**共通のものがそのまま使える**。
　入力経路を2つ作っても、**出口は1つ**にしておくこと。

画面の作りで意識したこと
- 質問は**大きく出す**（職員が読み上げるため）
- 質問の下に「**この質問のもと**」（source_note）を出す。話を広げやすくなる
- 「聞けなかった」ボタンを置く。**無理に聞き出させない**
- **1問ごとに保存**。職員は途中で必ず呼ばれる。開き直すと**続きから**始まる
- `base.html` の本文は `.page-wrapper` が持っている。
  `window.scrollTo` では動かない（`ivTop()` で `.page-wrapper.scrollTop` を戻す）

### (5) ICFの状態欄を自動で埋める  <!-- self-eval-status-v1 -->

職員が回答を見ながら**手で6か所選んでいた**ところ。点数はもう本人からもらっている。

`POST /api/self-eval/to-evaluation` に追加した。埋めるのは `patient_evaluations` の

| 介護区分 | 埋める欄 |
|---|---|
| 要介護 | `short_goal_{function,activity,participation}_status` と `long_…`（計6） |
| 要支援・事業対象者 | `short_goal_status` / `long_goal_status`（計2） |
| 空 | **何もしない**（どちらの欄を使うか決められないため） |

点数 → 状態は ○△× と同じしきい値（8以上＝達成／4以上＝一部達成／それ未満＝未達成）。
`goal_kind`（short/long）と `icf_zone`（body→機能 / activity→活動 / participation→参加）で振り分ける。

★**同じ軸に質問が複数あるときは平均で決める。**
　いちばん低い点で決めない。1問できなかっただけで「未達成」になるのは実態より厳しい。

★**矛盾を作らない。**
　短期が「達成」でないのに長期を「達成」にしない（一部達成に落とす）。
　この組み合わせは `assessment.html` 自身が警告を出す。そこまで言い切らないほうがいい。

★**空のときだけ埋める。** 職員が選んだものには触らない。満足度などと同じ考え方。
　あくまで下書きで、評価画面でいつでも変えられる。画面の案内文にもそう書いた。

### (6) 印刷は作らない（2026-08-21 現場判断）

設計時に「第3段：印刷（本人・家族に見せる形）」を置いていたが、
**現場から不要と回答があった。** 作らないこと。
必要になったら、そのとき改めて何のために出すのかを聞くところから始める。

### (7) 次に残っていること

- 聞き取りモードでの**音声入力**（職員が話した内容をそのまま文字に）は未着手
- iPhone実機でのカレンダー通知の鳴動確認（`cal-notify-v1`）
- `CalendarBarConnect` の `gridRect` 宣言順バグ（複数日の連結バーがずっと出ていない）
- SESSION_67 の残タスク（Stripe本番Webhook・CRON_TOKEN・Apple/APNs・Android内部テスト ほか）


---

## 運行画面の見せ方を選べるようにした 2026-08-21  <!-- soge-view-v1 -->

現場の要望。それまでは **車両 → 便** の1通りだけだった。
これを **便 → 車両** でも見られるようにし、切り替えられるようにした。

### なぜ2通り必要か

見たいものが人によって違う。どちらが正しいということはない。

| 誰が | 見たいもの | 向いている見せ方 |
|---|---|---|
| 運転手 | 自分の車が今日どう回るか | **車両 → 便**（従来） |
| 送迎を組む人・管理者 | 迎え便に何台出ているか | **便 → 車両**（今回追加） |

### 実装（`templates/soge_run.html` のみ。サーバもDBも変更なし）

- `state.mode` … `'vehicle'`（既定）／`'trip'`
- **端末ごとに `localStorage['soge_run_mode']` に覚える。**
  運転手はいつも車両から、組む人はいつも便から使う。毎回選び直させない
- タブは上下2段のまま。**中身が入れ替わるだけ**（1段目と2段目のどちらに何を出すかを変える）
- 色の意味は変えない。**車両＝青（`.sr-tab`）／便＝緑（`.sr-ttab`）**。
  位置ではなく中身でクラスを決めているので、入れ替えても意味が保たれる
- 便の並び順は `tripOrder()`：迎え便 → 送り便/迎え便 → 送り便 → その他 → **臨時便（必ず最後）**
- 便から見るとき、**その便を持っていない車両はタブに出さない**（出ていない車を選ばせない）

### ★つまずきやすい点

**メーターの「出発㎞の目安」は、同じ車の1つ前の便から取ること。**
便から見るモードでは画面上の並びが車をまたぐので、
「1つ前のタブ」から取ると**別の車の㎞**を目安として出してしまう。
`sel.ti`（その車の中での便の位置）を持ち回って解決している。

便を変えたときは**車両を先頭に戻す**。前の便の3台目が、この便にもあるとは限らない。

---

## 送迎の3件（確定・休み連絡・利用中止） 2026-08-21  <!-- soge-lock-v1 / soge-leave-v1 -->

### (1) ★「配車を直したのに運行表に反映されない」の正体

**不具合ではなく、意図的な作りだった。** `soge_materialize_day()` は
`soge_days` にその日の行が1つでもあれば、何もせず戻っていた。

つまり **その日を一度でも運行画面で開いた瞬間に配車表からコピーされ、
以降は配車表を直しても永久に反映されない。** 翌日の予定を先に覗いただけでも固まる。
走り出したあとに表が変わる事故を防ぐ意図だったが、現場には不具合に見えていた。

**直し方（ユーザー判断）：止めるかどうかを【人が決める】ようにした。**

| その日の状態 | 運行画面を開いたとき |
|---|---|
| 未確定・打刻なし | **配車表から作り直す**（＝配車の直しがそのまま出る） |
| 未確定・打刻あり | 自動では作り直さない。「配車表から作り直す」ボタンを出す（打刻と臨時便が消える警告つき） |
| **確定済み** | 何があっても作り直さない |

- 確定は `soge_day_locks`（`db/soge_lock.sql`）。**行が有る＝確定。無い＝未確定。**
- `POST /api/soge/run/lock` … 確定する／解除する
- `POST /api/soge/run/rebuild` … 明示的に作り直す（**確定済みの日は拒否する**。最後の砦）
- 画面の一番上に確定バーを出す（`renderLock()`）

★★**過ぎた日は、確定の有無に関わらず絶対に作り直さない。**
　過去の運行表は「実際にどう走ったか」の記録で、月の記録表（`/soge/print`）の元にもなる。
　打刻が1つも無い日（誰も押し忘れた日）でも、今の配車表で書き換えたら**記録の改ざん**になる。
　最初の実装ではここが抜けていて、**過去の日を開いただけで書き換わる穴**があった。
　`/api/soge/run/rebuild` も過去日は拒否する。画面には「過ぎた日」とだけ出す。

★**`_soge_day_locked()` は、表が読めないときに「確定」を返す。**
　読めないことを理由に、走っている表を作り直してしまうほうが危ないため。
　DDLを流す前にデプロイしても、これまでどおり「作り直さない」に倒れるだけで壊れない。

### (2) 休み連絡の方を運行表で「お休み」にする  <!-- soge-leave-v1 -->

**消さずに残して「お休み」と出す**（ユーザー判断）。消してしまうと、運転手が
「もともと乗らない」のか「休みなのか」を区別できない。

- `_soge_leave_names(supabase, f_code, date)` … その日に休み連絡がある利用者名
- **DBには書かない。** 連絡が取り消されたら、そのまま元に戻ってほしいため。
  手で付けた欠席（✕）は `soge_stops.is_absent`、休み連絡は `is_leave` として**別に持つ**
- ★飛び飛びの休みは `calendar_events` が正。記録の start〜end を機械展開すると
  間の休みでない日まで休みになる。**`leave-scattered-fix-v1` とまったく同じ規則**を使っている。
  規則を2つに分けると、片方だけ直したときに必ず食い違う

### (3) 利用を中止した方を、中止日より後に出さない

判定は**すでにあった** `patient_active_on(p, date_str)`（`patient-active-v1`）。
入っていなかったのは送迎の2か所だけだったので、そこに足した。

- `soge_materialize_day()` … 作るときに落とす（`_active_today`）
- `_soge_run_payload()` … **すでに作られていた表からも外す**（確定済みの日でも）

★**過去をさかのぼるときはその日を基準に判定するので、中止前はちゃんと出る。**
　「中止前の検索には表示する」という要望はこれで満たされる。

★**記録表（`/soge/print`）には手を入れていない。** あれは実際に走った記録であって、
　あとから人を消してよいものではない。

---

## 作業の受け渡しについて（2026-08-20 に解決済み）  <!-- handoff-note-2026-08-19 -->

**この節の下半分（8/19時点の記述）はもう当てはまらない。8/20 の状況が正しい。**

### 2026-08-20 時点（いまはこれ）
- **`device_stage_files` / `device_commit_files` は動く。** AIがMacのファイルを直接読み書きできる。
- **`device_bash`（Mac側のシェル）だけ起動しない。** 「Workspace unavailable」で失敗する。
  → **git はユーザーに実行してもらう。** コマンドを丸ごと提示すれば滞りなく進む。
- **AIが書き戻したら、必ず先に `git add` → `git commit`。**
  コミットせずに `git checkout` すると
  `error: Your local changes to the following files would be overwritten by checkout` で止まる。

### 2026-08-19 時点（解決済み・記録として残す）
- Macを新しくした直後は、`device_bash` / `device_stage_files` / `device_commit_files` が
  すべて「デバイスがブリッジに接続されていません」で失敗した。
  チャットを開始した時点のMac（＝古いMac）にセッションが紐づいていたため。
- **新しいMacで新しいチャットを始めたら直った。** これが対処法。
- 直接書き込みが使えないときの代替手段は
  `env-note-2026-08-19` の節にまとめてある（`python3 -c` の1行コマンド／VSCodeへの直接貼り付け）。

---
## 【重要】新しいチャットを始めるAIへ（2026-08-20 更新）  <!-- session-67-entrypoint -->

**まず `SESSION_67_HANDOFF.md` を読むこと。** 2026-08-18 時点の作業状況・
守るべきルール（セキュリティ、ファイル受け渡しの手順、ユーザーへの説明の仕方）が全部書いてある。
**そのうえで、このREADMEの `session-68-2026-08-20` の節を読むこと。**
8/19〜8/20 で環境も進捗も変わっているので、そちらが最新。
ユーザー（岸本さん）に同じ説明を繰り返させないこと。

要点だけここにも書く。

### セキュリティ
- **APIキー・トークン・シークレット・`.p8` の中身・パスワードは、チャットにもコードにも一切出力しない。**
- 言及が必要なときは必ず伏せ字にする（例：`AIza••••••••3f2a` / `sk_live_••••••••`）。
- キーは Cloud Run の環境変数と Supabase 側にのみ置く。README にもコードにも書かない。
- ユーザーがキーを貼ってしまったら、その場で指摘して再発行を勧め、以後繰り返さない。

### ファイルの受け渡し（2026-08-20 時点）
- **ローカルパスは `/Users/ZIMAX/dev/kaigo-ai-app`。** 古い `"/Users/ZIMAX 1/dev/..."` はもう無い。
- **`device_stage_files` / `device_commit_files` は動く。** AIが直接読み書きできる。
- **`device_bash`（Mac側シェル）は起動しない。** git はユーザーに実行してもらう（コマンドを丸ごと渡す）。
- **書き戻したら必ず `git add` → `git commit` をしてもらう。**
  コミット前に `git checkout` すると「local changes would be overwritten」で止まる。
- git が `index.lock` で止まったら `rm -f .git/index.lock .git/HEAD.lock` を先頭に付ける。
- **Cloud Run のデプロイは4〜6分。** マーカー文字列がHTMLに入ったかで完了を判定する。

### 進め方
- ユーザーはエンジニアではない。**一度に1タスク、5ステップ以内、具体的な操作手順で。**
- **推測で断定しない。** DBの実データ・スクリーンショット・ログで裏を取ってから結論を言う。
- 調査範囲を限定したら、結論にもその範囲を明示する。
- **本番の施設コードは `cocokaraplus-5526`。** 診断SQLを書く前に必ず確認する。
- **DDLが要る変更は、必ず「本番DDL → デプロイ」の順で案内する。** 逆にすると保存が全部落ちる。

### 次の最優先タスク（2026-08-20 時点）
1. **`shift-weekday-times-v1` の本番反映。** ★本番DDLがまだ★
   ```sql
   alter table staff_shift_defaults add column if not exists weekday_times jsonb;
   ```
   これを本番Supabase（`abvglnkwtdeoaazyqwyd`）で実行してから merge → push。
   `kinmu-back-to-cal-v1` も一緒に本番へ入る。
2. **iPhone実機でのカレンダー通知の鳴動確認**（未実施）。`cal-notify-v1` の節を参照。
   実機アプリの接続先は**DEV**なので、テストはDEVで行うことになる。

3. **利用者セルフ評価（タブレット）— ★本番反映済み。現場で調整中★**
   **次にやるのは「ペンでの手書き入力」**（利用者がフリック入力できず、いま機能不全）。
   手順は `self-eval-impl-2026-08-20` の「10.(8)」。
   実データで見つかった問題と対策は同じ節の「10.」に全部書いてある。**必ず読むこと。**
   （以下は本番反映のときの手順。反映は 2026-08-20 に完了済み）
   本番Supabaseで `db/self_eval.sql` と
   `alter table patient_self_evaluations add column if not exists next_goal_draft text;`
   を流してから merge → push すること（DDLが先）。
   設計は `self-eval-design-2026-08-20`、実装の詳細と落とし穴は `self-eval-impl-2026-08-20`。
   その先は第3段（評価・モニタリングへの反映）→ 第4段（既存評価との接続。方針は合意済み）。

**触るときに気をつけること（この3つは壊すと業務が止まる／情報が漏れる）**
- **手で入れた休み（`staff_leave_days.source` が `'shift_plan'` 以外）に勤務予定から触らない。**
  詳細は `session-68-2026-08-20` の「3.」を読むこと。
- **カレンダー通知の予約（`cal-notify-v1`）を `base.html` から動かさない。**
- **利用者セルフ評価の `_kiosk_guard()` を消さない・緩めない。**
  許可URLは**完全一致のリスト**で持つこと。前方一致にすると職員の一覧画面
  （利用者名がずらりと並ぶ）まで通ってしまう。実際に一度そうなった。
  詳細は `self-eval-impl-2026-08-20` の「3.」。

その先は `SESSION_67_HANDOFF.md` の「3. 次にやること → 残タスク」の1〜9へ進む。
