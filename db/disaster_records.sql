-- app-disaster-sync-v1 : 災害安否記録の同期先テーブル
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行してください（1回だけ）。
-- 端末内(dr_records)の安否記録を /api/disaster_records/sync が一括INSERTします。

create table if not exists public.disaster_records (
    id             bigserial primary key,
    facility_code  text        not null,          -- 施設コード（セッションから）
    patient_name   text        not null,          -- 利用者名（dr_records のキー）
    patient_int_id bigint,                         -- 名寄せ用（patients.id。取れた時のみ）
    status         text        not null,          -- s0/s1/s2/s3/s4
    status_label   text,                           -- 無事/要観察/要救急/避難済/不明
    note           text        default '',         -- メモ
    recorded_by    text,                           -- 記録者名（recorder。無ければログイン者名）
    recorded_at    timestamptz,                    -- 端末で安否を記録した時刻（at）
    synced_at      timestamptz not null default now(),  -- サーバ到着時刻
    created_at     timestamptz not null default now()
);

-- 施設ごと・新しい順の取り出しを速く
create index if not exists idx_disaster_records_fac_synced
    on public.disaster_records (facility_code, synced_at desc);
