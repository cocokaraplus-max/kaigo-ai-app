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

def send_email(to_email, subject, html_content):
    """SendGridでメール送信"""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        api_key = get_secret("SENDGRID_API_KEY")
        from_email = get_secret("SENDGRID_FROM_EMAIL")
        if not api_key or not from_email:
            return False
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            html_content=html_content
        )
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ==========================================
# ログイン必須デコレータ
# ==========================================
from functools import wraps
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("f_code") or not session.get("my_name"):
            if request.args.get("partial"):
                return jsonify({"redirect": "/login"})
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def render(template, **kwargs):
    """partialパラメータがあればJSON形式でコンテンツのみ返す"""
    if request.args.get("partial"):
        import re as _re
        html = render_template(template, **kwargs)

        # <style>タグを抽出（base.htmlのものは除く）
        styles = _re.findall(r'<style[^>]*>(.*?)</style>', html, _re.DOTALL)
        # 最初のstyleはbase.htmlの共通CSS、2つ目以降がページ固有
        page_styles = styles[1:] if len(styles) > 1 else []
        style = '<style>' + '\n'.join(page_styles) + '</style>' if page_styles else ''

        # page-wrapperの中身を抽出（終了タグまで）
        content_match = _re.search(
            r'<div class=["\']page-wrapper["\'][^>]*>(.*?)</div>\s*\n\s*\n\s*(?:<!--.*?-->)?\s*\{%',
            html, _re.DOTALL
        )
        if not content_match:
            # 別パターン：page-wrapperからnavタグまで
            content_match = _re.search(
                r'<div class=["\']page-wrapper["\'][^>]*>(.*?)</div>(?:\s|\n)*<(?:nav|script)',
                html, _re.DOTALL
            )
        if not content_match:
            # フォールバック：bodyの最初のdivの中身
            content_match = _re.search(
                r'<div class=["\']page-wrapper["\'][^>]*>(.*)',
                html, _re.DOTALL
            )
            if content_match:
                raw = content_match.group(1)
                # page-wrapperの閉じタグを探す
                depth = 1
                pos = 0
                result = []
                while pos < len(raw) and depth > 0:
                    open_tag = raw.find('<div', pos)
                    close_tag = raw.find('</div>', pos)
                    if close_tag == -1:
                        break
                    if open_tag != -1 and open_tag < close_tag:
                        depth += 1
                        result.append(raw[pos:open_tag + 4])
                        pos = open_tag + 4
                    else:
                        depth -= 1
                        if depth > 0:
                            result.append(raw[pos:close_tag + 6])
                        else:
                            result.append(raw[pos:close_tag])
                        pos = close_tag + 6
                content = ''.join(result).strip()
            else:
                content = html
        else:
            content = content_match.group(1).strip()

        # <script>タグを抽出（SPAルーター以外を全部結合）
        scripts = _re.findall(r'<script[^>]*>(.*?)</script>', html, _re.DOTALL)
        # SPAルーターを含まないスクリプトのみ全部結合
        page_scripts = [s for s in scripts if 'navigateTo' not in s and 'SPAルーター' not in s]
        script = '<script>' + '\n'.join(page_scripts) + '</script>' if page_scripts else ''

        return jsonify({
            "style": style,
            "content": content,
            "script": script,
        })
    return render_template(template, **kwargs)

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

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    error = None
    success = False
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            error = 'メールアドレスを入力してください'
        else:
            try:
                import secrets as _sec
                supabase = get_supabase()
                # メールアドレスからスタッフを検索
                res = supabase.table('staffs').select('id,staff_name,facility_code').eq('email', email).eq('is_active', True).execute()
                if res.data:
                    staff = res.data[0]
                    token = _sec.token_urlsafe(32)
                    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                    # 既存トークン削除
                    supabase.table('password_resets').delete().eq('staff_id', staff['id']).execute()
                    supabase.table('password_resets').insert({
                        'facility_code': staff['facility_code'],
                        'staff_id': staff['id'],
                        'token': token,
                        'expires_at': expires_at
                    }).execute()
                    reset_url = request.host_url.rstrip('/') + f'/new_password?token={token}'
                    html = f"""
                    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px;">
                        <h2 style="color:#1a73e8;">パスワードリセット</h2>
                        <p>{staff['staff_name']} さん、パスワードリセットのリクエストを受け付けました。</p>
                        <p>以下のボタンから新しいパスワードを設定してください（有効期限：30分）：</p>
                        <a href="{reset_url}" style="display:inline-block;background:#1a73e8;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0;">パスワードを再設定する</a>
                        <p style="font-size:0.85rem;color:#666;">このメールに心当たりがない場合は無視してください。</p>
                    </div>
                    """
                    send_email(email, '【TASUKARU】パスワードリセット', html)
                # メールが登録されていなくても同じメッセージ（セキュリティ）
                success = True
            except Exception as e:
                error = f'エラーが発生しました: {e}'
    return render_template('reset_password.html', error=error, success=success)

