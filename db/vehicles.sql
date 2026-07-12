-- ============================================================
-- TASUKARU  車両マスタ（施設共通）
-- marker: vehicles-ddl-v1
-- 投入先: DEV → 本番
--
-- rec_cars を「請求額計算の車」から「施設の車両マスタ」に格上げする。
-- 送迎（運行記録表）と請求額計算の両方が同じマスタを見る。
-- 登録場所は 管理者MENU。
--
-- 追加する列:
--   plate_no  … ナンバー（運行記録表に出す）
--   capacity  … 定員（送迎の車両割当で使う）
--   note      … 備考
-- ============================================================

alter table rec_cars
  add column if not exists plate_no text;

alter table rec_cars
  add column if not exists capacity integer;

alter table rec_cars
  add column if not exists note text;

create index if not exists idx_rec_cars_facility
  on rec_cars (facility_code, is_active, sort_order);

-- ---------- 確認用 ----------
-- select column_name, data_type from information_schema.columns
--  where table_name = 'rec_cars' order by ordinal_position;
