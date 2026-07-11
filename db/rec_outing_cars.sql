-- ============================================================
-- TASUKARU  レク費精算モジュール Phase2 (車)
-- marker: rec-expense-ddl-v4-cars
-- 投入先: まず DEV Supabase。本番はリリース時。
-- 前提: db/rec_outing.sql (v3.1) 適用済み
--
-- 変更点:
--  (1) rec_expenses.place_id を nullable に
--      車費用は「場所」に紐づかない (イベント直下) ため。
--  (2) rec_events.cars jsonb を追加
--      [{"car_id":uuid|null,"name":"ハイエース","fuel_km_per_l":10.5,
--        "distance_km":42.0,"fuel_price_per_l":175}]
--      複数台対応。車1台につきガソリン/駐車/高速の費用行がぶら下がる。
--  (3) rec_cars (車マスタ) は v3 で作成済み。ここでは索引のみ確認。
--
-- ガソリン代は保存時にサーバが再計算する (距離 ÷ 燃費 × 単価)。
-- rec_expenses.car_meta = {"car_index":0,"type":"gas|parking|highway"}
-- ============================================================

alter table rec_expenses
  alter column place_id drop not null;

alter table rec_events
  add column if not exists cars jsonb not null default '[]'::jsonb;

create index if not exists idx_rec_cars_facility
  on rec_cars (facility_code, is_active, sort_order);

-- ---------- 確認用 ----------
-- select column_name, is_nullable from information_schema.columns
--  where table_name='rec_expenses' and column_name='place_id';
-- select column_name from information_schema.columns
--  where table_name='rec_events' and column_name='cars';
