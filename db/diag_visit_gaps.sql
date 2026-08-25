-- ============================================================
-- diag_visit_gaps.sql  （visit-unknown-not-transfer-v1 の見張り役）
--
-- 何のためのSQLか
--   来所記録(visit_records)は、バイタルを保存したその瞬間に1回だけ判定して書かれる。
--   あとからデータを直しても書き換わらない。だから「そのとき何かがおかしかった」日は、
--   誰も見に行かなければ そのまま残る。
--
--   ★visit-unknown-not-transfer-v1 で「判定できなかった日は書かない」ようにしたので、
--     これからは「誤った振替」ではなく「空欄」として現れる。空欄を見つけるのがこのSQL。
--
-- 使い方
--   Supabase の SQL Editor に貼って実行する。★読むだけ。データは変わらない。
--   月に1度（請求前が良い）と、「振替のはずがない」と現場から言われたときに実行する。
--
-- 氏名は1文字も出ない。出るのは 日付・利用者番号・件数だけ。
-- ============================================================


-- ------------------------------------------------------------
-- ① 抜け：バイタルはあるのに、来所記録が無い日
--    → 判定できなかった日。バイタルを開いて保存し直せば正しく付く。
-- ------------------------------------------------------------
select v.measured_date::date            as 日付,
       pp.patient_number                as 利用者番号,
       count(*)                         as バイタル件数
from vitals v
join patient_profiles pp
  on pp.id::text = v.patient_id
 and pp.facility_code = v.facility_code
left join visit_records vr
  on vr.facility_code = v.facility_code
 and vr.patient_id    = v.patient_id
 and vr.visit_date    = v.measured_date::date
where v.measured_date::date >= current_date - 90
  and vr.id is null
group by v.measured_date::date, pp.patient_number
order by 1 desc, 2;


-- ------------------------------------------------------------
-- ② 化け：予定曜日に入っているのに「振替」になっている日
--    → 今回(2026-08-25)と同じ化け方。過去のぶんもここに出る。
--
--    ★「第N週のみ」の指定がある人は、正しく振替のこともある。
--      第N週指定 の列が {} 以外なら、その人は要確認（誤検知の可能性）。
-- ------------------------------------------------------------
select vr.visit_date                                   as 日付,
       pp.patient_number                               as 利用者番号,
       vd.weekdays                                     as 予定曜日,
       extract(dow from vr.visit_date)::int            as その日の曜日,
       vd.nth_per_day                                  as 第N週指定,
       vr.source                                       as 由来,
       vr.checked_at                                   as 記録された時刻
from visit_records vr
join patient_profiles pp
  on pp.id::text = vr.patient_id
 and pp.facility_code = vr.facility_code
join patients p
  on p.facility_code = pp.facility_code
 and p.user_name     = pp.user_name
join patient_visit_days vd
  on vd.facility_code = pp.facility_code
 and vd.patient_id    = p.id::text
where vr.status = 'transfer'
  and strpos(vd.weekdays, extract(dow from vr.visit_date)::int::text) > 0
order by vr.visit_date desc, pp.patient_number;


-- ------------------------------------------------------------
-- ③ 逆の化け：予定曜日に入っていないのに「出席」になっている日
--    → 本来なら振替のはずが出席で通っている。件数が多ければ設定のズレを疑う。
-- ------------------------------------------------------------
select vr.visit_date                                   as 日付,
       pp.patient_number                               as 利用者番号,
       vd.weekdays                                     as 予定曜日,
       extract(dow from vr.visit_date)::int            as その日の曜日
from visit_records vr
join patient_profiles pp
  on pp.id::text = vr.patient_id
 and pp.facility_code = vr.facility_code
join patients p
  on p.facility_code = pp.facility_code
 and p.user_name     = pp.user_name
join patient_visit_days vd
  on vd.facility_code = pp.facility_code
 and vd.patient_id    = p.id::text
where vr.status = 'present'
  and strpos(vd.weekdays, extract(dow from vr.visit_date)::int::text) = 0
order by vr.visit_date desc, pp.patient_number;


-- ------------------------------------------------------------
-- ④ 土台のズレ：氏名で突き合わせられない利用者（人数だけ）
--    → 1人でもいれば、その人は来所記録が付かない。
--      patient_profiles.user_name と patients.user_name の文字列一致で突合しているため、
--      漢字1字・全角半角スペースの違いでも成立しない。
-- ------------------------------------------------------------
select count(*)                                        as 利用者数,
       count(p.id)                                     as 氏名で突合できた人数,
       count(*) - count(p.id)                          as 突合できない人数
from patient_profiles pp
left join patients p
  on p.facility_code = pp.facility_code
 and p.user_name     = pp.user_name
where pp.is_discontinued is not true;
