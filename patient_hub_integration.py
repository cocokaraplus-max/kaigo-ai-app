"""
TASUKARU 利用者情報ハブ（patient-hub-v1）

利用者情報ページ（/patient-info）を「見る/入力」のハブに拡張するための
バックエンドAPI。既存の patient_info_integration.py（ケアプラン）とは別モジュール。

キーは facility_code + patient_profile_id（= patient_profiles.id を文字列で保持）。
DDL: db/patient_hub.sql（先に DEV→本番 の順で適用すること）。

提供API:
  GET  /api/patient-hub/get                 - 選択利用者の全情報（基本情報+家族+病歴+ICF+性質+数秘）
  POST /api/patient-hub/save-basic          - 基本情報の保存（既往歴/家族構成備考/職歴/趣味/好き嫌い）
  POST /api/patient-hub/family/save         - 家族メンバー（ジェノグラム）を一括置換
  POST /api/patient-hub/medical/add         - 病歴イベント追加（手入力=承認済み）
  POST /api/patient-hub/medical/set-status  - 病歴イベントの承認/却下/削除
  POST /api/patient-hub/medical/scan        - ケース記録からAIで病歴候補を抽出（candidate）
  POST /api/patient-hub/icf/save            - ICF付箋を一括置換
  POST /api/patient-hub/icf/import          - 直近議事録の付箋を取り込み
  POST /api/patient-hub/personality/generate- ケース記録からAIで人となりを推測
  POST /api/patient-hub/hobby-ocr           - 趣味嗜好シートをOCRして返す（保存はsave-basic）
"""
from flask import request, jsonify, session, redirect, url_for
from functools import wraps
from datetime import datetime
import re
import json as _json


# ---- 数秘（ライフパスナンバー） ----
_NUMEROLOGY_TRAITS = {
    1:  ("開拓・自立", "自分で決めて進みたい人。頼られると力を出すが、指図は苦手。"),
    2:  ("協調・受容", "人の気持ちに敏感で場を和ませる。控えめで無理を抱えやすい。"),
    3:  ("表現・楽天", "明るく話し好き。楽しいことで元気が出る。飽きやすい面も。"),
    4:  ("堅実・几帳面", "決まった手順を大事にする。急な変更が苦手で安心を好む。"),
    5:  ("自由・好奇心", "変化と刺激を好む。束縛を嫌い、外出や新しい事が楽しみ。"),
    6:  ("世話好き・責任感", "面倒見がよく人に頼られると力を発揮。無理を抱えやすい面も。"),
    7:  ("探究・マイペース", "一人の時間を大切にする。静かな環境で落ち着く。"),
    8:  ("実行・現実的", "しっかり者で任される。頑張りすぎに注意。"),
    9:  ("博愛・情に厚い", "人を思いやり尽くす。過去や人情を大切にする。"),
    11: ("感受性・直感", "繊細で気づきが多い。環境の空気に左右されやすい。"),
    22: ("大器・実現力", "こつこつ大きな事を成す。責任感が強い。"),
    33: ("無償の愛・奉仕", "深い思いやりで人を包む。抱え込みに注意。"),
}


def _calc_numerology(birth_str):
    """生年月日(YYYY-MM-DD)→ライフパスナンバー。1-9,11,22,33。"""
    if not birth_str:
        return None
    digits = [int(c) for c in str(birth_str).replace('-', '') if c.isdigit()]
    if not digits:
        return None
    s = sum(digits)
    while s > 9 and s not in (11, 22, 33):
        s = sum(int(c) for c in str(s))
    return s


def _pp_row(supabase, f_code, pid):
    """patient_profiles を id で1件取得（施設スコープ）。無ければNone。"""
    try:
        r = (supabase.table("patient_profiles").select("*")
             .eq("facility_code", f_code).eq("id", pid).single().execute())
        return r.data
    except Exception:
        return None


