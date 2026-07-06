-- ============================================================
-- TASUKARU  担当者会議 ICF分類機能  DDL (idempotent)
-- marker: meetings-ddl-v1
-- 投入先: まず DEV Supabase (DEMO001) の SQL Editor。
--         本番(cocokaraplus-5526)は機能リリース時に同SQLを流す。
-- 依存: icf_codes (icf-master-l2-v1) が先に投入済みであること。
-- ============================================================

-- ------------------------------------------------------------
-- 1) meetings : 会議レコード（録音・文字起こし・議事録）
-- ------------------------------------------------------------
create table if not exists meetings (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  patient_id     uuid,                              -- 対象利用者（任意）
  title          text,
  meeting_date   date,
  audio_path     text,                              -- Supabase Storage の録音パス
  transcript     text,                              -- 文字起こし全文
  minutes        text,                              -- AI生成議事録
  status         text not null default 'recording', -- recording/transcribed/summarized/classified/confirmed
  created_by     text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists idx_meetings_facility      on meetings (facility_code);
create index if not exists idx_meetings_facility_date on meetings (facility_code, meeting_date desc);
create index if not exists idx_meetings_patient       on meetings (patient_id);

-- ------------------------------------------------------------
-- 2) meeting_icf_links : 議事録↔ICFコードの分類結果（付箋1枚 = 1行）
--    - AI初期分類の根拠(source_text)と確信度(confidence)を保持
--    - 人がボード上で動かした結果(board_component, sort_order)を保存
--    - 「人が承認」思想: confirmed で確定管理
--    - 1軸で機能開始。将来の2軸(能力/実行)用カラムを最初から仕込む
-- ------------------------------------------------------------
create table if not exists meeting_icf_links (
  id                    uuid primary key default gen_random_uuid(),
  meeting_id            uuid not null references meetings(id) on delete cascade,
  icf_code              text references icf_codes(code),      -- null許容: 手動メモ付箋(コード未確定)も置ける
  source_text           text,                                 -- 根拠となった議事録該当箇所
  note                  text,                                 -- 付箋上の自由記述(手動追記)
  confidence            text not null default 'auto',         -- auto / needs_review
  confirmed             boolean not null default false,       -- 人が承認したか
  -- ボード状態（人が付箋を動かした結果。AIのicf_codes.componentとは別に保持）
  board_component       text,                                 -- 現在置かれている領域 b/s/d/e
  sort_order            integer not null default 0,           -- 領域内の縦並び
  -- 将来の2軸(ICF公式 qualifier)用。今は未使用・NULLのまま。
  qualifier_capacity    text,                                 -- 能力（支援なしの本来の力）
  qualifier_performance text,                                 -- 実行状況（実生活での現状）
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists idx_micf_meeting    on meeting_icf_links (meeting_id);
create index if not exists idx_micf_board       on meeting_icf_links (meeting_id, board_component, sort_order);
create index if not exists idx_micf_confirmed   on meeting_icf_links (meeting_id, confirmed);

-- ------------------------------------------------------------
-- 3) meeting_settings は新設せず、既存 admin_settings に相乗り。
--    (facility_code + key + value(JSON) パターン)
--    想定キー: meetings_enabled(bool) / meetings_plan_gate('pro')
--    → 別途アプリ側で読み書き。ここではDDL不要。
-- ------------------------------------------------------------

-- 確認用（値は返さない・件数のみ）
-- select count(*) from meetings;
-- select count(*) from meeting_icf_links;
