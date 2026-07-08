-- ============================================================
-- TASUKARU  勉強会・会議議事録 機能  DDL (idempotent)
-- marker: staff-minutes-ddl-v1
-- 投入先: まず DEV Supabase (DEMO001) の SQL Editor。
--         本番(cocokaraplus-5526)は機能リリース時に同SQLを流す。
-- 依存: なし（利用者・ICFに非依存の独立テーブル）。
-- ============================================================

-- ------------------------------------------------------------
-- staff_meetings : 社内の勉強会・会議の議事録（利用者に紐づかない）
--   担当者会議(meetings)とは完全に別。ICF/patient_id/assessment は持たない。
-- ------------------------------------------------------------
create table if not exists staff_meetings (
  id                uuid primary key default gen_random_uuid(),
  facility_code     text not null,
  title             text,                              -- 会議名（例: 6月度全体会議 / 感染症勉強会）
  meeting_date      date,                              -- 開催日
  attendees         text,                              -- 参加者（自由記述）
  audio_session_id  text,                              -- 録音セッションUUID（チャンク束ね）
  transcript        text,                              -- 文字起こし全文
  minutes           text,                              -- AI生成議事録（本文）
  minutes_struct    text,                              -- 議事録の構造化JSON文字列（テンプレ流し込み用）
  minutes_style     text default 'a',                  -- 選択された議事録スタイル a〜h
  decisions         text,                              -- 決定事項（JSON配列文字列 ["...","..."]）
  todos             text,                              -- ToDo（JSON配列文字列 ["...","..."]）
  status            text not null default 'draft',     -- draft/transcribed/summarized/confirmed
  created_by        text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_staff_meetings_facility
  on staff_meetings (facility_code);
create index if not exists idx_staff_meetings_facility_date
  on staff_meetings (facility_code, meeting_date desc);

-- ------------------------------------------------------------
-- PRO制限は admin_settings に相乗り（key = staff_minutes_enabled）。
--   ※ 担当者会議(meetings_enabled)とは判定意図が逆:
--      未設定の施設は「許可」(今は全施設で使える)。明示的に false のときだけ弾く。
--   → DDL不要。アプリ側の _staff_minutes_gate_ok() で読む。
-- ------------------------------------------------------------

-- 確認用（件数のみ）
-- select count(*) from staff_meetings;
