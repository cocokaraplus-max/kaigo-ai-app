-- =============================================================================
-- line-approve-login-v1 : LINE承認ログイン（共有PC向け）
--
--   ★このSQLはHIROさんの手で流してください。こちらからは流しません。
--   ★決まりどおり、コードより先にこれを流します。
--   ★何度流しても同じ結果になります（if not exists）。
--   ★DEV(DEMO001)で流して確かめてから、本番へ。
--
--   作成 2026-08-28
-- =============================================================================


-- -----------------------------------------------------------------------------
-- ① login_devices : ログインに使える端末の登録
--
--   打刻端末(timecard_devices)と同じ考え方。端末が申請し、管理者が許可する。
--   ★許可された端末だけが、職員名の一覧を出せる／承認ログインを使える。
--     これが無いと、URLを知っている人が誰でも職員名を並べられてしまう。
-- -----------------------------------------------------------------------------
create table if not exists login_devices (
  id            bigserial   primary key,
  facility_code text        not null,
  device_token  text        not null,               -- 端末のブラウザが持つ印
  device_label  text        not null default '新しい端末',  -- 「事務所PC（受付）」など

  -- ★既定は共有(true)。
  --   設定し忘れた端末が入りっぱなしにならないよう、安全な側に倒す。
  --   true  = 共有 = 30分さわらなければ自動ログアウト
  --   false = 専用 = 自動ログアウトしない（セッションは30日）
  is_shared     boolean     not null default true,
  kind_set_by   text,                               -- 共有/専用を決めた職員名
  kind_set_at   timestamptz,                        -- 未設定(null)なら、ログイン後に聞く

  -- ★管理者が許可するまで使えない。個人の端末も同じ。
  is_active     boolean     not null default false,
  approved_by   text,
  approved_at   timestamptz,
  revoked_at    timestamptz,                        -- 取り消した日時（記録として残す）

  last_used_at  timestamptz,
  created_at    timestamptz not null default now(),

  unique (facility_code, device_token)
);

create index if not exists idx_login_devices_fc
  on login_devices (facility_code, is_active);


-- -----------------------------------------------------------------------------
-- ② login_requests : 承認待ちのログイン要求
--
--   ★鍵を2本に分けているのが肝。
--     poll_token    … PC側だけが持つ。これでしかセッションを作れない
--     approve_token … LINEに送る。これでは【ログインできない】
--     こうしておくと、LINEのメッセージを人に転送されても乗っ取られない。
--
--   ★check_code(4桁) は、画面とLINEの両方に出す。
--     番号が同じことを見てから押してもらう。これが無いと、
--     別人が自分の名前で入ろうとしたのを、うっかり承認してしまう。
-- -----------------------------------------------------------------------------
create table if not exists login_requests (
  id            bigserial   primary key,
  facility_code text        not null,
  staff_name    text        not null,
  device_token  text        not null,

  poll_token    text        not null,               -- PC側の鍵
  approve_token text        not null,               -- LINE側の鍵（ログインには使えない）
  check_code    text        not null,               -- 画面とLINEに出す4桁

  -- pending  … 承認待ち
  -- approved … 承認された（まだPCが引き換えていない）
  -- used     … PCがセッションを受け取った（もう使えない）
  -- denied   … 「心当たりがない」を押された
  -- expired  … 期限切れ
  status        text        not null default 'pending',

  requested_ip  text,                               -- あとで不審な要求を追えるように
  user_agent    text,
  expires_at    timestamptz not null,               -- 3分後
  decided_at    timestamptz,
  created_at    timestamptz not null default now(),

  unique (poll_token),
  unique (approve_token)
);

create index if not exists idx_login_requests_lookup
  on login_requests (facility_code, staff_name, status);

-- 期限切れの掃除で使う
create index if not exists idx_login_requests_exp
  on login_requests (expires_at);


-- -----------------------------------------------------------------------------
-- ③ draft_autosaves : 書きかけの一時退避
--
--   ★共有PCは30分で自動ログアウトする。書きかけの記録が消えると現場が困る。
--     入力中に数秒おきに退避し、同じ人が入り直したときだけ戻す。
--
--   ★別の人が入ったときには出さない。staff_name で必ず絞ること。
--     共有PCなので、ここを間違えると他人の書きかけが見えてしまう。
--
--   ★中身は利用者の記録そのもの。通常の記録と同じ慎重さで扱う。
--     7日たっても戻されなければ捨てる（掃除の処理を別途入れる）。
-- -----------------------------------------------------------------------------
create table if not exists draft_autosaves (
  id            bigserial   primary key,
  facility_code text        not null,
  staff_name    text        not null,               -- ★この人にしか見せない

  -- 何の書きかけか。画面＋対象で一意にする。
  -- 例: 'record:2026-08-28:<patient_id>' / 'evaluation:2026-08:<user_name>'
  form_key      text        not null,

  payload       jsonb       not null,               -- 入力欄の中身
  device_token  text,                               -- どの端末で書いていたか（参考）

  updated_at    timestamptz not null default now(),
  created_at    timestamptz not null default now(),

  unique (facility_code, staff_name, form_key)      -- 同じ書きかけは1件だけ持つ
);

create index if not exists idx_draft_autosaves_owner
  on draft_autosaves (facility_code, staff_name);

-- 掃除で使う
create index if not exists idx_draft_autosaves_updated
  on draft_autosaves (updated_at);


-- =============================================================================
-- 確認（流したあとに、これも流して結果を見せてください）
-- =============================================================================
select table_name,
       (select count(*) from information_schema.columns c
         where c.table_name = t.table_name) as 列数
from information_schema.tables t
where table_name in ('login_devices','login_requests','draft_autosaves')
order by table_name;


-- =============================================================================
-- ★確かめていないこと
--
--   このリポジトリの他の表で RLS(行レベルセキュリティ)を使っているかどうかを、
--   こちらでは確認していません。
--   他の表に RLS とポリシーが付いているなら、この3本にも同じものが要ります。
--   Supabase の Table Editor で既存の表（staffs など）の RLS 設定を見て、
--   付いていれば教えてください。合わせたポリシーを書きます。
-- =============================================================================
