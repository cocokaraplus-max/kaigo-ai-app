with open('app.py', 'r') as f:
    content = f.read()

update_api = """
@app.route("/api/board/update_post", methods=["POST"])
@login_required
def api_board_update_post():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        post = supabase.table("board_posts").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not post.data: return jsonify({"status": "error", "message": "見つかりません"}), 404
        p = post.data[0]
        if p["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        if not is_admin and p["staff_name"] != my_name:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        supabase.table("board_posts").update({
            "content": data.get("content", ""),
            "updated_at": "now()"
        }).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
"""

old = '@app.route("/api/board/delete_post"'
if old in content:
    content = content.replace(old, update_api + '\n' + old, 1)
    with open('app.py', 'w') as f:
        f.write(content)
    print("OK 行数:", len(content.splitlines()))
else:
    print("挿入位置なし")
