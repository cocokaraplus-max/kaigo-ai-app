-- ============================================================
-- TASUKARU  送迎モジュール ①送迎設定
-- marker: soge-ddl-v1-settings
-- 投入先: まず DEV Supabase。本番はリリース時。
--
-- 施設ごとの運営単位数と、便（trip）の定義を持つ。
-- 便は「迎え専用/送り専用」ではない。2単位運営の中間便は
-- 「1単位目を送る + 2単位目を迎える」が同一車両で混在する。
--
-- trips の形:
-- [
--   {"key":"t1","name":"迎え便","depart":"08:30","pickup_units":[1],"dropoff_units":[]},
--   {"key":"t2","name":"中間便","depart":"12:00","pickup_units":[2],"dropoff_units":[1]},
--   {"key":"t3","name":"送り便","depart":"16:00","pickup_units":[],"dropoff_units":[2]}
-- ]
--   pickup_units  … その便で「迎えに行く」単位（1=午前/1単位目, 2=午後/2単位目）
--   dropoff_units … その便で「送り届ける」単位
--   depart        … 施設の出発予定時刻（到着予定時刻の算出起点）
--
-- 1単位運営なら trips は2本（迎え便 / 送り便）。
-- 単位は既存の patient_visit_days.ampm_per_day（AM=1単位目 / PM=2単位目）に対応する。
-- ============================================================

create table if not exists soge_settings (
  facility_code   text primary key,
  unit_count      smallint not null default 1,      -- 1 or 2
  trips           jsonb not null default '[]'::jsonb,
  mid_dropoff_first boolean not null default true,  -- 中間便は「送ってから迎え」を優先
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- 既存テーブルがある場合の追補（冪等）
alter table soge_settings
  add column if not exists mid_dropoff_first boolean not null default true;

-- ---------- 確認用 ----------
-- select * from soge_settings;
