# このファイルをkaigo-ai-appフォルダに置いて実行してください
# python3 add_board.py

board_api = '''
# ==========================================
# 掲示板
# ==========================================

@app.route('/board')
@login_required
def board():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    posts = []
    try:
        res = supabase.table("board_posts").select("*").eq("facility_code", f_code).order("is_pinned", desc=True).order("created_at", desc=True).limit(30).execute()
        posts = res.data or []
    except Exception as e:
        print(f"board error: {e}")
    icons = get_staff_icons(supabase, f_code)
    post_ids = [p["id"] for p in posts]
    comments_count = {}
    reactions_data = {}
    read_data = {}
    try:
        if post_ids:
            for pid in post_ids:
                cnt = supabase.table("board_comments").select("id", count="exact").eq("post_id", pid).execute()
                comments_count[pid] = cnt.count or 0
            rres = supabase.table("board_reactions").select("*").in_("post_id", post_ids).execute()
            for r in (rres.data or []):
                pid = r["post_id"]
                if pid not in reactions_data: reactions_data[pid] = {}
                em = r["reaction"]
                if em not in reactions_data[pid]: reactions_data[pid][em] = []
                reactions_data[pid][em].append(r["staff_name"])
            rdres = supabase.table("board_reads").select("post_id,staff_name").in_("post_id", post_ids).execute()
            for r in (rdres.data or []):
                pid = r["post_id"]
                if pid not in read_data: read_data[pid] = []
                read_data[pid].append(r["staff_name"])
    except Exception as e:
        print(f"board detail error: {e}")
    staffs = [name for name in icons.keys()]
    return render("board.html",
        posts=posts, icons=icons, my_name=my_name,
        my_color=staff_color(my_name), my_initial=staff_initial(my_name),
        comments_count=comments_count, reactions_data=reactions_data,
        read_data=read_data, staffs=staffs,
        supabase_url=get_secret("SUPABASE_URL"),
        supabase_anon_key=get_secret("SUPABASE_KEY"),
    )

@app.route("/api/board/create_post", methods=["POST"])
@login_required
def api_board_create_post():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        content = request.form.get("content", "").strip()
        photos = request.files.getlist("photos")
        audio = request.files.get("audio")
        import json as _json
        mentions = _json.loads(request.form.get("mention_names", "[]"))
        image_urls = []
        if photos and photos[0].filename:
            from utils import upload_images_to_supabase
            image_urls = upload_images_to_supabase(supabase, photos, f_code)
        audio_url = ""
        if audio and audio.filename:
            from utils import upload_audio_to_supabase
            audio_url = upload_audio_to_supabase(supabase, audio.read(), audio.filename, f_code)
        res = supabase.table("board_posts").insert({
            "facility_code": f_code, "staff_name": my_name,
            "content": content, "image_urls": image_urls,
            "file_urls": [], "audio_url": audio_url,
            "mention_names": mentions, "is_pinned": False,
        }).execute()
        return jsonify({"status": "success", "post_id": res.data[0]["id"] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/delete_post", methods=["POST"])
@login_required
def api_board_delete_post():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        post = supabase.table("board_posts").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not post.data: return jsonify({"status": "error"}), 404
        p = post.data[0]
        if p["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        if not is_admin and p["staff_name"] != my_name: return jsonify({"status": "error", "message": "権限がありません"}), 403
        supabase.table("board_posts").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route("/api/board/pin_post", methods=["POST"])
@login_required
def api_board_pin_post():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        if not is_admin: return jsonify({"status": "error", "message": "管理者のみ操作可能"}), 403
        supabase = get_supabase()
        supabase.table("board_posts").update({"is_pinned": data.get("pinned", True)}).eq("id", data["id"]).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route("/api/board/get_comments")
@login_required
def api_board_get_comments():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        post_id = request.args.get("post_id")
        supabase = get_supabase()
        icons = get_staff_icons(supabase, f_code)
        res = supabase.table("board_comments").select("*").eq("post_id", post_id).eq("facility_code", f_code).order("created_at").execute()
        comments = []
        for c in (res.data or []):
            ic = staff_icon_data(icons, c["staff_name"])
            comments.append({**c, "color": ic["color"], "initial": ic["initial"],
                "emoji": ic.get("emoji",""), "image_url": ic.get("image_url",""),
                "is_mine": c["staff_name"] == my_name, "time_label": parse_jst(c["created_at"])})
        try:
            supabase.table("board_reads").upsert({
                "facility_code": f_code, "post_id": int(post_id), "staff_name": my_name
            }, on_conflict="post_id,staff_name").execute()
        except: pass
        return jsonify({"status": "success", "comments": comments})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/add_comment", methods=["POST"])
@login_required
def api_board_add_comment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        res = supabase.table("board_comments").insert({
            "facility_code": f_code, "post_id": data["post_id"],
            "staff_name": my_name, "content": data.get("content","").strip(),
            "mention_names": data.get("mention_names", []),
        }).execute()
        return jsonify({"status": "success", "comment_id": res.data[0]["id"] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/delete_comment", methods=["POST"])
@login_required
def api_board_delete_comment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        c = supabase.table("board_comments").select("staff_name").eq("id", data["id"]).execute()
        if not c.data: return jsonify({"status": "error"}), 404
        if not is_admin and c.data[0]["staff_name"] != my_name:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        supabase.table("board_comments").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route("/api/board/react", methods=["POST"])
@login_required
def api_board_react():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        post_id = data.get("post_id")
        reaction = data.get("reaction", "✅")
        existing = supabase.table("board_reactions").select("id").eq("post_id", post_id).eq("staff_name", my_name).eq("reaction", reaction).execute()
        if existing.data:
            supabase.table("board_reactions").delete().eq("id", existing.data[0]["id"]).execute()
            action = "removed"
        else:
            supabase.table("board_reactions").insert({
                "facility_code": f_code, "post_id": post_id,
                "staff_name": my_name, "reaction": reaction,
            }).execute()
            action = "added"
        rres = supabase.table("board_reactions").select("reaction,staff_name").eq("post_id", post_id).execute()
        reactions = {}
        for r in (rres.data or []):
            em = r["reaction"]
            if em not in reactions: reactions[em] = []
            reactions[em].append(r["staff_name"])
        return jsonify({"status": "success", "action": action, "reactions": reactions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/unread_count")
@login_required
def api_board_unread_count():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        all_posts = supabase.table("board_posts").select("id").eq("facility_code", f_code).execute()
        all_ids = [p["id"] for p in (all_posts.data or [])]
        if not all_ids: return jsonify({"count": 0})
        read_posts = supabase.table("board_reads").select("post_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        read_ids = set(r["post_id"] for r in (read_posts.data or []))
        return jsonify({"count": len([i for i in all_ids if i not in read_ids])})
    except Exception as e:
        return jsonify({"count": 0})
'''

with open('app.py', 'r') as f:
    content = f.read()

old = "if __name__ == '__main__':"
if old in content:
    content = content.replace(old, board_api + "\n" + old, 1)
    with open('app.py', 'w') as f:
        f.write(content)
    print("掲示板API追加OK")
    print("行数:", len(content.splitlines()))
else:
    print("挿入位置が見つかりません")
