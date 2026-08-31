-- ============================================================
-- TASUKARU 送迎: 車両の色
-- marker: soge-car-color-v1
-- 投入先: まず DEV Supabase → 確認後に本番 Supabase
-- 前提: rec_cars がある（車両マスタ。送迎と請求額計算が同じマスタを見る）
--
-- 【なぜ要るか】
--  HIROさん「配車、運行画面、記録表などすべてを車両毎に色分けできるようにしたい。
--            視覚でパッとみてどの車両かを認識できるようにしたい」
--
--  ★実際の車の色（白・青・銀…）に合わせられるようにする。
--    自動で割り当てるだけだと「1号車＝緑」を職員が覚えることになる。
--    実物に合っていれば、覚えなくても分かる。
--
-- 【入る値】
--  決まった名前だけ: blue / green / orange / purple / red / teal / brown / pink
--  空（NULL）なら【自動】。車両の並び順で色が決まる。
--  ★色そのもの（#1a73e8 など）は入れない。名前だけにする。
--    画面に出す色はアプリ側の1か所で決める。あとで色味を直すときに、
--    データを触らずに済む。
-- ============================================================

alter table rec_cars add column if not exists color text;

comment on column rec_cars.color is
  'soge-car-color-v1 送迎画面での色。blue/green/orange/purple/red/teal/brown/pink。空なら並び順で自動';

-- ---------- 確認 ----------
-- 下の1本だけを流すと、列が増えているか見られます。
-- （Supabase の SQL エディタは【最後の1文】の結果しか返しません）
select column_name, data_type, is_nullable
from information_schema.columns
where table_name = 'rec_cars'
  and column_name = 'color';
