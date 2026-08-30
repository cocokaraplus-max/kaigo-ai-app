"""
evaluation_helper.py — Phase 2.B 月次評価機能のヘルパー関数群

Session 38 / Phase 5 で新規作成。

主な責務:
  - 訓練目標 / 介護区分の初期値取得(将来マスタ参照可能な設計、教訓 #51)
  - 編集ロック取得 / 解放(悲観的ロック、10 分タイムアウト)
  - 評価レコードの完成状態判定(3 色バッジ: 緑/オレンジ/赤)
  - 評価データの UPSERT(同月既存判定 + ロック整合性チェック)

依存:
  - supabase-py (create_client は呼び出し側で生成、関数に渡す)
  - datetime / timezone (UTC で扱う)

設計参考:
  - docs/SESSION38_HANDOFF.md(Session 37 で確定した全 12 論点)
  - DB スキーマ: patient_evaluations 29 カラム、patients 8 カラム
"""

from datetime import date, datetime, timedelta, timezone

# goal-asof-current-month-v1: 「今月かどうか」は日本時間で判定する。
#   ★UTCで判定すると、月初と月末に1日ずれる。
#     このリポジトリでは同じ理由で一度事故が起きている（セルフ評価の対象月）。
_JST = timezone(timedelta(hours=9))


# ===========================================================================
# 定数
# ===========================================================================

LOCK_TIMEOUT_MINUTES = 10  # 編集ロックのタイムアウト(分)。設計書 §論点 11-2

# 介護区分の選択肢(DB CHECK 制約と一致)
CARE_CLASSIFICATIONS = ("要介護", "要支援", "事業対象者")

# 介護度の選択肢(patients.care_level の CHECK 制約と一致)
CARE_LEVELS = (
    "要介護1", "要介護2", "要介護3", "要介護4", "要介護5",
    "要支援1", "要支援2", "事業対象者", "自立",
)

# 達成度の選択肢(各 *_status カラムの CHECK 制約と一致)
ACHIEVEMENT_VALUES = ("達成", "一部達成", "未達成")


# ===========================================================================
# 内部ヘルパー
# ===========================================================================

def _care_level_to_classification(care_level: str) -> str:
    """patients.care_level の値を care_classification にマッピング。

    Args:
        care_level: '要介護1' 〜 '要介護5', '要支援1', '要支援2', '事業対象者', '自立'

    Returns:
        '要介護' / '要支援' / '事業対象者' / ''(自立 or 不明)
    """
    if not care_level:
        return ""
    if care_level.startswith("要介護"):
        return "要介護"
    if care_level.startswith("要支援"):
        return "要支援"
    if care_level == "事業対象者":
        return "事業対象者"
    # '自立' などは空
    return ""


def _now_utc_iso() -> str:
    """現在時刻を UTC ISO 文字列で返す(Supabase 互換)"""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(iso_str: str) -> datetime:
    """ISO 文字列を timezone-aware datetime に変換(Z 形式も対応)"""
    return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))


# ===========================================================================
# 1. 初期値取得関数(将来マスタ参照可能、教訓 #51)
# ===========================================================================

def get_initial_training_goal(supabase, facility_code: str, user_name: str, target_month: str) -> str:
    """訓練目標の初期値を返す。

    優先順位:
      1. (将来 Phase 2.D) patients.training_goal がマスタとして設定されていればそれ
      2. (現状)         対象月より前の最新 patient_evaluations.training_goal
      3. (フォールバック) 空文字

    Args:
        supabase: Supabase Client instance(get_supabase() の結果)
        facility_code: 施設コード
        user_name: 利用者名
        target_month: 対象月 'YYYY-MM' 形式

    Returns:
        初期値文字列(該当なしの場合は空文字)
    """
    # ── ① 将来: patients マスタ参照 ──
    # NOTE: 現状の patients.training_goal は Session 35 以前から存在するが、
    #       単一値のみで履歴管理がない。Phase 2.D で利用者マスタ整備時に
    #       「マスタ優先」とするかを再検討する。今は ② を優先。
    # try:
    #     res = supabase.table("patients") \
    #         .select("training_goal") \
    #         .eq("facility_code", facility_code) \
    #         .eq("user_name", user_name) \
    #         .limit(1) \
    #         .execute()
    #     if res.data and res.data[0].get("training_goal"):
    #         return res.data[0]["training_goal"]
    # except Exception:
    #     pass

    # ── ② 対象月より前の最新 patient_evaluations.training_goal ──
    try:
        res = supabase.table("patient_evaluations") \
            .select("training_goal") \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .lt("year_month", target_month) \
            .order("year_month", desc=True) \
            .limit(1) \
            .execute()
        if res.data and res.data[0].get("training_goal"):
            return res.data[0]["training_goal"]
    except Exception:
        pass

    # ── ③ フォールバック ──
    return ""


