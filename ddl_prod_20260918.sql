-- ===========================================================
-- 本番（tasukaru / cocokaraplus-5526 の Supabase）へ流すもの
--   2026-09-18 ぶん：運営規程 ＋ 処遇改善加算の書類
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、【1つずつ順に】。
-- ★DEVでは何回かに分けて足した列を、本番では【最初から入った形】でまとめてあります。
--   DEVと同じ中身になります（表・列・索引・RLS）。
-- ★どの文も「もう有れば何もしない」形なので、途中で止まっても流し直せます。
-- ===========================================================


-- ① 運営規程の版
create table if not exists unei_versions (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  service_type text not null default '地域密着型通所介護',
  label text,
  effective_date date,
  head jsonb not null default '[]'::jsonb,
  articles jsonb not null default '[]'::jsonb,
  source_name text,
  note text,
  todokede_id uuid,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);


-- ② 運営規程の並び用
create index if not exists unei_versions_fac_svc_idx on unei_versions (facility_code, service_type, effective_date desc);


-- ③ 運営規程のRLS（★新しく作った表はRLSオフで生まれる）
alter table unei_versions enable row level security;


-- ④ 処遇改善の書類（年度ごと・種類ごと）
--    notified_on … 周知した日。入っていれば、署名はその日で記録される。
--    summary     … 計画書のExcelから読み取った要点。
create table if not exists shogu_docs (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  fiscal_year int not null,
  doc_type text not null default '計画書',
  title text,
  status text not null default '下書き',
  sign_round int not null default 1,
  need_sign boolean not null default true,
  note text,
  published_at timestamptz,
  notified_on date,
  summary jsonb,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);


-- ⑤ 添付した書類
create table if not exists shogu_files (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  doc_id uuid not null references shogu_docs(id) on delete cascade,
  file_name text not null,
  storage_path text not null,
  mime text,
  file_size int,
  uploaded_by text,
  created_at timestamptz not null default now()
);


-- ⑥ 署名
--    sign_round         … 何回目の周知か。書類を差し替えたら1つ増やす。
--    mime               … 取り込んだ署名の種類（JPEG・PNG・PDF）。
--    recorded_by        … 管理者が代わりに入れたときの、その人。
--    signed_at_original … 日付を直したときの、もとの日時（最初の1回だけ）。
create table if not exists shogu_signs (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  doc_id uuid not null references shogu_docs(id) on delete cascade,
  sign_round int not null default 1,
  staff_name text not null,
  signed_at timestamptz not null default now(),
  image_path text,
  mime text,
  note text,
  recorded_by text,
  signed_at_original timestamptz,
  date_edited_by text,
  date_edited_at timestamptz
);


-- ⑦ 一覧の並び用（施設ごとに、年度の新しい順）
create index if not exists shogu_docs_fac_year_idx on shogu_docs (facility_code, fiscal_year desc);


-- ⑧ 添付を引くとき用
create index if not exists shogu_files_doc_idx on shogu_files (doc_id);


-- ⑨ 署名を引くとき用
create index if not exists shogu_signs_doc_idx on shogu_signs (doc_id, sign_round);


-- ⑩ RLS
alter table shogu_docs enable row level security;


-- ⑪ RLS
alter table shogu_files enable row level security;


-- ⑫ RLS
alter table shogu_signs enable row level security;


-- ⑬ 確認（4 と返れば正解：unei_versions / shogu_docs / shogu_files / shogu_signs）
select count(*) as tables_ok from information_schema.tables
where table_schema = 'public'
  and table_name in ('unei_versions', 'shogu_docs', 'shogu_files', 'shogu_signs');


-- ⑭ 念のため、あとから足した列もそろっているか（5 と返れば正解）
select count(*) as cols_ok from information_schema.columns
where table_schema = 'public'
  and ((table_name = 'shogu_docs'  and column_name in ('summary', 'notified_on'))
    or (table_name = 'shogu_signs' and column_name in ('recorded_by', 'mime', 'signed_at_original')));
