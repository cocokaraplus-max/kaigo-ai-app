-- ============================================================
-- TASUKARU  勤怠: 休暇区分の記録 (idempotent)
-- marker: staff-leave-ddl-v1
-- 投入先: まず DEV Supabase (DEMO001)。本番はリリース時。
-- 目的: 打刻(timecard_records)とは別に、日ごとの休暇区分を保存する。
--       様式(参考様式4)出力や勤怠管理で「その日が有給/忌休/休か」を判定する。
-- ============================================================

create table if not exists staff_leave_days (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  staff_name     text not null,
  leave_date     date not null,          -- 対象の日(JST基準)
  leave_type     text not null,          -- paid/substitute/condolence/absence/off/half/hourly
  substitute_for date,                   -- 振替休のとき、何月何日の勤務の振替か(振替元の日付)
  note           text,                   -- 備考(任意)
  created_by     text,                   -- 登録者
  created_at     timestamptz default now(),
  updated_at     timestamptz default now()
);

-- 同じ施設・職員・日付は1件に(全日休みの重複防止)。半休/時間休も1日1レコード想定。
create unique index if not exists uq_staff_leave_day
  on staff_leave_days (facility_code, staff_name, leave_date);

create index if not exists idx_staff_leave_lookup
  on staff_leave_days (facility_code, leave_date);

-- 既存テーブルがある場合の追補(冪等)
alter table staff_leave_days
  add column if not exists substitute_for date;

-- 確認用
-- select count(*) from staff_leave_days;