def get_initial_goal_values(supabase, facility_code: str, user_name: str, target_month: str) -> dict:
    """各軸の目標初期値を返す。

    どこから読むか（上から順に、後のものが優先）:
      1. patient_profiles（いまの目標。マスタ）
      2. goal_history（★過去の月だけ。当時の目標に巻き戻す）
    ★今月は巻き戻さない。今月は 1 がそのまま正しい。
    要介護: short/long × function/activity/participation の6軸
    要支援/事業対象者: short/long_goal_simple の2軸
    Returns:
        dict with keys:
            short_goal_function, short_goal_activity, short_goal_participation,
            long_goal_function, long_goal_activity, long_goal_participation,
            short_goal_simple, long_goal_simple
    """
    result = {
        "short_goal_function": "", "short_goal_activity": "", "short_goal_participation": "",
        "long_goal_function": "",  "long_goal_activity": "",  "long_goal_participation": "",
        "short_goal_simple": "", "long_goal_simple": "",
    }
    # goal-dead-prevmonth-remove-v1: ここには「前月の patient_evaluations から
    #   目標を読む」処理があったが、patient_evaluations に short_goal_function
    #   などの列は【存在しない】。2026-08-28に本番で確認：
    #       column "short_goal_function" does not exist
    #   問い合わせは毎回エラーになり、except Exception: pass で握りつぶされて
    #   いた。一度も動いたことがない。読む人を惑わせるので消した。
    #   目標は下の patient_profiles から読めているので、動きは変わらない。
    #   ★もし将来「前月の評価から引き継ぐ」を作るなら、まず列を作ること（DDL先行）。
    # goal-period-config-v1: 期間キーを追加(評価テーブルには列が無いのでselect対象外)
    for _pk in ("short_goal_period_from", "short_goal_period_to",
                "long_goal_period_from", "long_goal_period_to"):
        result[_pk] = ""

    # patient_profilesからのフォールバック（evaluationsに値がない場合）
    try:
        prof = supabase.table("patient_profiles") \
            .select("short_goal,long_goal,short_goal_function,short_goal_activity,short_goal_participation,long_goal_function,long_goal_activity,long_goal_participation,short_goal_period_from,short_goal_period_to,long_goal_period_from,long_goal_period_to") \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .limit(1) \
            .execute()
        if prof.data and prof.data[0]:
            p = prof.data[0]
            if not result["short_goal_simple"]:
                result["short_goal_simple"] = p.get("short_goal") or ""
            if not result["long_goal_simple"]:
                result["long_goal_simple"] = p.get("long_goal") or ""
            for axis in ["function", "activity", "participation"]:
                if not result[f"short_goal_{axis}"]:
                    result[f"short_goal_{axis}"] = p.get(f"short_goal_{axis}") or ""
                if not result[f"long_goal_{axis}"]:
                    result[f"long_goal_{axis}"] = p.get(f"long_goal_{axis}") or ""
            for _pk in ("short_goal_period_from", "short_goal_period_to",
                        "long_goal_period_from", "long_goal_period_to"):
                if not result[_pk]:
                    result[_pk] = p.get(_pk) or ""
    except Exception:
        pass

    # goal-asof-month-v1: 過去月は goal_history から「当時の目標」に復元する。
    # これが無いと最新の patient_profiles を読むため、目標を後から変更すると
    # 過去評価の「現在の目標」まで新しい値に見えてしまう。
    # 対象月以降(year_month >= target_month)の変更のうち最も古いものの old_value
    # = その対象月当時に有効だった目標、として上書きする。
    try:
        _fmap = {
            "short_goal": "short_goal_simple", "long_goal": "long_goal_simple",
            "short_goal_function": "short_goal_function", "short_goal_activity": "short_goal_activity",
            "short_goal_participation": "short_goal_participation",
            "long_goal_function": "long_goal_function", "long_goal_activity": "long_goal_activity",
            "long_goal_participation": "long_goal_participation",
            "short_goal_period_from": "short_goal_period_from", "short_goal_period_to": "short_goal_period_to",
            "long_goal_period_from": "long_goal_period_from", "long_goal_period_to": "long_goal_period_to",
        }
        # goal-valid-from-v1: その月に有効だった目標を【適用日】から決める。
        #   ★「どの月の画面で操作したか(year_month)」ではなく、
        #     「いつから有効か(valid_from)」で決める。
        #     操作した画面に左右されなくなる。
        #     介護度の _care_level_at_month_end と同じ考え方。
        #
        #   決め方:
        #     適用日 <= その月の月末 の変更のうち【最新】の new_value。
        #     1件も無ければ、一番古い変更の old_value（＝まだ変わる前の値）。
        #
        # goal-asof-current-month-v1: 【今月と先の月は巻き戻さない】
        #   ★巻き戻しの目的は「過去の評価が、後から変えた新しい目標に見えて
        #     しまう」のを防ぐこと。今月にまで効かせると、逆に
        #     【いま変更した目標が今月に反映されない】。
        #   ★2026-08 に実際に起きた：7月の画面から目標を直したのに、
        #     8月の画面が古いままだった（現場から「変更しても変わらない」）。
        #     7月からの変更には「7月」のタグが付くので、8月を見るときの
        #     gte(year_month, '2026-08') に入らず、無視されるため。
        #   ★今月は「いまの目標（patient_profiles）」がそのまま正しい。
        if target_month >= datetime.now(_JST).strftime("%Y-%m"):
            return result

        _gh = supabase.table("goal_history") \
            .select("field, old_value, new_value, valid_from, changed_at") \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .execute()

        # その月の月末（'YYYY-MM-DD'）
        _y, _m = int(target_month[:4]), int(target_month[5:7])
        _next = date(_y + 1, 1, 1) if _m == 12 else date(_y, _m + 1, 1)
        _month_end = (_next - timedelta(days=1)).isoformat()

        _by_field = {}
        for _row in (_gh.data or []):
            _f = _row.get("field")
            if _f in _fmap:
                _by_field.setdefault(_f, []).append(_row)

        for _f, _rows in _by_field.items():
            # 適用日の順に並べる。同じ日なら、後から記録したほうを後ろに。
            _rows.sort(key=lambda r: ((r.get("valid_from") or ""),
                                      (r.get("changed_at") or "")))
            _applied = [r for r in _rows if (r.get("valid_from") or "") <= _month_end]
            if _applied:
                _v = _applied[-1].get("new_value")      # 効いている中で最新
            else:
                _v = _rows[0].get("old_value")          # まだ一度も効いていない
            if _v is None or str(_v).strip().lower() in ("none", "null"):
                _v = ""
            result[_fmap[_f]] = _v
    except Exception:
        pass

    return result

