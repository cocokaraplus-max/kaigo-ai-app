-- sql_soge_back_plan_v1.sql   marker: soge-back-plan-v1
--
-- 迎えの立ち寄りを「到着時刻から逆算」するための設定を入れる列。
--   back_plan = false … これまでどおり、全部の便を出発時刻から前向きに計算する
--   back_plan = true  … 「到着」を入れた便では、迎えの立ち寄りを到着時刻から逆算する
--
-- 便ごとの「到着」時刻は soge_settings.trips（JSON列）の中に入るので、
-- そちらに SQL は要らない。要るのはこの1列だけ。
--
-- ★流す順番: このSQLが先。app.py のパッチはそのあと。
--   逆にすると、送迎設定を保存したときに「そんな列は無い」で落ちて、
--   設定画面が保存できなくなる。
--
-- ★DEV と 本番 の両方で流すこと。文は同じ。
-- ★何度流しても同じ（if not exists）。既定は false なので、
--   流しただけでは今までと1つも動きが変わらない。

alter table soge_settings
  add column if not exists back_plan boolean not null default false;

-- 確認（流したあとに、この1本だけが結果として返る）
select
  '① back_plan の列' as 種類,
  (case when exists (
     select 1 from information_schema.columns
      where table_name = 'soge_settings' and column_name = 'back_plan'
   ) then 'あり' else '★無い' end) as 値
union all
select
  '② いま逆算がONの施設の数',
  (select count(*)::text from soge_settings where back_plan is true)
union all
select
  '③ soge_settings の行数',
  (select count(*)::text from soge_settings);
