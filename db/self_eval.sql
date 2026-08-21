-- ============================================================
-- 利用者セルフ評価（タブレット） self-eval-v1
--
-- 利用者本人がタブレットで目標の達成度を答える。
-- 設計は README.md の self-eval-design-2026-08-20 の節を読むこと。
--
-- 実行対象: DEV(DEMO001) → 本番(cocokaraplus-5526) の順で貼る。
-- すべて冪等（create ... if not exists / add column if not exists）。
-- ★デプロイより先に、必ずこれを流すこと。
-- ============================================================

-- ---- 1. 1回の実施＝1行 ----
create table if not exists patient_self_evaluations (
  id                 uuid primary key default gen_random_uuid(),
  facility_code      text not null,
  patient_profile_id text not null,          -- patient_profiles.id を文字列で保持
  user_name          text,                   -- 表示用
  target_ym          text,                   -- 対象月 'YYYY-MM'
  -- draft = 利用者が回答中 / answered = 回答終了・職員確認待ち / confirmed = 職員が確定
  status             text not null default 'draft',
  started_by         text,                   -- 開始した職員
  started_at         timestamptz default now(),
  answered_at        timestamptz,            -- 利用者の回答が終わった時刻
  confirmed_by       text,
  confirmed_at       timestamptz,
  staff_note         text,                   -- 職員の総括メモ
  created_at         timestamptz default now(),
  updated_at         timestamptz default now()
);
create index if not exists idx_pse_fac_status
  on patient_self_evaluations (facility_code, status);
create index if not exists idx_pse_fac_pid
  on patient_self_evaluations (facility_code, patient_profile_id);

-- ---- 2. 質問と回答（1問＝1行） ----
create table if not exists patient_self_eval_answers (
  id               uuid primary key default gen_random_uuid(),
  facility_code    text not null,
  evaluation_id    uuid not null,
  seq              integer not null,          -- 表示順（1始まり）
  question         text not null,             -- 職員が確認・修正したあとの質問文
  goal_kind        text,                      -- 'short' / 'long' / 'other'
  icf_zone         text,                      -- body/activity/participation/environment/personal
  source_note      text,                      -- どの材料から作ったか（職員向け。利用者には出さない）
  score            integer,                   -- 0〜10。未回答は null
  choice           text,                      -- 'no' / 'mid' / 'ok'
  reason_mode      text,                      -- 'write' / 'voice' / 'skip'
  reason_text      text,
  reason_audio_url text,
  answered_at      timestamptz,
  created_at       timestamptz default now(),
  updated_at       timestamptz default now()
);
create index if not exists idx_psea_eval
  on patient_self_eval_answers (evaluation_id, seq);

-- ---- 3. タブレットの解除コード（4桁）----
-- ★平文で保存しない。sha256(facility_code + ':' + pin) を入れる。
create table if not exists facility_kiosk_pins (
  facility_code text primary key,
  pin_hash      text not null,
  updated_by    text,
  updated_at    timestamptz default now()
);

-- ---- 4. ペンでの手書き（self-eval-pen-v1）----
-- 利用者はタブレットのキーボード（フリック入力）が使えない。
-- 紙に書くのと同じようにペンで書いてもらい、画像として残す。
-- ★入れるのは Storage の【パス】であって、公開URLではない。
--   手書きは本人が書いた要配慮個人情報。URLを知られたら誰でも見られる状態にはしない。
--   表示は職員ログインが必要な /self-eval/reason-image/<設問ID> を通す。
alter table patient_self_eval_answers
  add column if not exists reason_image_path text;
