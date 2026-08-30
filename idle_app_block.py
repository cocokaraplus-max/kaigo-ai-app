# ===== idle-logout-v1 : 共有PCの30分自動ログアウト＋書きかけの一時退避 =====
#   設計_LINE承認ログイン.md の §5。
#
#   ★落とし穴（設計書に書いてある、調べて分かったこと）
#     base.html は全画面で30秒ごとに /api/board/unread_count を叩いている。
#     「通信が来た＝操作中」と作ると、誰も触っていないPCが【永遠に落ちない】。
#     しかもエラーが出ないので、動いているつもりで放置される。
#     だから【既定は「操作していない」】。人が触ったときだけ画面から知らせる。
#     こうしておけば、あとから定期通信が増えても壊れない。
#
#   ★落とすのは「共有」と設定された端末だけ（HIROさん判断 2026-08-29）。
#       ・承認ログインで入った
#       ・その端末が login_devices にあり、サーバ側で is_shared
#     この両方がそろったときだけ。
#     本人のスマホ・いつものPC（施設コード＋パスワードで入った人）は落とさない。
#
#   ★判定は【ログインした時点でセッションに封じ込める】。
#     セッションは署名付きなので、ブラウザから書き換えられない。
#     毎回DBに聞くと、全画面・全リクエストで問い合わせが増える。
#     ただし、管理者が途中で「共有」に変えても、いま入っている人には効かない。
#     次のログインから効く。ここは承知のうえで選んでいる。
#
#   ★分からないときは【落とさない】。
#     ここだけは「安全側＝止める」ではない。通信が一瞬詰まっただけで
#     記録の途中の職員が蹴られるほうが、現場では害が大きい。
#     判定は毎リクエスト走るので、戻れば次で落ちる。

_IDLE_LIMIT_SEC = 1800      # 30分
_IDLE_WARN_SEC = 1740       # 29分（画面に警告を出す）
_IDLE_TOUCH_MIN_SEC = 55    # 画面から知らせるのは最大1分に1回

# 自動ログアウトの判定をしない道。
# ★ここに「操作したことを知らせる道」と「ログインの道」を必ず入れる。
#   入れ忘れると、落ちたあと入り直せなくなる。
_IDLE_SKIP_PREFIX = (
    "/static/", "/api/session/touch", "/api/session/state",
    "/login", "/logout", "/shared-login", "/api/shared-login/",
    "/favicon", "/healthz",
)


def _idle_is_shared_session():
    """いま入っている人は、共有端末から入ったか。"""
    return bool(session.get("login_device_shared"))


@app.before_request
def _idle_logout_guard():   # idle-logout-v1
    """共有端末で30分さわっていなければ、ここで降ろす。"""
    try:
        if not session.get("f_code") or not _idle_is_shared_session():
            return None
        path = request.path or ""
        for p in _IDLE_SKIP_PREFIX:
            if path.startswith(p):
                return None

        import time as _idle_time
        now = int(_idle_time.time())
        last = session.get("last_touch")
        if not isinstance(last, int):
            # ★分からないときは落とさない。いまを起点にして様子を見る。
            session["last_touch"] = now
            return None
        if now - last < _IDLE_LIMIT_SEC:
            return None

        session.clear()
        if request.args.get("partial") or path.startswith("/api/"):
            return jsonify({"status": "error", "code": "idle_logout",
                            "message": "30分さわらなかったため、ログアウトしました。",
                            "redirect": "/shared-login?timeout=1"}), 401
        return redirect("/shared-login?timeout=1")
    except Exception as e:
        # ★ここで落ちてもアプリを止めない。判定できなければ通す。
        print("[idle-logout] 判定に失敗: %s" % e, flush=True)
        return None


@app.route("/api/session/touch", methods=["POST"])
def api_session_touch():
    """人が触ったことを知らせる。★画面から明示的に呼ぶときだけ動く。

    ★定期通信からは呼ばないこと。呼ぶと自動ログアウトが1度も働かなくなる。
    """
    if not session.get("f_code"):
        return jsonify({"status": "error", "message": "ログインしていません。"}), 401
    import time as _t
    session["last_touch"] = int(_t.time())
    return jsonify({"status": "success"})


@app.route("/api/session/state", methods=["GET"])
def api_session_state():
    """この画面で自動ログアウトの見張りをするかどうかを返す。

    ★見張るかどうかは【サーバが決める】。画面の値では決めない。
      実際に降ろすのも上の before_request なので、
      画面をいじって見張りを外しても、ログアウト自体は止められない。
    """
    if not session.get("f_code"):
        return jsonify({"status": "success", "shared": False})
    import time as _t
    last = session.get("last_touch")
    if not isinstance(last, int):
        last = int(_t.time())
    remain = _IDLE_LIMIT_SEC - (int(_t.time()) - last)
    return jsonify({"status": "success",
                    "shared": _idle_is_shared_session(),
                    "limit": _IDLE_LIMIT_SEC,
                    "warn_at": _IDLE_WARN_SEC,
                    "touch_min": _IDLE_TOUCH_MIN_SEC,
                    "remaining": max(0, remain)})


