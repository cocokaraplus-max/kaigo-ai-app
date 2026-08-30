# ===== shared-login-v1 : LINE承認ログインの本体 =====
#   設計_LINE承認ログイン.md の §2 / §3 / §7 / §8。
#
#   ★既存の /login には1行も触らない。ここは新しいURLだけ。
#     旧方式は残す（設計 §12・案C）。閉じるのは最後の回。
#
#   ★鍵を2本に分けるのが肝。
#       poll_token    … PCだけが持つ。これでしかセッションを作れない
#       approve_token … LINEに送る。これでは【ログインできない】
#     LINEのメッセージを人に転送されても、転送先はログインできない。
#
#   ★「開いただけ」では通さない。
#     GET /login/approve は画面を出すだけ。承認は POST。
#     リンクのプレビュー取得や、指が当たっただけでは通らない。
#
#   ★確認番号（4桁）を画面とLINEの両方に出す。
#     番号が同じことを見てから押してもらう。これが無いと、
#     別人が自分の名前で入ろうとしたのを、うっかり承認してしまう。
#
#   ★ここでも「確かめられなかった」は全部【通さない】側に倒す。

_SL_TTL_SEC = 180          # 承認は3分で切れる（設計 §3）
_SL_RATE_SEC = 30          # 同じ人への要求は30秒に1回まで
_SL_RATE_HOUR_MAX = 10     # 同じ人へ1時間に10回まで
_SL_BUSY = {"status": "error",
            "message": "いま確認できませんでした。時間をおいて、もう一度お試しください。"}


def _sl_now():
    return datetime.now(timezone.utc)


def _sl_token():
    """推測できない鍵。★乱数は secrets を使う（random は予測できてしまう）。"""
    import secrets
    return secrets.token_urlsafe(32)


def _sl_check_code():
    """画面とLINEの両方に出す4桁。★秘密ではない。見比べるためのもの。"""
    import secrets
    return "%04d" % secrets.randbelow(10000)


def _sl_expired(row):
    """期限切れか。★読めない値は【切れている】とみなす（安全側）。"""
    raw = row.get("expires_at")
    if not raw:
        return True
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")) <= _sl_now()
    except (ValueError, TypeError):
        print("[shared-login] expires_at が読めない: %r" % raw, flush=True)
        return True


def _sl_find_request(supabase, field, value):
    """承認要求を1件さがす。返り値は (行, 確かめられたか)。
    ★「無かった」と「聞けなかった」を分ける。ここを混ぜると、
      通信の失敗が「そんな要求は無い」に化けて、原因が分からなくなる。"""
    try:
        res = (supabase.table("login_requests").select("*")
               .eq(field, value).limit(1).execute())
        rows = res.data or []
        return (rows[0] if rows else None), True
    except Exception as e:
        print("[shared-login] 承認要求の確認に失敗: %s" % e, flush=True)
        return None, False


def _sl_flex_approve(staff_name, device_label, check_code, approve_url, when_text):
    """LINEに送るボタン付きメッセージ（Flex Message）を組み立てる。

    ★既存の送信（line_send_message）は触らない。ここは【中身を作るだけ】。
      送るのは既存の関数に渡す。
    """
    return {
        "type": "flex",
        "altText": "【TASUKARU】ログイン承認 確認番号 %s" % check_code,
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#1a73e8",
                "paddingAll": "14px",
                "contents": [{"type": "text", "text": "TASUKARU ログイン承認",
                              "color": "#ffffff", "weight": "bold", "size": "md"}],
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "16px",
                "contents": [
                    {"type": "box", "layout": "baseline", "contents": [
                        {"type": "text", "text": "名前", "size": "sm", "color": "#9aa0a6", "flex": 2},
                        {"type": "text", "text": staff_name, "size": "sm",
                         "color": "#202124", "weight": "bold", "flex": 5, "wrap": True}]},
                    {"type": "box", "layout": "baseline", "contents": [
                        {"type": "text", "text": "端末", "size": "sm", "color": "#9aa0a6", "flex": 2},
                        {"type": "text", "text": device_label, "size": "sm",
                         "color": "#202124", "flex": 5, "wrap": True}]},
                    {"type": "box", "layout": "baseline", "contents": [
                        {"type": "text", "text": "日時", "size": "sm", "color": "#9aa0a6", "flex": 2},
                        {"type": "text", "text": when_text, "size": "sm",
                         "color": "#202124", "flex": 5}]},
                    {"type": "separator", "margin": "lg"},
                    {"type": "text", "text": "確認番号", "size": "xs", "color": "#9aa0a6",
                     "align": "center", "margin": "lg"},
                    {"type": "text", "text": check_code, "size": "3xl", "weight": "bold",
                     "color": "#1a73e8", "align": "center"},
                    {"type": "text",
                     "text": "画面に出ている番号と同じことを確かめてから押してください。",
                     "size": "xs", "color": "#5f6368", "wrap": True, "align": "center",
                     "margin": "md"},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "12px",
                "contents": [
                    {"type": "button", "style": "primary", "color": "#1a73e8",
                     "action": {"type": "uri", "label": "承認する", "uri": approve_url}},
                    {"type": "text",
                     "text": "心当たりがないときは、押さずにこのまま置いてください。3分で切れます。",
                     "size": "xxs", "color": "#9aa0a6", "wrap": True, "align": "center"},
                ],
            },
        },
    }


