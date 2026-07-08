-- ============================================================
-- TASUKARU  会議: 録音セッションID カラム追補 (idempotent)
-- marker: meetings-audio-session-v1
-- 投入先: DEV Supabase (DEMO001) SQL Editor。本番はリリース時。
-- 依存: meetings-ddl-v1 (meetings) が投入済みであること。
-- ============================================================

-- 長時間会議はフロントで時間分割し、複数音声チャンクを
-- assessment-audio/{f_code}/meetings/{session_id}/{index} に保存する。
-- その session_id を会議レコードに束ねる。
alter table meetings
  add column if not exists audio_session_id text;

-- 確認用（件数のみ）
-- select count(*) from meetings;
