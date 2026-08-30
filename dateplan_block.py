# ===== soge-date-plan-v1 : この日だけの配車 =====
#   （HIROさん 2026-08-30
#     「配車は日にち毎に設定することもできるようにしよう。
#       この日だけはこの配車でいこう、とできるようにしたい」
#      「現在の曜日での配車はデフォルトに、日付で決めた配車を運行画面では優先する」）
#
#   ★決まりは1つだけ。
#       その日の宣言（soge_date_plans）があれば   → その日の配車を使う
#       無ければ                                  → 曜日の配車を使う（これまでどおり）
#     日付が勝つ。曜日は既定値。
#
#   ★「行が無い」と「決めていない」を分ける。
#     中身の表だけを見て「行が0なら独自の配車は無い」と読むと、
#     たとえば祝日で全員休みの日に組んだ配車が【無かったこと】になり、
#     いつもの曜日の配車で走ってしまう。だから宣言の表を別に持つ。
#
#   ★当日データの作り直しは【もともとある仕組み】に任せる。
#     soge_materialize_day は、運行画面を開くたびに
#       確定済み → 作り直さない ／ 過ぎた日 → 作り直さない
#       打刻が始まっている → 作り直さない ／ それ以外 → 作り直す
#     と決めている。これはHIROさんの希望（打刻が無ければ作り直す、
#     始まっていたら止める）とちょうど同じなので、新しい規則は足さない。
#     ★同じ判断を2か所に書くと、片方だけ直したときに食い違う。

_SOGE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _soge_date_ok(v):  # soge-date-plan-v1
    """画面から来た日付を確かめて返す。おかしければ None。

    ★形だけでなく、実在する日かどうかも見る（2026-02-30 を弾く）。
    """
    s = str(v or "").strip()
    if not _SOGE_DATE_RE.match(s):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def _soge_date_weekday(date_str):  # soge-date-plan-v1
    """日付から、このアプリの曜日番号を出す（0=日 … 6=土）。"""
    y, m, d = [int(x) for x in date_str.split("-")]
    return (datetime(y, m, d).weekday() + 1) % 7


def _soge_plan_rows(trips, base, my_name, now_iso):  # soge-date-plan-v1
    """画面から来た配車を、表に入れる形に整える。

    base には表ごとの違いを入れて渡す。
        曜日の配車      … {"facility_code": ..., "weekday": 1}
        この日だけの配車 … {"facility_code": ..., "service_date": "2026-09-01"}

    ★曜日の保存とこの日だけの保存で、【同じ規則】を使うために切り出した。
      別々に書くと、片方だけ直したときに食い違う。
      （実際、車番の付け直しのような細かい規則を2か所で正しく保つのは無理）
    """
    rows = []
    for trip in (trips or []):
        tkey = (trip.get("trip_key") or "").strip()
        if not tkey:
            continue
        for v in (trip.get("vehicles") or []):
            stops = []
            for s in (v.get("stops") or []):
                pid = str(s.get("patient_id") or "").strip()
                stype = (s.get("type") or "").strip()
                if not pid or stype not in ("pickup", "dropoff"):
                    continue
                row = {"patient_id": pid, "type": stype, "nth": int(s.get("nth") or 0)}
                # soge-guest-v1: 登録の無い方（見学など）は名前も一緒に残す。
                # 利用者マスタには書き込まない。送迎の中だけで完結させる。
                if s.get("guest"):
                    row["guest"] = True
                    row["name"] = (s.get("user_name") or "").strip()[:40]
                stops.append(row)
            # soge-unassigned-v1: 0（まだ車が決まっていない人）と -1（送迎なし）を
            #   1号車に潰さないこと。"or 1" は 0 も偽と見なすので必ず化ける。
            _vno = v.get("vehicle_no")
            try:
                _vno = int(_vno) if _vno is not None else 1
            except (TypeError, ValueError):
                _vno = 1
            # 空の特別枠は残さない（次に開いたとき空箱だけ出るのを防ぐ）
            if _vno <= 0 and not stops:
                continue
            r = dict(base)
            r.update({
                "trip_key": tkey,
                "vehicle_no": _vno,
                "vehicle_id": (str(v["vehicle_id"]) if v.get("vehicle_id") else None),
                "driver_name": (v.get("driver_name") or "").strip() or None,
                "stop_order": stops,
                "updated_at": now_iso,
                "updated_by": my_name,
            })
            rows.append(r)

    # soge-unassigned-v1: (施設,曜日or日付,便,vehicle_no) が一意。
    #   ★先に delete しているので、insert が一意制約で落ちると
    #     【その配車表がまるごと消えたまま何も入らない】。
    #     画面側の番号付けを直したうえで、ここでも念のため付け直す。
    #     特別枠(0/-1)は番号そのものが意味なので触らない。
    seen_no = {}
    for r in rows:
        k = (r["trip_key"], r["vehicle_no"])
        if r["vehicle_no"] <= 0:
            continue
        if k in seen_no:
            nxt = max(x["vehicle_no"] for x in rows if x["trip_key"] == r["trip_key"]) + 1
            print("[soge] 車番の重複を付け直しました %s: %s -> %s"
                  % (r["trip_key"], r["vehicle_no"], nxt), flush=True)
            r["vehicle_no"] = nxt
        seen_no[(r["trip_key"], r["vehicle_no"])] = True
    return rows


