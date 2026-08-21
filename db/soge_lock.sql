-- ============================================================
-- TASUKARU  送迎: 運行表の「確定」
-- marker: soge-lock-v1
-- 投入先: DEV Supabase → 確認後に本番 Supabase
--
-- 【なぜ要るか】
--  これまでは【その日を一度開いた瞬間】に配車表からコピーされ、
--  以降は配車表を直しても運行表に反映されなかった。
--  走り出したあとに表が変わる事故を防ぐための作りだったが、
--  現場からは「配車を直したのに運行表が変わらない」という不具合に見えていた。
--
-- 【考え方を変えた】
--  止めるかどうかは【人が決める】。
--    確定していない日 … 開くたびに配車表から作り直す（常に最新）
--    確定した日       … 何があっても作り直さない
--  この表は「確定した日」を持つだけ。行が有る＝確定。無い＝未確定。
--
--  打刻が始まっている日は、確定していなくても自動では作り直さない
--  （確定の押し忘れに備えた保険。作り直しは画面のボタンから明示的に行う）。
-- ============================================================

create table if not exists soge_day_locks (
  facility_code text not null,
  service_date  date not null,
  locked_by     text,
  locked_at     timestamptz default now(),
  primary key (facility_code, service_date)
);

-- ---------- 確認 ----------
-- select * from soge_day_locks order by service_date desc limit 20;
