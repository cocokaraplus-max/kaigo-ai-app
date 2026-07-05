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
