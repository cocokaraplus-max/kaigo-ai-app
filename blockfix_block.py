# ===== staff-block-enforce-v1 : ブロックと退職を、実際にログインに効かせる =====
#   （HIROさん 2026-08-30「職員の退職でブロック設定したけど入れる」）
#
#   ★何が起きていたか
#     管理画面の「ブロック」は blocked_devices に行を足すだけで、
#     ログインの処理はその表を【一度も見ていなかった】。
#     ブロック一覧には出るのに、普通にログインできる状態だった。
#     ★「設定した」と見えるのに効いていない。いちばん危ない形の不具合。
#
#   ★もう1つの穴
#     職員を止めても（is_active=false）、【すでに入っている端末はそのまま使える】。
#     セッションは30日もつ設定で、職員の状態は入るときにしか見ていなかった。
#     退職者が自分のスマホでログインしたままなら、最大30日使えてしまう。
#
#   ★直し方は2つ
#     ① 入るとき  … ブロックされている人は、パスワードが合っていても入れない
#     ② 入ったあと … 数分おきに「まだ使ってよい人か」を確かめ、駄目なら降ろす
#
#   ★②の間隔は5分。毎回DBに聞くと全リクエストで問い合わせが増える。
#     5分は「退職者が最大5分だけ使える」ということでもある。
#     即座に切りたいときは、その人のセッションが切れるまで待つのではなく、
#     ①で入り直せなくしたうえで、5分待てばよい。
#
#   ★確かめられなかったときは【降ろさない】。
#     通信が一瞬詰まっただけで全職員が蹴られるほうが、現場では害が大きい。
#     ただし控えの時刻を更新しないので、次のリクエストでまた確かめる。

_STAFF_CHECK_INTERVAL_SEC = 300      # 5分に1回だけ確かめる
_STAFF_CHECK_SKIP_PREFIX = (
    "/static/", "/login", "/logout", "/shared-login", "/api/shared-login/",
    "/login/approve", "/api/session/touch", "/api/session/state",
    "/favicon", "/healthz", "/setup", "/reset_password", "/new_password",
)


def staff_is_blocked(supabase, f_code, staff_name):
    """この職員はブロックされているか。返り値は (ブロック中か, 確かめられたか)。

    ★「無かった」と「聞けなかった」を分ける。
      聞けなかったのを「ブロックされていない」と読むと、
      通信が詰まった隙にブロック中の人が入れてしまう。
    """
    if not staff_name:
        return False, True
    try:
        res = (supabase.table("blocked_devices").select("id")
               .eq("facility_code", f_code).eq("staff_name", staff_name)
               .eq("is_active", True).limit(1).execute())
        return bool(res.data or []), True
    except Exception as e:
        print("[staff-block] ブロックの確認に失敗: %s" % e, flush=True)
        return False, False


def staff_can_use(supabase, f_code, staff_name):
    """いまもTASUKARUを使ってよい人か。返り値は (使ってよいか, 確かめられたか)。

    使ってよい ＝ 職員として生きている（is_active）かつ ブロックされていない。
    """
    try:
        res = (supabase.table("staffs").select("is_active")
               .eq("facility_code", f_code).eq("staff_name", staff_name)
               .limit(1).execute())
        rows = res.data or []
    except Exception as e:
        print("[staff-block] 職員の確認に失敗: %s" % e, flush=True)
        return True, False        # ★確かめられない。降ろさない（控えも更新しない）
    if not rows:
        return False, True        # 職員として居ない＝使わせない
    if not rows[0].get("is_active"):
        return False, True
    blocked, checked = staff_is_blocked(supabase, f_code, staff_name)
    if not checked:
        return True, False
    return (not blocked), True


@app.before_request
def _staff_block_guard():   # staff-block-enforce-v1
    """入ったあとも、数分おきに「まだ使ってよい人か」を確かめる。

    ★これが無いと、退職者を止めてもセッションが切れるまで（最大30日）使えてしまう。
    """
    try:
        f_code = session.get("f_code")
        my_name = session.get("my_name")
        if not f_code or not my_name:
            return None
        path = request.path or ""
        for p in _STAFF_CHECK_SKIP_PREFIX:
            if path.startswith(p):
                return None

        import time as _sb_time
        now = int(_sb_time.time())
        last = session.get("staff_checked_at")
        if isinstance(last, int) and now - last < _STAFF_CHECK_INTERVAL_SEC:
            return None

        ok, checked = staff_can_use(get_supabase(), f_code, my_name)
        if not checked:
            # ★確かめられなかった。降ろさないが、控えも更新しない。
            #   次のリクエストでまた確かめる。
            return None
        session["staff_checked_at"] = now
        if ok:
            return None

        print("[staff-block] %s / %s は使えないため降ろしました" % (f_code, my_name), flush=True)
        session.clear()
        if request.args.get("partial") or path.startswith("/api/"):
            return jsonify({"status": "error", "code": "staff_blocked",
                            "message": "このアカウントは使えなくなっています。"
                                       "施設の管理者にお問い合わせください。",
                            "redirect": "/login"}), 401
        return redirect("/login")
    except Exception as e:
        # ★ここで落ちてもアプリを止めない。
        print("[staff-block] 判定に失敗: %s" % e, flush=True)
        return None
# ===== /staff-block-enforce-v1 =====