def _care_level_at_month_end(history_rows, month_end_iso):
    """care_level_history(list of dict)から month_end_iso('YYYY-MM-DD')時点で有効な care_level を返す。
    valid_from <= 月末日 の中で valid_from 最大(同日ならid最大)を採用。無ければ None。"""
    best = None
    for h in (history_rows or []):
        vf = (h.get("valid_from") or "")[:10]
        if not vf or vf > month_end_iso:
            continue
        if best is None:
            best = h
        else:
            bvf = (best.get("valid_from") or "")[:10]
            if vf > bvf or (vf == bvf and (h.get("id") or 0) > (best.get("id") or 0)):
                best = h
    return (best.get("care_level") if best else None)


def get_initial_care_classification(supabase, facility_code: str, user_name: str, target_month: str) -> str:
    """介護区分の初期値を返す（clh-dateaware-v1: 対象月時点の介護度を優先）。

    優先順位:
      1. care_level_history から「対象月末時点」で有効な介護度 → care_classification
         （過去月の評価には当時の介護度が当たる）
      2. patient_profiles.care_level（現在値）→ care_classification（履歴が無い利用者向けフォールバック）
      3. 対象月より前の最新 patient_evaluations.care_classification
      4. 空文字
    """
    month_end = ""
    try:
        import calendar as _cal
        _y, _m = target_month.split("-")
        _y, _m = int(_y), int(_m)
        _last = _cal.monthrange(_y, _m)[1]
        month_end = "%04d-%02d-%02d" % (_y, _m, _last)
    except Exception:
        month_end = ""

    pid = None
    cur_level = ""
    try:
        res = supabase.table("patient_profiles") \
            .select("id, care_level") \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .limit(1) \
            .execute()
        if res.data:
            pid = res.data[0].get("id")
            cur_level = res.data[0].get("care_level") or ""
    except Exception:
        pass

    # ── ① care_level_history 対象月末時点で有効な介護度 ──
    if pid and month_end:
        try:
            hres = supabase.table("care_level_history") \
                .select("care_level, valid_from, id") \
                .eq("facility_code", facility_code) \
                .eq("patient_id", pid) \
                .execute()
            lv = _care_level_at_month_end(hres.data or [], month_end)
            if lv:
                mapped = _care_level_to_classification(lv)
                if mapped:
                    return mapped
        except Exception:
            pass

    # ── ② patient_profiles.care_level（現在値）──
    if cur_level:
        mapped = _care_level_to_classification(cur_level)
        if mapped:
            return mapped

    # ── ③ 対象月より前の最新 patient_evaluations.care_classification ──
    try:
        res = supabase.table("patient_evaluations") \
            .select("care_classification") \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .lt("year_month", target_month) \
            .order("year_month", desc=True) \
            .limit(1) \
            .execute()
        if res.data and res.data[0].get("care_classification"):
            return res.data[0]["care_classification"]
    except Exception:
        pass

    # ── ④ フォールバック ──
    return ""



# ===========================================================================
# 2. 編集ロック関数(悲観的ロック、10 分タイムアウト)
# ===========================================================================

