-- ============================================================
-- TASUKARU  送迎: 所要時間の目標と上限
-- marker: soge-ddl-v5-time
-- 投入先: まず DEV Supabase。本番はリリース時。
-- 前提: db/soge_settings.sql 適用済み
--
-- 【なぜ必要か】
--  車両割当の本当の制約は「席数」ではなく「事業所に戻ってくるまでの時間」。
--  席が空いていても、1台で16か所も回ると時間がかかりすぎて現実的でない。
--
--  目標時間を超えたら車を増やして分担する。
--  上限時間を超えたら警告を出す（それ以上は車が足りない）。
--
-- 【所要時間の見積り】
--  Routes API の走行時間 + 乗降にかかる時間
--    乗降時間 = 歩ける人 × stop_minutes + 車いすの人 × stop_minutes_wc
-- ============================================================

alter table soge_settings
  add column if not exists target_minutes integer not null default 30;   -- 目標（これを超えたら車を増やす）

alter table soge_settings
  add column if not exists max_minutes integer not null default 40;      -- 上限（超えたら警告）

alter table soge_settings
  add column if not exists stop_minutes integer not null default 2;      -- 1人あたりの乗降時間（分）

alter table soge_settings
  add column if not exists stop_minutes_wc integer not null default 5;   -- 車いす1名あたりの乗降時間（分）

-- ---------- 所要時間のキャッシュ ----------
-- 同じ立ち寄り順なら結果は変わらないので、Routes API を毎回叩かない。
create table if not exists soge_route_time (
  facility_code  text not null,
  route_hash     text not null,          -- 立ち寄り順のハッシュ
  drive_minutes  integer not null,       -- 走行時間（乗降時間は含まない）
  distance_km    double precision,
  computed_at    timestamptz not null default now(),
  primary key (facility_code, route_hash)
);

-- ---------- 確認用 ----------
-- select unit_count, target_minutes, max_minutes, stop_minutes, stop_minutes_wc
--   from soge_settings where facility_code = 'cocokaraplus-5526';
