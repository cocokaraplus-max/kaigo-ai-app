-- ============================================================
-- patient-hub-v1: ICF付箋に「できる/できない」区分を追加
-- polarity: 'can'(できる) / 'cannot'(できない・赤表示) / null(未指定=できる扱い)
-- 冪等。DEV→本番の順に適用。
-- ============================================================
alter table patient_icf_stickies add column if not exists polarity text;
