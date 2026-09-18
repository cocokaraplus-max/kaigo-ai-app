-- ===========================================================
-- shogu-view-v1 : 計画書のExcelから読み取った【要点】を書類に持たせる
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★まず【DEV】で通してから本番へ。同じものをそのまま流せます。
--
-- なぜ要るのか
--   処遇改善計画書は様式2-1〜2-3の3枚に分かれ、列も数十ある。
--   職員がスマホで開いて読めるものではない。
--   取り込んだときに読み取って、職員が知りたい順に並べ直したものを
--   ここへ置いておく。読めなかったときは空のまま（原本はそのまま開ける）。
-- ===========================================================


-- ① 読み取った要点を入れる列
alter table shogu_docs add column if not exists summary jsonb;


-- ② 確認（1 と返れば正解）
select count(*) as shogu_summary_col from information_schema.columns
where table_schema = 'public' and table_name = 'shogu_docs' and column_name = 'summary';
