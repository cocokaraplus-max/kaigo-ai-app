-- ============================================================
-- TASUKARU  自費曜日ルールに「有効期間」を追加
-- marker: jihi-validfrom-ddl-v1
-- 投入先: まず DEV Supabase。本番はリリース時。
--
-- 【なぜ必要か】
-- 自費/保険の判定は、実績の集計時に patient_jihi_weekdays（曜日ルール）を
-- その場で読んで決めている。このルールには有効期間が無いため、
-- 今日ルールを変えると 過去の月の集計まで遡って変わってしまう。
--   例: 「8月から自費をやめる」と設定 → 6〜7月の自費まで消える
--
-- 要介護度は care_level_history が valid_from を持ち「その日時点の値」を引いている。
-- 自費ルールも同じ形にする。
--
-- 【安全性】
-- 既存の行は valid_from = '1900-01-01' になるので、
-- 今の集計結果は 1件も変わらない。
--
-- valid_from … このルールが有効になった日（この日を含む）
-- valid_to   … 無効になった日（この日を含まない。NULL = 現在も有効）
-- ============================================================

alter table patient_jihi_weekdays
  add column if not exists valid_from date not null default '1900-01-01';

alter table patient_jihi_weekdays
  add column if not exists valid_to date;

create index if not exists idx_pjw_lookup
  on patient_jihi_weekdays (facility_code, patient_id, valid_from);

-- ---------- 確認用 ----------
-- select patient_id, weekday, valid_from, valid_to
--   from patient_jihi_weekdays
--  where facility_code = 'cocokaraplus-5526'
--  order by patient_id, weekday, valid_from;

-- ============================================================
-- 【重要・追記】ユニーク制約の張り替え
-- marker: jihi-validfrom-ddl-v2
--
-- 元の制約 (facility_code, patient_id, weekday) は「曜日ごとに1行」を強制する。
-- 有効期間を持たせると、同じ曜日で期間ごとに複数行が必要になるため、
-- この制約があると履歴を作れず、保存が duplicate key で失敗する。
--
-- 代わりに「同じ期間の重複だけ」を禁止する。
-- ============================================================

alter table patient_jihi_weekdays
  drop constraint if exists patient_jihi_weekdays_facility_code_patient_id_weekday_key;

create unique index if not exists uq_pjw_period
  on patient_jihi_weekdays (facility_code, patient_id, weekday, valid_from);

-- ---------- 確認用 ----------
-- select conname from pg_constraint
--  where conrelid = 'patient_jihi_weekdays'::regclass;
