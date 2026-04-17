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

@app.route('/sound_test')
def sound_test():
    return app.send_static_file('sound_test.html')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/static/sw.js')
def service_worker():
    response = app.send_static_file('sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/manual')
@login_required
def manual():
    return render("manual.html",
        version="2.0",
        updated=datetime.now(tokyo_tz).strftime("%Y-%m-%d"),
    )

@app.route('/api/update_my_icon', methods=['POST'])
@login_required
def api_update_my_icon():
    """スタッフ自身のアイコンを更新"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()

        icon_emoji = request.form.get("icon_emoji", "")
        photo = request.files.get("photo")

        image_url = ""
        if photo and photo.filename:
            from utils import upload_images_to_supabase
            urls = upload_images_to_supabase(supabase, [photo], f_code)
            if urls:
                image_url = urls[0]

        update_data = {"icon_emoji": icon_emoji}
        if image_url:
            update_data["icon_image_url"] = image_url
        elif request.form.get("clear_image") == "1":
            update_data["icon_image_url"] = ""

        supabase.table("staffs").update(update_data).eq("facility_code", f_code).eq("staff_name", my_name).execute()
        return jsonify({"status": "success", "icon_emoji": icon_emoji, "icon_image_url": image_url})
    except Exception as e:
        print(f"update_my_icon error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/patients_cache')
@login_required
def api_patients_cache():
    """PWAオフラインキャッシュ用：利用者一覧を返す"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        patients = get_patients(supabase, f_code)
        return jsonify({"patients": patients})
    except Exception as e:
        return jsonify({"patients": [], "error": str(e)})

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
        ).eq("facility_code", f_code).order("id", desc=True).limit(hist_limit * 2).execute()
        if res_hist.data:
            # id降順（DB挿入順）でソートすることで、未来日付の記録が上に鎮座しなくなる
            filtered = [r for r in res_hist.data if r['staff_name'] != "AI統合記録"][:hist_limit]
            for r in filtered:
                records.append({
                    "user_name": r["user_name"],
                    "time": parse_jst(r["created_at"]),
                    "date": str(parse_jst_date(r["created_at"])),
                })
    except:
        pass

    # 自分のアイコン情報を取得
    my_icon_emoji = ""
    my_icon_image_url = ""
    try:
        icon_res = supabase.table("staffs").select("icon_emoji,icon_image_url").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        if icon_res.data:
            my_icon_emoji = icon_res.data[0].get("icon_emoji") or ""
            my_icon_image_url = icon_res.data[0].get("icon_image_url") or ""
    except:
        pass

    return render("top.html", f_code=f_code, my_name=my_name, records=records,
        birthday_users=get_birthday_users(supabase, f_code),
        my_icon_emoji=my_icon_emoji,
        my_icon_image_url=my_icon_image_url,
        my_color=staff_color(my_name),
        my_initial=staff_initial(my_name),
    )

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
                    user_name = m.group(2)
                    record_date_str = record_date
                    # XHR（SPA）からのリクエストにはJSONを返す
                    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                        return jsonify({"status": "success", "redirect": url_for("daily_view", user=user_name, date=record_date_str)})
                    return redirect(url_for("daily_view", user=user_name, date=record_date_str))
            except Exception as e:
                error = f"保存に失敗しました: {e}"
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"status": "error", "message": error}), 500

    return render("input.html",
        patients=patients, today=today, content=content,
        selected_patient=selected_patient, error=error, success=success
    )

@app.route('/daily_view')
@login_required
def daily_view():
    f_code = session["f_code"]
    my_name = session["my_name"]
    is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
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
    """施設の全スタッフアイコン情報を取得 {staff_name: {color, initial, emoji, image_url}}"""
    icons = {}
    try:
        try:
            res = supabase.table("staffs").select("staff_name,icon_emoji,icon_image_url").eq("facility_code", f_code).eq("is_active", True).execute()
        except:
            try:
                res = supabase.table("staffs").select("staff_name,icon_emoji").eq("facility_code", f_code).eq("is_active", True).execute()
            except:
                res = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("is_active", True).execute()
        for s in (res.data or []):
            name = s["staff_name"]
            icons[name] = {
                "color": staff_color(name),
                "initial": staff_initial(name),
                "emoji": s.get("icon_emoji") or "",
                "image_url": s.get("icon_image_url") or "",
            }
    except:
        pass
    return icons

def staff_icon_data(icons, name):
    """get_staff_iconsの結果から1名分のアイコンデータを取得（なければデフォルト）"""
    if name in icons:
        return icons[name]
    return {"color": staff_color(name), "initial": staff_initial(name), "emoji": "", "image_url": ""}

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
    try:
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
                try:
                    dt = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")).astimezone(tokyo_tz)
                    today = datetime.now(tokyo_tz).date()
                    readers = []
                    if r["staff_name"] == my_name:
                        msg_dt_str = str(r["created_at"])
                        for mn, last_read in mem_reads.items():
                            if mn == my_name:
                                continue
                            try:
                                if last_read and str(last_read) >= msg_dt_str:
                                    ic = staff_icon_data(icons, mn)
                                    readers.append({"staff_name": mn, "color": ic["color"], "initial": ic["initial"], "emoji": ic["emoji"]})
                            except:
                                pass
                        ic = staff_icon_data(icons, r["staff_name"])
                    messages.append({
                        "id": r["id"],
                        "staff_name": r["staff_name"],
                        "content": r.get("content", ""),
                        "is_mine": r["staff_name"] == my_name,
                        "color": ic["color"],
                        "initial": ic["initial"],
                        "emoji": ic.get("emoji", ""),
                        "image_url": ic.get("image_url", ""),
                        "date_label": dt.strftime("%-m月%-d日") if dt.date() != today else "今日",
                        "time_label": dt.strftime("%H:%M"),
                        "readers": readers,
                        "read_count": len(readers),
                    })
                except Exception as e:
                    print(f"message parse error: {e}", flush=True)
                    continue

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
                my_color=staff_color(my_name),
                my_initial=staff_initial(my_name),
                is_admin=is_admin,
                supabase_url=get_secret("SUPABASE_URL"),
                supabase_anon_key=get_secret("SUPABASE_KEY"),
            )
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"chat_room error: {err}", flush=True)
        return f"<pre style='padding:20px;'>エラー詳細:\n{err}</pre>", 500

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
        if not data or not data.get("room_id") or not data.get("content", "").strip():
            return jsonify({"status": "error", "message": "room_id と content は必須です"}), 400
        my_name = session["my_name"]
        f_code = session["f_code"]
        supabase = get_supabase()
        room_id = data["room_id"]
        # 参加確認
        mem_check = supabase.table("chat_members").select("id").eq("room_id", room_id).eq("staff_name", my_name).execute()
        if not mem_check.data:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        now_iso = datetime.now(timezone.utc).isoformat()
        # facility_codeカラムがない場合も考慮して最小限のカラムで挿入
        try:
            supabase.table("chat_messages").insert({
                "room_id": room_id,
                "facility_code": f_code,
                "staff_name": my_name,
                "content": data["content"],
            }).execute()
        except Exception:
            # facility_codeカラムがない場合はなしで試みる
            supabase.table("chat_messages").insert({
                "room_id": room_id,
                "staff_name": my_name,
                "content": data["content"],
            }).execute()
        supabase.table("chat_rooms").update({"last_message_at": now_iso}).eq("id", room_id).execute()
        # 送信者は既読済みにする
        supabase.table("chat_members").update({"last_read_at": now_iso}).eq("room_id", room_id).eq("staff_name", my_name).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"send_room_message error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

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

