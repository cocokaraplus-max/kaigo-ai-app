-- ============================================================
-- TASUKARU  レク費精算モジュール (おでかけ費用の割り勘/精算)
-- marker: rec-expense-ddl-v3.1
-- 投入先: まず DEV Supabase。本番はリリース時。
--
-- v3 (rec_events / rec_places / rec_expenses / rec_cars) は投入済み。
-- このファイルは v3 の内容を記録として残しつつ、v3.1 の追補
--   (1) rec_events.title      … おでかけのタイトル
--   (2) rec_expenses.target_id … 個別費用の対象者を patient_id(uuid) で保持
--       ※ target_name は表示用として残す。名前だけだと同姓同名で壊れるため。
-- を冪等に適用する。4テーブルとも空のため安全に流せる。
--
-- さらに フラグ rec_expense_enabled を cocokaraplus-5526 / DEMO001 に seed する。
-- ============================================================

-- ---------- v3 本体 (既に投入済み。念のため冪等に再掲) ----------

create table if not exists rec_events (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  event_date     date not null,
  place          text,                          -- 旧: 行き先メモ。v3.1以降は title を使用
  staff_names    jsonb not null default '[]'::jsonb,   -- ["山田", "佐藤"]
  participants   jsonb not null default '[]'::jsonb,   -- [{"patient_id":"uuid","user_name":"..."}]
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
  place_id    uuid not null,
  event_id    uuid not null,
  kind        text not null,                    -- split(割り勘) / flat(一律加算) / individual(個別)
  label       text,
  amount      integer not null default 0,
  excluded    jsonb not null default '[]'::jsonb,  -- ["patient_id", ...] 割り勘/一律から除外
  target_name text,                             -- individual の対象者名(表示用)
  is_car      boolean not null default false,   -- Phase2(車)で使用
  car_meta    jsonb,                            -- Phase2(車)で使用
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

-- ---------- v3.1 追補 (これが今回の必須差分) ----------

alter table rec_events
  add column if not exists title text;

alter table rec_expenses
  add column if not exists target_id uuid;

-- ---------- インデックス ----------

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

-- ---------- フラグ seed (最初から ON) ----------
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

-- 既に行があるが value が 'true' でない場合の是正
update admin_settings set value = 'true'
where key = 'rec_expense_enabled'
  and facility_code in ('cocokaraplus-5526', 'DEMO001')
  and value is distinct from 'true';

-- ---------- 確認用 ----------
-- select column_name from information_schema.columns where table_name='rec_events' order by ordinal_position;
-- select facility_code, key, value from admin_settings where key = 'rec_expense_enabled';
-- select count(*) from rec_events;
