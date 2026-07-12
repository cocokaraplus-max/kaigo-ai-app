-- ============================================================
-- TASUKARU  送迎モジュール ②週次の送迎表
-- marker: soge-ddl-v2-routes
-- 投入先: まず DEV Supabase。本番はリリース時。
-- 前提: db/soge_settings.sql 適用済み
--
-- 【考え方】
--  soge_routes … 曜日 × 便 ごとの「確定した周り順」。学習の実体。
--                 職員が画面で順番を直すと、ここが上書きされ、次週の初期値になる。
--                 日付ではなく曜日で持つので、毎週そのまま使い回せる。
--
--  soge_days   … その日の実際の運行（車両・運転手・出発時刻）。
--                 週次表を「その日の分」として確定させたもの。臨時便もここに1行。
--
--  soge_stops  … その日の立ち寄り1件（誰を・迎えか送りか・何番目に・何時に着いたか）。
--                 打刻はここに入る。二重押し防止のため arrived_at は
--                 「一度入ったら上書きしない」をサーバ側でも守る（アプリ側で制御）。
--
-- 便(trip)は迎え専用/送り専用ではない。2単位運営の中間便は
-- 「1単位目を送る + 2単位目を迎える」が混在する。だから stop ごとに種別を持つ。
-- ============================================================

-- ---------- 曜日 × 便 の確定した周り順（＝学習の実体） ----------
create table if not exists soge_routes (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  weekday        smallint not null,          -- 0=日 … 6=土（既存表記に合わせる）
  trip_key       text not null,              -- soge_settings.trips[].key（t1/t2/t3）
  vehicle_no     smallint not null default 1,-- 同じ便で複数台使うときの通し番号
  vehicle_id     uuid,                       -- rec_cars.id（車両マスタ）
  driver_name    text,                       -- staffs.staff_name
  stop_order     jsonb not null default '[]'::jsonb,
  -- stop_order = [{"patient_id":"uuid","type":"pickup|dropoff"}, ...]
  --   職員が並べ替えた順がそのまま入る。これが次週の初期値になる。
  updated_at     timestamptz not null default now(),
  updated_by     text
);

create unique index if not exists uq_soge_routes
  on soge_routes (facility_code, weekday, trip_key, vehicle_no);

-- ---------- その日の運行 ----------
create table if not exists soge_days (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  service_date   date not null,
  trip_key       text not null,              -- 定期便は t1/t2/t3、臨時便は 'extra'
  trip_name      text,                       -- 表示名（臨時便は「早退送り」など自由）
  vehicle_no     smallint not null default 1,
  vehicle_id     uuid,
  vehicle_name   text,                       -- 記録として当時の車名を残す（マスタが変わっても崩れない）
  plate_no       text,
  driver_name    text,
  depart_at      time,                       -- 出発予定
  departed_at    timestamptz,                -- 実際の出発（任意）
  returned_at    timestamptz,                -- 帰着
  odo_start      integer,                    -- 走行距離（任意。運行記録表用）
  odo_end        integer,
  is_extra       boolean not null default false,  -- 臨時便（早退・遅刻など）
  extra_reason   text,                       -- 早退 / 遅刻 / 通院 / その他
  note           text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create unique index if not exists uq_soge_days
  on soge_days (facility_code, service_date, trip_key, vehicle_no);

create index if not exists idx_soge_days_date
  on soge_days (facility_code, service_date);

-- ---------- その日の立ち寄り（＝打刻の単位） ----------
create table if not exists soge_stops (
  id             uuid primary key default gen_random_uuid(),
  day_id         uuid not null,              -- soge_days.id
  facility_code  text not null,
  service_date   date not null,
  patient_id     uuid not null,              -- patient_profiles.id
  user_name      text,                       -- 記録として当時の氏名を残す
  stop_type      text not null,              -- pickup(迎え) / dropoff(送り)
  seq            smallint not null default 0,-- 周り順
  planned_at     time,                       -- 到着予定（出発時刻 + 所要時間から自動算出）
  arrived_at     timestamptz,                -- 実際の到着（打刻）。一度入れたら上書きしない
  arrived_by     text,                       -- 打刻した職員
  edited_at      timestamptz,                -- 時刻を手修正したとき
  edited_by      text,
  is_absent      boolean not null default false,  -- 欠席（当日キャンセル）
  note           text,
  created_at     timestamptz not null default now()
);

create unique index if not exists uq_soge_stops
  on soge_stops (day_id, patient_id, stop_type);

create index if not exists idx_soge_stops_day
  on soge_stops (day_id, seq);

create index if not exists idx_soge_stops_date
  on soge_stops (facility_code, service_date);

-- ---------- 確認用 ----------
-- select * from soge_routes where facility_code = 'DEMO001' order by weekday, trip_key;
-- select * from soge_days   where facility_code = 'DEMO001' order by service_date desc limit 10;
