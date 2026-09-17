-- 通所介護計画書：本番用のDDL
-- ★DEVの実物（information_schema / pg_constraint / pg_indexes）から組み立て、
--   列21/6/10/9/20/6 と索引7つが完全に一致することを機械で確かめてある。
-- ★do $$ ... $$; でまとめたら Supabase のエディタで走らなかったので、素の文の並びにした。
-- ★いちばん最後に確認のSELECTを置いてある。実行するとその結果が返る。
--   「6」と出れば成功。

create table if not exists public.tsusho_plans (
    id uuid default gen_random_uuid() not null,
    facility_code text not null,
    patient_id uuid not null,
    created_on date not null,
    planner_name text,
    wish_self text,
    wish_family text,
    wish_family_rel text,
    notes text,
    long_from date,
    long_to date,
    short_from date,
    short_to date,
    explained_on date,
    explainer text,
    consent_signed boolean default false not null,
    consent_proxy_rel text,
    remarks text,
    created_by text,
    created_at timestamptz default now() not null,
    updated_at timestamptz default now() not null,
    constraint tsusho_plans_pkey primary key (id)
  );
create table if not exists public.tsusho_plan_goals (
    id bigserial not null,
    plan_id uuid not null,
    kind text not null,
    seq integer not null,
    body text default ''::text not null,
    created_at timestamptz default now() not null,
    constraint tsusho_plan_goals_pkey primary key (id),
    constraint tsusho_plan_goals_kind_check check (kind = any (array['issue'::text, 'long'::text, 'short'::text])),
    constraint tsusho_plan_goals_plan_id_fkey foreign key (plan_id) references public.tsusho_plans(id) on delete cascade
  );
create table if not exists public.tsusho_plan_services (
    id bigserial not null,
    plan_id uuid not null,
    seq integer default 1 not null,
    time_from text,
    time_to text,
    reward_class text,
    weekdays text,
    pickup boolean,
    dropoff boolean,
    created_at timestamptz default now() not null,
    constraint tsusho_plan_services_pkey primary key (id),
    constraint tsusho_plan_services_plan_id_fkey foreign key (plan_id) references public.tsusho_plans(id) on delete cascade
  );
create table if not exists public.tsusho_plan_programs (
    id bigserial not null,
    plan_id uuid not null,
    service_seq integer default 1 not null,
    seq integer not null,
    time_hm text,
    name text,
    body text,
    note text,
    created_at timestamptz default now() not null,
    constraint tsusho_plan_programs_pkey primary key (id),
    constraint tsusho_plan_programs_plan_id_fkey foreign key (plan_id) references public.tsusho_plans(id) on delete cascade
  );
create table if not exists public.tsusho_monitorings (
    id uuid default gen_random_uuid() not null,
    facility_code text not null,
    patient_id uuid not null,
    year_month text not null,
    plan_id uuid,
    done_on date,
    doer text,
    q1_choice integer,
    q1_note text,
    q2_choice integer,
    q2_note text,
    q3_choice integer,
    q3_note text,
    q4_choice integer,
    q4_note text,
    ai_drafted boolean default false not null,
    confirmed_by text,
    confirmed_at timestamptz,
    created_at timestamptz default now() not null,
    updated_at timestamptz default now() not null,
    constraint tsusho_monitorings_pkey primary key (id),
    constraint tsusho_monitorings_q1_choice_check check (q1_choice = any (array[1, 2, 3])),
    constraint tsusho_monitorings_q2_choice_check check (q2_choice = any (array[1, 2])),
    constraint tsusho_monitorings_q3_choice_check check (q3_choice = any (array[1, 2])),
    constraint tsusho_monitorings_q4_choice_check check (q4_choice = any (array[1, 2])),
    constraint tsusho_monitorings_plan_id_fkey foreign key (plan_id) references public.tsusho_plans(id) on delete set null
  );
create table if not exists public.tsusho_program_templates (
    id bigserial not null,
    facility_code text not null,
    name text default '既定'::text not null,
    items jsonb default '[]'::jsonb not null,
    updated_by text,
    updated_at timestamptz default now() not null,
    constraint tsusho_program_templates_pkey primary key (id)
  );
create unique index if not exists uq_tsusho_plans_fac_pt_on on public.tsusho_plans using btree (facility_code, patient_id, created_on);
create index if not exists ix_tsusho_plans_fac_on on public.tsusho_plans using btree (facility_code, created_on);
create unique index if not exists uq_tsusho_goals_plan_kind_seq on public.tsusho_plan_goals using btree (plan_id, kind, seq);
create unique index if not exists uq_tsusho_services_plan_seq on public.tsusho_plan_services using btree (plan_id, seq);
create unique index if not exists uq_tsusho_programs_plan_svc_seq on public.tsusho_plan_programs using btree (plan_id, service_seq, seq);
create unique index if not exists uq_tsusho_mon_fac_pt_ym on public.tsusho_monitorings using btree (facility_code, patient_id, year_month);
create unique index if not exists uq_tsusho_prog_tpl on public.tsusho_program_templates using btree (facility_code, name);
alter table public.tsusho_plans enable row level security;
alter table public.tsusho_plan_goals enable row level security;
alter table public.tsusho_plan_services enable row level security;
alter table public.tsusho_plan_programs enable row level security;
alter table public.tsusho_monitorings enable row level security;
alter table public.tsusho_program_templates enable row level security;

-- ここまでで作成。下は確認（最後の文の結果が画面に返る）
select count(*) as tsusho_tables
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r' and c.relname like 'tsusho%';
