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