# ===== eval-two-entrances-v1: 入口ごとのロック列 =====
#   入口を担当ごとに分けると、2人が同時に同じ月の記録を開く。
#   ロックが【記録まるごと】に掛かっていると、後から保存したほうが必ず弾かれる。
#   そこで入口ごとに別の列を使う。
#     'eval' … 評価担当者（目標の達成度・聞き取り・満足度・体重）
#     'ft'   … 機能訓練指導員（体の評価・報告文）
#     None   … 分ける前の1枚の画面（今までどおり editing_by）
#   ★移行が終わるまで、旧列も必ず一緒に見ること。
#     旧画面が開いているのに新入口から保存できてしまうと、丸ごと上書きになる。
_LOCK_COLS = {
    "eval": ("editing_by_eval", "editing_started_at_eval"),
    "ft":   ("editing_by_ft",   "editing_started_at_ft"),
    None:   ("editing_by",      "editing_started_at"),
}

def _lock_cols(section):
    """section から (誰が, いつから) の列名を返す。知らない値は旧列にする。"""
    return _LOCK_COLS.get(section if section in ("eval", "ft") else None)


def acquire_edit_lock(supabase, evaluation_id: int, current_user: str,
                      facility_code: str = None, section: str = None) -> dict:
    """編集ロックを取得する。

    ★eval-two-entrances-v1: section を渡すと、その入口のロックだけを取る。
      渡さなければ今までどおり（1枚の画面のロック）。

    ★eval-lock-scope-v1（2026-08-26）
      facility_code を必ず受け取り、その施設の評価だけを対象にする。
      これが無かったため、ログインしていれば【他の施設の評価にも】
      自分の名前でロックをかけられ、相手施設の職員名も見えていた。
      （他の評価系のルートはすべて f_code でしぼっていた。ここだけ漏れていた）

      ★facility_code を渡さない呼び出しは、通さずに失敗させる。
        黙って全施設を対象にするより、はっきり失敗するほうが安全なため。

    動作:
      - 該当評価レコードが ID で存在する場合のみ動作(新規評価=ID 未確定の場合は不要)
      - 別ユーザーがロック中 + タイムアウト未経過 → success=False
      - タイムアウト経過 or 自分のロック or ロックなし → 取得して success=True

    Args:
        supabase: Supabase Client instance
        evaluation_id: patient_evaluations.id
        current_user: 現在ログイン中のユーザー名

    Returns:
        {
            "success": True/False,
            "editing_by": str (失敗時、ロック中のユーザー名),
            "editing_started_at": str (失敗時、ISO 時刻文字列),
            "lock_age_seconds": int (失敗時、ロック経過秒数),
        }
    """
    if not facility_code:
        return {"success": False, "error": "facility_code がありません（eval-lock-scope-v1）"}
    by_col, at_col = _lock_cols(section)
    # ★旧列も一緒に読む。分ける前の画面が開いているときは、そちらを優先して弾く。
    sel = by_col + ", " + at_col
    if by_col != "editing_by":
        sel += ", editing_by, editing_started_at"
    try:
        res = supabase.table("patient_evaluations") \
            .select(sel) \
            .eq("id", evaluation_id) \
            .eq("facility_code", facility_code) \
            .single() \
            .execute()
    except Exception as e:
        return {"success": False, "error": f"レコード取得失敗: {e}"}

    current = res.data or {}
    now = datetime.now(timezone.utc)

    # 見る順番：まず旧画面（全部を書き換えるので影響が大きい）、次に同じ入口
    pairs = []
    if by_col != "editing_by":
        pairs.append(("editing_by", "editing_started_at"))
    pairs.append((by_col, at_col))

    for _b, _a in pairs:
        if not (current.get(_b) and current.get(_a)):
            continue
        try:
            started = _parse_iso_datetime(current[_a])
            age_seconds = (now - started).total_seconds()
        except Exception:
            age_seconds = float("inf")  # パース失敗時は強制解放扱い

        # 別ユーザーがロック中 + タイムアウト未経過 → 失敗
        if current[_b] != current_user and age_seconds < LOCK_TIMEOUT_MINUTES * 60:
            return {
                "success": False,
                "editing_by": current[_b],
                "editing_started_at": current[_a],
                "lock_age_seconds": int(age_seconds),
                # ★eval-two-entrances-v1: どちらのロックで弾いたかを返す。
                #   'old'  … 分ける前の1枚の画面（全部の欄を書き換える）
                #   'same' … 同じ入口
                #   画面はこれを見て、職員に出す文を変える。
                #   （どちらも「この入口を開いています」と出すと、実態と食い違う）
                "lock_scope": ("old" if _b == "editing_by" else "same"),
            }
        # 自分のロック or タイムアウト → そのまま更新へ

    # ロック取得 or 更新
    try:
        supabase.table("patient_evaluations").update({
            by_col: current_user,
            at_col: _now_utc_iso(),
        }).eq("id", evaluation_id).eq("facility_code", facility_code).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"ロック取得失敗: {e}"}


