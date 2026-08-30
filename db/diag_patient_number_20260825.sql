-- =============================================================
-- patient-number-mismatch-diag-20260825
-- 目的: ケース記録閲覧の利用者検索で
--       (1) 同じ人が2件出る  (2) カルテ番号が基本情報と違う
--       の原因と規模を、氏名を一切出さずに数だけで確認する。
-- 使い方: Supabase の SQL Editor に貼って実行（全部 SELECT。書き換えは一切しない）
-- =============================================================

-- ① patients に「同じ氏名の行」が複数ある → 検索で二重に出る原因
select facility_code,
       count(*) as 重複している氏名の数
from (
  select facility_code, user_name
  from patients
  group by facility_code, user_name
  having count(*) > 1
) t
group by facility_code
order by facility_code;


-- ② 番号がズレている人数
--    patients.chart_number (ケース記録の検索が見る)
--    ≠ patient_profiles.patient_number (利用者基本情報が見る)
select pp.facility_code,
       count(*) as 番号がズレている件数
from patient_profiles pp
join patients p
  on  p.facility_code = pp.facility_code
 and p.user_name      = pp.user_name
where coalesce(nullif(btrim(p.chart_number::text), ''), '-')
   <> coalesce(nullif(btrim(pp.patient_number::text), ''), '-')
group by pp.facility_code
order by pp.facility_code;


-- ③ 数字でない chart_number（「臨時」など、自動採番の失敗跡）
select facility_code,
       count(*) as 数字でない番号の件数
from patients
where btrim(chart_number::text) !~ '^[0-9]+$'
group by facility_code
order by facility_code;


-- ④ ふりがなが空の patients 行（検索で「かな無し」で出てくるもの）
select facility_code,
       count(*) as かなが空の件数
from patients
where coalesce(btrim(user_kana), '') = ''
group by facility_code
order by facility_code;


-- ⑤ patients にあるのに patient_profiles に無い行（＝基本情報に存在しない幽霊行）
select p.facility_code,
       count(*) as 幽霊行の件数
from patients p
left join patient_profiles pp
  on  pp.facility_code = p.facility_code
 and pp.user_name      = p.user_name
where pp.id is null
group by p.facility_code
order by p.facility_code;


-- ⑥ 重複行のうち「記録が紐づいている側」を判定するための下ごしらえ。
--    ★消す前に必ずこれを見る。0 でない側を残す必要がある。
--    氏名は出さず、行ID と紐づき件数だけを出す。
select p.id as patients_id,
       p.facility_code,
       (select count(*) from patient_visit_days v where v.patient_id::text = p.id::text) as 曜日設定,
       (select count(*) from vital_daily_includes d where d.patient_id::text = p.id::text) as 当日追加
from patients p
where (p.facility_code, p.user_name) in (
  select facility_code, user_name
  from patients
  group by facility_code, user_name
  having count(*) > 1
)
order by p.facility_code, p.id;
