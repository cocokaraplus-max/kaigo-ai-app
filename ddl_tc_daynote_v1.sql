-- ===========================================================
-- tc-daynote-v1 : 打刻の画面の「この日のメモ」を、ちゃんと保存できるようにする
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★まず【DEV】で通してから【本番】へ。同じものをそのまま流せます。
--
-- なぜ要るのか
--   打刻の修正画面に「修正メモ」の欄はあったが、押す先（保存ボタン）が無く、
--   打刻の保存・追加・削除に相乗りするだけだった。書いても画面には二度と出ない。
--   けれど残したいのは「振替休だが勉強会のみ参加」のような【その日の事情】で、
--   打刻にも休暇にもぶら下がらない。日そのものに付く場所を用意する。
-- ===========================================================


-- ① その日のメモ
create table if not exists timecard_day_notes (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  staff_name text not null,
  work_date date not null,
  note text,
  edited_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);


-- ② 施設＋職員＋日付でひとつ（同じ日に2つメモがある状態を作らない）
create unique index if not exists timecard_day_notes_uniq
  on timecard_day_notes (facility_code, staff_name, work_date);


-- ③ 月の一覧を引くとき用
create index if not exists timecard_day_notes_month_idx
  on timecard_day_notes (facility_code, work_date);


-- ④ RLSを有効にする（★新しく作った表はRLSオフで生まれる）
alter table timecard_day_notes enable row level security;


-- ⑤ 確認（1 と返れば正解）
select count(*) as daynote_table from information_schema.tables
where table_schema = 'public' and table_name = 'timecard_day_notes';