def release_edit_lock(supabase, evaluation_id: int, current_user: str,
                      facility_code: str = None, section: str = None) -> dict:
    """編集ロックを解放する(自分が保持している場合のみ)。

    ★eval-lock-scope-v1（2026-08-26）
      こちらは editing_by で自分のロックだけを解放していたが、
      別の施設に【同じ名前の職員】がいると解放できてしまう。
      facility_code でもしぼる。

    Args:
        supabase: Supabase Client instance
        evaluation_id: patient_evaluations.id
        current_user: 現在ログイン中のユーザー名

    Returns:
        {"success": True} または {"success": False, "error": "..."}
    """
    if not facility_code:
        return {"success": False, "error": "facility_code がありません（eval-lock-scope-v1）"}
    by_col, at_col = _lock_cols(section)      # eval-two-entrances-v1
    try:
        supabase.table("patient_evaluations").update({
            by_col: None,
            at_col: None,
        }).eq("id", evaluation_id).eq(by_col, current_user) \
          .eq("facility_code", facility_code).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===========================================================================
# 3. 完成状態判定(3 色バッジ: 緑/オレンジ/赤)
# ===========================================================================

# 必須項目(B 必須、設計書 §論点 10)
#
# ★eval-required-legacy-v1（2026-08-26）: training_goal を必須から外した。
#
#   training_goal は【1つの文章で訓練目標を書いていた時代】の列。
#   いまは利用者情報に登録した目標（要介護=ICF3軸×短期長期／要支援=短期長期）を
#   評価画面に表示し、変えたい軸だけ「新規目標」欄に書く作りになっている。
#   ★評価画面に training_goal を書き込む部品はもう無い
#     （<input type="hidden" id="eval-training-goal"> が残っているだけ）。
#   ★そのため【書けない項目を必須にしている】状態で、
#     新しく作った評価はすべて「必須未入力」の赤いバッジになっていた。
#     ＝「過去の評価」一覧でどれが仕上がっているか分からなくなっていた。
#
#   ★列そのものは消さないこと。過去の評価に実際の文章が入っており
#     （例: 2026-07「自宅内を伝い歩きで安全に移動できる」）、
#     過去評価の詳細画面で「訓練目標」として表示し続ける必要がある。
#   ★ALLOWED_UPSERT_KEYS からも外さないこと。外すと、古い値が入っている
#     記録を開いて保存し直したときに消えてしまう。
REQUIRED_FIELDS = ("user_name", "year_month", "care_classification", "evaluator_name")

# 全項目(完成度 100% 判定用、介護区分で分岐)
ALL_FIELDS_KAIGO = (
    # 必須（eval-required-legacy-v1: training_goal は書けない列なので外した）
    "user_name", "year_month", "care_classification", "evaluator_name",
    # 計測値
    "weight_kg", "attendance_count", "attendance_target",
    # 短期 ICF 3 個 + 長期 ICF 3 個
    "short_goal_function_status", "short_goal_activity_status", "short_goal_participation_status",
    "long_goal_function_status", "long_goal_activity_status", "long_goal_participation_status",
    # 自由文
    "source_data",
    "changes_by_training", "issues_and_causes", "special_notes",
    # モニタリング(new_requests_detail は条件付きなので含めない)
    "new_requests_exist", "satisfaction", "service_appropriateness",
)

ALL_FIELDS_SHIEN_OR_TAISHOU = (
    # 必須（eval-required-legacy-v1: training_goal は書けない列なので外した）
    "user_name", "year_month", "care_classification", "evaluator_name",
    # 計測値
    "weight_kg", "attendance_count", "attendance_target",
    # 短期/長期(単純)
    "short_goal_status", "long_goal_status",
    # 自由文
    "source_data",
    "changes_by_training", "issues_and_causes", "special_notes",
    # モニタリング
    "new_requests_exist", "satisfaction", "service_appropriateness",
)


