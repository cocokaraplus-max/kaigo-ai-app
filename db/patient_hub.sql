-- ============================================================
-- 利用者情報ハブ（利用者情報ページ拡張） patient-hub-v1
-- 既往歴・家族構成の入力を利用者情報ページに集約し、
-- 職歴・趣味嗜好・好き嫌い・ジェノグラム・病歴タイムライン・
-- ICF付箋・性質推測(AI)を扱うための列/テーブル。
--
-- 実行対象: DEV(DEMO001) → 本番(cocokaraplus-5526) の順で貼る。
-- すべて冪等（create ... if not exists / add column if not exists）。
-- 既存の patient_profiles.medical_history(既往歴) /
-- family_structure(家族構成) は残す（データはそのまま流用）。
-- 参照キーは facility_code + patient_profile_id(=patient_profiles.id を文字列で保持)。
-- ============================================================

-- ---- 1. patient_profiles に手入力の基本情報カラムを追加 ----
alter table patient_profiles add column if not exists job_history text;   -- 職歴
alter table patient_profiles add column if not exists hobbies     text;   -- 趣味・嗜好（OCR取込先）
alter table patient_profiles add column if not exists likes        text;  -- 好きなもの
alter table patient_profiles add column if not exists dislikes     text;  -- 苦手・嫌いなもの

-- ---- 2. 家族構成（ジェノグラム）メンバー ----
-- 既存の family_structure テキストは「備考」として残し、図はこちらに構造化して持つ。
create table if not exists patient_family_members (
  id                 uuid primary key default gen_random_uuid(),
  facility_code      text not null,
  patient_profile_id text not null,           -- patient_profiles.id を文字列で保持
  member_label       text,                    -- 続柄など（例: 本人/夫/長女）。実名は任意
  sex                text,                     -- 'm'(男性/□) / 'f'(女性/○) / '' (不明)
  is_self            boolean default false,    -- 本人（二重枠）
  is_deceased        boolean default false,    -- 故人（×）
  is_cohabiting      boolean default false,    -- 同居（枠で囲う対象）
  age                integer,                  -- 年齢（任意）
  relation_role      text,                     -- 続柄コード（spouse/child/parent/sibling/self/other）
  note               text,                     -- メモ
  pos_x              numeric,                  -- 図上の位置（自由配置用・任意）
  pos_y              numeric,
  sort_order         integer default 0,
  created_at         timestamptz default now(),
  updated_at         timestamptz default now()
);
create index if not exists idx_pfm_fac_pid
  on patient_family_members (facility_code, patient_profile_id);

-- ---- 3. 病歴タイムライン（承認済みイベント） ----
-- ケース記録からAIが候補(status='candidate')を出し、職員が承認(status='approved')して確定。
-- 承認済みだけを利用者ページに表示する。手入力(source='manual')も可。
create table if not exists patient_medical_events (
  id                 uuid primary key default gen_random_uuid(),
  facility_code      text not null,
  patient_profile_id text not null,
  event_ym           text,                     -- 発生年月 'YYYY-MM'（日まで不明でも可）
  event_date         date,                     -- 判明していれば日付
  label              text not null,            -- 例: 脳梗塞 / 大腿骨骨折 / 肺炎で入院
  detail             text,                     -- 補足
  severity           text default 'major',     -- 'major'(大きな出来事) / 'minor'
  source             text default 'manual',    -- 'manual' / 'record_ai'
  source_record_id   text,                     -- 由来のケース記録id（records.id）
  status             text default 'approved',  -- 'candidate'(承認待ち) / 'approved' / 'dismissed'
  approved_by        text,
  approved_at        timestamptz,
  created_at         timestamptz default now()
);
create index if not exists idx_pme_fac_pid
  on patient_medical_events (facility_code, patient_profile_id, status);

-- ---- 4. ICF付箋（利用者ページ上で貼る/剥がす/移動） ----
-- 議事録(meeting_icf_links)から取り込み可。zone は5領域。
create table if not exists patient_icf_stickies (
  id                 uuid primary key default gen_random_uuid(),
  facility_code      text not null,
  patient_profile_id text not null,
  zone               text not null,            -- body/activity/participation/environment/personal/unsorted
  text               text not null,            -- 付箋の本文
  icf_code           text,                     -- ICF第2レベルコード（任意）
  color              text,                     -- 付箋色（任意）
  pos_x              numeric,                  -- 自由配置用（任意）
  pos_y              numeric,
  sort_order         integer default 0,
  source_meeting_id  text,                     -- 取り込み元の会議id（任意）
  created_at         timestamptz default now(),
  updated_at         timestamptz default now()
);
create index if not exists idx_pis_fac_pid
  on patient_icf_stickies (facility_code, patient_profile_id, zone);

-- ---- 5. 性質推測（AIキャッシュ） ----
-- ケース記録から推測した人となり。1利用者1行で上書き（手動再生成）。
create table if not exists patient_personality_cache (
  id                 uuid primary key default gen_random_uuid(),
  facility_code      text not null,
  patient_profile_id text not null,
  traits             text,                     -- タグ（JSON配列文字列 or カンマ区切り）
  summary            text,                     -- 説明文
  source_count       integer default 0,        -- 参照した記録件数
  generated_at       timestamptz default now(),
  unique (facility_code, patient_profile_id)
);
