-- ============================================================
-- TASUKARU 送迎: 人を別の車へ移した記録
-- marker: soge-move-v1
-- 投入先: まず DEV Supabase → 確認後に本番 Supabase
-- 前提: db/soge_routes.sql 適用済み（soge_stops がある）
--
-- 【なぜ要るか】
--  これまで「この人を別の車に移す」手段が【どこにも無かった】。
--  直前に乗せ替えたいときは、臨時便を作るか、その日を丸ごと作り直す
--  （＝打刻も臨時便も全部消える）しかなかった。現場では使えない。
--
-- 【なぜ記録を残すか】
--  HIROさんの決め：確定済みの日・過ぎた日でも直せるようにする。
--  過ぎた日の運行表は【実際にどう走ったか】の記録で、月の記録表の元になる。
--  それを後から書き換えられるようにする以上、
--  「いつ・誰が・どこから移したか」が残っていないと、
--  あとで数字が合わないときに何が起きたのか誰にも説明できない。
--  ★消すのではなく足すだけなので、既存のデータは何も変わらない。
-- ============================================================

alter table soge_stops add column if not exists moved_at   timestamptz;
alter table soge_stops add column if not exists moved_by   text;
alter table soge_stops add column if not exists moved_from text;
-- moved_from … 移す前の「車名 / 便名」を、そのときの文字で残す。
--   ★車両マスタが後で変わっても崩れないよう、IDではなく【当時の表示名】を持つ。
--     soge_days.vehicle_name が同じ考え方で作られているのに合わせる。

comment on column soge_stops.moved_at   is 'soge-move-v1 別の車へ移した日時';
comment on column soge_stops.moved_by   is 'soge-move-v1 移した職員';
comment on column soge_stops.moved_from is 'soge-move-v1 移す前の車名/便名（当時の表示）';

-- ---------- 確認 ----------
-- 下の1本だけを流すと、3列が増えているか見られます。
-- （Supabase の SQL エディタは【最後の1文】の結果しか返しません）
select column_name, data_type
from information_schema.columns
where table_name = 'soge_stops'
  and column_name in ('moved_at', 'moved_by', 'moved_from')
order by column_name;