def _is_empty(value) -> bool:
    """値が「未入力」とみなせるか判定。空文字、None、空白のみ文字列、を未入力扱い。
    数値 0 や False は「入力済み」として扱う。"""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def evaluation_status(eval_dict: dict) -> dict:
    """評価レコードの完成状態を判定。

    Args:
        eval_dict: patient_evaluations の 1 レコード(dict)

    Returns:
        {
            "color": "green" / "orange" / "red",
            "label": "完成" / "一部未入力" / "必須未入力",
            "missing_required": [必須未入力フィールド名のリスト],
            "missing_optional": [任意未入力フィールド名のリスト],
            "total_fields": 全フィールド数,
            "filled_fields": 入力済みフィールド数,
        }
    """
    if not eval_dict:
        return {
            "color": "red", "label": "必須未入力",
            "missing_required": list(REQUIRED_FIELDS), "missing_optional": [],
            "total_fields": len(REQUIRED_FIELDS), "filled_fields": 0,
        }

    # 必須項目チェック
    missing_required = [f for f in REQUIRED_FIELDS if _is_empty(eval_dict.get(f))]

    # 介護区分に応じて「全項目」を選ぶ
    care_class = eval_dict.get("care_classification") or ""
    if care_class == "要介護":
        all_fields = ALL_FIELDS_KAIGO
    elif care_class in ("要支援", "事業対象者"):
        all_fields = ALL_FIELDS_SHIEN_OR_TAISHOU
    else:
        # 介護区分未入力時は必須最小限のみで判定
        all_fields = REQUIRED_FIELDS

    # new_requests_detail は条件付き必須(new_requests_exist == 'あり' の時のみ)
    optional_fields = [f for f in all_fields if f not in REQUIRED_FIELDS]
    if eval_dict.get("new_requests_exist") == "あり":
        optional_fields.append("new_requests_detail")

    missing_optional = [f for f in optional_fields if _is_empty(eval_dict.get(f))]

    total = len(REQUIRED_FIELDS) + len(optional_fields)
    filled = total - len(missing_required) - len(missing_optional)

    if missing_required:
        return {
            "color": "red", "label": "必須未入力",
            "missing_required": missing_required, "missing_optional": missing_optional,
            "total_fields": total, "filled_fields": filled,
        }
    if missing_optional:
        return {
            "color": "orange", "label": "一部未入力",
            "missing_required": [], "missing_optional": missing_optional,
            "total_fields": total, "filled_fields": filled,
        }
    return {
        "color": "green", "label": "完成",
        "missing_required": [], "missing_optional": [],
        "total_fields": total, "filled_fields": filled,
    }


# ===========================================================================
# 4. 評価データ UPSERT
# ===========================================================================

# UPSERT で受け入れる payload キーのホワイトリスト(セキュリティ + 想定外カラム防止)
ALLOWED_UPSERT_KEYS = (
    "facility_code", "user_name", "year_month", "evaluator_name",
    "weight_kg", "attendance_count", "attendance_target",
    "training_goal", "care_classification",
    # eval-two-entrances-v1: 評価担当者が集めた材料。
    #   source_data（機能訓練指導員の材料）とは別の列。
    #   2人が同時に書いてもぶつからないように分けてある。
    "source_data_eval",
    # 目標達成ステータス
    "short_goal_function_status", "short_goal_activity_status", "short_goal_participation_status",
    "long_goal_function_status", "long_goal_activity_status", "long_goal_participation_status",
    "short_goal_status", "long_goal_status",
    # 新規目標（入力時に更新）
    "short_goal_function_new", "short_goal_activity_new", "short_goal_participation_new",
    "long_goal_function_new", "long_goal_activity_new", "long_goal_participation_new",
    "short_goal_new", "long_goal_new",
    # 継続/変更フラグ
    "short_goal_function_cont", "short_goal_activity_cont", "short_goal_participation_cont",
    "long_goal_function_cont", "long_goal_activity_cont", "long_goal_participation_cont",
    "short_goal_cont", "long_goal_cont",
    "source_data",
    "changes_by_training", "issues_and_causes", "special_notes",
    "new_requests_exist", "new_requests_detail",
    "satisfaction", "service_appropriateness",
    "font_scale",
    "layout_mode",
    "eval_memo",
)


def eval_lock_holder(row: dict, current_user: str):   # eval-delete-v1
    """その評価を【いま誰かが開いているか】。開いていればその人の名前を返す。

    ★見るのは3つとも。分ける前の1枚の画面(editing_by)と、
      入口ごとの2つ(editing_by_eval / editing_by_ft)。
      どれか1つでも他の人が持っていれば、開かれている。
    ★保存の競合判定（upsert_patient_evaluation）と同じ規則にすること。
      別々に書くと、保存はできるのに消せない（またはその逆）が起きる。
    """
    for _b, _a in (("editing_by", "editing_started_at"),
                   ("editing_by_eval", "editing_started_at_eval"),
                   ("editing_by_ft", "editing_started_at_ft")):
        holder = row.get(_b)
        started = row.get(_a)
        if not (holder and holder != current_user and started):
            continue
        try:
            age = (datetime.now(timezone.utc) - _parse_iso_datetime(started)).total_seconds()
            if age < LOCK_TIMEOUT_MINUTES * 60:
                return holder
        except Exception:
            pass          # 時刻が読めないときは開いていない扱い（保存側と同じ）
    return None


