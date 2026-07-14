# TASUKARU 開発ドキュメント

介護記録システム「TASUKARU」の開発引き継ぎドキュメントです。
Session 56 までの完全な軌跡、技術的知見、作業方法論を記載しています。

新しいAIとのチャットを開始する際は、このREADMEと `SESSION_57_HANDOFF.md` を必ず読んでください。

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
