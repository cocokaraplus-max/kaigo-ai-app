-- ============================================================
-- TASUKARU  会議: 議事録 構造化データ カラム追補 (idempotent)
-- marker: meetings-minutes-struct-v1
-- 投入先: DEV Supabase (DEMO001) SQL Editor。本番はリリース時。
-- 依存: meetings-ddl-v1 (meetings) が投入済みであること。
-- ============================================================

-- 議事録を3スタイル(A/B/C)のレイアウトに流し込むための構造化データ。
-- 従来の minutes(全文テキスト)は互換のため残し、こちらは構造化JSON文字列を入れる。
--   {"header":{"date","place","attendees":[...],"absentees"},
--    "items":[...], "discussion":"...", "conclusions":[...], "issues":"..."}
-- 無い情報は「（記載なし）」。職員が後から手入力で補完可能。
alter table meetings
  add column if not exists minutes_struct text;

-- 確認用
-- select count(*) from meetings;
