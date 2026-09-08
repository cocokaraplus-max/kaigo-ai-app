-- sql_line_multi_patient_v1.sql   marker: line-multi-patient-v1
--
-- 1つのLINEアカウントに、複数の利用者を紐付けられるようにする。
-- （娘様がご両親2人ぶんの連絡帳を受け取る、など）
--
-- いまは line_friends が「LINEアカウント1行＝利用者1人」しか持てない。
-- 紐付けだけを別の表に切り出して、1行＝1つの関係にする。
--
-- ★型は information_schema で確かめてから書いた（2026-09-08）。
--     line_friends.patient_id   … uuid
--     patient_profiles.id       … uuid
--   なので patient_id は uuid。text にすると照合できない。
--   （renraku_notes.patient_id は text だが、この表とは関係しない）
--
-- ★流す順番: このSQLが【先】。app.py のパッチはそのあと。
--   逆にすると、送信先を引く先の表が無くて【連絡帳が誰にも送れなく】なる。
--   （パッチ側にも保険を入れるが、順番を守るのがいちばん確実）
--
-- ★DEV と 本番 の両方で流すこと。文は同じ。
-- ★何度流しても同じ（if not exists / on conflict do nothing）。
--   流しただけでは今までと1つも動きが変わらない（読む側がまだ居ないため）。

create table if not exists line_friend_patients (
  id            bigserial   primary key,
  facility_code text        not null,
  line_user_id  text        not null,
  patient_id    uuid        not null,
  linked_by     text,
  created_at    timestamptz not null default now(),
  constraint line_friend_patients_uniq
    unique (facility_code, line_user_id, patient_id)
);

-- 「この利用者に紐付いているのは誰か」を引くための索引（連絡帳の送信で毎回使う）
create index if not exists idx_lfp_fac_patient
  on line_friend_patients (facility_code, patient_id);
-- 「このLINEアカウントは誰を担当しているか」を引くための索引（管理画面の一覧）
create index if not exists idx_lfp_fac_user
  on line_friend_patients (facility_code, line_user_id);

-- いまの紐付けを引っ越す。★元の line_friends は消さない。
--   パッチ側の保険（新しい表が読めないときは元の列を見る）が効くようにするため。
insert into line_friend_patients (facility_code, line_user_id, patient_id, linked_by)
select facility_code, line_user_id, patient_id, linked_by
  from line_friends
 where patient_id is not null
   and status = 'linked'
on conflict on constraint line_friend_patients_uniq do nothing;


-- 確認（流したあとに、この1本だけが結果として返る）
select '① 表' as 種類,
  (case when exists (select 1 from information_schema.tables
     where table_name = 'line_friend_patients')
   then 'あり' else '★無い' end) as 値
union all
select '② 引っ越し元（line_friends の linked）',
  (select count(*)::text from line_friends
    where patient_id is not null and status = 'linked')
union all
select '③ 引っ越し先（line_friend_patients）',
  (select count(*)::text from line_friend_patients)
union all
select '④ 2人以上を担当しているLINEアカウント',
  (select count(*)::text from (
     select line_user_id from line_friend_patients
      group by facility_code, line_user_id having count(*) > 1) x)
union all
select '⑤ patient_id の型',
  (select data_type from information_schema.columns
    where table_name = 'line_friend_patients' and column_name = 'patient_id');