def _soge_date_plan_row(supabase, f_code, date_str):  # soge-date-plan-v1
    """その日の宣言を1行返す。返り値は (行 または None, 確かめられたか)。

    ★「無かった」と「聞けなかった」を分ける。
      聞けなかったのを「無い」と読むと、通信が詰まった日だけ
      いつもの曜日の配車で走ってしまう。それは黙って起きる事故になる。
    """
    try:
        r = (supabase.table("soge_date_plans").select("*")
             .eq("facility_code", f_code).eq("service_date", date_str)
             .limit(1).execute())
        rows = r.data or []
        return (rows[0] if rows else None), True
    except Exception as e:
        print("[soge] その日の配車の確認に失敗: %s" % e, flush=True)
        return None, False


def _soge_saved_date(supabase, f_code, date_str, settings):  # soge-date-plan-v1
    """その日だけの配車を、画面用の形にして返す。宣言が無ければ None。"""
    plan, checked = _soge_date_plan_row(supabase, f_code, date_str)
    if not checked or not plan:
        return None
    try:
        r = (supabase.table("soge_date_routes").select("*")
             .eq("facility_code", f_code).eq("service_date", date_str).execute())
        rows = r.data or []
    except Exception as e:
        print("[soge] その日の配車の取得に失敗: %s" % e, flush=True)
        return None
    out = _soge_rows_view(supabase, f_code, _soge_date_weekday(date_str), settings, rows)
    if out is not None:
        out["date"] = date_str
        out["has_plan"] = True
        out["plan_source"] = plan.get("source") or "weekday"
        out["plan_note"] = plan.get("note") or ""
    return out


def _soge_date_day_info(supabase, f_code, date_str):  # soge-date-plan-v1
    """その日の運行表の状態を、画面に伝える形でまとめる。"""
    st = _soge_day_state(supabase, f_code, date_str)
    return {"exists": st["exists"], "touched": st["touched"],
            "locked": st["locked"], "past": st["past"]}


def _soge_date_rebuild(supabase, f_code, date_str):  # soge-date-plan-v1
    """保存や取り消しのあと、当日の運行表を作り直せるなら作り直す。

    ★まだ当日データが無い日は【何もしない】。
      運行画面を開いたときに作られるので、ここで先に作る必要が無い。
      先に作ると、まだ誰も見ていない日の運行表が増えるだけ。
    """
    st = _soge_day_state(supabase, f_code, date_str)
    if not st["exists"]:
        return {"built": False, "reason": "not_yet"}
    return soge_materialize_day(supabase, f_code, date_str)


_SOGE_REBUILD_SAY = {
    "not_yet": "",     # まだ当日の表が無い。運行画面を開いたときに作られる
    "touched": "ただし、この日はもう打刻が始まっているので、"
               "当日の運行表は作り直していません。",
    "locked": "ただし、この日は確定済みなので、当日の運行表は作り直していません。",
    "past": "ただし、過ぎた日なので、当日の運行表は作り直していません。",
    "clear_failed": "ただし、当日の運行表を作り直せませんでした。",
    "no_week": "ただし、元になる配車が見つからず、当日の運行表は作り直していません。",
}


@app.route("/api/soge/date", methods=["GET"])  # soge-date-plan-v1
@login_required
def api_soge_date_get():
    """その日の配車。宣言があればその日のもの、無ければ曜日のものを下地に返す。

    ★宣言が無いときに【曜日の配車をそのまま返す】のが「コピーが下地」の正体。
      画面はそれを直して保存するだけでよく、コピー専用の処理が要らない。
    """
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        date_str = _soge_date_ok(request.args.get("date"))
        if not date_str:
            return jsonify({"status": "error", "message": "日付が正しくありません。"}), 400

        settings = get_soge_settings(supabase, f_code)
        weekday = _soge_date_weekday(date_str)

        plan, checked = _soge_date_plan_row(supabase, f_code, date_str)
        if not checked:
            return jsonify({"status": "error",
                            "message": "いま確認できませんでした。"
                                       "少し時間をおいて、もう一度お試しください。"}), 503

        if plan:
            out = _soge_saved_date(supabase, f_code, date_str, settings)
            if out is None:
                return jsonify({"status": "error",
                                "message": "いま確認できませんでした。"
                                           "少し時間をおいて、もう一度お試しください。"}), 503
        else:
            out = _soge_saved_week(supabase, f_code, weekday, settings)
            if not out:
                out = soge_build_week(supabase, f_code, weekday, settings)
            out["has_plan"] = False
            out["plan_source"] = "weekday"
            out["plan_note"] = ""
            out["saved"] = False

        out["status"] = "success"
        out["date"] = date_str
        out["weekday"] = weekday
        out["day"] = _soge_date_day_info(supabase, f_code, date_str)
        return jsonify(out)
    except Exception as e:
        print("api_soge_date_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/soge/date", methods=["PUT"])  # soge-date-plan-v1
