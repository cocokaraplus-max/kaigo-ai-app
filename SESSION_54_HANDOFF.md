# TASUKARU 開発引き継ぎ — Session 54

---

## チャット冦頭に貼る文章（次のAIへの引き継ぎ）

```
あなたはTASUKARUという介護記録システムの開発パートナーです。
前のClaudeと同じレベルで作業を続けてください。

「作業スタイルの引き継ぎ」は前回と同樹。

[プロジェクト情報]
リポジトリ: cocokaraplus-max/kaigo-ai-app
ローカル: /Users/ZIMAX 1/dev/kaigo-ai-app/
ブランチ: 開発=tasukaru-dev / 本番=tasukaru
dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
本番URL: https://tasukaru-191764727533.asia-northeast1.run.app
本番Supabase: abvglnkwtdeoaazyqwyd (facility_code: cocokaraplus-5526)
dev Supabase: otjevnmoycnvaxeltrtj (facility_code: DEMO001)
ANTHROPIC_API_KEY: Cloud Runに環境変数として設定済み（devのみ。本番はマージ時に設定必要）

Session 54の引き継ぎファイルを読んで、残タスクから作業を開始してください。
引き継ぎファイル: /Users/ZIMAX 1/dev/kaigo-ai-app/SESSION_54_HANDOFF.md
```

---

## Session 53 完了済み作業（devのみ・本番未反映）

### 出納帳
- 仕訳モーダルバグ修正・プレースホルダー追加
- renderSummaryバグ修正・試算表PDF出力
- CSV取込をClaude APIに切り替え・AI科目推定強化
- CSV取込プレビューUI改善
- requirements.txtにantropic追加・バグ修正等
- **CSV取込5件・AI科目推定 全件正確 OK**

### 評価ページ
- ALLOWED_UPSERT_KEYSに_new・_contフィールド追加（新規目標保存バグ修正）
- トースト通知の表示位置を下部→上部に修正

### マニュアル
- ケース記録モックを右端ピンクタブUIに更新

### 休み連絡機能改善
- content自動生成（「5月26日はお休みと家族から連絡がありました。」）
- leave_date_start/endをrecordsテーブルに保存
- モニタリング生成時に休日情報を反映
- 編集UIに休み日付フィールド追加
- ケース記録編集↔カレンダー双方向同期実装
- 動作確認 OK（26日にカレンダー登録・AI要約正確）

### DBマイグレーション（dev+prod完了）
```sql
ALTER TABLE records ADD COLUMN IF NOT EXISTS leave_date_start DATE DEFAULT NULL;
ALTER TABLE records ADD COLUMN IF NOT EXISTS leave_date_end DATE DEFAULT NULL;
```

---

## 最新のcommit（tasukaru-dev）

- 62a18c9: fix: カレンダー→ケース記録同期改善・利用者検索mousedown追加・左日付自動コピー修正
- 62a18c9: fix: カレンダー→ケース記録同期改善・利用者検索mousedown追加・左日付自動コピー修正
- 3b2f9d6: feat: 休み連絡編集に日付フィールド追加・ケース記録↔カレンダー双方向同期
- 1d6d638: fix: サーバー側でも休み連絡時はcontentバリデーションをスキップ
- f76cf08: fix: マニュアルのモックを右端ピンクタブUIに修正
- 2f23a23: fix: 休み連絡時はcontentバリデーションスキップ
- adee88f: feat: 休み連絡の精度改善
- ecbd7b4: fix: 評価ページバグ修正・トースト上部修正

---

## 残タスク（Session 54 以降）

### 優先度：最高

#### 1. 出納帳 追加帳簿実装
- 現金出納帳・預金出納帳・経費クレカ・売上台帳
- PDF/Excel出力（税理士提出用）
- 同じ法人（介護施設＋接骨院）
- DBマイグレーション必要（cash_ledger, bank_accounts, bank_ledger, sales_ledger）

#### 2. 出納帳 本番マージ
- ANTHROPIC_API_KEYを本番Cloud Runにも追加必要
- 本番Supabaseに上記DBマイグレーション

### 優先度：高

#### 3. モニタリング生成の「今日は」→日付変換
- app.py /api/generate_monitoring を修正

#### 4. 掲示板スタッフ検索のふりがな確認
- staffsテーブルにstaff_name_kanaカラムがあるか確認

### 優先度：中

#### 5. admin.html 利用者検索機能の確認

---

## 重要な技術的知見

### Claude API設定
- モデル: claude-sonnet-4-5
- エンボイント: client = _anthropic.Anthropic()
- APIキー: Cloud Run環境変数 ANTHROPIC_API_KEY

### 休み連絡の処理フロー
1. フロント：content空で保存OK（休み連絡のみバリデーションスキップ）
2. サーバー：content自動生成「○月○日はお休みと○○から連絡がありました。」
3. カレンダーに「○○様 お休み」を休みの日に登録
4. recordsにleave_date_start/endを保存
5. 編集時：日付変更するとカレンダーも同期・contentも再生成
6. カレンダー編集時：日付変更するとleave_date_start/endを更新、contentを再生成（created_atは入力日のまま保持）
   「5月28日はお休みと家族から連絡がありました。」→日付変更で「6月6日はお休みと家族から連絡がありました。」に自動更新

### 出納帳アクセス制限
```python
LEDGER_ALLOWED_FACILITY = 'cocokaraplus-5526'
LEDGER_ALLOWED_USER = '岐本洋幸'
LEDGER_DEV_FACILITY = 'DEMO001'
LEDGER_DEV_USER = 'デモ職員A'
```

### ブランチ管理
- 必ずtasukaru-devで作業
- commit前に git branch で確認
- 本番へは git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru
