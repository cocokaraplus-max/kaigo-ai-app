# TASUKARU 開発引き継ぎ — Session 53

---

## チャット冒頭に貼る文章

```
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
- git add を忘れずに行うこと
- commitする前に必ず git branch で現在のブランチを確認すること

Session 53の引き継ぎファイルを読んで、残タスクから作業を開始してください。
引き継ぎファイル: /Users/ZIMAX 1/dev/kaigo-ai-app/SESSION_53_HANDOFF.md
```

---

## Session 52 の反省点

1. tasukaruブランチに直接commitしてしまうことが複数回発生
   - 作業前に必ず git branch でブランチ確認をすること
   - commitはtasukaru-devのみ、本番はmergeのみ

---

## Session 52 完了済み修正（本番反映済み）

### 主要変更ファイル
- calendar.html: モーダルpadding修正、削除エラーハンドリング、ケース記録連動
- assessment.html: source_data保存対応、AI生成ボタン追加
- daily_view.html: 付箋ボタン左端移動、TTS Audio要素方式、FAB→サイドドロワー、全既読ボタン
- board.html: 全既読ボタン、boardMarkAllRead関数
- base.html: overflow修正、PC可変幅、全既読JS
- admin.html: facility_code修正、overflow-x
- input.html: 休み連絡日付入力欄
- manual.html: サイドドロワー説明、休み連絡×カレンダー連携説明追加
- ledger.html: 【新規】出納帳ページ骨組み
- app.py: ai_fill、mark_all_read、カレンダー連動、出納帳API

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

-- patient_profiles(本番のみ不足していたカラムを追加済み)
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
CREATE TABLE IF NOT EXISTS accounts (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    tax_type TEXT DEFAULT 'taxable',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS journal_entries (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT NOT NULL,
    entry_date DATE NOT NULL,
    debit_account_id BIGINT REFERENCES accounts(id),
    credit_account_id BIGINT REFERENCES accounts(id),
    amount INTEGER NOT NULL,
    tax_amount INTEGER DEFAULT 0,
    description TEXT,
    receipt_urls JSONB DEFAULT '[]',
    source TEXT DEFAULT 'manual',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS receipts (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT NOT NULL,
    image_url TEXT NOT NULL,
    ocr_result JSONB DEFAULT '{}',
    entry_id BIGINT REFERENCES journal_entries(id),
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 残タスク（Session 53 以降）

### 優先度：最高

#### 1. 出納帳 Phase 2（Session 53メインタスク）
- アクセス制限: facility_code=cocokaraplus-5526 かつ 岸本洋幸のみ
- 現状: 骨組みのみtasukaru-devにデプロイ済み（本番未反映・未確認）
- 要確認: devで /ledger にアクセスして動作確認
- 残実装:
  - [ ] ナビゲーションバーに出納帳アイコン追加（岸本洋幸のみ表示）
  - [ ] CSVインポートの動作確認・スマレジ形式対応
  - [ ] 試算表PDF出力機能
  - [ ] 消費税オン/オフ設定
  - [ ] 勘定科目カスタマイズ画面
  - [ ] 領収書一覧画面
  - [ ] 本番マージ

### 優先度：高

#### 2. モニタリング生成の「今日は」→日付変換
- ケース記録内の「今日は」「本日は」→created_atの日付に変換してからAI生成
- app.py /api/generate_monitoring を修正

#### 3. 評価ページ音声入力の保存確認
- source_dataの保存は実装済み・現場確認が必要

### 優先度：中

#### 4. admin.html 利用者検索機能の確認

### 優先度：低

#### 5. 保留タスク（Session 50以前）
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
# /ledger以外のアカウントは /top にリダイレクト
```

### 出納帳 実装済みAPI一覧
- GET /ledger ページ（初回アクセスで勘定科目を自動作成）
- GET /api/ledger/entries?month=YYYY-MM 仕訳一覧
- POST /api/ledger/entry 仕訳登録・更新
- DELETE /api/ledger/entry/<id> 仕訳削除
- GET /api/ledger/trial_balance?month=YYYY-MM 試算表
- POST /api/ledger/import_csv CSVインポート（Gemini自動仕訳）
- POST /api/ledger/ocr_receipt 領収書OCR（Gemini）

### 出納帳 初期勘定科目（自動投入）
- 資産: 現金/普通預金/売掛金
- 負債: 買掛金/未払金/借入金
- 収益: 介護報酬売上/自費売上/雑収入
- 費用: 給与手当/法定福利費/地代家賃/水道光熱費/通信費/消耗品費/車両費/外注費/雑費

### カレンダー連動
- records.calendar_event_id（UUID型）でカレンダーイベントと紐付け
- calendars.is_system = True のカレンダーは削除不可
- カレンダーイベント削除→ケース記録削除
- カレンダーイベント更新→ケース記録の日付・content更新

### iOS Audio制約
- new Audio()をタップ時に先に作成、srcは後から差し替え
- _ttsUnlockAudio()は不要（むしろ邪魔）

### Supabase直接アクセス（admin.html）
- patient_profilesはSupabaseに直接PATCH
- facility_codeを必ずpayloadに含める（RLS対策）

### PC可変幅
- CSS変数 --page-max-width で制御
- localStorageに保存、ダブルクリックで480pxリセット