def delete_patient_evaluation(supabase, facility_code: str, user_name: str,
                              year_month: str, current_user: str) -> dict:   # eval-delete-v1
    """その月の評価を1件消す。★元に戻せない。

    返り値:
        {"success": True, "id": ..., "filled": [中身があった欄の名前]}
        {"success": False, "error": ..., "code": "notfound"/"locked"/"busy"}

    ★施設コードは【呼び出し側がセッションから渡す】こと。
      画面から受け取った値を使ってはいけない（他施設の評価が消せてしまう）。
    """
    if not (facility_code and user_name and year_month):
        return {"success": False, "error": "利用者と対象月が必要です", "code": "bad"}
    try:
        res = (supabase.table("patient_evaluations").select("*")
               .eq("facility_code", facility_code)
               .eq("user_name", user_name)
               .eq("year_month", year_month)
               .limit(1).execute())
        rows = res.data or []
    except Exception as e:
        # ★確かめられないときは消さない。消すのは元に戻せないので、迷ったら止める。
        return {"success": False, "error": f"いま確認できませんでした: {e}", "code": "busy"}
    if not rows:
        return {"success": False, "error": "この月の評価はまだありません", "code": "notfound"}

    row = rows[0]
    holder = eval_lock_holder(row, current_user)
    if holder:
        # ★開いている人がいる間は消さない。
        #   相手が保存しようとした瞬間に消えていると、原因が分からない事故になる。
        return {"success": False, "error": f"いま {holder} さんが開いています", "code": "locked"}

    # ★中身そのものは残さない。どの欄に中身があったかだけ控える。
    skip = ("id", "facility_code", "user_name", "year_month",
            "created_at", "updated_at",
            "editing_by", "editing_started_at",
            "editing_by_eval", "editing_started_at_eval",
            "editing_by_ft", "editing_started_at_ft")
    filled = sorted(k for k, v in row.items()
                    if k not in skip and v not in (None, "", 0))

    try:
        (supabase.table("patient_evaluations").delete()
         .eq("facility_code", facility_code).eq("id", row["id"]).execute())
    except Exception as e:
        return {"success": False, "error": f"消せませんでした: {e}", "code": "busy"}
    return {"success": True, "id": row["id"], "filled": filled}


def upsert_patient_evaluation(supabase, payload: dict, current_user: str,
                              section: str = None) -> dict:
    """評価データを UPSERT する。

    動作:
      - (facility_code, user_name, year_month) で既存検索(UNIQUE INDEX uq_patient_eval_user_month)
      - 既存あり: editing_by が current_user またはタイムアウト経過なら UPDATE、それ以外は競合エラー
      - 既存なし: INSERT
      - 保存成功時: editing_by, editing_started_at を NULL に(ロック解放)+ updated_at 更新

    Args:
        supabase: Supabase Client instance
        payload: 保存するデータ。必須キー: facility_code, user_name, year_month
        current_user: ログイン中のユーザー名(競合判定用)

    Returns:
        {
            "success": True,
            "id": int,
            "mode": "insert" / "update",
        }
        または
        {
            "success": False,
            "error": str,
            "conflict": True (競合の場合),
            "editing_by": str (競合相手),
        }
    """
    # 必須キーチェック
    if not payload.get("facility_code"):
        return {"success": False, "error": "facility_code が必要です"}
    if not payload.get("user_name"):
        return {"success": False, "error": "user_name が必要です"}
    if not payload.get("year_month"):
        return {"success": False, "error": "year_month が必要です"}

    # ホワイトリストでフィルタ(想定外キー除外)
    clean = {k: v for k, v in payload.items() if k in ALLOWED_UPSERT_KEYS}

    # 空文字を None に正規化(数値カラム対策、checkbox 未選択対策)
    for numeric_key in ("weight_kg", "attendance_count", "attendance_target"):
        if numeric_key in clean and clean[numeric_key] == "":
            clean[numeric_key] = None

    # 既存検索
    try:
        # eval-two-entrances-save: 入口ごとのロック列も読む
        existing_res = supabase.table("patient_evaluations") \
            .select("id, editing_by, editing_started_at, "
                    "editing_by_eval, editing_started_at_eval, "
                    "editing_by_ft, editing_started_at_ft") \
            .eq("facility_code", clean["facility_code"]) \
            .eq("user_name", clean["user_name"]) \
            .eq("year_month", clean["year_month"]) \
            .limit(1) \
            .execute()
    except Exception as e:
        return {"success": False, "error": f"既存検索失敗: {e}"}

    existing = (existing_res.data or [None])[0]

    if existing:
        # ── UPDATE 経路 ──
        evaluation_id = existing["id"]

        # 競合判定(別ユーザーがロック中 + タイムアウト未経過)
        #
        # ★eval-two-entrances-save
        #   入口を分けると、評価担当者と機能訓練指導員が同時に開く。
        #   自分の入口のロックだけを見ればよい……ではない。
        #   【分ける前の1枚の画面】は全部の欄を書き換えるので、
        #   そちらが開いていたら、どの入口からも保存させてはいけない。
        #   → 旧列 ＋ 自分の入口の列、その両方を見る。
        _by_col, _at_col = _lock_cols(section)
        _checks = []
        if _by_col != "editing_by":
            _checks.append(("editing_by", "editing_started_at"))
        _checks.append((_by_col, _at_col))

        for _b, _a in _checks:
            lock_holder = existing.get(_b)
            lock_started = existing.get(_a)
            if not (lock_holder and lock_holder != current_user and lock_started):
                continue
            try:
                started = _parse_iso_datetime(lock_started)
                age = (datetime.now(timezone.utc) - started).total_seconds()
                if age < LOCK_TIMEOUT_MINUTES * 60:
                    return {
                        "success": False,
                        "error": f"{lock_holder} が編集中です(あと約 {int((LOCK_TIMEOUT_MINUTES * 60 - age) / 60)} 分)",
                        "conflict": True,
                        "editing_by": lock_holder,
                        "lock_scope": ("old" if _b == "editing_by" else "same"),
                    }
            except Exception:
                pass  # パース失敗時は競合扱いせず続行

        # 更新(updated_at を明示、ロック解放)
        # ★解放するのは【自分が取った入口のロックだけ】。
        #   相手の入口のロックまで外すと、相手が保存する前に横取りされる。
        clean["updated_at"] = _now_utc_iso()
        clean[_by_col] = None
        clean[_at_col] = None
        try:
            supabase.table("patient_evaluations").update(clean).eq("id", evaluation_id).execute()
            return {"success": True, "id": evaluation_id, "mode": "update"}
        except Exception as e:
            return {"success": False, "error": f"UPDATE 失敗: {e}"}
    else:
        # ── INSERT 経路 ──
        # ロック関連は INSERT 時は NULL(新規作成と同時にロック解放)
        # eval-two-entrances-save: 新規作成なので、どの入口の列も空でよい
        clean["editing_by"] = None
        clean["editing_started_at"] = None
        clean["editing_by_eval"] = None
        clean["editing_started_at_eval"] = None
        clean["editing_by_ft"] = None
        clean["editing_started_at_ft"] = None
        try:
            res = supabase.table("patient_evaluations").insert(clean).execute()
            new_id = (res.data or [{}])[0].get("id")
            return {"success": True, "id": new_id, "mode": "insert"}
        except Exception as e:
            return {"success": False, "error": f"INSERT 失敗: {e}"}


