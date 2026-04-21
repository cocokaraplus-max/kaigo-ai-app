"""
TASUKARU モニタリング書類生成モジュール (Stage2対応版)

追加機能:
  - 利用者情報（patient_care_plans）から目標・支援内容を自動転記
  - AIは「記録からの整文」に専念。事前登録された情報は優先使用
"""
from flask import request, jsonify, send_file, session, redirect, url_for
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from io import BytesIO
import json
import re
import pytz

from monitoring_gen import generate_structured_data
from template_filler import fill_template

# 利用者情報モジュールから取得ヘルパーを借りる
try:
    from patient_info_integration import get_care_plan
except ImportError:
    def get_care_plan(supabase, f_code, user_name):
        """patient_info_integration がまだ無い場合のフォールバック"""
        return None


tokyo_tz = pytz.timezone('Asia/Tokyo')

BASE_DIR = Path(__file__).parent
MAPPINGS_DIR = BASE_DIR / "mappings"
TEMPLATES_XLSX_DIR = BASE_DIR / "templates_xlsx"


def _get_facility_mappings_dir(f_code):
    specific = MAPPINGS_DIR / f_code
    if specific.exists():
        return specific
    default = MAPPINGS_DIR / "default"
    return default if default.exists() else specific


def _get_facility_templates_dir(f_code):
    specific = TEMPLATES_XLSX_DIR / f_code
    if specific.exists():
        return specific
    default = TEMPLATES_XLSX_DIR / "default"
    return default if default.exists() else specific


def list_available_templates(f_code):
    mappings_dir = _get_facility_mappings_dir(f_code)
    if not mappings_dir.exists():
        return []
    result = []
    for mp in sorted(mappings_dir.glob("*.json")):
        try:
            with open(mp, encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "id": mp.stem,
                "name": data.get("template_name", mp.stem),
                "template_file": data.get("template_file", ""),
            })
        except Exception as e:
            print(f"[monitoring] マッピング読込失敗 {mp}: {e}")
    return result


def load_mapping(f_code, template_id):
    mappings_dir = _get_facility_mappings_dir(f_code)
    mp_path = mappings_dir / f"{template_id}.json"
    if not mp_path.exists():
        raise FileNotFoundError(f"様式定義が見つかりません: {template_id}")
    with open(mp_path, encoding="utf-8") as f:
        return json.load(f)


def collect_records_for_period(supabase, f_code, user_name, year, month):
    s_date = tokyo_tz.localize(datetime(year, month, 1))
    e_date = (s_date + timedelta(days=32)).replace(day=1)
    res = supabase.table("records").select(
        "content, staff_name, created_at"
    ).eq("facility_code", f_code).eq("user_name", user_name).gte(
        "created_at", s_date.isoformat()
    ).lt("created_at", e_date.isoformat()).execute()
    if not res.data:
        return []
    return [r for r in res.data if r.get("staff_name") != "AI統合記録"]


def merge_care_plan_into_structured(structured: dict, care_plan: dict) -> dict:
    """
    ケアプラン情報を構造化データにマージ（ケアプラン優先）。
    
    AI生成の項目は、ケアプランに値があればそれで上書きする。
    ケアプランに値が無ければAI生成値を残す。
    """
    if not care_plan:
        return structured
    
    # ケアプラン → mapping.jsonのフィールド名 の対応
    mapping_from_care_plan = {
        # 長期目標
        "long_goal_function":       "long_goal_function",
        "long_goal_activity":       "long_goal_activity",
        "long_goal_participation":  "long_goal_participation",
        "long_goal_period_from":    "long_goal_period_from",
        "long_goal_period_to":      "long_goal_period_to",
        # 短期目標
        "short_goal_function":       "short_goal_function",
        "short_goal_activity":       "short_goal_activity",
        "short_goal_participation":  "short_goal_participation",
        "short_goal_period_from":    "short_goal_period_from",
        "short_goal_period_to":      "short_goal_period_to",
        # 支援内容 = モニタリング項目①〜④
        "support_content_1": "monitoring_item_1",
        "support_content_2": "monitoring_item_2",
        "support_content_3": "monitoring_item_3",
        "support_content_4": "monitoring_item_4",
    }
    
    for care_key, struct_key in mapping_from_care_plan.items():
        value = care_plan.get(care_key)
        if value not in ("", None):
            structured[struct_key] = value
    
    return structured


