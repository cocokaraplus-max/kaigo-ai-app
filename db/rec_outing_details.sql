-- ============================================================
-- TASUKARU  請求額計算モジュール: 費用の明細
-- marker: rec-expense-ddl-v5-details
-- 投入先: DEV → 本番
-- 前提: db/rec_outing_all.sql (v4) 適用済み
--
-- 変更点:
--   rec_expenses.details jsonb を追加
--     [{"name":"お茶","unit_price":150,"qty":3},
--      {"name":"パン","unit_price":200,"qty":2}]
--   明細がある場合、amount は sum(unit_price × qty) をサーバが再計算して上書きする。
--   明細が空なら、従来どおり amount を直接入力する。
--
-- 「いくらのものを何個買ったか」を記録し、請求内訳を追える状態にするための列。
-- ============================================================

alter table rec_expenses
  add column if not exists details jsonb not null default '[]'::jsonb;

-- ---------- 確認用 ----------
-- select column_name, data_type from information_schema.columns
--  where table_name = 'rec_expenses' and column_name = 'details';
