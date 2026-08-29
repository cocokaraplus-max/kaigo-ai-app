-- 「要介護なのに、目標が2軸の欄に入ったまま」の方を数える（2026-08-29）
--
-- ★なぜ見るか
--   利用者基本情報は、要支援・事業対象者なら2軸（短期目標・長期目標）、
--   要介護なら3軸（機能・活動・参加）の欄を出す。
--   2軸の欄に目標が入ったまま要介護になると、評価画面は3軸しか見ないので
--   「この軸には目標が登録されていません」になる。目標は在るのに拾えない。
--   （DEV 青木利夫さんで確認。要介護3・2軸に目標あり・3軸すべて空）
--
-- ★画面側の作りは【変わった】ので、その前提でこの数字を見ること。
--   最初は「3軸が全部空なら2軸を出す」落とし先を入れたが、HIROさんの指示で撤去した。
--     「2軸を出すのが正解ではなく、3軸の目標を入力するように促す事が大切」
--   いまは評価画面と利用者情報の両方で【3軸に入れてください】と促す案内を出し、
--   古い2軸の目標は参考として横に並べているだけ。自動では拾わない。
--   つまりこのSQLの B に入る人は【入れ直しが要る人】そのものの数。
--   （落とし先があった頃のように「動くから急がない」ではない）
--
-- select だけ。何も書き換えない。

select
  case
    when 状況 = 'axis' then 'A: 3軸に入っている（そのままでよい）'
    when 状況 = 'simple' then 'B: ★2軸に入ったまま（3軸への入れ直しが要る）'
    else 'C: どちらも空（目標が未登録）'
  end as 区分,
  count(*) as 人数,
  string_agg(user_name, ' / ' order by user_name) as 対象者
from (
  select
    user_name,
    case
      when coalesce(short_goal_function,'')||coalesce(short_goal_activity,'')
        || coalesce(short_goal_participation,'')||coalesce(long_goal_function,'')
        || coalesce(long_goal_activity,'')||coalesce(long_goal_participation,'') <> ''
        then 'axis'
      when coalesce(short_goal,'')||coalesce(long_goal,'') <> ''
        then 'simple'
      else 'none'
    end as 状況
  from patient_profiles
  where facility_code = 'cocokaraplus-5526'
    and care_level like '要介護%'
    and coalesce(is_discontinued, false) = false    -- 利用中止の方は除く
) t
group by 状況
order by 区分;
