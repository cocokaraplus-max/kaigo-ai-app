-- soge-legtime-v1 : 区間ごとの走行時間を覚えておく列
-- 到着予定時刻を「n+1等分」ではなく区間ごとに積み上げるために使う。
-- null のあいだは今までどおり等分。追加しても動きは変わらない（安全）。
alter table soge_route_time
  add column if not exists legs jsonb;
