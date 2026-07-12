-- ============================================================
-- TASUKARU  利用曜日の「第N週のみ」対応
-- marker: visit-nth-ddl-v1
-- 投入先: まず DEV Supabase。本番はリリース時。
--
-- 「第2火曜だけ利用」のような隔週・月N回の利用者に対応する。
-- 既存の ampm_per_day（曜日 -> AM/PM/ALL）と同じ持ち方で、
-- nth_per_day（曜日 -> 第N週）を並べる。
--
-- nth_per_day の形:
--   {}            … 全曜日「毎週」（既定。既存利用者はこれ）
--   {"2": 2}      … 火曜は第2週のみ（0=日, 1=月 … 6=土。ampm_per_day と同じキー）
--   {"1": 1, "3": 3} … 月曜は第1週のみ、水曜は第3週のみ
--
-- 値は 1..5。キーが無い曜日は「毎週」。
-- 既存データは空 {} になるので、これまでどおり毎週扱いになる（挙動は変わらない）。
-- ============================================================

alter table patient_visit_days
  add column if not exists nth_per_day jsonb not null default '{}'::jsonb;

-- ---------- 確認用 ----------
-- select patient_id, weekdays, ampm_per_day, nth_per_day
--   from patient_visit_days limit 20;
