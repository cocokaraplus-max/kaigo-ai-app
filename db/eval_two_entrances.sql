-- ============================================================
-- TASUKARU  月次評価: 担当ごとの入口を2つに分ける
-- marker: eval-two-entrances-v1
-- 投入先: DEV Supabase → 確認後に本番 Supabase
--
-- 【なぜ要るか】
--  いまの評価画面は1枚に全部が並んでいて、
--  自分に関係のない入力欄まで目に入る。
--  担当ごとに入口を分けて、必要な欄だけ見えるようにする。
--
--    評価担当者     … 目標の達成状況、モニタリング、新規目標、体重などの測定値
--    機能訓練指導員 … 身体評価（元データ・AI生成）
--    どちらも       … 評価者、介護区分、
--                     「訓練による変化」「課題とその要因」（誰でも直せる）
--
-- 【2人が同時に入ることがある】
--  ★これが設計の要。2026-08-26 に編集ロックを直したばかりで、
--    いまのロックは【記録まるごと】に掛かる。
--    入口を分けただけだと、後から保存したほうが必ず弾かれる。
--  → ロックを【入口ごと】に持たせる。列を2組足す。
--  ★いまの editing_by / editing_started_at は【消さない】。
--    入口を分ける前の画面がまだ動いているため。
--    移行が終わってから片付けること。
--
-- 【材料の欄を2つに分ける】
--  AI生成の材料（元データ）は、いまは1つの欄。
--  2人が同時に書くと【片方の文章が消える】。同じ列だから、
--  送った項目だけを更新する仕組みでは守れない。
--  → 担当ごとに別の列にする。同時に書いてもぶつからない。
--     互いの内容は画面で読める。AI生成には【両方】を渡す。
--
--  ★ source_data は名前を変えずに【機能訓練指導員の材料】として使う。
--    過去のデータがすべてここに入っているため、意味を移すほうが危ない。
--  ★ source_data_eval を新設し、【評価担当者の材料】とする。
--    セルフ評価の取り込み先も、今後はこちら。
--    ・過去に取り込んだぶんは source_data に残る（消さない・移さない）。
--      どちらもAI生成に渡すので、実害はない。
-- ============================================================

alter table patient_evaluations
  -- 評価担当者が集めた材料（聴取した達成状況・疼痛など、セルフ評価の取り込み）
  add column if not exists source_data_eval        text,

  -- 入口ごとの編集ロック（'eval' = 評価担当者 / 'ft' = 機能訓練指導員）
  add column if not exists editing_by_eval         text,
  add column if not exists editing_started_at_eval timestamptz,
  add column if not exists editing_by_ft           text,
  add column if not exists editing_started_at_ft   timestamptz;

comment on column patient_evaluations.source_data_eval is
  'eval-two-entrances-v1: 評価担当者が集めた材料。AI生成には source_data と両方を渡す';
comment on column patient_evaluations.editing_by_eval is
  'eval-two-entrances-v1: 評価担当者の入口を開いている職員名（10分でタイムアウト）';
comment on column patient_evaluations.editing_by_ft is
  'eval-two-entrances-v1: 機能訓練指導員の入口を開いている職員名（10分でタイムアウト）';


-- ---------- 確認 ----------
-- ① 列が5つとも足されたか（5行返れば正常）
-- select column_name, data_type
-- from information_schema.columns
-- where table_name = 'patient_evaluations'
--   and column_name in ('source_data_eval','editing_by_eval','editing_started_at_eval',
--                       'editing_by_ft','editing_started_at_ft')
-- order by column_name;

-- ② 既存の行が壊れていないか（新しい列はすべて空のはず）
-- select count(*) as 全体,
--        count(source_data_eval)  as 評価担当者の材料が入っている行,
--        count(editing_by_eval)   as 評価担当者が編集中の行,
--        count(editing_by_ft)     as 機能訓練指導員が編集中の行,
--        count(source_data)       as 既存の材料が入っている行
-- from patient_evaluations;

-- ③ 古いロック列が残っているか（移行が終わるまで消さない）
-- select column_name from information_schema.columns
-- where table_name = 'patient_evaluations'
--   and column_name in ('editing_by','editing_started_at');
