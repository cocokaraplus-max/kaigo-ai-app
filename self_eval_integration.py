"""
TASUKARU 利用者セルフ評価（タブレット） self-eval-v1

利用者本人がタブレットで、目標の達成度（0〜10）と理由を答える機能。
設計の全体像は README.md の self-eval-design-2026-08-20 を読むこと。

DDL: db/self_eval.sql（デプロイより先に DEV→本番 の順で適用）

★★ この機能で一番重要なのは「利用者モード（キオスク）」 ★★
  利用者にタブレットを渡している間、他の画面へ行けないようにする。
  画面を隠すだけでは防げない。アドレスバーに /board と打たれたら素通りする。
  そのため _kiosk_guard() で【すべてのリクエストの入口】を止めている。
  ここを外すと、他の利用者のケース記録・掲示板に到達される。絶対に消さないこと。

提供API（職員側）:
  GET  /self-eval                      - 職員の画面（一覧・作成）
  GET  /api/self-eval/list             - 一覧（status で絞れる。確認待ち件数もここ）
  POST /api/self-eval/create           - 利用者を選んで新規作成＋AIで質問を生成
  GET  /api/self-eval/get              - 1件取得（質問と回答）
  POST /api/self-eval/questions/save   - 質問の追加・修正・削除（★途中保存）
  POST /api/self-eval/start            - 利用者モードに入る（キオスクON）
  POST /api/self-eval/kiosk-pin/set    - 解除コード（4桁）の設定（管理者のみ）
  GET  /api/self-eval/kiosk-pin/status - 解除コードが設定済みかだけ返す

提供API（利用者側・キオスク中のみ）:
  GET  /self-eval/run                  - 回答画面
  GET  /self-eval/locked               - ロック画面
  POST /api/self-eval/answer           - 1問ぶんの回答を保存（★1問ごと自動保存）
  POST /api/self-eval/finish           - 回答完了 → status='answered' → ロック
  POST /api/self-eval/unlock           - 4桁で利用者モードを解除
"""
from flask import request, jsonify, session, redirect, url_for, render_template
from functools import wraps
from datetime import datetime, timezone
import hashlib
import json as _json
import re
import time


# セッションに入れるキー（利用者モードの印）
_K_EVAL = "kiosk_eval_id"      # 回答中の評価id
_K_PID  = "kiosk_pid"          # 対象の利用者
_K_NAME = "kiosk_user_name"    # 表示用
_K_LOCK = "kiosk_locked"       # 回答が終わってロック画面で止まっている

# 利用者モード中に通してよいパス。これ以外は全部止める。
# ★【完全一致】で持つこと。前方一致にすると /self-eval（職員の一覧＝利用者名が並ぶ画面）や
#   /api/self-eval/kiosk-pin/set（解除コードの再設定）まで通ってしまう。
#   ここを緩めると、利用者に渡したタブレットから他の利用者の氏名が見える。
_KIOSK_ALLOW_EXACT = (
    "/self-eval/run",              # 回答画面
    "/self-eval/locked",           # ロック画面
    "/api/self-eval/questions",    # 自分の質問を読む
    "/api/self-eval/answer",       # 1問ぶん保存
    "/api/self-eval/finish",       # 回答完了
    "/api/self-eval/unlock",       # 職員が解除する
)
# 見た目の部品だけは通す（CSS・画像・フォント）
_KIOSK_ALLOW_PREFIX = ("/static/",)

# 解除コードの総当たり対策（プロセス内で数える。厳密でなくてよい）
_pin_fail = {}     # facility_code -> [失敗回数, 最後に失敗した時刻]
_PIN_MAX_FAIL = 10
_PIN_COOLDOWN = 60  # 秒


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _pin_hash(f_code, pin):
    """★平文で保存しない。施設コードを混ぜてsha256。"""
    return hashlib.sha256((str(f_code) + ":" + str(pin)).encode("utf-8")).hexdigest()


def _clean_goal(v):
    """目標欄の値を掃除する。
    ★実データには文字列の "None" が入っていることがある（DEVで53人中4人）。
      そのまま渡すと『None　これはできるようになりましたか』という質問が作られてしまう。"""
    v = (v or "").strip()
    if v.lower() in ("none", "null", "nan", "undefined", "-", "―", "なし", "特になし", "無し"):
        return ""
    return v


def _zone_label(z):
    return {
        "body": "心身機能", "activity": "活動", "participation": "参加",
        "environment": "環境", "personal": "個人因子",
    }.get(z or "", "")


