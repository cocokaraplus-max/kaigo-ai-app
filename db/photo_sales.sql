-- ============================================================
-- photo-sales-v1 : 写真販売（行事写真の管理番号・注文・請求・キタムラ入稿）
--
-- 設計の要点（半年後の自分へ）
--  * 管理番号 photo_no = 「アルバムコード-連番」（例 A012-001）。
--    番号は必ずサーバで採番する。クライアントから番号を受け取ることは無い。
--    unique(facility_code, photo_no) と unique(album_id, seq) の2枚看板で重複を物理的に防ぐ。
--  * 番号は再利用しない。写真を消すときは is_deleted=true にして行は残す（欠番のままにする）。
--    番号の使い回しは「別人の写真が届く」事故に直結するため。
--  * Storage のファイル名も photo_no と同じにする（A012-001.jpg）。
--    DB・画面・ZIP・注文一覧のどこを見ても同じ文字列が出るようにするため。
--  * 単価は注文行に写し取る（unit_price）。あとで単価を変えても、確定済みの請求額が動かない。
--
-- DEV → 本番の順で、Supabase の SQL Editor に貼って実行する。
-- ============================================================

-- 機能フラグ（既定OFF。開発者MENUのトグルで施設ごとに許可する。タイムカードと同じ作法）
alter table facilities
  add column if not exists photo_sales_enabled boolean not null default false;

-- 行事（アルバム）
create table if not exists photo_albums (
  id           uuid primary key default gen_random_uuid(),
  facility_code text not null,
  code         text not null,                 -- 施設内で一意の短いコード（例 A012）。管理番号の頭になる
  title        text not null,                 -- 例「2026年7月 夕食会」
  event_date   date,
  is_closed    boolean not null default false,-- 締めたアルバムは注文・アップロード不可
  created_by   text,
  created_at   timestamptz not null default now()
);
create unique index if not exists uq_photo_albums_code
  on photo_albums (facility_code, code);

-- 写真（1枚 = 1行）
create table if not exists photos (
  id            uuid primary key default gen_random_uuid(),
  facility_code text not null,
  album_id      uuid not null references photo_albums(id) on delete cascade,
  seq           integer not null,             -- アルバム内の連番（1始まり）。サーバ採番
  photo_no      text not null,                -- 管理番号（A012-001）。seq から組み立てた確定値
  storage_path  text not null,                -- 例 cocokaraplus-5526/photos/A012/A012-001.jpg
  url           text not null,
  taken_at      timestamptz,
  uploaded_by   text,
  is_deleted    boolean not null default false, -- 番号を再利用しないための論理削除
  created_at    timestamptz not null default now()
);
-- 重複を物理的に防ぐ2枚看板。採番が競合したら insert が落ちるので、サーバ側で seq+1 して再試行する
create unique index if not exists uq_photos_no
  on photos (facility_code, photo_no);
create unique index if not exists uq_photos_seq
  on photos (album_id, seq);
create index if not exists ix_photos_album on photos (album_id, seq);

-- 注文（利用者1人 × 写真1枚 = 1行。枚数は qty）
create table if not exists photo_orders (
  id            uuid primary key default gen_random_uuid(),
  facility_code text not null,
  photo_id      uuid not null references photos(id) on delete cascade,
  album_id      uuid not null references photo_albums(id) on delete cascade,
  patient_id    uuid not null,                -- patient_profiles.id
  user_name     text not null,                -- 表示用のスナップショット（改名しても注文履歴は当時の名前）
  qty           integer not null default 1 check (qty > 0),
  unit_price    integer not null default 0,   -- 注文時点の単価を写し取る
  ordered_by    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
-- 同じ人が同じ写真を2行持たない。枚数の増減は qty の更新で行う（手動 upsert）
create unique index if not exists uq_photo_orders
  on photo_orders (facility_code, patient_id, photo_id);
create index if not exists ix_photo_orders_album on photo_orders (album_id);
create index if not exists ix_photo_orders_patient on photo_orders (facility_code, patient_id);

-- ============================================================
-- 施設設定（既存 admin_settings。UNIQUE が無いので手動 upsert する既存作法のまま）
--   photo_unit_price : "200"  写真1枚の金額（円）。管理画面から入れるので DDL 不要。
-- ============================================================

-- ============================================================
-- 有効化（弊社のみ。他社は既定OFFのまま）
-- DEV では DEMO001、本番では cocokaraplus-5526 を ON にする。
-- ============================================================
-- DEV で実行:
--   update facilities set photo_sales_enabled = true where facility_code = 'DEMO001';
-- 本番で実行:
--   update facilities set photo_sales_enabled = true where facility_code = 'cocokaraplus-5526';
-- 確認:
--   select facility_code, photo_sales_enabled from facilities order by facility_code;

-- ============================================================
-- 消すとき（DEVのみ）
-- drop table if exists photo_orders;
-- drop table if exists photos;
-- drop table if exists photo_albums;
-- ============================================================