@login_required
def api_soge_date_save():
    """この日だけの配車を保存する。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        data = request.json or {}
        date_str = _soge_date_ok(data.get("date"))
        if not date_str:
            return jsonify({"status": "error", "message": "日付が正しくありません。"}), 400

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = _soge_plan_rows(data.get("trips") or [],
                               {"facility_code": f_code, "service_date": date_str},
                               my_name, now_iso)

        # ★宣言を【先に】立てる。
        #   中身だけ入って宣言が無い状態でここが落ちると、
        #   その日は「独自の配車は無い」と見なされ、曜日の配車で走ってしまう。
        #   逆に宣言だけ立って中身が空でも、「全員送迎なしの日」として正しく動く。
        head = {
            "facility_code": f_code,
            "service_date": date_str,
            "source": ("auto" if (data.get("source") == "auto") else "weekday"),
            "note": (str(data.get("note") or "").strip()[:200] or None),
            "updated_at": now_iso,
            "updated_by": my_name,
        }
        plan, checked = _soge_date_plan_row(supabase, f_code, date_str)
        if not checked:
            return jsonify({"status": "error",
                            "message": "いま確認できませんでした。"
                                       "少し時間をおいて、もう一度お試しください。"}), 503
        try:
            if plan:
                (supabase.table("soge_date_plans").update(head)
                 .eq("facility_code", f_code).eq("service_date", date_str).execute())
            else:
                supabase.table("soge_date_plans").insert(head).execute()
        except Exception as e:
            print("[soge] その日の配車の宣言に失敗: %s" % e, flush=True)
            return jsonify({"status": "error",
                            "message": "保存できませんでした。もう一度お試しください。"}), 500

        try:
            (supabase.table("soge_date_routes").delete()
             .eq("facility_code", f_code).eq("service_date", date_str).execute())
            if rows:
                supabase.table("soge_date_routes").insert(rows).execute()
        except Exception as e:
            print("[soge] その日の配車の保存に失敗: %s" % e, flush=True)
            return jsonify({"status": "error",
                            "message": "保存できませんでした。もう一度お試しください。"}), 500

        res = _soge_date_rebuild(supabase, f_code, date_str)
        say = "" if res.get("built") else _SOGE_REBUILD_SAY.get(res.get("reason") or "", "")
        return jsonify({"status": "success", "saved": len(rows),
                        "rebuilt": bool(res.get("built")),
                        "reason": res.get("reason") or "",
                        "message": ("この日だけの配車を保存しました。" + (" " + say if say else "")).strip(),
                        "day": _soge_date_day_info(supabase, f_code, date_str)})
    except Exception as e:
        print("api_soge_date_save error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/soge/date", methods=["DELETE"])  # soge-date-plan-v1
@login_required
def api_soge_date_delete():
    """この日だけの配車をやめて、いつもの曜日の配車に戻す。"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        date_str = _soge_date_ok(request.args.get("date"))
        if not date_str:
            return jsonify({"status": "error", "message": "日付が正しくありません。"}), 400

        # ★中身を先に消し、宣言を後に消す。
        #   逆にすると、宣言だけ消えて中身が残った状態で落ちたとき、
        #   使われない行が残り続ける（動きは正しいが、後で見て分からなくなる）。
        try:
            (supabase.table("soge_date_routes").delete()
             .eq("facility_code", f_code).eq("service_date", date_str).execute())
            (supabase.table("soge_date_plans").delete()
             .eq("facility_code", f_code).eq("service_date", date_str).execute())
        except Exception as e:
            print("[soge] その日の配車の取り消しに失敗: %s" % e, flush=True)
            return jsonify({"status": "error",
                            "message": "取り消せませんでした。もう一度お試しください。"}), 500

        res = _soge_date_rebuild(supabase, f_code, date_str)
        say = "" if res.get("built") else _SOGE_REBUILD_SAY.get(res.get("reason") or "", "")
        return jsonify({"status": "success",
                        "rebuilt": bool(res.get("built")),
                        "reason": res.get("reason") or "",
                        "message": ("いつもの曜日の配車に戻しました。" + (" " + say if say else "")).strip(),
                        "day": _soge_date_day_info(supabase, f_code, date_str)})
    except Exception as e:
        print("api_soge_date_delete error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500
# ===== /soge-date-plan-v1 =====


