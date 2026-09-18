-- ===========================================================
-- unei-v1 : 運営規程を【版】で持つ
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★DEVで通してから本番へ。同じものをそのまま流せます。
--
-- なぜ版で持つのか
--   令和6年4月の運営規程から日曜営業の記載が抜け、誰も気づかなかった。
--   前の版が残っていれば、その場で「第5条が変わっています」と出せた。
--   条文を版で持つ、というのはそのための作りです。
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


-- ② 一覧の並び用（施設・サービスごとに、施行日の新しい順）
create index if not exists unei_versions_fac_svc_idx on unei_versions (facility_code, service_type, effective_date desc);


-- ③ RLSを有効にする（★新しく作った表はRLSオフで生まれる）
alter table unei_versions enable row level security;


-- ④ 確認（1 と返れば正解）
select count(*) as unei_tables from information_schema.tables
where table_schema = 'public' and table_name = 'unei_versions';
