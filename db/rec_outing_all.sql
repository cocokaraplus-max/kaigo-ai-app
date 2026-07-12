-- ============================================================
-- TASUKARU  請求額計算モジュール (おでかけ費用の割り勘/精算)
-- marker: rec-expense-ddl-all-v4
-- 投入先: 本番 Supabase (DEV は rec_outing.sql + rec_outing_cars.sql で投入済み)
--
-- rec_outing.sql (v3.1) と rec_outing_cars.sql (v4) を1本にまとめたもの。
-- すべて冪等。何度流しても壊れない。上から順に全部実行すること。
--
-- 内容:
--   1. rec_events / rec_places / rec_expenses / rec_cars の4テーブル
--   2. rec_events.title, rec_events.cars, rec_expenses.target_id の追加
--   3. rec_expenses.place_id を nullable に (車費用は場所に紐づかないため)
--   4. インデックス
--   5. フラグ rec_expense_enabled を cocokaraplus-5526 / DEMO001 に seed
--      → この2施設以外には画面もAPIも出ない
-- ============================================================

-- ---------- 1. テーブル ----------

create table if not exists rec_events (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  event_date     date not null,
  place          text,                                  -- 旧: 行き先メモ。現在は title を使用
  staff_names    jsonb not null default '[]'::jsonb,    -- ["山田", "佐藤"]
  participants   jsonb not null default '[]'::jsonb,    -- [{"patient_id":"uuid","user_name":"..."}]
  memo           text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  is_deleted     boolean not null default false
);

create table if not exists rec_places (
  id          uuid primary key default gen_random_uuid(),
  event_id    uuid not null,
  place_name  text not null default ''::text,
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now()
);

create table if not exists rec_expenses (
  id          uuid primary key default gen_random_uuid(),
  place_id    uuid,                                     -- 車費用は NULL
  event_id    uuid not null,
  kind        text not null,                            -- split(割り勘) / flat(一律加算) / individual(個別)
  label       text,
  amount      integer not null default 0,
  excluded    jsonb not null default '[]'::jsonb,       -- ["patient_id", ...] 割り勘/一律から除外
  target_name text,                                     -- individual の対象者名(表示用)
  is_car      boolean not null default false,
  car_meta    jsonb,                                    -- {"car_index":0,"type":"gas|parking|highway"}
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now()
);

create table if not exists rec_cars (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  name           text not null,
  fuel_km_per_l  numeric,
  is_active      boolean not null default true,
  sort_order     integer not null default 0,
  created_at     timestamptz not null default now()
);

-- ---------- 2. 列の追加 (既存テーブルがある場合の追補) ----------

alter table rec_events
  add column if not exists title text;

alter table rec_events
  add column if not exists cars jsonb not null default '[]'::jsonb;
  -- [{"car_id":uuid|null,"name":"ハイエース","fuel_km_per_l":10.5,
  --   "distance_km":42.6,"fuel_price_per_l":175,
  --   "origin":"出発地の住所","round_trip":true}]

alter table rec_expenses
  add column if not exists target_id uuid;

-- ---------- 3. 車費用は場所に紐づかない ----------

alter table rec_expenses
  alter column place_id drop not null;

-- ---------- 4. インデックス ----------

create index if not exists idx_rec_events_lookup
  on rec_events (facility_code, event_date desc);

create index if not exists idx_rec_places_event
  on rec_places (event_id, sort_order);

create index if not exists idx_rec_expenses_event
  on rec_expenses (event_id, sort_order);

create index if not exists idx_rec_expenses_place
  on rec_expenses (place_id, sort_order);

create index if not exists idx_rec_cars_facility
  on rec_cars (facility_code, is_active, sort_order);

-- ---------- 5. フラグ seed (最初から ON) ----------
-- admin_settings は (facility_code, key) にユニーク制約が無いため NOT EXISTS で冪等化する。

insert into admin_settings (facility_code, key, value)
select 'cocokaraplus-5526', 'rec_expense_enabled', 'true'
where not exists (
  select 1 from admin_settings
  where facility_code = 'cocokaraplus-5526' and key = 'rec_expense_enabled'
);

insert into admin_settings (facility_code, key, value)
select 'DEMO001', 'rec_expense_enabled', 'true'
where not exists (
  select 1 from admin_settings
  where facility_code = 'DEMO001' and key = 'rec_expense_enabled'
);

update admin_settings set value = 'true'
where key = 'rec_expense_enabled'
  and facility_code in ('cocokaraplus-5526', 'DEMO001')
  and value is distinct from 'true';

-- ---------- 確認用 ----------
-- 実行後、これを流して 2行 true が返れば成功:
--   select facility_code, key, value from admin_settings where key = 'rec_expense_enabled';
-- 列の確認:
--   select table_name, column_name, is_nullable from information_schema.columns
--    where table_name in ('rec_events','rec_places','rec_expenses','rec_cars')
--    order by table_name, ordinal_position;