def register_self_eval_routes(app):
    """Flaskアプリに利用者セルフ評価のルートを登録。"""

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("f_code") or not session.get("my_name"):
                if request.args.get("partial"):
                    return jsonify({"redirect": "/login"})
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    def _admin_only():
        from app import get_supabase, is_admin_user
        supabase = get_supabase()
        f_code = session.get("f_code")
        me = session.get("my_name", "")
        try:
            return bool(is_admin_user(supabase, f_code, me))
        except Exception:
            return False

    # ==========================================================
    # ★★ 利用者モード（キオスク）のガード ★★
    #   これがこの機能の要。画面を隠すだけの対策では、URLを直打ちされて素通りする。
    #   ここで【すべてのリクエスト】を見て、評価に関係ないものは全部止める。
    #   ・APIなら403
    #   ・画面ならロック画面へ戻す
    #   別タブでTASUKARUを開いても同じセッションなので、同じように止まる。
    # ==========================================================
    @app.before_request
    def _kiosk_guard():                                   # self-eval-v1
        if not session.get(_K_EVAL):
            return None                                    # 利用者モードでなければ何もしない
        p = (request.path or "").rstrip("/") or "/"
        if p in _KIOSK_ALLOW_EXACT or p.startswith(_KIOSK_ALLOW_PREFIX):
            return None
        if p.startswith("/api/"):
            return jsonify({"status": "error",
                            "message": "利用者モード中です。職員が解除してください。"}), 403
        return redirect("/self-eval/locked")

    # ==========================================================
    # 職員側
    # ==========================================================
    @app.route('/self-eval')
    @login_required
    def self_eval_page():
        return render_template('self_eval.html')

    @app.route('/api/self-eval/list', methods=['GET'])
    @login_required
    def api_self_eval_list():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        st = (request.args.get("status") or "").strip()
        try:
            q = (supabase.table("patient_self_evaluations").select("*")
                 .eq("facility_code", f_code))
            if st:
                q = q.eq("status", st)
            r = q.order("started_at", desc=True).limit(200).execute()
            rows = r.data or []
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        # 「確認待ち」の件数は現場に必ず見せる（放置されないように）
        waiting = len([x for x in rows if x.get("status") == "answered"]) if not st else None
        if st == "answered":
            waiting = len(rows)
        return jsonify({"status": "success", "items": rows, "waiting": waiting})

    @app.route('/api/self-eval/get', methods=['GET'])
    @login_required
    def api_self_eval_get():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        eid = (request.args.get("id") or "").strip()
        if not eid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        try:
            e = (supabase.table("patient_self_evaluations").select("*")
                 .eq("facility_code", f_code).eq("id", eid).execute())
            if not e.data:
                return jsonify({"status": "error", "message": "見つかりません"}), 404
            a = (supabase.table("patient_self_eval_answers").select("*")
                 .eq("facility_code", f_code).eq("evaluation_id", eid)
                 .order("seq").execute())
        except Exception as ex:
            return jsonify({"status": "error", "message": str(ex)}), 500
        return jsonify({"status": "success", "eval": e.data[0], "answers": a.data or []})

    # ---------- 材料あつめ ----------
    def _gather_material(supabase, f_code, pid):
        """質問生成の材料。README self-eval-design-2026-08-20 の「4.」の順で集める。"""
        out = {"goals": {}, "can": [], "cannot": [], "env": [], "zones": set(),
               "hobbies": "", "likes": "", "job": "", "medical": [], "personality": ""}
        try:
            pp = (supabase.table("patient_profiles").select(
                "user_name, short_goal, long_goal, "
                "short_goal_function, short_goal_activity, short_goal_participation, "
                "long_goal_function, long_goal_activity, long_goal_participation, "
                "hobbies, likes, job_history"
            ).eq("facility_code", f_code).eq("id", pid).execute())
            row = (pp.data or [{}])[0]
        except Exception:
            row = {}
        for k in ("short_goal", "long_goal",
                  "short_goal_function", "short_goal_activity", "short_goal_participation",
                  "long_goal_function", "long_goal_activity", "long_goal_participation"):
            v = _clean_goal(row.get(k))       # "None" などは空として扱う
            if v:
                out["goals"][k] = v
        out["hobbies"] = _clean_goal(row.get("hobbies"))
        out["likes"] = _clean_goal(row.get("likes"))
        out["job"] = _clean_goal(row.get("job_history"))
        out["user_name"] = (row.get("user_name") or "").strip()

        try:
            st = (supabase.table("patient_icf_stickies").select("zone,text,polarity")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute())
            for s in (st.data or []):
                z = s.get("zone") or "unsorted"
                t = (s.get("text") or "").strip()
                if not t:
                    continue
                out["zones"].add(z)
                item = {"zone": z, "text": t}
                if s.get("polarity") == "cannot":
                    out["cannot"].append(item)
                else:
                    out["can"].append(item)
                if z == "environment":
                    out["env"].append(item)
        except Exception:
            pass

        try:
            me = (supabase.table("patient_medical_events")
                  .select("event_ym,label").eq("facility_code", f_code)
                  .eq("patient_profile_id", str(pid)).eq("status", "approved").execute())
            rows = sorted((me.data or []), key=lambda x: (x.get("event_ym") or ""), reverse=True)
            out["medical"] = [((r.get("event_ym") or "") + " " + (r.get("label") or "")).strip()
                              for r in rows[:5]]
        except Exception:
            pass

        try:
            pc = (supabase.table("patient_personality_cache").select("summary")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute())
            out["personality"] = ((pc.data or [{}])[0].get("summary") or "")[:300]
        except Exception:
            pass
        return out

    def _build_prompt(m):
        L = []
        L.append("あなたは介護施設の相談員です。利用者【本人】がタブレットで答えるための質問を作ります。")
        L.append("")
        L.append("【目標】")
        for k, v in (m.get("goals") or {}).items():
            L.append(f"- {k}: {v}")
        if not m.get("goals"):
            L.append("- （登録なし）")
        if m.get("cannot"):
            L.append("")
            L.append("【できないこと・支障】※ここを掘る")
            for x in m["cannot"][:12]:
                L.append(f"- [{_zone_label(x['zone'])}] {x['text']}")
        if m.get("can"):
            L.append("")
            L.append("【できること】※前提を間違えないために使う。できない前提で聞かないこと")
            for x in m["can"][:12]:
                L.append(f"- [{_zone_label(x['zone'])}] {x['text']}")
        if m.get("hobbies") or m.get("likes") or m.get("job"):
            L.append("")
            L.append("【趣味・好きなもの・職歴】※「参加」の質問に使う")
            for v in (m.get("hobbies"), m.get("likes"), m.get("job")):
                if v:
                    L.append("- " + v[:120])
        if m.get("medical"):
            L.append("")
            L.append("【最近の出来事】")
            for v in m["medical"]:
                L.append("- " + v)
        if m.get("personality"):
            L.append("")
            L.append("【人となり】※言い回しの調整に使う。質問文に事実として書かない")
            L.append("- " + m["personality"])

        missing = [z for z in ("body", "activity", "participation") if z not in (m.get("zones") or set())]
        if missing:
            L.append("")
            L.append("【注意】次の領域の情報が不足しています。1問ずつ補う質問を入れてください: "
                     + " / ".join(_zone_label(z) for z in missing))

        L.append("")
        L.append("【作り方の決まり】")
        L.append("- 利用者本人が読んで答えます。高齢の方が多いので、やさしく短い日本語で。")
        L.append("- 1問1事実。二重否定を使わない。専門用語（ADL・IADL・移乗・見守り等）を使わない。")
        L.append("- 敬語で「〜できましたか」「〜になりましたか」。責める言い方にしない。")
        L.append("- できることは前提にして聞く（例：歩行器が使えるなら『歩行器を使って〜できましたか』）。")
        L.append("- 6問以上8問以下。多いと途中でやめてしまいます。")
        L.append("- source_note には、どの材料から作ったかを職員向けに短く書く（利用者には見せません）。")
        # ここから下は 2026-08-20 にDEVで実際に生成させて見つかった不具合への対策。消さないこと。
        L.append("")
        L.append("【必ず守ること（守らないと画面で答えられません）】")
        L.append("★1. 回答は【0〜10の達成度】を選ぶ形式です。")
        L.append("     『どのくらいできたか』を答えられる質問だけにしてください。")
        L.append("     「〜してみたいですか」「〜したいと思いますか」のような")
        L.append("     【希望・意向をたずねる質問は禁止】です。達成度で答えられません。")
        L.append("     悪い例：『歩行器を使わずに歩いてみたいですか』")
        L.append("     良い例：『歩行器を使って、廊下を歩けましたか』")
        L.append("★2. ふりかえる期間は【この1か月】に統一してください。")
        L.append("     「今日」「昨日」「今週」など短い期間を指す言葉は使わないでください。")
        L.append("     悪い例：『今日、他の方とお話しできましたか』")
        L.append("     良い例：『この1か月で、他の方とお話しする機会はありましたか』")
        L.append("")
        L.append("次のJSONだけを返してください（説明文は禁止）:")
        L.append('{"questions":[{"question":"歩行器を使って、トイレまで行けましたか",'
                 '"goal_kind":"short","icf_zone":"activity","source_note":"短期目標＋can:歩行器で50m歩行"}]}')
        return "\n".join(L)

    @app.route('/api/self-eval/create', methods=['POST'])
    @login_required
    def api_self_eval_create():
        """利用者を選んで新規作成し、AIで質問のたたき台を作る。
        ★ここで作った質問は必ず職員が確認してから利用者に見せること（そのまま出さない）。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        me = session.get("my_name", "")
        data = request.json or {}
        pid = str(data.get("pid") or "").strip()
        target_ym = (data.get("target_ym") or "").strip() or datetime.now().strftime("%Y-%m")
        if not pid:
            return jsonify({"status": "error", "message": "利用者を選んでください"}), 400

        m = _gather_material(supabase, f_code, pid)
        if not m.get("goals"):
            return jsonify({"status": "error",
                            "message": "この方には目標が登録されていません。先に利用者情報で目標を入れてください。"}), 400

        qs = []
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(_build_prompt(m))
            text = (resp.text or "").strip()
            mm = re.search(r'\{.*\}', text, re.DOTALL)
            qs = _json.loads(mm.group()).get("questions", []) if mm else []
        except Exception as e:
            print(f"[self-eval] AI生成失敗: {e}", flush=True)
            qs = []

        if not qs:
            # AIが落ちても作業が止まらないように、目標をそのまま質問にして返す
            for k, v in (m.get("goals") or {}).items():
                kind = "short" if k.startswith("short") else "long"
                qs.append({"question": f"この1か月で、{v}　これはできましたか",
                           "goal_kind": kind, "icf_zone": "", "source_note": "目標そのまま（AI生成に失敗）"})
            qs = qs[:8]

        try:
            ins = (supabase.table("patient_self_evaluations").insert({
                "facility_code": f_code, "patient_profile_id": pid,
                "user_name": m.get("user_name") or "", "target_ym": target_ym,
                "status": "draft", "started_by": me,
            }).execute())
            eid = ins.data[0]["id"]
        except Exception as e:
            return jsonify({"status": "error", "message": f"作成失敗: {e}"}), 500

        rows = []
        for i, q in enumerate(qs[:8]):
            t = (q.get("question") or "").strip()
            if not t:
                continue
            rows.append({
                "facility_code": f_code, "evaluation_id": eid, "seq": len(rows) + 1,
                "question": t[:300],
                "goal_kind": (q.get("goal_kind") or "")[:10],
                "icf_zone": (q.get("icf_zone") or "")[:20],
                "source_note": (q.get("source_note") or "")[:200],
            })
        if rows:
            try:
                supabase.table("patient_self_eval_answers").insert(rows).execute()
            except Exception as e:
                return jsonify({"status": "error", "message": f"質問の保存に失敗: {e}"}), 500
        return jsonify({"status": "success", "id": eid, "count": len(rows)})

    @app.route('/api/self-eval/questions/save', methods=['POST'])
    @login_required
    def api_self_eval_questions_save():
        """★途中保存。職員が質問を直したら、その都度これを呼ぶ。
        送られてきた並びで丸ごと置き換える（回答済みの内容は保持する）。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        eid = (data.get("id") or "").strip()
        qs = data.get("questions") or []
        if not eid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        try:
            cur = (supabase.table("patient_self_eval_answers").select("*")
                   .eq("facility_code", f_code).eq("evaluation_id", eid).execute())
            old = {str(r["id"]): r for r in (cur.data or [])}
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        keep, ins = [], []
        for i, q in enumerate(qs):
            t = (q.get("question") or "").strip()
            if not t:
                continue
            qid = str(q.get("id") or "")
            payload = {
                "seq": i + 1, "question": t[:300],
                "goal_kind": (q.get("goal_kind") or "")[:10],
                "icf_zone": (q.get("icf_zone") or "")[:20],
                "source_note": (q.get("source_note") or "")[:200],
                "updated_at": _now_iso(),
            }
            if qid and qid in old:
                keep.append(qid)
                try:
                    supabase.table("patient_self_eval_answers").update(payload).eq("id", qid).execute()
                except Exception:
                    pass
            else:
                p = dict(payload)
                p.update({"facility_code": f_code, "evaluation_id": eid})
                ins.append(p)
        if ins:
            try:
                supabase.table("patient_self_eval_answers").insert(ins).execute()
            except Exception as e:
                return jsonify({"status": "error", "message": f"追加失敗: {e}"}), 500
        # 画面から消された質問だけ削除（回答済みでも職員が消したなら消す）
        gone = [k for k in old.keys() if k not in keep]
        if gone:
            try:
                supabase.table("patient_self_eval_answers").delete().in_("id", gone).execute()
            except Exception:
                pass
        try:
            supabase.table("patient_self_evaluations").update(
                {"updated_at": _now_iso()}).eq("id", eid).eq("facility_code", f_code).execute()
        except Exception:
            pass
        return jsonify({"status": "success", "saved": len(qs)})

    # ---------- 解除コード ----------
    @app.route('/api/self-eval/kiosk-pin/status', methods=['GET'])
    @login_required
    def api_kiosk_pin_status():
        """設定済みかどうかだけ返す。★コードそのものは絶対に返さない。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        try:
            r = (supabase.table("facility_kiosk_pins").select("facility_code")
                 .eq("facility_code", f_code).execute())
            return jsonify({"status": "success", "configured": bool(r.data)})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/self-eval/kiosk-pin/set', methods=['POST'])
    @login_required
    def api_kiosk_pin_set():
        from app import get_supabase
        if not _admin_only():
            return jsonify({"status": "error", "message": "管理者のみ設定できます"}), 403
        supabase = get_supabase()
        f_code = session["f_code"]
        pin = str((request.json or {}).get("pin") or "").strip()
        if not re.fullmatch(r"\d{4}", pin):
            return jsonify({"status": "error", "message": "4桁の数字で入力してください"}), 400
        if pin in ("0000", "1234", "1111"):
            return jsonify({"status": "error", "message": "推測されやすい番号は使えません"}), 400
        try:
            supabase.table("facility_kiosk_pins").upsert({
                "facility_code": f_code, "pin_hash": _pin_hash(f_code, pin),
                "updated_by": session.get("my_name", ""), "updated_at": _now_iso(),
            }, on_conflict="facility_code").execute()
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success"})

    # ---------- 利用者モードの開始・解除 ----------
    @app.route('/api/self-eval/start', methods=['POST'])
    @login_required
    def api_self_eval_start():
        """★ここから利用者モード。以後 _kiosk_guard がすべてのリクエストを止める。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        eid = ((request.json or {}).get("id") or "").strip()
        if not eid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        try:
            pin = (supabase.table("facility_kiosk_pins").select("facility_code")
                   .eq("facility_code", f_code).execute())
            if not pin.data:
                return jsonify({"status": "error",
                                "message": "先に解除コード（4桁）を設定してください。設定しないとタブレットを渡せません。"}), 400
            e = (supabase.table("patient_self_evaluations").select("*")
                 .eq("facility_code", f_code).eq("id", eid).execute())
            if not e.data:
                return jsonify({"status": "error", "message": "見つかりません"}), 404
            row = e.data[0]
            if row.get("status") == "confirmed":
                return jsonify({"status": "error", "message": "この評価は確定済みです"}), 400
            cnt = (supabase.table("patient_self_eval_answers").select("id")
                   .eq("facility_code", f_code).eq("evaluation_id", eid).execute())
            if not (cnt.data or []):
                return jsonify({"status": "error", "message": "質問がありません"}), 400
        except Exception as ex:
            return jsonify({"status": "error", "message": str(ex)}), 500

        session[_K_EVAL] = eid
        session[_K_PID] = row.get("patient_profile_id")
        session[_K_NAME] = row.get("user_name") or ""
        session[_K_LOCK] = False
        return jsonify({"status": "success", "redirect": "/self-eval/run"})

    @app.route('/api/self-eval/unlock', methods=['POST'])
    def api_self_eval_unlock():
        """4桁で利用者モードを解除。★総当たり対策あり。"""
        from app import get_supabase
        if not session.get(_K_EVAL):
            return jsonify({"status": "success"})     # 既に解除済み
        f_code = session.get("f_code")
        pin = str((request.json or {}).get("pin") or "").strip()
        st = _pin_fail.get(f_code) or [0, 0.0]
        if st[0] >= _PIN_MAX_FAIL and (time.time() - st[1]) < _PIN_COOLDOWN:
            wait = int(_PIN_COOLDOWN - (time.time() - st[1])) + 1
            return jsonify({"status": "error",
                            "message": f"間違いが続いています。{wait}秒お待ちください。"}), 429
        supabase = get_supabase()
        try:
            r = (supabase.table("facility_kiosk_pins").select("pin_hash")
                 .eq("facility_code", f_code).execute())
            ok = bool(r.data) and r.data[0].get("pin_hash") == _pin_hash(f_code, pin)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        if not ok:
            _pin_fail[f_code] = [st[0] + 1, time.time()]
            return jsonify({"status": "error", "message": "番号が違います"}), 401
        _pin_fail[f_code] = [0, 0.0]
        eid = session.get(_K_EVAL)
        print(f"[self-eval] kiosk unlocked eval={eid} by={session.get('my_name','')}", flush=True)
        for k in (_K_EVAL, _K_PID, _K_NAME, _K_LOCK):
            session.pop(k, None)
        return jsonify({"status": "success", "redirect": "/self-eval"})

    # ==========================================================
    # 利用者側（キオスク中）
    # ==========================================================
    @app.route('/self-eval/run')
    def self_eval_run():
        if not session.get(_K_EVAL):
            return redirect("/self-eval")
        if session.get(_K_LOCK):
            return redirect("/self-eval/locked")
        return render_template('self_eval_run.html',
                               user_name=session.get(_K_NAME, ""),
                               eval_id=session.get(_K_EVAL, ""))

    @app.route('/self-eval/locked')
    def self_eval_locked():
        if not session.get(_K_EVAL):
            return redirect("/self-eval")
        return render_template('self_eval_locked.html',
                               user_name=session.get(_K_NAME, ""))

    @app.route('/api/self-eval/questions', methods=['GET'])
    def api_self_eval_questions():
        """利用者側が読む質問。★キオスク中のセッションの評価しか返さない。"""
        from app import get_supabase
        eid = session.get(_K_EVAL)
        if not eid:
            return jsonify({"status": "error", "message": "利用者モードではありません"}), 403
        supabase = get_supabase()
        f_code = session.get("f_code")
        try:
            a = (supabase.table("patient_self_eval_answers")
                 .select("id,seq,question,score,choice,reason_mode,reason_text")
                 .eq("facility_code", f_code).eq("evaluation_id", eid)
                 .order("seq").execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success", "user_name": session.get(_K_NAME, ""),
                        "questions": a.data or []})

    @app.route('/api/self-eval/answer', methods=['POST'])
    def api_self_eval_answer():
        """★1問ごとに呼ばれる自動保存。途中で電源が切れても回答は消えない。"""
        from app import get_supabase
        eid = session.get(_K_EVAL)
        if not eid:
            return jsonify({"status": "error", "message": "利用者モードではありません"}), 403
        supabase = get_supabase()
        f_code = session.get("f_code")
        d = request.json or {}
        qid = (d.get("id") or "").strip()
        if not qid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        score = d.get("score")
        try:
            score = int(score)
        except Exception:
            score = None
        if score is not None and not (0 <= score <= 10):
            score = None
        choice = d.get("choice") if d.get("choice") in ("no", "mid", "ok") else None
        mode = d.get("reason_mode") if d.get("reason_mode") in ("write", "voice", "skip") else None
        payload = {
            "score": score, "choice": choice, "reason_mode": mode,
            "reason_text": (d.get("reason_text") or "")[:2000] or None,
            "answered_at": _now_iso(), "updated_at": _now_iso(),
        }
        try:
            (supabase.table("patient_self_eval_answers").update(payload)
             .eq("id", qid).eq("facility_code", f_code).eq("evaluation_id", eid).execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success"})

    @app.route('/api/self-eval/finish', methods=['POST'])
    def api_self_eval_finish():
        """回答完了。status='answered'（＝職員の確認待ち）にしてロック画面へ。
        ★ここで確定しない。人の目を通すまでは未確定のままにする。"""
        from app import get_supabase
        eid = session.get(_K_EVAL)
        if not eid:
            return jsonify({"status": "error", "message": "利用者モードではありません"}), 403
        supabase = get_supabase()
        f_code = session.get("f_code")
        try:
            (supabase.table("patient_self_evaluations")
             .update({"status": "answered", "answered_at": _now_iso(), "updated_at": _now_iso()})
             .eq("id", eid).eq("facility_code", f_code).execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        session[_K_LOCK] = True
        return jsonify({"status": "success", "redirect": "/self-eval/locked"})
