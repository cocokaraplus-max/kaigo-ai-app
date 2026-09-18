-- ===========================================================
-- shogu-notified-v3 : 書類に「周知した日」を持たせる
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★まず【DEV】で通してから本番へ。同じものをそのまま流せます。
--
-- なぜ要るのか
--   過去の年度のぶんを、いまから職員に見てもらって署名をもらうことがある。
--   署名の日を【あとから直す】と、直した跡が残って書き換えたように見える。
--   そうではなく、書類のほうに「いつ周知したか」を持たせる。
--   そうすれば署名は【はじめからその日】で入り、直す場面そのものが無くなる。
--
--   空のままなら、これまでどおり「職員が署名したその日」が入る。
-- ===========================================================


-- ① 周知した日
alter table shogu_docs add column if not exists notified_on date;


-- ② 確認（1 と返れば正解）
select count(*) as shogu_notified_col from information_schema.columns
where table_schema = 'public' and table_name = 'shogu_docs' and column_name = 'notified_on';
