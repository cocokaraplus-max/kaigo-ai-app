-- ============================================================
-- TASUKARU 送迎: 車の形（アイコン）
-- marker: soge-car-icon-v1
-- 投入先: まず DEV Supabase → 確認後に本番 Supabase
-- 前提: rec_cars がある（車両マスタ）。soge-car-color-v1 で color 列を足してある。
--
-- 【なぜ要るか】
--  HIROさん「名前は全部黒で、名前の前に車の形のアイコンを置いて、それに色を入れよう。
--            ワゴンタイプ、タントのような軽車両、を選べるようにしたい」
--
--  ★色だけだと、色の見分けがつきにくい方には伝わらない。
--    形が違えば、色が分からなくても見分けがつく。
--  ★実際の車に近い形にすると、職員は覚えなくても分かる。
--
-- 【入る値】
--  決まった名前だけ: kei / keibox / wagon / van
--    kei    … 軽（タント・N-BOX など。短い車体にボンネットあり）
--    keibox … 軽バン（エブリイ・ハイゼットなど。ボンネットの無い箱型）
--    wagon  … ワゴン（セレナ・ヴォクシーなど。中くらい）
--    van    … バン（キャラバン・ハイエースなど。長い）
--  空（NULL）なら wagon として出す。
--  ★形そのもの（SVGの絵）はアプリ側の1か所で持つ。
--    あとで絵を描き直すときに、データを触らずに済む。
-- ============================================================

alter table rec_cars add column if not exists body_type text;

comment on column rec_cars.body_type is
  'soge-car-icon-v1 送迎画面のアイコンの形。kei/keibox/wagon/van。空なら wagon';

-- ---------- 確認 ----------
-- 下の1本だけを流すと、列が増えているか見られます。
-- （Supabase の SQL エディタは【最後の1文】の結果しか返しません）
select column_name, data_type, is_nullable
from information_schema.columns
where table_name = 'rec_cars'
  and column_name = 'body_type';
