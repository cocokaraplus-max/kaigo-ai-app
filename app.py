from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from supabase import create_client
from datetime import datetime, timedelta, time as dt_time, timezone
import os
import pytz
import re
import base64
import json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tasukaru-secret-key-change-in-production")

tokyo_tz = pytz.timezone('Asia/Tokyo')

# ==========================================
# 設定・DB接続
# ==========================================
def get_secret(key):
    return os.environ.get(key, "")

def get_supabase():
    url = get_secret("SUPABASE_URL").strip()
    key = get_secret("SUPABASE_KEY").strip()
    return create_client(url, key)

# ==========================================
# ログイン必須デコレータ
# ==========================================
from functools import wraps
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("f_code") or not session.get("my_name"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ==========================================
# 共通ヘルパー
# ==========================================
def parse_jst(iso_str, fmt='%H:%M'):
    try:
        dt = datetime.fromisoformat(str(iso_str).replace('Z', '+00:00'))
        return dt.astimezone(tokyo_tz).strftime(fmt)
    except:
        return str(iso_str)[11:16]

def parse_jst_date(iso_str):
    try:
        dt = datetime.fromisoformat(str(iso_str).replace('Z', '+00:00'))
        return dt.astimezone(tokyo_tz).date()
    except:
        return datetime.now(tokyo_tz).date()

def birth_to_wareki_text(birth_date_str):
    if not birth_date_str:
        return ""
    try:
        bd = datetime.strptime(str(birth_date_str), "%Y-%m-%d")
        y = bd.year
        if y >= 2019: era, base = "令和", 2018
        elif y >= 1989: era, base = "平成", 1988
        elif y >= 1926: era, base = "昭和", 1925
        elif y >= 1912: era, base = "大正", 1911
        else: era, base = "明治", 1867
        return f"{era}{y - base}年{bd.month}月{bd.day}日"
    except:
        return ""

def get_patients(supabase, f_code):
    try:
        res = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        patients = []
        for r in res.data:
            kana = r.get('user_kana') or ""
            chart = str(r['chart_number'])
            name = r['user_name']
            patients.append({
                "value": f"(No.{chart}) [{name}] {kana}",
                "label": f"(No.{chart}) [{name}] {kana}",
                "id": r["id"],
                "chart_number": chart,
                "user_name": name,
                "user_kana": kana,
                "birth_date": r.get("birth_date") or "",
                "birth_text": birth_to_wareki_text(r.get("birth_date")),
            })
        return patients
    except:
        return []

def get_birthday_users(supabase, f_code):
    try:
        now = datetime.now(tokyo_tz)
        res = supabase.table("patients").select("user_name, birth_date").eq("facility_code", f_code).execute()
        birthday_users = []
        for r in res.data:
            if not r.get("birth_date"):
                continue
            try:
                bd = datetime.strptime(str(r["birth_date"]), "%Y-%m-%d")
                if bd.month == now.month:
                    age = now.year - bd.year
                    if (now.month, now.day) < (bd.month, bd.day):
                        age -= 1
                    birthday_users.append({
                        "user_name": r["user_name"],
                        "month": bd.month,
                        "day": bd.day,
                        "age": age
                    })
            except:
                continue
        return sorted(birthday_users, key=lambda x: x["day"])
    except:
        return []

DAILY_SUMMARY_PROMPT = """以下は介護職員それぞれが記録した1日のケース記録です。
これらを介護職員間の申し送りとして、一つの文章にまとめてください。

【ルール】
・箇条書きや「・」は絶対に使わない。必ず一つながりの文章で書く
・利用者名などの主語は不要
・職員名は不要
・「支援内容」として記録されている事柄は必ず要約して含める
・変化・気になる点・注意事項を優先して記載
・です・ます調で書く

【記録】
{records}
"""

# ==========================================
# ページルート
# ==========================================

@app.route('/')
def index():
    if session.get("f_code"):
        return redirect(url_for("top"))
    return redirect(url_for("login"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    saved_f_code = session.get("saved_f_code", "")

    if request.method == 'POST':
        f_code = request.form.get("f_code", "").strip()
        password = request.form.get("password", "").strip()

        if not f_code or not password:
            error = "施設コードとパスワードを入力してください。"
        else:
            try:
                supabase = get_supabase()
                fac = supabase.table("facilities").select(
                    "facility_name,is_active,expires_at,admin_password"
                ).eq("facility_code", f_code).execute()

                if not fac.data:
                    error = "この施設コードは登録されていません。"
                else:
                    fac_data = fac.data[0]
                    if not fac_data.get("is_active", True):
                        error = "この施設コードは無効です。"
                    else:
                        expires = datetime.fromisoformat(
                            str(fac_data.get("expires_at", "")).replace("Z", "+00:00")
                        )
                        if expires < datetime.now(timezone.utc):
                            error = "この施設コードの有効期限が切れています。"
                        else:
                            import hashlib
                            def verify_password(pw, hashed):
                                return hashlib.sha256(pw.encode()).hexdigest() == hashed

                            admin_pw = fac_data.get("admin_password", "")
                            staff = supabase.table("staffs").select("*").eq(
                                "facility_code", f_code
                            ).eq("is_active", True).execute()

                            matched_staff = None
                            for s in staff.data:
                                if verify_password(password, s["password_hash"]):
                                    matched_staff = s
                                    break

                            is_admin = (password == admin_pw)
                            if not is_admin and not matched_staff:
                                error = "パスワードが違います。"
                            else:
                                my_name = "管理者" if is_admin else matched_staff["staff_name"]
                                session["f_code"] = f_code
                                session["my_name"] = my_name
                                session["saved_f_code"] = f_code
                                return redirect(url_for("top"))
            except Exception as e:
                error = f"ログイン中にエラーが発生しました: {e}"

    return render_template("login.html", error=error, saved_f_code=saved_f_code)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    success = None
    if request.method == 'POST':
        facility_code = request.form.get("facility_code", "").strip()
        facility_name = request.form.get("facility_name", "").strip()
        admin_email = request.form.get("admin_email", "").strip()
        if not facility_code or not facility_name or not admin_email:
            error = "全項目を入力してください。"
        else:
            try:
                import random, string
                supabase = get_supabase()
                existing = supabase.table("facilities").select("facility_code").eq("facility_code", facility_code).execute()
                if existing.data:
                    error = "この施設コードはすでに使われています。"
                else:
                    temp_pw = "".join(random.choices(string.ascii_letters + string.digits, k=10))
                    supabase.table("facilities").insert({
                        "facility_code": facility_code,
                        "facility_name": facility_name,
                        "admin_password": temp_pw,
                        "plan_limit": 99999,
                        "is_active": True
                    }).execute()
                    success = "登録完了！メールをご確認ください。"
            except Exception as e:
                error = f"登録エラー: {e}"
    return render_template("register.html", error=error, success=success)

@app.route('/top')
@login_required
def top():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()

    hist_limit = 30
    try:
        res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        if res_l.data:
            hist_limit = int(res_l.data[0]['value'])
    except:
        pass

    records = []
    try:
        res_hist = supabase.table("records").select(
            "id, user_name, staff_name, created_at"
        ).eq("facility_code", f_code).order("created_at", desc=True).limit(hist_limit * 2).execute()
        if res_hist.data:
            filtered = [r for r in res_hist.data if r['staff_name'] != "AI統合記録"][:hist_limit]
            for r in filtered:
                records.append({
                    "user_name": r["user_name"],
                    "time": parse_jst(r["created_at"]),
                    "date": str(parse_jst_date(r["created_at"])),
                })
    except:
        pass

    return render_template("top.html", f_code=f_code, my_name=my_name, records=records, birthday_users=get_birthday_users(supabase, f_code))

@app.route('/input', methods=['GET', 'POST'])
@login_required
def input_view():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    patients = get_patients(supabase, f_code)
    today = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
    error = None
    success = None
    content = ""
    selected_patient = ""

    if request.method == 'POST':
        sel = request.form.get("patient", "")
        record_date = request.form.get("record_date", today)
        content = request.form.get("content", "").strip()
        photos = request.files.getlist("photos")

        if not sel or sel == "" or not content:
            error = "利用者と内容を入力してください。"
        else:
            try:
                m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                if m:
                    from utils import upload_images_to_supabase
                    image_urls = []
                    if photos and photos[0].filename:
                        image_urls = upload_images_to_supabase(supabase, photos, f_code)

                    from datetime import time as dt_time
                    record_time = datetime.now(tokyo_tz).time()
                    dt_record = tokyo_tz.localize(datetime.combine(
                        datetime.strptime(record_date, "%Y-%m-%d").date(),
                        record_time
                    ))
                    supabase.table("records").insert({
                        "facility_code": f_code,
                        "chart_number": m.group(1),
                        "user_name": m.group(2),
                        "staff_name": my_name,
                        "content": content,
                        "created_at": dt_record.isoformat(),
                        "image_urls": image_urls if image_urls else None
                    }).execute()
                    content = ""
                    selected_patient = ""
                    return redirect(url_for("daily_view"))
            except Exception as e:
                error = f"保存に失敗しました: {e}"

    return render_template("input.html",
        patients=patients, today=today, content=content,
        selected_patient=selected_patient, error=error, success=success
    )

@app.route('/daily_view')
@login_required
def daily_view():
    f_code = session["f_code"]
    my_name = session["my_name"]
    is_admin = session.get("admin_authenticated", False)
    supabase = get_supabase()

    selected_date_str = request.args.get("date", datetime.now(tokyo_tz).strftime("%Y-%m-%d"))
    target_user = request.args.get("user", "")

    try:
        selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    except:
        selected_date = datetime.now(tokyo_tz).date()

    date_label = selected_date.strftime("%-m月%-d日")
    t_start = tokyo_tz.localize(datetime.combine(selected_date, dt_time.min))

    records = {}
    try:
        res = supabase.table("records").select("*").eq("facility_code", f_code).gte(
            "created_at", t_start.isoformat()
        ).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at").execute()

        if res.data:
            for r in res.data:
                user = r["user_name"]
                if user not in records:
                    records[user] = {"ai_record": None, "normal_records": []}
                if r["staff_name"] == "AI統合記録":
                    records[user]["ai_record"] = r
                else:
                    r["time"] = parse_jst(r["created_at"])
                    r["can_edit"] = (str(r["staff_name"]) == str(my_name)) or is_admin
                    records[user]["normal_records"].append(r)
    except Exception as e:
        pass

    return render_template("daily_view.html",
        selected_date=selected_date_str,
        date_label=date_label,
        target_user=target_user,
        records=records,
        is_admin=is_admin
    )

@app.route('/birthday')
@login_required
def birthday():
    f_code = session["f_code"]
    supabase = get_supabase()
    now = datetime.now(tokyo_tz)

    try:
        res = supabase.table("patients").select("user_name, user_kana, chart_number, birth_date").eq("facility_code", f_code).execute()
    except:
        res = type('obj', (object,), {'data': []})()

    def calc_numerology(birth_str):
        if not birth_str:
            return None
        digits = [int(c) for c in birth_str.replace('-', '') if c.isdigit()]
        s = sum(digits)
        while s > 9 and s not in [11, 22, 33]:
            s = sum(int(c) for c in str(s))
        return s

    months_data = {}
    patients_list = []
    for r in res.data:
        chart = str(r.get('chart_number', ''))
        kana = r.get('user_kana') or ''
        patients_list.append({
            "user_name": r["user_name"],
            "user_kana": kana,
            "chart_number": chart,
            "birth_date": r.get("birth_date") or "",
        })
        if not r.get("birth_date"):
            continue
        try:
            bd = datetime.strptime(str(r["birth_date"]), "%Y-%m-%d")
            age = now.year - bd.year
            if (now.month, now.day) < (bd.month, bd.day):
                age -= 1
            is_today = (bd.month == now.month and bd.day == now.day)
            wareki = birth_to_wareki_text(r["birth_date"])
            num = calc_numerology(r["birth_date"])
            m = bd.month
            if m not in months_data:
                months_data[m] = []
            months_data[m].append({
                "user_name": r["user_name"],
                "month": bd.month,
                "day": bd.day,
                "age": age,
                "wareki": wareki,
                "is_today": is_today,
                "numerology": num,
                "birth_iso": r["birth_date"],
            })
        except:
            continue

    all_birthdays = []
    for i in range(12):
        m = (now.month - 1 + i) % 12 + 1
        if m in months_data:
            users = sorted(months_data[m], key=lambda x: x["day"])
            all_birthdays.append({
                "month": m,
                "is_current": (m == now.month),
                "users": users
            })

    return render_template("birthday.html",
        all_birthdays=all_birthdays,
        patients=patients_list
    )

@app.route('/history')
@login_required
def history():
    f_code = session["f_code"]
    supabase = get_supabase()
    patients = get_patients(supabase, f_code)
    now = datetime.now(tokyo_tz)
    months = []
    for i in range(6):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12; y -= 1
        months.append({"value": f"{y}-{m:02d}", "label": f"{y}年{m:02d}月"})
    return render_template("history.html", patients=patients, months=months, result="")

@app.route('/admin')
@login_required
def admin():
    f_code = session["f_code"]
    my_name = session["my_name"]
    authenticated = session.get("admin_authenticated", False)
    supabase = get_supabase()

    patients = []
    blocked = []
    staff_list = []
    hist_limit = 30

    if authenticated:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            patients = res_p.data
        except: pass
        try:
            res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
            blocked = res_b.data
        except: pass
        try:
            res_s = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
            if res_s.data:
                names = sorted(set([r['staff_name'] for r in res_s.data if r['staff_name'] and r['staff_name'] != "AI統合記録"]))
                for name in names:
                    is_b = len(supabase.table("blocked_devices").select("id").eq("staff_name", name).eq("facility_code", f_code).eq("is_active", True).execute().data) > 0
                    staff_list.append({"name": name, "blocked": is_b})
        except: pass
        try:
            res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
            if res_l.data: hist_limit = int(res_l.data[0]['value'])
        except: pass

    return render_template("admin.html",
        authenticated=authenticated,
        patients=patients,
        blocked=blocked,
        staff_list=staff_list,
        hist_limit=hist_limit,
        error=None
    )

# ==========================================
# API エンドポイント
# ==========================================

@app.route('/api/transcribe', methods=['POST'])
@login_required
def api_transcribe():
    try:
        data = request.json
        from utils import get_generative_model
        model = get_generative_model()
        prompt = "以下の音声を介護記録として文章に起こしてください。\n【ルール】\n・話した内容をできるだけ忠実に文章化する\n・「あー」「えー」「えっと」などのフィラーは省略する\n・職員名や「利用者様は」などの主語は不要\n・です・ます調に整える\n・事実のみを記載し、余計な装飾は不要"
        audio_bytes = base64.b64decode(data["audio_data"])
        contents = [prompt, {"mime_type": data["audio_mime"], "data": audio_bytes}]
        result = model.generate_content(contents)
        return jsonify({"text": result.text.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/generate_daily', methods=['POST'])
@login_required
def api_generate_daily():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        user = data["user"]
        selected_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        t_start = tokyo_tz.localize(datetime.combine(selected_date, dt_time.min))
        res = supabase.table("records").select("*").eq("facility_code", f_code).eq(
            "user_name", user
        ).gte("created_at", t_start.isoformat()).lt(
            "created_at", (t_start + timedelta(days=1)).isoformat()
        ).execute()
        normal_recs = [r for r in res.data if r["staff_name"] != "AI統合記録"]
        if not normal_recs:
            return jsonify({"status": "error", "message": "個別記録がありません"})
        recs_text = "\n".join([f"【{r['staff_name']}】{r['content']}" for r in normal_recs])
        from utils import get_generative_model
        model = get_generative_model()
        summary = model.generate_content([DAILY_SUMMARY_PROMPT.format(records=recs_text)]).text
        c_num = normal_recs[0]["chart_number"]
        dt = tokyo_tz.localize(datetime.combine(selected_date, dt_time(23, 59, 59)))
        supabase.table("records").insert({
            "facility_code": f_code, "chart_number": c_num, "user_name": user,
            "staff_name": "AI統合記録", "content": summary, "created_at": dt.isoformat()
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/regenerate_daily', methods=['POST'])
@login_required
def api_regenerate_daily():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        user = data["user"]
        selected_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        t_start = tokyo_tz.localize(datetime.combine(selected_date, dt_time.min))
        res = supabase.table("records").select("*").eq("facility_code", f_code).eq(
            "user_name", user
        ).gte("created_at", t_start.isoformat()).lt(
            "created_at", (t_start + timedelta(days=1)).isoformat()
        ).execute()
        normal_recs = [r for r in res.data if r["staff_name"] != "AI統合記録"]
        recs_text = "\n".join([f"【{r['staff_name']}】{r['content']}" for r in normal_recs])
        from utils import get_generative_model
        model = get_generative_model()
        summary = model.generate_content([DAILY_SUMMARY_PROMPT.format(records=recs_text)]).text
        c_num = normal_recs[0]["chart_number"]
        dt = tokyo_tz.localize(datetime.combine(selected_date, dt_time(23, 59, 59)))
        supabase.table("records").delete().eq("id", data["ai_record_id"]).execute()
        supabase.table("records").insert({
            "facility_code": f_code, "chart_number": c_num, "user_name": user,
            "staff_name": "AI統合記録", "content": summary, "created_at": dt.isoformat()
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_record', methods=['POST'])
@login_required
def api_update_record():
    try:
        data = request.json
        supabase = get_supabase()
        supabase.table("records").update({"content": data["content"]}).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/delete_record', methods=['POST'])
@login_required
def api_delete_record():
    try:
        data = request.json
        supabase = get_supabase()
        supabase.table("records").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/generate_monitoring', methods=['POST'])
@login_required
def api_generate_monitoring():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        patient_val = data["patient"]
        month_val = data["month"]
        char_limit = data["char_limit"]
        name_match = re.search(r'\[(.*?)\]', patient_val)
        u_name = name_match.group(1) if name_match else ""
        y, m = map(int, month_val.split("-"))
        s_date = tokyo_tz.localize(datetime(y, m, 1))
        e_date = (s_date + timedelta(days=32)).replace(day=1)
        res = supabase.table("records").select("content, staff_name").eq(
            "facility_code", f_code
        ).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt(
            "created_at", e_date.isoformat()
        ).execute()
        if not res.data:
            return jsonify({"error": "対象期間に記録がありません。"})
        filtered = [r['content'] for r in res.data if r['staff_name'] != "AI統合記録"]
        recs = "\n".join(filtered)
        from utils import get_generative_model
        model = get_generative_model()
        prompt = f"以下の介護記録を報告口調で一つの文章にまとめて。『支援内容』として記録されている事柄は積極的に盛り込んでください。職員名や主語は不要。箇条書きは使わず一つの文章で書いてください。おおよそ{char_limit}程度で作成してください。\n\n{recs}"
        result = model.generate_content([prompt]).text
        return jsonify({"text": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin_login', methods=['POST'])
@login_required
def api_admin_login():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res.data[0]['value'] if res.data else "8888"
        if data["password"] == cur_pw:
            session["admin_authenticated"] = True
            return jsonify({"status": "success"})
        return jsonify({"status": "error"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/admin_logout', methods=['POST'])
def api_admin_logout():
    session["admin_authenticated"] = False
    return jsonify({"status": "success"})

@app.route('/api/add_patient', methods=['POST'])
@login_required
def api_add_patient():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        insert_data = {
            "facility_code": f_code,
            "chart_number": data["chart"],
            "user_name": data["name"],
            "user_kana": data["kana"]
        }
        if data.get("birth"):
            insert_data["birth_date"] = data["birth"]
        supabase.table("patients").insert(insert_data).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/delete_patient', methods=['POST'])
@login_required
def api_delete_patient():
    try:
        data = request.json
        supabase = get_supabase()
        supabase.table("patients").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/update_patient', methods=['POST'])
@login_required
def api_update_patient():
    try:
        data = request.json
        supabase = get_supabase()
        update_data = {
            "chart_number": data["chart"],
            "user_name": data["name"],
            "user_kana": data["kana"]
        }
        if data.get("birth"):
            update_data["birth_date"] = data["birth"]
        supabase.table("patients").update(update_data).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/update_password', methods=['POST'])
@login_required
def api_update_password():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("admin_settings").upsert({
            "facility_code": f_code, "key": "admin_password", "value": data["password"]
        }, on_conflict="facility_code,key").execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/update_hist_limit', methods=['POST'])
@login_required
def api_update_hist_limit():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("admin_settings").upsert({
            "facility_code": f_code, "key": "history_limit", "value": str(data["limit"])
        }, on_conflict="facility_code,key").execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/block_staff', methods=['POST'])
@login_required
def api_block_staff():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("blocked_devices").insert({
            "staff_name": data["name"], "facility_code": f_code,
            "is_active": True, "device_id": "NAME_LOCK"
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/unblock_device', methods=['POST'])
@login_required
def api_unblock_device():
    try:
        data = request.json
        supabase = get_supabase()
        supabase.table("blocked_devices").update({"is_active": False}).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)