-- ============================================================
-- TASUKARU  送迎: 運行記録表の「氏名の下に住所」確認用ダミー利用者
-- marker: soge-dummy-dev-addr
--
-- ★★ DEV の Supabase でだけ実行すること。本番では絶対に実行しない。 ★★
--
-- 【なぜ要るか】
--  db/soge_dummy_dev.sql は soge_stops.patient_id を md5('dummy-'||氏名)::uuid で作っており、
--  patient_profiles と結び付いていない。運行記録表(soge-print-addr-v1)は
--  patient_profiles.address を patient_id で引くので、このままでは住所が出ない。
--  そこで「同じUUID・同じ氏名・架空の住所」を持つダミー利用者を patient_profiles に入れる。
--
-- 【中身】
--  完全な架空の氏名・住所。実在の利用者情報は一切含まない。
--  氏名は soge_dummy_dev.sql の12名と同一（UUIDが一致するので住所が紐づく）。
--
-- 【実行順】
--  1) db/soge_dummy_dev.sql   （運行・立ち寄りのダミー）
--  2) db/soge_dummy_dev_addr.sql （このファイル。住所付きダミー利用者）
--  ※ 逆順でも結果は同じ（UUIDが決まっているため）
--
-- 【消し方】（見終わったら必ず消す）
--  delete from soge_stops where facility_code = 'DEMO001' and service_date between '2026-07-01' and '2026-07-31';
--  delete from soge_days  where facility_code = 'DEMO001' and service_date between '2026-07-01' and '2026-07-31';
--  delete from patient_profiles where facility_code = 'DEMO001' and patient_number like 'DUMMY-%';
-- ============================================================

-- ★ DEV の施設コードに合わせて、ここだけ書き換える
create temporary table _p as select 'DEMO001'::text as f_code;

with names(idx, nm, kana, addr) as (
  values
    ( 1, '山田 太郎',   'ヤマダ タロウ',     '東京都品川区西五反田3-12-5 グリーンハイツ201'),
    ( 2, '佐々木 梅子', 'ササキ ウメコ',     '東京都品川区大崎1-4-8'),
    ( 3, '井上 春江',   'イノウエ ハルエ',   '東京都品川区戸越2-9-14 戸越コーポ103'),
    ( 4, '中村 三郎',   'ナカムラ サブロウ', '東京都品川区旗の台5-3-1'),
    ( 5, '小林 千代',   'コバヤシ チヨ',     '東京都品川区中延4-7-22'),
    ( 6, '加藤 文子',   'カトウ フミコ',     '東京都品川区荏原6-11-3 サンハイム505'),
    ( 7, '吉田 昭夫',   'ヨシダ アキオ',     '東京都品川区平塚1-8-16'),
    ( 8, '山口 静江',   'ヤマグチ シズエ',   '東京都品川区小山3-24-7'),
    ( 9, '松本 幸子',   'マツモト サチコ',   '東京都品川区豊町2-15-9 パークサイド302'),
    (10, '清水 とめ',   'シミズ トメ',       '東京都品川区二葉1-6-11'),
    (11, '森 正夫',     'モリ マサオ',       '東京都品川区西大井5-18-2'),
    (12, '池田 きく',   'イケダ キク',       '東京都品川区東中延1-2-20 中延レジデンス406')
)
insert into patient_profiles (id, facility_code, patient_number, user_name, user_name_kana, address)
select
  md5('dummy-' || n.nm)::uuid,          -- soge_dummy_dev.sql の patient_id と同じ作り方
  (select f_code from _p),
  'DUMMY-' || lpad(n.idx::text, 2, '0'),
  n.nm,
  n.kana,
  n.addr
from names n
on conflict (id) do update
   set user_name      = excluded.user_name,
       user_name_kana = excluded.user_name_kana,
       address        = excluded.address;

-- ---------- 確認 ----------
-- 立ち寄りの patient_id と、ダミー利用者が正しく突合しているか（12件出れば成功）
select p.user_name, p.address, count(s.id) as 立寄件数
  from patient_profiles p
  left join soge_stops s
    on s.patient_id = p.id
   and s.facility_code = (select f_code from _p)
   and s.service_date between '2026-07-01' and '2026-07-31'
 where p.facility_code = (select f_code from _p)
   and p.patient_number like 'DUMMY-%'
 group by p.user_name, p.address
 order by p.user_name;