# ===========================================================================
# 5. ユーティリティ: 過去評価のクエリ用ヘルパー
# ===========================================================================

def fetch_patient_evaluations(
    supabase,
    facility_code: str,
    user_name: str = None,
    user_names: list = None,
    year_month_from: str = None,
    year_month_to: str = None,
    sort_by: str = "year_month_desc",
    limit: int = 100,
) -> list:
    """過去の評価レコードを取得する(過去の評価タブ用)。

    Args:
        supabase: Supabase Client instance
        facility_code: 施設コード(必須)
        user_name: 利用者名フィルタ・完全一致(任意、後方互換用)
        user_names: 利用者名フィルタ・複数候補のいずれかに一致(任意)。
                    指定時は user_name より優先。空リストを渡した場合は
                    「該当者なし」とみなし空の結果を返す(検索ワードがマスタに
                    一度も一致しなかったケースを呼び出し側が表現できる)。
        year_month_from: 対象月の下限 'YYYY-MM'(任意)
        year_month_to: 対象月の上限 'YYYY-MM'(任意)
        sort_by: 'year_month_desc' / 'year_month_asc' / 'user_name' / 'updated_at_desc'
        limit: 取得上限(デフォルト 100)

    Returns:
        list of dict(評価レコード + 'status' フィールド付き)
    """
    try:
        # user_names が「明示的に渡された」かどうかで分岐する。
        # None = 未指定(従来どおり user_name を見る) / [] = 該当者なし / [...] = 候補で絞る
        if user_names is not None:
            if len(user_names) == 0:
                return []  # 検索ワードがどの利用者にも一致しなかった
            q = supabase.table("patient_evaluations").select("*").eq("facility_code", facility_code)
            q = q.in_("user_name", user_names)
        else:
            q = supabase.table("patient_evaluations").select("*").eq("facility_code", facility_code)
            if user_name:
                q = q.eq("user_name", user_name)
        if year_month_from:
            q = q.gte("year_month", year_month_from)
        if year_month_to:
            q = q.lte("year_month", year_month_to)

        # ソート
        if sort_by == "year_month_asc":
            q = q.order("year_month", desc=False).order("user_name")
        elif sort_by == "user_name":
            q = q.order("user_name").order("year_month", desc=True)
        elif sort_by == "updated_at_desc":
            q = q.order("updated_at", desc=True)
        else:  # year_month_desc (default)
            q = q.order("year_month", desc=True).order("user_name")

        q = q.limit(limit)
        res = q.execute()
        records = res.data or []

        # 各レコードに完成状態を付加
        for r in records:
            r["_status"] = evaluation_status(r)

        return records
    except Exception:
        return []
