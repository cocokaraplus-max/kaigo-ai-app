"""
TASUKARU 既存Excel一括インポート用 Flask routes

提供する機能:
  - GET  /patient-info/import          - インポート画面
  - POST /api/patient-info/import/analyze  - アップロードファイルを解析
  - POST /api/patient-info/import/save     - 解析結果を保存
"""
from flask import request, jsonify, session, redirect, url_for
from functools import wraps
from io import BytesIO

from excel_importer import analyze_xlsx, convert_to_care_plan


def register_import_routes(app):
    """Flask に既存Excelインポート用ルートを登録"""
    
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
    # インポート画面
    # ====================================================
    @app.route('/patient-info/import')
    @login_required
    def patient_info_import_page():
        try:
            from app import render as tasukaru_render
            return tasukaru_render("patient_info_import.html")
        except Exception:
            from flask import render_template
            return render_template("patient_info_import.html")
    
    # ====================================================
    # アップロードファイルの解析 API
    # ====================================================
    @app.route('/api/patient-info/import/analyze', methods=['POST'])
    @login_required
    def api_import_analyze():
        """
        multipart/form-data で xlsx を受け取り、解析結果を返す。
        この段階ではDBには保存しない（プレビュー用）。
        """
        try:
            if 'file' not in request.files:
                return jsonify({"error": "ファイルがアップロードされていません"}), 400
            
            uploaded = request.files['file']
            if uploaded.filename == '':
                return jsonify({"error": "ファイル名が空です"}), 400
            
            # xlsx 以外は弾く
            fname = uploaded.filename.lower()
            if not (fname.endswith('.xlsx') or fname.endswith('.xlsm')):
                return jsonify({"error": "xlsxファイルのみ対応しています"}), 400
            
            # メモリ上で解析
            file_bytes = uploaded.read()
            result = analyze_xlsx(BytesIO(file_bytes))
            
            if result["status"] != "success":
                return jsonify({
                    "error": "解析に失敗しました",
                    "warnings": result.get("warnings", []),
                }), 400
            
            return jsonify({
                "status": "success",
                "filename": uploaded.filename,
                "latest_sheet_name": result["latest_sheet_name"],
                "latest_period": result["latest_period"],
                "extracted": result["extracted"],
                "missing_fields": result["missing_fields"],
                "warnings": result["warnings"],
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    # ====================================================
    # 解析結果を patient_care_plans に保存 API
    # ====================================================
    @app.route('/api/patient-info/import/save', methods=['POST'])
    @login_required
    def api_import_save():
        """
        解析&ユーザーによる修正後のデータを受け取り、DBに保存。
        """
        try:
            data = request.json or {}
            extracted = data.get("extracted", {})
            
            if not extracted.get("user_name"):
                return jsonify({"error": "利用者氏名が空です"}), 400
            
            f_code = session["f_code"]
            
            # ケアプラン形式に変換
            care_plan = convert_to_care_plan(extracted)
            
            # 既存の upsert を再利用
            from patient_info_integration import upsert_care_plan
            from app import get_supabase
            
            supabase = get_supabase()
            saved = upsert_care_plan(supabase, f_code, care_plan)
            
            return jsonify({
                "status": "success",
                "user_name": care_plan["user_name"],
                "saved": saved,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    print("[patient_info_import] Excelインポートルートを登録しました")
    return app
