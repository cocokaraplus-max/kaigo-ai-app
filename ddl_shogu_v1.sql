-- ===========================================================
-- shogu-v1 : 処遇改善加算の書類を保管し、職員に周知して署名をもらう
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★まず【DEV】で通してから本番へ。同じものをそのまま流せます。
--
-- なぜ作るのか
--   処遇改善加算は、計画書を全職員に周知することが要件。
--   令和6年度からは賃金改善の【実績】も周知することが求められる。
--   紙で回すと「誰が見たか」が残らず、監査で説明できない。
--   見せた記録と手書きの署名を、書類と一緒に置いておく。
-- ===========================================================


-- ① 書類（年度ごと・種類ごと）
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
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);


-- ② 添付した書類
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


-- ③ 署名
--    ★sign_round は「何回目の周知か」。書類を差し替えたら1つ増やす。
--      前の署名を消さずに残せるので、いつ誰が何を見たかが後から追える。
create table if not exists shogu_signs (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  doc_id uuid not null references shogu_docs(id) on delete cascade,
  sign_round int not null default 1,
  staff_name text not null,
  signed_at timestamptz not null default now(),
  image_path text,
  note text
);


-- ④ 一覧の並び用（施設ごとに、年度の新しい順）
create index if not exists shogu_docs_fac_year_idx on shogu_docs (facility_code, fiscal_year desc);


-- ⑤ 添付を引くとき用
create index if not exists shogu_files_doc_idx on shogu_files (doc_id);


-- ⑥ 署名を引くとき用
create index if not exists shogu_signs_doc_idx on shogu_signs (doc_id, sign_round);


-- ⑦ RLSを有効にする（★新しく作った表はRLSオフで生まれる）
alter table shogu_docs enable row level security;


-- ⑧ 同じく
alter table shogu_files enable row level security;


-- ⑨ 同じく
alter table shogu_signs enable row level security;


-- ⑩ 確認（3 と返れば正解）
select count(*) as shogu_tables from information_schema.tables
where table_schema = 'public' and table_name in ('shogu_docs', 'shogu_files', 'shogu_signs');
