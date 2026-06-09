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