@app.route('/api/new_messages')
@login_required
def api_new_messages():
    """最後に取得したメッセージIDより新しいメッセージを返す（差分ポーリング）"""
    try:
        room_id  = request.args.get("room_id")
        after_id = request.args.get("after_id", "")  # 最後のメッセージID
        f_code   = session["f_code"]
        my_name  = session["my_name"]
        supabase = get_supabase()

        # after_idより新しいメッセージを取得
        if after_id:
            # created_atを使って差分取得
            after_res = supabase.table("chat_messages").select("created_at").eq("id", after_id).execute()
            if after_res.data:
                after_time = after_res.data[0]["created_at"]
                res = supabase.table("chat_messages").select("*").eq("room_id", room_id).gt("created_at", after_time).order("created_at").execute()
            else:
                res = supabase.table("chat_messages").select("*").eq("room_id", room_id).order("created_at").limit(50).execute()
        else:
            res = supabase.table("chat_messages").select("*").eq("room_id", room_id).order("created_at").limit(50).execute()

        icons = get_staff_icons(supabase, f_code)
        messages = []
        today = datetime.now(tokyo_tz).date()
        for r in (res.data or []):
            try:
                dt = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")).astimezone(tokyo_tz)
                ic = staff_icon_data(icons, r["staff_name"])
                messages.append({
                    "id": r["id"],
                    "staff_name": r["staff_name"],
                    "content": r.get("content", ""),
                    "is_mine": r["staff_name"] == my_name,
                    "color": ic["color"],
                    "initial": ic["initial"],
                    "emoji": ic.get("emoji", ""),
                    "image_url": ic.get("image_url", ""),
                    "date_label": dt.strftime("%-m月%-d日") if dt.date() != today else "今日",
                    "time_label": dt.strftime("%H:%M"),
                })
            except:
                continue

        # 既読を更新
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("chat_members").update({"last_read_at": now_iso}).eq("room_id", room_id).eq("staff_name", my_name).execute()

        return jsonify({"status": "success", "messages": messages})
    except Exception as e:
        print(f"new_messages error: {e}", flush=True)
        return jsonify({"status": "error", "messages": []}), 500

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
# バイタル
# ==========================================

DEFAULT_VITAL_SETTINGS = {
    "bp_high_max": 140, "bp_high_min": 90,
    "bp_low_max": 90,   "bp_low_min": 60,
    "pulse_max": 100,   "pulse_min": 50,
    "temp_max": 37.5,   "temp_min": 35.0,
    "spo2_min": 94,
    "recheck_notify": True,
    "recheck_time": "10:00",
    "recheck_times": "10:00",
}

def get_vital_settings(supabase, f_code):
    try:
        res = supabase.table("vital_alert_settings").select("*").eq("facility_code", f_code).execute()
        if res.data:
            d = res.data[0]
            return {k: d.get(k, v) for k, v in DEFAULT_VITAL_SETTINGS.items()}
    except: pass
    return DEFAULT_VITAL_SETTINGS.copy()

@app.route('/vitals')
@login_required
def vitals():
    f_code = session["f_code"]
    supabase = get_supabase()
    today = datetime.now(tokyo_tz).strftime("%Y-%m-%d")

    patients = get_patients(supabase, f_code)

    # 各患者のweekdays・ampm取得
    visit_days = {}
    ampm_data = {}
    try:
        res = supabase.table("patient_visit_days").select("patient_id,weekdays,ampm").eq("facility_code", f_code).execute()
        for r in (res.data or []):
            visit_days[r["patient_id"]] = r.get("weekdays") or ""
            ampm_data[r["patient_id"]] = r.get("ampm") or "BOTH"
        for p in patients:
            p["weekdays"] = visit_days.get(p["id"], "")
            p["ampm"] = ampm_data.get(p["id"], "BOTH")
    except:
        for p in patients:
            p["weekdays"] = ""
            p["ampm"] = "BOTH"

    # 今日のバイタルデータ取得
    vitals_data = {}
    try:
        res = supabase.table("vitals").select("*").eq("facility_code", f_code).eq("measured_date", today).execute()
        for r in (res.data or []):
            vitals_data[r["patient_id"]] = r
    except: pass

    settings = get_vital_settings(supabase, f_code)
    visit_days_map = {p["id"]: p["weekdays"] for p in patients}
    ampm_map = {p["id"]: p["ampm"] for p in patients}

    return render("vitals.html",
        patients=patients,
        visit_days=visit_days_map,
        ampm_data=ampm_map,
        vitals_data=vitals_data,
        settings=settings,
        today=today,
    )

