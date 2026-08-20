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


# ===== self-eval-v1（第4段）: 目標とは別に、毎回かならず聞く質問 =====
#   既存の評価 patient_evaluations には、本来【ご本人にしか答えられない】欄がある。
#     satisfaction（満足度） / service_appropriateness（サービスの適切さ）
#     new_requests_exist（新たな要望の有無） / changes_by_training（訓練による変化）
#   これらは職員が推測で埋めがちなので、本人に直接聞いて評価の材料にする。
#   ★AIに作らせない。必ず入る必要があるのでサーバ側で固定して足す。
#   goal_kind でどの欄に対応するかを持つ:
#     'change'   … 訓練による変化
#     'satisfy'  … 満足度
#     'fit'      … サービスの適切さ
#     'free'     … 新たな要望（★達成度では答えられないので、自由記載だけの質問）
_COMMON_QUESTIONS = [
    {"question": "この1か月で、体を動かすのが 前より楽になりましたか",
     "goal_kind": "change", "icf_zone": "body",
     "source_note": "共通質問：評価の「訓練による変化」の材料"},
    {"question": "いまの デイサービスに 満足していますか",
     "goal_kind": "satisfy", "icf_zone": "",
     "source_note": "共通質問：評価の「満足度」に入ります"},
    {"question": "いまの サービスの内容は ご自身に合っていると思いますか",
     "goal_kind": "fit", "icf_zone": "",
     "source_note": "共通質問：評価の「サービスの適切さ」に入ります"},
    {"question": "これから してみたいことや、困っていることは ありますか",
     "goal_kind": "free", "icf_zone": "participation",
     "source_note": "共通質問：評価の「新たな要望」の材料。自由記載のみ"},
]


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

        # 目標由来の質問は6問までに抑え、そのあとに共通質問4問を必ず足す。
        # 合計10問。多すぎると途中でやめてしまうので、目標側を削って調整する。
        rows = []
        for i, q in enumerate(list(qs[:6]) + _COMMON_QUESTIONS):
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
                 .select("id,seq,question,score,choice,reason_mode,reason_text,goal_kind")
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

    # ==========================================================
    # 第2段：職員の確認 → ICF付箋へのフィードバック → 次の目標
    #   ここで初めて status='confirmed' になる。
    #   ★どの操作も途中でやめられること。職員は他の仕事に呼ばれる。
    # ==========================================================

    def _eval_bundle(supabase, f_code, eid):
        """評価1件と、その回答をまとめて取る。"""
        e = (supabase.table("patient_self_evaluations").select("*")
             .eq("facility_code", f_code).eq("id", eid).execute())
        if not e.data:
            return None, None
        a = (supabase.table("patient_self_eval_answers").select("*")
             .eq("facility_code", f_code).eq("evaluation_id", eid).order("seq").execute())
        return e.data[0], (a.data or [])

    def _answers_text(answers):
        """AIに渡す用に、回答を読みやすい形へ。"""
        L = []
        for a in answers:
            sc = a.get("score")
            if sc is None:
                continue
            L.append(f"- Q: {a.get('question')}")
            L.append(f"  達成度: {sc}/10")
            if a.get("reason_text"):
                L.append(f"  本人の言葉: {a.get('reason_text')}")
            elif a.get("reason_mode") == "skip":
                L.append("  本人の言葉: （答えたくないとのことで、とばした）")
            if a.get("icf_zone"):
                L.append(f"  領域: {_zone_label(a.get('icf_zone'))}")
        return "\n".join(L)

    def _dedup_key(code, pol, text):
        """★ patient_hub_integration の _icf_dedup_key と【同じ規則】にすること。
        ずれると同じ付箋が二重に増える。向こうを直したらこちらも直す。"""
        p = "cannot" if pol == "cannot" else "can"
        c = (str(code).strip() if code else "")
        return ("c", c, p) if c else ("t", (text or "").strip().lower(), p)

    @app.route('/api/self-eval/staff-note', methods=['POST'])
    @login_required
    def api_self_eval_staff_note():
        """★職員メモの途中保存。確定しなくても残る。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        d = request.json or {}
        eid = (d.get("id") or "").strip()
        if not eid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        try:
            (supabase.table("patient_self_evaluations")
             .update({"staff_note": (d.get("staff_note") or "")[:4000], "updated_at": _now_iso()})
             .eq("id", eid).eq("facility_code", f_code).execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success"})

    @app.route('/api/self-eval/icf-suggest', methods=['POST'])
    @login_required
    def api_self_eval_icf_suggest():
        """回答から、ICF付箋の候補をAIが出す。
        ★ここではまだ何も保存しない。職員が選んだものだけ icf-apply で貼る。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        eid = ((request.json or {}).get("id") or "").strip()
        ev, answers = _eval_bundle(supabase, f_code, eid)
        if not ev:
            return jsonify({"status": "error", "message": "見つかりません"}), 404
        body = _answers_text(answers)
        if not body:
            return jsonify({"status": "success", "stickies": [], "message": "回答がありません"})

        # ★いま貼ってある付箋を id つきで渡す。
        #   できるようになった項目は「新しい付箋を足す」だけでは足りない。
        #   元の『できない』付箋を『できる』に書き換えないと、
        #   「入浴に見守りが必要」と「入浴が自分でできる」が並ぶ矛盾した board になる。
        cur = []
        try:
            ex = (supabase.table("patient_icf_stickies").select("id,zone,text,polarity,icf_code")
                  .eq("facility_code", f_code)
                  .eq("patient_profile_id", str(ev.get("patient_profile_id"))).execute())
            cur = ex.data or []
        except Exception:
            cur = []
        cur_lines = []
        for c in cur:
            cur_lines.append(
                f"- id={c.get('id')} [{_zone_label(c.get('zone'))}]"
                f"({'できない' if c.get('polarity') == 'cannot' else 'できる'}) {c.get('text')}")

        prompt = (
            "以下は、介護施設の利用者【本人】がタブレットで答えた、目標の達成度と理由です。\n"
            "これをもとに、ICF（国際生活機能分類）の付箋を更新します。やることは2つです。\n\n"
            "【1】新しく分かったことを付箋にする（stickies）\n"
            "【2】★すでに貼ってある付箋のうち、【できるようになったもの】を書き換える（updates）\n\n"
            "【領域(zone)】\n"
            "  body=心身機能 / activity=活動 / participation=参加 /"
            " environment=環境因子 / personal=個人因子\n"
            "【polarity】can=できる・良好 / cannot=できない・支障\n\n"
            "★★【必ずこの順番で考えること】★★\n"
            "手順1. まず『いま貼ってある付箋』を1枚ずつ見ます。\n"
            "手順2. その付箋の内容に【対応する質問】が本人の回答の中にあるか探します。\n"
            "        例：付箋『入浴に見守りが必要』 ←→ 質問『お風呂で体を洗えましたか』\n"
            "        例：付箋『食事に一部介助が必要』 ←→ 質問『ご自分で食べられましたか』\n"
            "手順3. 対応する質問があり、その達成度が【8以上】なら、\n"
            "        その付箋の id を updates に入れて can に書き換えます。\n"
            "        text も自然な日本語に直すこと。\n"
            "        例：『入浴に見守りが必要』(cannot) → 『入浴を自分でできる』(can)\n"
            "        『できない』のままの文で polarity だけ can にしてはいけません。意味が通りません。\n"
            "        達成度が4〜7ならまだ支障が残っているので書き換えないこと。\n"
            "手順4. 最後に、既存の付箋では表せない【新しい情報】だけを stickies に入れます。\n\n"
            "★★【stickies に入れてはいけないもの】★★\n"
            "・すでにある付箋と同じ意味のもの。\n"
            "  → それは新規ではなく updates で書き換えるべきものです。\n"
            "  悪い例：付箋に『入浴に見守りが必要』があるのに『自分で体を洗える』を新規で足す。\n"
            "        この2つが並ぶと、どちらが本当か分からない board になります。\n"
            "・質問文をひっくり返しただけのもの。\n"
            "  悪い例：質問『他の方と話す機会がありましたか』→『他者との会話機会に介助が必要』\n"
            "・達成度の数字だけから機械的に作ったもの。\n"
            "  【本人の言葉（自由記載）に新しい情報があるときだけ】足してください。\n"
            "・達成度が4〜7の項目から作った付箋。まだ途中なので、既存の付箋のままで構いません。\n"
            "・新しい情報が無ければ stickies は空配列で構いません。無理に埋めないでください。\n\n"
            "【そのほかの決まり】\n"
            "・本人が言ったことだけを書く。書かれていないことを推測して足さない。\n"
            "・短い体言止めで1項目1事実。医療診断はしない。\n"
            "・本人の言葉に趣味・役割・人との関わりが出てきたら participation や personal に拾う。\n"
            "・stickies は最大5項目。updates は該当が無ければ空配列にすること。\n"
            "・できていたことができなくなった場合も updates で can → cannot にしてよい。\n\n"
            "JSONのみを返す（説明文は禁止）:\n"
            '{"stickies":[{"zone":"participation","text":"他の利用者と将棋で交流している",'
            '"polarity":"can","why":"本人が「将棋の相手ができた」と答えたため"}],'
            '"updates":[{"id":"<いま貼ってある付箋のid>","text":"入浴を自分でできる",'
            '"polarity":"can","why":"入浴の達成度が9で、見守りなしでできたため"}]}\n\n'
            "=== いま貼ってある付箋 ===\n" + ("\n".join(cur_lines) or "（なし）") +
            "\n\n=== 本人の回答 ===\n" + body
        )
        items, ups = [], []
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            mm = re.search(r'\{.*\}', (resp.text or "").strip(), re.DOTALL)
            if mm:
                parsed = _json.loads(mm.group())
                items = parsed.get("stickies", []) or []
                ups = parsed.get("updates", []) or []
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI生成に失敗しました: {e}"}), 500

        # すでにボードにある付箋は「新規」候補から外す（同じ付箋が増えないように）
        seen = set()
        for c in cur:
            seen.add(_dedup_key(c.get("icf_code"), c.get("polarity"), c.get("text")))
        out = []
        for s in items[:5]:
            t = (str(s.get("text") or "")).strip()
            if not t:
                continue
            pol = s.get("polarity") if s.get("polarity") in ("can", "cannot") else None
            if _dedup_key(None, pol, t) in seen:
                continue
            out.append({"zone": (s.get("zone") or "unsorted"), "text": t[:200],
                        "polarity": pol, "why": (s.get("why") or "")[:200]})

        # updates は実在する付箋のidだけ通す（AIが勝手なidを返すことがある）
        by_id = {str(c.get("id")): c for c in cur}
        upd_out = []
        for u in (ups or [])[:8]:
            uid = str(u.get("id") or "")
            old = by_id.get(uid)
            if not old:
                continue
            pol = u.get("polarity") if u.get("polarity") in ("can", "cannot") else None
            t = (str(u.get("text") or "")).strip() or (old.get("text") or "")
            if not pol or (pol == old.get("polarity") and t == old.get("text")):
                continue                      # 変化なしなら出さない
            upd_out.append({"id": uid, "text": t[:200], "polarity": pol,
                            "old_text": old.get("text"), "old_polarity": old.get("polarity"),
                            "zone": old.get("zone"), "why": (u.get("why") or "")[:200]})
        return jsonify({"status": "success", "stickies": out, "updates": upd_out})

    @app.route('/api/self-eval/icf-apply', methods=['POST'])
    @login_required
    def api_self_eval_icf_apply():
        """職員が採用した付箋をICFボードへ貼る。
        ★二段階承認にしない（現場の手間が増えるだけ）。ただし重複判定は必ず通す。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        d = request.json or {}
        eid = (d.get("id") or "").strip()
        stickies = d.get("stickies") or []
        updates = d.get("updates") or []
        ev, _ = _eval_bundle(supabase, f_code, eid)
        if not ev:
            return jsonify({"status": "error", "message": "見つかりません"}), 404
        pid = str(ev.get("patient_profile_id"))

        # ★先に「できない → できる」の書き換えを済ませる。
        #   これを後回しにすると、書き換え後の内容と新規追加が重複判定に引っかかる。
        changed = 0
        for u in updates:
            uid = str((u or {}).get("id") or "")
            pol = u.get("polarity") if u.get("polarity") in ("can", "cannot") else None
            t = (str(u.get("text") or "")).strip()
            if not uid or not pol or not t:
                continue
            try:
                (supabase.table("patient_icf_stickies")
                 .update({"text": t[:200], "polarity": pol, "updated_at": _now_iso()})
                 .eq("id", uid).eq("facility_code", f_code)
                 .eq("patient_profile_id", pid).execute())
                changed += 1
            except Exception as e:
                print(f"[self-eval] icf update failed id={uid}: {e}", flush=True)

        seen = set()
        base = 0
        try:
            ex = (supabase.table("patient_icf_stickies").select("icf_code,polarity,text,sort_order")
                  .eq("facility_code", f_code).eq("patient_profile_id", pid).execute())
            for r in (ex.data or []):
                seen.add(_dedup_key(r.get("icf_code"), r.get("polarity"), r.get("text")))
                base = max(base, int(r.get("sort_order") or 0))
        except Exception:
            pass
        base += 1

        rows = []
        for s in stickies:
            t = (str((s or {}).get("text") or "")).strip()
            if not t:
                continue
            pol = s.get("polarity") if s.get("polarity") in ("can", "cannot") else None
            k = _dedup_key(None, pol, t)
            if k in seen:
                continue
            seen.add(k)
            rows.append({
                "facility_code": f_code, "patient_profile_id": pid,
                "zone": (s.get("zone") or "unsorted"), "text": t[:200],
                "polarity": pol, "sort_order": base + len(rows),
            })
        if rows:
            try:
                supabase.table("patient_icf_stickies").insert(rows).execute()
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success", "added": len(rows), "changed": changed})

    @app.route('/api/self-eval/next-goal', methods=['POST'])
    @login_required
    def api_self_eval_next_goal():
        """達成できた項目があるとき、次の目標をAIが提案する。
        ★介護の目標設定では『活動ができたら参加へ広げる』のが本筋。
          「歩ける」の次が「もっと歩ける」だけでは、その方の生活は広がらない。
          そのためプロンプトで【同じ軸で少し難しく】と【別の軸へ広げる】の2方向を必ず出させる。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        d = request.json or {}
        eid = (d.get("id") or "").strip()
        tone = (d.get("tone") or "").strip()      # '' / 'easier' / 'concrete' / 'longer'
        ev, answers = _eval_bundle(supabase, f_code, eid)
        if not ev:
            return jsonify({"status": "error", "message": "見つかりません"}), 404

        m = _gather_material(supabase, f_code, str(ev.get("patient_profile_id")))
        done = [a for a in answers if (a.get("score") or 0) >= 8]
        if not done:
            return jsonify({"status": "success", "goals": [],
                            "message": "達成できた項目がありません。目標は続けてよさそうです。"})

        L = ["以下は介護施設の利用者について、いまの目標・達成状況・本人の言葉です。",
             "達成できた項目があるので、【次の目標】の案を作ってください。", ""]
        L.append("【いまの目標】")
        for k, v in (m.get("goals") or {}).items():
            L.append(f"- {k}: {v}")
        L.append("")
        L.append("【本人の回答】")
        L.append(_answers_text(answers))
        if m.get("can"):
            L.append("")
            L.append("【できること】")
            for x in m["can"][:10]:
                L.append(f"- [{_zone_label(x['zone'])}] {x['text']}")
        if m.get("cannot"):
            L.append("")
            L.append("【まだできないこと】")
            for x in m["cannot"][:10]:
                L.append(f"- [{_zone_label(x['zone'])}] {x['text']}")
        if m.get("hobbies") or m.get("likes") or m.get("job"):
            L.append("")
            L.append("【趣味・好きなもの・職歴】※参加の目標を考えるときに使う")
            for v in (m.get("hobbies"), m.get("likes"), m.get("job")):
                if v:
                    L.append("- " + v[:120])
        L += ["", "【必ず守ること】",
              "★1. 案は3つ。うち【少なくとも1つは『参加』の領域へ広げる案】にすること。",
              "     介護では、活動ができるようになったら参加（役割・人との関わり）へ広げるのが本筋です。",
              "     『歩ける』の次が『もっと歩ける』だけでは、その方の生活は広がりません。",
              "★2. 各案に kind を付ける: 'step_up'(同じ軸で少し難しく) / 'widen'(別の軸へ広げる)",
              "★3. 目標文は、達成できたかどうかを判定できる具体的な行動で書く。",
              "     悪い例『意欲を持って生活する』 良い例『食堂まで歩いて行き、週に1回は他の方と話す』",
              "★4. why には、なぜこの目標を勧めるのかを職員向けに1〜2文で書く。",
              "★5. できないことを無視して背伸びさせない。いまの状態から一歩先にすること。"]
        if tone == "easier":
            L.append("★6. 前回より【やさしめ】にしてください。段差を小さく。")
        elif tone == "concrete":
            L.append("★6. 前回より【具体的】にしてください。回数・場所・時間などを入れる。")
        elif tone == "longer":
            L.append("★6. 【長期目標】として、3〜6か月かけて達成する大きさにしてください。")
        L += ["", "JSONのみを返す（説明文は禁止）:",
              '{"goals":[{"text":"食堂まで歩いて行き、週に1回は他の方と話す",'
              '"kind":"widen","zone":"participation","term":"short",'
              '"why":"歩行が安定してきたため、活動から参加へ広げる時期です。"}]}']

        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content("\n".join(L))
            mm = re.search(r'\{.*\}', (resp.text or "").strip(), re.DOTALL)
            goals = _json.loads(mm.group()).get("goals", []) if mm else []
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI生成に失敗しました: {e}"}), 500

        goals = [{"text": (g.get("text") or "")[:300], "kind": (g.get("kind") or "")[:12],
                  "zone": (g.get("zone") or "")[:20], "term": (g.get("term") or "short")[:10],
                  "why": (g.get("why") or "")[:300]} for g in goals[:3] if (g.get("text") or "").strip()]
        # ★途中保存：作った案は残す。職員が他の仕事に呼ばれても消えない。
        try:
            (supabase.table("patient_self_evaluations")
             .update({"next_goal_draft": _json.dumps({"goals": goals}, ensure_ascii=False),
                      "updated_at": _now_iso()})
             .eq("id", eid).eq("facility_code", f_code).execute())
        except Exception:
            pass
        return jsonify({"status": "success", "goals": goals,
                        "achieved": [a.get("question") for a in done]})

    @app.route('/api/self-eval/next-goal/apply', methods=['POST'])
    @login_required
    def api_self_eval_next_goal_apply():
        """選んだ次の目標を patient_profiles に反映する。
        ★短期か長期かは職員が決める。反映前に必ず確認させること（目標は計画書の根幹）。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        d = request.json or {}
        eid = (d.get("id") or "").strip()
        text = (d.get("text") or "").strip()
        term = d.get("term") if d.get("term") in ("short", "long") else "short"
        if not text:
            return jsonify({"status": "error", "message": "目標の文が空です"}), 400
        ev, _ = _eval_bundle(supabase, f_code, eid)
        if not ev:
            return jsonify({"status": "error", "message": "見つかりません"}), 404
        col = "short_goal" if term == "short" else "long_goal"
        try:
            (supabase.table("patient_profiles").update({col: text[:500]})
             .eq("facility_code", f_code).eq("id", ev.get("patient_profile_id")).execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        print(f"[self-eval] next goal applied ({term}) eval={eid} by={session.get('my_name','')}", flush=True)
        return jsonify({"status": "success", "term": term})

    # ==========================================================
    # 第4段：既存の評価（patient_evaluations）へつなぐ
    #   ★方針（2026-08-20 ユーザーと合意）：
    #     セルフ評価は「評価の入力欄」ではなく【評価を書くための材料】。
    #     入力の入口は既存の評価画面ひとつに保つ。二極化させない。
    #     ここでやるのは source_data（元データ）への追記だけ。
    #     そのあと職員が評価画面の「AIで生成」を押すと、
    #     本人の声も踏まえた「訓練による変化」「課題とその要因」が出る。
    # ==========================================================
    _EVAL_MARK = "【ご本人の回答】"

    def _build_source_block(ev, answers):
        """評価の source_data に貼るテキストを作る。職員が読んで分かる形にする。"""
        L = [_EVAL_MARK + "　" + (ev.get("answered_at") or "")[:10] + "　タブレットでご本人が回答"]
        kind_label = {"change": "訓練による変化について", "satisfy": "満足度",
                      "fit": "サービスの適切さ", "free": "これからしてみたいこと・困っていること"}
        for a in answers:
            k = a.get("goal_kind") or ""
            sc = a.get("score")
            head = kind_label.get(k)
            if k == "free":
                txt = (a.get("reason_text") or "").strip()
                if txt:
                    L.append(f"・{head}：「{txt}」")
                elif a.get("reason_mode") == "voice":
                    L.append(f"・{head}：声で回答あり（録音）")
                continue
            if sc is None:
                continue
            if head:
                L.append(f"・{head}：{sc}/10")
                if (a.get("reason_text") or "").strip():
                    L.append(f"　　本人の言葉：「{a.get('reason_text').strip()}」")
                continue
            L.append(f"・{a.get('question')}　→ {sc}/10")
            if (a.get("reason_text") or "").strip():
                L.append(f"　　本人の言葉：「{a.get('reason_text').strip()}」")
            elif a.get("reason_mode") == "skip":
                L.append("　　本人の言葉：（答えたくないとのことでとばした）")
            elif a.get("reason_mode") == "voice":
                L.append("　　本人の言葉：声で回答あり（録音）")
        if (ev.get("staff_note") or "").strip():
            L.append("・職員のメモ：" + ev.get("staff_note").strip())
        return "\n".join(L)

    @app.route('/api/self-eval/to-evaluation', methods=['POST'])
    @login_required
    def api_self_eval_to_evaluation():
        """回答を、その月の評価の source_data（元データ）へ追記する。
        ★上書きしない。職員が書いた内容の後ろに足すだけ。
        ★評価の行がまだ無いときは作らない（必須項目が空の中途半端な行を作らないため）。
          その場合は職員に「先に評価画面で評価を作ってください」と伝える。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        d = request.json or {}
        eid = (d.get("id") or "").strip()
        force = bool(d.get("force"))
        ev, answers = _eval_bundle(supabase, f_code, eid)
        if not ev:
            return jsonify({"status": "error", "message": "見つかりません"}), 404
        uname = (ev.get("user_name") or "").strip()
        ym = (ev.get("target_ym") or "").strip()
        if not uname or not ym:
            return jsonify({"status": "error", "message": "利用者名か対象月が空です"}), 400
        try:
            r = (supabase.table("patient_evaluations").select("id,source_data")
                 .eq("facility_code", f_code).eq("user_name", uname)
                 .eq("year_month", ym).execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        if not r.data:
            return jsonify({"status": "error", "need_eval": True,
                            "message": f"{ym} の評価がまだ作られていません。"
                                       "先に評価画面でこの方の評価を作ってから、もう一度お試しください。"}), 400
        row = r.data[0]
        old = row.get("source_data") or ""
        if (_EVAL_MARK in old) and not force:
            return jsonify({"status": "error", "already": True,
                            "message": "すでに取り込み済みのようです。もう一度追加しますか？"}), 409
        block = _build_source_block(ev, answers)
        new = (old.rstrip() + "\n\n" + block).strip() if old.strip() else block
        try:
            (supabase.table("patient_evaluations").update({"source_data": new[:20000]})
             .eq("id", row["id"]).execute())
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        print(f"[self-eval] source_data appended eval={eid} ym={ym}", flush=True)
        return jsonify({"status": "success", "chars": len(block)})

    @app.route('/api/self-eval/confirm', methods=['POST'])
    @login_required
    def api_self_eval_confirm():
        """職員が確認を終えて確定する。ここで初めて status='confirmed'。"""
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        me = session.get("my_name", "")
        d = request.json or {}
        eid = (d.get("id") or "").strip()
        ev, _ = _eval_bundle(supabase, f_code, eid)
        if not ev:
            return jsonify({"status": "error", "message": "見つかりません"}), 404
        if ev.get("status") == "draft":
            return jsonify({"status": "error", "message": "まだご本人の回答が終わっていません"}), 400
        upd = {"status": "confirmed", "confirmed_by": me,
               "confirmed_at": _now_iso(), "updated_at": _now_iso()}
        if d.get("staff_note") is not None:
            upd["staff_note"] = (d.get("staff_note") or "")[:4000]
        try:
            (supabase.table("patient_self_evaluations").update(upd)
             .eq("id", eid).eq("facility_code", f_code).execute())
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