@app.route('/new_password', methods=['GET', 'POST'])
def new_password():
    token = request.args.get('token') or request.form.get('token')
    if not token:
        return render_template('new_password.html', expired=True)
    try:
        supabase = get_supabase()
        res = supabase.table('password_resets').select('*').eq('token', token).execute()
        if not res.data:
            return render_template('new_password.html', expired=True)
        row = res.data[0]
        expires = datetime.fromisoformat(str(row['expires_at']).replace('Z', '+00:00'))
        if expires < datetime.now(timezone.utc):
            return render_template('new_password.html', expired=True)
        if request.method == 'POST':
            import hashlib
            password = request.form.get('password', '')
            password2 = request.form.get('password2', '')
            if len(password) < 4:
                return render_template('new_password.html', expired=False, token=token, error='パスワードは4文字以上にしてください', success=False)
            if password != password2:
                return render_template('new_password.html', expired=False, token=token, error='パスワードが一致しません', success=False)
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            supabase.table('staffs').update({'password_hash': pw_hash}).eq('id', row['staff_id']).execute()
            supabase.table('password_resets').delete().eq('token', token).execute()
            return render_template('new_password.html', expired=False, token=token, error=None, success=True)
        return render_template('new_password.html', expired=False, token=token, error=None, success=False)
    except Exception as e:
        return render_template('new_password.html', expired=True)

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

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
                    # 管理者にメール送信
                    login_url = request.host_url.rstrip('/') + '/login'
                    html = f"""
                    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px;">
                        <h2 style="color:#1a73e8;">TASUKARUへようこそ！</h2>
                        <p>{facility_name} の登録が完了しました。</p>
                        <div style="background:#f8f9fa;border-radius:10px;padding:16px;margin:20px 0;">
                            <p><b>施設コード：</b>{facility_code}</p>
                            <p><b>管理者パスワード：</b>{temp_pw}</p>
                        </div>
                        <p>以下のURLからログインしてください：</p>
                        <a href="{login_url}" style="display:inline-block;background:#1a73e8;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">ログインする</a>
                        <p style="margin-top:20px;font-size:0.85rem;color:#666;">セキュリティのため、ログイン後にパスワードを変更することをお勧めします。</p>
                    </div>
                    """
                    send_email(admin_email, f"【TASUKARU】{facility_name} 登録完了", html)
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

    return render("top.html", f_code=f_code, my_name=my_name, records=records, birthday_users=get_birthday_users(supabase, f_code))

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

    return render("input.html",
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

    # 当月の記録がある日付リストを取得（カレンダーのドット表示用）
    record_dates = []
    try:
        month_start = tokyo_tz.localize(datetime(selected_date.year, selected_date.month, 1))
        if selected_date.month == 12:
            next_month = tokyo_tz.localize(datetime(selected_date.year + 1, 1, 1))
        else:
            next_month = tokyo_tz.localize(datetime(selected_date.year, selected_date.month + 1, 1))
        month_res = supabase.table("records").select("created_at").eq("facility_code", f_code).gte(
            "created_at", month_start.isoformat()
        ).lt("created_at", next_month.isoformat()).execute()
        if month_res.data:
            dates_set = set()
            for r in month_res.data:
                d = parse_jst_date(r["created_at"])
                dates_set.add(d.strftime("%Y-%m-%d"))
            record_dates = list(dates_set)
    except Exception as e:
        pass

    return render("daily_view.html",
        selected_date=selected_date_str,
        date_label=date_label,
        target_user=target_user,
        records=records,
        is_admin=is_admin,
        record_dates=record_dates
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

    return render("birthday.html",
        all_birthdays=all_birthdays,
        patients=patients_list
    )

# ==========================================
# トーク (LINE風チャット)
# ==========================================

# スタッフ名からアイコンカラーを決定（固定カラーパレット）
AVATAR_COLORS = [
    "#1a73e8","#34a853","#ea4335","#fbbc04","#9c27b0",
    "#00bcd4","#ff5722","#607d8b","#e91e63","#4caf50",
]
def staff_color(name):
    return AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]

def staff_initial(name):
    return name[:1] if name else "?"

def get_staff_icons(supabase, f_code):
    """施設の全スタッフアイコン情報を取得 {staff_name: {color, initial, emoji}}"""
    icons = {}
    try:
        res = supabase.table("staffs").select("staff_name,icon_emoji").eq("facility_code", f_code).eq("is_active", True).execute()
        for s in (res.data or []):
            name = s["staff_name"]
            icons[name] = {
                "color": staff_color(name),
                "initial": staff_initial(name),
                "emoji": s.get("icon_emoji") or "",
            }
    except:
        pass
    return icons

def staff_icon_data(icons, name):
    """get_staff_iconsの結果から1名分のアイコンデータを取得（なければデフォルト）"""
    if name in icons:
        return icons[name]
    return {"color": staff_color(name), "initial": staff_initial(name), "emoji": ""}

@app.route('/chat')
@login_required
def chat():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    # スタッフアイコン情報を一括取得
    icons = get_staff_icons(supabase, f_code)
    rooms = []
    try:
        mem_res = supabase.table("chat_members").select("room_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        room_ids = [r["room_id"] for r in (mem_res.data or [])]
        if room_ids:
            room_res = supabase.table("chat_rooms").select("*").in_("id", room_ids).order("last_message_at", desc=True).execute()
            for room in (room_res.data or []):
                rid = room["id"]
                is_group = room["is_group"]
                if is_group:
                    name = room.get("name") or "グループ"
                    other_color = "#1a73e8"
                    other_initial = "G"
                    other_emoji = ""
                    # グループ：メンバー最大3人分のアイコンをスタックで表示用
                    all_mem = supabase.table("chat_members").select("staff_name").eq("room_id", rid).execute()
                    group_members_icons = [staff_icon_data(icons, m["staff_name"]) | {"staff_name": m["staff_name"]} for m in (all_mem.data or [])]
                else:
                    all_mem = supabase.table("chat_members").select("staff_name").eq("room_id", rid).execute()
                    others = [m["staff_name"] for m in (all_mem.data or []) if m["staff_name"] != my_name]
                    other_name = others[0] if others else "?"
                    name = other_name
                    icon = staff_icon_data(icons, other_name)
                    other_color = icon["color"]
                    other_initial = icon["initial"]
                    other_emoji = icon["emoji"]
                    group_members_icons = []
                last_msg_res = supabase.table("chat_messages").select("content,created_at").eq("room_id", rid).order("created_at", desc=True).limit(1).execute()
                last_msg = ""
                last_time = ""
                if last_msg_res.data:
                    lm = last_msg_res.data[0]
                    last_msg = lm["content"][:30] + ("…" if len(lm["content"]) > 30 else "")
                    dt = datetime.fromisoformat(str(lm["created_at"]).replace("Z", "+00:00")).astimezone(tokyo_tz)
                    today = datetime.now(tokyo_tz).date()
                    last_time = dt.strftime("%H:%M") if dt.date() == today else dt.strftime("%-m/%-d")
                my_mem = supabase.table("chat_members").select("last_read_at").eq("room_id", rid).eq("staff_name", my_name).execute()
                unread = 0
                if my_mem.data:
                    last_read = my_mem.data[0].get("last_read_at")
                    if last_read:
                        unread_res = supabase.table("chat_messages").select("id", count="exact").eq("room_id", rid).gt("created_at", last_read).neq("staff_name", my_name).execute()
                        unread = unread_res.count or 0
                    else:
                        unread_res = supabase.table("chat_messages").select("id", count="exact").eq("room_id", rid).neq("staff_name", my_name).execute()
                        unread = unread_res.count or 0
                rooms.append({
                    "id": rid,
                    "name": name,
                    "is_group": is_group,
                    "other_color": other_color,
                    "other_initial": other_initial,
                    "other_emoji": other_emoji,
                    "group_members_icons": group_members_icons,
                    "last_msg": last_msg,
                    "last_time": last_time,
                    "unread": unread,
                })
    except Exception as e:
        print(f"chat rooms error: {e}")

    # スタッフ一覧（自分以外）- アイコン情報付き
    staffs = []
    for name, icon in icons.items():
        if name != my_name:
            staffs.append({
                "staff_name": name,
                "color": icon["color"],
                "initial": icon["initial"],
                "emoji": icon["emoji"],
            })

    return render("chat_rooms.html", rooms=rooms, staffs=staffs)

@app.route('/chat/<room_id>')
@login_required
def chat_room(room_id):
    f_code = session["f_code"]
    my_name = session["my_name"]
    is_admin = session.get("admin_authenticated", False)
    supabase = get_supabase()

    # 参加確認
    mem_check = supabase.table("chat_members").select("id").eq("room_id", room_id).eq("facility_code", f_code).eq("staff_name", my_name).execute()
    if not mem_check.data:
        return redirect(url_for("chat"))

    room_res = supabase.table("chat_rooms").select("*").eq("id", room_id).execute()
    if not room_res.data:
        return redirect(url_for("chat"))
    room = room_res.data[0]
    is_group = room["is_group"]

    # スタッフアイコン情報を一括取得
    icons = get_staff_icons(supabase, f_code)

    # ルーム名・アイコン
    if is_group:
        room_name = room.get("name") or "グループ"
        other_color = "#1a73e8"
        other_initial = "G"
        other_emoji = ""
    else:
        all_mem = supabase.table("chat_members").select("staff_name").eq("room_id", room_id).execute()
        others = [m["staff_name"] for m in (all_mem.data or []) if m["staff_name"] != my_name]
        other_name = others[0] if others else "?"
        room_name = other_name
        icon = staff_icon_data(icons, other_name)
        other_color = icon["color"]
        other_initial = icon["initial"]
        other_emoji = icon["emoji"]

    # メンバー一覧（グループ用）
    members = []
    if is_group:
        all_mem2 = supabase.table("chat_members").select("staff_name").eq("room_id", room_id).execute()
        for m in (all_mem2.data or []):
            ic = staff_icon_data(icons, m["staff_name"])
            members.append({"staff_name": m["staff_name"], "color": ic["color"], "initial": ic["initial"], "emoji": ic["emoji"]})

    # メッセージ取得
    msg_res = supabase.table("chat_messages").select("*").eq("room_id", room_id).order("created_at").execute()
    messages = []
    # 全メンバーのlast_read_at取得
    mem_reads = {}
    try:
        all_reads = supabase.table("chat_members").select("staff_name,last_read_at").eq("room_id", room_id).execute()
        for m in (all_reads.data or []):
            mem_reads[m["staff_name"]] = m.get("last_read_at")
    except:
        pass

    for r in (msg_res.data or []):
        dt = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")).astimezone(tokyo_tz)
        today = datetime.now(tokyo_tz).date()
        # 既読者リスト（自分のメッセージのみ・自分以外で既読済みの人）
        readers = []
        if r["staff_name"] == my_name:
            for mn, last_read in mem_reads.items():
                if mn == my_name:
                    continue
                if last_read and last_read >= r["created_at"]:
                    ic = staff_icon_data(icons, mn)
                    readers.append({"staff_name": mn, "color": ic["color"], "initial": ic["initial"], "emoji": ic["emoji"]})
        ic = staff_icon_data(icons, r["staff_name"])
        messages.append({
            "id": r["id"],
            "staff_name": r["staff_name"],
            "content": r["content"],
            "is_mine": r["staff_name"] == my_name,
            "color": ic["color"],
            "initial": ic["initial"],
            "emoji": ic["emoji"],
            "date_label": dt.strftime("%-m月%-d日") if dt.date() != today else "今日",
            "time_label": dt.strftime("%H:%M"),
            "readers": readers,
        })

    return render("chat_room.html",
        room_id=room_id,
        room_name=room_name,
        is_group=is_group,
        other_color=other_color,
        other_initial=other_initial,
        other_emoji=other_emoji,
        members=members,
        messages=messages,
        my_name=my_name,
        is_admin=is_admin,
    )

@app.route('/api/create_room', methods=['POST'])
@login_required
def api_create_room():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        room_type = data.get("type", "dm")
        members = data.get("members", [])
        if not members:
            return jsonify({"status": "error", "message": "メンバーを選択してください"})

        all_members = list(set([my_name] + members))
        is_group = (room_type == "group")

        # DM：既存ルームチェック（同じ2人の1:1が既にあれば再利用）
        if not is_group and len(all_members) == 2:
            my_rooms = supabase.table("chat_members").select("room_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
            my_room_ids = [r["room_id"] for r in (my_rooms.data or [])]
            other_rooms = supabase.table("chat_members").select("room_id").eq("facility_code", f_code).eq("staff_name", members[0]).execute()
            other_room_ids = [r["room_id"] for r in (other_rooms.data or [])]
            common = set(my_room_ids) & set(other_room_ids)
            for rid in common:
                r_check = supabase.table("chat_rooms").select("is_group").eq("id", rid).execute()
                if r_check.data and not r_check.data[0]["is_group"]:
                    return jsonify({"status": "success", "room_id": rid})

        # 新規ルーム作成
        room_data = {
            "facility_code": f_code,
            "is_group": is_group,
            "name": data.get("group_name", "") if is_group else None,
            "created_by": my_name,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        }
        room_res = supabase.table("chat_rooms").insert(room_data).execute()
        room_id = room_res.data[0]["id"]

        # メンバー追加
        for m in all_members:
            supabase.table("chat_members").insert({
                "room_id": room_id,
                "facility_code": f_code,
                "staff_name": m,
            }).execute()

        return jsonify({"status": "success", "room_id": room_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/send_room_message', methods=['POST'])
@login_required
def api_send_room_message():
    try:
        data = request.json
        my_name = session["my_name"]
        f_code = session["f_code"]
        supabase = get_supabase()
        room_id = data["room_id"]
        # 参加確認
        mem_check = supabase.table("chat_members").select("id").eq("room_id", room_id).eq("staff_name", my_name).execute()
        if not mem_check.data:
            return jsonify({"status": "error"}), 403
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("chat_messages").insert({
            "room_id": room_id,
            "facility_code": f_code,
            "staff_name": my_name,
            "content": data["content"],
        }).execute()
        supabase.table("chat_rooms").update({"last_message_at": now_iso}).eq("id", room_id).execute()
        # 送信者は既読済みにする
        supabase.table("chat_members").update({"last_read_at": now_iso}).eq("room_id", room_id).eq("staff_name", my_name).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/mark_read', methods=['POST'])
@login_required
def api_mark_read():
    try:
        data = request.json
        my_name = session["my_name"]
        supabase = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("chat_members").update({"last_read_at": now_iso}).eq("room_id", data["room_id"]).eq("staff_name", my_name).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/delete_room_message', methods=['POST'])
@login_required
def api_delete_room_message():
    try:
        data = request.json
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False)
        supabase = get_supabase()
        msg = supabase.table("chat_messages").select("staff_name").eq("id", data["id"]).execute()
        if msg.data and (msg.data[0]["staff_name"] == my_name or is_admin):
            supabase.table("chat_messages").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

# 旧APIの後方互換（既存messagesテーブルへのアクセスは念のため残す）
@app.route('/api/send_message', methods=['POST'])
@login_required
def api_send_message():
    return jsonify({"status": "error", "message": "deprecated"}), 410

@app.route('/api/delete_message', methods=['POST'])
@login_required
def api_delete_message():
    return jsonify({"status": "error", "message": "deprecated"}), 410

# ==========================================
# 評価（個別機能訓練 月次評価報告書）
# ==========================================

@app.route('/assessment')
@login_required
def assessment():
    f_code = session["f_code"]
    supabase = get_supabase()
    patients = get_patients(supabase, f_code)
    # patientsにdisease_name/care_manager/training_goalを追加
    try:
        res = supabase.table("patients").select("id,disease_name,care_manager,training_goal").eq("facility_code", f_code).execute()
        extra = {r["id"]: r for r in (res.data or [])}
        for p in patients:
            e = extra.get(p["id"], {})
            p["disease_name"] = e.get("disease_name") or ""
            p["care_manager"]  = e.get("care_manager") or ""
            p["training_goal"] = e.get("training_goal") or ""
    except:
        for p in patients:
            p["disease_name"] = p["care_manager"] = p["training_goal"] = ""
    # 過去評価一覧
    assessments = []
    try:
        a_res = supabase.table("assessments").select("id,user_name,target_month,ai_change").eq("facility_code", f_code).order("target_month", desc=True).limit(50).execute()
        assessments = a_res.data or []
    except:
        pass
    this_month = datetime.now(tokyo_tz).strftime("%Y-%m")
    return render("assessment.html", patients=patients, assessments=assessments, this_month=this_month)

@app.route('/api/generate_assessment', methods=['POST'])
@login_required
def api_generate_assessment():
    try:
        from utils import get_generative_model
        data = request.json
        name       = data.get("patient_name", "")
        birth      = data.get("patient_birth", "")
        disease    = data.get("disease_name", "未記載")
        goal       = data.get("training_goal", "未記載")
        month      = data.get("target_month", "")
        achievement       = data.get("achievement", "")
        home_effort       = data.get("home_effort", "")
        training_progress = data.get("training_progress", "")
        other_notes       = data.get("other_notes", "")

        prompt = f"""あなたは介護施設の機能訓練指導員です。
以下の情報をもとに、ケアマネジャーへ提出する「個別機能訓練 月次評価報告書」の2項目を生成してください。

【利用者情報】
氏名: {name}　生年月日: {birth}　疾患名: {disease}
訓練目標: {goal}
対象月: {month}

【聴取内容】
・今月の訓練達成度: {achievement or '（記載なし）'}
・自宅での取り組み: {home_effort or '（記載なし）'}
・デイでの訓練進捗: {training_progress or '（記載なし）'}
・その他・気づき: {other_notes or '（記載なし）'}

以下の2項目をそれぞれ3〜5文で、専門的かつ具体的に記述してください。
箇条書きは使わず、流れのある文章で書いてください。

【個別機能訓練実施による変化】
（訓練を通じて利用者の身体機能・ADL・意欲などにどのような変化があったかを記述）

【個別機能訓練実施における課題とその要因】
（現在の課題、その背景にある要因、今後の方針を記述）

回答はJSON形式で返してください：
{{"ai_change": "変化の文章", "ai_challenge": "課題の文章"}}"""

        model = get_generative_model()
        resp = model.generate_content([prompt])
        text = resp.text.strip()
        # JSON抽出
        import re as _re
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if m:
            import json as _json
            result = _json.loads(m.group())
            return jsonify({"status": "success", "ai_change": result.get("ai_change",""), "ai_challenge": result.get("ai_challenge","")})
        # フォールバック：テキストをそのまま返す
        return jsonify({"status": "success", "ai_change": text, "ai_challenge": ""})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_assessment', methods=['POST'])
@login_required
def api_save_assessment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        supabase.table("assessments").insert({
            "facility_code":    f_code,
            "patient_id":       data.get("patient_id") or None,
            "user_name":        data.get("patient_name",""),
            "target_month":     data.get("target_month",""),
            "achievement":      data.get("achievement",""),
            "home_effort":      data.get("home_effort",""),
            "training_progress":data.get("training_progress",""),
            "other_notes":      data.get("other_notes",""),
            "ai_change":        data.get("ai_change",""),
            "ai_challenge":     data.get("ai_challenge",""),
            "created_by":       my_name,
        }).execute()
        # 訓練目標をpatientsに保存
        if data.get("patient_id") and data.get("training_goal"):
            supabase.table("patients").update({"training_goal": data["training_goal"]}).eq("id", data["patient_id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_assessment')
@login_required
def api_get_assessment():
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        res = supabase.table("assessments").select("*").eq("id", request.args.get("id")).eq("facility_code", f_code).execute()
        return jsonify({"data": res.data[0] if res.data else None})
    except Exception as e:
        return jsonify({"data": None}), 500

@app.route('/api/parse_assessment_file', methods=['POST'])
@login_required
def api_parse_assessment_file():
    """PC用：アップロードファイルをGeminiで読み取り各フィールドに分配"""
    try:
        from utils import get_generative_model
        file = request.files.get('file')
        if not file:
            return jsonify({"status": "error", "message": "ファイルなし"})
        filename = file.filename.lower()
        file_bytes = file.read()
        mime = "application/pdf" if filename.endswith('.pdf') else "text/plain"
        prompt = """以下のドキュメントから介護記録・評価に関する情報を読み取り、JSON形式で返してください。
該当する情報がない項目は空文字にしてください。

{"achievement": "訓練達成度に関する内容",
 "home_effort": "自宅での取り組みに関する内容",
 "training_progress": "デイでの訓練進捗に関する内容",
 "other_notes": "その他の情報"}

JSONのみを返してください。"""
        model = get_generative_model()
        if filename.endswith('.pdf'):
            resp = model.generate_content([{"mime_type": mime, "data": file_bytes}, prompt])
        else:
            text = file_bytes.decode('utf-8', errors='ignore')
            resp = model.generate_content([text + "\n\n" + prompt])
        import re as _re, json as _json
        m = _re.search(r'\{.*\}', resp.text.strip(), _re.DOTALL)
        if m:
            result = _json.loads(m.group())
            return jsonify({"status": "success", "text": resp.text, **result})
        return jsonify({"status": "success", "text": resp.text, "achievement": "", "home_effort": "", "training_progress": "", "other_notes": resp.text})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/numerology')
@login_required
def numerology():
    f_code = session["f_code"]
    supabase = get_supabase()
    all_persons = []
    # 利用者（誕生日なしでも全員表示）
    try:
        res_p = supabase.table("patients").select("user_name,user_kana,chart_number,birth_date").eq("facility_code", f_code).execute()
        for r in res_p.data:
            all_persons.append({
                "name": r["user_name"],
                "kana": r.get("user_kana") or "",
                "chart": str(r["chart_number"]),
                "birth": r.get("birth_date") or "",
                "type": "patient"
            })
    except:
        pass
    # 職員
    try:
        res_s = supabase.table("staffs").select("staff_name,birth_date").eq("facility_code", f_code).eq("is_active", True).execute()
        for r in res_s.data:
            if r.get("birth_date"):
                all_persons.append({
                    "name": r["staff_name"],
                    "kana": "",
                    "chart": "",
                    "birth": r["birth_date"],
                    "type": "staff"
                })
    except:
        pass
    all_persons.sort(key=lambda x: x["name"])
    return render("numerology.html", all_persons=all_persons)


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
    return render("history.html", patients=patients, months=months, result="")

@app.route('/admin_auth', methods=['POST'])
@login_required
def admin_auth():
    f_code = session["f_code"]
    pw = request.form.get("admin_pw", "")
    try:
        supabase = get_supabase()
        res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res.data[0]['value'] if res.data else "8888"
    except:
        cur_pw = "8888"
    if pw == cur_pw:
        session["admin_authenticated"] = True
        return redirect(url_for("admin"))
    else:
        return render_template("admin.html",
            authenticated=False,
            patients=[],
            blocked=[],
            staff_list=[],
            hist_limit=30,
            error="パスワードが違います。",
            claude_url=None
        )

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
            patients = get_patients(supabase, f_code)
        except: pass
        try:
            res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
            blocked = res_b.data
        except: pass
        try:
            res_s = supabase.table("staffs").select("staff_name,birth_date").eq("facility_code", f_code).eq("is_active", True).execute()
            staff_with_birth = {r["staff_name"]: r.get("birth_date") for r in res_s.data}
        except:
            staff_with_birth = {}
        try:
            res_s = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
            if res_s.data:
                names = sorted(set([r['staff_name'] for r in res_s.data if r['staff_name'] and r['staff_name'] != "AI統合記録"]))
                for name in names:
                    is_b = len(supabase.table("blocked_devices").select("id").eq("staff_name", name).eq("facility_code", f_code).eq("is_active", True).execute().data) > 0
                    bd = staff_with_birth.get(name)
                    staff_list.append({
                        "name": name,
                        "blocked": is_b,
                        "birth_date": bd or "",
                        "birth_text": birth_to_wareki_text(bd) if bd else ""
                    })
        except: pass
        try:
            res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
            if res_l.data: hist_limit = int(res_l.data[0]['value'])
        except: pass

    # 登録済みスタッフ一覧（招待タブ用）
    registered_staffs = []
    if authenticated:
        try:
            res_rs = supabase.table("staffs").select("id,staff_name,created_at").eq("facility_code", f_code).eq("is_active", True).order("created_at").execute()
            registered_staffs = res_rs.data
        except: pass

    claude_url = session.pop("claude_url", None)
    if claude_url:
        claude_url = request.host_url.rstrip('/') + claude_url

    return render_template("admin.html",
        authenticated=authenticated,
        patients=patients,
        blocked=blocked,
        staff_list=staff_list,
        hist_limit=hist_limit,
        error=None,
        claude_url=claude_url,
        registered_staffs=registered_staffs,
        f_code=f_code
    )

# ==========================================
# API エンドポイント
# ==========================================

@app.route('/api/record_dates')
@login_required
def api_record_dates():
    """カレンダーのドット表示用：指定月の記録がある日付一覧を返す"""
    try:
        f_code = session["f_code"]
        year = int(request.args.get("year", datetime.now(tokyo_tz).year))
        month = int(request.args.get("month", datetime.now(tokyo_tz).month))
        supabase = get_supabase()
        month_start = tokyo_tz.localize(datetime(year, month, 1))
        if month == 12:
            next_month = tokyo_tz.localize(datetime(year + 1, 1, 1))
        else:
            next_month = tokyo_tz.localize(datetime(year, month + 1, 1))
        res = supabase.table("records").select("created_at").eq("facility_code", f_code).gte(
            "created_at", month_start.isoformat()
        ).lt("created_at", next_month.isoformat()).execute()
        dates_set = set()
        if res.data:
            for r in res.data:
                d = parse_jst_date(r["created_at"])
                dates_set.add(d.strftime("%Y-%m-%d"))
        return jsonify({"dates": list(dates_set)})
    except Exception as e:
        return jsonify({"dates": [], "error": str(e)})

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
        # 既存レコードを確認
        existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "admin_password").execute()
        if existing.data:
            supabase.table("admin_settings").update({"value": data["password"]}).eq("facility_code", f_code).eq("key", "admin_password").execute()
        else:
            supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": data["password"]}).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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

@app.route('/api/issue_claude_session_form', methods=['POST'])
@login_required
def api_issue_claude_session_form():
    try:
        import secrets
        f_code = session["f_code"]
        supabase = get_supabase()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        supabase.table("claude_sessions").delete().eq("facility_code", f_code).execute()
        supabase.table("claude_sessions").insert({
            "facility_code": f_code,
            "token": token,
            "expires_at": expires_at.isoformat()
        }).execute()
        session["claude_url"] = f"/claude_view?token={token}"
        return redirect(url_for("admin") + "#settings")
    except Exception as e:
        return redirect(url_for("admin"))

@app.route('/api/issue_claude_session', methods=['POST'])
@login_required
def api_issue_claude_session():
    try:
        import secrets
        f_code = session["f_code"]
        supabase = get_supabase()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        # 既存トークンを削除
        supabase.table("claude_sessions").delete().eq("facility_code", f_code).execute()
        # 新しいトークンを発行
        supabase.table("claude_sessions").insert({
            "facility_code": f_code,
            "token": token,
            "expires_at": expires_at.isoformat()
        }).execute()
        return jsonify({"status": "success", "token": token})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/issue_invite', methods=['POST'])
@login_required
def api_issue_invite():
    try:
        import secrets as _secrets
        f_code = session['f_code']
        supabase = get_supabase()
        token = _secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        supabase.table('invite_tokens').delete().eq('facility_code', f_code).execute()
        supabase.table('invite_tokens').insert({
            'facility_code': f_code,
            'token': token,
            'expires_at': expires_at
        }).execute()
        return jsonify({'status': 'success', 'token': token})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/invite', methods=['GET', 'POST'])
def invite():
    token = request.args.get('token') or request.form.get('token')
    if not token:
        return render_template('invite.html', expired=True)
    try:
        supabase = get_supabase()
        res = supabase.table('invite_tokens').select('*').eq('token', token).execute()
        if not res.data:
            return render_template('invite.html', expired=True)
        row = res.data[0]
        expires = datetime.fromisoformat(str(row['expires_at']).replace('Z', '+00:00'))
        if expires < datetime.now(timezone.utc):
            return render_template('invite.html', expired=True)
        f_code = row['facility_code']
        # 施設名取得
        fac = supabase.table('facilities').select('facility_name').eq('facility_code', f_code).execute()
        facility_name = fac.data[0]['facility_name'] if fac.data else f_code

        if request.method == 'POST':
            import hashlib
            staff_name = request.form.get('staff_name', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            password2 = request.form.get('password2', '')
            error = None
            if not staff_name:
                error = '名前を入力してください'
            elif len(password) < 4:
                error = 'パスワードは4文字以上にしてください'
            elif password != password2:
                error = 'パスワードが一致しません'
            else:
                existing = supabase.table('staffs').select('id').eq('facility_code', f_code).eq('staff_name', staff_name).eq('is_active', True).execute()
                if existing.data:
                    error = 'この名前は既に登録されています'
            if error:
                return render_template('invite.html', expired=False, token=token,
                    facility_name=facility_name, error=error, success=False)
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            supabase.table('staffs').insert({
                'facility_code': f_code,
                'staff_name': staff_name,
                'password_hash': pw_hash,
                'is_active': True,
                'email': email if email else None
            }).execute()
            return render_template('invite.html', expired=False, token=token,
                facility_name=facility_name, error=None, success=True)

        return render_template('invite.html', expired=False, token=token,
            facility_name=facility_name, error=None, success=False)
    except Exception as e:
        return render_template('invite.html', expired=True)

@app.route('/claude_view')
def claude_view():
    """Claude用の閲覧ページ - トークン認証"""
    token = request.args.get("token")
    if not token:
        return "アクセストークンが必要です", 403
    try:
        supabase = get_supabase()
        res = supabase.table("claude_sessions").select("*").eq("token", token).execute()
        if not res.data:
            return "トークンが無効です", 403
        expires = datetime.fromisoformat(res.data[0]["expires_at"].replace("Z", "+00:00"))
        if expires < datetime.now(timezone.utc):
            return "トークンの有効期限が切れています", 403
        f_code = res.data[0]["facility_code"]
        # セッションにClaude閲覧用フラグをセット
        session["f_code"] = f_code
        session["my_name"] = "Claude"
        session["is_claude"] = True
        return redirect(url_for("top"))
    except Exception as e:
        return f"エラー: {e}", 500


@app.route('/api/add_staff', methods=['POST'])
@login_required
def api_add_staff():
    try:
        import hashlib
        data = request.json
        f_code = session["f_code"]
        name = data["name"].strip()
        password = data["password"]
        supabase = get_supabase()
        existing = supabase.table("staffs").select("id").eq("facility_code", f_code).eq("staff_name", name).eq("is_active", True).execute()
        if existing.data:
            return jsonify({"status": "error", "message": "同じ名前のスタッフが既に登録されています"})
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        supabase.table("staffs").insert({
            "facility_code": f_code,
            "staff_name": name,
            "password_hash": pw_hash,
            "is_active": True
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete_staff', methods=['POST'])
@login_required
def api_delete_staff():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("staffs").update({"is_active": False}).eq("id", data["id"]).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/update_staff_icon', methods=['POST'])
@login_required
def api_update_staff_icon():
    """スタッフの絵文字アイコンを更新"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("staffs").update({"icon_emoji": data.get("emoji") or None}).eq("staff_name", data["name"]).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_staff_birth', methods=['POST'])
@login_required
def api_update_staff_birth():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("staffs").update({"birth_date": data["birth"] or None}).eq("staff_name", data["name"]).eq("facility_code", f_code).execute()
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