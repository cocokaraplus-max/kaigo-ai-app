-- sql_ai_usage_v1.sql   marker: ai-usage-meter-v1
--
-- AIの使用量を1回ずつ残す表。
--
-- ★何のために作るか
--   料金プランの差を「AI記録の件数」でつけるのをやめ、【録音の時間】だけで
--   つけると決めた（2026-09-08 HIROさん決め）。その時間を正しく測るための表。
--
-- ★なぜトークン数で持つのか
--   音声は 32トークン＝1秒（Googleの決まり。1分＝1,920トークン）。
--   つまり【実際に課金された量】そのもの。ファイルの長さを推測する必要も、
--   現場と「何分だった」で揉めることもない。
--   分に直すのは読むときにやる。生の数を残しておけば、あとから計算を変えられる。
--
-- ★この表を作っただけでは、まだ何も止まらない。
--   入れるのは「測る」だけ。上限は実データを2週間ほど見てから決める。
--
-- ★DEV と 本番 の両方で流すこと。文は同じ。
-- ★何度流しても同じ（if not exists）。

create table if not exists ai_usage (
  id            bigserial   primary key,
  facility_code text        not null,
  ym            text        not null,          -- '2026-09'。JSTの月で入れる
  kind          text        not null default 'text',   -- audio / image / text
  audio_tokens  integer     not null default 0,
  input_tokens  integer     not null default 0,
  output_tokens integer     not null default 0,
  model         text,                          -- 実際に応答したモデル名
  route         text,                          -- どの画面から呼ばれたか
  created_at    timestamptz not null default now()
);

-- 「その施設の今月ぶん」を引くための索引（上限の判定で毎回使う）
create index if not exists idx_ai_usage_fac_ym
  on ai_usage (facility_code, ym);
-- 期間で見るための索引（あとから分析するとき用）
create index if not exists idx_ai_usage_created
  on ai_usage (created_at);


-- 確認（流したあとに、この1本だけが結果として返る）
select '① 表' as 種類,
  (case when exists (select 1 from information_schema.tables
     where table_name = 'ai_usage')
   then 'あり' else '★無い' end) as 値
union all
select '② いまの行数', (select count(*)::text from ai_usage)
union all
select '③ audio_tokens の型',
  (select data_type from information_schema.columns
    where table_name = 'ai_usage' and column_name = 'audio_tokens');
