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

### 掲示板関連
- board.html: メンション投稿のis_private対応（メンションのみ投稿は指定した人だけ表示）
- board.html: メンション検索でひらがな・カタカナ両方ヒット
- board.html: スタッフにふりがなデータ追加（data-kana属性）
- app.py: unread_countでis_privateフィルタリング（メンションされていない人にバッジが付かない）
- app.py: mark_all_readでis_privateフィルタリング
- app.py: board_postsにis_privateカラム追加・保存対応
- DB: board_posts に is_private BOOLEAN DEFAULT FALSE 追加（dev+prod両方）
- DB: 既存メンション付き投稿を is_private=TRUE に更新済み

### 休み連絡関連
- input.html: 休み連絡の「誰から」にケアマネ・その他を追加
- input.html: その他選択時に自由記載欄が表示される

### 評価ページ
- assessment.html: 保存後に利用者検索欄が消える問題を修正

### ふりがな統一
- admin.html: 利用者登録のふりがなplaceholderをひらがなに変更
- patient_profile.html: ふりがな入力欄をひらがなに、カタカナ入力で自動変換

### 出納帳（dev=tasukaru-devのみ・本番未反映）
- ledger.html: 仕訳帳/試算表/CSV取込/領収書OCR/勘定科目/設定タブ
- 設定タブ: 事業部管理トグル・事業部追加/編集/削除
- app.py: 出納帳API全般

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

-- 掲示板
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT FALSE;

-- 出納帳（dev + prod両方で実施済み）
CREATE TABLE IF NOT EXISTS accounts (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, tax_type TEXT DEFAULT 'taxable', is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS journal_entries (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, entry_date DATE NOT NULL, debit_account_id BIGINT REFERENCES accounts(id), credit_account_id BIGINT REFERENCES accounts(id), amount INTEGER NOT NULL, tax_amount INTEGER DEFAULT 0, description TEXT, receipt_urls JSONB DEFAULT '[]', source TEXT DEFAULT 'manual', created_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS receipts (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, image_url TEXT NOT NULL, ocr_result JSONB DEFAULT '{}', entry_id BIGINT REFERENCES journal_entries(id), created_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS ledger_divisions (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, name TEXT NOT NULL, is_active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS ledger_settings (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL UNIQUE, auto_cash_fill BOOLEAN DEFAULT FALSE, divisions_enabled BOOLEAN DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS ledger_permissions (id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL, staff_name TEXT DEFAULT NULL, auto_cash_fill BOOLEAN DEFAULT FALSE, cash_source_division_id BIGINT DEFAULT NULL, inter_division_fill BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE, granted_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
```

---

## 残タスク（Session 53 以降）

### 優先度：最高

#### 1. 出納帳 動作確認・本番マージ
- 現状: tasukaru-devのみ。本番未反映。
- アクセス: facility_code=cocokaraplus-5526 かつ 岸本洋幸のみ（devはDEMO001+デモ職員Aも可）
- 残実装:
  - [ ] 開発者MENUに出納帳アクセス管理を追加（施設・ユーザー単位で許可）
  - [ ] 試算表PDF出力
  - [ ] 消費税集計表示
  - [ ] 現金自動補填機能（岸本洋幸専用・施設ごとトグル）
  - [ ] 事業間資金移動の自動記録
  - [ ] 本番マージ

### 優先度：高

#### 2. モニタリング生成の「今日は」→日付変換
- ケース記録内の「今日は」「本日は」→created_atの日付に変換してからAI生成

#### 3. 掲示板スタッフ検索のふりがな
- staffsテーブルにstaff_name_kanaカラムが必要
- 現状: kana_mapからkanaを取得しているが、staffsテーブルにstaff_name_kanaがなければ空になる
- 確認: staffsテーブルにstaff_name_kanaカラムがあるか確認が必要

### 優先度：中

#### 4. admin.html 利用者検索機能の確認

### 優先度：低

#### 5. 保留タスク
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

### 掲示板is_private
- is_private=TRUE: mention_namesに含まれるスタッフ + 投稿者のみ表示・バッジカウント
- 既存投稿はUPDATE済み（mention_names != '[]' → is_private=TRUE）
- unread_count・mark_all_readともにis_privateフィルタリング済み

### 出納帳アクセス制限
```python
LEDGER_ALLOWED_FACILITY = 'cocokaraplus-5526'
LEDGER_ALLOWED_USER = '岸本洋幸'
LEDGER_DEV_FACILITY = 'DEMO001'
LEDGER_DEV_USER = 'デモ職員A'
```

### 出納帳 実装済みAPI
- GET/POST /api/ledger/settings
- GET /api/ledger/divisions
- POST /api/ledger/division
- DELETE /api/ledger/division/<id>
- POST /api/ledger/cash_fill
- GET /api/ledger/accounts
- POST /api/ledger/account
- DELETE /api/ledger/account/<id>
- GET /api/ledger/entries?month=YYYY-MM
- POST /api/ledger/entry
- DELETE /api/ledger/entry/<id>
- GET /api/ledger/trial_balance?month=YYYY-MM
- POST /api/ledger/import_csv
- POST /api/ledger/ocr_receipt

### カレンダー連動
- records.calendar_event_id（UUID型）でカレンダーイベントと紐付け
- calendars.is_system=True のカレンダーは削除不可
- カレンダーイベント削除→ケース記録削除
- カレンダーイベント更新→ケース記録の日付・content更新

### iOS Audio制約
- new Audio()をタップ時に先に作成、srcは後から差し替え
- _ttsUnlockAudio()は不要（むしろ邪魔）
