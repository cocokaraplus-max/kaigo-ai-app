-- ===========================================================
-- shogu-signdate-v1 : 署名の日付を、実際に確認した日に直せるようにする
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★まず【DEV】で通してから本番へ。同じものをそのまま流せます。
--
-- なぜ要るのか
--   過去の年度の計画書を、いまから職員に見てもらって署名をもらうことがある。
--   そのとき署名の日付は【今日】になるが、周知して確認したのは別の日。
--   監査で聞かれるのは「いつ職員に周知したか」なので、そこを直せないと困る。
--
--   ただし、跡を残さずに書き換えられる作りは、記録としての意味を失う。
--   だから【もとの日時・直した人・直した日時】を一緒に持つ。
-- ===========================================================


-- ① 直した跡を残す3つの列
alter table shogu_signs
  add column if not exists signed_at_original timestamptz,
  add column if not exists date_edited_by text,
  add column if not exists date_edited_at timestamptz;


-- ② 確認（3 と返れば正解）
select count(*) as shogu_signdate_cols from information_schema.columns
where table_schema = 'public' and table_name = 'shogu_signs'
  and column_name in ('signed_at_original', 'date_edited_by', 'date_edited_at');