def _resolve_pid(supabase, f_code, pid, user_name):
    """pid が来ていればそれ。無ければ user_name から patient_profiles.id を解決。"""
    if pid:
        return pid
    if not user_name:
        return None
    try:
        r = (supabase.table("patient_profiles").select("id")
             .eq("facility_code", f_code).eq("user_name", user_name)
             .limit(1).execute())
        if r.data:
            return r.data[0]["id"]
    except Exception:
        pass
    return None


def register_patient_hub_routes(app):
    """Flaskアプリに利用者情報ハブのルートを登録。"""

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("f_code") or not session.get("my_name"):
                if request.args.get("partial"):
                    return jsonify({"redirect": "/login"})
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    # ==========================================================
    # 選択利用者の全情報を返す
    # ==========================================================
    @app.route('/api/patient-hub/get', methods=['GET'])
    @login_required
    def api_hub_get():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        pid = (request.args.get("pid") or "").strip()
        user_name = (request.args.get("user_name") or "").strip()
        pid = _resolve_pid(supabase, f_code, pid, user_name)
        if not pid:
            return jsonify({"status": "error", "message": "利用者が特定できません"}), 400

        pp = _pp_row(supabase, f_code, pid)
        if not pp:
            return jsonify({"status": "error", "message": "対象が見つかりません"}), 404

        # 家族（ジェノグラム）
        family = []
        try:
            fr = (supabase.table("patient_family_members").select("*")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid))
                  .order("sort_order").execute())
            family = fr.data or []
        except Exception:
            family = []

        # 病歴（承認済み=表示、候補=承認待ちで分ける）
        med_approved, med_candidates = [], []
        try:
            mr = (supabase.table("patient_medical_events").select("*")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid))
                  .execute())
            rows = mr.data or []
            def _key(x):
                return (x.get("event_ym") or x.get("event_date") or "")
            for x in sorted(rows, key=_key, reverse=True):
                if x.get("status") == "candidate":
                    med_candidates.append(x)
                elif x.get("status") == "approved":
                    med_approved.append(x)
        except Exception:
            pass

        # ICF付箋
        icf = []
        try:
            ir = (supabase.table("patient_icf_stickies").select("*")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid))
                  .order("sort_order").execute())
            icf = ir.data or []
        except Exception:
            icf = []

        # 性質推測（キャッシュ）
        personality = None
        try:
            pr = (supabase.table("patient_personality_cache").select("*")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid))
                  .limit(1).execute())
            if pr.data:
                personality = pr.data[0]
        except Exception:
            personality = None

        # 数秘
        num = _calc_numerology(pp.get("birth_date"))
        num_traits = _NUMEROLOGY_TRAITS.get(num)

        return jsonify({
            "status": "success",
            "pid": pid,
            "profile": {
                "id": pp.get("id"),
                "user_name": pp.get("user_name"),
                "user_name_kana": pp.get("user_name_kana"),
                "birth_date": pp.get("birth_date"),
                "care_level": pp.get("care_level"),
                "gender": pp.get("gender"),
                "service_start_date": pp.get("service_start_date"),
                "is_discontinued": pp.get("is_discontinued"),
                "medical_history": pp.get("medical_history"),   # 既往歴（テキスト）
                "family_structure": pp.get("family_structure"), # 家族構成（備考テキスト）
                "job_history": pp.get("job_history"),
                "hobbies": pp.get("hobbies"),
                "likes": pp.get("likes"),
                "dislikes": pp.get("dislikes"),
            },
            "family": family,
            "medical_approved": med_approved,
            "medical_candidates": med_candidates,
            "icf": icf,
            "personality": personality,
            "numerology": {
                "number": num,
                "label": num_traits[0] if num_traits else "",
                "desc": num_traits[1] if num_traits else "",
            },
        })

    # ==========================================================
    # 基本情報の保存（patient_profiles の該当列のみ）
    # ==========================================================
    @app.route('/api/patient-hub/save-basic', methods=['POST'])
    @login_required
    def api_hub_save_basic():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        if not pid:
            return jsonify({"status": "error", "message": "pid が必要です"}), 400
        # 更新可能な列のみホワイトリスト
        allow = ("medical_history", "family_structure", "job_history",
                 "hobbies", "likes", "dislikes")
        row = {k: (data.get(k) if data.get(k) != "" else None)
               for k in allow if k in data}
        if not row:
            return jsonify({"status": "error", "message": "保存対象がありません"}), 400
        row["updated_at"] = datetime.now().isoformat()
        try:
            res = (supabase.table("patient_profiles").update(row)
                   .eq("id", pid).eq("facility_code", f_code).execute())
            if not res.data:
                return jsonify({"status": "error", "message": "対象が見つかりません"}), 404
            return jsonify({"status": "success"})
        except Exception as e:
            print(f"[patient_hub] save_basic error: {e}", flush=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================================
    # 家族メンバー（ジェノグラム）一括置換
    # ==========================================================
    @app.route('/api/patient-hub/family/save', methods=['POST'])
    @login_required
    def api_hub_family_save():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        members = data.get("members") or []
        if not pid:
            return jsonify({"status": "error", "message": "pid が必要です"}), 400
        try:
            # 一括置換（この利用者の既存を消して入れ直す）
            supabase.table("patient_family_members").delete() \
                .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute()
            rows = []
            for i, m in enumerate(members):
                rows.append({
                    "facility_code": f_code,
                    "patient_profile_id": str(pid),
                    "member_label": (m.get("member_label") or None),
                    "sex": (m.get("sex") or None),
                    "is_self": bool(m.get("is_self")),
                    "is_deceased": bool(m.get("is_deceased")),
                    "is_cohabiting": bool(m.get("is_cohabiting")),
                    "age": (int(m["age"]) if str(m.get("age") or "").strip().isdigit() else None),
                    "relation_role": (m.get("relation_role") or None),
                    "note": (m.get("note") or None),
                    "pos_x": m.get("pos_x"),
                    "pos_y": m.get("pos_y"),
                    "sort_order": i,
                })
            if rows:
                supabase.table("patient_family_members").insert(rows).execute()
            return jsonify({"status": "success", "count": len(rows)})
        except Exception as e:
            print(f"[patient_hub] family_save error: {e}", flush=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================================
    # 病歴イベント：手入力追加（承認済みで確定）
    # ==========================================================
    @app.route('/api/patient-hub/medical/add', methods=['POST'])
    @login_required
    def api_hub_medical_add():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        label = (data.get("label") or "").strip()
        if not pid or not label:
            return jsonify({"status": "error", "message": "pid と 内容 が必要です"}), 400
        row = {
            "facility_code": f_code,
            "patient_profile_id": str(pid),
            "event_ym": (data.get("event_ym") or None),
            "event_date": (data.get("event_date") or None),
            "label": label,
            "detail": (data.get("detail") or None),
            "severity": (data.get("severity") or "major"),
            "source": "manual",
            "status": "approved",
            "approved_by": session.get("my_name"),
            "approved_at": datetime.now().isoformat(),
        }
        try:
            res = supabase.table("patient_medical_events").insert(row).execute()
            return jsonify({"status": "success", "id": (res.data[0]["id"] if res.data else None)})
        except Exception as e:
            print(f"[patient_hub] medical_add error: {e}", flush=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================================
    # 病歴イベント：承認/却下/削除
    # ==========================================================
    @app.route('/api/patient-hub/medical/set-status', methods=['POST'])
    @login_required
    def api_hub_medical_set_status():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        ev_id = (data.get("id") or "").strip()
        action = (data.get("action") or "").strip()  # approve/dismiss/delete
        if not ev_id or action not in ("approve", "dismiss", "delete"):
            return jsonify({"status": "error", "message": "不正なリクエスト"}), 400
        try:
            if action == "delete":
                supabase.table("patient_medical_events").delete() \
                    .eq("id", ev_id).eq("facility_code", f_code).execute()
            else:
                upd = {"status": "approved" if action == "approve" else "dismissed"}
                if action == "approve":
                    upd["approved_by"] = session.get("my_name")
                    upd["approved_at"] = datetime.now().isoformat()
                supabase.table("patient_medical_events").update(upd) \
                    .eq("id", ev_id).eq("facility_code", f_code).execute()
            return jsonify({"status": "success"})
        except Exception as e:
            print(f"[patient_hub] medical_set_status error: {e}", flush=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================================
    # 病歴：ケース記録からAIで候補抽出（candidateとして保存）
    # ==========================================================
    @app.route('/api/patient-hub/medical/scan', methods=['POST'])
    @login_required
    def api_hub_medical_scan():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        pp = _pp_row(supabase, f_code, pid) if pid else None
        if not pp:
            return jsonify({"status": "error", "message": "利用者が特定できません"}), 400
        user_name = pp.get("user_name")

        # ケース記録を取得（user_name で結合。直近を対象に件数を絞る）
        try:
            rr = (supabase.table("records").select("id,created_at,category,content")
                  .eq("facility_code", f_code).eq("user_name", user_name)
                  .order("created_at", desc=True).limit(400).execute())
            recs = rr.data or []
        except Exception as e:
            return jsonify({"status": "error", "message": f"記録取得失敗: {e}"}), 500
        if not recs:
            return jsonify({"status": "success", "added": 0, "message": "対象の記録がありません"})

        # 既存イベント（重複回避のためラベル+年月を集合化）
        existing = set()
        try:
            er = (supabase.table("patient_medical_events").select("label,event_ym")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute())
            for e in (er.data or []):
                existing.add(((e.get("label") or "").strip(), (e.get("event_ym") or "").strip()))
        except Exception:
            pass

        # 記録を軽くテキスト化してAIへ
        lines = []
        for r in recs:
            d = (r.get("created_at") or "")[:10]
            c = (r.get("content") or "").replace("\n", " ").strip()
            if c:
                lines.append(f"[{d}] {c[:180]}")
        joined = "\n".join(lines[:300])

        prompt = (
            "以下は介護施設の1利用者のケース記録の抜粋です。日付は[YYYY-MM-DD]。\n"
            "この中から『大きな医療上の出来事』だけを抽出してください。"
            "対象: 脳梗塞・心筋梗塞・骨折・肺炎・入院・手術・がん等の重大な病気やけが。\n"
            "日常の体調変化・軽微な事柄・服薬・通院のみ等は除外。\n"
            "各出来事について、記録の日付から発生年月(YYYY-MM)を推定し、短い病名ラベルを付けてください。\n"
            "必ず次のJSONのみを返す（説明文禁止）:\n"
            '{"events":[{"event_ym":"YYYY-MM","label":"脳梗塞","detail":"根拠となる記録の要点"}]}\n'
            "該当が無ければ {\"events\":[]} を返す。\n\n"
            "=== 記録 ===\n" + joined
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            events = _json.loads(m.group())["events"] if m else []
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI抽出失敗: {e}"}), 500

        added = 0
        for ev in events:
            label = (ev.get("label") or "").strip()
            ym = (ev.get("event_ym") or "").strip()
            if not label:
                continue
            if (label, ym) in existing:
                continue
            try:
                supabase.table("patient_medical_events").insert({
                    "facility_code": f_code,
                    "patient_profile_id": str(pid),
                    "event_ym": ym or None,
                    "label": label,
                    "detail": (ev.get("detail") or None),
                    "severity": "major",
                    "source": "record_ai",
                    "status": "candidate",   # 承認待ち
                }).execute()
                existing.add((label, ym))
                added += 1
            except Exception:
                continue
        return jsonify({"status": "success", "added": added})

    # ==========================================================
    # ICF付箋：一括置換
    # ==========================================================
    @app.route('/api/patient-hub/icf/save', methods=['POST'])
    @login_required
    def api_hub_icf_save():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        stickies = data.get("stickies") or []
        if not pid:
            return jsonify({"status": "error", "message": "pid が必要です"}), 400
        try:
            supabase.table("patient_icf_stickies").delete() \
                .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute()
            rows = []
            for i, s in enumerate(stickies):
                txt = (s.get("text") or "").strip()
                if not txt:
                    continue
                rows.append({
                    "facility_code": f_code,
                    "patient_profile_id": str(pid),
                    "zone": (s.get("zone") or "unsorted"),
                    "text": txt,
                    "icf_code": (s.get("icf_code") or None),
                    "color": (s.get("color") or None),
                    "pos_x": s.get("pos_x"),
                    "pos_y": s.get("pos_y"),
                    "sort_order": i,
                    "source_meeting_id": (s.get("source_meeting_id") or None),
                })
            if rows:
                supabase.table("patient_icf_stickies").insert(rows).execute()
            return jsonify({"status": "success", "count": len(rows)})
        except Exception as e:
            print(f"[patient_hub] icf_save error: {e}", flush=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================================
    # ICF付箋：直近議事録から取り込み（追記。既存は消さない）
    # ==========================================================
    @app.route('/api/patient-hub/icf/import', methods=['POST'])
    @login_required
    def api_hub_icf_import():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        pp = _pp_row(supabase, f_code, pid) if pid else None
        if not pp:
            return jsonify({"status": "error", "message": "利用者が特定できません"}), 400
        user_name = pp.get("user_name")

        # この利用者の直近の担当者会議を1件（meetings に user_name 列がある前提。無ければ空振り）
        meeting_id = (data.get("meeting_id") or "").strip()
        try:
            if not meeting_id:
                mq = (supabase.table("meetings").select("id,created_at")
                      .eq("facility_code", f_code).eq("user_name", user_name)
                      .order("created_at", desc=True).limit(1).execute())
                if mq.data:
                    meeting_id = mq.data[0]["id"]
        except Exception:
            meeting_id = meeting_id
        if not meeting_id:
            return jsonify({"status": "success", "added": 0, "message": "取り込める議事録が見つかりません"})

        # 会議の付箋（board_slot が付いているもの＝配置済み）を取り込む
        added = 0
        try:
            lr = (supabase.table("meeting_icf_links").select("*")
                  .eq("meeting_id", meeting_id).execute())
            # ICFコード→領域(component)の対応
            code_comp = {}
            try:
                mm = (supabase.table("icf_codes").select("code,component").eq("level", 2).execute())
                for c in (mm.data or []):
                    code_comp[c.get("code")] = c.get("component")
            except Exception:
                pass
            zone_map = {  # component → 利用者ページの zone
                "body": "body", "b": "body", "s": "body",
                "activity": "activity", "d": "activity",
                "participation": "participation",
                "environment": "environment", "e": "environment",
                "personal": "personal",
            }
            rows = []
            for i, s in enumerate(lr.data or []):
                txt = (s.get("source_text") or s.get("text") or "").strip()
                if not txt:
                    continue
                comp = code_comp.get(s.get("icf_code")) or (s.get("component") or "")
                zone = zone_map.get(str(comp).lower(), "unsorted")
                rows.append({
                    "facility_code": f_code,
                    "patient_profile_id": str(pid),
                    "zone": zone,
                    "text": txt,
                    "icf_code": (s.get("icf_code") or None),
                    "sort_order": i,
                    "source_meeting_id": meeting_id,
                })
            if rows:
                supabase.table("patient_icf_stickies").insert(rows).execute()
                added = len(rows)
        except Exception as e:
            return jsonify({"status": "error", "message": f"取り込み失敗: {e}"}), 500
        return jsonify({"status": "success", "added": added})

    # ==========================================================
    # 性質推測：ケース記録からAIで人となりを生成（キャッシュ上書き）
    # ==========================================================
    @app.route('/api/patient-hub/personality/generate', methods=['POST'])
    @login_required
    def api_hub_personality_generate():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        pp = _pp_row(supabase, f_code, pid) if pid else None
        if not pp:
            return jsonify({"status": "error", "message": "利用者が特定できません"}), 400
        user_name = pp.get("user_name")

        try:
            rr = (supabase.table("records").select("created_at,category,content")
                  .eq("facility_code", f_code).eq("user_name", user_name)
                  .order("created_at", desc=True).limit(200).execute())
            recs = rr.data or []
        except Exception as e:
            return jsonify({"status": "error", "message": f"記録取得失敗: {e}"}), 500
        if not recs:
            return jsonify({"status": "success", "message": "対象の記録がありません", "personality": None})

        lines = []
        for r in recs:
            c = (r.get("content") or "").replace("\n", " ").strip()
            if c:
                lines.append(c[:160])
        joined = "\n".join(lines[:200])

        prompt = (
            "以下は介護施設の1利用者のケース記録の抜粋です。\n"
            "記録から読み取れる『人となり（性格傾向・接し方のヒント）』を推測してください。\n"
            "断定しすぎず、支援者が接するときの参考になる表現で。医療診断はしない。\n"
            "必ず次のJSONのみを返す（説明文禁止）:\n"
            '{"traits":["穏やか","几帳面"],"summary":"接し方の要点を2〜3文で"}\n\n'
            "=== 記録 ===\n" + joined
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            obj = _json.loads(m.group()) if m else {"traits": [], "summary": ""}
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI生成失敗: {e}"}), 500

        traits = obj.get("traits") or []
        summary = obj.get("summary") or ""
        rowdata = {
            "facility_code": f_code,
            "patient_profile_id": str(pid),
            "traits": _json.dumps(traits, ensure_ascii=False),
            "summary": summary,
            "source_count": len(recs),
            "generated_at": datetime.now().isoformat(),
        }
        try:
            # 手動upsert（unique制約はあるが安全側で存在確認）
            ex = (supabase.table("patient_personality_cache").select("id")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid))
                  .limit(1).execute())
            if ex.data:
                supabase.table("patient_personality_cache").update(rowdata) \
                    .eq("id", ex.data[0]["id"]).execute()
            else:
                supabase.table("patient_personality_cache").insert(rowdata).execute()
        except Exception as e:
            print(f"[patient_hub] personality upsert error: {e}", flush=True)

        return jsonify({"status": "success", "personality": {
            "traits": traits, "summary": summary, "source_count": len(recs),
        }})

    # ==========================================================
    # 趣味嗜好シートOCR（画像→Gemini→テキスト。保存はsave-basic側）
    # ==========================================================
    @app.route('/api/patient-hub/hobby-ocr', methods=['POST'])
    @login_required
    def api_hub_hobby_ocr():
        data = request.json or {}
        image_b64 = data.get("image", "")
        mime = data.get("mime_type", "image/jpeg")
        if not image_b64:
            return jsonify({"status": "error", "message": "画像がありません"}), 400
        prompt = (
            "これは介護施設の『趣味・嗜好シート』の画像です。手書きや印刷の記入内容を読み取り、"
            "次のJSONのみで返してください（説明文禁止）:\n"
            '{"hobbies":"趣味・嗜好（好きな活動・音楽・食べ物など）を文章で",'
            '"likes":"好きなもの","dislikes":"苦手・嫌いなもの","job_history":"職歴（あれば）"}\n'
            "読み取れない項目は空文字。"
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content([
                {"mime_type": mime, "data": image_b64}, prompt
            ])
            text = (resp.text or "").strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            obj = _json.loads(m.group()) if m else {}
        except Exception as e:
            return jsonify({"status": "error", "message": f"OCR失敗: {e}"}), 500
        return jsonify({"status": "success", "ocr": {
            "hobbies": obj.get("hobbies", ""),
            "likes": obj.get("likes", ""),
            "dislikes": obj.get("dislikes", ""),
            "job_history": obj.get("job_history", ""),
        }})

    print("[patient_hub] 利用者情報ハブのルートを登録しました")
    return app
