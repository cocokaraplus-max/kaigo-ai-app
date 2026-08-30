-- ============================================================
-- diag_selfeval_goalmix.sql   2026-08-26（v2）
--
-- セルフ評価まわりで、コードを読んで見つかった気になる点が
-- 【実データで本当に起きているか】を確かめるためだけのSQL。
-- ★SELECT しかしない。データは1行も変えない。
--
-- ★★v2 での修正（v1は誤検知を出した）
--   実データには【文字列としての "None"】が入っていることがある。
--   アプリ側は _clean_goal でこれを空として扱っている：
--     none / null / nan / undefined / - / ― / なし / 特になし / 無し
--   v1 はこれを「目標が入っている」と数えてしまい、
--   正常な人（磯谷能子さん・要介護2）を問題ありとして出してしまった。
--   ★アプリが空として扱う値は、SQLでも空として扱うこと。
-- ============================================================


-- ------------------------------------------------------------
-- ① 要約：何人いるのかを先に見る（まずこれだけ実行すればよい）
-- ------------------------------------------------------------
with pc as (
  select
    facility_code, user_name, care_level,
    -- アプリの _clean_goal と同じ掃除をしてから中身の有無を見る
    (case when lower(btrim(coalesce(short_goal,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal) end)                    as g_short,
    (case when lower(btrim(coalesce(long_goal,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal) end)                     as g_long,
    (case when lower(btrim(coalesce(short_goal_function,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal_function) end)           as g_sf,
    (case when lower(btrim(coalesce(short_goal_activity,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal_activity) end)           as g_sa,
    (case when lower(btrim(coalesce(short_goal_participation,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal_participation) end)      as g_sp,
    (case when lower(btrim(coalesce(long_goal_function,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal_function) end)            as g_lf,
    (case when lower(btrim(coalesce(long_goal_activity,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal_activity) end)            as g_la,
    (case when lower(btrim(coalesce(long_goal_participation,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal_participation) end)       as g_lp
  from patient_profiles
)
select
  facility_code,
  count(*)                                                     as 全体,
  count(*) filter (where coalesce(care_level,'') = '')         as 区分が空,
  -- 要介護なのに、要支援用の簡易欄にも目標がある
  count(*) filter (
    where care_level like '要介護%' and (g_short <> '' or g_long <> '')
  )                                                            as 要介護なのに簡易欄あり,
  -- 要支援・事業対象者なのに、要介護用の3軸にも目標がある
  count(*) filter (
    where (care_level like '要支援%' or care_level = '事業対象者')
      and (g_sf<>'' or g_sa<>'' or g_sp<>'' or g_lf<>'' or g_la<>'' or g_lp<>'')
  )                                                            as 要支援なのに3軸あり,
  -- 目標が1つも入っていない人（質問が作れない）
  count(*) filter (
    where g_short='' and g_long='' and g_sf='' and g_sa='' and g_sp=''
      and g_lf='' and g_la='' and g_lp=''
  )                                                            as 目標が1つもない
from pc
group by facility_code
order by facility_code;


-- ------------------------------------------------------------
-- ② 食い違っている人の一覧（①で0でなかったときだけ見ればよい）
-- ------------------------------------------------------------
with pc as (
  select
    facility_code, user_name, care_level,
    (case when lower(btrim(coalesce(short_goal,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal) end)                    as g_short,
    (case when lower(btrim(coalesce(long_goal,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal) end)                     as g_long,
    (case when lower(btrim(coalesce(short_goal_function,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal_function) end)           as g_sf,
    (case when lower(btrim(coalesce(short_goal_activity,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal_activity) end)           as g_sa,
    (case when lower(btrim(coalesce(short_goal_participation,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(short_goal_participation) end)      as g_sp,
    (case when lower(btrim(coalesce(long_goal_function,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal_function) end)            as g_lf,
    (case when lower(btrim(coalesce(long_goal_activity,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal_activity) end)            as g_la,
    (case when lower(btrim(coalesce(long_goal_participation,''))) in
       ('','none','null','nan','undefined','-','―','なし','特になし','無し')
     then '' else btrim(long_goal_participation) end)       as g_lp
  from patient_profiles
)
select
  facility_code, user_name,
  coalesce(nullif(care_level,''),'（空）')          as 介護度,
  left(g_short,30)  as 短期_簡易,
  left(g_long,30)   as 長期_簡易,
  (g_sf<>'') as 短期_機能, (g_sa<>'') as 短期_活動, (g_sp<>'') as 短期_参加,
  (g_lf<>'') as 長期_機能, (g_la<>'') as 長期_活動, (g_lp<>'') as 長期_参加,
  case
    when coalesce(care_level,'') = ''
      then '★区分が空（どちらの欄を使うか決められない）'
    when care_level like '要介護%' and (g_short<>'' or g_long<>'')
      then '★要介護なのに簡易欄にも目標がある'
    when (care_level like '要支援%' or care_level = '事業対象者')
     and (g_sf<>'' or g_sa<>'' or g_sp<>'' or g_lf<>'' or g_la<>'' or g_lp<>'')
      then '★要支援なのに3軸にも目標がある'
    when g_short='' and g_long='' and g_sf='' and g_sa='' and g_sp=''
     and g_lf='' and g_la='' and g_lp=''
      then '★目標が1つもない（質問が作れない）'
    else '—'
  end                                                as 見立て
from pc
where coalesce(care_level,'') = ''
   or (care_level like '要介護%' and (g_short<>'' or g_long<>''))
   or ((care_level like '要支援%' or care_level = '事業対象者')
       and (g_sf<>'' or g_sa<>'' or g_sp<>'' or g_lf<>'' or g_la<>'' or g_lp<>''))
   or (g_short='' and g_long='' and g_sf='' and g_sa='' and g_sp=''
       and g_lf='' and g_la='' and g_lp='')
order by facility_code, user_name;


-- ------------------------------------------------------------
-- ③ 文字列 "None" などのゴミが、どの欄にどれだけ入っているか
--
--   アプリは _clean_goal で除外しているので【いま困ってはいない】。
--   ただし掃除しておけば、今後この手の誤検知に振り回されない。
-- ------------------------------------------------------------
select
  facility_code,
  count(*) filter (where lower(btrim(coalesce(short_goal,''))) in
    ('none','null','nan','undefined'))                        as 短期_簡易,
  count(*) filter (where lower(btrim(coalesce(long_goal,''))) in
    ('none','null','nan','undefined'))                        as 長期_簡易,
  count(*) filter (where lower(btrim(coalesce(short_goal_function,''))) in
    ('none','null','nan','undefined'))                        as 短期_機能,
  count(*) filter (where lower(btrim(coalesce(short_goal_activity,''))) in
    ('none','null','nan','undefined'))                        as 短期_活動,
  count(*) filter (where lower(btrim(coalesce(short_goal_participation,''))) in
    ('none','null','nan','undefined'))                        as 短期_参加,
  count(*) filter (where lower(btrim(coalesce(long_goal_function,''))) in
    ('none','null','nan','undefined'))                        as 長期_機能,
  count(*) filter (where lower(btrim(coalesce(long_goal_activity,''))) in
    ('none','null','nan','undefined'))                        as 長期_活動,
  count(*) filter (where lower(btrim(coalesce(long_goal_participation,''))) in
    ('none','null','nan','undefined'))                        as 長期_参加
from patient_profiles
group by facility_code
order by facility_code;


-- ------------------------------------------------------------
-- ④ care_level が「要介護1」「要支援1」に偏っていないか
--
--   評価画面で区分を手で変えると careMap により
--     要介護 → 要介護1 ／ 要支援 → 要支援1  で上書きされる。
--   ★偏っていても、それだけでは断定できない。実際の介護度と見比べること。
-- ------------------------------------------------------------
select
  facility_code,
  coalesce(nullif(care_level,''),'（空）')  as 介護度,
  count(*)                                  as 人数
from patient_profiles
group by facility_code, coalesce(nullif(care_level,''),'（空）')
order by facility_code, 人数 desc;
