-- vital-daily-include-v1
-- 目的: バイタルの「本日の利用者を追加」を、曜日の恒久設定ではなく【その日だけ】の追加にする。
--       あわせて 午前 / 午後 / 終日 を選べるようにする。
--
-- 既存の vital_daily_excludes（今日だけ削除）と対になるテーブル。
-- patient_id は画面が使うIDをそのまま文字列で持つ（vital_daily_excludes と同じ持ち方）。
--
-- 実行先: Supabase の SQL Editor（まず tasukaru-dev、確認後に本番 kaigo-ai-app）
-- 影響: 新規テーブルの作成のみ。既存テーブルには一切触れない。

create table if not exists public.vital_daily_includes (
    id            bigserial   primary key,
    facility_code text        not null,
    patient_id    text        not null,
    user_name     text,
    include_date  date        not null,
    ampm          text        not null default 'ALL',
    created_by    text,
    created_at    timestamptz not null default now(),
    constraint vital_daily_includes_ampm_chk
        check (ampm in ('AM', 'PM', 'ALL')),
    constraint vital_daily_includes_uniq
        unique (facility_code, patient_id, include_date)
);

create index if not exists vital_daily_includes_lookup
    on public.vital_daily_includes (facility_code, include_date);

-- RLS: 他テーブルと同じ方針。ポリシーは作らない＝サーバー(service_role)からのみ読み書き可能。
alter table public.vital_daily_includes enable row level security;

-- 確認用
-- select * from public.vital_daily_includes limit 1;
