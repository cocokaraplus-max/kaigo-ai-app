-- ===========================================================
-- todokede-v1 : 介護保険課への届出の台帳と保管庫
--
-- ★SupabaseのSQLエディタは【最後の文の結果しか返さない】ので、
--   1つずつ順に流してください。まとめて貼らないこと。
-- ★DEVで通してから本番へ。同じ内容をそのまま流せます。
-- ===========================================================


-- ① 届出の台帳
create table if not exists todokede_records (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  filed_ym text not null,
  filed_date date,
  change_date date,
  effective_date date,
  doc_type text not null default '変更届',
  service_type text,
  summary text,
  status text not null default '提出済',
  note text,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);


-- ② その届出で出した書類
create table if not exists todokede_files (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  record_id uuid not null references todokede_records(id) on delete cascade,
  kind text not null default '提出したもの',
  title text,
  file_name text,
  storage_path text not null,
  file_size bigint,
  mime text,
  uploaded_by text,
  created_at timestamptz not null default now()
);


-- ③ 一覧の並び用（施設ごと・年月の新しい順）
create index if not exists todokede_records_fac_ym_idx on todokede_records (facility_code, filed_ym desc);


-- ④ 届出に付いた書類を引く用
create index if not exists todokede_files_rec_idx on todokede_files (record_id);


-- ⑤ RLSを有効にする（★新しく作った表はRLSオフで生まれる）
alter table todokede_records enable row level security;


-- ⑥ RLSを有効にする
alter table todokede_files enable row level security;


-- ⑦ 確認（2 と返れば正解）
select count(*) as todokede_tables from information_schema.tables
where table_schema = 'public' and table_name in ('todokede_records', 'todokede_files');
