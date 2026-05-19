# TASUKARU 開発引き継ぎ — Session 53

---

## チャット冒頭に貼る文章（次のAIへの引き継ぎ）

```
あなたはTASUKARUという介護記録システムの開発パートナーです。
前のClaudeと同じレベルで作業を続けてください。

【重要：作業スタイルの引き継ぎ】
前のClaudeは以下のスタイルで作業していました。必ず同じスタイルで行動してください：

1. 変更前に必ず現在のコードを確認してから修正する
2. Pythonスクリプトを ~/Desktop/ に保存して実行する方式（ターミナルのヒアドキュメントは文字化けするため使わない）
3. 修正前にOK/NGで結果を確認し、NGの場合は原因を特定してから再修正
4. 必ずdev(tasukaru-dev)で確認してから本番(tasukaru)にマージする
5. 本番マージ前に必ず「本番にマージしてOKですか？」と確認を取る
6. commitの前に必ず git branch で現在のブランチを確認する
7. 日本語テキストはすべてUnicode（\uXXXX）エスケープで記述する
8. 一度に大量の変更をせず、確認しながら段階的に進める
9. セキュリティを常に意識し、アクセス制限は必ず実装する
10. エラーが出たら原因を特定してから修正し、推測で直さない

【プロジェクト情報】
リポジトリ: cocokaraplus-max/kaigo-ai-app
ローカル: /Users/ZIMAX 1/dev/kaigo-ai-app/
ブランチ: 開発=tasukaru-dev / 本番=tasukaru
dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
本番URL: https://tasukaru-191764727533.asia-northeast1.run.app
本番Supabase: abvglnkwtdeoaazyqwyd (facility_code: cocokaraplus-5526)
dev Supabase: otjevnmoycnvaxeltrtj (facility_code: DEMO001)
技術スタック: Python/Flask, Supabase, Cloud Run, Jinja2テンプレート

【開発者情報】
岸本洋幸（facility_code: cocokaraplus-5526）がオーナー
devではデモ職員AとしてDEMO001でログイン確認

Session 53の引き継ぎファイルを読んで、残タスクから作業を開始してください。
引き継ぎファイル: /Users/ZIMAX 1/dev/kaigo-ai-app/SESSION_53_HANDOFF.md
```

---

## Session 52 の反省点

1. tasukaruブランチに直接commitしてしまうことが複数回発生
   - commitの前に git branch で確認すること
   - commitはtasukaru-devのみ、本番はmergeのみ

---

## Session 52 完了済み修正（本番反映済み）

### 掲示板関連
- is_private対応: メンションのみ投稿は指定した人だけ表示・バッジカウント
- メンション検索でひらがな・カタカナ両方ヒット
- board_posts に is_private BOOLEAN DEFAULT FALSE 追加（dev+prod）
- 既存メンション付き投稿を is_private=TRUE に更新済み

### 休み連絡関連
- 休み連絡の「誰から」にケアマネ・その他を追加
- その他選択時に自由記載欄が表示される

### 評価ページ
- 保存後に利用者検索欄が消える問題を修正

### ふりがな統一
- 利用者登録・プロフィールのふりがな入力欄をひらがなに統一
- カタカナ入力で自動ひらがな変換

### カレンダー×ケース記録連動（本番反映済み）
- 休み連絡保存→カレンダー自動登録
- カレンダー削除→ケース記録削除
- カレンダー更新→ケース記録の日付・内容更新
- records.calendar_event_id はUUID型

### その他バグ修正
- PC可変幅リサイズ
- TTS Audio iOS対応
- FABをサイドドロワーに変更
- 全既読ボタン（掲示板・ケース記録）
- 利用者情報保存エラー修正

### 出納帳（dev=tasukaru-devのみ・本番未反映）
- ledger.html: 仕訳帳/試算表/CSV取込/領収書OCR/勘定科目/設定タブ
- 設定タブ: 事業部管理トグル
- app.py: 出納帳API全般

---

## DBマイグレーション（実施済み - dev + prod両方）

```sql
ALTER TABLE patient_evaluations ADD COLUMN IF NOT EXISTS source_data TEXT DEFAULT '';
ALTER TABLE records DROP COLUMN calendar_event_id;
ALTER TABLE records ADD COLUMN calendar_event_id UUID DEFAULT NULL;
ALTER TABLE calendars ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;
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
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT FALSE;
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
- 残実装:
  - [ ] 開発者MENUに出納帳アクセス管理（施設・ユーザー単位で許可）
  - [ ] 試算表PDF出力（銀行提出用）
  - [ ] 現金自動補填機能（岸本洋幸専用・施設ごとトグル）
  - [ ] 事業間資金移動の自動記録
  - [ ] 本番マージ

### 優先度：高

#### 2. モニタリング生成の「今日は」→日付変換
- ケース記録内の「今日は」「本日は」→created_atの日付に変換してからAI生成
- app.py /api/generate_monitoring を修正

#### 3. 掲示板スタッフ検索のふりがな確認
- staffsテーブルにstaff_name_kanaカラムがあるか確認
- なければ追加が必要

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

### Pythonスクリプトの書き方（重要）
- 日本語テキストは必ず \uXXXX Unicode エスケープで記述
- ターミナルのヒアドキュメント（<<EOF）は文字化けするため使わない
- スクリプトは /mnt/user-data/outputs/ に作成してpresent_filesで提供
- ユーザーがダウンロードして ~/Desktop/ に保存して実行

### 掲示板is_private
- is_private=TRUE: mention_namesに含まれるスタッフ + 投稿者のみ表示
- unread_count・mark_all_readともにis_privateフィルタリング済み

### 出納帳アクセス制限
```python
LEDGER_ALLOWED_FACILITY = 'cocokaraplus-5526'
LEDGER_ALLOWED_USER = '\u5c90\u672c\u6d0b\u5e78'  # 岸本洋幸
LEDGER_DEV_FACILITY = 'DEMO001'
LEDGER_DEV_USER = '\u30c7\u30e2\u8077\u54e1A'  # デモ職員A
```

### カレンダー連動
- records.calendar_event_id（UUID型）でカレンダーイベントと紐付け
- calendars.is_system=True のカレンダーは削除不可（TASUKARUケース記録連動）

### iOS Audio制約
- new Audio()をタップ時に先に作成、srcは後から差し替え
- _ttsUnlockAudio()は不要

### Supabase直接アクセス（admin.html）
- patient_profilesはSupabaseに直接PATCH
- facility_codeを必ずpayloadに含める（RLS対策）