@app.route("/shared-login", methods=["GET"])
def shared_login_page():
    """共有PCのログイン画面。★ログインしていなくても開ける。

    許可された端末かどうかは、画面が開いたあとに /api/shared-login/names で確かめる。
    未登録の端末には、そこで登録の申請フォームを出す。
    """
    return render_template("shared_login.html")


@app.route("/api/shared-login/names", methods=["GET"])
def api_shared_login_names():
    """職員名の一覧。★許可された端末にだけ返す（設計 §3）。

    ここを誰にでも返すと、URLを知っている人が職員名を並べられてしまう。
    """
    f_code = (request.args.get("fc") or "").strip()
    token = (request.args.get("token") or "").strip()
    if not f_code or not token:
        return jsonify({"status": "error", "message": "施設コードと端末の印が必要です。"}), 400

    supabase = get_supabase()
    dev, checked = _login_device_find(supabase, f_code, token)
    if not checked:
        return jsonify(_SL_BUSY), 503
    if not dev:
        return jsonify({"status": "unregistered",
                        "message": "この端末はまだ登録されていません。"}), 200
    if dev.get("revoked_at"):
        return jsonify({"status": "revoked",
                        "message": "この端末は使えなくなっています。管理者にご連絡ください。"}), 200
    if not dev.get("is_active"):
        return jsonify({"status": "pending",
                        "message": "管理者の承認をお待ちください。"}), 200

    try:
        res = (supabase.table("staffs").select("staff_name,line_user_id")
               .eq("facility_code", f_code).eq("is_active", True).execute())
    except Exception as e:
        print("[shared-login] 職員名の取得に失敗: %s" % e, flush=True)
        return jsonify(_SL_BUSY), 503

    names = []
    for s in (res.data or []):
        nm = (s.get("staff_name") or "").strip()
        if not nm:
            continue
        # ★LINEが繋がっていない人も名前は出す。
        #   出さないと「自分の名前が無い」で止まってしまう。
        #   選んだときに「旧方式で入ってください」と案内する。
        names.append({"name": nm, "line": bool((s.get("line_user_id") or "").strip())})
    names.sort(key=lambda x: x["name"])
    return jsonify({"status": "success",
                    "device_label": dev.get("device_label") or "この端末",
                    "names": names})


