-- =============================================================================
-- goal-valid-from-v1 : 目標の変更に「適用日」を持たせる
--
--   ★このSQLはHIROさんの手で流してください。こちらからは流しません。
--   ★決まりどおり、コードより先にこれを流します。
--   ★まず DEV(DEMO001) で流して確かめてから、本番へ。
--   ★何度流しても同じ結果になります。
--
--   作成 2026-08-28
--
-- ── なぜ要るか ──────────────────────────────────────────────────────────
--   いまの goal_history には「いつから有効か」がありません。
--   代わりに year_month（どの月の画面で操作したか）で代用しているため、
--   7月の画面から直すと8月の評価に反映されない、ということが起きました。
--   （2026-08-28・難波節子さんの件）
--
--   介護度はすでに care_level_history が valid_from を持っていて、
--   「月末時点で有効な値」を取り出す形になっています。目標も同じ形にします。
--
-- ── 決めたこと（HIROさん判断・2026-08-28）──────────────────────────────
--   ・評価画面からの変更   → 適用日は【評価月の翌月1日】
--                            7月の評価なら 8/1。8月に7月の評価をしても 8/1。
--                            いつ操作したかに左右されない。
--   ・利用者基本情報からの変更 → 職員が適用日を指定する（月の途中の変更）
--   ・どちらも履歴に残し、画面で見られるようにする
-- =============================================================================


-- -----------------------------------------------------------------------------
-- STEP 0. 先に列と型を見る（読むだけ）
--   ★changed_at の型が分からないまま移行SQLを書くと、日付が1日ずれます。
--     この結果を見てから STEP 2 を流してください。
-- -----------------------------------------------------------------------------
select column_name as 列, data_type as 型, is_nullable as 空を許すか
from information_schema.columns
where table_name = 'goal_history'
order by ordinal_position;


-- -----------------------------------------------------------------------------
-- STEP 1. 適用日の列を足す
--   ★足すだけ。既存の行には何も入りません（次のSTEPで埋めます）。
--     この時点ではコードは何も変わらないので、流しても安全です。
-- -----------------------------------------------------------------------------
alter table goal_history add column if not exists valid_from date;

comment on column goal_history.valid_from is
  'この変更が有効になる日。評価画面からの変更は【評価月の翌月1日】。利用者基本情報からの変更は職員が指定した日。goal-valid-from-v1';

-- 月ごとの目標を引くときに使う
create index if not exists idx_goal_history_valid
  on goal_history (facility_code, user_name, valid_from);


-- -----------------------------------------------------------------------------
-- STEP 2. 既存の履歴に適用日を入れる
--
--   ★これまでの変更はすべて評価画面から行われたものなので、
--     決めたとおり【評価月の翌月1日】を入れます。
--   ★year_month が入っていない行は、変更した日を適用日とみなします。
--     （STEP 0 で changed_at の型を見てから、下の2つのどちらかを選んでください）
-- -----------------------------------------------------------------------------

-- 2-a) year_month がある行（ほとんどはこちら）
update goal_history
   set valid_from = (to_date(year_month || '-01', 'YYYY-MM-DD') + interval '1 month')::date
 where valid_from is null
   and year_month ~ '^[0-9]{4}-[0-9]{2}$';


-- 2-b) year_month が無い行。★STEP 0 の結果でどちらかを選ぶ
--
--   changed_at が「timestamp with time zone」なら、こちら（日本時間で日付を出す）
--
-- update goal_history
--    set valid_from = (changed_at at time zone 'Asia/Tokyo')::date
--  where valid_from is null and changed_at is not null;
--
--   changed_at が「timestamp without time zone」なら、こちら
--
-- update goal_history
--    set valid_from = changed_at::date
--  where valid_from is null and changed_at is not null;


-- -----------------------------------------------------------------------------
-- STEP 3. 入ったことを確かめる（読むだけ）
-- -----------------------------------------------------------------------------
select count(*)                                   as 履歴の全件数,
       count(valid_from)                          as 適用日が入った件数,
       count(*) - count(valid_from)               as まだ空の件数,
       min(valid_from)                            as 一番古い適用日,
       max(valid_from)                            as 一番新しい適用日
from goal_history
where facility_code = 'cocokaraplus-5526';


-- 難波節子さんの履歴で、狙いどおりになっているかを見る
select year_month                        as 評価月,
       valid_from                        as 適用日,
       left(coalesce(old_value,''), 28)  as 変更前,
       left(coalesce(new_value,''), 28)  as 変更後,
       changed_by                        as 変更者
from goal_history
where facility_code = 'cocokaraplus-5526'
  and user_name = '難波節子'
  and field = 'short_goal'
order by valid_from, changed_at;

-- 読み方
--   ・評価月 2026-07 の行 → 適用日 2026-08-01
--   ・評価月 2026-08 の行 → 適用日 2026-09-01
--   これで「8月の目標」は、適用日が 8/31 以前で一番新しいもの
--   ＝ 2026-08-01 の行の【変更後】＝「毎日の散歩を続ける」になります。


-- =============================================================================
-- ★このあと（コード側・まだ作っていません）
--
--   1. 月ごとの目標を「適用日が月末以前で最新のもの」から決める
--      （care_level_history の _care_level_at_month_end と同じ形）
--   2. 評価画面からの変更は valid_from = 評価月の翌月1日 で記録する
--   3. 利用者基本情報に「月途中の目標変更」欄（適用日つき）を作る
--   4. 変更するとき、何を破棄していつから反映するかを確認する
--   5. 目標の変更履歴を、利用者基本情報で見られるようにする
--   6. 応急処置（goal-asof-current-month-v1）は役目を終えるので撤去する
-- =============================================================================
