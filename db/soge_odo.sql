-- ============================================================
-- TASUKARU  送迎: 走行距離（メーター）のアプリ入力
-- marker: soge-odo-v1
-- 投入先: DEV Supabase → 確認後に本番 Supabase
--
-- 【考え方】
--  走行距離を記録するかどうかは事業所によって分かれるので、施設ごとのトグルにする。
--  既定は false（＝今までどおり出ない）。管理者MENUの「送迎設定」でオンにする。
--
--  メーターは soge_days に持つ（＝便ごと）。既に列はあるが、
--  古い環境にも当たるよう add column if not exists を書いておく（冪等）。
--  走行距離は odo_end - odo_start をその都度計算する（列は持たない）。
-- ============================================================

alter table soge_settings
  add column if not exists odo_enabled boolean not null default false;

alter table soge_days
  add column if not exists odo_start integer;

alter table soge_days
  add column if not exists odo_end integer;

-- ---------- 確認 ----------
-- select facility_code, odo_enabled from soge_settings;
