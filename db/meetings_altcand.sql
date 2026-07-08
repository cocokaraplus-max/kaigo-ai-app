-- ============================================================
-- TASUKARU  会議ICF分類: 次点候補カラム追補 (idempotent)
-- marker: meetings-icf-altcand-v1
-- 投入先: DEV Supabase (DEMO001) SQL Editor。本番はリリース時。
-- 依存: meetings-ddl-v1 (meeting_icf_links) が投入済みであること。
-- ============================================================

-- 方式A+次点候補: AIが迷った近いコードを1つ添える。
-- 付箋に「もしかして: d460?」と小さく出し、人がワンタップで移せる。
alter table meeting_icf_links
  add column if not exists alt_icf_code   text references icf_codes(code);  -- 次点候補コード
alter table meeting_icf_links
  add column if not exists alt_reason      text;                            -- 次点にした理由（短文）

-- 確認用（件数のみ）
-- select count(*) from meeting_icf_links;