def register_monitoring_routes(app):
    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("f_code") or not session.get("my_name"):
                if request.args.get("partial"):
                    return jsonify({"redirect": "/login"})
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    @app.route('/monitoring')
    @login_required
    def monitoring_page():
        f_code = session["f_code"]
        templates = list_available_templates(f_code)
        patients = []
        try:
            from app import get_supabase, get_patients
            patients = get_patients(get_supabase(), f_code)
        except Exception as e:
            print(f"[monitoring] 利用者リスト取得失敗: {e}")

        try:
            from app import render as tasukaru_render
            return tasukaru_render("monitoring.html", patients=patients, templates=templates)
        except Exception:
            from flask import render_template
            return render_template("monitoring.html", patients=patients, templates=templates)

    @app.route('/api/monitoring/templates')
    @login_required
    def api_monitoring_templates():
        f_code = session["f_code"]
        return jsonify({"templates": list_available_templates(f_code)})

    @app.route('/api/monitoring/generate', methods=['POST'])
    @login_required
    def api_monitoring_generate():
        try:
            data = request.json or {}
            patient_val = data.get("patient", "")
            month_val = data.get("month", "")
            template_id = data.get("template_id", "")

            if not patient_val or not month_val or not template_id:
                return jsonify({"error": "patient, month, template_id は必須です"}), 400

            f_code = session["f_code"]
            name_match = re.search(r'\[(.*?)\]', patient_val)
            user_name = name_match.group(1) if name_match else patient_val
            y, m = map(int, month_val.split("-"))

            from app import get_supabase
            supabase = get_supabase()
            records = collect_records_for_period(supabase, f_code, user_name, y, m)
            if not records:
                return jsonify({"error": "対象期間に記録がありません。"}), 404

            raw_text = "\n".join([
                f"【{r.get('staff_name', '')}】{r.get('content', '')}"
                for r in records
            ])

            mapping = load_mapping(f_code, template_id)

            # ケアプラン情報を取得
            care_plan = get_care_plan(supabase, f_code, user_name)

            context = {
                "user_name": user_name,
                "period_year": y,
                "period_month": m,
                "staff_name": session.get("my_name", ""),
                "facility_code": f_code,
                "care_plan": care_plan,  # AIプロンプトでも参照可能に
            }

            # AI整文
            structured = generate_structured_data(raw_text, mapping, context)

            # ケアプラン情報で上書き（最優先）
            structured = merge_care_plan_into_structured(structured, care_plan)

            return jsonify({
                "status": "success",
                "structured_data": structured,
                "mapping": mapping,
                "record_count": len(records),
                "care_plan_found": care_plan is not None,
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/monitoring/download', methods=['POST'])
    @login_required
    def api_monitoring_download():
        try:
            data = request.json or {}
            template_id = data.get("template_id", "")
            structured = data.get("structured_data", {})

            if not template_id or not structured:
                return jsonify({"error": "template_id と structured_data は必須です"}), 400

            f_code = session["f_code"]
            mapping = load_mapping(f_code, template_id)

            templates_dir = _get_facility_templates_dir(f_code)
            template_path = templates_dir / mapping["template_file"]

            if not template_path.exists():
                return jsonify({"error": f"様式ファイルが見つかりません: {mapping['template_file']}"}), 404

            buf = BytesIO()
            fill_template(mapping, structured, str(template_path), buf)
            buf.seek(0)

            user_name = structured.get("client_name", "") or structured.get("user_name", "利用者")
            today_str = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
            download_name = f"{mapping.get('template_name', 'monitoring')}_{user_name}_{today_str}.xlsx"

            return send_file(
                buf,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=download_name,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    print("[monitoring] 書類生成ルートを登録しました (Stage2対応)")
    return app
