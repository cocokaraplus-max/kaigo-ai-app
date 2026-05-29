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

from datetime import datetime, timezone


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
    前月の patient_evaluations から各軸の目標テキストを取得する。
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
    try:
        res = supabase.table("patient_evaluations") \
            .select(",".join(result.keys())) \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .lt("year_month", target_month) \
            .order("year_month", desc=True) \
            .limit(1) \
            .execute()
        if res.data and res.data[0]:
            for key in result:
                val = res.data[0].get(key)
                if val:
                    result[key] = val
    except Exception:
        pass
    # patient_profilesからのフォールバック（evaluationsに値がない場合）
    try:
        prof = supabase.table("patient_profiles") \
            .select("short_goal,long_goal,short_goal_function,short_goal_activity,short_goal_participation,long_goal_function,long_goal_activity,long_goal_participation") \
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
    except Exception:
        pass
    return result

def get_initial_care_classification(supabase, facility_code: str, user_name: str, target_month: str) -> str:
    """介護区分の初期値を返す。

    優先順位:
      1. patients.care_level → care_classification にマッピング
         (要介護1-5 → '要介護'、要支援1-2 → '要支援'、事業対象者 → '事業対象者')
      2. 対象月より前の最新 patient_evaluations.care_classification
      3. フォールバック: 空文字

    Args:
        supabase: Supabase Client instance
        facility_code: 施設コード
        user_name: 利用者名
        target_month: 対象月 'YYYY-MM' 形式

    Returns:
        '要介護' / '要支援' / '事業対象者' / ''(不明)
    """
    # ── ① patients.care_level からマッピング ──
    try:
        res = supabase.table("patient_profiles") \
            .select("care_level") \
            .eq("facility_code", facility_code) \
            .eq("user_name", user_name) \
            .limit(1) \
            .execute()
        if res.data and res.data[0].get("care_level"):
            mapped = _care_level_to_classification(res.data[0]["care_level"])
            if mapped:
                return mapped
    except Exception:
        pass

    # ── ② 対象月より前の最新 patient_evaluations.care_classification ──
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

    # ── ③ フォールバック ──
    return ""


# ===========================================================================
# 2. 編集ロック関数(悲観的ロック、10 分タイムアウト)
# ===========================================================================

def acquire_edit_lock(supabase, evaluation_id: int, current_user: str) -> dict:
    """編集ロックを取得する。

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
    try:
        res = supabase.table("patient_evaluations") \
            .select("editing_by, editing_started_at") \
            .eq("id", evaluation_id) \
            .single() \
            .execute()
    except Exception as e:
        return {"success": False, "error": f"レコード取得失敗: {e}"}

    current = res.data or {}
    now = datetime.now(timezone.utc)

    if current.get("editing_by") and current.get("editing_started_at"):
        try:
            started = _parse_iso_datetime(current["editing_started_at"])
            age_seconds = (now - started).total_seconds()
        except Exception:
            age_seconds = float("inf")  # パース失敗時は強制解放扱い

        # 別ユーザーがロック中 + タイムアウト未経過 → 失敗
        if current["editing_by"] != current_user and age_seconds < LOCK_TIMEOUT_MINUTES * 60:
            return {
                "success": False,
                "editing_by": current["editing_by"],
                "editing_started_at": current["editing_started_at"],
                "lock_age_seconds": int(age_seconds),
            }
        # 自分のロック or タイムアウト → そのまま更新へ

    # ロック取得 or 更新
    try:
        supabase.table("patient_evaluations").update({
            "editing_by": current_user,
            "editing_started_at": _now_utc_iso(),
        }).eq("id", evaluation_id).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"ロック取得失敗: {e}"}


def release_edit_lock(supabase, evaluation_id: int, current_user: str) -> dict:
    """編集ロックを解放する(自分が保持している場合のみ)。

    Args:
        supabase: Supabase Client instance
        evaluation_id: patient_evaluations.id
        current_user: 現在ログイン中のユーザー名

    Returns:
        {"success": True} または {"success": False, "error": "..."}
    """
    try:
        supabase.table("patient_evaluations").update({
            "editing_by": None,
            "editing_started_at": None,
        }).eq("id", evaluation_id).eq("editing_by", current_user).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===========================================================================
# 3. 完成状態判定(3 色バッジ: 緑/オレンジ/赤)
# ===========================================================================

# 必須項目(B 必須、設計書 §論点 10)
REQUIRED_FIELDS = ("user_name", "year_month", "care_classification", "evaluator_name", "training_goal")

# 全項目(完成度 100% 判定用、介護区分で分岐)
ALL_FIELDS_KAIGO = (
    # 必須
    "user_name", "year_month", "care_classification", "evaluator_name", "training_goal",
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
    # 必須
    "user_name", "year_month", "care_classification", "evaluator_name", "training_goal",
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
    "eval_memo",
)


def upsert_patient_evaluation(supabase, payload: dict, current_user: str) -> dict:
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
        existing_res = supabase.table("patient_evaluations") \
            .select("id, editing_by, editing_started_at") \
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
        lock_holder = existing.get("editing_by")
        lock_started = existing.get("editing_started_at")
        if lock_holder and lock_holder != current_user and lock_started:
            try:
                started = _parse_iso_datetime(lock_started)
                age = (datetime.now(timezone.utc) - started).total_seconds()
                if age < LOCK_TIMEOUT_MINUTES * 60:
                    return {
                        "success": False,
                        "error": f"{lock_holder} が編集中です(あと約 {int((LOCK_TIMEOUT_MINUTES * 60 - age) / 60)} 分)",
                        "conflict": True,
                        "editing_by": lock_holder,
                    }
            except Exception:
                pass  # パース失敗時は競合扱いせず続行

        # 更新(updated_at を明示、ロック解放)
        clean["updated_at"] = _now_utc_iso()
        clean["editing_by"] = None
        clean["editing_started_at"] = None
        try:
            supabase.table("patient_evaluations").update(clean).eq("id", evaluation_id).execute()
            return {"success": True, "id": evaluation_id, "mode": "update"}
        except Exception as e:
            return {"success": False, "error": f"UPDATE 失敗: {e}"}
    else:
        # ── INSERT 経路 ──
        # ロック関連は INSERT 時は NULL(新規作成と同時にロック解放)
        clean["editing_by"] = None
        clean["editing_started_at"] = None
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