@app.route("/api/shared-login/request", methods=["POST"])
def api_shared_login_request():
    """承認要求を作り、本人のLINEへボタン付きで送る。"""
    data = request.get_json(silent=True) or {}
    f_code = (data.get("fc") or "").strip()
    token = (data.get("token") or "").strip()
    staff_name = (data.get("staff_name") or "").strip()
    if not f_code or not token or not staff_name:
        return jsonify({"status": "error", "message": "入力が足りません。"}), 400

    supabase = get_supabase()

    # ★許可された端末からしか要求を作らせない。
    dev, checked = _login_device_find(supabase, f_code, token)
    if not checked:
        return jsonify(_SL_BUSY), 503
    if not dev or dev.get("revoked_at") or not dev.get("is_active"):
        return jsonify({"status": "error",
                        "message": "この端末は使えません。管理者にご連絡ください。"}), 403

    # 本人を探す。★LINEが繋がっていなければ、ここで正直にそう言う。
    try:
        st = (supabase.table("staffs").select("staff_name,line_user_id")
              .eq("facility_code", f_code).eq("staff_name", staff_name)
              .eq("is_active", True).limit(1).execute())
    except Exception as e:
        print("[shared-login] 職員の確認に失敗: %s" % e, flush=True)
        return jsonify(_SL_BUSY), 503
    rows = st.data or []
    if not rows:
        return jsonify({"status": "error", "message": "その名前は登録されていません。"}), 400
    line_uid = (rows[0].get("line_user_id") or "").strip()
    if not line_uid:
        return jsonify({"status": "no_line",
                        "message": "この方はLINEがつながっていないため、この方法では入れません。"
                                   "施設コードとパスワードでログインしてください。"}), 200

    # ★連投を止める（設計 §3）。LINEを埋め尽くす嫌がらせを防ぐ。
    now = _sl_now()
    try:
        recent = (supabase.table("login_requests").select("created_at")
                  .eq("facility_code", f_code).eq("staff_name", staff_name)
                  .gte("created_at", (now - timedelta(hours=1)).isoformat()).execute())
    except Exception as e:
        print("[shared-login] 連投の確認に失敗: %s" % e, flush=True)
        # ★数えられないときは作らない。ここを通すと制限が意味を失う。
        return jsonify(_SL_BUSY), 503
    rec = recent.data or []
    if len(rec) >= _SL_RATE_HOUR_MAX:
        return jsonify({"status": "error",
                        "message": "この1時間に何度も送っています。しばらくおいてからお試しください。"}), 429
    for r in rec:
        try:
            t = datetime.fromisoformat(str(r.get("created_at")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if (now - t).total_seconds() < _SL_RATE_SEC:
            return jsonify({"status": "error",
                            "message": "少し前に送っています。30秒ほどおいてからお試しください。"}), 429

    poll_token = _sl_token()
    approve_token = _sl_token()
    code = _sl_check_code()
    row = {
        "facility_code": f_code, "staff_name": staff_name, "device_token": token,
        "poll_token": poll_token, "approve_token": approve_token, "check_code": code,
        "status": "pending",
        "requested_ip": _login_client_ip(),
        "user_agent": (request.headers.get("User-Agent") or "")[:300],
        "expires_at": (now + timedelta(seconds=_SL_TTL_SEC)).isoformat(),
        "created_at": now.isoformat(),
    }
    try:
        supabase.table("login_requests").insert(row).execute()
    except Exception as e:
        print("[shared-login] 承認要求の登録に失敗: %s" % e, flush=True)
        return jsonify(_SL_BUSY), 503

    # LINEへ送る。★送れなかったら、そう言って旧方式へ逃がす（設計 §9）。
    approve_url = request.host_url.rstrip("/") + "/login/approve?t=" + approve_token
    jst_now = now + timedelta(hours=9)
    flex = _sl_flex_approve(staff_name, dev.get("device_label") or "この端末",
                            code, approve_url,
                            "%d月%d日 %02d:%02d" % (jst_now.month, jst_now.day,
                                                    jst_now.hour, jst_now.minute))
    sent = False
    try:
        sent = line_send_message(line_uid, [flex])
    except Exception as e:
        print("[shared-login] LINE送信に失敗: %s" % e, flush=True)
    if not sent:
        # ★作った要求は残しておく。3分で切れる。
        #   消すと「送れなかったのか、作れなかったのか」が分からなくなる。
        return jsonify({"status": "line_failed",
                        "message": "LINEに送れませんでした。"
                                   "施設コードとパスワードでログインしてください。"}), 200

    return jsonify({"status": "sent", "poll_token": poll_token,
                    "check_code": code, "ttl": _SL_TTL_SEC})


@app.route("/api/shared-login/poll", methods=["GET"])
def api_shared_login_poll():
    """承認されたかを確かめる。承認されていればここでログインさせる。

    ★セッションを作れるのは poll_token を持っているPCだけ。
      LINEに送った鍵（approve_token）では、ここへ来てもログインできない。
    """
    poll_token = (request.args.get("p") or "").strip()
    if not poll_token:
        return jsonify({"status": "error", "message": "鍵がありません。"}), 400

    supabase = get_supabase()
    row, checked = _sl_find_request(supabase, "poll_token", poll_token)
    if not checked:
        return jsonify(_SL_BUSY), 503
    if not row:
        return jsonify({"status": "unknown"}), 200

    st = row.get("status")
    if st == "denied":
        return jsonify({"status": "denied"}), 200
    if st == "used":
        return jsonify({"status": "used"}), 200
    if _sl_expired(row):
        return jsonify({"status": "expired"}), 200
    if st != "approved":
        return jsonify({"status": "pending"}), 200

    # ★ここで初めてログインさせる。先に「使った」印を付けてから通す。
    #   逆にすると、印を付ける前に落ちたとき、同じ鍵で二度ログインできてしまう。
    try:
        (supabase.table("login_requests")
         .update({"status": "used", "decided_at": _sl_now().isoformat()})
         .eq("id", row["id"]).eq("status", "approved").execute())
    except Exception as e:
        print("[shared-login] 使用済みにできない: %s" % e, flush=True)
        return jsonify(_SL_BUSY), 503

    session["f_code"] = row["facility_code"]
    session["my_name"] = row["staff_name"]
    session["saved_f_code"] = row["facility_code"]
    # ★前の人の管理者権限を引き継がせない（既存の /login と同じ）。
    session["admin_authenticated"] = False
    session["dev_authenticated"] = False
    # shared-login-v1: この端末は共有か専用か。次の回（自動ログアウト）で使う。
    session["login_device_token"] = row.get("device_token")

    try:
        (supabase.table("login_devices")
         .update({"last_used_at": _sl_now().isoformat()})
         .eq("facility_code", row["facility_code"])
         .eq("device_token", row.get("device_token")).execute())
    except Exception as e:
        # ★ここは記録だけ。失敗してもログインは通す。
        print("[shared-login] last_used_at を書けない: %s" % e, flush=True)

    return jsonify({"status": "approved", "redirect": "/"})


@app.route("/login/approve", methods=["GET"])
def login_approve_page():
    """LINEから開く承認ページ。★開いただけでは承認しない（設計 §3）。

    ここは画面を出すだけ。承認は下の POST で。
    リンクのプレビュー取得や、誤タップでは通らない。
    """
    t = (request.args.get("t") or "").strip()
    if not t:
        return render_template("login_approve.html", state="invalid")

    supabase = get_supabase()
    row, checked = _sl_find_request(supabase, "approve_token", t)
    if not checked:
        return render_template("login_approve.html", state="busy")
    if not row:
        return render_template("login_approve.html", state="invalid")
    if row.get("status") == "denied":
        return render_template("login_approve.html", state="denied")
    if row.get("status") == "used":
        return render_template("login_approve.html", state="used")
    if _sl_expired(row):
        return render_template("login_approve.html", state="expired")
    if row.get("status") == "approved":
        return render_template("login_approve.html", state="already")

    return render_template("login_approve.html", state="ask", t=t,
                           staff_name=row.get("staff_name"),
                           check_code=row.get("check_code"))


@app.route("/login/approve", methods=["POST"])
def login_approve_do():
    """ここで初めて承認する／拒否する。"""
    data = request.get_json(silent=True) or {}
    t = (data.get("t") or "").strip()
    action = (data.get("action") or "").strip()
    if not t or action not in ("approve", "deny"):
        return jsonify({"status": "error", "message": "入力が正しくありません。"}), 400

    supabase = get_supabase()
    row, checked = _sl_find_request(supabase, "approve_token", t)
    if not checked:
        return jsonify(_SL_BUSY), 503
    if not row:
        return jsonify({"status": "error", "message": "この要求は見つかりません。"}), 404
    if row.get("status") != "pending":
        return jsonify({"status": "error", "message": "この要求はもう使えません。"}), 409
    if _sl_expired(row):
        return jsonify({"status": "error",
                        "message": "3分が過ぎたため無効になりました。もう一度やり直してください。"}), 410

    new_status = "approved" if action == "approve" else "denied"
    try:
        # ★status が pending のままのときだけ書き換える。
        #   二重に押されても、あとから来たほうは何も起きない。
        (supabase.table("login_requests")
         .update({"status": new_status, "decided_at": _sl_now().isoformat()})
         .eq("id", row["id"]).eq("status", "pending").execute())
    except Exception as e:
        print("[shared-login] 承認の書き込みに失敗: %s" % e, flush=True)
        return jsonify(_SL_BUSY), 503

    return jsonify({"status": "success", "result": new_status})
# ===== /shared-login-v1 =====