# ---------------------------------------------------------------------------
# 書きかけの一時退避（draft_autosaves）
#
#   ★30分で落ちるとき、書きかけの記録が消える。現場でいちばん怒られるところ。
#   ★共有PCなので、必ず staff_name で絞る。ここを間違えると
#     【他人の書きかけが見えてしまう】。中身は利用者の記録そのもの。
#   ★7日たっても戻されなければ捨てる。書きかけを溜めっぱなしにしない。
# ---------------------------------------------------------------------------

_DRAFT_MAX_BYTES = 100 * 1024   # 1件の上限。音声などの大きい中身は入れない
_DRAFT_KEEP_DAYS = 7


def _draft_key_ok(k):
    """退避の鍵の形。★英数字と _ : - だけ。

    ★. と / を外した。ファイルの道として使ってはいないので穴ではないが、
      「../」のような文字列が通ると、読む人が道だと勘違いする。
      通す形は、いま使うぶんだけにしておく（form_key は "input" だけ）。
      （試験で ../etc が通ることに気づいて狭めた 2026-08-30）
    """
    return bool(k) and len(k) <= 120 and re.match(r"^[A-Za-z0-9_:\-]+$", k)


@app.route("/api/draft/save", methods=["POST"])
@login_required
def api_draft_save():
    """書きかけを退避する。"""
    try:
        data = request.get_json(silent=True) or {}
        key = (data.get("form_key") or "").strip()
        payload = data.get("payload")
        if not _draft_key_ok(key) or not isinstance(payload, dict):
            return jsonify({"status": "error", "message": "入力が正しくありません。"}), 400
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > _DRAFT_MAX_BYTES:
            # ★黙って切り詰めない。切り詰めた書きかけを戻すほうが混乱する。
            return jsonify({"status": "error", "code": "too_large",
                            "message": "書きかけが大きすぎるため退避できませんでした。"}), 413

        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("draft_autosaves").upsert({
            "facility_code": f_code, "staff_name": my_name, "form_key": key,
            "payload": payload, "device_token": session.get("login_device_token"),
            "updated_at": now,
        }, on_conflict="facility_code,staff_name,form_key").execute()

        # 古い退避を捨てる。★失敗しても保存は成功として扱う（掃除はおまけ）。
        try:
            old = (datetime.now(timezone.utc) - timedelta(days=_DRAFT_KEEP_DAYS)).isoformat()
            (supabase.table("draft_autosaves").delete()
             .eq("facility_code", f_code).lt("updated_at", old).execute())
        except Exception as e:
            print("[draft] 古い退避の掃除に失敗: %s" % e, flush=True)

        return jsonify({"status": "success"})
    except Exception as e:
        print("api_draft_save error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": "退避できませんでした。"}), 503


@app.route("/api/draft/get", methods=["GET"])
@login_required
def api_draft_get():
    """自分の書きかけを1件返す。★必ず staff_name で絞る。"""
    try:
        key = (request.args.get("form_key") or "").strip()
        if not _draft_key_ok(key):
            return jsonify({"status": "error", "message": "入力が正しくありません。"}), 400
        supabase = get_supabase()
        res = (supabase.table("draft_autosaves").select("payload,updated_at")
               .eq("facility_code", session["f_code"])
               .eq("staff_name", session.get("my_name", ""))   # ★他人のものは返さない
               .eq("form_key", key).limit(1).execute())
        rows = res.data or []
        if not rows:
            return jsonify({"status": "success", "found": False})
        return jsonify({"status": "success", "found": True,
                        "payload": rows[0].get("payload") or {},
                        "updated_at": rows[0].get("updated_at")})
    except Exception as e:
        # ★「無い」と答えない。読めなかったのか、無いのかを分ける。
        #   「無い」と答えると、書きかけが在るのに黙って捨てたように見える。
        print("api_draft_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": "いま確認できませんでした。"}), 503


@app.route("/api/draft/clear", methods=["POST"])
@login_required
def api_draft_clear():
    """書きかけを消す（戻したあと・保存し終えたあと）。"""
    try:
        data = request.get_json(silent=True) or {}
        key = (data.get("form_key") or "").strip()
        if not _draft_key_ok(key):
            return jsonify({"status": "error", "message": "入力が正しくありません。"}), 400
        supabase = get_supabase()
        (supabase.table("draft_autosaves").delete()
         .eq("facility_code", session["f_code"])
         .eq("staff_name", session.get("my_name", ""))
         .eq("form_key", key).execute())
        return jsonify({"status": "success"})
    except Exception as e:
        print("api_draft_clear error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": "消せませんでした。"}), 503
# ===== /idle-logout-v1 =====


