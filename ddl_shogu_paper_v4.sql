-- ===========================================================
-- shogu-paper-v4 : 紙でもらった確認を、管理者が記録できるようにする
--
-- ★SupabaseのSQLエディタは最後の文の結果しか返さないので、1つずつ順に。
-- ★まず【DEV】で通してから本番へ。同じものをそのまま流せます。
--
-- なぜ要るのか
--   退職した職員は、もうログインできない。けれど在職中に計画書を確認していれば、
--   その記録は要る。監査で見られるのは「そのとき在籍していた全職員に周知したか」で、
--   いま在籍している人だけではない。
--
--   recorded_by … 誰が代わりに入れたか（手書きが無い記録の出どころ）
--   mime        … 取り込んだ署名の種類（JPEG・PNG・PDF）。
--                 決め打ちにすると、PDFを画像として開こうとして真っ黒になる。
-- ===========================================================


-- ① 代わりに入れた人と、取り込んだものの種類
alter table shogu_signs
  add column if not exists recorded_by text,
  add column if not exists mime text;


-- ② 確認（2 と返れば正解）
select count(*) as shogu_paper_cols from information_schema.columns
where table_schema = 'public' and table_name = 'shogu_signs'
  and column_name in ('recorded_by', 'mime');
