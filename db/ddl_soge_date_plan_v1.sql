-- ============================================================
-- TASUKARU  送迎モジュール ⑤「この日だけの配車」
-- marker: soge-date-plan-v1
-- 投入先: まず DEV Supabase。動作を見てから本番。
-- 前提: db/soge_routes.sql 適用済み
-- （HIROさん 2026-08-30
--   「配車は日にち毎に設定することもできるようにしよう。
--     曜日だけでなく、この日だけはこの配車でいこう、とできるようにしたい」）
--
-- 【考え方】
--   soge_routes      … 曜日ごとの【いつもの配車】。これまでどおり。基本形。
--   soge_date_plans  … 「この日は、いつもと違う配車にする」という【宣言】。1日1行。
--   soge_date_routes … その日の中身（便 × 車 ごとの周り順）。soge_routes と同じ形。
--
--   運行画面が当日データを作るときの順番:
--       ① soge_date_plans にその日がある  → soge_date_routes を使う
--       ② 無ければ                        → soge_routes（曜日）を使う  ←これまでどおり
--   ★日付が勝つ。曜日は既定値。
--
-- 【なぜ表を2つに分けるか】
--   中身の表（soge_date_routes）だけでは、
--   「その日は全員送迎なし」という配車を作ったときに【1行も入らない】。
--   行が無いことと、まだ何も決めていないことが、区別できなくなる。
--   ★宣言の表（soge_date_plans）に1行あることを【この日は独自】の印にする。
--     行数ではなく、宣言があるかどうかで判断する。
--
-- 【消さない】
--   過ぎた日付の行も残す。「あの日はどう組んだか」を後から見られる。
--   1日ぶんでも数行しかないので、量は問題にならない。
-- ============================================================


-- ---------- ①「この日は独自の配車にする」という宣言（1日1行） ----------
create table if not exists soge_date_plans (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  service_date   date not null,
  -- 何を下地に作ったか。あとで「なぜこうなっているか」を辿るために残す。
  --   'weekday' … その曜日のいつもの配車をコピーした
  --   'auto'    … その日の顔ぶれで自動で組んだ
  source         text not null default 'weekday',
  note           text,                       -- 「祝日で午後便なし」など、人が書く覚え書き
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  updated_by     text
);

-- ★1施設1日につき1行だけ。二重に作らせない。
create unique index if not exists uq_soge_date_plans
  on soge_date_plans (facility_code, service_date);


-- ---------- ② その日の中身（soge_routes と同じ形。weekday が service_date になっただけ） ----------
create table if not exists soge_date_routes (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  service_date   date not null,
  trip_key       text not null,              -- soge_settings.trips[].key（t1/t2/t3）
  vehicle_no     smallint not null default 1,-- 同じ便で複数台使うときの通し番号
                                             --   0=まだ車が決まっていない / -1=送迎なし
  vehicle_id     uuid,                       -- rec_cars.id（車両マスタ）
  driver_name    text,                       -- staffs.staff_name
  stop_order     jsonb not null default '[]'::jsonb,
  -- stop_order = [{"patient_id":"uuid","type":"pickup|dropoff","nth":0}, ...]
  --   曜日の配車（soge_routes.stop_order）と【まったく同じ形】にすること。
  --   ★形を変えると、コピーするだけで済むはずの所に変換処理が要る。
  updated_at     timestamptz not null default now(),
  updated_by     text
);

-- ★曜日の表と同じ組み合わせで一意にする（weekday → service_date）。
create unique index if not exists uq_soge_date_routes
  on soge_date_routes (facility_code, service_date, trip_key, vehicle_no);

-- その日ぶんをまとめて読むので、日付で引けるようにする。
create index if not exists idx_soge_date_routes_date
  on soge_date_routes (facility_code, service_date);


-- ---------- ③ 行レベルセキュリティ ----------
--   アプリはサービスキーで繋いでいるので、RLSを入れても動きは変わらない。
--   ★入れておくと、万一ほかの鍵で触られたときに読めない。
--   ★ポリシーは作らない（誰にも許可しない）。これで十分。
alter table soge_date_plans  enable row level security;
alter table soge_date_routes enable row level security;


-- ============================================================
-- 確認（流したあとに、これも流して結果を見せてください）
-- ============================================================
select t.table_name,
       (select count(*) from information_schema.columns c
         where c.table_name = t.table_name) as 列数,
       (select relrowsecurity from pg_class where relname = t.table_name) as RLS
from information_schema.tables t
where t.table_name in ('soge_date_plans','soge_date_routes')
order by t.table_name;
