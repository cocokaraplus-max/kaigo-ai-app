-- ============================================================
-- TASUKARU  請求額計算: レシート読み取り（OCR）
-- marker: rec-receipt-ocr-v1
-- 投入先: DEV Supabase → 確認後に本番 Supabase
--
-- 撮ったレシート画像は Supabase Storage に上げ、その URL を費用行に持たせる。
-- （出納帳の receipts テーブルには入れない。あちらは「未仕訳の領収書」一覧に出てしまい、
--   おでかけのレシートが会計側に混ざるため。）
-- ============================================================

alter table rec_expenses
  add column if not exists receipt_url text;

-- ---------- 確認 ----------
-- select id, label, receipt_url from rec_expenses where receipt_url is not null;
