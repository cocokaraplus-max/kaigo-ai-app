-- ============================================================
-- TASUKARU  会議ICFボード: モデル図スロット カラム追補 (idempotent)
-- marker: meetings-board-slot-v1
-- 投入先: DEV Supabase (DEMO001) SQL Editor。本番はリリース時。
-- 依存: meetings-ddl-v1 (meeting_icf_links) が投入済みであること。
-- ============================================================

-- ICF生活機能モデル図レイアウト用の表示スロット。
-- board_component(b/s/d/e = ICF正式構成要素)はそのまま保ち、
-- 図のどのボックスに置くかを board_slot で別管理する。
--   health       : 健康状態(病気・疾患。コードなしメモ付箋)
--   bs           : 心身機能・身体構造 (b/s)
--   activity     : 活動 (d のうち活動寄り)
--   participation: 参加 (d のうち参加寄り)
--   environment  : 環境因子 (e)
--   personal     : 個人因子(年齢・性格など。コードなしメモ付箋)
alter table meeting_icf_links
  add column if not exists board_slot text;

-- 確認用（件数のみ）
-- select count(*) from meeting_icf_links;
