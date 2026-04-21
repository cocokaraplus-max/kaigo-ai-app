-- ========================================================
-- TASUKARU 段階2-b 追加: patient_care_plans に usage_weekday を追加
-- ========================================================
-- 実行場所: Supabase Dashboard → SQL Editor → New query
-- 既に patient_care_plans テーブルが作成されている前提

ALTER TABLE patient_care_plans 
    ADD COLUMN IF NOT EXISTS usage_weekday text DEFAULT '';

COMMENT ON COLUMN patient_care_plans.usage_weekday IS '利用曜日と時間帯（例: 火・午前）';

-- 確認
-- SELECT column_name, data_type, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'patient_care_plans' AND column_name = 'usage_weekday';
