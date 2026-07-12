-- ============================================================
-- TASUKARU  送迎: 住所→座標のキャッシュ
-- marker: soge-ddl-v3-geocode
-- 投入先: まず DEV Supabase。本番はリリース時。
--
-- 【なぜキャッシュするか】
--  車両割当と周り順は「施設からの距離」と「方位角（方面）」で決める。
--  そのため利用者の住所を座標に変換する必要があるが、
--  毎週 Geocoding API を叩くのは無駄で費用もかかる。
--
--  住所は滅多に変わらないので、1回変換したら保存しておき、
--  住所が変わった人だけ再変換する（address をハッシュして変更を検知）。
--
-- 【個人情報】
--  住所そのものはここに置かない。座標とハッシュだけ。
--  住所の原本は patient_profiles.address のまま。
-- ============================================================

create table if not exists soge_geocode (
  facility_code  text not null,
  patient_id     uuid not null,              -- patient_profiles.id
  address_hash   text not null,              -- 住所が変わったかの検知用（住所そのものは保存しない）
  lat            double precision not null,
  lng            double precision not null,
  -- 施設から見た位置（毎回計算しなくていいように保存）
  dist_km        double precision,           -- 施設からの直線距離
  bearing        double precision,           -- 施設から見た方位角（0=北, 90=東, 180=南, 270=西）
  geocoded_at    timestamptz not null default now(),
  primary key (facility_code, patient_id)
);

create index if not exists idx_soge_geocode_dist
  on soge_geocode (facility_code, dist_km);

-- ---------- 確認用 ----------
-- select patient_id, round(dist_km::numeric, 2) as km, round(bearing::numeric) as deg
--   from soge_geocode where facility_code = 'cocokaraplus-5526'
--  order by bearing;
