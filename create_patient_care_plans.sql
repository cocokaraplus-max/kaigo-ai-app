-- ========================================================
-- TASUKARU モニタリング機能: 利用者ケアプラン情報テーブル
-- ========================================================
-- 実行場所: Supabase Dashboard → SQL Editor → New query
-- このSQLを貼り付けて「Run」を押すだけで完了します
--
-- このテーブルは、利用者ごとに以下の情報を保持します:
--   - 長期目標（機能/活動/参加）+ 期間
--   - 短期目標（機能/活動/参加）+ 期間
--   - 支援内容①〜④
--
-- モニタリング書類生成時に、この情報を自動転記します。
-- ========================================================

CREATE TABLE IF NOT EXISTS patient_care_plans (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- 利用者を特定するキー
    facility_code text NOT NULL,
    chart_number  text NOT NULL,
    user_name     text NOT NULL,
    
    -- 長期目標
    long_goal_function      text DEFAULT '',
    long_goal_activity      text DEFAULT '',
    long_goal_participation text DEFAULT '',
    long_goal_period_from   date,
    long_goal_period_to     date,
    
    -- 短期目標
    short_goal_function      text DEFAULT '',
    short_goal_activity      text DEFAULT '',
    short_goal_participation text DEFAULT '',
    short_goal_period_from   date,
    short_goal_period_to     date,
    
    -- 支援内容（モニタリングの①〜④に対応）
    support_content_1 text DEFAULT '',
    support_content_2 text DEFAULT '',
    support_content_3 text DEFAULT '',
    support_content_4 text DEFAULT '',
    
    -- 管理用
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    
    -- 1利用者1レコード制約（将来版数管理するなら削除）
    CONSTRAINT patient_care_plans_unique UNIQUE (facility_code, chart_number)
);

-- 検索高速化用インデックス
CREATE INDEX IF NOT EXISTS idx_patient_care_plans_facility 
    ON patient_care_plans(facility_code);

CREATE INDEX IF NOT EXISTS idx_patient_care_plans_user 
    ON patient_care_plans(facility_code, user_name);

-- 更新日時を自動更新するトリガー
CREATE OR REPLACE FUNCTION update_patient_care_plans_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_patient_care_plans_updated_at ON patient_care_plans;
CREATE TRIGGER trigger_patient_care_plans_updated_at
    BEFORE UPDATE ON patient_care_plans
    FOR EACH ROW
    EXECUTE FUNCTION update_patient_care_plans_updated_at();

-- コメント（Supabase Dashboardで表示される）
COMMENT ON TABLE patient_care_plans IS 'TASUKARU: 利用者ごとの長期目標・短期目標・支援内容を管理';
COMMENT ON COLUMN patient_care_plans.support_content_1 IS 'モニタリング項目①として使用';
COMMENT ON COLUMN patient_care_plans.support_content_2 IS 'モニタリング項目②として使用';
COMMENT ON COLUMN patient_care_plans.support_content_3 IS 'モニタリング項目③として使用';
COMMENT ON COLUMN patient_care_plans.support_content_4 IS 'モニタリング項目④として使用';

-- ========================================================
-- 確認クエリ（テーブルができたか確認）
-- ========================================================
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'patient_care_plans'
-- ORDER BY ordinal_position;
