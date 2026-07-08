-- ============================================================
-- TASUKARU  勉強会・会議議事録 マインドマップ カラム追補 (idempotent)
-- marker: staff-minutes-mindmap-v1
-- 投入先: まず DEV Supabase (DEMO001) の SQL Editor。本番はリリース時。
-- 依存: staff-minutes-ddl-v1 (staff_meetings) が投入済みであること。
-- ============================================================

-- マインドマップの元データ(markmap用のMarkdown階層テキスト)を保存。
-- 再描画・再PDF化に使う。中心=会議名、見出しレベルで階層。
alter table staff_meetings
  add column if not exists mindmap text;

-- 確認用（件数のみ）
-- select count(*) from staff_meetings;
