-- patient-safety-notes-v1
-- 利用者情報に「サービス時の重要確認事項」の列を足します。
-- Supabase の SQL Editor に貼り付けて実行してください。
--
-- ★安全です：列を1つ足すだけで、いまのデータは何も変わりません。
-- ★2回実行しても大丈夫です（すでにあれば何もしません）。

alter table patient_profiles
  add column if not exists safety_notes text;

comment on column patient_profiles.safety_notes is
  'サービス時の重要確認事項（アレルギー・ペースメーカー・体内金属など）patient-safety-notes-v1';

-- 確認用：列ができたか見る
select column_name, data_type
  from information_schema.columns
 where table_name = 'patient_profiles'
   and column_name = 'safety_notes';
