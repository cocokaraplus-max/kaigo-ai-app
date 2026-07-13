-- ============================================================
-- TASUKARU  職員ごとの個人設定
-- marker: staff-settings-v1
-- 投入先: DEV Supabase → 確認後に本番 Supabase
--
-- 【なぜ要るか】
--  これまで個人設定（文字サイズ・ナビ並び順・音）は全部 localStorage だった。
--  端末を変えると消えるし、同じ人が別のタブレットで開くと元に戻る。
--  TOPのアイコン配置・フォルダは作り込む前提なので、消えると困る。
--  そこで「職員 × キー」の汎用の入れ物を1つ作る。今後の個人設定もここに足せる。
--
--  職員の特定は既存コードに合わせて facility_code + staff_name（staffs.id ではない）。
--
-- 【入るキー（予定）】
--  top_style   … 'grid'（アイコン一覧） / 'classic'（従来のTOP）
--  top_layout  … TOPのアイコン配置・フォルダ（JSON文字列）
-- ============================================================

create table if not exists staff_settings (
  id             uuid primary key default gen_random_uuid(),
  facility_code  text not null,
  staff_name     text not null,
  key            text not null,
  value          text,
  updated_at     timestamptz not null default now()
);

create unique index if not exists uq_staff_settings
  on staff_settings (facility_code, staff_name, key);

-- ---------- 確認 ----------
-- select facility_code, staff_name, key, left(coalesce(value,''), 40) from staff_settings;
