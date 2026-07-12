-- ============================================================
-- TASUKARU  送迎: 席数と車いす対応
-- marker: soge-ddl-v4-seats
-- 投入先: まず DEV Supabase。本番はリリース時。
--
-- 【なぜ「定員」だけでは足りないか】
--  定員は車検証の乗車定員であって、送迎で乗せられる人数とは違う。
--  運転手が1席使うし、車いすを1台載せると座席が何席か潰れる。
--  リフトやスペースの都合で「車いすは1台まで」という上限もある。
--
-- 【数え方】
--  使う席数 = 歩ける人の数 × 1 ＋ 車いすの人の数 × wheelchair_seats
--  これが soge_seats 以下、かつ 車いすの人数が wheelchair_max 以下なら乗れる。
--
--  例: セレナ（soge_seats=7 / wheelchair_seats=2 / wheelchair_max=1）
--      車いす1名(2席) + 歩ける方5名(5席) = 7席 → ちょうど満席
-- ============================================================

-- ---------- 車両側 ----------
alter table rec_cars
  add column if not exists soge_seats integer;          -- 送迎で乗せられる席数（運転手を除く）

alter table rec_cars
  add column if not exists wheelchair_seats integer default 2;  -- 車いす1台が使う席数

alter table rec_cars
  add column if not exists wheelchair_max integer default 0;    -- 車いすの最大台数（0=乗せられない）

-- ---------- 利用者側 ----------
alter table patient_profiles
  add column if not exists is_wheelchair boolean not null default false;  -- 送迎は車いす

-- ---------- 確認用 ----------
-- select name, capacity, soge_seats, wheelchair_seats, wheelchair_max
--   from rec_cars where facility_code = 'cocokaraplus-5526' and is_active;
-- select count(*) filter (where is_wheelchair) as 車いす利用者
--   from patient_profiles where facility_code = 'cocokaraplus-5526';
