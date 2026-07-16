-- ============================================================
-- patient-hub-v1 A: 担当者会議のICF付箋に「できる/できない」区分を追加
-- meeting_icf_links.polarity: 'can'(できる) / 'cannot'(できない・支障) / null
-- 議事録の音声→ICF分類で cannot も拾い、利用者ページ取り込み時に赤で表示するため。
-- 冪等。DEV→本番の順に適用。
-- ============================================================
alter table meeting_icf_links add column if not exists polarity text;
