cd ~/Desktop/kaigo-ai-app

cat > STAGE2_PROGRESS.md << 'EOF'
# TASUKARU 段階2 進捗記録 (2026-04-20 深夜就寝時点)

## ✅ 完了済み

### 段階1
- openpyxl問題解消（評価目盛・チェックボックス復活）
- #REF!エラー除去
- 要介護度の分割（要介護/数字）
- 満足度・適切性のフォント 11pt化
- 満足度・適切性の選択肢UI

### 段階2 - 基盤
- Supabase `patient_care_plans` テーブル作成
- 列 `usage_weekday`, `care_level_category` 追加済み
- `create_patient_care_plans.sql`, `add_usage_weekday.sql`, `add_care_level_category.sql` 実行済

### 段階2 - コード配置（ローカル ~/Desktop/kaigo-ai-app）
- monitoring_integration.py（ケアプラン連携込み）
- monitoring_gen.py
- template_filler.py
- patient_info_integration.py
- patient_info_import_integration.py
- excel_importer.py（最新月フォールバック + 利用曜日B51-E51対応）
- templates/monitoring.html
- templates/patient_info.html（検索UI + 要介護度セレクタ + 期間自動計算）
- templates/patient_info_import.html
- templates/history.html（歯車メニュー追加、spaNav削除済み）
- mappings/cocokaraplus-5526/monitoring.json
- templates_xlsx/cocokaraplus-5526/モニタリング報告書.xlsx
- app.py 末尾に3つのroute登録追加済

### 動作確認済み
- Flask 起動時に3つのルートログが出る
- /patient-info で検索UIが動作（キャッシュクリア後）
- 要介護度セレクタで期間が自動計算される

## ⚠️ 未解決の問題（明日の朝ここから）

### 症状
1. 歯車メニューから /patient-info 等に遷移した直後、検索窓が表示されない
2. 戻るボタンが表示されない
3. ページリロードすると表示される
4. ページ遷移がぎこちない

### 推定原因
TASUKARUのSPAナビゲーション（spaNav）と新画面の相性問題。
- /history の歯車メニューの spaNav は削除済
- でもまだ症状が出る
- → ボトムナビ側の spaNav が影響している可能性

### 次にやる候補
1. Flaskターミナルのログを見て、?partial=1 が付いているか確認
2. どこから画面に遷移したか特定（下タブ / 歯車 / URL直打ち）
3. 必要なら base.html のボトムナビから spaNav を外す
4. または新画面のテンプレートを SPA対応の形式に書き換え

## 📂 重要ファイル

### 設定・ドキュメント
- STAGE1_BETA_README.md
- STAGE2_README.md  
- STAGE2B_README.md
- STAGE2C_README.md
- create_patient_care_plans.sql
- add_usage_weekday.sql
- add_care_level_category.sql
### 起動コマンド
### 環境変数（本番と同じ、要再設定）
以下の変数は `setenv.sh` で管理（gitignore済み）。値は管理者から取得してください。
- SUPABASE_URL
- SUPABASE_KEY
- GEMINI_API_KEY
- FACILITY_CODE
- SECRET_KEY
- DEV_PASSWORD
