# TASUKARU 開発引き継ぎ — Session 53

---

## チャット冒頭に貼る文章

TASUKARUの開発を続けます。以下が現状です。

【リポジトリ】cocokaraplus-max/kaigo-ai-app
【ローカル】/Users/ZIMAX 1/dev/kaigo-ai-app/
【ブランチ】開発: tasukaru-dev / 本番: tasukaru
【dev URL】https://tasukaru-dev-191764727533.asia-northeast1.run.app
【本番URL】https://tasukaru-191764727533.asia-northeast1.run.app
【本番Supabase】abvglnkwtdeoaazyqwyd (facility_code: cocokaraplus-5526)
【dev Supabase】otjevnmoycnvaxeltrtj (facility_code: DEMO001)

【作業方式】
- Pythonスクリプトを ~/Desktop/ に置いて実行
- 必ずdev確認 → 本番マージの順番を厳守
- 本番マージ前に「本番にマージしてOKですか？」と必ず確認を取ること
- commitする前に必ず git branch で現在のブランチを確認すること

Session 53の引き継ぎファイルを読んで、残タスクから作業を開始してください。
引き継ぎファイル: /Users/ZIMAX 1/dev/kaigo-ai-app/SESSION_53_HANDOFF.md

---

## Session 52 の反省点

1. tasukaruブランチに直接commitしてしまうことが複数回発生
   - 作業前に必ず git branch でブランチ確認をすること
   - commitはtasukaru-devのみ、本番はmergeのみ

---

## Session 52 完了済み修正（本番反映済み）

### 本番反映済み
- calendar.html: モーダルpadding修正、削除エラーハンドリング、ケース記録連動
- assessment.html: source_data保存対応、AI生成ボタン追加
- daily_view.html: 付箋ボタン左端移動、TTS Audio要素方式、FAB→サイドドロワー、全既読ボタン
- board.html: 全既読ボタン、boardMarkAllRead関数
- base.html: overflow修正、PC可変幅、全既読JS、出納帳ナビアイコン（岸本洋幸/デモ職員Aのみ）
- admin.html: facility_code修正、overflow-x
- input.html: 休み連絡日付入力欄
- manual.html: サイドドロワー説明、休み連絡×カレンダー連携説明追加
- app.py: ai_fill、mark_all_read、カレンダー連動

### dev(tasukaru-dev)のみ・本番未反映
- ledger.html: 出納帳ページ（仕訳帳/試算表/CSV取込/領収書OCR/勘定科目/設定）
- app.py: 出納帳API全般（entries/entry/trial_balance/import_csv/ocr_receipt/accounts/settings/divisions/cash_fill）

---

## DBマイグレーション（実施済み - dev + prod両方）

```sql
-- patient_evaluations
ALTER TABLE patient_evaluations ADD COLUMN IF NOT EXISTS source_data TEXT DEFAULT '';

-- records (UUID型に変更済み)
ALTER TABLE records DROP COLUMN calendar_event_id;
ALTER TABLE records ADD COLUMN calendar_event_id UUID DEFAULT NULL;

-- calendars
ALTER TABLE calendars ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;

-- patient_profiles
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS care_manager_name TEXT DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS delegate_office TEXT DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS postal_code TEXT DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS certification_start_date DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS certification_end_date DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS long_goal_period_from DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS long_goal_period_to DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS short_goal_period_from DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS short_goal_period_to DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT NULL;

-- 出納帳（dev + prod両方で実施済み）
CREATE TABLE IF NOT EXISTS accounts (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, tax_type TEXT DEFAULT 'taxable', is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS journal_entries (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, entry_date DATE NOT NULL, debit_account_id BIGINT REFERENCES accounts(id), credit_account_id BIGINT REFERENCES accounts(id), amount INTEGER NOT NULL, tax_amount INTEGER DEFAULT 0, description TEXT, receipt_urls JSONB DEFAULT '[]', source TEXT DEFAULT 'manual', created_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS receipts (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, image_url TEXT NOT NULL, ocr_result JSONB DEFAULT '{}', entry_id BIGINT REFERENCES journal_entries(id), created_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS ledger_divisions (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, name TEXT NOT NULL, is_active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS ledger_settings (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL UNIQUE, auto_cash_fill BOOLEAN DEFAULT FALSE, divisions_enabled BOOLEAN DEFAULT FALSE);
```

---

## 残タスク（Session 53 以降）

### 優先度：最高

#### 1. 出納帳の動作確認・本番マージ
- 現状: tasukaru-devのみ動作確認中
- アクセス制限: facility_code=cocokaraplus-5526 かつ 岸本洋幸のみ（devはDEMO001+デモ職員Aも可）
- 確認済み: 仕訳帳・勘定科目タブ表示OK
- 未確認: 設定タブのボタン動作・仕訳保存・試算表
- 本番マージ前にdevで全機能確認すること

#### 2. 出納帳 Phase 3（残機能）
- [ ] 試算表PDF出力
- [ ] 消費税集計表示
- [ ] 事業間資金移動の自動記録（現金自動補填機能）
- [ ] 現金残高リアルタイム表示
- [ ] 領収書OCRから仕訳自動生成の動作確認

### 優先度：高

#### 3. モニタリング生成の「今日は」→日付変換
- ケース記録内の「今日は」「本日は」→created_atの日付に変換してからAI生成

#### 4. 評価ページ音声入力の保存確認
- source_dataの保存は実装済み・現場確認が必要

### 優先度：中

#### 5. admin.html 利用者検索機能の確認

### 優先度：低

#### 6. 保留タスク
- A. 目標管理の利用者情報紐付け
- B. バイタル入力改修4項目
- C. PC専用一括入力画面
- D. 方式B（サーバーPDF生成）

---

## 重要な技術的知見

### ブランチ管理
- 必ずtasukaru-devで作業
- commitの前に git branch で確認
- 本番へは git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru

### 出納帳アクセス制限
```python
LEDGER_ALLOWED_FACILITY = 'cocokaraplus-5526'
LEDGER_ALLOWED_USER = '岸本洋幸'
LEDGER_DEV_FACILITY = 'DEMO001'
LEDGER_DEV_USER = 'デモ職員A'
```

### 出納帳 実装済みAPI
- GET/POST /api/ledger/settings - 設定取得・保存
- GET /api/ledger/divisions - 事業部一覧
- POST /api/ledger/division - 事業部登録・更新
- DELETE /api/ledger/division/<id> - 事業部削除
- POST /api/ledger/cash_fill - 日次現金自動補填
- GET /api/ledger/accounts - 勘定科目一覧
- POST /api/ledger/account - 勘定科目登録・更新
- DELETE /api/ledger/account/<id> - 勘定科目削除
- GET /api/ledger/entries?month=YYYY-MM - 仕訳一覧
- POST /api/ledger/entry - 仕訳登録・更新
- DELETE /api/ledger/entry/<id> - 仕訳削除
- GET /api/ledger/trial_balance?month=YYYY-MM - 試算表
- POST /api/ledger/import_csv - CSVインポート（Gemini自動仕訳）
- POST /api/ledger/ocr_receipt - 領収書OCR（Gemini）

### 出納帳 初期勘定科目（初回アクセス時に自動投入）
- 資産: 現金(101)/普通預金(102)/売掛金(103)
- 負債: 買掛金(201)/未払金(202)/借入金(203)
- 収益: 介護報酬売上(401)/自費売上(402)/雑収入(403)
- 費用: 給与手当(501)/法定福利費(502)/地代家賃(503)/水道光熱費(504)/通信費(505)/消耗品費(506)/車両費(507)/外注費(508)/雑費(509)

### カレンダー連動
- records.calendar_event_id（UUID型）でカレンダーイベントと紐付け
- calendars.is_system=True のカレンダーは削除不可
- カレンダーイベント削除→ケース記録削除
- カレンダーイベント更新→ケース記録の日付・content更新

### iOS Audio制約
- new Audio()をタップ時に先に作成、srcは後から差し替え
- _ttsUnlockAudio()は不要（むしろ邪魔）

### Supabase直接アクセス（admin.html）
- patient_profilesはSupabaseに直接PATCH
- facility_codeを必ずpayloadに含める（RLS対策）
