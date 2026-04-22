"""
TASUKARU 利用者情報（ケアプラン）管理モジュール

このモジュールが提供する機能:
  - /patient-info                     - 利用者情報編集画面
  - GET  /api/patient-info/list       - 利用者一覧（ケアプラン登録状況込み）
  - GET  /api/patient-info/get        - 特定利用者のケアプラン取得
  - POST /api/patient-info/save       - ケアプランを保存（新規/更新）

また、他モジュール（モニタリング書類生成）から使うためのヘルパー関数:
  - get_care_plan(supabase, f_code, user_name_or_chart_no) -> dict | None
"""
from flask import request, jsonify, session, redirect, url_for
from functools import wraps
from datetime import datetime
import re


def get_care_plan(supabase, f_code: str, user_name: str) -> dict:
    """
    利用者のケアプラン情報を取得。無ければNone。
    
    Args:
        supabase: Supabaseクライアント
        f_code: 事業所コード
        user_name: 利用者名
    
    Returns:
        dict（ケアプラン情報）or None
    """
    try:
        res = (supabase.table("patient_care_plans")
                       .select("*")
                       .eq("facility_code", f_code)
                       .eq("user_name", user_name)
                       .execute())
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception as e:
        print(f"[patient_info] get_care_plan error: {e}")
    return None


def upsert_care_plan(supabase, f_code: str, data: dict) -> dict:
    """
    ケアプランを新規作成または更新（upsert）
    """
    # 必須項目チェック
    if not data.get("user_name"):
        raise ValueError("user_name は必須です")
    
    # chart_number が無ければ user_name で代用
    if not data.get("chart_number"):
        data["chart_number"] = data.get("user_name", "")
    
    # facility_codeを確実にセット
    data["facility_code"] = f_code
    
    # 空文字を None に変換（date型カラム用）
    for date_key in ("long_goal_period_from", "long_goal_period_to",
                      "short_goal_period_from", "short_goal_period_to"):
        if data.get(date_key) == "":
            data[date_key] = None
    
    try:
        # 既存レコードを確認
        existing = (supabase.table("patient_care_plans")
                            .select("id")
                            .eq("facility_code", f_code)
                            .eq("chart_number", data["chart_number"])
                            .execute())
        
        if existing.data and len(existing.data) > 0:
            # UPDATE
            record_id = existing.data[0]["id"]
            # idは更新対象から除外
            update_data = {k: v for k, v in data.items() if k != "id"}
            res = (supabase.table("patient_care_plans")
                           .update(update_data)
                           .eq("id", record_id)
                           .execute())
        else:
            # INSERT
            insert_data = {k: v for k, v in data.items() if k != "id"}
            res = (supabase.table("patient_care_plans")
                           .insert(insert_data)
                           .execute())
        
        return res.data[0] if res.data else {}
    except Exception as e:
        print(f"[patient_info] upsert_care_plan error: {e}")
        raise


def register_patient_info_routes(app):
    """Flaskアプリに利用者情報管理のルートを登録"""
    
    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("f_code") or not session.get("my_name"):
                if request.args.get("partial"):
                    return jsonify({"redirect": "/login"})
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated
    
    # ====================================================
    # 利用者情報編集画面
    # ====================================================
    @app.route('/patient-info')
    @login_required
    def patient_info_page():
        f_code = session["f_code"]
        patients = []
        try:
            from app import get_supabase, get_patients
            patients = get_patients(get_supabase(), f_code)
        except Exception as e:
            print(f"[patient_info] 利用者リスト取得失敗: {e}")
        
        try:
            from app import render as tasukaru_render
            return tasukaru_render("patient_info.html", patients=patients)
        except Exception:
            from flask import render_template
            return render_template("patient_info.html", patients=patients)
    
    # ====================================================
    # 利用者ごとのケアプラン取得API
    # ====================================================
    @app.route('/api/patient-info/get', methods=['GET'])
    @login_required
    def api_patient_info_get():
        f_code = session["f_code"]
        patient = request.args.get("patient", "")
        
        # [利用者名] 形式の場合は中身を取り出す
        m = re.search(r'\[(.*?)\]', patient)
        user_name = m.group(1) if m else patient
        
        if not user_name:
            return jsonify({"error": "patient is required"}), 400
        
        try:
            from app import get_supabase
            supabase = get_supabase()
            care_plan = get_care_plan(supabase, f_code, user_name)
            return jsonify({
                "status": "success",
                "user_name": user_name,
                "care_plan": care_plan,  # None の可能性あり
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    # ====================================================
    # 保存API
    # ====================================================
    @app.route('/api/patient-info/save', methods=['POST'])
    @login_required
    def api_patient_info_save():
        f_code = session["f_code"]
        data = request.json or {}
        
        try:
            saved = upsert_care_plan(f_code=f_code, data=data,
                                      supabase=__import__("app").get_supabase())
            return jsonify({"status": "success", "data": saved})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    # ====================================================
    # ケアプラン登録状況一覧
    # ====================================================
    @app.route('/api/patient-info/list', methods=['GET'])
    @login_required
    def api_patient_info_list():
        f_code = session["f_code"]
        try:
            from app import get_supabase, get_patients
            supabase = get_supabase()
            
            # 利用者全員
            all_patients = get_patients(supabase, f_code)
            
            # ケアプラン登録済みの利用者名
            res = (supabase.table("patient_care_plans")
                           .select("user_name")
                           .eq("facility_code", f_code)
                           .execute())
            registered = set(r["user_name"] for r in (res.data or []))
            
            result = []
            for p in all_patients:
                m = re.search(r'\[(.*?)\]', p)
                name = m.group(1) if m else p
                result.append({
                    "display": p,
                    "user_name": name,
                    "has_care_plan": name in registered,
                })
            
            return jsonify({"status": "success", "patients": result})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    print("[patient_info] 利用者情報ルートを登録しました")
    return app