@app.route('/api/save_vital', methods=['POST'])
@login_required
def api_save_vital():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()

        payload = {
            "facility_code": f_code,
            "patient_id": data.get("patient_id"),
            "user_name": data.get("user_name", ""),
            "measured_date": data.get("measured_date"),
            "measured_at": now_iso,
            "bp_high": data.get("bp_high"),
            "bp_low": data.get("bp_low"),
            "pulse": data.get("pulse"),
            "temperature": data.get("temperature"),
            "spo2": data.get("spo2"),
            "note": data.get("note", ""),
            "recheck": data.get("recheck", False),
            "staff_name": my_name,
        }
        # 既存レコードがあればupdate、なければinsert
        if not data.get("patient_id") or not data.get("measured_date"):
            return jsonify({"status": "error", "message": "patient_idとmeasured_dateは必須です"}), 400
        existing = supabase.table("vitals").select("id").eq("facility_code", f_code).eq("patient_id", data["patient_id"]).eq("measured_date", data["measured_date"]).execute()
        if existing.data:
            rid = existing.data[0]["id"]
            supabase.table("vitals").update(payload).eq("id", rid).execute()
        else:
            res = supabase.table("vitals").insert(payload).execute()
            rid = res.data[0]["id"] if res.data else None

        # 再検査通知（トークの全員チャンネルに送信）
        settings = get_vital_settings(supabase, f_code)
        if data.get("recheck") and settings.get("recheck_notify"):
            # 今すぐトークに通知（時刻設定は将来対応）
            alert_items = []
            if data.get("bp_high") and (data["bp_high"] >= settings["bp_high_max"] or data["bp_high"] <= settings["bp_high_min"]):
                alert_items.append("血圧")
            if data.get("pulse") and (data["pulse"] >= settings["pulse_max"] or data["pulse"] <= settings["pulse_min"]):
                alert_items.append("脈拍")
            if data.get("temperature") and (float(data["temperature"]) >= settings["temp_max"] or float(data["temperature"]) <= settings["temp_min"]):
                alert_items.append("体温")
            if data.get("spo2") and data["spo2"] <= settings["spo2_min"]:
                alert_items.append("SpO2")
            if alert_items:
                msg = f"⚠️ 【再検査】{data['user_name']} 様の {'・'.join(alert_items)} の再検査が必要です。（記録者：{my_name}）"
                # 全スタッフ共有のチャットルームを探して通知
                try:
                    rooms = supabase.table("chat_rooms").select("id").eq("facility_code", f_code).eq("is_group", True).execute()
                    if rooms.data:
                        room_id = rooms.data[0]["id"]
                        supabase.table("chat_messages").insert({
                            "room_id": room_id,
                            "facility_code": f_code,
                            "staff_name": "バイタルアラート",
                            "content": msg,
                        }).execute()
                        supabase.table("chat_rooms").update({"last_message_at": now_iso}).eq("id", room_id).execute()
                except: pass

        return jsonify({"status": "success", "id": rid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/read_vital_image', methods=['POST'])
@login_required
def api_read_vital_image():
    try:
        from utils import get_generative_model, upload_audio_to_supabase
        img = request.files.get('image')
        if not img:
            return jsonify({"status": "error", "message": "画像なし"})
        img_bytes = img.read()
        prompt = """この画像には血圧計・体温計・パルスオキシメーターのいずれかが写っています。
画面に表示されている数値を正確に読み取り、JSON形式のみで返してください（説明文不要）：

{
  "bp_high": 収縮期血圧の数値（整数）または null,
  "bp_low": 拡張期血圧の数値（整数）または null,
  "pulse": 脈拍の数値（整数）または null,
  "temperature": 体温の数値（小数点1桁）または null,
  "spo2": SpO2の数値（整数）または null
}

読み取れない項目はnullにしてください。"""
        model = get_generative_model()
        resp = model.generate_content([{"mime_type": "image/jpeg", "data": img_bytes}, prompt])
        import re as _re, json as _json
        m = _re.search(r'\{.*\}', resp.text.strip(), _re.DOTALL)
        
        if m:
            result = _json.loads(m.group())
            return jsonify({"status": "success", **result})
        return jsonify({"status": "error", "message": "数値を読み取れませんでした"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/vitals_daily')
@login_required
def api_vitals_daily():
    try:
        f_code = session["f_code"]
        date = request.args.get("date", datetime.now(tokyo_tz).strftime("%Y-%m-%d"))
        supabase = get_supabase()
        res = supabase.table("vitals").select("*").eq("facility_code", f_code).eq("measured_date", date).order("user_name").execute()
        return jsonify({"vitals": res.data or []})
    except Exception as e:
        return jsonify({"vitals": [], "error": str(e)})

@app.route('/api/vitals_history')
@login_required
def api_vitals_history():
    try:
        f_code = session["f_code"]
        patient_id = request.args.get("patient_id")
        supabase = get_supabase()
        res = supabase.table("vitals").select("*").eq("facility_code", f_code).eq("patient_id", patient_id).order("measured_date", desc=True).limit(60).execute()
        return jsonify({"vitals": res.data or []})
    except Exception as e:
        return jsonify({"vitals": [], "error": str(e)})

@app.route('/api/save_visit_day', methods=['POST'])
@login_required
def api_save_visit_day():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        existing = supabase.table("patient_visit_days").select("id").eq("facility_code", f_code).eq("patient_id", data["patient_id"]).execute()
        if existing.data:
            supabase.table("patient_visit_days").update({"weekdays": data["weekdays"]}).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("patient_visit_days").insert({
                "facility_code": f_code,
                "patient_id": data["patient_id"],
                "user_name": data["user_name"],
                "weekdays": data["weekdays"],
            }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/remove_visit_day', methods=['POST'])
@login_required
def api_remove_visit_day():
    """指定曜日を利用者の利用曜日から削除する"""
    try:
        data = request.json
        f_code = session["f_code"]
        patient_id = str(data["patient_id"])
        weekday = str(data["weekday"])
        supabase = get_supabase()
        existing = supabase.table("patient_visit_days").select("id,weekdays").eq("facility_code", f_code).eq("patient_id", patient_id).execute()
        if existing.data:
            old_days = existing.data[0].get("weekdays") or ""
            new_days = old_days.replace(weekday, "")
            supabase.table("patient_visit_days").update({"weekdays": new_days}).eq("id", existing.data[0]["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"remove_visit_day error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_vital_settings', methods=['POST'])
@login_required
def api_save_vital_settings():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        payload = {**data, "facility_code": f_code}
        existing = supabase.table("vital_alert_settings").select("id").eq("facility_code", f_code).execute()
        if existing.data:
            supabase.table("vital_alert_settings").update(payload).eq("facility_code", f_code).execute()
        else:
            supabase.table("vital_alert_settings").insert(payload).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/check_temp_vital')
@login_required
def api_check_temp_vital():
    """臨時利用者追加時に同名の過去バイタルがあるか確認"""
    try:
        f_code = session["f_code"]
        name = request.args.get("name", "").strip()
        supabase = get_supabase()
        res = supabase.table("vitals").select("id,user_name,measured_date,patient_id").eq("facility_code", f_code).eq("user_name", name).order("measured_date", desc=True).limit(1).execute()
        if res.data:
            r = res.data[0]
            return jsonify({"exists": True, "date": r["measured_date"], "patient_id": r.get("patient_id")})
        return jsonify({"exists": False})
    except Exception as e:
        return jsonify({"exists": False})

@app.route('/api/link_temp_vital', methods=['POST'])
@login_required
def api_link_temp_vital():
    """臨時利用者のバイタルを既存利用者に紐づける"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        # 同名の臨時バイタルを本利用者IDに紐づけ
        supabase.table("vitals").update({"patient_id": data["link_to_id"]}).eq("facility_code", f_code).eq("user_name", data["temp_name"]).is_("patient_id", "null").execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

# ==========================================
# カレンダー
# ==========================================

STICKERS = [
    {"emoji": "🎂", "label": "誕生日"},
    {"emoji": "🎉", "label": "記念日"},
    {"emoji": "🏥", "label": "医療"},
    {"emoji": "💊", "label": "薬"},
    {"emoji": "🌸", "label": "春"},
    {"emoji": "☀️", "label": "晴れ"},
    {"emoji": "🌙", "label": "休み"},
    {"emoji": "⭐", "label": "重要"},
    {"emoji": "📋", "label": "会議"},
    {"emoji": "👥", "label": "担当者会議"},
    {"emoji": "🏢", "label": "運営推進会議"},
    {"emoji": "📞", "label": "電話"},
    {"emoji": "🚗", "label": "外出"},
    {"emoji": "✈️", "label": "旅行"},
    {"emoji": "🎵", "label": "イベント"},
    {"emoji": "💪", "label": "訓練"},
    {"emoji": "🍽️", "label": "食事"},
    {"emoji": "😴", "label": "休養"},
    {"emoji": "❤️", "label": "大切"},
    {"emoji": "✅", "label": "完了"},
    {"emoji": "⚠️", "label": "注意"},
    {"emoji": "🔔", "label": "通知"},
    {"emoji": "📅", "label": "予定"},
    {"emoji": "🎯", "label": "目標"},
]

EVENT_COLORS = [
    "#1a73e8", "#ea4335", "#34a853", "#fbbc04",
    "#9c27b0", "#00bcd4", "#ff5722", "#607d8b",
    "#e91e63", "#4caf50", "#ff9800", "#795548",
]

@app.route('/calendar')
@login_required
def calendar_view():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()

    # 自分が作成したカレンダー OR メンバーとして招待されたカレンダーを取得
    calendars = []
    try:
        # 自分が作ったカレンダー
        own_res = supabase.table("calendars").select("*").eq("facility_code", f_code).eq("owner_name", my_name).order("created_at").execute()
        own_cals = own_res.data or []

        # 招待されているカレンダーのIDを取得
        mem_res = supabase.table("calendar_members").select("calendar_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        invited_ids = [r["calendar_id"] for r in (mem_res.data or [])]

        # 招待されているカレンダーを取得
        invited_cals = []
        if invited_ids:
            inv_res = supabase.table("calendars").select("*").in_("id", invited_ids).execute()
            invited_cals = inv_res.data or []

        # 重複排除してマージ
        seen = set()
        for cal in own_cals + invited_cals:
            if cal["id"] not in seen:
                cal["is_owner"] = (cal.get("owner_name") == my_name)
                calendars.append(cal)
                seen.add(cal["id"])

        # デフォルトカレンダーがなければ作成（初回のみ）
        if not calendars:
            default_cals = [
                {"facility_code": f_code, "name": "マイカレンダー", "color": "#1a73e8", "is_private": True, "is_shared": False, "owner_name": my_name},
                {"facility_code": f_code, "name": "仕事", "color": "#34a853", "is_private": False, "is_shared": True, "owner_name": my_name},
            ]
            for dc in default_cals:
                r = supabase.table("calendars").insert(dc).execute()
                if r.data:
                    cal = r.data[0]
                    cal["is_owner"] = True
                    calendars.append(cal)
    except Exception as e:
        print(f"calendar error: {e}")

    # スタッフ一覧（招待用）
    staffs = []
    try:
        st_res = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("is_active", True).execute()
        staffs = [s["staff_name"] for s in (st_res.data or []) if s["staff_name"] != my_name]
    except: pass

    # カレンダーメンバー一覧（招待済みメンバー）
    cal_members = {}
    try:
        cal_ids = [c["id"] for c in calendars]
        if cal_ids:
            mem_res = supabase.table("calendar_members").select("calendar_id,staff_name,role").in_("calendar_id", cal_ids).execute()
            for m in (mem_res.data or []):
                if m["calendar_id"] not in cal_members:
                    cal_members[m["calendar_id"]] = []
                cal_members[m["calendar_id"]].append(m["staff_name"])
    except: pass

    # 今月のイベント取得（自分が見られるカレンダーのみ）
    events = []
    try:
        cal_ids = [c["id"] for c in calendars]
        if cal_ids:
            now = datetime.now(tokyo_tz)
            date_from = (now.replace(day=1) - timedelta(days=31)).strftime("%Y-%m-%d")
            date_to   = (now.replace(day=1) + timedelta(days=62)).strftime("%Y-%m-%d")
            res = supabase.table("calendar_events").select("*").in_("calendar_id", cal_ids).gte("event_date", date_from).lte("event_date", date_to).order("event_date").execute()
            events = res.data or []
    except Exception as e:
        print(f"events error: {e}")

    return render("calendar.html",
        calendars=calendars,
        events=events,
        stickers=STICKERS,
        event_colors=EVENT_COLORS,
        staffs=staffs,
        cal_members=cal_members,
        my_name=my_name,
    )

@app.route('/api/save_calendar_event', methods=['POST'])
@login_required
def api_save_calendar_event():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        payload = {
            "facility_code": f_code,
            "calendar_id":   data.get("calendar_id"),
            "title":         data.get("title", ""),
            "event_date":    data.get("event_date"),
            "end_date":      data.get("end_date") or data.get("event_date"),
            "start_time":    data.get("start_time"),
            "end_time":      data.get("end_time"),
            "all_day":       data.get("all_day", True),
            "color":         data.get("color"),
            "sticker":       data.get("sticker", ""),
            "memo":          data.get("memo", ""),
            "repeat_type":   data.get("repeat_type", "none"),
            "repeat_until":  data.get("repeat_until"),
            "notify_before": data.get("notify_before", 0),
            "created_by":    my_name,
        }
        event_id = data.get("id")
        if event_id:
            supabase.table("calendar_events").update(payload).eq("id", event_id).eq("facility_code", f_code).execute()
            return jsonify({"status": "success", "id": event_id})
        else:
            res = supabase.table("calendar_events").insert(payload).execute()
            new_id = res.data[0]["id"] if res.data else None
            return jsonify({"status": "success", "id": new_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete_calendar_event', methods=['POST'])
@login_required
def api_delete_calendar_event():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("calendar_events").delete().eq("id", data["id"]).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/save_calendar', methods=['POST'])
@login_required
def api_save_calendar():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        is_private = data.get("is_private", False)
        res = supabase.table("calendars").insert({
            "facility_code": f_code,
            "name":       data["name"],
            "color":      data.get("color", "#1a73e8"),
            "is_private": is_private,
            "is_shared":  not is_private,
            "owner_name": my_name,
        }).execute()
        return jsonify({"status": "success", "id": res.data[0]["id"] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/invite_calendar_member', methods=['POST'])
@login_required
def api_invite_calendar_member():
    """共有カレンダーにメンバーを招待"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        # 自分が所有者かチェック
        cal = supabase.table("calendars").select("owner_name").eq("id", data["calendar_id"]).execute()
        if not cal.data or cal.data[0]["owner_name"] != session["my_name"]:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        # メンバー追加（重複は無視）
        for staff_name in data.get("staff_names", []):
            try:
                supabase.table("calendar_members").insert({
                    "calendar_id":   data["calendar_id"],
                    "facility_code": f_code,
                    "staff_name":    staff_name,
                    "role":          "member",
                }).execute()
            except: pass
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/remove_calendar_member', methods=['POST'])
@login_required
def api_remove_calendar_member():
    """メンバーをカレンダーから削除"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        supabase.table("calendar_members").delete().eq("calendar_id", data["calendar_id"]).eq("staff_name", data["staff_name"]).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/unread_count')
@login_required
def api_unread_count():
    """トークの未読メッセージ数を返す"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()

        # 自分が参加しているルームを取得
        rooms_res = supabase.table("chat_members").select("room_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        room_ids = [r["room_id"] for r in (rooms_res.data or [])]
        if not room_ids:
            return jsonify({"count": 0})

        # 各ルームの未読数を合計
        total = 0
        for room_id in room_ids:
            # 自分の最後の既読時刻を取得
            read_res = supabase.table("chat_members").select("last_read_at").eq("room_id", room_id).eq("staff_name", my_name).execute()
            last_read = read_res.data[0]["last_read_at"] if read_res.data and read_res.data[0].get("last_read_at") else "2000-01-01T00:00:00+00:00"

            # 未読メッセージ数をカウント
            unread_res = supabase.table("chat_messages").select("id", count="exact").eq("room_id", room_id).gt("created_at", last_read).neq("staff_name", my_name).execute()
            total += unread_res.count or 0

        return jsonify({"count": total})
    except Exception as e:
        return jsonify({"count": 0})

@app.route('/api/calendar_events')
@login_required
def api_calendar_events():
    """月移動時のイベント取得"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        date_from = request.args.get("from")
        date_to   = request.args.get("to")
        res = supabase.table("calendar_events").select("*").eq("facility_code", f_code).gte("event_date", date_from).lte("event_date", date_to).order("event_date").execute()
        return jsonify({"events": res.data or []})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})

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
        from utils import get_generative_model, upload_audio_to_supabase
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

        prompt = f"""あなたは通所介護事業所の機能訓練指導員です。
以下の情報をもとに、ケアマネジャーへ提出する「個別機能訓練 月次評価報告書」の2項目を作成してください。

【利用者情報】
氏名: {name}　生年月日: {birth}　疾患名: {disease}
訓練目標: {goal}
対象月: {month}

【今月の状況】
・訓練達成度: {achievement or '（記載なし）'}
・自宅での取り組み: {home_effort or '（記載なし）'}
・デイでの訓練進捗: {training_progress or '（記載なし）'}
・その他・気づき: {other_notes or '（記載なし）'}

【作成ルール】
・機能訓練指導員としての専門的立場から、客観的事実に基づいて記述する
・ICFの視点（①心身機能・身体構造、②活動、③参加）を意識して記述する
・情報の虚偽・誇張・憶測は一切行わない。記載のない情報は補完しない
・ケアマネジャーが読みやすい「です・ます調」の報告書口調で記述する
・専門用語は使いつつも簡潔に。1項目あたり3〜4文、100〜150字程度
・箇条書きは使わず、流れのある文章で書く

【個別機能訓練実施による変化】
（今月の訓練を通じて確認できた心身機能・ADL・意欲等の変化を、機能訓練指導員の視点から記述）

【個別機能訓練実施における課題とその要因】
（現在残存する課題、その背景となる要因、今後の訓練方針を記述）

回答はJSON形式のみで返してください（説明文・コードブロック不要）：
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
            "audio_url":          data.get("audio_url",""),
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
    """PC/スマホ用：アップロードファイル（テキスト・PDF・音声）をGeminiで解析"""
    try:
        from utils import get_generative_model, upload_audio_to_supabase
        file = request.files.get('file')
        if not file:
            return jsonify({"status": "error", "message": "ファイルなし"})
        filename = file.filename.lower()
        file_bytes = file.read()
        audio_mode = request.form.get('audio_mode', 'solo')  # solo or dialog

        # MIMEタイプ判定
        audio_exts = ('.mp3', '.m4a', '.wav', '.aac', '.ogg', '.webm')
        is_audio = any(filename.endswith(ext) for ext in audio_exts)
        is_pdf   = filename.endswith('.pdf')

        json_schema = """{
  "transcript": "文字起こし全文",
  "achievement": "今月の訓練達成度に関する内容",
  "home_effort": "自宅での取り組みに関する内容",
  "training_progress": "デイでの訓練進捗に関する内容",
  "other_notes": "その他・気づき・本人の様子など"
}"""

        if is_audio:
            ext_mime = {
                '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
                '.wav': 'audio/wav',  '.aac': 'audio/aac',
                '.ogg': 'audio/ogg',  '.webm': 'audio/webm',
            }
            mime = next((v for k, v in ext_mime.items() if filename.endswith(k)), 'audio/mpeg')

            if audio_mode == 'dialog':
                prompt = f"""これはデイサービスのスタッフと利用者の対話録音です。
会話を正確に文字起こしし、スタッフの発言・利用者の返答から
介護評価に必要な情報を読み取って以下の4項目に整理してください。
利用者本人の言葉や様子も積極的に反映してください。
該当する情報がない項目は空文字にしてください。
JSON形式のみで返してください（説明文不要）：

{json_schema}"""
            else:
                prompt = f"""これはデイサービスの介護スタッフが利用者の状況について自分一人で話したメモ録音です。
スタッフの独り言・口述メモとして内容を正確に文字起こしし、
介護評価の観点から以下の4項目に分類・整理してください。
該当する情報がない項目は空文字にしてください。
JSON形式のみで返してください（説明文不要）：

{json_schema}"""

            model = get_generative_model()
            resp = model.generate_content([{"mime_type": mime, "data": file_bytes}, prompt])

        elif is_pdf:
            prompt = f"""以下のPDF文書から介護記録・評価に関する情報を読み取り、JSON形式のみで返してください。

{json_schema}"""
            model = get_generative_model()
            resp = model.generate_content([{"mime_type": "application/pdf", "data": file_bytes}, prompt])

        else:
            text = file_bytes.decode('utf-8', errors='ignore')
            prompt = f"""以下のテキストから介護評価に関する情報を整理し、JSON形式のみで返してください。

{text}

{json_schema}"""
            model = get_generative_model()
            resp = model.generate_content([prompt])

        audio_url = ""
        if is_audio:
            try:
                supabase_s = get_supabase()
                audio_url = upload_audio_to_supabase(supabase_s, file_bytes, filename, session.get("f_code","unknown"))
            except Exception as _ae:
                print(f"音声保存エラー: {_ae}")
        import re as _re, json as _json
        m = _re.search(r'\{.*\}', resp.text.strip(), _re.DOTALL)
        if m:
            result = _json.loads(m.group())
            return jsonify({"status": "success", "is_audio": is_audio, "audio_mode": audio_mode, "audio_url": audio_url, **result})
        return jsonify({
            "status": "success", "is_audio": is_audio, "audio_mode": audio_mode,
            "transcript": resp.text, "achievement": "",
            "home_effort": "", "training_progress": "", "other_notes": resp.text, "audio_url": audio_url
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/numerology')
@login_required
def numerology():
    f_code = session["f_code"]
    supabase = get_supabase()
    patients = []
    try:
        res_p = supabase.table("patients").select("user_name,user_kana,chart_number,birth_date").eq("facility_code", f_code).execute()
        for r in res_p.data:
            name  = r["user_name"]
            kana  = r.get("user_kana") or ""
            chart = str(r["chart_number"])
            birth = r.get("birth_date") or ""
            label = f"(No.{chart}) [{name}] {kana}"
            patients.append({
                "value": label,
                "label": label,
                "user_name": name,
                "user_kana": kana,
                "birth_date": birth,
                "type": "patient"
            })
    except:
        pass
    try:
        res_s = supabase.table("staffs").select("staff_name,birth_date").eq("facility_code", f_code).eq("is_active", True).execute()
        for r in res_s.data:
            name  = r["staff_name"]
            birth = r.get("birth_date") or ""
            label = f"[職員] {name}"
            patients.append({
                "value": label,
                "label": label,
                "user_name": name,
                "user_kana": "",
                "birth_date": birth,
                "type": "staff"
            })
    except:
        pass
    patients.sort(key=lambda x: x["user_name"])
    return render("numerology.html", patients=patients)


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
    mode = request.form.get("mode", "admin")  # admin or dev

    # 開発者認証
    if mode == "dev":
        dev_pw = get_secret("DEV_PASSWORD") or "tasukaru-dev-2024"
        if pw == dev_pw:
            session["dev_authenticated"] = True
            return redirect(url_for("dev_menu"))
        else:
            return render_template("admin.html",
                authenticated=False, dev_mode=True,
                patients=[], blocked=[], staff_list=[],
                hist_limit=30, error="開発者パスワードが違います。",
                claude_url=None, registered_staffs=[], f_code=f_code
            ,
            board_editors=[])

    # 管理者認証
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
            authenticated=False, dev_mode=False,
            patients=[], blocked=[], staff_list=[],
            hist_limit=30, error="パスワードが違います。",
            claude_url=None, registered_staffs=[], f_code=f_code
        ,
            board_editors=[])

@app.route('/api/scan_patients_from_image', methods=['POST'])
@login_required
def api_scan_patients_from_image():
    """写真から利用者の名前・生年月日をGeminiで読み取る"""
    try:
        data = request.json
        image_base64 = data.get('image', '')
        mime_type    = data.get('mime_type', 'image/jpeg')

        from utils import get_generative_model, upload_audio_to_supabase
        model = get_generative_model()

        prompt = """この画像を詳しく解析してください。利用者名簿・介護ソフトの画面・紙の名簿・Excel表など、人の名前と情報が含まれている可能性があります。

画像に含まれる全ての人物の情報を読み取り、以下のJSON形式のみで返してください（前置きや説明文は一切不要）：

{"patients": [
  {
    "name": "氏名（漢字。姓と名の間のスペースは除去）",
    "kana": "ふりがな（ひらがな。読み取れなければ空文字）",
    "birth_date": "生年月日をYYYY-MM-DD形式で（和暦も西暦に変換。例：昭和30年3月15日→1955-03-15、S30.3.15→1955-03-15）",
    "chart": "カルテ番号・利用者番号・IDなど（なければ空文字）",
    "weekdays": "利用曜日の数字を連結（月=1,火=2,水=3,木=4,金=5,土=6,日=0。例：月水金→135。わからなければ空文字）",
    "ampm": "AM（午前）かPM（午後）かBOTH（両方/不明）"
  }
]}

重要な注意：
- 表の中の全ての行を漏れなく読み取ること
- 生年月日は必ず西暦YYYY-MM-DDに変換すること
- 昭和元年=1926年、平成元年=1989年、令和元年=2019年
- 読み取れない文字はそのままにせず、前後の文脈から推測すること
- 絶対にJSON以外の文字を返さないこと"""

        import json as _json
        import re as _re

        resp = model.generate_content([
            {"mime_type": mime_type, "data": image_base64},
            prompt
        ])

        text = resp.text.strip()
        # JSONを抽出
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if not m:
            return jsonify({"status": "error", "message": "JSONを取得できませんでした", "patients": []})

        result = _json.loads(m.group())
        patients = result.get("patients", [])

        if not patients:
            return jsonify({"status": "error", "message": "利用者情報が見つかりませんでした", "patients": []})

        return jsonify({"status": "success", "patients": patients, "count": len(patients)})

    except Exception as e:
        print(f"scan_patients error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e), "patients": []}), 500

@app.route('/api/bulk_register_patients', methods=['POST'])
@login_required
def api_bulk_register_patients():
    """読み取った利用者を一括登録"""
    try:
        data = request.json
        f_code   = session["f_code"]
        patients = data.get("patients", [])
        supabase = get_supabase()

        # 既存のカルテ番号の最大値を取得
        existing = supabase.table("patients").select("chart_number").eq("facility_code", f_code).execute()
        existing_nums = []
        for p in (existing.data or []):
            try: existing_nums.append(int(p["chart_number"]))
            except: pass
        next_num = max(existing_nums, default=0) + 1

        registered = 0
        for p in patients:
            name = p.get("name", "").strip()
            if not name:
                continue
            # カルテ番号
            chart = p.get("chart", "").strip()
            if not chart:
                chart = str(next_num).zfill(3)
                next_num += 1

            # 生年月日の整形
            birth_date = p.get("birth_date", "") or None
            if birth_date and len(birth_date) == 10:
                try:
                    from datetime import datetime as dt
                    dt.strptime(birth_date, "%Y-%m-%d")
                except:
                    birth_date = None

            supabase.table("patients").insert({
                "facility_code": f_code,
                "user_name":     name,
                "user_kana":     p.get("kana", "") or "",
                "birth_date":    birth_date,
                "chart_number":  chart,
            }).execute()

            # 利用曜日・AM/PMをpatient_visit_daysに保存
            weekdays = p.get("weekdays", "") or ""
            ampm     = p.get("ampm", "BOTH") or "BOTH"
            if weekdays:
                # 登録したpatientsのIDを取得
                new_p = supabase.table("patients").select("id").eq("facility_code", f_code).eq("user_name", name).eq("chart_number", chart).execute()
                if new_p.data:
                    pid = str(new_p.data[0]["id"])
                    try:
                        supabase.table("patient_visit_days").insert({
                            "facility_code": f_code,
                            "patient_id":    pid,
                            "user_name":     name,
                            "weekdays":      weekdays,
                            "ampm":          ampm,
                        }).execute()
                    except:
                        pass
            registered += 1

        return jsonify({"status": "success", "count": registered})
    except Exception as e:
        print(f"bulk_register error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

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
        dev_mode=False,
        patients=patients,
        blocked=blocked,
        staff_list=staff_list,
        hist_limit=hist_limit,
        error=None,
        claude_url=claude_url,
        registered_staffs=registered_staffs,
        f_code=f_code
    ,
            board_editors=[])

# ==========================================

@app.route('/mapping')
@login_required
def mapping():
    import os, json
    from flask import Response
    html = open('static/mapping.html', encoding='utf-8').read()
    config = json.dumps({
        'supabaseUrl': os.environ.get('SUPABASE_URL', ''),
        'supabaseKey': os.environ.get('SUPABASE_KEY', ''),
        'facilityCode': os.environ.get('FACILITY_CODE', 'cocokaraplus-5526')
    })
    cfg = '<script>window.TASUKARU_CONFIG=' + config + ';</script>'
    html = html.replace('</head>', cfg + '</head>', 1)
    return Response(html, mimetype='text/html')

@app.route('/help')
@login_required
def help_page():
    return app.send_static_file('help.html')

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
        if not data or not data.get("audio_data"):
            return jsonify({"error": "音声データがありません"}), 400
        from utils import get_generative_model, upload_audio_to_supabase
        model = get_generative_model()
        prompt = "以下の音声を介護記録として文章に起こしてください。\n【ルール】\n・話した内容をできるだけ忠実に文章化する\n・「あー」「えー」「えっと」などのフィラーは省略する\n・職員名や「利用者様は」などの主語は不要\n・です・ます調に整える\n・事実のみを記載し、余計な装飾は不要"
        try:
            audio_bytes = base64.b64decode(data["audio_data"])
        except Exception:
            return jsonify({"error": "音声データのデコードに失敗しました"}), 400
        mime = data.get("audio_mime", "audio/webm")
        contents = [prompt, {"mime_type": mime, "data": audio_bytes}]
        result = model.generate_content(contents)
        return jsonify({"text": result.text.strip()})
    except Exception as e:
        print(f"[transcribe error] {e}")
        return jsonify({"error": f"音声変換に失敗しました: {str(e)}"}), 500

@app.route('/api/generate_daily', methods=['POST'])
@login_required
def api_generate_daily():
    try:
        data = request.json
        if not data or not data.get("user") or not data.get("date"):
            return jsonify({"status": "error", "message": "user と date は必須です"}), 400
        f_code = session["f_code"]
        supabase = get_supabase()
        user = data["user"]
        try:
            selected_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"status": "error", "message": "日付の形式が正しくありません（YYYY-MM-DD）"}), 400
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
        from utils import get_generative_model, upload_audio_to_supabase
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
        if not data or not data.get("user") or not data.get("date"):
            return jsonify({"status": "error", "message": "user と date は必須です"}), 400
        f_code = session["f_code"]
        supabase = get_supabase()
        user = data["user"]
        try:
            selected_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"status": "error", "message": "日付の形式が正しくありません（YYYY-MM-DD）"}), 400
        t_start = tokyo_tz.localize(datetime.combine(selected_date, dt_time.min))
        res = supabase.table("records").select("*").eq("facility_code", f_code).eq(
            "user_name", user
        ).gte("created_at", t_start.isoformat()).lt(
            "created_at", (t_start + timedelta(days=1)).isoformat()
        ).execute()
        normal_recs = [r for r in res.data if r["staff_name"] != "AI統合記録"]
        recs_text = "\n".join([f"【{r['staff_name']}】{r['content']}" for r in normal_recs])
        from utils import get_generative_model, upload_audio_to_supabase
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
        if not data or not data.get("id") or data.get("content") is None:
            return jsonify({"status": "error", "message": "id と content は必須です"}), 400
        supabase = get_supabase()
        supabase.table("records").update({"content": data["content"]}).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete_record', methods=['POST'])
@login_required
def api_delete_record():
    try:
        data = request.json
        if not data or not data.get("id"):
            return jsonify({"status": "error", "message": "id は必須です"}), 400
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        # 権限チェック：自分の記録か管理者のみ削除可能
        rec = supabase.table("records").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not rec.data:
            return jsonify({"status": "error", "message": "記録が見つかりません"}), 404
        r = rec.data[0]
        if r["facility_code"] != f_code:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        if not is_admin and r["staff_name"] != my_name:
            return jsonify({"status": "error", "message": "この記録を削除する権限がありません"}), 403
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
        from utils import get_generative_model, upload_audio_to_supabase
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
        mode = data.get("mode", "admin")

        if mode == "dev":
            dev_pw = get_secret("DEV_PASSWORD") or "tasukaru-dev-2024"
            if data["password"] == dev_pw:
                session["dev_authenticated"] = True
                return jsonify({"status": "success", "redirect": "/dev"})
            return jsonify({"status": "error"})

        supabase = get_supabase()
        res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res.data[0]['value'] if res.data else "8888"
        if data["password"] == cur_pw:
            session["admin_authenticated"] = True
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "error"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/admin_logout', methods=['POST'])
def api_admin_logout():
    session["admin_authenticated"] = False
    session["dev_authenticated"] = False
    return jsonify({"status": "success"})

@app.route('/dev')
@login_required
def dev_menu():
    if not session.get("dev_authenticated"):
        return redirect(url_for("admin"))
    supabase = get_supabase()
    f_code = session["f_code"]

    # 全施設一覧
    facilities = []
    try:
        res = supabase.table("facilities").select("facility_code,facility_name,is_active,created_at").order("created_at", desc=True).execute()
        facilities = res.data or []
    except: pass

    # 各施設のレコード数・スタッフ数
    stats = []
    for fac in facilities:
        fc = fac["facility_code"]
        try:
            rec_count = supabase.table("records").select("id", count="exact").eq("facility_code", fc).execute().count or 0
            staff_count = supabase.table("staffs").select("id", count="exact").eq("facility_code", fc).eq("is_active", True).execute().count or 0
            patient_count = supabase.table("patients").select("id", count="exact").eq("facility_code", fc).execute().count or 0
            stats.append({
                "facility_code": fc,
                "facility_name": fac.get("facility_name", fc),
                "is_active": fac.get("is_active", True),
                "created_at": fac.get("created_at", "")[:10],
                "records": rec_count,
                "staffs": staff_count,
                "patients": patient_count,
            })
        except:
            stats.append({"facility_code": fc, "facility_name": fc, "is_active": True, "created_at": "", "records": 0, "staffs": 0, "patients": 0})

    # 環境変数チェック（値は隠す）
    env_keys = ["SUPABASE_URL","SUPABASE_KEY","GEMINI_API_KEY","SECRET_KEY","SENDGRID_API_KEY","SENDGRID_FROM_EMAIL","DEV_PASSWORD"]
    env_status = {k: "✅ 設定済み" if get_secret(k) else "❌ 未設定" for k in env_keys}

    # 直近エラーログ（recordsの最新など）
    recent_records = []
    try:
        res = supabase.table("records").select("facility_code,user_name,staff_name,created_at").order("created_at", desc=True).limit(20).execute()
        recent_records = res.data or []
    except: pass

    import sys
    runtime_info = {
        "python": sys.version.split()[0],
        "flask": "Flask",
        "current_facility": f_code,
        "total_facilities": len(facilities),
    }

    return render_template("dev_menu.html",
        stats=stats,
        env_status=env_status,
        recent_records=recent_records,
        runtime_info=runtime_info,
        current_f_code=f_code,
    )

@app.route('/api/dev_logout', methods=['POST'])
def api_dev_logout():
    session["dev_authenticated"] = False
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


# ==========================================
# 掲示板
# ==========================================

@app.route('/board')
@login_required
def board():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    posts = []
    try:
        res = supabase.table("board_posts").select("*").eq("facility_code", f_code).order("is_pinned", desc=True).order("created_at", desc=True).limit(30).execute()
        posts = res.data or []
    except Exception as e:
        print(f"board error: {e}")
    icons = get_staff_icons(supabase, f_code)
    post_ids = [p["id"] for p in posts]
    comments_count = {}
    reactions_data = {}
    read_data = {}
    try:
        if post_ids:
            for pid in post_ids:
                cnt = supabase.table("board_comments").select("id", count="exact").eq("post_id", pid).execute()
                comments_count[pid] = cnt.count or 0
            rres = supabase.table("board_reactions").select("*").in_("post_id", post_ids).execute()
            for r in (rres.data or []):
                pid = r["post_id"]
                if pid not in reactions_data: reactions_data[pid] = {}
                em = r["reaction"]
                if em not in reactions_data[pid]: reactions_data[pid][em] = []
                reactions_data[pid][em].append(r["staff_name"])
            rdres = supabase.table("board_reads").select("post_id,staff_name").in_("post_id", post_ids).execute()
            for r in (rdres.data or []):
                pid = r["post_id"]
                if pid not in read_data: read_data[pid] = []
                read_data[pid].append(r["staff_name"])
    except Exception as e:
        print(f"board detail error: {e}")
    staffs = [name for name in icons.keys()]
    return render("board.html",
        posts=posts, icons=icons, my_name=my_name,
        my_color=staff_color(my_name), my_initial=staff_initial(my_name),
        comments_count=comments_count, reactions_data=reactions_data,
        read_data=read_data, staffs=staffs,
        supabase_url=get_secret("SUPABASE_URL"),
        supabase_anon_key=get_secret("SUPABASE_KEY"),
    )

@app.route("/api/board/create_post", methods=["POST"])
@login_required
def api_board_create_post():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        content = request.form.get("content", "").strip()
        photos = request.files.getlist("photos")
        audio = request.files.get("audio")
        import json as _json
        mentions = _json.loads(request.form.get("mention_names", "[]"))
        image_urls = []
        if photos and photos[0].filename:
            from utils import upload_images_to_supabase
            image_urls = upload_images_to_supabase(supabase, photos, f_code)
        audio_url = ""
        if audio and audio.filename:
            from utils import upload_audio_to_supabase
            audio_url = upload_audio_to_supabase(supabase, audio.read(), audio.filename, f_code)
        res = supabase.table("board_posts").insert({
            "facility_code": f_code, "staff_name": my_name,
            "content": content, "image_urls": image_urls,
            "file_urls": [], "audio_url": audio_url,
            "mention_names": mentions, "is_pinned": False,
        }).execute()
        return jsonify({"status": "success", "post_id": res.data[0]["id"] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/board/update_post", methods=["POST"])
@login_required
def api_board_update_post():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        post = supabase.table("board_posts").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not post.data: return jsonify({"status": "error", "message": "見つかりません"}), 404
        p = post.data[0]
        if p["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        if not is_admin and p["staff_name"] != my_name:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        supabase.table("board_posts").update({
            "content": data.get("content", ""),
            "updated_at": "now()"
        }).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/delete_post", methods=["POST"])
@login_required
def api_board_delete_post():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        post = supabase.table("board_posts").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not post.data: return jsonify({"status": "error"}), 404
        p = post.data[0]
        if p["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        if not is_admin and p["staff_name"] != my_name: return jsonify({"status": "error", "message": "権限がありません"}), 403
        supabase.table("board_posts").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route("/api/board/pin_post", methods=["POST"])
@login_required
def api_board_pin_post():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        if not is_admin: return jsonify({"status": "error", "message": "管理者のみ操作可能"}), 403
        supabase = get_supabase()
        supabase.table("board_posts").update({"is_pinned": data.get("pinned", True)}).eq("id", data["id"]).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route("/api/board/get_comments")
@login_required
def api_board_get_comments():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        post_id = request.args.get("post_id")
        supabase = get_supabase()
        icons = get_staff_icons(supabase, f_code)
        res = supabase.table("board_comments").select("*").eq("post_id", post_id).eq("facility_code", f_code).order("created_at").execute()
        comments = []
        for c in (res.data or []):
            ic = staff_icon_data(icons, c["staff_name"])
            comments.append({**c, "color": ic["color"], "initial": ic["initial"],
                "emoji": ic.get("emoji",""), "image_url": ic.get("image_url",""),
                "is_mine": c["staff_name"] == my_name, "time_label": parse_jst(c["created_at"])})
        try:
            supabase.table("board_reads").upsert({
                "facility_code": f_code, "post_id": int(post_id), "staff_name": my_name
            }, on_conflict="post_id,staff_name").execute()
        except: pass
        return jsonify({"status": "success", "comments": comments})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/add_comment", methods=["POST"])
@login_required
def api_board_add_comment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        res = supabase.table("board_comments").insert({
            "facility_code": f_code, "post_id": data["post_id"],
            "staff_name": my_name, "content": data.get("content","").strip(),
            "mention_names": data.get("mention_names", []),
        }).execute()
        return jsonify({"status": "success", "comment_id": res.data[0]["id"] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/delete_comment", methods=["POST"])
@login_required
def api_board_delete_comment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False) or my_name == "管理者"
        supabase = get_supabase()
        c = supabase.table("board_comments").select("staff_name").eq("id", data["id"]).execute()
        if not c.data: return jsonify({"status": "error"}), 404
        if not is_admin and c.data[0]["staff_name"] != my_name:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        supabase.table("board_comments").delete().eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route("/api/board/react", methods=["POST"])
@login_required
def api_board_react():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        post_id = data.get("post_id")
        reaction = data.get("reaction", "✅")
        existing = supabase.table("board_reactions").select("id").eq("post_id", post_id).eq("staff_name", my_name).eq("reaction", reaction).execute()
        if existing.data:
            supabase.table("board_reactions").delete().eq("id", existing.data[0]["id"]).execute()
            action = "removed"
        else:
            supabase.table("board_reactions").insert({
                "facility_code": f_code, "post_id": post_id,
                "staff_name": my_name, "reaction": reaction,
            }).execute()
            action = "added"
        rres = supabase.table("board_reactions").select("reaction,staff_name").eq("post_id", post_id).execute()
        reactions = {}
        for r in (rres.data or []):
            em = r["reaction"]
            if em not in reactions: reactions[em] = []
            reactions[em].append(r["staff_name"])
        return jsonify({"status": "success", "action": action, "reactions": reactions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/unread_count")
@login_required
def api_board_unread_count():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        all_posts = supabase.table("board_posts").select("id").eq("facility_code", f_code).execute()
        all_ids = [p["id"] for p in (all_posts.data or [])]
        if not all_ids: return jsonify({"count": 0})
        read_posts = supabase.table("board_reads").select("post_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
        read_ids = set(r["post_id"] for r in (read_posts.data or []))
        return jsonify({"count": len([i for i in all_ids if i not in read_ids])})
    except Exception as e:
        return jsonify({"count": 0})


# ==========================================
# タスク管理
# ==========================================

@app.route('/tasks')
@login_required
def tasks():
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    staffs = []
    try:
        res = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("is_active", True).execute()
        staffs = [r["staff_name"] for r in (res.data or [])]
    except: pass
    projects = []
    try:
        res = supabase.table("task_projects").select("*").eq("facility_code", f_code).order("created_at", desc=True).execute()
        projects = res.data or []
    except: pass
    return render("tasks.html",
        my_name=my_name,
        staffs=staffs,
        projects=projects,
        my_color=staff_color(my_name),
        my_initial=staff_initial(my_name),
    )

@app.route("/api/tasks/list")
@login_required
def api_tasks_list():
    """タスク一覧取得（自分が関わるタスク）"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        filter_type = request.args.get("filter", "all")  # all/assigned/created/project
        project_id = request.args.get("project_id")

        res = supabase.table("tasks").select("*").eq("facility_code", f_code).order("due_date").order("priority").execute()
        tasks = res.data or []

        # フィルタ
        if filter_type == "assigned":
            tasks = [t for t in tasks if my_name in (t.get("assigned_to") or [])]
        elif filter_type == "created":
            tasks = [t for t in tasks if t.get("created_by") == my_name]
        elif filter_type == "project" and project_id:
            tasks = [t for t in tasks if str(t.get("project_id")) == str(project_id)]
        else:
            # 自分が作成 or 自分がアサインされているもの
            tasks = [t for t in tasks if
                t.get("created_by") == my_name or
                my_name in (t.get("assigned_to") or []) or
                not t.get("assigned_to")  # 全体タスク
            ]

        # 期限の日本語変換・優先度ラベル
        now_date = datetime.now(tokyo_tz).date()
        priority_map = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}
        status_map = {"todo": "未着手", "in_progress": "進行中", "done": "完了"}

        for t in tasks:
            t["priority_label"] = priority_map.get(t.get("priority", "medium"), "🟡 中")
            t["status_label"] = status_map.get(t.get("status", "todo"), "未着手")
            t["is_mine"] = t.get("created_by") == my_name
            t["is_assigned"] = my_name in (t.get("assigned_to") or [])
            if t.get("due_date"):
                try:
                    due = datetime.strptime(str(t["due_date"]), "%Y-%m-%d").date()
                    diff = (due - now_date).days
                    t["due_label"] = str(t["due_date"])
                    t["due_diff"] = diff
                    t["due_urgent"] = diff <= 7 and t.get("status") != "done"
                except: pass

        return jsonify({"status": "success", "tasks": tasks})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/urgent")
@login_required
def api_tasks_urgent():
    """TOPページ用：期限3日以内の自分のタスク"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        now_date = datetime.now(tokyo_tz).date()
        limit_date = (now_date + timedelta(days=7)).isoformat()

        res = supabase.table("tasks").select("id,title,due_date,priority,status,assigned_to").eq(
            "facility_code", f_code
        ).lte("due_date", limit_date).neq("status", "done").order("due_date").limit(5).execute()

        tasks = []
        priority_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for t in (res.data or []):
            assigned = t.get("assigned_to") or []
            if my_name in assigned or not assigned:
                due = datetime.strptime(str(t["due_date"]), "%Y-%m-%d").date()
                diff = (due - now_date).days
                tasks.append({
                    "id": t["id"],
                    "title": t["title"],
                    "due_date": t["due_date"],
                    "due_diff": diff,
                    "priority_icon": priority_map.get(t.get("priority","medium"), "🟡"),
                })
        return jsonify({"status": "success", "tasks": tasks})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/create", methods=["POST"])
@login_required
def api_tasks_create():
    """タスク作成"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        import json as _json

        assigned_to = data.get("assigned_to", [])
        # 全体タスクの場合は空配列
        if data.get("assign_type") == "all":
            assigned_to = []

        insert_data = {
            "facility_code": f_code,
            "title": data.get("title", "").strip(),
            "description": data.get("description", "").strip(),
            "created_by": my_name,
            "assigned_to": assigned_to,
            "priority": data.get("priority", "medium"),
            "status": "todo",
        }
        if data.get("due_date"):
            insert_data["due_date"] = data["due_date"]
        if data.get("project_id"):
            insert_data["project_id"] = int(data["project_id"])

        res = supabase.table("tasks").insert(insert_data).execute()
        return jsonify({"status": "success", "task": res.data[0] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/update", methods=["POST"])
@login_required
def api_tasks_update():
    """タスク更新（ステータス・内容）"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        task_id = data.get("id")

        # 権限チェック
        task = supabase.table("tasks").select("created_by,assigned_to").eq("id", task_id).eq("facility_code", f_code).execute()
        if not task.data:
            return jsonify({"status": "error", "message": "タスクが見つかりません"}), 404
        t = task.data[0]
        assigned = t.get("assigned_to") or []
        if t["created_by"] != my_name and my_name not in assigned:
            return jsonify({"status": "error", "message": "権限がありません"}), 403

        update_data = {"updated_at": datetime.now(tokyo_tz).isoformat()}
        for field in ["title", "description", "priority", "status", "due_date", "assigned_to", "project_id"]:
            if field in data:
                update_data[field] = data[field]

        supabase.table("tasks").update(update_data).eq("id", task_id).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/delete", methods=["POST"])
@login_required
def api_tasks_delete():
    """タスク削除（作成者のみ）"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        task_id = data.get("id")

        task = supabase.table("tasks").select("created_by").eq("id", task_id).eq("facility_code", f_code).execute()
        if not task.data:
            return jsonify({"status": "error"}), 404
        if task.data[0]["created_by"] != my_name:
            return jsonify({"status": "error", "message": "作成者のみ削除できます"}), 403

        supabase.table("tasks").delete().eq("id", task_id).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/projects", methods=["GET"])
@login_required
def api_tasks_projects():
    """プロジェクト一覧"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        res = supabase.table("task_projects").select("*").eq("facility_code", f_code).order("created_at", desc=True).execute()
        return jsonify({"status": "success", "projects": res.data or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/projects/create", methods=["POST"])
@login_required
def api_tasks_projects_create():
    """プロジェクト作成"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        res = supabase.table("task_projects").insert({
            "facility_code": f_code,
            "name": data.get("name", "").strip(),
            "members": data.get("members", []),
            "created_by": my_name,
        }).execute()
        return jsonify({"status": "success", "project": res.data[0] if res.data else None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tasks/projects/delete", methods=["POST"])
@login_required
def api_tasks_projects_delete():
    """プロジェクト削除（作成者のみ）"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        project_id = data.get("id")
        proj = supabase.table("task_projects").select("created_by").eq("id", project_id).eq("facility_code", f_code).execute()
        if not proj.data:
            return jsonify({"status": "error"}), 404
        if proj.data[0]["created_by"] != my_name:
            return jsonify({"status": "error", "message": "作成者のみ削除できます"}), 403
        supabase.table("tasks").update({"project_id": None}).eq("project_id", project_id).execute()
        supabase.table("task_projects").delete().eq("id", project_id).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)