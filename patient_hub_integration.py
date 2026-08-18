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
                    "polarity": (s.get("polarity") if s.get("polarity") in ("can", "cannot") else None),
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

        # A1(icf-accumulate-dedup-v1): 指定担会 or 全担会のICFを既存ボードへ積み上げ（重複スルー）
        meeting_id = (data.get("meeting_id") or "").strip()
        try:
            if meeting_id:
                _mq = (supabase.table("meetings").select("id")
                       .eq("facility_code", f_code).eq("patient_id", str(pid))
                       .eq("id", meeting_id).limit(1).execute())
                meeting_ids = [meeting_id] if _mq.data else []
            else:
                _mq = (supabase.table("meetings").select("id,meeting_date")
                       .eq("facility_code", f_code).eq("patient_id", str(pid))
                       .order("meeting_date", desc=False).execute())
                meeting_ids = [m["id"] for m in (_mq.data or [])]
        except Exception:
            meeting_ids = [meeting_id] if meeting_id else []
        if not meeting_ids:
            return jsonify({"status": "success", "added": 0, "skipped": 0, "message": "取り込める議事録が見つかりません"})

        # 会議の付箋を取り込む → 利用者ページの zone を決める。
        # 優先1: board_slot(配置スロット名: bs/activity/participation/environment/personal/health)
        # 優先2: board_component(ICF構成要素の文字: b/s/d/e)
        # 優先3: icf_code から構成要素を引く
        SLOT_TO_ZONE = {
            "bs": "body", "activity": "activity", "participation": "participation",
            "environment": "environment", "personal": "personal", "health": "unsorted",
        }
        COMP_TO_ZONE = {"b": "body", "s": "body", "d": "activity", "e": "environment"}
        def _pol_norm(p):
            return "cannot" if p == "cannot" else "can"

        def _dedup_key(code, pol, text):
            code = (str(code).strip() if code else "")
            if code:
                return ("c", code, _pol_norm(pol))
            return ("t", (text or "").strip().lower(), _pol_norm(pol))

        added = 0
        skipped = 0
        try:
            # 既存ボードの重複キー集合（再実行で増やさない） icf-accumulate-dedup-v1
            seen = set()
            try:
                ex = (supabase.table("patient_icf_stickies").select("icf_code,polarity,text")
                      .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute())
                for r in (ex.data or []):
                    seen.add(_dedup_key(r.get("icf_code"), r.get("polarity"), r.get("text")))
            except Exception:
                pass
            # icf_code→構成要素(b/s/d/e) のフォールバック用
            code_comp = {}
            try:
                mm = (supabase.table("icf_codes").select("code,component").eq("level", 2).execute())
                for c in (mm.data or []):
                    code_comp[c.get("code")] = (c.get("component") or "")
            except Exception:
                pass
            rows = []
            for mid in meeting_ids:
                lr = (supabase.table("meeting_icf_links").select("*")
                      .eq("meeting_id", mid).order("sort_order", desc=False).execute())
                for i, s in enumerate(lr.data or []):
                    txt = (s.get("source_text") or s.get("note") or "").strip()
                    if not txt:
                        continue
                    _pol = s.get("polarity")
                    key = _dedup_key(s.get("icf_code"), _pol, txt)
                    if key in seen:
                        skipped += 1
                        continue
                    seen.add(key)
                    slot = str(s.get("board_slot") or "").strip().lower()
                    comp = str(s.get("board_component") or "").strip().lower()[:1]
                    if slot in SLOT_TO_ZONE:
                        zone = SLOT_TO_ZONE[slot]
                    elif comp in COMP_TO_ZONE:
                        zone = COMP_TO_ZONE[comp]
                    else:
                        c2 = str(code_comp.get(s.get("icf_code"), "")).lower()[:1]
                        zone = COMP_TO_ZONE.get(c2, "unsorted")
                    rows.append({
                        "facility_code": f_code,
                        "patient_profile_id": str(pid),
                        "zone": zone,
                        "text": txt,
                        "icf_code": (s.get("icf_code") or None),
                        "polarity": (_pol if _pol in ("can", "cannot") else None),
                        "sort_order": len(rows),
                        "source_meeting_id": mid,
                    })
            if rows:
                supabase.table("patient_icf_stickies").insert(rows).execute()
                added = len(rows)
        except Exception as e:
            return jsonify({"status": "error", "message": f"積み上げ失敗: {e}"}), 500
        return jsonify({"status": "success", "added": added, "skipped": skipped})

    # ==========================================================
    # ICF：ケース記録からAIで「できる/できない」付きICF案を生成（保存せず返す）
    # フロントがボードに追加→職員が確認して保存する運用。
    # ==========================================================
    @app.route('/api/patient-hub/icf/generate', methods=['POST'])
    @login_required
    def api_hub_icf_generate():
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
            return jsonify({"status": "success", "stickies": [], "message": "対象の記録がありません"})

        lines = []
        for r in recs:
            c = (r.get("content") or "").replace("\n", " ").strip()
            if c:
                lines.append(c[:160])
        joined = "\n".join(lines[:200])

        prompt = (
            "以下は介護施設の1利用者のケース記録の抜粋です。\n"
            "この人の状態をICF（国際生活機能分類）の視点で整理してください。\n"
            "『できること(can)』だけでなく『できないこと/支障(cannot)』も必ず拾ってください。\n"
            "各項目を次の領域(zone)に分類:\n"
            "  body=心身機能・身体構造 / activity=活動(日常動作) / participation=参加(役割・社会)\n"
            "  environment=環境因子(家族・住環境・支援) / personal=個人因子(性格・生活歴など)\n"
            "polarity は can(できる/良好) か cannot(できない/支障) のどちらか。\n"
            "短い体言止めで、1項目1事実。医療診断はしない。最大16項目。\n"
            "必ず次のJSONのみを返す（説明文禁止）:\n"
            '{"stickies":[{"zone":"activity","text":"屋内は伝い歩き","polarity":"can"},'
            '{"zone":"activity","text":"入浴は全介助","polarity":"cannot"}]}\n\n'
            "=== 記録 ===\n" + joined
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            items = _json.loads(m.group())["stickies"] if m else []
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI生成失敗: {e}"}), 500

        _zones = {"body", "activity", "participation", "environment", "personal"}
        out = []
        for it in items:
            txt = (str(it.get("text") or "")).strip()
            if not txt:
                continue
            zone = it.get("zone") if it.get("zone") in _zones else "unsorted"
            pol = it.get("polarity") if it.get("polarity") in ("can", "cannot") else "can"
            out.append({"zone": zone, "text": txt, "polarity": pol})
        return jsonify({"status": "success", "stickies": out})

    # ==========================================================
    # icf-suggest-from-record-v1 : 1件のケース記録からICF追記案（新規のみ）を返す
    # ==========================================================
    def _icf_dedup_key(code, pol, text):
        p = "cannot" if pol == "cannot" else "can"
        c = (str(code).strip() if code else "")
        return ("c", c, p) if c else ("t", (text or "").strip().lower(), p)

    def _icf_pid_by_name(supabase, f_code, user_name):
        try:
            r = (supabase.table("patient_profiles").select("id")
                 .eq("facility_code", f_code).eq("user_name", user_name).limit(1).execute())
            return (r.data or [{}])[0].get("id")
        except Exception:
            return None

    def _icf_board_keys(supabase, f_code, pid):
        seen = set()
        if not pid:
            return seen
        try:
            ex = (supabase.table("patient_icf_stickies").select("icf_code,polarity,text")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid)).execute())
            for r in (ex.data or []):
                seen.add(_icf_dedup_key(r.get("icf_code"), r.get("polarity"), r.get("text")))
        except Exception:
            pass
        return seen

    @app.route('/api/patient-hub/icf/suggest', methods=['POST'])
    @login_required
    def api_hub_icf_suggest():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        user_name = (data.get("user_name") or "").strip()
        text = (data.get("text") or "").strip()
        if not user_name or len(text) < 6:
            return jsonify({"status": "success", "stickies": [], "pid": None})
        pid = _icf_pid_by_name(supabase, f_code, user_name)
        prompt = (
            "以下は介護施設のある利用者の『1件のケース記録』です。\n"
            "この記録から、ICF（国際生活機能分類）に残すべき『生活機能の事実』だけを抽出してください。\n"
            "ルール:\n"
            "1. 明確に読み取れる事実のみ。推測・一般論・医療診断・その日限りの一過性の様子は入れない。\n"
            "2. 似た内容は必ず1つにまとめる（重複禁止）。1項目=1事実、体言止めで簡潔に。\n"
            "3. できること=can、できないこと/支障=cannot。\n"
            "4. 領域(zone)は次で厳密に分類:\n"
            "   body=心身機能・身体構造（筋力・認知・感情・麻痺・痛み・嚥下など体の働き）\n"
            "   activity=活動（歩行・移乗・食事・入浴・排泄・更衣などの動作）\n"
            "   participation=参加（行事/レク参加・役割・地域交流・就労など社会的関与）\n"
            "   environment=環境因子（家族の支援・住環境・福祉用具・制度など周囲の条件）\n"
            "   personal=個人因子（性格・生活歴・価値観・趣味嗜好）\n"
            "5. 会話・理解・意思疎通は、状態はbody・実際のやりとり動作はactivityに寄せ、両方を別項目に分けない。\n"
            "6. ICFに値する事実が無ければ空配列。多くても4項目まで。\n"
            "必ず次のJSONのみ返す（説明文禁止）:\n"
            '{"stickies":[{"zone":"activity","text":"見守りで歩行器歩行","polarity":"can"}]}\n\n'
            "=== 記録 ===\n" + text[:1500]
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            raw = (resp.text or "").strip()
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            items = _json.loads(m.group())["stickies"] if m else []
        except Exception as e:
            return jsonify({"status": "success", "stickies": [], "pid": pid, "note": str(e)})
        seen = _icf_board_keys(supabase, f_code, pid)
        _zones = {"body", "activity", "participation", "environment", "personal"}
        out = []
        for it in (items or []):
            txt = (str(it.get("text") or "")).strip()
            if not txt:
                continue
            zone = it.get("zone") if it.get("zone") in _zones else "unsorted"
            pol = it.get("polarity") if it.get("polarity") in ("can", "cannot") else "can"
            key = _icf_dedup_key(None, pol, txt)
            if key in seen:
                continue
            seen.add(key)
            out.append({"zone": zone, "text": txt, "polarity": pol})
        return jsonify({"status": "success", "stickies": out, "pid": pid})

    @app.route('/api/patient-hub/icf/add', methods=['POST'])
    @login_required
    def api_hub_icf_add():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        stickies = data.get("stickies") or []
        if not pid:
            return jsonify({"status": "error", "message": "pid が必要です"}), 400
        seen = _icf_board_keys(supabase, f_code, pid)
        base = 0
        try:
            mx = (supabase.table("patient_icf_stickies").select("sort_order")
                  .eq("facility_code", f_code).eq("patient_profile_id", str(pid))
                  .order("sort_order", desc=True).limit(1).execute())
            base = int((mx.data or [{}])[0].get("sort_order") or 0) + 1
        except Exception:
            base = 0
        rows = []
        for s in stickies:
            txt = (str(s.get("text") or "")).strip()
            if not txt:
                continue
            pol = s.get("polarity") if s.get("polarity") in ("can", "cannot") else None
            key = _icf_dedup_key(s.get("icf_code"), pol, txt)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "facility_code": f_code, "patient_profile_id": str(pid),
                "zone": (s.get("zone") or "unsorted"), "text": txt,
                "icf_code": (s.get("icf_code") or None),
                "polarity": pol, "sort_order": base + len(rows),
            })
        added = 0
        if rows:
            try:
                supabase.table("patient_icf_stickies").insert(rows).execute()
                added = len(rows)
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success", "added": added, "skipped": len(stickies) - added})

    # ==========================================================
    # icf-classify-position-v1 : 各ICF付箋の内容から推奨zone/polarityを返す（貼り位置提案）
    # ==========================================================
    @app.route('/api/patient-hub/icf/classify', methods=['POST'])
    @login_required
    def api_hub_icf_classify():
        from app import get_supabase
        get_supabase()
        data = request.json or {}
        items = data.get("items") or []
        texts = [(str((it or {}).get("text") or "")).strip() for it in items]
        if not any(texts):
            return jsonify({"status": "success", "items": []})
        _zones = {"body", "activity", "participation", "environment", "personal"}
        numbered = "\n".join("%d: %s" % (i, t) for i, t in enumerate(texts) if t)
        prompt = (
            "次の各ICF付箋の内容を、ICF（国際生活機能分類）の領域に分類してください。\n"
            "領域(zone): body=心身機能・身体構造 / activity=活動 / participation=参加 / environment=環境因子 / personal=個人因子\n"
            "polarity: can(できる/良好) か cannot(できない/支障)。判断できなければ can。\n"
            "各付箋について最も適切な領域を1つだけ。番号(i)は入力のまま。必ず次のJSONのみ返す（説明文禁止）:\n"
            '{"items":[{"i":0,"zone":"activity","polarity":"can"}]}\n\n'
            "=== 付箋 ===\n" + numbered
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            raw = (resp.text or "").strip()
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            parsed = _json.loads(m.group())["items"] if m else []
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI分類失敗: {e}"}), 500
        out = []
        for it in (parsed or []):
            try:
                i = int(it.get("i"))
            except Exception:
                continue
            if i < 0 or i >= len(texts) or not texts[i]:
                continue
            zone = it.get("zone") if it.get("zone") in _zones else None
            pol = it.get("polarity") if it.get("polarity") in ("can", "cannot") else None
            if zone:
                out.append({"i": i, "zone": zone, "polarity": pol})
        return jsonify({"status": "success", "items": out})

    # ==========================================================
    # icf-pending-queue-v1 : ICF追記の保留キュー（あとでまとめて承認）
    # ==========================================================
    @app.route('/api/patient-hub/icf/defer', methods=['POST'])
    @login_required
    def api_hub_icf_defer():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        my = session.get("my_name", "")
        data = request.json or {}
        pid = (data.get("pid") or "").strip()
        user_name = (data.get("user_name") or "").strip() or None
        stickies = data.get("stickies") or []
        label = (data.get("source_label") or "").strip() or None
        if not pid or not stickies:
            return jsonify({"status": "error", "message": "pid と stickies が必要です"}), 400
        rows = []
        for s in stickies:
            txt = (str((s or {}).get("text") or "")).strip()
            if not txt:
                continue
            pol = s.get("polarity") if s.get("polarity") in ("can", "cannot") else None
            rows.append({
                "facility_code": f_code, "patient_profile_id": str(pid),
                "user_name": user_name, "zone": (s.get("zone") or "unsorted"),
                "text": txt, "polarity": pol, "icf_code": (s.get("icf_code") or None),
                "source_label": label, "created_by": my,
            })
        saved = 0
        if rows:
            try:
                supabase.table("icf_pending").insert(rows).execute()
                saved = len(rows)
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success", "deferred": saved})

    @app.route('/api/patient-hub/icf/pending', methods=['GET'])
    @login_required
    def api_hub_icf_pending():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        try:
            r = (supabase.table("icf_pending").select("*")
                 .eq("facility_code", f_code).order("created_at", desc=False).execute())
            rows = r.data or []
        except Exception as e:
            return jsonify({"status": "error", "message": str(e), "pending": [], "count": 0}), 500
        return jsonify({"status": "success", "pending": rows, "count": len(rows)})

    @app.route('/api/patient-hub/icf/pending/resolve', methods=['POST'])
    @login_required
    def api_hub_icf_pending_resolve():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        ids = data.get("ids") or []
        action = (data.get("action") or "").strip()
        ids = [i for i in ids if isinstance(i, int)]
        if not ids or action not in ("approve", "reject"):
            return jsonify({"status": "error", "message": "ids と action(approve/reject) が必要です"}), 400
        added = 0
        try:
            sel = (supabase.table("icf_pending").select("*")
                   .eq("facility_code", f_code).in_("id", ids).execute())
            rows = sel.data or []
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        if action == "approve":
            by_pid = {}
            for r in rows:
                by_pid.setdefault(str(r.get("patient_profile_id")), []).append(r)
            for pid, items in by_pid.items():
                seen = _icf_board_keys(supabase, f_code, pid)
                base = 0
                try:
                    mx = (supabase.table("patient_icf_stickies").select("sort_order")
                          .eq("facility_code", f_code).eq("patient_profile_id", pid)
                          .order("sort_order", desc=True).limit(1).execute())
                    base = int((mx.data or [{}])[0].get("sort_order") or 0) + 1
                except Exception:
                    base = 0
                ins = []
                for r in items:
                    txt = (r.get("text") or "").strip()
                    pol = r.get("polarity") if r.get("polarity") in ("can", "cannot") else None
                    key = _icf_dedup_key(r.get("icf_code"), pol, txt)
                    if not txt or key in seen:
                        continue
                    seen.add(key)
                    ins.append({
                        "facility_code": f_code, "patient_profile_id": pid,
                        "zone": (r.get("zone") or "unsorted"), "text": txt,
                        "icf_code": (r.get("icf_code") or None), "polarity": pol,
                        "sort_order": base + len(ins),
                    })
                if ins:
                    try:
                        supabase.table("patient_icf_stickies").insert(ins).execute()
                        added += len(ins)
                    except Exception:
                        pass
        try:
            supabase.table("icf_pending").delete().eq("facility_code", f_code).in_("id", ids).execute()
        except Exception as e:
            return jsonify({"status": "error", "message": f"削除失敗: {e}"}), 500
        return jsonify({"status": "success", "added": added, "resolved": len(ids)})

    # ==========================================================
    # icf-review-delete-v1 : ICF見直し（削除候補）＝ボード＋最近の記録をAI点検
    # ==========================================================
    @app.route('/api/patient-hub/icf/review', methods=['POST'])
    @login_required
    def api_hub_icf_review():
        from app import get_supabase
        supabase = get_supabase()
        f_code = session["f_code"]
        data = request.json or {}
        user_name = (data.get("user_name") or "").strip()
        items = data.get("items") or []
        texts = [(str((it or {}).get("text") or "")).strip() for it in items]
        pols = [(it or {}).get("polarity") for it in items]
        if not any(texts):
            return jsonify({"status": "success", "items": []})
        recs_text = ""
        if user_name:
            try:
                rr = (supabase.table("records").select("created_at,content")
                      .eq("facility_code", f_code).eq("user_name", user_name)
                      .order("created_at", desc=True).limit(60).execute())
                lines = []
                for r in (rr.data or []):
                    c = (r.get("content") or "").replace("\n", " ").strip()
                    if c:
                        lines.append(c[:140])
                recs_text = "\n".join(lines[:60])
            except Exception:
                recs_text = ""
        numbered = "\n".join(
            "%d: [%s] %s" % (i, ("できない" if pols[i] == "cannot" else "できる"), t)
            for i, t in enumerate(texts) if t
        )
        prompt = (
            "介護施設の1利用者について、現在のICF付箋一覧と最近のケース記録を渡します。\n"
            "ICFから【削除を検討すべき付箋】だけを挙げてください。無ければ空配列。\n"
            "reasonは次のいずれか:\n"
            "  duplicate=他の付箋とほぼ重複 / improved=最近の記録から状態が変わり不要（例:『できない』が既に『できる』）/ outdated=古い・一過性・不適切で残す価値が低い\n"
            "慎重に。明確なものだけ。番号(i)は入力のまま。noteに短い理由。必ず次のJSONのみ返す（説明文禁止）:\n"
            '{"items":[{"i":3,"reason":"improved","note":"最近は入浴を自立して行えており不要"}]}\n\n'
            "=== 現在のICF付箋 ===\n" + numbered + "\n\n=== 最近の記録 ===\n" + (recs_text or "(なし)")
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            resp = model.generate_content(prompt)
            raw = (resp.text or "").strip()
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            parsed = _json.loads(m.group())["items"] if m else []
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI見直し失敗: {e}"}), 500
        _reasons = {"duplicate", "improved", "outdated"}
        out = []
        for it in (parsed or []):
            try:
                i = int(it.get("i"))
            except Exception:
                continue
            if i < 0 or i >= len(texts) or not texts[i]:
                continue
            reason = it.get("reason") if it.get("reason") in _reasons else "outdated"
            note = (str(it.get("note") or "")).strip()[:120]
            out.append({"i": i, "reason": reason, "note": note})
        return jsonify({"status": "success", "items": out})

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
    @app.route('/api/patient-hub/sheet-ocr', methods=['POST'])
    @app.route('/api/patient-hub/hobby-ocr', methods=['POST'])   # 旧名（後方互換）
    @login_required
    def api_hub_sheet_ocr():
        """sheet-ocr-v1: 居宅サービス計画書・利用者情報シートを複数枚まとめて読み取り、
        基本情報6項目とICF付箋の候補を返す。DBには保存しない（画面で確認してから保存ボタン）。"""
        data = request.json or {}
        # 複数枚: images=[{data|image, mime_type}] / 旧形式: image + mime_type
        imgs = []
        for it in (data.get("images") or []):
            if not isinstance(it, dict):
                continue
            b = (it.get("data") or it.get("image") or "").strip()
            if b:
                imgs.append({"mime_type": it.get("mime_type") or "image/jpeg", "data": b})
        if not imgs:
            b = (data.get("image") or "").strip()
            if b:
                imgs.append({"mime_type": data.get("mime_type") or "image/jpeg", "data": b})
        if not imgs:
            return jsonify({"status": "error", "message": "画像がありません"}), 400
        imgs = imgs[:8]   # 上限8枚

        prompt = (
            "これは介護の『居宅サービス計画書（第1表・第2表など）』または"
            "『利用者情報シート・フェイスシート・アセスメント表』の画像です（複数ページのことがあります）。\n"
            "手書き・印刷どちらも読み取り、次のJSONのみで返してください（説明文・マークダウン禁止）。\n"
            "\n"
            "【厳守】\n"
            "・シートに実際に書かれている内容だけを使う。書かれていないことは推測・創作しない。\n"
            "・読み取れない項目は空文字\"\"、配列は[]。欄を埋めるために内容を作らない。\n"
            "・医療診断はしない（書かれている病名をそのまま写すのは可）。\n"
            "・【最重要】書かれている語をそのまま写すこと。言い換え・要約・きれいな表現への直しをしない。\n"
            "　例）『店の手伝い』→『店主』、『一部介助』→『介助』、\n"
            "　　　『大腿骨頸部』→『大腿骨頭部』、『左片麻痺』→『右片麻痺』は、いずれも書き換え禁止。\n"
            "　医学用語は一般的な言い回しに直さず、シートの字をそのまま写すこと。\n"
            "・特に次は1文字も変えない：左右の別（左／右）、数値、年月、部位名（頸部／頭部など）、\n"
            "　程度の語（全介助／一部介助／見守り／自立）、病名。\n"
            "　少しでも読み取りに自信が無い箇所は、推測で書かずその部分を省く。\n"
            "・複数ページに同じ人の情報がある場合、矛盾したら『よりはっきり書かれている方』を採用し、\n"
            "　勝手に折衷した表現を作らない。\n"
            "\n"
            "{\n"
            '  "medical_history":"既往歴・傷病名（発症年が書いてあれば併記）",\n'
            '  "family_structure":"家族構成・介護力（同居/別居、主介護者、続柄など）を文章で",\n'
            '  "job_history":"職歴",\n'
            '  "hobbies":"趣味・嗜好（好きな活動・音楽・食べ物など）",\n'
            '  "likes":"好きなもの",\n'
            '  "dislikes":"苦手・嫌いなもの",\n'
            '  "stickies":[{"zone":"activity","text":"屋内は伝い歩き","polarity":"can"}]\n'
            "}\n"
            "\n"
            "stickies は ICF（国際生活機能分類）の付箋候補。シートに書かれた本人の状態・生活歴・環境から作る。\n"
            "  zone: body=心身機能・身体構造 / activity=活動(日常動作) / participation=参加(役割・社会)\n"
            "        environment=環境因子(家族・住環境・支援) / personal=個人因子(性格・生活歴・趣味)\n"
            "  polarity: can(できる/良好) か cannot(できない/支障)。両方を拾う。\n"
            "  短い体言止めで1項目1事実。最大16項目。シートに根拠が無いものは作らない。"
        )
        try:
            from utils import get_generative_model
            model = get_generative_model()
            parts = [{"mime_type": im["mime_type"], "data": im["data"]} for im in imgs]
            parts.append(prompt)
            # halluc-guard-v2 と同じ方針で温度を下げ、読み取り内容の創作を抑える
            resp = model.generate_content(parts, generation_config={"temperature": 0.1})
            text = (resp.text or "").strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            obj = _json.loads(m.group()) if m else {}
        except Exception as e:
            return jsonify({"status": "error", "message": f"読み取り失敗: {e}"}), 500

        def sv(k):
            v = obj.get(k, "")
            return v.strip() if isinstance(v, str) else ""

        _zones = {"body", "activity", "participation", "environment", "personal"}
        stickies = []
        for it in (obj.get("stickies") or [])[:16]:
            if not isinstance(it, dict):
                continue
            txt = (str(it.get("text") or "")).strip()
            if not txt:
                continue
            stickies.append({
                "zone": it.get("zone") if it.get("zone") in _zones else "unsorted",
                "text": txt,
                "polarity": "cannot" if it.get("polarity") == "cannot" else "can",
            })

        return jsonify({"status": "success", "pages": len(imgs), "ocr": {
            "medical_history": sv("medical_history"),
            "family_structure": sv("family_structure"),
            "job_history":     sv("job_history"),
            "hobbies":         sv("hobbies"),
            "likes":           sv("likes"),
            "dislikes":        sv("dislikes"),
        }, "stickies": stickies})

    print("[patient_hub] 利用者情報ハブのルートを登録しました")
    return app
