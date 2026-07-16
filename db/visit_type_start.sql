-- ============================================================
-- visit-type-start-v1: 利用管理の予定を「型別の利用開始日」で制御する
-- patient_visit_days に 半日型/1日型の利用開始日を追加。
--   half_start_date: 半日型(ampm_per_day=AM/PM)の利用開始日
--   full_start_date: 1日型(ampm_per_day=ALL)の利用開始日
-- 自費(patient_jihi_weekdays)は既存の valid_from を開始日として流用する。
-- 開始日が NULL のときは従来どおり(いつからでも予定)＝後方互換。
-- 冪等。DEV→本番の順に適用。
-- ============================================================
alter table patient_visit_days add column if not exists half_start_date date;
alter table patient_visit_days add column if not exists full_start_date date;
