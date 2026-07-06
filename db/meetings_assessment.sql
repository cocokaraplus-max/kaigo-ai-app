-- ============================================================
-- TASUKARU  会議: アセスメントシート カラム追補 (idempotent)
-- marker: meetings-assessment-v1
-- 投入先: DEV Supabase (DEMO001) SQL Editor。本番はリリース時。
-- 依存: meetings-ddl-v1 (meetings) が投入済みであること。
-- ============================================================

-- 課題分析標準項目23項目のアセスメントシートを保存。
-- 項目ごとの編集・削除・追加に対応するため、項目配列のJSON文字列を入れる。
--   例: [{"id":1,"heading":"健康状態","body":"...","recorded":true}, ...]
--   recorded=false は「（未記載）」項目。職員が後から手入力で補完可能。
alter table meetings
  add column if not exists assessment text;

-- 確認用（件数のみ）
-- select count(*) from meetings;
