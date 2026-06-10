from flask import Flask, render_template, request, jsonify, redirect, url_for, session, current_app
from supabase import create_client
from utils import classify_category, generate_search_tags
from evaluation_helper import (
    get_initial_training_goal,
    get_initial_care_classification,
    get_initial_goal_values,
    acquire_edit_lock,
    release_edit_lock,
    evaluation_status,
    upsert_patient_evaluation,
    fetch_patient_evaluations,
)
from datetime import datetime, timedelta, time as dt_time, timezone
import os
import threading
_monitoring_gen_lock = threading.Lock()
import uuid
import pytz
import re
import base64
import json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY が設定されていません。環境変数を確認してください。")

# ===== Session persistence for PWA/mobile =====
# Keep users logged in across browser restarts (up to 30 days)
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only (Cloud Run is always HTTPS)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

@app.before_request
def make_session_permanent():
    from flask import session
    session.permanent = True

# ============================================================
# HTMLno-cache
# ============================================================
@app.after_request
def add_no_cache_headers(response):
    ct = response.headers.get('Content-Type', '')
    if 'text/html' in ct:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


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
        from_email = from_email.strip() if from_email else from_email
        print(f"[send_email] to={to_email} subject={subject!r} api_key_set={bool(api_key)} from_email={from_email!r}", flush=True)
        if not api_key or not from_email:
            print(f"[send_email] EARLY RETURN: missing credentials (api_key={bool(api_key)}, from_email={bool(from_email)})", flush=True)
            return False
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            html_content=html_content
        )
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print(f"[send_email] SendGrid response status={response.status_code}", flush=True)
        return 200 <= response.status_code < 300
    except Exception as e:
        print(f"[send_email] Exception: {type(e).__name__}: {e}", flush=True)
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
    """partial param returns JSON content only (Jinja2 block mode)"""
    if request.args.get("partial"):
        tmpl = current_app.jinja_env.get_template(template)
        ctx = tmpl.new_context(kwargs)

        def render_block(name):
            if name in tmpl.blocks:
                try:
                    return "".join(tmpl.blocks[name](ctx))
                except Exception as e:
                    print(f"[render partial] block {name} error: {e}")
                    return ""
            return ""

        content_block = render_block("content")
        style_block = render_block("extra_style")
        script_block = render_block("extra_script")
        title_block = render_block("title")

        return jsonify({
            "content": content_block,
            "style": style_block,
            "script": script_block,
            "title": title_block,
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
        res = supabase.table("patient_profiles").select("*").eq("facility_code", f_code).order("user_name_kana").execute()
        # patientsテーブルの整数IDをuser_nameでマッピング
        pt_res = supabase.table("patients").select("id,user_name").eq("facility_code", f_code).execute()
        pt_id_map = {r["user_name"]: r["id"] for r in (pt_res.data or [])}
        patients = []
        for r in res.data:
            kana  = r.get('user_name_kana') or ""
            chart = str(r.get('patient_number') or "")
            name  = r.get('user_name') or ""
            patients.append({
                "value": f"(No.{chart}) [{name}] {kana}",
                "label": f"(No.{chart}) [{name}] {kana}",
                "id": r["id"],
                "patient_int_id": pt_id_map.get(name),
                "chart_number": chart,
                "patient_number": chart,
                "user_name": name,
                "user_kana": kana,
                "user_name_kana": kana,
                "birth_date": r.get("birth_date") or "",
                "birth_text": birth_to_wareki_text(r.get("birth_date")),
                "care_level": r.get("care_level") or "",
                "gender": r.get("gender") or "",
                "long_goal": r.get("long_goal") or "",
                "short_goal": r.get("short_goal") or "",
                "is_discontinued": bool(r.get("is_discontinued")),
                "discontinued_date": r.get("discontinued_date") or "",
            })
        return patients
    except:
        return []

def get_birthday_users(supabase, f_code):
    try:
        now = datetime.now(tokyo_tz)
        res = supabase.table("patients").select("user_name, birth_date").eq("facility_code", f_code).execute()
        pp_res = supabase.table("patient_profiles").select("user_name, birth_date").eq("facility_code", f_code).execute()
        pp_birth = {r["user_name"]: r["birth_date"] for r in (pp_res.data or []) if r.get("birth_date")}
        for r in (res.data or []):
            if not r.get("birth_date") and r["user_name"] in pp_birth:
                r["birth_date"] = pp_birth[r["user_name"]]
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
# 休み連絡content生成ヘルパー
# ==========================================
def _build_leave_content(period, reporter_type, other_detail, leave_reason):
    """休み連絡のcontent文字列を生成する共通関数"""
    _reporter_map = {"self": "本人", "family": "家族", "caremanager": "ケアマネ", "other": "その他"}
    _reporter = _reporter_map.get(reporter_type or "", "")
    if reporter_type == "other" and other_detail:
        _reporter = other_detail
    if _reporter:
        base = f"{period}はお休みと{_reporter}から連絡がありました。"
    else:
        base = f"{period}はお休みと連絡がありました。"
    if leave_reason:
        base += f"理由：{leave_reason}"
    return base


def _format_leave_period(dates):
    """日付文字列(YYYY-MM-DD)のリストから '6月2日・6月5日・6月10日' のような表記を作る。
    連続範囲は '6月2日〜6月5日' のようにまとめる。"""
    from datetime import datetime as _dt, timedelta as _td
    ds = sorted(set([d for d in dates if d]))
    if not ds:
        return ""
    parsed = []
    for d in ds:
        try:
            parsed.append(_dt.strptime(d, "%Y-%m-%d").date())
        except Exception:
            pass
    if not parsed:
        return ""
    parsed = sorted(set(parsed))
    # 連続する日をグループ化
    groups = []
    start = prev = parsed[0]
    for cur in parsed[1:]:
        if cur == prev + _td(days=1):
            prev = cur
            continue
        groups.append((start, prev))
        start = prev = cur
    groups.append((start, prev))
    parts = []
    for s, e in groups:
        if s == e:
            parts.append(f"{s.month}月{s.day}日")
        else:
            parts.append(f"{s.month}月{s.day}日〜{e.month}月{e.day}日")
    return "・".join(parts)


def _build_leave_content_multi(dates, reporter_type, other_detail, leave_reason):
    """複数日(飛び日含む)の休み連絡content文字列を生成する。"""
    period = _format_leave_period(dates)
    return _build_leave_content(period, reporter_type, other_detail, leave_reason)

# ==========================================
# 管理者権限ヘルパー
# ==========================================
def get_admin_managers(supabase, f_code):
    """
    施設の管理者として指定されているスタッフ名リストを取得。
    admin_settings に保存されていなければ、facilities.admin_email に紐づくスタッフを
    自動で初期管理者として登録してから返す。
    """
    import json as _json
    try:
        res = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "admin_managers").execute()
        if res.data and res.data[0].get("value"):
            try:
                lst = _json.loads(res.data[0]["value"])
                if isinstance(lst, list) and len(lst) > 0:
                    return lst
            except: pass
    except: pass

    # 空または未設定 → facilities.admin_email に紐づくスタッフを初期管理者に
    initial = []
    try:
        fac_res = supabase.table("facilities").select("admin_email").eq("facility_code", f_code).execute()
        admin_email = fac_res.data[0].get("admin_email") if fac_res.data else None
        if admin_email:
            staff_res = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("email", admin_email).eq("is_active", True).execute()
            if staff_res.data:
                initial = [s["staff_name"] for s in staff_res.data]
    except: pass

    # 初期値があれば保存
    if initial:
        try:
            existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "admin_managers").execute()
            value_json = _json.dumps(initial, ensure_ascii=False)
            if existing.data:
                supabase.table("admin_settings").update({"value": value_json}).eq("facility_code", f_code).eq("key", "admin_managers").execute()
            else:
                supabase.table("admin_settings").insert({
                    "facility_code": f_code, "key": "admin*********", "value": value_json
                }).execute()
        except: pass
    return initial

def is_admin_email_staff(supabase, f_code, my_name):
    """指定スタッフが facilities.admin_email に紐づく超管理者かを判定。
    緊急リカバリ用: admin_managers が空・誤操作で消えた場合でも
    施設作成時の管理者メール登録者は常に管理者として認める。"""
    if not my_name:
        return False
    try:
        fac_res = supabase.table("facilities").select("admin_email").eq("facility_code", f_code).execute()
        admin_email = fac_res.data[0].get("admin_email") if fac_res.data else None
        if not admin_email:
            return False
        st = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("email", admin_email).eq("is_active", True).execute()
        return any(s.get("staff_name") == my_name for s in (st.data or []))
    except: return False

def is_admin_user(supabase, f_code, my_name):
    """指定スタッフが管理者として認可されているかを判定。
    admin_managers リストに含まれているか、または facilities.admin_email
    に紐づくスタッフ(超管理者: 緊急リカバリ用) であれば True。"""
    if not my_name:
        return False
    # 1. admin_managers リスト
    managers = get_admin_managers(supabase, f_code)
    if my_name in managers:
        return True
    # 2. 緊急リカバリ: admin_email スタッフは常に管理者
    if is_admin_email_staff(supabase, f_code, my_name):
        return True
    return False

def is_board_editor_user(supabase, f_code, my_name, is_admin_authenticated=False):
    """指定スタッフが掲示板の編集削除権限を持つかを判定。
    管理者MENUにログイン中、または board_editors リストに含まれていればOK。"""
    if is_admin_authenticated:
        return True
    if not my_name:
        return False
def is_ledger_user(supabase, f_code, my_name, is_admin_authenticated=False):
    """Check if user can access ledger (admin_settings の ledger_users リストから判定)"""
    if is_admin_authenticated:
        return True
    if not my_name:
        return False
# pyright: reportUndefinedVariable=false
@app.route('/api/admin/toggle_ledger_access', methods=['POST'])
def api_toggle_ledger_access():
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "msg": "権限がありません"}), 403
    
    import json as _json
    f_code = session["f_code"]
    data = request.get_json()
    staff_name = data.get("staff_name")
    can_ledger = data.get("can_ledger", False)
    
    try:
        res = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "ledger_users").execute()
        
        if res.data:
            current_list = _json.loads(res.data[0].get("value") or "[]")
        else:
            current_list = []
        
        if can_ledger:
            if staff_name not in current_list:
                current_list.append(staff_name)
        else:
            current_list = [n for n in current_list if n != staff_name]
        
        new_value = _json.dumps(current_list, ensure_ascii=False)
        
        if res.data:
            supabase.table("admin_settings").update({"value": new_value}).eq("facility_code", f_code).eq("key", "ledger_users").execute()
        else:
            supabase.table("admin_settings").insert({
                "facility_code": f_code,
                "key": "ledger_users",
                "value": new_value
            }).execute()
        
        return jsonify({"success": True, "msg": f"{staff_name} の出納帳権限を更新"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500
    try:
        import json as _json
        res = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "ledger_users").execute()
        if res.data and res.data[0].get("value"):
            ledger_users = _json.loads(res.data[0]["value"])
            return str(my_name) in [str(n) for n in ledger_users]
        return False
    except:
        return False  
    try:
        import json as _json
        res = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "board_editors").execute()
        if res.data and res.data[0].get("value"):
            editors_list = _json.loads(res.data[0]["value"])
            if isinstance(editors_list, list) and my_name in editors_list:
                return True
    except: pass
    return False

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
                        expires_raw = fac_data.get("expires_at")
                        expires = None
                        if expires_raw not in (None, "", "None"):
                            try:
                                expires = datetime.fromisoformat(
                                    str(expires_raw).replace("Z", "+00:00")
                                )
                            except (ValueError, TypeError):
                                expires = None
                        if expires is not None and expires < datetime.now(timezone.utc):
                            error = "この施設コードの有効期限が切れています。"
                        else:
                            import hashlib
                            def verify_password(pw, hashed):
                                return hashlib.sha256(pw.encode()).hexdigest() == hashed

                            staff = supabase.table("staffs").select("*").eq(
                                "facility_code", f_code
                            ).eq("is_active", True).execute()

                            matched_staff = None
                            for s in staff.data:
                                if verify_password(password, s["password_hash"]):
                                    matched_staff = s
                                    break

                            if not matched_staff:
                                error = "パスワードが違います。"
                            else:
                                my_name = matched_staff["staff_name"]
                                session["f_code"] = f_code
                                session["my_name"] = my_name
                                session["saved_f_code"] = f_code
                                # ログイン成功時に管理者セッションフラグをクリア
                                # (前のユーザーが管理者だった場合に権限が引き継がれないように)
                                session["admin_authenticated"] = False
                                session["dev_authenticated"] = False
                                return redirect(url_for("top"))
            except Exception as e:
                error = f"ログイン中にエラーが発生しました: {e}"

    return render_template("login.html", error=error, saved_f_code=saved_f_code)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route('/api/whoami')
def api_whoami():
    """セッション情報を返すデバッグ用API"""
    return jsonify({
        "f_code": session.get("f_code"),
        "my_name": session.get("my_name"),
        "admin_authenticated": session.get("admin_authenticated", False),
        "dev_authenticated": session.get("dev_authenticated", False),
    })

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

    # タスク取得（自分が関わる未完了のみ）
    my_tasks = []
    try:
        task_res = supabase.table("tasks").select("id,title,due_date,priority,status,assigned_to,created_by").eq("facility_code", f_code).neq("status", "done").order("due_date").execute()
        # top-task-meta: 期限の緊急/超過フラグと優先度ラベルを付与
        from datetime import datetime as _dttsk, date as _dtsk
        _today_tsk = _dtsk.today()
        _prio_lbl = {"high": "高", "medium": "中", "low": "低"}
        for t in (task_res.data or []):
            if t.get("created_by") == my_name or my_name in (t.get("assigned_to") or []) or not t.get("assigned_to"):
                t["priority_label"] = _prio_lbl.get(t.get("priority") or "medium", "中")
                t["due_urgent"] = False
                t["overdue"] = False
                if t.get("due_date"):
                    try:
                        _dd = _dttsk.strptime(str(t["due_date"]), "%Y-%m-%d").date()
                        _diff = (_dd - _today_tsk).days
                        if _diff < 0:
                            t["overdue"] = True
                        elif _diff <= 7:
                            t["due_urgent"] = True
                    except Exception:
                        pass
                my_tasks.append(t)
    except:
        pass
    return render("top.html", f_code=f_code, my_name=my_name, records=records,
        birthday_users=get_birthday_users(supabase, f_code),
        my_tasks=my_tasks,
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

        _cat_for_check = request.form.get("category", "")
        if not sel or sel == "" or (not content and _cat_for_check != "休み連絡"):
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
                    must_read_flag = (request.form.get("must_read", "0") == "1")
                    category = (request.form.get("category", "") or "その他").strip()
                    if not category:
                        category = "その他"
                    # Session 33: 休み連絡カテゴリ専用フィールド(category=休み連絡 以外は None で保存)
                    leave_reporter_type = (request.form.get("leave_reporter_type", "") or "").strip()
                    leave_reporter_relation = (request.form.get("leave_reporter_relation", "") or "").strip()
                    if category != "休み連絡":
                        leave_reporter_type = None
                        leave_reporter_relation = None
                    else:
                        # 休み連絡だが値が空のとき(理論上クライアント側で弾かれているが念のため)も None に
                        if not leave_reporter_type:
                            leave_reporter_type = None
                        if not leave_reporter_relation:
                            leave_reporter_relation = None
                    # 休み連絡の場合はcontentを自動生成
                    leave_date_start_val = (request.form.get("leave_date_start", "") or "").strip()
                    leave_date_end_val = (request.form.get("leave_date_end", "") or "").strip()
                    leave_reason_val = (request.form.get("leave_reason", "") or "").strip() if category == "休み連絡" else ""
                    # 複数日(飛び日)対応: leave_dates(カンマ区切り)があれば優先
                    leave_dates_raw = (request.form.get("leave_dates", "") or "").strip()
                    leave_dates_list = []
                    if leave_dates_raw:
                        leave_dates_list = [d.strip() for d in leave_dates_raw.split(",") if d.strip()]
                    if category == "休み連絡" and leave_dates_list:
                        # 複数日モード: 最小日/最大日をstart/endに、contentは全日列挙
                        try:
                            from datetime import datetime as _dtm0
                            _sorted = sorted(leave_dates_list, key=lambda x: _dtm0.strptime(x, "%Y-%m-%d"))
                            leave_date_start_val = _sorted[0]
                            leave_date_end_val = _sorted[-1]
                            _other_detail = (request.form.get("leave_other_detail", "") or "").strip()
                            content = _build_leave_content_multi(leave_dates_list, leave_reporter_type, _other_detail, leave_reason_val)
                        except Exception as _cem:
                            print(f"[休み連絡content生成エラー(複数日)] {_cem}", flush=True)
                    elif category == "休み連絡" and leave_date_start_val:
                        try:
                            from datetime import datetime as _dt
                            _ls = _dt.strptime(leave_date_start_val, "%Y-%m-%d")
                            _ls_str = f"{_ls.month}月{_ls.day}日"
                            _other_detail = (request.form.get("leave_other_detail", "") or "").strip()
                            if leave_date_end_val and leave_date_end_val != leave_date_start_val:
                                _le = _dt.strptime(leave_date_end_val, "%Y-%m-%d")
                                _period = f"{_ls_str}〜{_le.month}月{_le.day}日"
                            else:
                                _period = _ls_str
                            content = _build_leave_content(_period, leave_reporter_type, _other_detail, leave_reason_val)
                        except Exception as _ce:
                            print(f"[休み連絡content生成エラー] {_ce}", flush=True)
                    insert_res = supabase.table("records").insert({
                        "facility_code": f_code,
                        "chart_number": m.group(1),
                        "user_name": m.group(2),
                        "staff_name": my_name,
                        "content": content,
                        "created_at": dt_record.isoformat(),
                        "image_urls": image_urls if image_urls else None,
                        "must_read": must_read_flag,
                        "category": category,
                        "leave_reporter_type": leave_reporter_type,
                        "leave_reporter_relation": leave_reporter_relation,
                        "leave_date_start": leave_date_start_val if category == "休み連絡" else None,
                        "leave_date_end": (leave_date_end_val or leave_date_start_val) if category == "休み連絡" else None,
                        "leave_reason": leave_reason_val if category == "休み連絡" else None,
                    }).execute()

                    # Session 29 (B-4): AIタグ自動生成。失敗してもメイン処理は止めない
                    try:
                        new_id = None
                        if insert_res and getattr(insert_res, "data", None):
                            new_id = insert_res.data[0].get("id")
                        if new_id:
                            from utils import generate_search_tags
                            tags = generate_search_tags(content, category)
                            if tags:
                                supabase.table("records").update(
                                    {"search_tags": tags}
                                ).eq("id", new_id).execute()
                    except Exception as _tag_err:
                        print(f"[search_tags] generation failed for new record: {_tag_err}", flush=True)
                    # 休み連絡カテゴリ: カレンダーに自動登録
                    if category == "休み連絡" and new_id:
                        try:
                            user_name_for_cal = m.group(2)
                            # 登録する日付リストを決定（複数日優先、なければ単日/期間の開始日1件）
                            if leave_dates_list:
                                _cal_dates = sorted(set(leave_dates_list))
                            else:
                                _ls0 = (request.form.get("leave_date_start", "") or "").strip()
                                _le0 = (request.form.get("leave_date_end", "") or "").strip()
                                _cal_dates = [_ls0] if _ls0 else []
                                _single_end = _le0 or _ls0
                            if _cal_dates:
                                cal_id = _get_or_create_system_calendar(supabase, f_code, my_name)
                                if cal_id:
                                    first_event_id = None
                                    for _idx, _cd in enumerate(_cal_dates):
                                        # 単日/期間モードのときだけ end_date を期間終端にする。複数日モードは各日単独。
                                        if leave_dates_list:
                                            _ev_end = _cd
                                        else:
                                            _ev_end = _single_end or _cd
                                        cal_payload = {
                                            "facility_code": f_code,
                                            "calendar_id": cal_id,
                                            "title": f"{user_name_for_cal}様 お休み",
                                            "event_date": _cd,
                                            "end_date": _ev_end,
                                            "all_day": True,
                                            "color": "#e53935",
                                            "memo": content,
                                            "created_by": my_name,
                                            "record_id": new_id,
                                        }
                                        cal_res = supabase.table("calendar_events").insert(cal_payload).execute()
                                        _eid = None
                                        if cal_res.data:
                                            _eid = cal_res.data[0]["id"]
                                        else:
                                            fetch_res = supabase.table("calendar_events").select("id").eq("facility_code", f_code).eq("calendar_id", cal_id).eq("event_date", _cd).eq("created_by", my_name).order("id", desc=True).limit(1).execute()
                                            if fetch_res.data:
                                                _eid = fetch_res.data[0]["id"]
                                        if _eid and first_event_id is None:
                                            first_event_id = _eid
                                    # 後方互換: 記録のcalendar_event_idには先頭イベントをセット
                                    if first_event_id:
                                        supabase.table("records").update(
                                            {"calendar_event_id": first_event_id}
                                        ).eq("id", new_id).execute()
                                        print(f"[calendar sync] linked record {new_id} to {len(_cal_dates)} event(s), first={first_event_id}", flush=True)
                        except Exception as _cal_err:
                            print(f"[calendar sync] failed: {_cal_err}", flush=True)

                    # Session 36: VAS データを record_vas テーブルに一括 INSERT。失敗してもメイン処理は止めない
                    try:
                        if new_id:
                            vas_json = request.form.get("vas_records", "") or ""
                            vas_list = json.loads(vas_json) if vas_json.strip() else []
                            vas_rows = []
                            for v in vas_list:
                                if not isinstance(v, dict):
                                    continue
                                part = v.get("part")
                                side = v.get("side")
                                value = v.get("value")
                                if not part or not side:
                                    continue
                                if not isinstance(value, int) or value < 0 or value > 10:
                                    continue
                                vas_rows.append({
                                    "record_id": new_id,
                                    "facility_code": f_code,
                                    "user_name": m.group(2),
                                    "part": part,
                                    "side": side,
                                    "vas_value": value,
                                })
                            if vas_rows:
                                supabase.table("record_vas").insert(vas_rows).execute()
                                print(f"[vas_records] saved {len(vas_rows)} entries for record {new_id}", flush=True)
                    except Exception as _vas_err:
                        print(f"[vas_records] save failed for new record: {_vas_err}", flush=True)

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
            # Session 20: 当日記録の既読状況をまとめて取得
            day_record_ids = [r["id"] for r in res.data]
            my_read_ids = set()
            reads_by_record = {}
            if day_record_ids:
                try:
                    rr = supabase.table("record_reads").select("record_id, staff_name").eq("facility_code", f_code).in_("record_id", day_record_ids).execute()
                    if rr.data:
                        for row in rr.data:
                            rid = row["record_id"]
                            sname = row["staff_name"]
                            if rid not in reads_by_record:
                                reads_by_record[rid] = []
                            reads_by_record[rid].append(sname)
                            if sname == my_name:
                                my_read_ids.add(rid)
                except Exception:
                    pass

            # Session 36: 当日記録の VAS データをまとめて取得
            vas_by_record = {}
            if day_record_ids:
                try:
                    vr = supabase.table("record_vas").select("record_id, part, side, vas_value").eq("facility_code", f_code).in_("record_id", day_record_ids).execute()
                    if vr.data:
                        for row in vr.data:
                            rid = row["record_id"]
                            if rid not in vas_by_record:
                                vas_by_record[rid] = []
                            vas_by_record[rid].append({
                                "part": row["part"],
                                "side": row["side"],
                                "vas_value": row["vas_value"],
                            })
                except Exception as _vas_get_err:
                    print(f"[record_vas] fetch failed for daily_view: {_vas_get_err}", flush=True)

            for r in res.data:
                user = r["user_name"]
                if user not in records:
                    records[user] = {"ai_record": None, "normal_records": []}
                if r["staff_name"] == "AI統合記録":
                    records[user]["ai_record"] = r
                else:
                    r["time"] = parse_jst(r["created_at"])
                    r["can_edit"] = (str(r["staff_name"]) == str(my_name)) or is_admin
                    # Session 20: 既読情報を付与
                    r_reads = reads_by_record.get(r["id"], [])
                    r["read_staffs"] = r_reads
                    r["read_count"] = len(r_reads)
                    r["is_read_by_me"] = (r["id"] in my_read_ids)
                    # Session 36: VAS データを付与(なければ空配列)
                    r["vas_records"] = vas_by_record.get(r["id"], [])
                    # image_urlsをリスト型に正規化（None・空配列・JSON文字列対応）
                    raw_urls = r.get("image_urls")
                    if isinstance(raw_urls, list) and len(raw_urls) > 0:
                        r["image_urls"] = raw_urls
                    else:
                        r["image_urls"] = []
                    records[user]["normal_records"].append(r)
    except Exception as e:
        pass

    # 当月の記録がある日付リストを取得（カレンダーのドット表示用）
    record_dates = []
    photo_dates = []
    try:
        month_start = tokyo_tz.localize(datetime(selected_date.year, selected_date.month, 1))
        if selected_date.month == 12:
            next_month = tokyo_tz.localize(datetime(selected_date.year + 1, 1, 1))
        else:
            next_month = tokyo_tz.localize(datetime(selected_date.year, selected_date.month + 1, 1))
        month_res = supabase.table("records").select("created_at, image_urls").eq("facility_code", f_code).gte(
            "created_at", month_start.isoformat()
        ).lt("created_at", next_month.isoformat()).execute()
        if month_res.data:
            dates_set = set()
            photo_dates_set = set()
            for r in month_res.data:
                d = parse_jst_date(r["created_at"])
                ds = d.strftime("%Y-%m-%d")
                dates_set.add(ds)
                if r.get("image_urls"):
                    photo_dates_set.add(ds)
            record_dates = list(dates_set)
            photo_dates = list(photo_dates_set)
    except Exception as e:
        pass
    # Session 19: 利用者を user_kana ベースのあいうえお順にソート
    user_kana_map = {}
    try:
        p_res = supabase.table("patients").select("user_name, user_kana").eq("facility_code", f_code).execute()
        if p_res.data:
            for p in p_res.data:
                user_kana_map[p["user_name"]] = p.get("user_kana") or p["user_name"]
    except Exception as e:
        pass
    records = dict(sorted(records.items(), key=lambda x: user_kana_map.get(x[0], x[0])))
    # Session 19: 利用者検索用 PATIENTS リスト取得
    patients_list = []
    try:
        pl_res = supabase.table("patients").select("id, user_name, user_kana, chart_number").eq("facility_code", f_code).order("user_kana").execute()
        if pl_res.data:
            for p in pl_res.data:
                patients_list.append({
                    "id": p["id"],
                    "user_name": p["user_name"],
                    "user_kana": p.get("user_kana") or "",
                    "chart_number": str(p.get("chart_number") or ""),
                })
    except Exception as e:
        pass
    return render("daily_view.html",
        selected_date=selected_date_str,
        date_label=date_label,
        target_user=target_user,
        records=records,
        is_admin=is_admin,
        record_dates=record_dates,
        photo_dates=photo_dates,
        patients=patients_list
    )

# ===== Session 29 (B-5): ケース記録キーワード検索 =====
def _build_search_snippet(content_text, keywords, max_len=150, ctx=40):
    """検索結果用snippet。keywordsの最初のヒット位置周辺を抜粋。
    ヒットしなければ先頭max_len文字。"""
    if not content_text:
        return ""
    hit_pos = -1
    for kw in keywords:
        if not kw:
            continue
        i = content_text.find(kw)
        if i >= 0:
            hit_pos = i
            break
    if hit_pos < 0:
        return content_text[:max_len] + ("…" if len(content_text) > max_len else "")
    start = max(0, hit_pos - ctx)
    end = min(len(content_text), hit_pos + ctx + max_len // 2)
    snippet = content_text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(content_text):
        snippet = snippet + "…"
    return snippet

@app.route('/api/records/search')
@login_required
def api_records_search():
    """
    ケース記録キーワード検索API
    GET /api/records/search?q=褥瘡 入浴&category=入浴&user_name=石井&from=2025-05-01&to=2026-05-09
    返却: {"results":[{id, created_at, user_name, category, staff_name, content, snippet, search_tags}], "total":N, "limited":bool}
    """
    f_code = session["f_code"]
    supabase = get_supabase()

    q_raw = (request.args.get("q", "") or "").strip()
    category = (request.args.get("category", "") or "").strip()
    user_name = (request.args.get("user_name", "") or "").strip()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()

    # キーワードを空白(全角/半角)で分割。最大5語まで。
    keywords = []
    if q_raw:
        for tok in re.split(r'[\s\u3000]+', q_raw):
            tok = tok.strip()
            if tok:
                keywords.append(tok)
        keywords = keywords[:5]

    LIMIT = 5000

    try:
        query = supabase.table("records").select(
            "id, created_at, user_name, category, staff_name, content, search_tags"
        ).eq("facility_code", f_code)

        # キーワード AND 検索: contains演算子(@>)で全部含むレコードを絞り込み
        if keywords:
            query = query.contains("search_tags", keywords)

        if category:
            query = query.eq("category", category)
        if user_name:
            query = query.eq("user_name", user_name)
        if date_from:
            try:
                d = datetime.strptime(date_from, "%Y-%m-%d").date()
                t_start = tokyo_tz.localize(datetime.combine(d, dt_time.min))
                query = query.gte("created_at", t_start.isoformat())
            except Exception:
                pass
        if date_to:
            try:
                d = datetime.strptime(date_to, "%Y-%m-%d").date()
                t_end = tokyo_tz.localize(datetime.combine(d + timedelta(days=1), dt_time.min))
                query = query.lt("created_at", t_end.isoformat())
            except Exception:
                pass

        # AI統合記録は検索結果から除外
        query = query.neq("staff_name", "AI統合記録")

        # 新しい順、上限+1件で limited 判定
        query = query.order("created_at", desc=True).limit(LIMIT + 1)

        res = query.execute()
        rows = res.data or []
        limited = len(rows) > LIMIT
        if limited:
            rows = rows[:LIMIT]

        results = []
        for r in rows:
            content_text = r.get("content") or ""
            snippet = _build_search_snippet(content_text, keywords)
            results.append({
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "user_name": r.get("user_name") or "",
                "category": r.get("category") or "",
                "staff_name": r.get("staff_name") or "",
                "content": content_text,
                "snippet": snippet,
                "search_tags": r.get("search_tags") or [],
            })

        return jsonify({
            "results": results,
            "total": len(results),
            "limited": limited,
        })

    except Exception as e:
        return jsonify({"results": [], "total": 0, "limited": False, "error": str(e)}), 500


@app.route('/api/records/search/categories')
@login_required
def api_records_search_categories():
    """検索モーダルのカテゴリ選択肢を返す。
    標準4カテゴリ(入浴/食事/排泄/その他)を常に先頭に出し、
    Facility内で実際に使われている非標準カテゴリがあれば末尾に追加する。

    Supabase クライアントは select() がデフォルト1000件上限のため、
    レンジを大きく取って見落としを最小化する。
    """
    f_code = session["f_code"]
    supabase = get_supabase()
    standard = ["入浴", "食事", "排泄", "その他"]
    try:
        # 多めに取得して非標準カテゴリ拾い漏れを減らす。
        # 標準カテゴリしか使ってない通常運用ではこれで十分。
        res = (
            supabase.table("records")
            .select("category")
            .eq("facility_code", f_code)
            .neq("category", "")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        seen_extra = []
        seen_extra_set = set()
        for r in (res.data or []):
            c = (r.get("category") or "").strip()
            if not c or c in standard or c in seen_extra_set:
                continue
            seen_extra_set.add(c)
            seen_extra.append(c)
        ordered = standard + sorted(seen_extra)
        return jsonify({"categories": ordered})
    except Exception as e:
        # 失敗しても標準4カテゴリは返す
        return jsonify({"categories": standard, "error": str(e)}), 200


@app.route('/api/user_month_records')
@login_required
def api_user_month_records():
    """Session 19: 指定利用者の月内ケース記録を返す"""
    f_code = session["f_code"]
    my_name = session["my_name"]
    is_admin = session.get("admin_authenticated", False)
    supabase = get_supabase()
    try:
        user_id = int(request.args.get("user_id", 0))
        year = int(request.args.get("year", 0))
        month = int(request.args.get("month", 0))
    except:
        return jsonify({"status": "error", "message": "invalid params"}), 400
    if not (user_id and year and month):
        return jsonify({"status": "error", "message": "missing params"}), 400
    # patient_id から user_name を引く
    try:
        p_res = supabase.table("patients").select("user_name").eq("facility_code", f_code).eq("id", user_id).execute()
        if not p_res.data:
            return jsonify({"status": "error", "message": "patient not found"}), 404
        user_name = p_res.data[0]["user_name"]
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    # 月の開始/終了を計算
    month_start = tokyo_tz.localize(datetime(year, month, 1))
    if month == 12:
        next_month = tokyo_tz.localize(datetime(year + 1, 1, 1))
    else:
        next_month = tokyo_tz.localize(datetime(year, month + 1, 1))
    # records から user_name で絞り込み
    records_by_date = {}
    record_dates_set = set()
    try:
        res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", user_name).gte(
            "created_at", month_start.isoformat()
        ).lt("created_at", next_month.isoformat()).order("created_at").execute()
        if res.data:
            # Session 20: 既読情報をまとめて取得
            month_record_ids = [r["id"] for r in res.data]
            my_read_ids2 = set()
            reads_by_record2 = {}
            if month_record_ids:
                try:
                    rr2 = supabase.table("record_reads").select("record_id, staff_name").eq("facility_code", f_code).in_("record_id", month_record_ids).execute()
                    if rr2.data:
                        for row in rr2.data:
                            rid = row["record_id"]
                            sname = row["staff_name"]
                            if rid not in reads_by_record2:
                                reads_by_record2[rid] = []
                            reads_by_record2[rid].append(sname)
                            if sname == my_name:
                                my_read_ids2.add(rid)
                except Exception:
                    pass
            for r in res.data:
                d = parse_jst_date(r["created_at"]).strftime("%Y-%m-%d")
                record_dates_set.add(d)
                if d not in records_by_date:
                    records_by_date[d] = {"ai_record": None, "normal_records": []}
                if r["staff_name"] == "AI統合記録":
                    records_by_date[d]["ai_record"] = r
                else:
                    r["time"] = parse_jst(r["created_at"])
                    r["can_edit"] = (str(r["staff_name"]) == str(my_name)) or is_admin
                    # Session 20: 既読情報
                    r_reads2 = reads_by_record2.get(r["id"], [])
                    r["read_staffs"] = r_reads2
                    r["read_count"] = len(r_reads2)
                    r["is_read_by_me"] = (r["id"] in my_read_ids2)
                    records_by_date[d]["normal_records"].append(r)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    # 日付昇順で並べ替え
    sorted_dates = sorted(records_by_date.keys())
    sorted_records = {d: records_by_date[d] for d in sorted_dates}
    return jsonify({
        "status": "success",
        "user_name": user_name,
        "records_by_date": sorted_records,
        "record_dates": list(record_dates_set),
    })


# ===== Session 20: 必読バッジ・既読管理 API =====

@app.route('/api/toggle_must_read', methods=['POST'])
@login_required
def api_toggle_must_read():
    """ケース記録の must_read フラグを切り替え"""
    f_code = session["f_code"]
    my_name = session["my_name"]
    is_admin = session.get("admin_authenticated", False)
    supabase = get_supabase()
    try:
        data = request.get_json(silent=True) or {}
        record_id = int(data.get("record_id", 0))
        must_read = bool(data.get("must_read", False))
    except Exception:
        return jsonify({"status": "error", "message": "invalid params"}), 400
    if not record_id:
        return jsonify({"status": "error", "message": "record_id required"}), 400
    try:
        # 同一施設の記録か確認
        res = supabase.table("records").select("id, staff_name").eq("id", record_id).eq("facility_code", f_code).execute()
        if not res.data:
            return jsonify({"status": "error", "message": "record not found"}), 404
        # 権限: 投稿者本人 or 管理者のみ
        owner = res.data[0].get("staff_name") or ""
        if not is_admin and str(owner) != str(my_name):
            return jsonify({"status": "error", "message": "forbidden"}), 403
        supabase.table("records").update({"must_read": must_read}).eq("id", record_id).eq("facility_code", f_code).execute()
        # 自分が既読かどうかも返す(UIの分岐用)
        rd = supabase.table("record_reads").select("id").eq("record_id", record_id).eq("staff_name", my_name).limit(1).execute()
        is_read_by_me = bool(rd.data)
        return jsonify({"status": "success", "must_read": must_read, "is_read_by_me": is_read_by_me})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/mark_records_read', methods=['POST'])
@login_required
def api_mark_records_read():
    """指定された record_id 群を自分の既読としてマーク(掲示板の mark_all_read 相当)"""
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    try:
        data = request.get_json(silent=True) or {}
        record_ids = data.get("record_ids", [])
        record_ids = [int(x) for x in record_ids if x]
    except Exception:
        return jsonify({"status": "error", "message": "invalid params"}), 400
    if not record_ids:
        return jsonify({"status": "success", "marked_ids": []})
    try:
        # 既存の既読を取得して重複を避ける
        existing = supabase.table("record_reads").select("record_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("record_id", record_ids).execute()
        existing_ids = set(r["record_id"] for r in (existing.data or []))
        to_insert = [
            {"facility_code": f_code, "record_id": rid, "staff_name": my_name}
            for rid in record_ids if rid not in existing_ids
        ]
        if to_insert:
            supabase.table("record_reads").insert(to_insert).execute()
        return jsonify({"status": "success", "marked_ids": [x["record_id"] for x in to_insert]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/record_reads/<int:record_id>')
@login_required
def api_record_reads(record_id):
    """指定記録の既読スタッフ一覧"""
    f_code = session["f_code"]
    supabase = get_supabase()
    try:
        # 同一施設の記録か確認
        rec = supabase.table("records").select("id").eq("id", record_id).eq("facility_code", f_code).execute()
        if not rec.data:
            return jsonify({"status": "error", "message": "record not found"}), 404
        rr = supabase.table("record_reads").select("staff_name, read_at").eq("facility_code", f_code).eq("record_id", record_id).order("read_at").execute()
        names = []
        seen = set()
        for row in (rr.data or []):
            n = row.get("staff_name") or ""
            if n and n not in seen:
                seen.add(n)
                names.append(n)
        return jsonify({"status": "success", "read_staffs": names})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/records/unread_count')
@login_required
def api_records_unread_count():
    """自分にとって未読の必読ケース記録の件数を返す(全期間)"""
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    try:
        # 全期間の must_read=true な記録を取得
        res = supabase.table("records").select("id").eq("facility_code", f_code).eq("must_read", True).execute()
        if not res.data:
            return jsonify({"status": "success", "count": 0})
        must_read_ids = [r["id"] for r in res.data]
        # 自分が既読の record_id を取得
        rr = supabase.table("record_reads").select("record_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("record_id", must_read_ids).execute()
        read_ids = set(row["record_id"] for row in (rr.data or []))
        unread_count = sum(1 for rid in must_read_ids if rid not in read_ids)
        return jsonify({"status": "success", "count": unread_count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "count": 0}), 500


@app.route('/api/records/unread_list')
@login_required
def api_records_unread_list():
    """自分にとって未読の必読ケース記録の一覧(日付グループ化、新しい順)"""
    f_code = session["f_code"]
    my_name = session["my_name"]
    supabase = get_supabase()
    try:
        # 全期間の must_read=true な記録(本人投稿の AI統合記録は除外)
        res = supabase.table("records").select("*").eq("facility_code", f_code).eq("must_read", True).neq("staff_name", "AI統合記録").order("created_at", desc=True).execute()
        if not res.data:
            return jsonify({"status": "success", "groups": []})
        all_records = res.data
        all_ids = [r["id"] for r in all_records]
        # 自分が既読の record_id を取得
        rr = supabase.table("record_reads").select("record_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("record_id", all_ids).execute()
        read_ids = set(row["record_id"] for row in (rr.data or []))
        unread = [r for r in all_records if r["id"] not in read_ids]

        # 日付ごとにグループ化(JST基準)
        from collections import OrderedDict
        groups = OrderedDict()
        for r in unread:
            d = parse_jst_date(r["created_at"]).strftime("%Y-%m-%d")
            if d not in groups:
                groups[d] = []
            groups[d].append({
                "id": r["id"],
                "user_name": r.get("user_name") or "",
                "staff_name": r.get("staff_name") or "",
                "content": r.get("content") or "",
                "time": parse_jst(r["created_at"]),
                "image_urls": r.get("image_urls") or [],
                "created_at": r["created_at"],
            })
        out = []
        for d, items in groups.items():
            try:
                d_obj = datetime.strptime(d, "%Y-%m-%d")
                date_label = d_obj.strftime("%m月%d日 (") + "日月火水木金土"[d_obj.weekday()] + ")"
                date_label = d_obj.strftime("%m月%d日") + " (" + "月火水木金土日"[d_obj.weekday()] + ")"
            except Exception:
                date_label = d
            out.append({
                "date": d,
                "date_label": date_label,
                "records": items
            })
        return jsonify({"status": "success", "groups": out})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "groups": []}), 500


@app.route('/birthday')
@login_required
def birthday():
    f_code = session["f_code"]
    supabase = get_supabase()
    now = datetime.now(tokyo_tz)

    try:
        res = supabase.table("patients").select("user_name, user_kana, chart_number, birth_date").eq("facility_code", f_code).execute()
        pp_res = supabase.table("patient_profiles").select("user_name, birth_date").eq("facility_code", f_code).execute()
        pp_birth = {r["user_name"]: r["birth_date"] for r in (pp_res.data or []) if r.get("birth_date")}
        for r in (res.data or []):
            if not r.get("birth_date") and r["user_name"] in pp_birth:
                r["birth_date"] = pp_birth[r["user_name"]]
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

@app.route('/api/mark_all_read', methods=['POST'])
@login_required
def api_mark_all_read():
    """掲示板 + ケース記録を一括既読にする"""
    try:
        f_code = session['f_code']
        my_name = session['my_name']
        supabase = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()

        # --- 掲示板: 全ルームの last_read_at を更新 ---
        rooms_res = supabase.table('chat_members').select('room_id').eq('facility_code', f_code).eq('staff_name', my_name).execute()
        room_ids = [r['room_id'] for r in (rooms_res.data or [])]
        for room_id in room_ids:
            supabase.table('chat_members').update({'last_read_at': now_iso}).eq('room_id', room_id).eq('staff_name', my_name).execute()

        # --- ケース記録: 未読の must_read 記録を全て既読に ---
        must_res = supabase.table('records').select('id').eq('facility_code', f_code).eq('must_read', True).execute()
        all_ids = [r['id'] for r in (must_res.data or [])]
        if all_ids:
            existing = supabase.table('record_reads').select('record_id').eq('facility_code', f_code).eq('staff_name', my_name).in_('record_id', all_ids).execute()
            existing_ids = set(r['record_id'] for r in (existing.data or []))
            to_insert = [
                {'facility_code': f_code, 'record_id': rid, 'staff_name': my_name}
                for rid in all_ids if rid not in existing_ids
            ]
            if to_insert:
                supabase.table('record_reads').insert(to_insert).execute()

        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


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
    # 利用終了日が今日以前の人はバイタル対象候補から除外(終了日当日までは表示)
    patients = [p for p in patients if not (p.get("discontinued_date") and str(p["discontinued_date"]) < today)]

    # 各患者のweekdays・ampm・ampm_per_day取得
    # ★型不一致対策: patient_id は str() で統一(BIGINT vs string でマッチしない問題対応)
    # ★Session 18: ampm_per_day (JSONB) で曜日ごとの AM/PM/ALL/NONE を保持
    visit_days = {}
    ampm_data = {}
    ampm_per_day_data = {}
    try:
        int_id_map = {str(p["patient_int_id"]): p for p in patients if p.get("patient_int_id")}
        res = supabase.table("patient_visit_days").select("patient_id,weekdays,ampm,ampm_per_day").eq("facility_code", f_code).execute()
        for r in (res.data or []):
            pid = str(r["patient_id"])
            if pid not in int_id_map:
                continue
            visit_days[pid] = r.get("weekdays") or ""
            ampm_data[pid] = r.get("ampm") or "BOTH"
            apd = r.get("ampm_per_day")
            ampm_per_day_data[pid] = apd if isinstance(apd, dict) else {}
        for p in patients:
            int_id = str(p["patient_int_id"]) if p.get("patient_int_id") else ""
            p["weekdays"] = visit_days.get(int_id, "")
            p["ampm"] = ampm_data.get(int_id, "BOTH")
            p["ampm_per_day"] = ampm_per_day_data.get(int_id, {})
    except Exception as e:
        print(f"vitals visit_days fetch error: {e}", flush=True)
        for p in patients:
            p["weekdays"] = ""
            p["ampm"] = "BOTH"
            p["ampm_per_day"] = {}

    # 今日のバイタルデータ取得
    vitals_data = {}
    try:
        res = supabase.table("vitals").select("*").eq("facility_code", f_code).eq("measured_date", today).execute()
        for r in (res.data or []):
            vitals_data[str(r["patient_id"])] = r
    except Exception as e:
        print(f"vitals data fetch error: {e}", flush=True)

    # 今日除外されている利用者ID一覧を取得
    excludes_today = []
    try:
        res = supabase.table("vital_daily_excludes").select("patient_id").eq("facility_code", f_code).eq("excluded_date", today).execute()
        excludes_today = [str(r["patient_id"]) for r in (res.data or [])]
    except Exception as e:
        print(f"vitals excludes fetch error: {e}", flush=True)

    settings = get_vital_settings(supabase, f_code)
    # ★patient_id は文字列キーで統一(JS側で String(p.id) と比較されるため)
    visit_days_map = {str(p["id"]): p["weekdays"] for p in patients}
    ampm_map = {str(p["id"]): p["ampm"] for p in patients}
    # ★Session 18: 曜日ごとの AM/PM/ALL 状態
    ampm_per_day_map = {str(p["id"]): p["ampm_per_day"] for p in patients}

    return render("vitals.html",
        patients=patients,
        visit_days=visit_days_map,
        ampm_data=ampm_map,
        ampm_per_day=ampm_per_day_map,
        vitals_data=vitals_data,
        excludes_today=excludes_today,
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

@app.route('/api/vital_voice_parse', methods=['POST'])
@login_required
def api_vital_voice_parse():
    """音声を Gemini で解析して血圧・脈拍・体温・SpO2 を抽出（音声は永続保存しない）"""
    try:
        from utils import get_generative_model
        audio = request.files.get('audio')
        if not audio:
            return jsonify({"status": "error", "message": "音声なし"})
        filename = (audio.filename or '').lower()
        audio_bytes = audio.read()
        if not audio_bytes:
            return jsonify({"status": "error", "message": "音声データが空です"})
        # 極端に短い録音(無音とみなせる)は AI に送らず弾く。誤検出(捏造)防止。
        if len(audio_bytes) < 2048:
            return jsonify({"status": "error", "message": "音声が短すぎます。もう一度お話しください。"})

        # MIMEタイプ判定（parse_assessment_file と同じパターン + iOS Safari の audio/mp4 対応）
        ext_mime = {
            '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
            '.wav': 'audio/wav',  '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',  '.webm': 'audio/webm',
            '.mp4': 'audio/mp4',
        }
        mime = next((v for k, v in ext_mime.items() if filename.endswith(k)), 'audio/webm')

        prompt = """これは介護施設のスタッフがバイタル測定値を口頭で報告している音声です。
発話内容を文字起こしし、数値を抽出してください。

抽出ルール:
- 「血圧上」「血圧の上」「収縮期」「上が」→ bp_high(整数)
- 「血圧下」「血圧の下」「拡張期」「下が」→ bp_low(整数)
- 「脈拍」「脈」「心拍」 → pulse(整数)
- 「体温」「熱」 → temperature(小数点1桁、例:36.5)
- 「SpO2」「酸素」「酸素飽和度」「サチュレーション」 → spo2(整数、80~100の範囲)
- 数値以外の発話(様子・気づき)があれば memo に格納
- 言及のない項目は null
- 数値の言い間違い(例:「ひゃくにじゅう」=120)も整数化する

JSON形式のみで返してください(説明文・コードブロック禁止):

{
  "transcript": "発話の全文書き起こし",
  "bp_high": 整数 or null,
  "bp_low": 整数 or null,
  "pulse": 整数 or null,
  "temperature": 小数 or null,
  "spo2": 整数 or null,
  "memo": "数値以外の発話、なければ空文字"
}"""

        model = get_generative_model()
        resp = model.generate_content([{"mime_type": mime, "data": audio_bytes}, prompt])
        import re as _re, json as _json
        m = _re.search(r'\{.*\}', resp.text.strip(), _re.DOTALL)
        if m:
            result = _json.loads(m.group())
            return jsonify({"status": "success", **result})
        return jsonify({"status": "error", "message": "音声を認識できませんでした。もう一度お試しください。"})
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
        res = supabase.table("vitals").select("*").eq("facility_code", f_code).eq("patient_id", patient_id).order("measured_date", desc=True).limit(1825).execute()
        return jsonify({"vitals": res.data or []})
    except Exception as e:
        return jsonify({"vitals": [], "error": str(e)})

@app.route('/api/get_all_visit_days', methods=['GET'])
@login_required
def api_get_all_visit_days():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        vd_res = supabase.table('patient_visit_days').select('patient_id,weekdays,ampm_per_day').eq('facility_code', f_code).execute()
        pt_res = supabase.table('patients').select('id').eq('facility_code', f_code).execute()
        int_ids = {str(p['id']) for p in (pt_res.data or [])}
        result = {}
        for r in (vd_res.data or []):
            pid = str(r['patient_id'])
            if pid in int_ids:
                result[pid] = {'weekdays': r.get('weekdays',''), 'ampm_per_day': r.get('ampm_per_day') or {}}
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/save_visit_day', methods=['POST'])
@login_required
def api_save_visit_day():
    """利用曜日を保存。Session 18 から ampm_per_day も任意で保存可能。"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        # 後方互換: ampm_per_day が来ていれば一緒に保存
        raw_wd = data.get("weekdays", "") or ""
        normalized_wd = "".join(sorted(set(raw_wd.replace(",",""))))
        update_payload = {"weekdays": normalized_wd}
        insert_payload = {
            "facility_code": f_code,
            "patient_id": data["patient_id"],
            "user_name": data["user_name"],
            "weekdays": normalized_wd,
        }
        if "ampm_per_day" in data:
            update_payload["ampm_per_day"] = data["ampm_per_day"]
            insert_payload["ampm_per_day"] = data["ampm_per_day"]
        existing = supabase.table("patient_visit_days").select("id").eq("facility_code", f_code).eq("patient_id", data["patient_id"]).execute()
        if existing.data:
            supabase.table("patient_visit_days").update(update_payload).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("patient_visit_days").insert(insert_payload).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"save_visit_day error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_weekday_ampm', methods=['POST'])
@login_required
def api_save_weekday_ampm():
    """単一曜日の状態(AM/PM/ALL/NONE)を ampm_per_day JSONB に保存。
    Session 18 で新設。後方互換のため weekdays カラムも同期更新する。
    payload: {patient_id, weekday("0"-"6"), state("AM"/"PM"/"ALL"/"NONE"), user_name?}
    """
    try:
        data = request.json
        f_code = session["f_code"]
        patient_id = str(data["patient_id"])
        weekday = str(data["weekday"])
        state = data["state"]
        if weekday not in "0123456":
            return jsonify({"status": "error", "message": "invalid weekday"}), 400
        if state not in ("AM", "PM", "ALL", "NONE"):
            return jsonify({"status": "error", "message": "invalid state"}), 400
        supabase = get_supabase()
        existing = supabase.table("patient_visit_days").select("id,ampm_per_day,weekdays,user_name").eq("facility_code", f_code).eq("patient_id", patient_id).execute()
        if existing.data:
            row = existing.data[0]
            current_map = row.get("ampm_per_day")
            if not isinstance(current_map, dict):
                current_map = {}
            old_weekdays = row.get("weekdays") or ""
            if state == "NONE":
                current_map.pop(weekday, None)
                new_weekdays = old_weekdays.replace(weekday, "")
            else:
                current_map[weekday] = state
                if weekday not in old_weekdays:
                    new_weekdays = "".join(sorted(set(old_weekdays + weekday)))
                else:
                    new_weekdays = old_weekdays
            supabase.table("patient_visit_days").update({
                "ampm_per_day": current_map,
                "weekdays": new_weekdays,
            }).eq("id", row["id"]).execute()
            return jsonify({"status": "success", "ampm_per_day": current_map, "weekdays": new_weekdays})
        else:
            user_name = data.get("user_name", "")
            if not user_name:
                p_res = supabase.table("patients").select("user_name").eq("facility_code", f_code).eq("id", patient_id).execute()
                if p_res.data:
                    user_name = p_res.data[0].get("user_name", "")
            initial_map = {} if state == "NONE" else {weekday: state}
            initial_weekdays = "" if state == "NONE" else weekday
            supabase.table("patient_visit_days").insert({
                "facility_code": f_code,
                "patient_id": patient_id,
                "user_name": user_name,
                "weekdays": initial_weekdays,
                "ampm_per_day": initial_map,
            }).execute()
            return jsonify({"status": "success", "ampm_per_day": initial_map, "weekdays": initial_weekdays})
    except Exception as e:
        print(f"save_weekday_ampm error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

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

# ========== バイタル編集API(2026-05-01:複数測定対応) ==========
@app.route('/api/add_vital', methods=['POST'])
@login_required
def api_add_vital():
    """新規測定をINSERT(同じpatient_id+date があっても新しいレコード作成)"""
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()

        if not data.get("patient_id") or not data.get("measured_date"):
            return jsonify({"status": "error", "message": "patient_idとmeasured_dateは必須です"}), 400

        payload = {
            "facility_code": f_code,
            "patient_id": str(data.get("patient_id")),
            "user_name": data.get("user_name", ""),
            "measured_date": data.get("measured_date"),
            "measured_at": data.get("measured_at") or now_iso,
            "bp_high": data.get("bp_high"),
            "bp_low": data.get("bp_low"),
            "pulse": data.get("pulse"),
            "temperature": data.get("temperature"),
            "spo2": data.get("spo2"),
            "note": data.get("note", ""),
            "recheck": data.get("recheck", False),
            "staff_name": my_name,
        }
        res = supabase.table("vitals").insert(payload).execute()
        rid = res.data[0]["id"] if res.data else None
        return jsonify({"status": "success", "id": rid})
    except Exception as e:
        print(f"add_vital error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_vital', methods=['POST'])
@login_required
def api_update_vital():
    """既存測定をid指定でUPDATE"""
    try:
        data = request.json
        supabase = get_supabase()
        rid = data.get("id")
        if not rid:
            return jsonify({"status": "error", "message": "idは必須です"}), 400
        payload = {
            "bp_high": data.get("bp_high"),
            "bp_low": data.get("bp_low"),
            "pulse": data.get("pulse"),
            "temperature": data.get("temperature"),
            "spo2": data.get("spo2"),
            "note": data.get("note", ""),
            "recheck": data.get("recheck", False),
        }
        if data.get("measured_at"):
            payload["measured_at"] = data["measured_at"]
        supabase.table("vitals").update(payload).eq("id", rid).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"update_vital error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/bulk_temp_smart_save', methods=['POST'])
@login_required
def api_bulk_temp_smart_save():
    try:
        data = request.json
        f_code = session['f_code']
        my_name = session['my_name']
        supabase = get_supabase()
        patient_id = str(data.get('patient_id'))
        temperature = data.get('temperature')
        measured_date = data.get('measured_date')
        user_name = data.get('user_name', '')
        if not patient_id or temperature is None or not measured_date:
            return jsonify({'status': 'error', 'message': 'missing params'}), 400
        existing = supabase.table('vitals').select('id,temperature').eq('facility_code', f_code).eq('patient_id', patient_id).eq('measured_date', measured_date).order('measured_at', desc=True).execute()
        target = None
        for rec in (existing.data or []):
            if rec.get('temperature') is None:
                target = rec
                break
        now_iso = datetime.now(timezone.utc).isoformat()
        if target:
            supabase.table('vitals').update({'temperature': temperature, 'staff_name': my_name}).eq('id', target['id']).execute()
            return jsonify({'status': 'success', 'action': 'update', 'id': target['id']})
        else:
            res = supabase.table('vitals').insert({'facility_code': f_code, 'patient_id': patient_id, 'user_name': user_name, 'measured_date': measured_date, 'measured_at': now_iso, 'temperature': temperature, 'staff_name': my_name}).execute()
            rid = res.data[0]['id'] if res.data else None
            return jsonify({'status': 'success', 'action': 'insert', 'id': rid})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/delete_vital', methods=['POST'])
@login_required
def api_delete_vital():
    """測定をid指定でDELETE"""
    try:
        data = request.json
        supabase = get_supabase()
        rid = data.get("id")
        if not rid:
            return jsonify({"status": "error", "message": "idは必須です"}), 400
        supabase.table("vitals").delete().eq("id", rid).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"delete_vital error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# ========== 再検査予約API(2026-05-02:アラーム機能 Step 2) ==========
@app.route('/api/recheck_schedule', methods=['POST'])
@login_required
def api_recheck_schedule_post():
    """再検査予約を登録"""
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()

        if not data.get("patient_id") or not data.get("scheduled_at"):
            return jsonify({"status": "error", "message": "patient_idとscheduled_atは必須です"}), 400

        payload = {
            "facility_code": f_code,
            "patient_id": str(data.get("patient_id")),
            "user_name": data.get("user_name", ""),
            "vital_id": data.get("vital_id"),
            "scheduled_at": data.get("scheduled_at"),
            "note": data.get("note", ""),
            "is_completed": False,
            "created_by": my_name,
        }
        res = supabase.table("vital_recheck_schedules").insert(payload).execute()
        rid = res.data[0]["id"] if res.data else None
        return jsonify({"status": "success", "id": rid})
    except Exception as e:
        print(f"recheck_schedule_post error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/recheck_schedule', methods=['GET'])
@login_required
def api_recheck_schedule_get():
    """指定日の再検査予約一覧を取得(デフォルトは今日)"""
    try:
        f_code = session["f_code"]
        date = request.args.get("date", datetime.now(tokyo_tz).strftime("%Y-%m-%d"))
        only_pending = request.args.get("only_pending", "false").lower() == "true"
        supabase = get_supabase()

        # 当日の予約を時刻順で取得
        start = f"{date}T00:00:00+09:00"
        end = f"{date}T23:59:59+09:00"
        q = supabase.table("vital_recheck_schedules").select("*").eq("facility_code", f_code) \
            .gte("scheduled_at", start).lte("scheduled_at", end)
        if only_pending:
            q = q.eq("is_completed", False)
        res = q.order("scheduled_at").execute()
        return jsonify({"schedules": res.data or []})
    except Exception as e:
        print(f"recheck_schedule_get error: {e}", flush=True)
        return jsonify({"schedules": [], "error": str(e)})

@app.route('/api/recheck_schedule/complete', methods=['POST'])
@login_required
def api_recheck_schedule_complete():
    """再検査予約を完了マーク"""
    try:
        data = request.json
        rid = data.get("id")
        if not rid:
            return jsonify({"status": "error", "message": "idは必須です"}), 400
        supabase = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("vital_recheck_schedules").update({
            "is_completed": True,
            "completed_at": now_iso,
        }).eq("id", rid).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"recheck_schedule_complete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/recheck_schedule/snooze', methods=['POST'])
@login_required
def api_recheck_schedule_snooze():
    """再検査予約をN分後にスヌーズ(scheduled_atを更新)"""
    try:
        data = request.json
        rid = data.get("id")
        minutes = int(data.get("minutes", 10))
        if not rid:
            return jsonify({"status": "error", "message": "idは必須です"}), 400
        if minutes < 1 or minutes > 240:
            return jsonify({"status": "error", "message": "minutesは1〜240の範囲で指定してください"}), 400
        supabase = get_supabase()
        new_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        supabase.table("vital_recheck_schedules").update({
            "scheduled_at": new_at,
        }).eq("id", rid).execute()
        return jsonify({"status": "success", "scheduled_at": new_at})
    except Exception as e:
        print(f"recheck_schedule_snooze error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/recheck_schedule/<int:rid>', methods=['DELETE'])
@login_required
def api_recheck_schedule_delete(rid):
    """再検査予約を削除"""
    try:
        supabase = get_supabase()
        supabase.table("vital_recheck_schedules").delete().eq("id", rid).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"recheck_schedule_delete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# ===== app-updates-api-v1: アップデート情報 =====
@app.route('/api/app_updates', methods=['GET'])
@login_required
def api_app_updates_get():
    """アップデート情報一覧（公開分のみ、新しい順）。全ユーザー閲覧可。"""
    try:
        supabase = get_supabase()
        include_unpub = request.args.get("all", "false").lower() == "true" and session.get("dev_authenticated")
        q = supabase.table("app_updates").select("*")
        if not include_unpub:
            q = q.eq("is_published", True)
        res = q.order("sort_order", desc=True).order("created_at", desc=True).execute()
        return jsonify({"updates": res.data or []})
    except Exception as e:
        print(f"app_updates_get error: {e}", flush=True)
        return jsonify({"updates": [], "error": str(e)})

@app.route('/api/app_updates', methods=['POST'])
@login_required
def api_app_updates_post():
    """アップデート情報の新規/更新（開発者のみ）。idがあれば更新、なければ新規。"""
    if not session.get("dev_authenticated"):
        return jsonify({"status": "error", "message": "開発者認証が必要です"}), 403
    try:
        data = request.json or {}
        version = (data.get("version") or "").strip()
        body = (data.get("body") or "").strip()
        if not version or not body:
            return jsonify({"status": "error", "message": "versionとbodyは必須です"}), 400
        supabase = get_supabase()
        payload = {
            "version": version,
            "release_date": (data.get("release_date") or "").strip(),
            "body": body,
            "sort_order": int(data.get("sort_order") or 0),
            "is_published": bool(data.get("is_published", True)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        uid = data.get("id")
        if uid:
            supabase.table("app_updates").update(payload).eq("id", uid).execute()
            return jsonify({"status": "success", "id": uid})
        res = supabase.table("app_updates").insert(payload).execute()
        nid = res.data[0]["id"] if res.data else None
        return jsonify({"status": "success", "id": nid})
    except Exception as e:
        print(f"app_updates_post error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/app_updates/<uid>', methods=['DELETE'])
@login_required
def api_app_updates_delete(uid):
    """アップデート情報の削除（開発者のみ）。"""
    if not session.get("dev_authenticated"):
        return jsonify({"status": "error", "message": "開発者認証が必要です"}), 403
    try:
        supabase = get_supabase()
        supabase.table("app_updates").delete().eq("id", uid).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"app_updates_delete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_vital_settings', methods=['POST'])
@login_required
def api_save_vital_settings():
    try:
        data = request.json or {}
        f_code = session["f_code"]
        supabase = get_supabase()
        # Supabase テーブルに存在しないキーが含まれると 500 になるので
        # DEFAULT_VITAL_SETTINGS で定義されたキーだけに絞り込む
        allowed = set(DEFAULT_VITAL_SETTINGS.keys())
        clean = {k: v for k, v in data.items() if k in allowed}
        payload = {**clean, "facility_code": f_code}
        existing = supabase.table("vital_alert_settings").select("id").eq("facility_code", f_code).execute()
        if existing.data:
            supabase.table("vital_alert_settings").update(payload).eq("facility_code", f_code).execute()
        else:
            supabase.table("vital_alert_settings").insert(payload).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[save_vital_settings] error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

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
# 利用者の本日除外・本日追加(2026-05-01 追加)
# ==========================================

@app.route('/api/vital_excludes', methods=['GET'])
@login_required
def api_vital_excludes_get():
    """指定日に今日だけ除外されている利用者ID一覧を取得"""
    try:
        f_code = session["f_code"]
        date_str = request.args.get("date") or datetime.now(tokyo_tz).strftime("%Y-%m-%d")
        supabase = get_supabase()
        res = supabase.table("vital_daily_excludes").select("patient_id").eq("facility_code", f_code).eq("excluded_date", date_str).execute()
        ids = [str(r["patient_id"]) for r in (res.data or [])]
        return jsonify({"status": "success", "patient_ids": ids, "date": date_str})
    except Exception as e:
        print(f"vital_excludes_get error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/vital_excludes', methods=['POST'])
@login_required
def api_vital_excludes_post():
    """利用者を「今日だけ除外」する"""
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        patient_id = str(data["patient_id"])
        date_str = data.get("date") or datetime.now(tokyo_tz).strftime("%Y-%m-%d")
        supabase = get_supabase()
        # UNIQUE(facility_code, patient_id, excluded_date) 制約があるので、既存チェック
        existing = supabase.table("vital_daily_excludes").select("id").eq("facility_code", f_code).eq("patient_id", patient_id).eq("excluded_date", date_str).execute()
        if existing.data:
            return jsonify({"status": "success", "message": "already excluded"})
        supabase.table("vital_daily_excludes").insert({
            "facility_code": f_code,
            "patient_id": patient_id,
            "excluded_date": date_str,
            "excluded_by": my_name,
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"vital_excludes_post error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/vital_excludes', methods=['DELETE'])
@login_required
def api_vital_excludes_delete():
    """除外解除(リストに復活)"""
    try:
        data = request.json
        f_code = session["f_code"]
        patient_id = str(data["patient_id"])
        date_str = data.get("date") or datetime.now(tokyo_tz).strftime("%Y-%m-%d")
        supabase = get_supabase()
        supabase.table("vital_daily_excludes").delete().eq("facility_code", f_code).eq("patient_id", patient_id).eq("excluded_date", date_str).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"vital_excludes_delete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/add_today_patient', methods=['POST'])
@login_required
def api_add_today_patient():
    """利用者を本日の曜日に追加する(既存利用者の場合はvisit_daysに今日の曜日を追記)"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        date_str = data.get("date") or datetime.now(tokyo_tz).strftime("%Y-%m-%d")
        # 曜日番号(0=日, 1=月, ..., 6=土)を計算
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        weekday_num = str((target_date.weekday() + 1) % 7)  # Python: 月=0,...,日=6 → JS: 日=0,...,土=6 に変換

        patient_id = data.get("patient_id")
        if patient_id:
            patient_id = str(patient_id)
            # 既存利用者: visit_daysに該当曜日を追記
            existing = supabase.table("patient_visit_days").select("id,weekdays,user_name,ampm_per_day").eq("facility_code", f_code).eq("patient_id", patient_id).execute()
            if existing.data:
                old_days = existing.data[0].get("weekdays") or ""
                if weekday_num not in old_days:
                    new_days = old_days + weekday_num
                    # weekdays だけでなく ampm_per_day(曜日ごとのAM/PM/ALL)も更新する。
                    # renderPatientList(vitals.html)は ampm_per_day を見て表示を絞るため、
                    # ここで当該曜日キーを入れないと「追加したのに一覧に出ない」状態になる。
                    apd = existing.data[0].get("ampm_per_day")
                    if not isinstance(apd, dict):
                        apd = {}
                    if weekday_num not in apd:
                        apd[weekday_num] = "ALL"
                    supabase.table("patient_visit_days").update({
                        "weekdays": new_days,
                        "ampm_per_day": apd,
                    }).eq("id", existing.data[0]["id"]).execute()
            else:
                # patient_visit_days行が無い場合は新規作成(user_name必要)
                user_name = data.get("user_name", "")
                if not user_name:
                    p_res = supabase.table("patient_profiles").select("user_name").eq("facility_code", f_code).eq("id", patient_id).execute()
                    if p_res.data:
                        user_name = p_res.data[0].get("user_name", "")
                supabase.table("patient_visit_days").insert({
                    "facility_code": f_code,
                    "patient_id": patient_id,
                    "user_name": user_name,
                    "weekdays": weekday_num,
                    "ampm_per_day": {weekday_num: "ALL"},
                }).execute()
            # 除外フラグが残っていたら解除(再追加=表示復活)
            supabase.table("vital_daily_excludes").delete().eq("facility_code", f_code).eq("patient_id", patient_id).eq("excluded_date", date_str).execute()
            return jsonify({"status": "success", "patient_id": patient_id})
        else:
            # 新規利用者作成
            user_name = (data.get("user_name") or "").strip()
            if not user_name:
                return jsonify({"status": "error", "message": "user_name required"}), 400
            new_p = supabase.table("patients").insert({
                "facility_code": f_code,
                "user_name": user_name,
                "user_kana": data.get("user_kana", ""),
                "chart_number": data.get("chart_number", "臨時"),
            }).execute()
            new_id = str(new_p.data[0]["id"])
            supabase.table("patient_visit_days").insert({
                "facility_code": f_code,
                "patient_id": new_id,
                "user_name": user_name,
                "weekdays": weekday_num,
                "ampm_per_day": {weekday_num: "ALL"},
            }).execute()
            return jsonify({"status": "success", "patient_id": new_id, "user_name": user_name, "is_new": True})
    except Exception as e:
        print(f"add_today_patient error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

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

        # 施設内の共有カレンダー(is_shared=true)を取得
        shared_res = supabase.table("calendars").select("*").eq("facility_code", f_code).eq("is_shared", True).execute()
        shared_cals = shared_res.data or []

        # 重複排除してマージ
        seen = set()
        for cal in own_cals + invited_cals + shared_cals:
            if cal["id"] not in seen:
                cal["is_owner"] = (cal.get("owner_name") == my_name) or is_admin_user(supabase, f_code, my_name)
                calendars.append(cal)
                seen.add(cal["id"])

        # デフォルトカレンダー自動作成は廃止（カテゴリ機能導入により）
        # 全削除時はユーザーが意図的に削除したと判断し、再作成しない
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

    # 管理者フラグをテンプレートに渡す
    try:
        is_admin = is_admin_user(supabase, f_code, my_name)
    except Exception:
        is_admin = False
    return render("calendar.html",
        calendars=calendars,
        events=events,
        stickers=STICKERS,
        event_colors=EVENT_COLORS,
        staffs=staffs,
        cal_members=cal_members,
        my_name=my_name,
        is_admin=is_admin,
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

        # ===== 複数日（飛び日）一括登録 =====
        _dates = data.get("dates")
        if isinstance(_dates, list) and len(_dates) > 0:
            _ids = []
            for _d in _dates:
                if not _d:
                    continue
                _p = dict(payload)
                _p["event_date"] = _d
                _p["end_date"] = _d
                _r = supabase.table("calendar_events").insert(_p).execute()
                if _r.data:
                    _ids.append(_r.data[0]["id"])
            return jsonify({"status": "success", "ids": _ids})

        event_id = data.get("id")
        if event_id:
            # 編集前にrecord_id（複数日リンク）を取得
            _pre = supabase.table("calendar_events").select("record_id").eq("id", event_id).eq("facility_code", f_code).execute()
            _linked_record_id = _pre.data[0].get("record_id") if _pre.data else None

            supabase.table("calendar_events").update(payload).eq("id", event_id).eq("facility_code", f_code).execute()
            new_event_date = payload.get("event_date")
            new_memo = payload.get("memo")

            # ===== 複数日リンク(record_id)方式: 紐づく全イベントの日付から記録を作り直す =====
            if _linked_record_id:
                try:
                    rec_q = supabase.table("records").select("id,leave_reporter_type,leave_reason,category").eq("id", _linked_record_id).execute()
                    if rec_q.data and rec_q.data[0].get("category") == "休み連絡":
                        rec0 = rec_q.data[0]
                        all_ev = supabase.table("calendar_events").select("id,event_date").eq("facility_code", f_code).eq("record_id", _linked_record_id).execute()
                        _dates_all = sorted([r["event_date"] for r in (all_ev.data or []) if r.get("event_date")])
                        if _dates_all:
                            _new_content = _build_leave_content_multi(_dates_all, rec0.get("leave_reporter_type") or "", "", rec0.get("leave_reason") or "")
                            supabase.table("records").update({
                                "content": _new_content,
                                "leave_date_start": _dates_all[0],
                                "leave_date_end": _dates_all[-1],
                            }).eq("id", _linked_record_id).execute()
                            # 紐づく全イベントのmemoも揃える
                            for r in (all_ev.data or []):
                                supabase.table("calendar_events").update({"memo": _new_content}).eq("id", r["id"]).execute()
                            print(f"[カレンダー同期(複数日)] record {_linked_record_id} を {len(_dates_all)} 日で再生成", flush=True)
                except Exception as _ml_err:
                    print(f"[calendar sync multi update] failed: {_ml_err}", flush=True)
                return jsonify({"status": "success", "id": event_id, "memo": payload.get("memo", "")})

            # 連動ケース記録の内容を更新（カレンダー→ケース記録）：従来の単日/期間方式
            if new_event_date or new_memo is not None:
                try:
                    rec_res = supabase.table("records").select("id,created_at,leave_reporter_type,leave_reason,category").eq("facility_code", f_code).eq("calendar_event_id", event_id).execute()
                    for rec in (rec_res.data or []):
                        update_payload = {}
                        # 日付変更時: created_atは入力日のまま保持。leave_date_start/endを更新しcontentを再生成
                        if new_event_date and rec.get("category") == "休み連絡":
                            update_payload["leave_date_start"] = new_event_date
                            update_payload["leave_date_end"] = payload.get("end_date") or new_event_date
                            # contentを再生成
                            try:
                                from datetime import datetime as _dt4
                                _ls4 = _dt4.strptime(new_event_date, "%Y-%m-%d")
                                _ls4_str = f"{_ls4.month}月{_ls4.day}日"
                                _end4 = payload.get("end_date") or new_event_date
                                if _end4 != new_event_date:
                                    _le4 = _dt4.strptime(_end4, "%Y-%m-%d")
                                    _period4 = f"{_ls4_str}〜{_le4.month}月{_le4.day}日"
                                else:
                                    _period4 = _ls4_str
                                _type4 = rec.get("leave_reporter_type") or ""
                                _reason4 = rec.get("leave_reason") or ""
                                update_payload["content"] = _build_leave_content(_period4, _type4, "", _reason4)
                            except Exception as _ce4:
                                print(f"[カレンダー同期 content再生成エラー] {_ce4}", flush=True)
                        # メモ（内容）更新（休み連絡以外の記録のみ）
                        if new_memo is not None and rec.get("category") != "休み連絡":
                            update_payload["content"] = new_memo
                        if update_payload:
                            supabase.table("records").update(update_payload).eq("id", rec["id"]).execute()
                            print(f"[カレンダー同期] record " + str(rec["id"]) + " を更新: " + str(list(update_payload.keys())), flush=True)
                except Exception as _upd_err:
                    print(f"[calendar sync update] failed: {_upd_err}", flush=True)
            # 休み連絡イベントの場合、memoも新しい日付で再生成
            try:
                ev_check = supabase.table("calendar_events").select("title").eq("id", event_id).execute()
                if ev_check.data:
                    title = ev_check.data[0].get("title", "")
                    if "お休み" in title and new_event_date:
                        # 対応するrecordのleave_reporter_typeを取得
                        rec_for_memo = supabase.table("records").select("leave_reporter_type, leave_reason").eq("facility_code", f_code).eq("calendar_event_id", event_id).limit(1).execute()
                        if rec_for_memo.data:
                            _type_m = rec_for_memo.data[0].get("leave_reporter_type") or ""
                            _reason_m = rec_for_memo.data[0].get("leave_reason") or ""
                            from datetime import datetime as _dtm
                            _ls_m = _dtm.strptime(new_event_date, "%Y-%m-%d")
                            _ls_m_str = f"{_ls_m.month}月{_ls_m.day}日"
                            _end_m = payload.get("end_date") or new_event_date
                            if _end_m != new_event_date:
                                _le_m = _dtm.strptime(_end_m, "%Y-%m-%d")
                                _period_m = f"{_ls_m_str}〜{_le_m.month}月{_le_m.day}日"
                            else:
                                _period_m = _ls_m_str
                            new_memo = _build_leave_content(_period_m, _type_m, "", _reason_m)
                            supabase.table("calendar_events").update({"memo": new_memo}).eq("id", event_id).execute()
                            print(f"[カレンダー同期] event {event_id} のmemoを更新: {new_memo}", flush=True)
            except Exception as _memo_err:
                print(f"[カレンダー同期 memo更新エラー] {_memo_err}", flush=True)
            # 最新のmemoを取得してレスポンスに含める
            try:
                updated_ev = supabase.table("calendar_events").select("memo").eq("id", event_id).execute()
                updated_memo = updated_ev.data[0]["memo"] if updated_ev.data else payload.get("memo", "")
            except:
                updated_memo = payload.get("memo", "")
            return jsonify({"status": "success", "id": event_id, "memo": updated_memo})
        else:
            res = supabase.table("calendar_events").insert(payload).execute()
            new_id = res.data[0]["id"] if res.data else None
            return jsonify({"status": "success", "id": new_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
def _get_or_create_system_calendar(supabase, f_code, owner_name):
    """TASUKARUケース記録連動カレンダーを取得または作成する"""
    res = supabase.table('calendars').select('id').eq('facility_code', f_code).eq('is_system', True).execute()
    if res.data:
        return res.data[0]['id']
    ins = supabase.table('calendars').insert({
        'facility_code': f_code,
        'name': 'TASUKARUケース記録連動',
        'color': '#e53935',
        'category': 'JOB',
        'owner_name': owner_name,
        'is_system': True,
        'is_private': False,
    }).execute()
    return ins.data[0]['id'] if ins.data else None


@app.route('/api/delete_calendar_event', methods=['POST'])
@login_required
def api_delete_calendar_event():
    try:
        data = request.json
        event_id = data.get("id")
        f_code = session["f_code"]
        supabase = get_supabase()
        # 削除対象イベントの情報を取得（record_id / 連動記録の特定のため）
        ev_info = supabase.table("calendar_events").select("id,record_id").eq("id", event_id).eq("facility_code", f_code).execute()
        target_record_id = None
        if ev_info.data:
            target_record_id = ev_info.data[0].get("record_id")

        # まずイベント自体を削除
        supabase.table("calendar_events").delete().eq("id", event_id).eq("facility_code", f_code).execute()

        if target_record_id:
            # 複数日リンク方式: 同じ記録に紐づく残りの「お休み」イベントを確認
            remain = supabase.table("calendar_events").select("id,event_date").eq("facility_code", f_code).eq("record_id", target_record_id).execute()
            remain_rows = remain.data or []
            if remain_rows:
                # 残りの日付からケース記録を作り直す（削除した日が文から消える）
                rec_q = supabase.table("records").select("id,leave_reporter_type,leave_reason,category").eq("id", target_record_id).execute()
                if rec_q.data:
                    rec0 = rec_q.data[0]
                    if rec0.get("category") == "休み連絡":
                        _dates = sorted([r["event_date"] for r in remain_rows if r.get("event_date")])
                        if _dates:
                            new_content = _build_leave_content_multi(_dates, rec0.get("leave_reporter_type") or "", "", rec0.get("leave_reason") or "")
                            supabase.table("records").update({
                                "content": new_content,
                                "leave_date_start": _dates[0],
                                "leave_date_end": _dates[-1],
                                "calendar_event_id": remain_rows[0]["id"],
                            }).eq("id", target_record_id).execute()
                            # 残りイベントのmemoも更新
                            for r in remain_rows:
                                supabase.table("calendar_events").update({"memo": new_content}).eq("id", r["id"]).execute()
            else:
                # 残りなし → ケース記録も削除
                supabase.table("records").delete().eq("id", target_record_id).execute()
        else:
            # 従来方式(record_id無し): calendar_event_idで逆引きして記録削除
            rec_res = supabase.table("records").select("id").eq("facility_code", f_code).eq("calendar_event_id", event_id).execute()
            for rec in (rec_res.data or []):
                supabase.table("records").delete().eq("id", rec["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/api/delete_calendar', methods=['POST'])
def api_delete_calendar():
    try:
        data = request.json
        calendar_id = data.get('id')
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        
        # カレンダーの権限確認（カテゴリで分岐）
        cal_res = supabase.table("calendars").select("owner_name,category,is_system").eq("id", calendar_id).eq("facility_code", f_code).execute()
        if not cal_res.data:
            return jsonify({"status": "error", "message": "カレンダーが見つかりません"}), 404
        cal_data = cal_res.data[0]
        if cal_data.get("is_system"):
            return jsonify({"status": "error", "message": "このカレンダーは削除できません"}), 403
        category = cal_data.get("category") or "PRIVATE"
        is_owner = (cal_data["owner_name"] == my_name)
        is_admin = is_admin_user(supabase, f_code, my_name)
        # JOB: 管理者のみ削除可。PRIVATE: 作成者+招待者+管理者
        if category == "JOB":
            if not is_admin:
                return jsonify({"status": "error", "message": "JOBカレンダーは管理者のみ削除できます"}), 403
        else:
            # PRIVATEは作成者または招待されたメンバーまたは管理者
            is_member = False
            if not (is_owner or is_admin):
                mem_res = supabase.table("calendar_members").select("staff_name").eq("calendar_id", calendar_id).eq("staff_name", my_name).execute()
                is_member = bool(mem_res.data)
            if not (is_owner or is_admin or is_member):
                return jsonify({"status": "error", "message": "削除権限がありません"}), 403
        
        # 関連する予定を削除
        supabase.table("calendar_events").delete().eq("calendar_id", calendar_id).execute()
        
        # カレンダーメンバーを削除
        supabase.table("calendar_members").delete().eq("calendar_id", calendar_id).execute()
        
        # カレンダーを削除
        supabase.table("calendars").delete().eq("id", calendar_id).execute()
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_calendar', methods=['POST'])
def api_update_calendar():
    try:
        data = request.json
        calendar_id = data.get('id')
        name = data.get('name')
        color = data.get('color')
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        
        # カレンダーの権限確認（カテゴリで分岐）
        cal_res = supabase.table("calendars").select("owner_name,category,is_system").eq("id", calendar_id).eq("facility_code", f_code).execute()
        if not cal_res.data:
            return jsonify({"status": "error", "message": "カレンダーが見つかりません"}), 404
        cal_data = cal_res.data[0]
        if cal_data.get("is_system"):
            return jsonify({"status": "error", "message": "このカレンダーは削除できません"}), 403
        category = cal_data.get("category") or "PRIVATE"
        is_owner = (cal_data["owner_name"] == my_name)
        is_admin = is_admin_user(supabase, f_code, my_name)
        # JOB: 管理者のみ編集可。PRIVATE: 作成者+招待者+管理者
        if category == "JOB":
            if not is_admin:
                return jsonify({"status": "error", "message": "JOBカレンダーは管理者のみ編集できます"}), 403
        else:
            is_member = False
            if not (is_owner or is_admin):
                mem_res = supabase.table("calendar_members").select("staff_name").eq("calendar_id", calendar_id).eq("staff_name", my_name).execute()
                is_member = bool(mem_res.data)
            if not (is_owner or is_admin or is_member):
                return jsonify({"status": "error", "message": "編集権限がありません"}), 403
        
        # カレンダー更新
        update_data = {}
        if name:
            update_data["name"] = name
        if color:
            update_data["color"] = color
            
        supabase.table("calendars").update(update_data).eq("id", calendar_id).execute()
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_calendar', methods=['POST'])
@login_required
def api_save_calendar():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        # カテゴリ判定（デフォルトはPRIVATE）
        category = data.get("category", "PRIVATE")
        if category not in ("JOB", "PRIVATE"):
            category = "PRIVATE"
        # JOBカテゴリは管理者のみ作成可能
        if category == "JOB":
            if not is_admin_user(supabase, f_code, my_name):
                return jsonify({"status": "error", "message": "JOBカレンダーは管理者のみ作成できます"}), 403
        # is_shared/is_private はカテゴリに応じて自動設定
        is_shared = (category == "JOB")
        is_private = (category == "PRIVATE")
        res = supabase.table("calendars").insert({
            "facility_code": f_code,
            "name":       data["name"],
            "color":      data.get("color", "#1a73e8"),
            "is_private": is_private,
            "is_shared":  is_shared,
            "owner_name": my_name,
            "category":   category,
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
        my_name = session["my_name"]
        supabase = get_supabase()
        # カテゴリで招待権限を分岐
        cal = supabase.table("calendars").select("owner_name,category").eq("id", data["calendar_id"]).execute()
        if not cal.data:
            return jsonify({"status": "error", "message": "カレンダーが見つかりません"}), 404
        cal_data = cal.data[0]
        category = cal_data.get("category") or "PRIVATE"
        is_owner = (cal_data["owner_name"] == my_name)
        is_admin = is_admin_user(supabase, f_code, my_name)
        # JOB: 管理者のみ招待可。PRIVATE: 作成者のみ
        if category == "JOB":
            if not is_admin:
                return jsonify({"status": "error", "message": "JOBカレンダーへの招待は管理者のみ可能です"}), 403
        else:
            if not (is_owner or is_admin):
                return jsonify({"status": "error", "message": "招待は作成者のみ可能です"}), 403
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
        # 期間とイベント期間が重なるものを取得
        # (event_date <= date_to) AND (COALESCE(end_date, event_date) >= date_from)
        res = supabase.table("calendar_events").select("*").eq("facility_code", f_code).lte("event_date", date_to).order("event_date").execute()
        all_events = res.data or []
        events = [e for e in all_events if (e.get("end_date") or e.get("event_date")) >= date_from]
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})

# ==========================================

@app.route('/assessment')
@login_required
def assessment():
    """月次評価画面 (Session 38 Phase 2.B で全面刷新)

    旧: 自由文 6 個 + AI 生成 (assessments テーブル)
    新: 22 項目構造化フォーム + 過去評価フィルタ (patient_evaluations テーブル)
    """
    f_code = session["f_code"]
    my_name = session.get("my_name", "")
    supabase = get_supabase()
    patients = get_patients(supabase, f_code)


    this_month = datetime.now(tokyo_tz).strftime("%Y-%m")
    return render(
        "assessment.html",
        patients=patients,
        this_month=this_month,
        current_user=my_name,
    )


@app.route('/api/save_patient_evaluation', methods=['POST'])
@login_required
def api_save_patient_evaluation():
    """評価データの UPSERT (新規 or 更新を自動判定)"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        data["facility_code"] = f_code  # クライアント指定は無視 (セキュリティ)

        supabase = get_supabase()
        result = upsert_patient_evaluation(supabase, data, my_name)

        if result.get("success"):
            return jsonify({
                "status": "success",
                "id": result.get("id"),
                "mode": result.get("mode"),
            })
        else:
            status_code = 409 if result.get("conflict") else 400
            return jsonify({
                "status": "error",
                "message": result.get("error", "保存に失敗しました"),
                "conflict": result.get("conflict", False),
                "editing_by": result.get("editing_by", ""),
            }), status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _normalize_search_text(s):
    """検索用にテキストを正規化する。
    - 全空白(半角/全角)を除去
    - 小文字化
    assessment.html の evalFilterPatients(JS) と挙動を揃えるための共通処理。
    """
    if not s:
        return ""
    return re.sub(r"\s+", "", str(s)).lower()


def _hira_to_kata(s):
    """ひらがな → カタカナ"""
    return "".join(
        chr(ord(c) + 0x60) if "\u3041" <= c <= "\u3096" else c
        for c in (s or "")
    )


def _kata_to_hira(s):
    """カタカナ → ひらがな"""
    return "".join(
        chr(ord(c) - 0x60) if "\u30A1" <= c <= "\u30F6" else c
        for c in (s or "")
    )



def _voice_norm(s):
    """音声照合用の正規化。
    既存 _normalize_search_text(空白除去・小文字化) に加えて、
    カナ→ひら統一・長音/促音の揺れを吸収する。"""
    s = _normalize_search_text(s)
    s = _kata_to_hira(s)
    return s.replace("\u30fc", "").replace("\u3063", "")

def _voice_match_temp(ai_name, patients):
    """AIが返した氏名候補テキスト ai_name を、利用者リストに照合する。
    各 patient は dict: {patient_id/id, user_name, user_kana}
    返り値: (patient_dict or None, confidence) confidence in {"high","mid","none"}
    照合は漢字氏名・user_kana 両方の _voice_norm 値に対して行う。
    """
    import difflib
    q = _voice_norm(ai_name)
    if not q:
        return (None, "none")

    def keys_of(p):
        # 照合キー: 漢字氏名・読み仮名(フル) + 空白分割した姓/名
        ks = []
        nm = _voice_norm(p.get("user_name"))
        kn_raw = (p.get("user_kana") or "")
        kn = _voice_norm(kn_raw)
        if nm:
            ks.append(nm)
        if kn:
            ks.append(kn)
        # 姓名分離(空白あり)に対応: 元の user_kana を空白で割って各片も鍵に
        parts = re.split(r"[\s\u3000]+", str(kn_raw).strip())
        for part in parts:
            pv = _voice_norm(part)
            if pv and pv not in ks:
                ks.append(pv)
        return ks

    # --- 完全一致(漢字 or 読みフル or 姓/名) ---
    exact = []
    for p in patients:
        if q in keys_of(p):
            exact.append(p)
    if len(exact) == 1:
        return (exact[0], "high")
    if len(exact) >= 2:
        return (None, "none")  # 同名同読み複数 → あいまいで安全側

    # --- 部分一致(姓のみ・名のみ呼び / 前方後方包含) ---
    part_hits = []
    for p in patients:
        for k in keys_of(p):
            if len(q) >= 2 and len(k) >= 2 and (q in k or k in q):
                part_hits.append(p)
                break
    if len(part_hits) == 1:
        return (part_hits[0], "high")
    if len(part_hits) >= 2:
        return (None, "none")

    # --- fuzzy(読みの近さ) ---
    scored = []
    for p in patients:
        best = 0.0
        for k in keys_of(p):
            r = difflib.SequenceMatcher(None, q, k).ratio()
            if r > best:
                best = r
        scored.append((best, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] >= 0.8:
        # 2位と僅差なら曖昧 → mid 止まり、十分離れていれば mid(要確認)
        if len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08:
            return (scored[0][1], "mid")
        return (None, "none")
    return (None, "none")

def _patient_matches_query(patient, raw_query):
    """利用者1人が検索ワードに一致するか判定する。
    漢字氏名・ふりがな・カルテ番号のいずれかへの部分一致。
    空白は両側で無視。ひらがな/カタカナは相互変換して比較。
    assessment.html の evalFilterPatients(JS) と同じ判定。
    """
    q = _normalize_search_text(raw_query)
    if not q:
        return False
    q_kata = _hira_to_kata(q)
    q_hira = _kata_to_hira(q)

    name = _normalize_search_text(patient.get("user_name"))
    kana = _normalize_search_text(patient.get("user_kana"))
    chart = _normalize_search_text(patient.get("chart_number"))

    if q in name:
        return True
    if kana and (q in kana or q_kata in kana or q_hira in kana):
        return True
    if chart and q in chart:
        return True
    return False


@app.route('/api/get_patient_evaluations')
@login_required
def api_get_patient_evaluations():
    """過去評価の一覧取得 (過去の評価タブ用、フィルタ + ソート対応)"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()

        user_name = (request.args.get("user_name") or "").strip() or None
        ym_from = (request.args.get("from") or "").strip() or None
        ym_to = (request.args.get("to") or "").strip() or None
        sort_by = request.args.get("sort") or "year_month_desc"
        status_filter = request.args.get("status_filter") or "all"

        try:
            limit = int(request.args.get("limit") or 100)
            limit = max(1, min(500, limit))
        except ValueError:
            limit = 100

        # --- 利用者名フィルタ(漢字/ふりがな/カルテ番号、空白無視、ひらカナ相互) ---
        # 検索ワードを利用者マスタに当てて、一致した利用者の user_name 候補を作る。
        # patient_evaluations には user_name(漢字氏名)しか無いため、ふりがな・
        # カルテ番号での検索はマスタ経由で利用者を特定してから評価を絞る。
        matched_user_names = None  # None = フィルタなし(全件)
        if user_name:
            try:
                patients = get_patients(supabase, f_code)
            except Exception:
                patients = []
            matched = [
                p["user_name"] for p in patients
                if _patient_matches_query(p, user_name)
            ]
            # マスタに一致が無くても、評価データ側の user_name 直接一致を拾う
            # フォールバック(マスタ未登録のまま評価だけ存在するケースの保険)。
            if matched:
                # 重複除去(同名利用者がマスタに複数居る場合も1回でよい)
                matched_user_names = list(dict.fromkeys(matched))
            else:
                q_norm = _normalize_search_text(user_name)
                try:
                    fb = supabase.table("patient_evaluations") \
                        .select("user_name") \
                        .eq("facility_code", f_code) \
                        .execute()
                    fb_names = [
                        r["user_name"] for r in (fb.data or [])
                        if q_norm in _normalize_search_text(r.get("user_name"))
                    ]
                except Exception:
                    fb_names = []
                matched_user_names = list(dict.fromkeys(fb_names))  # 空なら[] = 該当なし

        records = fetch_patient_evaluations(
            supabase, f_code,
            user_names=matched_user_names,
            year_month_from=ym_from,
            year_month_to=ym_to,
            sort_by=sort_by,
            limit=limit,
        )

        if status_filter == "complete":
            records = [r for r in records if r["_status"]["color"] == "green"]
        elif status_filter == "partial":
            records = [r for r in records if r["_status"]["color"] == "orange"]
        elif status_filter == "incomplete":
            records = [r for r in records if r["_status"]["color"] == "red"]

        return jsonify({
            "status": "success",
            "evaluations": records,
            "total": len(records),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "evaluations": [], "total": 0}), 500


@app.route('/api/get_patient_evaluation')
@login_required
def api_get_patient_evaluation():
    """特定月の評価レコードを取得 (同月既存チェック + 自動ロード用)"""
    try:
        f_code = session["f_code"]
        user_name = (request.args.get("user_name") or "").strip()
        year_month = (request.args.get("year_month") or "").strip()

        if not user_name or not year_month:
            return jsonify({
                "status": "error",
                "message": "user_name と year_month が必要です"
            }), 400

        supabase = get_supabase()

        res = supabase.table("patient_evaluations") \
            .select("*") \
            .eq("facility_code", f_code) \
            .eq("user_name", user_name) \
            .eq("year_month", year_month) \
            .limit(1) \
            .execute()

        evaluation = (res.data or [None])[0]
        if evaluation:
            evaluation["_status"] = evaluation_status(evaluation)

        _goal_vals = get_initial_goal_values(supabase, f_code, user_name, year_month)
        initial_values = {
            "training_goal": get_initial_training_goal(supabase, f_code, user_name, year_month),
            "care_classification": get_initial_care_classification(supabase, f_code, user_name, year_month),
            **_goal_vals,
        }

        return jsonify({
            "status": "success",
            "evaluation": evaluation,
            "initial_values": initial_values,
        })
    except Exception as e:
        return jsonify({
            "status": "error", "message": str(e),
            "evaluation": None, "initial_values": {"training_goal": "", "care_classification": ""}
        }), 500


@app.route('/api/acquire_edit_lock', methods=['POST'])
@login_required
def api_acquire_edit_lock():
    """編集ロックを取得 (悲観的ロック、10 分タイムアウト)"""
    try:
        data = request.json or {}
        evaluation_id = data.get("evaluation_id")
        if not evaluation_id:
            return jsonify({"status": "error", "message": "evaluation_id が必要です"}), 400

        my_name = session.get("my_name", "")
        supabase = get_supabase()
        result = acquire_edit_lock(supabase, evaluation_id, my_name)

        if result.get("success"):
            return jsonify({"status": "success"})
        else:
            return jsonify({
                "status": "conflict",
                "editing_by": result.get("editing_by", ""),
                "editing_started_at": result.get("editing_started_at", ""),
                "lock_age_seconds": result.get("lock_age_seconds", 0),
                "error": result.get("error", ""),
            }), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/release_edit_lock', methods=['POST'])
@login_required
def api_release_edit_lock():
    """編集ロックを解放 (保存完了 or キャンセル時、Beacon API 対応)"""
    try:
        if request.is_json:
            data = request.json or {}
        else:
            try:
                import json as _json
                data = _json.loads(request.get_data(as_text=True) or "{}")
            except Exception:
                data = {}

        evaluation_id = data.get("evaluation_id")
        if not evaluation_id:
            return jsonify({"status": "success"})

        my_name = session.get("my_name", "")
        supabase = get_supabase()
        release_edit_lock(supabase, evaluation_id, my_name)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "success", "warning": str(e)})


# ==========================================
# 要望A 第1弾: 元データ収集 — ファイル文字化API
# ==========================================

@app.route('/api/evaluation/ingest_file', methods=['POST'])
@login_required
def api_evaluation_ingest_file():
    """
    入口3: アップロードされたファイルを文字化して返す。
    対応形式:
      音声系: mp3/m4a/wav/aac/ogg/webm → Gemini で文字起こし
      画像系: jpg/jpeg/png/heic         → Gemini で OCR
      文書系: txt                        → そのまま返す
              pdf                        → テキスト入りPDF はテキスト抽出、
                                           スキャンPDF は Gemini で OCR
    受け取り: multipart/form-data
      file       : アップロードファイル (必須)
      audio_mode : 'solo' or 'dialog'  (音声ファイル時のみ使用、省略時='solo')
    返す: {"status":"success","text":"文字化された全文"}
    第1弾は文字化のみ。要約・整理・構造化は一切しない。
    """
    try:
        from utils import get_generative_model, upload_audio_to_supabase
        import io

        f = request.files.get('file')
        if not f:
            return jsonify({"status": "error", "message": "ファイルがありません"}), 400

        filename  = (f.filename or '').lower()
        file_bytes = f.read()
        if not file_bytes:
            return jsonify({"status": "error", "message": "ファイルが空です"}), 400

        audio_mode = request.form.get('audio_mode', 'solo')  # 'solo' or 'dialog'

        # ---------- ファイル種別の判定 ----------
        audio_exts = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.webm'}
        image_exts = {'.jpg', '.jpeg', '.png', '.heic'}

        ext = ''
        for candidate in audio_exts | image_exts | {'.pdf', '.txt'}:
            if filename.endswith(candidate):
                ext = candidate
                break

        # ---------- txt: そのまま返す ----------
        if ext == '.txt':
            try:
                text = file_bytes.decode('utf-8')
            except UnicodeDecodeError:
                text = file_bytes.decode('shift_jis', errors='replace')
            return jsonify({"status": "success", "text": text.strip()})

        model = get_generative_model()

        # ---------- 音声: Gemini で文字起こし ----------
        if ext in audio_exts:
            mime_map = {
                '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
                '.wav': 'audio/wav',  '.aac': 'audio/aac',
                '.ogg': 'audio/ogg',  '.webm': 'audio/webm',
            }
            mime = mime_map.get(ext, 'audio/webm')

            # ストレージに一時保存（評価確定時に削除）
            f_code = session.get("f_code", "unknown")
            supabase = get_supabase()
            upload_audio_to_supabase(supabase, file_bytes, f.filename or 'audio', f_code)

            if audio_mode == 'dialog':
                prompt = """これは介護施設における機能訓練指導員と利用者の会話の録音です。
会話をそのまま文字起こししてください。

【厳守ルール】
・文字起こしに徹する。要約・整理・補完・推測・創作を一切しない
・可能であれば話者を区別し「スタッフ:」「利用者:」のように表記する
・話者の区別が困難な場合は区別なしで全文を文字起こしする
・聞き取れない箇所は[聞き取り不明瞭]と記載する（補完・推測は禁止）
・利用者の辻褄の合わない発言・事実と違って聞こえる発言も修正せずそのまま文字起こしする
・フィラー（「あー」「えー」等）はそのまま記載する"""
            else:
                prompt = """これは介護施設の機能訓練指導員が月次評価について口頭で述べた音声です。
発話内容をそのまま文字起こししてください。

【厳守ルール】
・文字起こしに徹する。要約・整理・補完・推測・創作を一切しない
・1人の発話として素直に文字起こしする
・聞き取れない箇所は[聞き取り不明瞭]と記載する（補完・推測は禁止）
・フィラー（「あー」「えー」等）はそのまま記載する"""

            resp = model.generate_content([{"mime_type": mime, "data": file_bytes}, prompt])
            return jsonify({"status": "success", "text": resp.text.strip()})

        # ---------- 画像: Gemini で OCR ----------
        if ext in image_exts:
            mime_map = {
                '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.png': 'image/png',  '.heic': 'image/heic',
            }
            mime = mime_map.get(ext, 'image/jpeg')
            prompt = """この画像に書かれている文字をすべてそのまま読み取ってください。

【厳守ルール】
・書かれている文字をそのまま読み取る。要約・整理・補完・推測・創作を一切しない
・判読できない文字は[判読不能]と記載する
・書かれていない情報を追加しない
・レイアウト（改行・段落）も元の形に近い形で再現する"""
            resp = model.generate_content([{"mime_type": mime, "data": file_bytes}, prompt])
            return jsonify({"status": "success", "text": resp.text.strip()})

        # ---------- PDF ----------
        if ext == '.pdf':
            # まずテキスト抽出を試みる（テキスト入りPDF）
            extracted = ""
            try:
                from pdfminer.high_level import extract_text as pdf_extract_text
                extracted = pdf_extract_text(io.BytesIO(file_bytes)).strip()
            except Exception:
                extracted = ""

            # テキストが十分に取れた場合はそのまま返す
            if len(extracted) > 50:
                return jsonify({"status": "success", "text": extracted})

            # テキストが少ない → スキャンPDF → 先頭ページを画像化してGemini OCR
            try:
                from PIL import Image as PILImage
                import fitz  # PyMuPDF（未インストール時は除外）
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                page = doc[0]
                mat = fitz.Matrix(2, 2)  # 解像度2倍
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("jpeg")
                prompt = """このPDFをスキャンした画像に書かれている文字をすべてそのまま読み取ってください。

【厳守ルール】
・書かれている文字をそのまま読み取る。要約・整理・補完・推測・創作を一切しない
・判読できない文字は[判読不能]と記載する
・書かれていない情報を追加しない"""
                resp = model.generate_content([{"mime_type": "image/jpeg", "data": img_bytes}, prompt])
                return jsonify({"status": "success", "text": resp.text.strip()})
            except ImportError:
                # PyMuPDF未インストール: Gemini に直接PDFバイトを渡す
                prompt = """このPDFに書かれている文字をすべてそのまま読み取ってください。

【厳守ルール】
・書かれている文字をそのまま読み取る。要約・整理・補完・推測・創作を一切しない
・判読できない文字は[判読不能]と記載する
・書かれていない情報を追加しない"""
                resp = model.generate_content([{"mime_type": "application/pdf", "data": file_bytes}, prompt])
                return jsonify({"status": "success", "text": resp.text.strip()})

        # 対応外の拡張子
        return jsonify({
            "status": "error",
            "message": f"対応していないファイル形式です（{ext or '不明'}）。"
                       "対応形式: mp3/m4a/wav/aac/ogg/webm/jpg/jpeg/png/heic/pdf/txt"
        }), 400

    except Exception as e:
        print(f"[ingest_file error] {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/api/evaluation/ai_fill', methods=['POST'])
@login_required
def api_evaluation_ai_fill():
    """文字起こし元データから訓練による変化・課題とその要因をAI生成"""
    try:
        from utils import get_generative_model
        import json as _json
        data = request.json or {}
        source_text = (data.get('source_data') or '').strip()
        char_count = int(data.get('char_count') or 200)
        if not source_text:
            return jsonify({"status": "error", "message": "元データが空です"}), 400

        model = get_generative_model()

        prompt = (
            "あなたは介護施設で働く機能訓練指導員（理学療法士・作業療法士・柔道整復師等）です。\n"
            "以下の元データをもとに、ケアマネージャーへの報告文として「訓練による変化」と「課題とその要因」の2項目を必ず両方作成してください。\n\n"
            "【厳守ルール】\n"
            "・必ず両方の項目に文章を生成する（片方だけにしない）\n"
            f"・各項目はそれぞれ約{char_count}文字で書く\n"
            "・機能訓練指導員（理学療法士・作業療法士・柔道整復師）の専門的視点でケアマネージャーへ伝える\n"
            "・堂すぎず碕けず、現場感のある丁寧な口調（です・ます調）\n"
            "・箇条書きは使わず、ひとつながりの文章で書く\n"
            "・職員名・利用者名・主語は不要\n"
            "・元データに明示されていない事実は絶対に書かない（ハルシネーション厳禁）\n"
            "・記録にない内容を補完・推測・創作しない\n\n"
            "【訓練による変化】\n"
            "・実施した訓練内容・頻度・身体機能の変化・改善点を記載\n"
            "・元データから読み取れる訓練関連の内容を必ず記載する\n\n"
            "【課題とその要因】\n"
            "・残存する問題点・その原因・今後対応が必要な点を記載\n"
            "・元データから読み取れる課題・継続すべき点を必ず記載する\n\n"
            "【出力形式】JSONのみ。前後の説明・マークダウン・コードブロック不要。\n"
            '{"changes_by_training": "訓練による変化の文章", "issues_and_causes": "課題とその要因の文章"}\n\n'
            "【元データ】\n"
            + source_text
        )

        resp = model.generate_content([prompt])
        raw = resp.text.strip()
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw).strip()
        raw = re.sub(r'```$', '', raw).strip()

        parsed = _json.loads(raw)
        return jsonify({
            "status": "success",
            "changes_by_training": parsed.get("changes_by_training", ""),
            "issues_and_causes":   parsed.get("issues_and_causes", ""),
        })

    except Exception as e:
        print(f"[ai_fill error] {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500



# ============================================================
# 出納帳機能 (Phase 1)
# アクセス制限: facility_code=cocokaraplus-5526 かつ 岸本洋幸のみ
# ============================================================
LEDGER_ALLOWED_FACILITY = 'cocokaraplus-5526'
LEDGER_ALLOWED_USER = '岸本洋幸'
LEDGER_DEV_FACILITY = 'DEMO001'
LEDGER_DEV_USER = 'デモ職員A'

@app.context_processor
def inject_can_ledger():
    try:
        f_code = session.get('f_code')
        my_name = session.get('my_name')
        if not f_code or not my_name:
            return {'can_ledger': False}
        allowed = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
        dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
        if not allowed and not dev:
            import json as _j
            supabase = get_supabase()
            # 施設レベルの許可確認
            fe = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "ledger_enabled").execute()
            facility_enabled = bool(fe.data and fe.data[0].get("value") == "true")
            if facility_enabled:
                # 施設内スタッフレベルの許可確認
                r = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "ledger_users").execute()
                lu = _j.loads(r.data[0]["value"]) if r.data else []
                allowed = my_name in lu
        return {'can_ledger': allowed or dev}
    except:
        return {'can_ledger': False}
@app.context_processor
def inject_is_dev_user():
    try:
        my_name = session.get('my_name')
        return {'is_dev_user': my_name in ['岸本洋幸', 'デモ職員A']}
    except:
        return {'is_dev_user': False}

def ledger_access_required(f):
    """出納帳専用アクセス制限デコレータ"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        _ok = (_fc == LEDGER_ALLOWED_FACILITY and _mn == LEDGER_ALLOWED_USER)
        _dev = (_fc == LEDGER_DEV_FACILITY and _mn == LEDGER_DEV_USER)
        # admin_settingsのledger_usersも確認
        try:
            import json as _j
            _sb = get_supabase()
            _r = _sb.table("admin_settings").select("value").eq("facility_code", _fc).eq("key", "ledger_users").execute()
            _lu = _j.loads(_r.data[0]["value"]) if _r.data else []
            _ok = _ok or (_mn in _lu)
        except: pass
        if not _ok and not _dev:
            return jsonify({'status': 'error', 'message': '権限がありません'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/ledger')
@login_required
def ledger():
    """出納帳トップページ"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    supabase = get_supabase()
    import json as _j2
    try:
        _r2 = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "ledger_users").execute()
        _lu2 = _j2.loads(_r2.data[0]["value"]) if _r2.data else []
        is_allowed = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER) or (my_name in _lu2)
    except:
        is_allowed = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    is_dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not is_allowed and not is_dev:
        return redirect('/top')
    # 勘定科目マスタ（なければ初期データを投入）
    acc_res = supabase.table('accounts').select('*').eq('facility_code', f_code).order('code').execute()
    accounts = acc_res.data or []
    if not accounts:
        # 初期勘定科目を投入
        default_accounts = [
            # 資産
            {'facility_code': f_code, 'code': '101', 'name': '現金', 'category': '資産', 'tax_type': 'none'},
            {'facility_code': f_code, 'code': '102', 'name': '普通預金', 'category': '資産', 'tax_type': 'none'},
            {'facility_code': f_code, 'code': '103', 'name': '売掛金', 'category': '資産', 'tax_type': 'none'},
            # 負債
            {'facility_code': f_code, 'code': '201', 'name': '買掛金', 'category': '負債', 'tax_type': 'none'},
            {'facility_code': f_code, 'code': '202', 'name': '未払金', 'category': '負債', 'tax_type': 'none'},
            {'facility_code': f_code, 'code': '203', 'name': '借入金', 'category': '負債', 'tax_type': 'none'},
            # 収益
            {'facility_code': f_code, 'code': '401', 'name': '介護報酬売上', 'category': '収益', 'tax_type': 'exempt'},
            {'facility_code': f_code, 'code': '402', 'name': '自費売上', 'category': '収益', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '403', 'name': '雑収入', 'category': '収益', 'tax_type': 'taxable'},
            # 費用
            {'facility_code': f_code, 'code': '501', 'name': '給与手当', 'category': '費用', 'tax_type': 'none'},
            {'facility_code': f_code, 'code': '502', 'name': '法定福利費', 'category': '費用', 'tax_type': 'none'},
            {'facility_code': f_code, 'code': '503', 'name': '地代家賃', 'category': '費用', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '504', 'name': '水道光熱費', 'category': '費用', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '505', 'name': '通信費', 'category': '費用', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '506', 'name': '消耗品費', 'category': '費用', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '507', 'name': '車両費', 'category': '費用', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '508', 'name': '外注費', 'category': '費用', 'tax_type': 'taxable'},
            {'facility_code': f_code, 'code': '509', 'name': '雑費', 'category': '費用', 'tax_type': 'taxable'},
        ]
        supabase.table('accounts').insert(default_accounts).execute()
        acc_res = supabase.table('accounts').select('*').eq('facility_code', f_code).order('code').execute()
        accounts = acc_res.data or []
    return render_template('ledger.html', accounts=accounts)


@app.route('/api/ledger/settings', methods=['GET'])
@login_required
def api_ledger_settings_get():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        # 設定取得
        s_res = supabase.table('ledger_settings').select('*').eq('facility_code', f_code).execute()
        settings = s_res.data[0] if s_res.data else {
            'facility_code': f_code,
            'auto_cash_fill': False,
            'divisions_enabled': False,
            'cash_fill_division_id': None,
        }
        # 事業部取得
        d_res = supabase.table('ledger_divisions').select('*').eq('facility_code', f_code).eq('is_active', True).order('id').execute()
        divisions = d_res.data or []
        # sekkotsu-settings-v1: \u4e8c\u6bb5\u968e\u30d5\u30e9\u30b0\u3092 settings \u306b\u4ed8\u52a0
        try:
            _fa = supabase.table('facilities').select('sekkotsu_mode_allowed').eq('facility_code', f_code).execute()
            settings['sekkotsu_mode_allowed'] = bool(_fa.data and _fa.data[0].get('sekkotsu_mode_allowed'))
        except Exception:
            settings['sekkotsu_mode_allowed'] = False
        settings['sekkotsu_mode_enabled'] = bool(settings.get('sekkotsu_mode_enabled'))
        # ledger-credit-mode-v1: クレカ明細モードフラグ
        settings['credit_mode_enabled'] = bool(settings.get('credit_mode_enabled'))
        return jsonify({'status': 'success', 'settings': settings, 'divisions': divisions})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/settings', methods=['POST'])
@login_required
def api_ledger_settings_save():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        _raw_div = data.get('cash_fill_division_id')
        payload = {
            'facility_code': f_code,
            'auto_cash_fill': data.get('auto_cash_fill', False),
            'divisions_enabled': data.get('divisions_enabled', False),
            'cash_fill_division_id': int(_raw_div) if _raw_div else None,
        }
        # sekkotsu-settings-v1: \u8a31\u53ef\u6e08\u307f\u65bd\u8a2d\u306e\u307f\u6709\u52b9\u5316\u3092\u8a31\u53ef\uff08\u7b2c\u4e00\u6bb5\u968e\u3092\u5c0a\u91cd\uff09
        if 'sekkotsu_mode_enabled' in data:
            _want = bool(data.get('sekkotsu_mode_enabled'))
            _allowed = False
            try:
                _fa = supabase.table('facilities').select('sekkotsu_mode_allowed').eq('facility_code', f_code).execute()
                _allowed = bool(_fa.data and _fa.data[0].get('sekkotsu_mode_allowed'))
            except Exception:
                _allowed = False
            payload['sekkotsu_mode_enabled'] = (_want and _allowed)
        # ledger-credit-mode-v1: 接骨院モードON時のみクレカ明細をON可
        if 'credit_mode_enabled' in data:
            _c_want = bool(data.get('credit_mode_enabled'))
            _sek_now = bool(payload.get('sekkotsu_mode_enabled', data.get('sekkotsu_mode_enabled')))
            if 'sekkotsu_mode_enabled' not in data:
                try:
                    _ls = supabase.table('ledger_settings').select('sekkotsu_mode_enabled').eq('facility_code', f_code).execute()
                    _sek_now = bool(_ls.data and _ls.data[0].get('sekkotsu_mode_enabled'))
                except Exception:
                    _sek_now = False
            payload['credit_mode_enabled'] = (_c_want and _sek_now)
        # upsert
        supabase.table('ledger_settings').upsert(payload, on_conflict='facility_code').execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/divisions', methods=['GET'])
@login_required
def api_ledger_divisions_get():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        res = supabase.table('ledger_divisions').select('*').eq('facility_code', f_code).order('id').execute()
        return jsonify({'status': 'success', 'divisions': res.data or []})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/division', methods=['POST'])
@login_required
def api_ledger_division_save():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        payload = {
            'facility_code': f_code,
            'name': data['name'],
            'is_active': True,
        }
        div_id = data.get('id')
        if div_id:
            supabase.table('ledger_divisions').update({'name': data['name']}).eq('id', div_id).eq('facility_code', f_code).execute()
            return jsonify({'status': 'success', 'id': div_id})
        else:
            res = supabase.table('ledger_divisions').insert(payload).execute()
            new_id = res.data[0]['id'] if res.data else None
            return jsonify({'status': 'success', 'id': new_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/division/<int:div_id>', methods=['DELETE'])
@login_required
def api_ledger_division_delete(div_id):
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        supabase.table('ledger_divisions').update({'is_active': False}).eq('id', div_id).eq('facility_code', f_code).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _ledger_recalc_day(supabase, f_code, target_date):
    """指定日の現金残高を再計算し、自動補填仕訳を更新する。
    現金自動補填機能ONの施設のみ実行。"""
    try:
        # 現金自動補填設定確認
        s_res = supabase.table('ledger_settings').select('auto_cash_fill,cash_fill_division_id').eq('facility_code', f_code).execute()
        if not s_res.data or not s_res.data[0].get('auto_cash_fill'):
            return  # 機能OFFなら何もしない

        fill_div_id = s_res.data[0].get('cash_fill_division_id')
        settings_data = s_res.data[0]

        # 現金科目取得
        cash_res = supabase.table('accounts').select('id,name').eq('facility_code', f_code).eq('code', '101').execute()
        if not cash_res.data:
            return
        cash_id = cash_res.data[0]['id']

        # 事業主借科目取得（補填用）
        owner_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('name', '事業主借').execute()
        if owner_res.data:
            owner_id = owner_res.data[0]['id']
        else:
            ins = supabase.table('accounts').insert({
                'facility_code': f_code, 'code': '300', 'name': '事業主借',
                'category': '純資産', 'tax_type': 'none',
            }).execute()
            owner_id = ins.data[0]['id'] if ins.data else cash_id

        # 事業間移動科目取得
        transfer_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('name', '事業間移動').execute()
        if transfer_res.data:
            transfer_id = transfer_res.data[0]['id']
        else:
            ins2 = supabase.table('accounts').insert({
                'facility_code': f_code, 'code': '199', 'name': '事業間移動',
                'category': '資産', 'tax_type': 'none',
            }).execute()
            transfer_id = ins2.data[0]['id'] if ins2.data else cash_id

        # 当日の全仕訳取得（自動生成以外）
        all_res = supabase.table('journal_entries').select(
            'id,amount,debit_account_id,credit_account_id,source,division_id,'
            'debit:debit_account_id(id,code,name,category),'
            'credit:credit_account_id(id,code,name,category)'
        ).eq('facility_code', f_code).eq('entry_date', target_date).execute()

        all_entries = all_res.data or []

        # 自動生成仕訳（auto_fill/transfer）と手動仕訳を分魔
        auto_entries = [e for e in all_entries if e.get('source') in ('auto_fill', 'transfer')]
        manual_entries = [e for e in all_entries if e.get('source') not in ('auto_fill', 'transfer')]

        # 手動仕訳から計算
        # 経費合計: 貸方=現金かつ借方=費用科目
        expense_total = sum(
            e['amount'] for e in manual_entries
            if e.get('credit', {}) and e['credit_account_id'] == cash_id
            and e.get('debit', {}) and e['debit'].get('category') == '費用'
        )

        # 銀行→現金入金合計: 借方=現金かつ貸方=普通領金または預金
        bank_to_cash = sum(
            e['amount'] for e in manual_entries
            if e.get('debit', {}) and e['debit_account_id'] == cash_id
            and e.get('credit', {}) and e['credit'].get('category') == '資産'
            and e['credit'].get('code') in ('102', '103')
        )

        # 不足分を計算
        shortage = expense_total - bank_to_cash

        # 既存自動生成仕訳を全削除
        for ae in auto_entries:
            supabase.table('journal_entries').delete().eq('id', ae['id']).execute()

        # 不足分がなければ終了
        if shortage <= 0:
            return

        # 不足分を補填
        # 補填元事業部が設定されている場合は事業間移動、なければ事業主借
        if fill_div_id:
            # 移動元（fill_div）出金仕訳
            supabase.table('journal_entries').insert({
                'facility_code': f_code,
                'entry_date': target_date,
                'debit_account_id': transfer_id,
                'credit_account_id': cash_id,
                'amount': shortage,
                'tax_amount': 0,
                'description': '現金補填（出金）',
                'source': 'auto_fill',
                'created_by': 'system',
                'division_id': int(fill_div_id),
            }).execute()
            # 合流先（全事業共通または経費発生事業部）入金仕訳
            supabase.table('journal_entries').insert({
                'facility_code': f_code,
                'entry_date': target_date,
                'debit_account_id': cash_id,
                'credit_account_id': transfer_id,
                'amount': shortage,
                'tax_amount': 0,
                'description': '現金補填（入金）',
                'source': 'auto_fill',
                'created_by': 'system',
                'division_id': None,
            }).execute()
        else:
            # 事業主借で補填
            supabase.table('journal_entries').insert({
                'facility_code': f_code,
                'entry_date': target_date,
                'debit_account_id': cash_id,
                'credit_account_id': owner_id,
                'amount': shortage,
                'tax_amount': 0,
                'description': '現金自動補填',
                'source': 'auto_fill',
                'created_by': 'system',
                'division_id': None,
            }).execute()
    except Exception as e:
        # 再計算のエラーはサイレントにスキップ（本主処理に影響しない）
        import logging
        logging.warning(f'ledger_recalc_day error: {e}')

@app.route('/api/ledger/cash_fill', methods=['POST'])
@login_required
def api_ledger_cash_fill():
    """日次現金補填: 当日の費用合計を現金入金として自動仕訳"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        target_date = data.get('date', datetime.now(tokyo_tz).strftime('%Y-%m-%d'))
        division_id = data.get('division_id')
        # リクエストになければ設定から補填元事業部を取得
        if not division_id:
            _s = supabase.table('ledger_settings').select('cash_fill_division_id').eq('facility_code', f_code).execute()
            if _s.data and _s.data[0].get('cash_fill_division_id'):
                division_id = _s.data[0]['cash_fill_division_id']
        # 当日の費用合計を計算（借方が費用科目の仕訳）
        q = supabase.table('journal_entries').select(
            'amount, debit:debit_account_id(category)'
        ).eq('facility_code', f_code).eq('entry_date', target_date)
        # 補填元事業部指定は仕訳の記録先に使う。経費集計は全事業対象
        res = q.execute()
        total_expense = sum(
            e['amount'] for e in (res.data or [])
            if e.get('debit') and e['debit'].get('category') == '費用'
        )
        if total_expense <= 0:
            return jsonify({'status': 'success', 'message': '補填する費用がありません', 'amount': 0})
        # 現金科目と収益科目を取得
        cash_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('code', '101').execute()
        if not cash_res.data:
            return jsonify({'status': 'error', 'message': '現金科目(101)が見つかりません'}), 400
        cash_id = cash_res.data[0]['id']
        # 補填仕訳: 借方=現金、貸方=現金（事業主から入金）
        # 実際には「事業主借」科目を使うが、ない場合は現金同士
        owner_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('name', '事業主借').execute()
        if owner_res.data:
            credit_id = owner_res.data[0]['id']
        else:
            # 事業主借科目を自動作成
            ins = supabase.table('accounts').insert({
                'facility_code': f_code,
                'code': '300',
                'name': '事業主借',
                'category': '純資産',
                'tax_type': 'none',
            }).execute()
            credit_id = ins.data[0]['id'] if ins.data else cash_id
        fill_res = supabase.table('journal_entries').insert({
            'facility_code': f_code,
            'entry_date': target_date,
            'debit_account_id': cash_id,
            'credit_account_id': credit_id,
            'division_id': int(division_id) if division_id else None,
            'amount': total_expense,
            'description': f'{target_date} 日次現金補填（経費合計）',
            'source': 'auto_fill',
            'created_by': my_name,
        }).execute()
        return jsonify({'status': 'success', 'amount': total_expense, 'message': f'¥{total_expense:,} を現金入金として自動記録しました'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/accounts', methods=['GET'])
@login_required
def api_ledger_accounts():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        res = supabase.table('accounts').select('*').eq('facility_code', f_code).order('code').execute()
        return jsonify({'status': 'success', 'accounts': res.data or []})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/account', methods=['POST'])
@login_required
def api_ledger_account_save():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        payload = {
            'facility_code': f_code,
            'code': data['code'],
            'name': data['name'],
            'category': data['category'],
            'tax_type': data.get('tax_type', 'taxable'),
            'is_active': True,
        }
        acc_id = data.get('id')
        if acc_id:
            supabase.table('accounts').update(payload).eq('id', acc_id).eq('facility_code', f_code).execute()
            return jsonify({'status': 'success', 'id': acc_id})
        else:
            res = supabase.table('accounts').insert(payload).execute()
            new_id = res.data[0]['id'] if res.data else None
            return jsonify({'status': 'success', 'id': new_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/account/<int:acc_id>', methods=['DELETE'])
@login_required
def api_ledger_account_delete(acc_id):
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        supabase.table('accounts').update({'is_active': False}).eq('id', acc_id).eq('facility_code', f_code).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/entries', methods=['GET'])
@login_required
def api_ledger_entries():
    """仕訳一覧取得"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        year_month = request.args.get('month', '')  # 例: 2026-05
        query = supabase.table('journal_entries').select(
            '*, debit:debit_account_id(code,name,category), credit:credit_account_id(code,name,category)'
        ).eq('facility_code', f_code)
        if year_month:
            y, m = year_month.split('-')
            from datetime import date
            start = date(int(y), int(m), 1).isoformat()
            if int(m) == 12:
                end = date(int(y)+1, 1, 1).isoformat()
            else:
                end = date(int(y), int(m)+1, 1).isoformat()
            query = query.gte('entry_date', start).lt('entry_date', end)
        div_filter = request.args.get('division_id')
        if div_filter == 'none':
            query = query.is_('division_id', 'null')
        elif div_filter and div_filter != 'all':
            query = query.eq('division_id', int(div_filter))
        res = query.order('entry_date', desc=False).execute()
        return jsonify({'status': 'success', 'entries': res.data or []})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/transfer', methods=['POST'])
@login_required
def api_ledger_transfer():
    """事業間資金移動: A事業→B事業へ現金移動を両側に自動記録"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        from_div_id = data.get('from_division_id')
        to_div_id = data.get('to_division_id')
        amount = int(data.get('amount', 0))
        entry_date = data.get('entry_date', datetime.now(tokyo_tz).strftime('%Y-%m-%d'))
        description = data.get('description', '事業間現金移動')
        if not from_div_id or not to_div_id or not amount:
            return jsonify({'status': 'error', 'message': '必須項目が足りません'}), 400
        # 現金科目取得
        cash_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('code', '101').execute()
        if not cash_res.data:
            return jsonify({'status': 'error', 'message': '現金科目(101)が見つかりません'}), 400
        cash_id = cash_res.data[0]['id']
        # 事業間移動科目取得（なければ自動作成）
        transfer_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('name', '事業間移動').execute()
        if transfer_res.data:
            transfer_id = transfer_res.data[0]['id']
        else:
            ins = supabase.table('accounts').insert({
                'facility_code': f_code, 'code': '199', 'name': '事業間移動',
                'category': '資産', 'tax_type': 'none',
            }).execute()
            transfer_id = ins.data[0]['id'] if ins.data else cash_id
        # 出金側（from事業部）: 借方=事業間移動, 貸方=現金
        from_entry = {
            'facility_code': f_code, 'entry_date': entry_date,
            'debit_account_id': transfer_id, 'credit_account_id': cash_id,
            'amount': amount, 'tax_amount': 0,
            'description': description + '（出金）',
            'source': 'transfer', 'created_by': my_name,
            'division_id': int(from_div_id),
        }
        # 入金側（to事業部）: 借方=現金, 貸方=事業間移動
        to_entry = {
            'facility_code': f_code, 'entry_date': entry_date,
            'debit_account_id': cash_id, 'credit_account_id': transfer_id,
            'amount': amount, 'tax_amount': 0,
            'description': description + '（入金）',
            'source': 'transfer', 'created_by': my_name,
            'division_id': int(to_div_id),
        }
        r1 = supabase.table('journal_entries').insert(from_entry).execute()
        r2 = supabase.table('journal_entries').insert(to_entry).execute()
        # 事業間移動は再計算不要（手動指定のため）
        return jsonify({
            'status': 'success',
            'message': f'事業間移動 ¥{amount:,} を記録しました',
            'from_id': r1.data[0]['id'] if r1.data else None,
            'to_id': r2.data[0]['id'] if r2.data else None,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/entry', methods=['POST'])
@login_required
def api_ledger_entry_save():
    """仕訳登録・更新"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        _rdiv = data.get('division_id')
        payload = {
            'facility_code': f_code,
            'entry_date': data['entry_date'],
            'debit_account_id': data['debit_account_id'],
            'credit_account_id': data['credit_account_id'],
            'amount': int(data['amount']),
            'tax_amount': int(data.get('tax_amount', 0)),
            'description': data.get('description', ''),
            'source': data.get('source', 'manual'),
            'created_by': my_name,
            'division_id': int(_rdiv) if _rdiv else None,
        }
        # entry-new3cols-v1: \u63a5\u9aa8\u9662\u53d6\u8fbc\u7b49\u3067\u9001\u3089\u308c\u305f\u5834\u5408\u306e\u307f\u4fdd\u5b58\uff08\u5f8c\u65b9\u4e92\u63db\uff09
        for _k in ('insurance_type', 'settlement_status', 'import_batch_id'):
            if data.get(_k) is not None:
                payload[_k] = data.get(_k)
        entry_id = data.get('id')
        if entry_id:
            # 編集時: 旧日付も取得して両日を再計算
            old_res = supabase.table('journal_entries').select('entry_date').eq('id', entry_id).execute()
            old_date = old_res.data[0]['entry_date'] if old_res.data else None
            supabase.table('journal_entries').update(payload).eq('id', entry_id).eq('facility_code', f_code).execute()
            dates_to_recalc = set([payload['entry_date']])
            if old_date and old_date != payload['entry_date']:
                dates_to_recalc.add(old_date)
            for d in dates_to_recalc:
                _ledger_recalc_day(supabase, f_code, d)
            return jsonify({'status': 'success', 'id': entry_id})
        else:
            res = supabase.table('journal_entries').insert(payload).execute()
            new_id = res.data[0]['id'] if res.data else None
            _ledger_recalc_day(supabase, f_code, payload['entry_date'])
            return jsonify({'status': 'success', 'id': new_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/entry/<int:entry_id>', methods=['DELETE'])
@login_required
def api_ledger_entry_delete(entry_id):
    """仕訳削除"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        # 削除前に日付を取得
        del_res = supabase.table('journal_entries').select('entry_date').eq('id', entry_id).execute()
        del_date = del_res.data[0]['entry_date'] if del_res.data else None
        supabase.table('journal_entries').delete().eq('id', entry_id).eq('facility_code', f_code).execute()
        if del_date:
            _ledger_recalc_day(supabase, f_code, del_date)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/trial_balance', methods=['GET'])
@login_required
def api_ledger_trial_balance():
    """試算表生成"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        year_month = request.args.get('month', '')
        query = supabase.table('journal_entries').select(
            '*, debit:debit_account_id(id,code,name,category), credit:credit_account_id(id,code,name,category)'
        ).eq('facility_code', f_code)
        if year_month:
            y, m = year_month.split('-')
            from datetime import date
            start = date(int(y), int(m), 1).isoformat()
            if int(m) == 12:
                end = date(int(y)+1, 1, 1).isoformat()
            else:
                end = date(int(y), int(m)+1, 1).isoformat()
            query = query.gte('entry_date', start).lt('entry_date', end)
        res = query.execute()
        entries = res.data or []
        # 勘定科目ごとに集計
        balances = {}
        for e in entries:
            amt = e['amount']
            for side, acc in [('debit', e.get('debit')), ('credit', e.get('credit'))]:
                if not acc:
                    continue
                acc_id = acc['id']
                if acc_id not in balances:
                    balances[acc_id] = {
                        'code': acc['code'],
                        'name': acc['name'],
                        'category': acc['category'],
                        'debit': 0, 'credit': 0
                    }
                balances[acc_id][side] += amt
        # カテゴリ別に整理
        result = {'資産': [], '負債': [], '収益': [], '費用': [], '純資産': []}
        for acc_id, b in sorted(balances.items(), key=lambda x: x[1]['code']):
            cat = b['category']
            if cat in result:
                result[cat].append({
                    'code': b['code'],
                    'name': b['name'],
                    'debit': b['debit'],
                    'credit': b['credit'],
                    'balance': b['debit'] - b['credit']
                })
        return jsonify({'status': 'success', 'trial_balance': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============ ledger-orico-v1: オリコ明細パーサ群(保存はしない純粋関数) ============
def _orico_is_amazon(used_for):
    """利用先がAmazonか(全角・半角・デジタル課金を吸収)。"""
    import unicodedata as _ud
    if not used_for:
        return False
    return 'AMAZON' in _ud.normalize('NFKC', str(used_for)).upper()


def _orico_norm_amount(x):
    r"""'\5,880' '"\5,880"' '="0407"' 等から数値を正規化。\ , " = 空白除去 -> int。空/非数は None。"""
    if x is None:
        return None
    s = str(x).strip().strip('"')
    s = s.replace('\\', '').replace(',', '').replace('=', '').replace('"', '').strip()
    if s == '' or s == '-':
        return None
    neg = s.startswith('-')
    s2 = s[1:] if neg else s
    if not s2.isdigit():
        return None
    v = int(s2)
    return -v if neg else v


def _orico_norm_text(x):
    """文字セル: 前後の " と = を剥がす。"""
    if x is None:
        return ''
    return str(x).strip().strip('"').lstrip('=').strip('"').strip()


def _orico_parse_date(x):
    """'2026年1月6日' -> '2026-01-06'。失敗時 None。"""
    import re as _re
    if not x:
        return None
    s = _orico_norm_text(x)
    m = _re.match(r'(\d{4})\s*\u5e74\s*(\d{1,2})\s*\u6708\s*(\d{1,2})\s*\u65e5', s)
    if m:
        y, mo, d = m.groups()
        return "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    m2 = _re.match(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if m2:
        y, mo, d = m2.groups()
        return "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    return None


def _orico_extract_last4(s):
    """契約番号セルから下4桁。'****-****-****-0407' や '="0407"' に対応。"""
    import re as _re
    s = _orico_norm_text(s)
    digits = _re.findall(r'\d{4}', s)
    if digits:
        return digits[-1]
    m = _re.search(r'(\d{3,4})\s*$', s)
    return m.group(1) if m else ''


def build_orico_rows(content):  # ledger-orico-v1
    """オリコCSV本文(デコード済み) -> (rows, meta)。保存はしない。"""
    import csv as _csv, io as _io
    reader_all = list(_csv.reader(_io.StringIO(content)))
    card_last4 = ''
    payment_date = None
    detail_start = None
    for i, cells in enumerate(reader_all):
        if not cells:
            continue
        head = (cells[0] or '').strip()
        if head.startswith('\u3054\u5951\u7d04\u756a\u53f7') and len(cells) > 1:  # ご契約番号
            card_last4 = _orico_extract_last4(cells[1])
        elif head.startswith('\u304a\u652f\u6255\u65e5') and len(cells) > 1:  # お支払日
            payment_date = _orico_parse_date(cells[1])
        elif '\u5229\u7528\u660e\u7d30' in head:  # 利用明細
            detail_start = i
    rows = []
    amazon_count = 0
    if detail_start is not None:
        for cells in reader_all[detail_start + 2:]:
            if not cells or not any((c or '').strip() for c in cells):
                continue
            padded = (cells + [''] * 14)[:14]
            used_date = _orico_parse_date(padded[0])
            used_for = _orico_norm_text(padded[1])
            if used_date is None and not used_for:
                continue
            row = {
                'used_date': used_date,
                'used_for': used_for,
                'new_old': _orico_norm_text(padded[2]),
                'user_name': _orico_norm_text(padded[3]),
                'pay_start_ym': _orico_norm_text(padded[4]),
                'pay_type': _orico_norm_text(padded[5]),
                'pay_count': _orico_norm_text(padded[6]),
                'pay_nth': _orico_norm_text(padded[7]),
                'amount': _orico_norm_amount(padded[8]),
                'fee_interest': _orico_norm_amount(padded[9]),
                'annual_rate': _orico_norm_text(padded[10]),
                'other': _orico_norm_text(padded[11]),
                'billed_amount': _orico_norm_amount(padded[12]),
                'carryover': _orico_norm_amount(padded[13]),
                'raw_line': ','.join(cells),
            }
            if _orico_is_amazon(used_for):
                amazon_count += 1
            rows.append(row)
    meta = {'card_last4': card_last4, 'payment_date': payment_date,
            'total_rows': len(rows), 'amazon_count': amazon_count}
    return rows, meta


def _detect_csv_format(header):  # ledger-csv-autodetect-v1  # ledger-csv-autodetect-decofix-v1
    """ヘッダ行(list[str]) -> 'nikkei' または None。
    「外さない」優先。確信できる日計表の指紋のみ nikkei。曖昧/未知は None。"""
    cells = [(c or '').strip() for c in (header or [])]
    # ledger-orico-v1: オリコ明細の指紋を先に判定
    if any(c.startswith('ご契約番号') for c in cells) or any('利用明細' in c for c in cells):
        return 'orico'
    has_karte = any('カルテ' in c for c in cells)
    has_set = ('日付' in cells) and ('保険' in cells) and ('保険外' in cells) and ('入金額' in cells)
    if has_karte or has_set:
        return 'nikkei'
    return None


def _build_nikkei_entries(content, f_code, my_name, code_to_id, div_id):  # ledger-csv-autodetect-v1
    """日計表CSV本文 -> (suggestions, entries, batch)。保存はしない。
    既存 api_ledger_import_nikkei と同一ロジック（サンドボックスで出力一致検証済）。"""
    import csv as _csv, io as _io, hashlib as _hashlib
    HOKEN_MAP = {'国本': '国保', '国保': '国保',
                 '組本': '組合', '組合': '組合', '後期': '後期'}
    def _to_int(x):
        x = (x or '').strip()
        return int(x) if x.replace('-', '').isdigit() else 0
    rows = list(_csv.reader(_io.StringIO(content)))
    if rows and rows[0] and rows[0][0].strip() == '日付':
        rows = rows[1:]
    batch = 'nikkei_' + _hashlib.md5(content.encode('utf-8', 'replace')).hexdigest()[:10]
    suggestions = []
    entries = []
    def _push(date, credit_code, amount, ins, desc, review=False):
        debit_id = code_to_id.get('101')
        credit_id = code_to_id.get(credit_code)
        if not (debit_id and credit_id and amount > 0):
            return
        suggestions.append({'entry_date': date, 'debit_code': '101', 'credit_code': credit_code,
                             'amount': amount, 'description': desc, 'insurance_type': ins,
                             'needs_review': review})
        entries.append({'facility_code': f_code, 'entry_date': date,
                        'debit_account_id': debit_id, 'credit_account_id': credit_id,
                        'amount': amount, 'tax_amount': 0, 'description': desc,
                        'source': 'nikkei_csv', 'created_by': my_name,
                        'division_id': div_id, 'insurance_type': ins,
                        'settlement_status': None, 'import_batch_id': batch})
    for r in rows:
        if not any((c or '').strip() for c in r):
            continue
        if len(r) < 11:
            continue
        date = r[0].strip().replace('/', '-')
        hoken = r[3].strip()
        nyukin = _to_int(r[10])
        if nyukin <= 0:
            continue
        if hoken == '自費':
            _push(date, '404', nyukin, '自費', '接骨院 自費売上')
        elif hoken in HOKEN_MAP:
            ins = HOKEN_MAP[hoken]
            hbun = _to_int(r[7])
            hgai = _to_int(r[8])
            if hbun > 0:
                _push(date, '405', hbun, ins, '接骨院 健康保険売上(窓口負担)')
            if hgai > 0:
                _push(date, '404', hgai, '自費', '接骨院 自費売上(保険外)')
        else:
            _push(date, '404', nyukin, hoken or '不明',
                  '接骨院 売上(区分要確認)', review=True)
    return suggestions, entries, batch


@app.route('/api/ledger/import_csv', methods=['POST'])
@login_required
def api_ledger_import_csv():
    """CSVインポート（売上・銀行明細）- Claude APIでAI自動科目推定"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        import anthropic as _anthropic, json as _json, re as _re
        f = request.files.get('file')
        csv_type = request.form.get('csv_type', 'auto')
        if not f:
            return jsonify({'status': 'error', 'message': 'ファイルがありません'}), 400
        content = f.read().decode('utf-8-sig', errors='replace')
        # --- ledger-csv-autodetect-v1: 自動判定で日計表を検出したら専用処理へ ---
        if csv_type == 'auto' and is_sekkotsu_enabled(supabase, f_code):
            try:
                f.seek(0)
                _raw = f.read()
            except Exception:
                _raw = b''
            _nik_content = None
            for _enc in ('utf-8-sig', 'cp932', 'utf-8'):
                try:
                    _nik_content = _raw.decode(_enc); break
                except Exception:
                    _nik_content = None
            if _nik_content is None and _raw:
                _nik_content = _raw.decode('cp932', 'replace')
            if _nik_content:
                import csv as _csv_d, io as _io_d
                _hdr_rows = list(_csv_d.reader(_io_d.StringIO(_nik_content)))
                _hdr = _hdr_rows[0] if _hdr_rows else []
                # ledger-orico-v1: オリコ明細なら保存のみ(仕訳化はしない)
                _orico_fmt = _detect_csv_format(_hdr)
                # ヘッダー以外に指紋がある場合も拾う(先頭行が契約情報のため)
                if _orico_fmt != 'orico':
                    for _ln in (_nik_content.splitlines()[:12]):
                        if _ln.startswith('ご契約番号') or ('利用明細' in _ln):
                            _orico_fmt = 'orico'; break
                if _orico_fmt == 'orico':
                    # ledger-credit-guard-v1
                    if not is_credit_enabled(supabase, f_code):
                        return jsonify({'status': 'error', 'message': 'クレカ明細モードが有効ではありません'}), 403
                    _o_rows, _o_meta = build_orico_rows(_nik_content)
                    _o_last4 = _o_meta.get('card_last4') or ''
                    _o_pay = _o_meta.get('payment_date')
                    if not _o_pay:
                        return jsonify({'status': 'error', 'message': 'お支払日を読み取れませんでした'}), 400
                    # ledger-orico-replace-v1: 月単位の置き換え方式
                    _o_replace = bool(request.form.get('orico_replace') == '1')
                    _o_exist = supabase.table('ledger_orico_statements').select('id')\
                        .eq('facility_code', f_code).eq('payment_date', _o_pay).execute()
                    _o_exist_n = len(_o_exist.data or [])
                    if _o_exist_n > 0 and not _o_replace:
                        # 既存あり、置換未承諾 → フロントに確認を求める
                        return jsonify({'status': 'exists', 'payment_date': _o_pay,
                                        'existing_count': _o_exist_n,
                                        'incoming_count': len(_o_rows),
                                        'amazon_count': _o_meta.get('amazon_count', 0),
                                        'card_last4': _o_last4, 'kind': 'orico'})
                    if _o_exist_n > 0 and _o_replace:
                        # その月を全削除してから入れ直す
                        supabase.table('ledger_orico_statements').delete()\
                            .eq('facility_code', f_code).eq('payment_date', _o_pay).execute()
                    _o_ins = 0
                    for _r in _o_rows:
                        _ins_row = dict(_r)
                        _ins_row['facility_code'] = f_code
                        _ins_row['card_last4'] = _o_last4
                        _ins_row['payment_date'] = _o_pay
                        _ins_row['match_status'] = 'none'
                        supabase.table('ledger_orico_statements').insert(_ins_row).execute()
                        _o_ins += 1
                    return jsonify({'status': 'success', 'imported': _o_ins,
                                    'replaced': (_o_exist_n if _o_replace else 0),
                                    'amazon_count': _o_meta.get('amazon_count', 0),
                                    'payment_date': _o_pay, 'card_last4': _o_last4,
                                    'kind': 'orico'})
                if _detect_csv_format(_hdr) == 'nikkei':
                    _acc = supabase.table('accounts').select('id,code').eq('facility_code', f_code).eq('is_active', True).execute()
                    _c2i = {a['code']: a['id'] for a in (_acc.data or [])}
                    _missing = [c for c in ('101', '404', '405') if c not in _c2i]
                    if not _missing:
                        _div = None
                        try:
                            _d = supabase.table('ledger_divisions').select('id,name').eq('facility_code', f_code).eq('is_active', True).execute()
                            for _row in (_d.data or []):
                                if '接骨' in (_row.get('name') or ''):
                                    _div = _row['id']; break
                        except Exception:
                            _div = None
                        _sg, _en, _bt = _build_nikkei_entries(_nik_content, f_code, my_name, _c2i, _div)
                        return jsonify({'status': 'success', 'imported': 0, 'batch_id': _bt,
                                        'suggestions': _sg, 'entries': _en})
        # --- /ledger-csv-autodetect-v1 ---
        # 勘定科目一覧を取得
        acc_res = supabase.table('accounts').select('id,code,name,category').eq('facility_code', f_code).execute()
        accounts = acc_res.data or []
        acc_list = '\n'.join([f"{a['code']} {a['name']}({a['category']})" for a in accounts])
        # CSVタイプ別のヒント
        type_hints = {
            'auto': '一般的なCSVか銀行明細か売上データです。形式を自動判定してください。',
            'smaregi': 'Smaregi(スマレジ)の売上データです。売上は充当金の収益になります。',
            'bank': '銀行口座の引落し明細です。出金は費用、入金は収益または販売歌入です。',
            'card': 'クレジットカード明細です。利用歌は未払金/当座の負債になります。',
        }
        type_hint = type_hints.get(csv_type, '')
        prompt = f"""あなたは介護施設の会計担当者です。以下のCSVデータを会計仕訳に変換してください。

【CSVの種類のヒント】
{type_hint}

【利用可能な勘定科目一覧】
{acc_list}

【仕訳ルール】
- 介護施設の一般的な科目属性：
  ・利用者からの利用料収入 → 借方:普通預金/現金、貸方:売上高
  ・銀行からの入金 → 借方:普通預金、貸方:売上高または貲掴金
  ・費用の引落し → 借方:各費用科目、貸方:普通預金/現金
  ・負債返済 → 借方:負債科目、貸方:普通預金
- 金額は正の整数で返す（マイナス不可）
- 日付はYYYY-MM-DD形式
- descriptionは日本語で簡潔に

【出力形式】
JSON配列のみ。マークダウン不要。
[{{"entry_date":"YYYY-MM-DD","debit_code":"101","credit_code":"401","amount":50000,"description":"利用料入金"}}]

【CSVデータ】
{content[:4000]}"""

        # Claude APIで自動仕訳生成
        client = _anthropic.Anthropic()
        message = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=2000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = message.content[0].text.strip()
        raw = _re.sub(r'^```[a-zA-Z]*\n?', '', raw).strip()
        raw = _re.sub(r'```$', '', raw).strip()
        suggestions = _json.loads(raw)
        # account codeからidに変換（コードまたは名前でマッチ）
        code_to_id = {a['code']: a['id'] for a in accounts}
        name_to_id = {a['name']: a['id'] for a in accounts}
        entries = []
        for s in suggestions:
            debit_id = code_to_id.get(str(s.get('debit_code'))) or name_to_id.get(s.get('debit_code'))
            credit_id = code_to_id.get(str(s.get('credit_code'))) or name_to_id.get(s.get('credit_code'))
            if debit_id and credit_id and int(s.get('amount', 0)) > 0:
                entries.append({
                    'facility_code': f_code,
                    'entry_date': s['entry_date'],
                    'debit_account_id': debit_id,
                    'credit_account_id': credit_id,
                    'amount': int(s.get('amount', 0)),
                    'tax_amount': int(s.get('tax_amount', 0)),
                    'description': s.get('description', ''),
                    'source': csv_type,
                    'created_by': my_name,
                })
        # 保存はフロントの確認後に行う。suggestionsとentriesを返す
        # entriesには内部ID変換済みのペイロードを含める
        return jsonify({'status': 'success', 'imported': 0, 'suggestions': suggestions, 'entries': entries})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/orico_list', methods=['GET'])  # ledger-orico-v1
@login_required
def api_ledger_orico_list():
    """オリコ明細を支払日(月)ごとにまとめて返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': 'クレカ明細モードが有効ではありません'}), 403  # ledger-credit-guard-v1
    try:
        res = supabase.table('ledger_orico_statements').select(
            'id,payment_date,used_date,used_for,amount,match_status,amazon_detail,account_id,division_id'  # ledger-credit-3a-v1 / ledger-credit-3b-div-v1
        ).eq('facility_code', f_code).order('payment_date', desc=True).order('used_date').execute()
        groups = {}
        for r in (res.data or []):
            key = r.get('payment_date') or '\u4e0d\u660e'
            groups.setdefault(key, []).append({
                'id': r['id'],
                'used_date': r.get('used_date'),
                'used_for': r.get('used_for') or '',
                'amount': r.get('amount'),
                'is_amazon': _orico_is_amazon(r.get('used_for') or ''),
                'match_status': r.get('match_status') or 'none',
                'amazon_detail': r.get('amazon_detail') or '',
                'account_id': r.get('account_id'),  # ledger-credit-3a-v1
                'division_id': r.get('division_id'),  # ledger-credit-3b-div-v1
            })
        out = [{'payment_date': k, 'items': v,
                'total': sum((it['amount'] or 0) for it in v)}
               for k, v in sorted(groups.items(), reverse=True)]
        return jsonify({'status': 'success', 'groups': out})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============ ledger-orico-card-v1: 会社カード管理(下4桁の束ね) ============
def _orico_clean_last4_list(raw):
    """入力(list/str)から下4桁の配列を正規化。数字のみ・重複排除・順序維持。"""
    import re as _re
    if raw is None:
        return []
    if isinstance(raw, str):
        items = _re.split(r'[,\s]+', raw)
    else:
        items = list(raw)
    out = []
    for it in items:
        d = _re.sub(r'\D', '', str(it))
        if not d:
            continue
        d = d[-4:]  # 末尾4桁
        if d not in out:
            out.append(d)
    return out


@app.route('/api/ledger/orico_cards', methods=['GET'])  # ledger-orico-card-v1
@login_required
def api_ledger_orico_cards_get():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': 'クレカ明細モードが有効ではありません'}), 403  # ledger-credit-guard-v1
    try:
        res = supabase.table('ledger_orico_cards').select('*').eq('facility_code', f_code).eq('is_active', True).order('id').execute()
        return jsonify({'status': 'success', 'cards': res.data or []})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/orico_card', methods=['POST'])  # ledger-orico-card-v1
@login_required
def api_ledger_orico_card_save():
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': 'クレカ明細モードが有効ではありません'}), 403  # ledger-credit-guard-v1
    try:
        data = request.json or {}
        last4_list = _orico_clean_last4_list(data.get('last4_list'))
        card_name = (data.get('card_name') or '').strip() or None
        card_id = data.get('id')
        if card_id:
            supabase.table('ledger_orico_cards').update({
                'card_name': card_name,
                'last4_list': last4_list,
            }).eq('id', card_id).eq('facility_code', f_code).execute()
            return jsonify({'status': 'success', 'id': card_id, 'last4_list': last4_list})
        else:
            res = supabase.table('ledger_orico_cards').insert({
                'facility_code': f_code,
                'card_name': card_name,
                'last4_list': last4_list,
                'is_active': True,
            }).execute()
            new_id = res.data[0]['id'] if res.data else None
            return jsonify({'status': 'success', 'id': new_id, 'last4_list': last4_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/orico_card/<int:card_id>', methods=['DELETE'])  # ledger-orico-card-v1
@login_required
def api_ledger_orico_card_delete(card_id):
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': 'クレカ明細モードが有効ではありません'}), 403  # ledger-credit-guard-v1
    try:
        supabase.table('ledger_orico_cards').update({'is_active': False}).eq('id', card_id).eq('facility_code', f_code).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============ ledger-amazon-v1: Amazon突合(発送単位・ホワイトリスト・出荷日基準) ============
# 内部名は amazon。画面表示名は「クレカ明細」(他社カード施設も使うため)。
# Amazon Business 全項目レポートCSV(UTF-8 BOM)を発送単位で集約し、
# オリコのAmazon未マッチ行と金額完全一致+登録カード下4桁+日付近接で突合する。
# DBには保存しない(ステートレス)。確定はサーバで再検証してから amazon_detail に書く。

AMAZON_MATCH_SHIP_WINDOW = 3   # ledger-amazon-v1: 出荷日ありのとき ±3日
AMAZON_MATCH_ORDER_WINDOW = 7  # ledger-amazon-v1: 出荷日なし(注文日フォールバック) ±7日

# ヘッダ名 -> 候補。最初に見つかったものを採用(列順/列数の変化に強い)。
_AMZ_COLS = {
    'order_no':    ['\u6ce8\u6587\u756a\u53f7'],
    'order_date':  ['\u6ce8\u6587\u65e5'],
    'order_total': ['\u6ce8\u6587\u306e\u5408\u8a08\uff08\u7a0e\u8fbc\uff09'],
    'ship_date':   ['\u51fa\u8377\u65e5'],
    'ship_total':  ['\u767a\u9001\u5546\u54c1\u306e\u5408\u8a08\uff08\u7a0e\u8fbc\uff09'],
    'last4':       ['\u30af\u30ec\u30b8\u30c3\u30c8\u30ab\u30fc\u30c9\u756a\u53f7\uff08\u4e0b4\u6841\uff09'],
    'item_name':   ['\u5546\u54c1\u540d'],
}


def _amz_build_colmap(header):
    norm = [(c or '').strip() for c in (header or [])]
    colmap = {}
    for key, names in _AMZ_COLS.items():
        idx = None
        for nm in names:
            if nm in norm:
                idx = norm.index(nm); break
        colmap[key] = idx
    return colmap


def _amazon_norm_amount(x):
    if x is None:
        return None
    s = str(x).strip().strip('"')
    s = s.replace(',', '').replace('\\', '').replace('=', '').replace('"', '').strip()
    if s == '' or s == '-':
        return None
    neg = s.startswith('-')
    s2 = s[1:] if neg else s
    if not s2.isdigit():
        return None
    v = int(s2)
    return -v if neg else v


def _amazon_norm_date(x):
    import re as _re
    if not x:
        return None
    s = str(x).strip().strip('"').lstrip('=').strip('"').strip()
    m = _re.match(r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})', s)
    if m:
        y, mo, d = m.groups()
        return "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    return None


def _amazon_extract_last4(s):
    import re as _re
    if s is None:
        return ''
    t = str(s).strip().strip('"').lstrip('=').strip('"').strip()
    digits = _re.findall(r'\d{4}', t)
    if digits:
        return digits[-1]
    m = _re.search(r'(\d{3,4})\s*$', t)
    return m.group(1) if m else ''


def _amazon_cell(row, colmap, key):
    idx = colmap.get(key)
    if idx is None or idx >= len(row):
        return ''
    return row[idx]


def _amazon_dedup_items(raw_items):
    out, seen = [], set()
    for nm in (raw_items or []):
        if not nm or nm in seen:
            continue
        seen.add(nm); out.append(nm)
    return out


def _amazon_summary(items):
    items = [i for i in (items or []) if i]
    if not items:
        return ''
    head = items[0]
    if len(head) > 40:
        head = head[:40] + '\u2026'
    n = len(items)
    if n == 1:
        return head
    return "%s \u307b\u304b%d\u70b9" % (head, n - 1)


def build_amazon_rows(content):  # ledger-amazon-v1
    """Amazon全項目レポートCSV本文 -> (shipments, meta)。発送単位集約。保存しない。"""
    import csv as _csv, io as _io
    reader_all = list(_csv.reader(_io.StringIO(content)))
    if not reader_all:
        return [], {'shipment_count': 0, 'order_count': 0, 'item_count': 0, 'cols_missing': list(_AMZ_COLS.keys())}
    header = reader_all[0]
    colmap = _amz_build_colmap(header)
    missing = [k for k, v in colmap.items() if v is None]
    by_ship = {}
    ship_seq = []
    order_ship_keys = {}
    item_count = 0
    for row in reader_all[1:]:
        if not row or not any((c or '').strip() for c in row):
            continue
        order_no = str(_amazon_cell(row, colmap, 'order_no')).strip().strip('"').lstrip('=').strip('"').strip()
        if not order_no:
            continue
        order_date = _amazon_norm_date(_amazon_cell(row, colmap, 'order_date'))
        ship_date = _amazon_norm_date(_amazon_cell(row, colmap, 'ship_date'))
        ship_total = _amazon_norm_amount(_amazon_cell(row, colmap, 'ship_total'))
        order_total = _amazon_norm_amount(_amazon_cell(row, colmap, 'order_total'))
        last4 = _amazon_extract_last4(_amazon_cell(row, colmap, 'last4'))
        item_name = str(_amazon_cell(row, colmap, 'item_name')).strip().strip('"').strip()
        amount = ship_total if ship_total is not None else order_total
        key = (order_no, ship_date, amount)
        if key not in by_ship:
            by_ship[key] = {'order_no': order_no, 'order_date': order_date,
                            'ship_date': ship_date, 'amount': amount, 'last4': last4, 'items': []}
            ship_seq.append(key)
            order_ship_keys.setdefault(order_no, set()).add(key)
        rec = by_ship[key]
        if rec['order_date'] is None and order_date is not None:
            rec['order_date'] = order_date
        if not rec['last4'] and last4:
            rec['last4'] = last4
        if item_name:
            rec['items'].append(item_name); item_count += 1
    shipments = []
    for key in ship_seq:
        rec = by_ship[key]
        rec['items_dedup'] = _amazon_dedup_items(rec['items'])
        rec['summary'] = _amazon_summary(rec['items_dedup'])
        rec['split'] = len(order_ship_keys.get(rec['order_no'], set())) > 1
        shipments.append(rec)
    meta = {'shipment_count': len(shipments), 'order_count': len(order_ship_keys),
            'item_count': item_count, 'cols_missing': missing}
    return shipments, meta


def _amazon_get_card_whitelist(supabase, f_code):  # ledger-amazon-v1
    """登録済み会社カードの下4桁を全カード束ねて集合で返す。"""
    wl = set()
    try:
        res = supabase.table('ledger_orico_cards').select('last4_list')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        for c in (res.data or []):
            for x in (c.get('last4_list') or []):
                d = str(x).strip()
                if d:
                    wl.add(d[-4:])
    except Exception:
        pass
    return wl


def _amazon_match_against_orico(orico_rows, amazon_ships, card_whitelist):  # ledger-amazon-v1
    """オリコAmazon未マッチ行 × Amazon発送 を突合。3分類で返す。"""
    import datetime as _dt
    def _d(s):
        if not s:
            return None
        try:
            return _dt.date.fromisoformat(s)
        except Exception:
            return None
    if card_whitelist:
        amz = [s for s in amazon_ships if s.get('last4') in card_whitelist]
    else:
        amz = list(amazon_ships)
    results = []
    used_ship_keys = set()
    for o in orico_rows:
        o_amt = o.get('amount')
        o_last4 = o.get('card_last4') or ''
        o_date = _d(o.get('used_date'))
        if card_whitelist and o_last4 and o_last4 not in card_whitelist:
            results.append({'orico': o, 'classification': 'skip_card', 'candidates': []})
            continue
        cands = []
        for s in amz:
            key = (s['order_no'], s['ship_date'], s['amount'])
            if key in used_ship_keys:
                continue
            if o_amt is None or s['amount'] is None or o_amt != s['amount']:
                continue
            last4_ok = True
            last4_uncertain = False
            if o_last4 and s.get('last4'):
                last4_ok = (o_last4 == s['last4'])
            else:
                last4_uncertain = True
            if not last4_ok:
                continue
            ref = _d(s['ship_date']) or _d(s['order_date'])
            win = AMAZON_MATCH_SHIP_WINDOW if s['ship_date'] else AMAZON_MATCH_ORDER_WINDOW
            within = False
            daydiff = None
            if o_date and ref:
                daydiff = abs((o_date - ref).days)
                within = daydiff <= win
            cands.append({'ship': s, 'daydiff': daydiff, 'within': within, 'last4_uncertain': last4_uncertain})
        in_win = [c for c in cands if c['within']]
        if len(in_win) == 1 and not in_win[0]['last4_uncertain']:
            chosen = in_win[0]
            used_ship_keys.add((chosen['ship']['order_no'], chosen['ship']['ship_date'], chosen['ship']['amount']))
            results.append({'orico': o, 'classification': 'auto', 'candidates': [chosen]})
        elif len(in_win) >= 1:
            results.append({'orico': o, 'classification': 'review', 'candidates': in_win})
        elif len(cands) >= 1:
            results.append({'orico': o, 'classification': 'review', 'candidates': cands})
        else:
            results.append({'orico': o, 'classification': 'none', 'candidates': []})
    return results


@app.route('/api/ledger/amazon_match', methods=['POST'])  # ledger-amazon-v1
@login_required
def api_ledger_amazon_match():
    """Amazon全項目CSVを受領 -> 発送単位集約 -> オリコAmazon未マッチ行と突合候補を返す。DB保存なし。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        f = request.files.get('file')
        if not f:
            return jsonify({'status': 'error', 'message': '\u30d5\u30a1\u30a4\u30eb\u304c\u3042\u308a\u307e\u305b\u3093'}), 400
        _raw = f.read()
        content = None
        for _enc in ('utf-8-sig', 'utf-8', 'cp932'):
            try:
                content = _raw.decode(_enc); break
            except Exception:
                content = None
        if content is None:
            content = _raw.decode('utf-8', 'replace')
        ships, meta = build_amazon_rows(content)
        if meta.get('cols_missing'):
            return jsonify({'status': 'error',
                            'message': 'Amazon\u660e\u7d30\u306e\u5217\u304c\u4e0d\u8db3\u3057\u3066\u3044\u307e\u3059: ' + ','.join(meta['cols_missing'])}), 400
        # オリコのAmazon未マッチ行を取得
        wl = _amazon_get_card_whitelist(supabase, f_code)
        _res = supabase.table('ledger_orico_statements')\
            .select('id,used_date,used_for,amount,card_last4,match_status')\
            .eq('facility_code', f_code).eq('match_status', 'none').execute()
        orico_amazon = []
        import unicodedata as _ud
        for r in (_res.data or []):
            uf = r.get('used_for') or ''
            if 'AMAZON' in _ud.normalize('NFKC', str(uf)).upper():
                orico_amazon.append(r)
        matches = _amazon_match_against_orico(orico_amazon, ships, wl)
        # フロント返却用に整形(ship内のitemsはdedup後を渡す)
        out = []
        for m in matches:
            o = m['orico']
            cands = []
            for c in m['candidates']:
                s = c['ship']
                cands.append({
                    'order_no': s['order_no'], 'order_date': s['order_date'],
                    'ship_date': s['ship_date'], 'amount': s['amount'],
                    'last4': s['last4'], 'items': s['items_dedup'],
                    'summary': s['summary'], 'split': s['split'],
                    'daydiff': c['daydiff'], 'within': c['within'],
                    'last4_uncertain': c['last4_uncertain'],
                })
            out.append({
                'orico_id': o['id'], 'used_date': o.get('used_date'),
                'used_for': o.get('used_for'), 'amount': o.get('amount'),
                'card_last4': o.get('card_last4'),
                'classification': m['classification'], 'candidates': cands,
            })
        summary = {'auto': 0, 'review': 0, 'none': 0, 'skip_card': 0}
        for m in matches:
            summary[m['classification']] = summary.get(m['classification'], 0) + 1
        return jsonify({'status': 'success', 'matches': out, 'summary': summary,
                        'amazon_meta': meta, 'whitelist': sorted(wl)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/amazon_apply', methods=['POST'])  # ledger-amazon-v1
@login_required
def api_ledger_amazon_apply():
    """承認された突合ペアを確定。サーバ側で金額一致を再検証してから amazon_detail(JSON)を書く。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        import json as _json, datetime as _dt
        data = request.json or {}
        pairs = data.get('pairs') or []
        applied = 0
        skipped = []
        for p in pairs:
            oid = p.get('orico_id')
            amt = p.get('amount')
            if oid is None:
                continue
            # 対象オリコ行を引き直して再検証
            _r = supabase.table('ledger_orico_statements')\
                .select('id,amount,used_for,match_status')\
                .eq('id', oid).eq('facility_code', f_code).execute()
            row = (_r.data or [None])[0]
            if not row:
                skipped.append({'orico_id': oid, 'reason': 'not_found'}); continue
            # 金額一致の再検証
            if amt is None or row.get('amount') != amt:
                skipped.append({'orico_id': oid, 'reason': 'amount_mismatch'}); continue
            # 既にマッチ済みは上書きしない(none のみ確定可)
            if (row.get('match_status') or 'none') != 'none':
                skipped.append({'orico_id': oid, 'reason': 'already_matched'}); continue
            detail = {
                'order_no': p.get('order_no'),
                'order_date': p.get('order_date'),
                'ship_date': p.get('ship_date'),
                'amount': amt,
                'items': p.get('items') or [],
                'summary': p.get('summary') or '',
                'split': bool(p.get('split')),
            }
            supabase.table('ledger_orico_statements').update({
                'amazon_detail': _json.dumps(detail, ensure_ascii=False),
                'match_status': 'matched',
                'matched_at': _dt.datetime.utcnow().isoformat(),
            }).eq('id', oid).eq('facility_code', f_code).execute()
            applied += 1
        return jsonify({'status': 'success', 'applied': applied, 'skipped': skipped})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============ /ledger-amazon-v1 ============


# ============ ledger-credit-rules-v1: 勘定科目の学習振り分け ============
# 学習辞書 ledger_credit_rules を使い、クレカ明細(ledger_orico_statements)に
# 勘定科目を推定・割当。キー=商品名(あれば)/店名(無ければ)。
# 推定順: 商品名完全一致 -> 店名完全一致 -> 店名部分一致 -> 未割当。


def _cr_norm(s):
    """キー正規化: NFKC + 前後空白除去 + 連続空白圧縮。"""
    import unicodedata as _ud
    if s is None:
        return ''
    t = _ud.normalize('NFKC', str(s)).strip()
    return ' '.join(t.split())


def _cr_item_from_detail(amazon_detail):
    """amazon_detail(JSON文字列)から代表商品名を取り出す。無ければ ''。"""
    import json as _json
    if not amazon_detail:
        return ''
    try:
        d = _json.loads(amazon_detail)
    except Exception:
        return ''
    if not isinstance(d, dict):
        return ''
    items = d.get('items') or []
    if items:
        return items[0]
    return d.get('summary') or ''


def _cr_load_rules(supabase, f_code):
    """その施設の学習辞書を読み、種別ごとに分けて返す。"""
    exact_item = {}
    exact_store = {}
    partial = []
    try:
        res = supabase.table('ledger_credit_rules').select(
            'key_type,key_text,match_type,account_id'
        ).eq('facility_code', f_code).execute()
        for r in (res.data or []):
            kt = r.get('key_type'); mt = r.get('match_type') or 'exact'
            key = _cr_norm(r.get('key_text'))
            aid = r.get('account_id')
            if not key or aid is None:
                continue
            if mt == 'partial' and kt == 'store':
                partial.append((key, aid))
            elif kt == 'item':
                exact_item[key] = aid
            elif kt == 'store':
                exact_store[key] = aid
    except Exception:
        pass
    return exact_item, exact_store, partial


def _cr_suggest_one(used_for, amazon_detail, rules):
    """1明細の科目推定。 (account_id, matched_by) を返す。未割当は (None,'none')。"""
    exact_item, exact_store, partial = rules
    item = _cr_norm(_cr_item_from_detail(amazon_detail))
    store = _cr_norm(used_for)
    if item and item in exact_item:
        return exact_item[item], 'item_exact'
    if store and store in exact_store:
        return exact_store[store], 'store_exact'
    for kw, aid in partial:
        if kw and kw in store:
            return aid, 'store_partial'
    return None, 'none'


@app.route('/api/ledger/credit_suggest', methods=['POST'])  # ledger-credit-rules-v1
@login_required
def api_ledger_credit_suggest():
    """クレカ明細idリストを受け、各明細の勘定科目を推定して返す。保存しない。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        data = request.json or {}
        ids = data.get('ids') or []
        rules = _cr_load_rules(supabase, f_code)
        drules = _dr_load_rules(supabase, f_code)  # ledger-credit-3b-div-v1
        acc = supabase.table('accounts').select('id,code,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        acc_map = {a['id']: a for a in (acc.data or [])}
        _dv = supabase.table('ledger_divisions').select('id,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()  # ledger-credit-3b-div-v1
        div_map = {d['id']: d for d in (_dv.data or [])}  # ledger-credit-3b-div-v1
        out = []
        rows = []
        if ids:
            res = supabase.table('ledger_orico_statements')\
                .select('id,used_for,amazon_detail,account_id,division_id')\
                .eq('facility_code', f_code).in_('id', ids).execute()
            rows = res.data or []
        for r in rows:
            aid, by = _cr_suggest_one(r.get('used_for'), r.get('amazon_detail'), rules)
            cur = r.get('account_id')
            use_aid = cur if cur is not None else aid
            acct = None
            if use_aid is not None and use_aid in acc_map:
                a = acc_map[use_aid]
                acct = {'id': a['id'], 'code': a['code'], 'name': a['name']}
            did, dby = _dr_suggest_one(r.get('used_for'), r.get('amazon_detail'), drules)  # ledger-credit-3b-div-v1
            dcur = r.get('division_id')  # ledger-credit-3b-div-v1
            use_did = dcur if dcur is not None else did  # ledger-credit-3b-div-v1
            dv = None  # ledger-credit-3b-div-v1
            if use_did is not None and use_did in div_map:  # ledger-credit-3b-div-v1
                _d = div_map[use_did]  # ledger-credit-3b-div-v1
                dv = {'id': _d['id'], 'name': _d['name']}  # ledger-credit-3b-div-v1
            out.append({
                'id': r['id'],
                'suggested_account': acct,
                'matched_by': ('assigned' if cur is not None else by),
                'suggested_division': dv,  # ledger-credit-3b-div-v1
                'division_matched_by': ('assigned' if dcur is not None else dby),  # ledger-credit-3b-div-v1
            })
        return jsonify({'status': 'success', 'suggestions': out})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/credit_assign', methods=['POST'])  # ledger-credit-rules-v1
@login_required
def api_ledger_credit_assign():
    """確認済みの (明細id -> 科目id) を保存し、学習辞書にも記録(upsert)。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        import datetime as _dt
        data = request.json or {}
        pairs = data.get('pairs') or []
        applied = 0
        learned = 0
        skipped = []
        for p in pairs:
            oid = p.get('id')
            aid = p.get('account_id')
            if oid is None or aid is None:
                skipped.append({'id': oid, 'reason': 'missing'}); continue
            _r = supabase.table('ledger_orico_statements')\
                .select('id,used_for,amazon_detail')\
                .eq('id', oid).eq('facility_code', f_code).execute()
            row = (_r.data or [None])[0]
            if not row:
                skipped.append({'id': oid, 'reason': 'not_found'}); continue
            # 科目が当該施設の有効科目か再検証
            _a = supabase.table('accounts').select('id')\
                .eq('id', aid).eq('facility_code', f_code).eq('is_active', True).execute()
            if not (_a.data):
                skipped.append({'id': oid, 'reason': 'bad_account'}); continue
            # 明細に科目を保存
            supabase.table('ledger_orico_statements').update({
                'account_id': aid,
            }).eq('id', oid).eq('facility_code', f_code).execute()
            applied += 1
            # ledger-credit-3b-div-v1: 事業の保存+学習(division_idが渡されたときのみ)
            did = p.get('division_id')
            if did is not None:
                _dchk = supabase.table('ledger_divisions').select('id')\
                    .eq('id', did).eq('facility_code', f_code).eq('is_active', True).execute()
                if _dchk.data:
                    supabase.table('ledger_orico_statements').update({
                        'division_id': did,
                    }).eq('id', oid).eq('facility_code', f_code).execute()
                    if p.get('learn', True):
                        _ditem = _cr_norm(_cr_item_from_detail(row.get('amazon_detail')))
                        if _ditem:
                            _dkt, _dkx = 'item', _ditem
                        else:
                            _dkt, _dkx = 'store', _cr_norm(row.get('used_for'))
                        if _dkx:
                            _dnow = _dt.datetime.utcnow().isoformat()
                            _de = supabase.table('ledger_division_rules').select('id')\
                                .eq('facility_code', f_code).eq('key_type', _dkt)\
                                .eq('key_text', _dkx).execute()
                            if _de.data:
                                supabase.table('ledger_division_rules').update({
                                    'division_id': did, 'updated_at': _dnow,
                                }).eq('id', _de.data[0]['id']).execute()
                            else:
                                supabase.table('ledger_division_rules').insert({
                                    'facility_code': f_code, 'key_type': _dkt,
                                    'key_text': _dkx, 'match_type': 'exact',
                                    'division_id': did, 'source': 'manual',
                                }).execute()
            # 学習辞書に記録(商品名があれば item、無ければ store)
            if p.get('learn', True):
                item = _cr_norm(_cr_item_from_detail(row.get('amazon_detail')))
                if item:
                    key_type, key_text = 'item', item
                else:
                    key_type, key_text = 'store', _cr_norm(row.get('used_for'))
                if key_text:
                    now = _dt.datetime.utcnow().isoformat()
                    # 既存検索 -> あれば更新、無ければ挿入
                    _e = supabase.table('ledger_credit_rules').select('id')\
                        .eq('facility_code', f_code).eq('key_type', key_type)\
                        .eq('key_text', key_text).execute()
                    if _e.data:
                        supabase.table('ledger_credit_rules').update({
                            'account_id': aid, 'updated_at': now,
                        }).eq('id', _e.data[0]['id']).execute()
                    else:
                        supabase.table('ledger_credit_rules').insert({
                            'facility_code': f_code, 'key_type': key_type,
                            'key_text': key_text, 'match_type': 'exact',
                            'account_id': aid, 'source': 'manual',
                        }).execute()
                    learned += 1
        return jsonify({'status': 'success', 'applied': applied,
                        'learned': learned, 'skipped': skipped})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500




def _dr_load_rules(supabase, f_code):
    """事業の学習辞書(ledger_division_rules)を読み種別ごとに返す。"""  # ledger-credit-3b-div-v1
    exact_item = {}
    exact_store = {}
    partial = []
    try:
        res = supabase.table('ledger_division_rules').select(
            'key_type,key_text,match_type,division_id'
        ).eq('facility_code', f_code).execute()
        for r in (res.data or []):
            kt = r.get('key_type'); mt = r.get('match_type') or 'exact'
            key = _cr_norm(r.get('key_text'))
            did = r.get('division_id')
            if not key or did is None:
                continue
            if mt == 'partial' and kt == 'store':
                partial.append((key, did))
            elif kt == 'item':
                exact_item[key] = did
            elif kt == 'store':
                exact_store[key] = did
    except Exception:
        pass
    return exact_item, exact_store, partial


def _dr_suggest_one(used_for, amazon_detail, rules):
    """1明細の事業推定。(division_id, matched_by)。未割当は(None,'none')。"""  # ledger-credit-3b-div-v1
    exact_item, exact_store, partial = rules
    item = _cr_norm(_cr_item_from_detail(amazon_detail))
    store = _cr_norm(used_for)
    if item and item in exact_item:
        return exact_item[item], 'item_exact'
    if store and store in exact_store:
        return exact_store[store], 'store_exact'
    for kw, did in partial:
        if kw and kw in store:
            return did, 'store_partial'
    return None, 'none'


@app.route('/api/ledger/partial_rules', methods=['GET'])  # ledger-credit-3bp-v1
@login_required
def api_ledger_partial_rules_get():
    """部分一致キーワードルール一覧(科目・事業をkeywordで統合)を返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        # 科目のpartial
        cr = supabase.table('ledger_credit_rules').select('key_text,account_id')\
            .eq('facility_code', f_code).eq('key_type', 'store')\
            .eq('match_type', 'partial').execute()
        # 事業のpartial
        dr = supabase.table('ledger_division_rules').select('key_text,division_id')\
            .eq('facility_code', f_code).eq('key_type', 'store')\
            .eq('match_type', 'partial').execute()
        acc = supabase.table('accounts').select('id,code,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        acc_map = {a['id']: a for a in (acc.data or [])}
        dv = supabase.table('ledger_divisions').select('id,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        div_map = {d['id']: d for d in (dv.data or [])}
        merged = {}
        for r in (cr.data or []):
            k = _cr_norm(r.get('key_text'))
            if not k:
                continue
            merged.setdefault(k, {'keyword': k, 'account': None, 'division': None})
            aid = r.get('account_id')
            if aid is not None and aid in acc_map:
                a = acc_map[aid]
                merged[k]['account'] = {'id': a['id'], 'code': a['code'], 'name': a['name']}
        for r in (dr.data or []):
            k = _cr_norm(r.get('key_text'))
            if not k:
                continue
            merged.setdefault(k, {'keyword': k, 'account': None, 'division': None})
            did = r.get('division_id')
            if did is not None and did in div_map:
                d = div_map[did]
                merged[k]['division'] = {'id': d['id'], 'name': d['name']}
        rules = sorted(merged.values(), key=lambda x: x['keyword'])
        return jsonify({'status': 'success', 'rules': rules})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/partial_rule', methods=['POST'])  # ledger-credit-3bp-v1
@login_required
def api_ledger_partial_rule_save():
    """部分一致ルールをupsert。keyword+account_id必須、division_id任意。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        import datetime as _dt
        data = request.json or {}
        kw = _cr_norm(data.get('keyword'))
        aid = data.get('account_id')
        did = data.get('division_id')
        if not kw:
            return jsonify({'status': 'error', 'message': '\u30ad\u30fc\u30ef\u30fc\u30c9\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044'}), 400
        if aid is None:
            return jsonify({'status': 'error', 'message': '\u79d1\u76ee\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044'}), 400
        # 科目検証
        _a = supabase.table('accounts').select('id').eq('id', aid)\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        if not _a.data:
            return jsonify({'status': 'error', 'message': 'bad_account'}), 400
        now = _dt.datetime.utcnow().isoformat()
        # 科目 partial upsert
        _e = supabase.table('ledger_credit_rules').select('id')\
            .eq('facility_code', f_code).eq('key_type', 'store')\
            .eq('key_text', kw).execute()
        if _e.data:
            supabase.table('ledger_credit_rules').update({
                'account_id': aid, 'match_type': 'partial', 'updated_at': now,
            }).eq('id', _e.data[0]['id']).execute()
        else:
            supabase.table('ledger_credit_rules').insert({
                'facility_code': f_code, 'key_type': 'store', 'key_text': kw,
                'match_type': 'partial', 'account_id': aid, 'source': 'manual',
            }).execute()
        # 事業 partial upsert(division_idが渡されたときのみ)
        if did is not None:
            _dchk = supabase.table('ledger_divisions').select('id').eq('id', did)\
                .eq('facility_code', f_code).eq('is_active', True).execute()
            if _dchk.data:
                _de = supabase.table('ledger_division_rules').select('id')\
                    .eq('facility_code', f_code).eq('key_type', 'store')\
                    .eq('key_text', kw).execute()
                if _de.data:
                    supabase.table('ledger_division_rules').update({
                        'division_id': did, 'match_type': 'partial', 'updated_at': now,
                    }).eq('id', _de.data[0]['id']).execute()
                else:
                    supabase.table('ledger_division_rules').insert({
                        'facility_code': f_code, 'key_type': 'store', 'key_text': kw,
                        'match_type': 'partial', 'division_id': did, 'source': 'manual',
                    }).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/partial_rule', methods=['DELETE'])  # ledger-credit-3bp-v1
@login_required
def api_ledger_partial_rule_delete():
    """部分一致ルールをkeywordで削除(科目・事業両方)。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        data = request.json or {}
        kw = _cr_norm(data.get('keyword'))
        if not kw:
            return jsonify({'status': 'error', 'message': 'keyword required'}), 400
        supabase.table('ledger_credit_rules').delete()\
            .eq('facility_code', f_code).eq('key_type', 'store')\
            .eq('match_type', 'partial').eq('key_text', kw).execute()
        supabase.table('ledger_division_rules').delete()\
            .eq('facility_code', f_code).eq('key_type', 'store')\
            .eq('match_type', 'partial').eq('key_text', kw).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/credit_preview', methods=['POST'])  # ledger-credit-3bp-v1
@login_required
def api_ledger_credit_preview():
    """全明細(既定:未割当のみ)を走査し、各明細の推定をまとめて返す。保存はしない。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        data = request.json or {}
        only_unassigned = data.get('only_unassigned', True)
        rules = _cr_load_rules(supabase, f_code)
        drules = _dr_load_rules(supabase, f_code)
        acc = supabase.table('accounts').select('id,code,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        acc_map = {a['id']: a for a in (acc.data or [])}
        dv = supabase.table('ledger_divisions').select('id,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        div_map = {d['id']: d for d in (dv.data or [])}
        res = supabase.table('ledger_orico_statements')\
            .select('id,payment_date,used_date,used_for,amount,amazon_detail,account_id,division_id')\
            .eq('facility_code', f_code).order('payment_date', desc=True).order('used_date').execute()
        out = []
        for r in (res.data or []):
            cur_a = r.get('account_id')
            cur_d = r.get('division_id')
            # 未割当のみモード: 科目が既にある明細はスキップ
            if only_unassigned and cur_a is not None:
                continue
            aid, by = _cr_suggest_one(r.get('used_for'), r.get('amazon_detail'), rules)
            did, dby = _dr_suggest_one(r.get('used_for'), r.get('amazon_detail'), drules)
            # 推定が何もない明細は返さない(仕分け対象外)
            if aid is None and did is None:
                continue
            acct = None
            if aid is not None and aid in acc_map:
                a = acc_map[aid]
                acct = {'id': a['id'], 'code': a['code'], 'name': a['name']}
            dvv = None
            if did is not None and did in div_map:
                d = div_map[did]
                dvv = {'id': d['id'], 'name': d['name']}
            out.append({
                'id': r['id'],
                'payment_date': r.get('payment_date'),
                'used_date': r.get('used_date'),
                'used_for': r.get('used_for') or '',
                'amount': r.get('amount'),
                'suggested_account': acct,
                'matched_by': by,
                'suggested_division': dvv,
                'division_matched_by': dby,
            })
        return jsonify({'status': 'success', 'previews': out})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============ /ledger-credit-rules-v1 ============



def is_sekkotsu_enabled(supabase, f_code):  # sekkotsu-guard-v1
    """\u63a5\u9aa8\u9662\u30e2\u30fc\u30c9\u306e\u4e8c\u6bb5\u968e\u30d5\u30e9\u30b0\u5224\u5b9a\u3002facilities.sekkotsu_mode_allowed \u304b\u3064 ledger_settings.sekkotsu_mode_enabled \u304c\u4e21\u65b9True\u306a\u3089True\u3002"""
    try:
        fa = supabase.table('facilities').select('sekkotsu_mode_allowed').eq('facility_code', f_code).execute()
        if not (fa.data and fa.data[0].get('sekkotsu_mode_allowed')):
            return False
        ls = supabase.table('ledger_settings').select('sekkotsu_mode_enabled').eq('facility_code', f_code).execute()
        return bool(ls.data and ls.data[0].get('sekkotsu_mode_enabled'))
    except Exception:
        return False


def is_credit_enabled(supabase, f_code):  # ledger-credit-mode-v1
    """クレカ明細モード: 接骨院モードON かつ credit_mode_enabled True で True。"""
    try:
        if not is_sekkotsu_enabled(supabase, f_code):
            return False
        ls = supabase.table('ledger_settings').select('credit_mode_enabled').eq('facility_code', f_code).execute()
        return bool(ls.data and ls.data[0].get('credit_mode_enabled'))
    except Exception:
        return False


@app.route('/api/ledger/reconcile', methods=['POST'])  # ledger-reconcile-v1
@login_required
def api_ledger_reconcile():
    """\u65e5\u8a08\u8868\u3068\u30b9\u30de\u30ec\u30b8\u3092\u7a81\u5408\u3057\u3001\u5dee\u984d\u306f\u30b3\u30fc\u30c9\u304c\u7b97\u51fa\u3001\u539f\u56e0\u8aac\u660e\u306e\u307f AI\u3002\u4fdd\u5b58\u306a\u3057\u3002"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_sekkotsu_enabled(supabase, f_code):  # ledger-reconcile-v1
        return jsonify({'status': 'error', 'message': '\u63a5\u9aa8\u9662\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        import csv as _csv, io as _io
        from collections import Counter as _Counter

        def _to_int(x):
            x = (x or '').strip()
            return int(x) if x.replace('-', '').isdigit() else 0

        def _read(file_storage):
            raw = file_storage.read()
            for enc in ('utf-8-sig', 'cp932', 'utf-8'):
                try:
                    return raw.decode(enc)
                except Exception:
                    pass
            return raw.decode('cp932', 'replace')

        f_nik = request.files.get('nikkei')
        f_sm = request.files.get('smaregi')
        if not f_nik or not f_sm:
            return jsonify({'status': 'error', 'message': '\u65e5\u8a08\u8868\u3068\u30b9\u30de\u30ec\u30b8\u306eCSV\u304c\u5fc5\u8981\u3067\u3059'}), 400
        nik_text = _read(f_nik)
        sm_text = _read(f_sm)

        # \u65e5\u8a08\u8868: \u5165\u91d1\u984d\u5408\u8a08\uff08\u5165\u91d10\u9664\u304f\uff09
        nik_rows = list(_csv.reader(_io.StringIO(nik_text)))
        if nik_rows and nik_rows[0] and nik_rows[0][0].strip() == '\u65e5\u4ed8':
            nik_rows = nik_rows[1:]
        nik_total = 0
        nik_amounts = _Counter()
        for r in nik_rows:
            if not any((c or '').strip() for c in r):
                continue
            if len(r) < 11:
                continue
            ny = _to_int(r[10])
            if ny <= 0:
                continue
            nik_total += ny
            nik_amounts[ny] += 1

        # \u30b9\u30de\u30ec\u30b8: \u53d6\u6d88\u533a\u5206=1\u9664\u5916\uff0b\u540c\u4e00\u65e5\u6642\u540c\u984d\u96c6\u7d04\u3001\u73fe\u91d1\u5217\u5408\u8a08
        sm_rows = list(_csv.reader(_io.StringIO(sm_text)))
        sm_header = sm_rows[0] if sm_rows else []
        has_cancel = any('\u53d6\u6d88' in (h or '') for h in sm_header)
        seen = set()
        sm_cash = 0
        sm_amounts = _Counter()
        for r in sm_rows[1:]:
            if not r or not r[0].strip():
                continue
            if has_cancel:
                if len(r) < 5:
                    continue
                if r[1].strip() == '1':
                    continue
                key = (r[0].strip(), _to_int(r[2]))
                if key in seen:
                    continue
                seen.add(key)
                sm_cash += _to_int(r[4])
                sm_amounts[_to_int(r[2])] += 1
            else:
                if len(r) < 4:
                    continue
                key = (r[0].strip(), _to_int(r[1]))
                if key in seen:
                    continue
                seen.add(key)
                sm_cash += _to_int(r[3])
                sm_amounts[_to_int(r[1])] += 1

        diff = nik_total - sm_cash
        by_amount = []
        for a in sorted(set(list(nik_amounts) + list(sm_amounts)), reverse=True):
            dc = nik_amounts[a] - sm_amounts[a]
            if dc != 0:
                by_amount.append({'amount': a, 'nikkei': nik_amounts[a], 'smaregi': sm_amounts[a], 'diff_count': dc})

        summary = {
            'nikkei_total': nik_total,
            'smaregi_cash': sm_cash,
            'diff': diff,
            'by_amount_diff': by_amount,
        }

        # AI \u306f\u8aac\u660e\u306e\u307f\uff08\u6570\u5024\u306f\u30b3\u30fc\u30c9\u304c\u78ba\u5b9a\u3055\u305b\u305f\u3082\u306e\u3092\u6e21\u3059\uff09
        ai_text = ''
        try:
            from utils import get_generative_model
            model = get_generative_model()
            _facts = (
                "\u65e5\u8a08\u8868\u7a93\u53e3\u5165\u91d1\u5408\u8a08=" + str(nik_total) + "\u5186 / "
                "\u30b9\u30de\u30ec\u30b8\u73fe\u91d1\u5408\u8a08\uff08\u53d6\u6d88\u9664\u5916\u30fb\u91cd\u8907\u96c6\u7d04\u5f8c\uff09=" + str(sm_cash) + "\u5186 / "
                "\u5dee\u984d\uff08\u65e5\u8a08\u8868\u2212\u30b9\u30de\u30ec\u30b8\u73fe\u91d1\uff09=" + str(diff) + "\u5186\u3002"
            )
            _detail = ''
            if by_amount:
                _detail = " \u91d1\u984d\u5225\u306e\u4ef6\u6570\u5dee: " + ', '.join(
                    [str(b['amount']) + "\u5186(\u65e5\u8a08\u8868" + str(b['nikkei']) + "/\u30b9\u30de\u30ec\u30b8" + str(b['smaregi']) + ")" for b in by_amount[:8]]
                )
            prompt = (
                "\u3042\u306a\u305f\u306f\u63a5\u9aa8\u9662\u306e\u4f1a\u8a08\u88dc\u52a9AI\u3067\u3059\u3002\u4ee5\u4e0b\u306f\u30b3\u30fc\u30c9\u304c\u53b3\u5bc6\u306b\u8a08\u7b97\u3057\u305f\u78ba\u5b9a\u5024\u3067\u3059\u3002"
                "\u6570\u5024\u306f\u7d76\u5bfe\u306b\u5909\u66f4\u305b\u305a\u3001\u3053\u306e\u5dee\u984d\u306e\u8003\u3048\u3089\u308c\u308b\u539f\u56e0\u3068\u63a8\u5968\u30a2\u30af\u30b7\u30e7\u30f3\u3092\u3001\u73fe\u5834\u306e\u4eba\u304c\u8aad\u3093\u3067\u5206\u304b\u308b\u8a00\u8449\u3067\u7c21\u6f54\u306b\u8aac\u660e\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
                "\u8003\u3048\u3089\u308c\u308b\u539f\u56e0\u4f8b: \u30ad\u30e3\u30c3\u30b7\u30e5\u30ec\u30b9\u6c7a\u6e08\uff08PayPay/\u697d\u5929/\u30ab\u30fc\u30c9\uff09\u306f\u65e5\u8a08\u8868\u306b\u306f\u8f09\u308b\u304c\u30b9\u30de\u30ec\u30b8\u73fe\u91d1\u306b\u306f\u542b\u307e\u308c\u306a\u3044\u3001\u5165\u529b\u5fd8\u308c\u3001\u30ad\u30e3\u30f3\u30bb\u30eb\u6b8b\u5b58\u3001\u6708\u307e\u305f\u304e\u8a08\u4e0a\u306a\u3069\u3002\n\n"
                + _facts + _detail
            )
            ai_text = model.generate_content([prompt]).text.strip()
        except Exception as _e:
            ai_text = ''

        return jsonify({'status': 'success', 'summary': summary, 'ai_explanation': ai_text})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _cashless_parse(file_storage):  # ledger-cashless-v1  # ledger-cashless-rakuten-fix-v3
    """PayPay / 楽天 のCSVを読み、(date 'YYYY-MM-DD', amount int, kind str) のリストを返す。
    楽天はアプリ/カード決済（合計金額(円)・利用カード）と
    電子マネー決済（電子マネー支払(円)・QUICPay等）の両形式に対応。"""
    import csv as _csv, io as _io
    raw = file_storage.read()
    text = None
    for enc in ('utf-8-sig', 'cp932', 'utf-8'):
        try:
            text = raw.decode(enc); break
        except Exception:
            pass
    if text is None:
        text = raw.decode('cp932', 'replace')
    rows = list(_csv.reader(_io.StringIO(text)))
    if not rows:
        return []
    header = rows[0]
    def _to_int(x):
        x = (x or '').strip().replace(',', '').replace('，', '')
        return int(x) if x.replace('-', '').isdigit() else 0
    out = []
    # PayPay: 取引日時 / 取引金額 / 支払い方法 / 取引ステータス
    is_paypay = any('支払い方法' in (h or '') for h in header) and any('取引日時' in (h or '') for h in header)
    # 楽天: 利用カード または 電子マネー支払 または 合計金額 を含む（PayPayを除く）
    is_rakuten = (not is_paypay) and any(
        ('利用カード' in (h or '')) or
        ('電子マネー支払' in (h or '')) or
        ('合計金額' in (h or ''))
        for h in header
    )
    if is_paypay:
        idx_dt = next((i for i, h in enumerate(header) if '取引日時' in (h or '')), 4)
        idx_amt = next((i for i, h in enumerate(header) if '取引金額' in (h or '')), 5)
        idx_st = next((i for i, h in enumerate(header) if '取引ステータス' in (h or '')), 3)
        idx_pm = next((i for i, h in enumerate(header) if '支払い方法' in (h or '')), 6)
        for r in rows[1:]:
            if len(r) <= max(idx_dt, idx_amt, idx_st, idx_pm):
                continue
            if r[idx_st].strip() != '取引完了':
                continue
            d = r[idx_dt].strip()[:10].replace('/', '-')
            out.append({'date': d, 'amount': _to_int(r[idx_amt]), 'kind': 'PayPay:' + r[idx_pm].strip()})
    elif is_rakuten:
        idx_d = next((i for i, h in enumerate(header) if (h or '').strip() == '取引日'), 0)
        # 金額列: 合計金額 を優先、なければ 電子マネー支払
        idx_amt = next((i for i, h in enumerate(header) if '合計金額' in (h or '')), -1)
        if idx_amt < 0:
            idx_amt = next((i for i, h in enumerate(header) if '電子マネー支払' in (h or '')), 3)
        # ステータス列: 'ステータス' または '処理内容'
        idx_st = next((i for i, h in enumerate(header) if (h or '').strip() in ('ステータス', '処理内容')), -1)
        # 決済方法列（au PAY / QUICPay 等）を kind に付与
        idx_pm = next((i for i, h in enumerate(header) if (h or '').strip() == '決済方法'), -1)
        for r in rows[1:]:
            if len(r) <= max(idx_d, idx_amt):
                continue
            if not r[idx_d].strip():
                continue
            if idx_st >= 0 and len(r) > idx_st and r[idx_st].strip() and '売上' not in r[idx_st]:
                continue
            pm = ''
            if idx_pm >= 0 and len(r) > idx_pm:
                pm = r[idx_pm].strip().strip('"')
            kind = ('楽天:' + pm) if pm else '楽天'
            out.append({'date': r[idx_d].strip()[:10].replace('/', '-'), 'amount': _to_int(r[idx_amt]), 'kind': kind})
    return out

@app.route('/api/ledger/cashless_match', methods=['POST'])  # ledger-cashless-v1
@login_required
def api_ledger_cashless_match():
    """\u30ad\u30e3\u30c3\u30b7\u30e5\u30ec\u30b9CSV\u3092\u4fdd\u5b58\u6e08\u65e5\u8a08\u8868\u4ed5\u8a33\u3068\u65e5\u4ed8\uff0b\u91d1\u984d\u3067\u7167\u5408\u3057\u3001\u632f\u66ff\u30d7\u30ec\u30d3\u30e5\u30fc\u3092\u8fd4\u3059\u3002\u4fdd\u5b58\u306a\u3057\u3002"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_sekkotsu_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u63a5\u9aa8\u9662\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        month = (request.form.get('month') or '').strip()  # 'YYYY-MM'
        if len(month) != 7:
            return jsonify({'status': 'error', 'message': '\u6708\uff08YYYY-MM\uff09\u3092\u6307\u5b9a\u3057\u3066\u304f\u3060\u3055\u3044'}), 400

        # \u30ad\u30e3\u30c3\u30b7\u30e5\u30ec\u30b9\u53d6\u5f15\u3092\u96c6\u7d04
        cashless = []
        for fs in request.files.getlist('files'):
            cashless.extend(_cashless_parse(fs))

        # \u73fe\u91d1(101) account_id \u3092\u30b3\u30fc\u30c9\u304b\u3089\u52d5\u7684\u53d6\u5f97
        acc = supabase.table('accounts').select('id,code').eq('facility_code', f_code).in_('code', ['101']).execute()
        cash_id = None
        for a in (acc.data or []):
            if a['code'] == '101':
                cash_id = a['id']

        # \u305d\u306e\u6708\u306e\u4fdd\u5b58\u6e08\u65e5\u8a08\u8868\u4ed5\u8a33\uff08\u501f\u65b9=\u73fe\u91d1\u3001source=nikkei_csv\uff09
        start = month + '-01'
        # \u6708\u672b\u306f\u7ffb\u6708\u5224\u5b9a\u3067\u6b21\u6708\u521d\u65e5\u672a\u6e80
        y, m = int(month[:4]), int(month[5:7])
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        nxt = '%04d-%02d-01' % (ny, nm)
        q = supabase.table('journal_entries').select(
            'id,entry_date,amount,debit_account_id,insurance_type,settlement_status,credit_account_id'
        ).eq('facility_code', f_code).eq('source', 'nikkei_csv').gte('entry_date', start).lt('entry_date', nxt).execute()
        entries = q.data or []

        # \u65e5\u4ed8\uff0b\u91d1\u984d -> [\u73fe\u91d1\u501f\u65b9\u306e\u4ed5\u8a33id]
        from collections import defaultdict as _dd
        idx = _dd(list)
        for e in entries:
            if cash_id is not None and e.get('debit_account_id') != cash_id:
                continue
            if e.get('settlement_status') == 'unpaid_cashless':
                continue  # \u65e2\u306b\u632f\u66ff\u6e08\u307f\u306f\u9664\u5916
            idx[(e['entry_date'], e['amount'])].append(e['id'])

        results = []
        auto = review = none = 0
        for c in sorted(cashless, key=lambda x: (x['date'], x['amount'])):
            cands = idx.get((c['date'], c['amount']), [])
            if len(cands) == 1:
                st = 'auto'; auto += 1
            elif len(cands) >= 2:
                st = 'review'; review += 1
            else:
                st = 'none'; none += 1
            results.append({'date': c['date'], 'amount': c['amount'], 'kind': c['kind'], 'status': st, 'candidates': cands})

        return jsonify({'status': 'success', 'summary': {'auto': auto, 'review': review, 'none': none, 'total': len(cashless)}, 'results': results})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/cashless_apply', methods=['POST'])  # ledger-cashless-v1
@login_required
def api_ledger_cashless_apply():
    """\u78ba\u5b9a\u3057\u305f\u4ed5\u8a33\u306e\u501f\u65b9\u3092 \u73fe\u91d1(101)\u2192\u672a\u53ce\u5165\u91d1(104) \u306b\u66f8\u63db\u3057\u3001settlement_status\u3092\u7acb\u3066\u308b\u3002"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_sekkotsu_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u63a5\u9aa8\u9662\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        data = request.json or {}
        items = data.get('items') or []  # [{entry_id, cashless_type}]
        if not items:
            return jsonify({'status': 'error', 'message': '\u632f\u66ff\u5bfe\u8c61\u304c\u3042\u308a\u307e\u305b\u3093'}), 400

        # 104 account_id \u3092\u30b3\u30fc\u30c9\u304b\u3089\u52d5\u7684\u53d6\u5f97
        acc = supabase.table('accounts').select('id,code').eq('facility_code', f_code).in_('code', ['101', '104']).execute()
        cash_id = uncollected_id = None
        for a in (acc.data or []):
            if a['code'] == '101':
                cash_id = a['id']
            if a['code'] == '104':
                uncollected_id = a['id']
        if uncollected_id is None:
            return jsonify({'status': 'error', 'message': '\u672a\u53ce\u5165\u91d1(104)\u304c\u672a\u767b\u9332\u3067\u3059'}), 400

        applied = 0
        for it in items:
            eid = it.get('entry_id')
            ctype = (it.get('cashless_type') or '').strip()
            if eid is None:
                continue
            # \u5b89\u5168\u306e\u305f\u3081\u3001\u5bfe\u8c61\u304c\u305d\u306e\u65bd\u8a2d\u30fbnikkei_csv\u30fb\u501f\u65b9\u73fe\u91d1\u3067\u3042\u308b\u3053\u3068\u3092\u78ba\u8a8d
            row = supabase.table('journal_entries').select('id,debit_account_id,source,facility_code').eq('id', eid).eq('facility_code', f_code).execute()
            if not row.data:
                continue
            r0 = row.data[0]
            if r0.get('source') != 'nikkei_csv':
                continue
            if cash_id is not None and r0.get('debit_account_id') != cash_id:
                continue
            upd = {'debit_account_id': uncollected_id, 'settlement_status': 'unpaid_cashless'}
            if ctype:
                upd['settlement_note'] = ctype  # \u4efb\u610f: \u7a2e\u5225\u30e1\u30e2\uff08\u5217\u304c\u7121\u3051\u308c\u3070\u7121\u8996\u3055\u308c\u308b\u53ef\u80fd\u6027\u3042\u308a\u2192except\u3067\u518d\u8a66\u884c\uff09
            try:
                supabase.table('journal_entries').update(upd).eq('id', eid).eq('facility_code', f_code).execute()
            except Exception:
                supabase.table('journal_entries').update({'debit_account_id': uncollected_id, 'settlement_status': 'unpaid_cashless'}).eq('id', eid).eq('facility_code', f_code).execute()
            applied += 1

        return jsonify({'status': 'success', 'applied': applied})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/import_nikkei', methods=['POST'])  # nikkei-import-api-v1
@login_required
def api_ledger_import_nikkei():
    """\u65e5\u8a08\u8868CSV\u3092\u30eb\u30fc\u30eb\u30d9\u30fc\u30b9\u3067\u73fe\u91d1\u5206\u4ed5\u8a33\u306b\u5909\u63db\u3057\u3066\u8fd4\u3059\uff08\u4fdd\u5b58\u306f\u30d5\u30ed\u30f3\u30c8\u78ba\u8a8d\u5f8c\uff09\u3002"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_sekkotsu_enabled(supabase, f_code):  # sekkotsu-guard-v1
        return jsonify({'status': 'error', 'message': '\u63a5\u9aa8\u9662\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        import csv as _csv, io as _io, hashlib as _hashlib
        f = request.files.get('file')
        if not f:
            return jsonify({'status': 'error', 'message': '\u30d5\u30a1\u30a4\u30eb\u304c\u3042\u308a\u307e\u305b\u3093'}), 400
        raw = f.read()
        content = None
        for enc in ('utf-8-sig', 'cp932', 'utf-8'):
            try:
                content = raw.decode(enc)
                break
            except Exception:
                content = None
        if content is None:
            content = raw.decode('cp932', 'replace')

        # \u79d1\u76ee\u30b3\u30fc\u30c9 -> id
        acc_res = supabase.table('accounts').select('id,code').eq('facility_code', f_code).eq('is_active', True).execute()
        code_to_id = {a['code']: a['id'] for a in (acc_res.data or [])}
        # \u5fc5\u8981\u79d1\u76ee\u306e\u5b58\u5728\u78ba\u8a8d
        missing = [c for c in ('101', '404', '405') if c not in code_to_id]
        if missing:
            return jsonify({'status': 'error', 'message': '\u79d1\u76ee\u672a\u4f5c\u6210: ' + ','.join(missing)}), 400

        # \u63a5\u9aa8\u9662 division_id\uff08\u540d\u79f0\u306b\u63a5\u9aa8\u3092\u542b\u3080\u3082\u306e\uff09\u3092\u63a2\u3059\uff08\u7121\u3051\u308c\u3070 None\uff09
        div_id = None
        try:
            d_res = supabase.table('ledger_divisions').select('id,name').eq('facility_code', f_code).eq('is_active', True).execute()
            for d in (d_res.data or []):
                if '\u63a5\u9aa8' in (d.get('name') or ''):
                    div_id = d['id']
                    break
        except Exception:
            div_id = None

        HOKEN_MAP = {'\u56fd\u672c': '\u56fd\u4fdd', '\u56fd\u4fdd': '\u56fd\u4fdd',
                     '\u7d44\u672c': '\u7d44\u5408', '\u7d44\u5408': '\u7d44\u5408',
                     '\u5f8c\u671f': '\u5f8c\u671f'}

        def _to_int(x):
            x = (x or '').strip()
            return int(x) if x.replace('-', '').isdigit() else 0

        rows = list(_csv.reader(_io.StringIO(content)))
        if rows and rows[0] and rows[0][0].strip() == '\u65e5\u4ed8':
            rows = rows[1:]
        batch = 'nikkei_' + _hashlib.md5(content.encode('utf-8', 'replace')).hexdigest()[:10]

        suggestions = []
        entries = []

        def _push(date, credit_code, amount, ins, desc, review=False):
            debit_id = code_to_id.get('101')
            credit_id = code_to_id.get(credit_code)
            if not (debit_id and credit_id and amount > 0):
                return
            suggestions.append({'entry_date': date, 'debit_code': '101', 'credit_code': credit_code,
                                 'amount': amount, 'description': desc, 'insurance_type': ins,
                                 'needs_review': review})
            entries.append({'facility_code': f_code, 'entry_date': date,
                            'debit_account_id': debit_id, 'credit_account_id': credit_id,
                            'amount': amount, 'tax_amount': 0, 'description': desc,
                            'source': 'nikkei_csv', 'created_by': my_name,
                            'division_id': div_id, 'insurance_type': ins,
                            'settlement_status': None, 'import_batch_id': batch})

        for r in rows:
            if not any((c or '').strip() for c in r):
                continue
            if len(r) < 11:
                continue
            date = r[0].strip().replace('/', '-')
            hoken = r[3].strip()
            nyukin = _to_int(r[10])
            if nyukin <= 0:
                continue
            if hoken == '\u81ea\u8cbb':
                _push(date, '404', nyukin, '\u81ea\u8cbb', '\u63a5\u9aa8\u9662 \u81ea\u8cbb\u58f2\u4e0a')
            elif hoken in HOKEN_MAP:
                ins = HOKEN_MAP[hoken]
                hbun = _to_int(r[7])
                hgai = _to_int(r[8])
                if hbun > 0:
                    _push(date, '405', hbun, ins, '\u63a5\u9aa8\u9662 \u5065\u5eb7\u4fdd\u967a\u58f2\u4e0a(\u7a93\u53e3\u8ca0\u62c5)')
                if hgai > 0:
                    _push(date, '404', hgai, '\u81ea\u8cbb', '\u63a5\u9aa8\u9662 \u81ea\u8cbb\u58f2\u4e0a(\u4fdd\u967a\u5916)')
            else:
                _push(date, '404', nyukin, hoken or '\u4e0d\u660e',
                      '\u63a5\u9aa8\u9662 \u58f2\u4e0a(\u533a\u5206\u8981\u78ba\u8a8d)', review=True)

        return jsonify({'status': 'success', 'imported': 0, 'batch_id': batch,
                        'suggestions': suggestions, 'entries': entries})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/ocr_receipt', methods=['POST'])
@login_required
def api_ledger_ocr_receipt():
    """領収書OCR"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    try:
        from utils import get_generative_model, upload_images_to_supabase
        supabase = get_supabase()
        files = request.files.getlist('files')
        if not files:
            return jsonify({'status': 'error', 'message': 'ファイルがありません'}), 400
        model = get_generative_model()
        results = []
        for f in files:
            img_bytes = f.read()
            f.seek(0)  # アップロード用にポインタリセット
            mime = 'image/jpeg'
            if f.filename.lower().endswith('.png'):
                mime = 'image/png'
            prompt = (
                "この領収書・レシートから以下の情報をJSONで抽出してください。\n"
                '{"date":"YYYY-MM-DD","amount":0,"tax_amount":0,"vendor":"店名","description":"内容","tax_rate":10}\n'
                "判読できない場合はnullを入れてください。JSONのみ返してください。"
            )
            resp = model.generate_content([{"mime_type": mime, "data": img_bytes}, prompt])
            raw = resp.text.strip()
            import re as _re, json as _json
            raw = _re.sub(r'^```[a-zA-Z]*\n?', '', raw).strip()
            raw = _re.sub(r'```$', '', raw).strip()
            ocr = _json.loads(raw)
            # dateフォーマット正規化
            import re as _re2
            if ocr.get('date'):
                d_str = str(ocr['date'])
                d_match = _re2.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', d_str)
                if d_match:
                    ocr['date'] = f"{d_match.group(1)}-{d_match.group(2).zfill(2)}-{d_match.group(3).zfill(2)}"
            # 金額を整数変換
            try: ocr['amount'] = int(str(ocr.get('amount',0)).replace(',','').replace('円','') or 0)
            except: ocr['amount'] = 0
            try: ocr['tax_amount'] = int(str(ocr.get('tax_amount',0)).replace(',','').replace('円','') or 0)
            except: ocr['tax_amount'] = 0
            # 画像をSupabaseにアップロード
            urls = upload_images_to_supabase(supabase, [f], f_code)
            image_url = urls[0] if urls else ''
            # receiptsテーブルに保存
            rec_res = supabase.table('receipts').insert({
                'facility_code': f_code,
                'image_url': image_url,
                'ocr_result': ocr,
                'created_by': my_name,
            }).execute()
            receipt_id = rec_res.data[0]['id'] if rec_res.data else None
            results.append({'receipt_id': receipt_id, 'ocr': ocr, 'image_url': image_url})
        return jsonify({'status': 'success', 'results': results})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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


@app.route('/case_records')
@login_required
def case_records():
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
    return render("case_records.html")

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
            board_editors=[], admin_managers=[])

    # 管理者認証(個人パスワード + admin_managers リストに含まれているかチェック)
    try:
        import hashlib
        def verify_password(p, h):
            return hashlib.sha256(p.encode()).hexdigest() == h
        supabase = get_supabase()
        my_name = session.get("my_name", "")

        # まず、ログイン中スタッフの個人パスワードと一致するか確認
        staff_res = supabase.table("staffs").select("staff_name,password_hash,email").eq(
            "facility_code", f_code
        ).eq("staff_name", my_name).eq("is_active", True).execute()

        if not staff_res.data:
            return render_template("admin.html",
                authenticated=False, dev_mode=False,
                patients=[], blocked=[], staff_list=[],
                hist_limit=30, error="ログイン情報が確認できません。",
                claude_url=None, registered_staffs=[], f_code=f_code,
                board_editors=[], admin_managers=[])

        s = staff_res.data[0]
        if not verify_password(pw, s.get("password_hash", "")):
            return render_template("admin.html",
                authenticated=False, dev_mode=False,
                patients=[], blocked=[], staff_list=[],
                hist_limit=30, error="パスワードが違います。",
                claude_url=None, registered_staffs=[], f_code=f_code,
                board_editors=[], admin_managers=[])

        # パスワードはOK、次に管理者として認可されているかチェック
        # (admin_managers リスト OR facilities.admin_email スタッフ = 超管理者)
        if not is_admin_user(supabase, f_code, my_name):
            return render_template("admin.html",
                authenticated=False, dev_mode=False,
                patients=[], blocked=[], staff_list=[],
                hist_limit=30, error="管理者権限がありません。施設の管理者にお問い合わせください。",
                claude_url=None, registered_staffs=[], f_code=f_code,
                board_editors=[], admin_managers=[])

        session["admin_authenticated"] = True
        return redirect(url_for("admin"))
    except Exception as e:
        return render_template("admin.html",
            authenticated=False, dev_mode=False,
            patients=[], blocked=[], staff_list=[],
            hist_limit=30, error=f"認証中にエラーが発生しました: {e}",
            claude_url=None, registered_staffs=[], f_code=f_code,
            board_editors=[], admin_managers=[])

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
                    # Session 18: weekdays から ampm_per_day を生成(全曜日 ALL)
                    ampm_per_day_init = {ch: "ALL" for ch in weekdays if ch in "0123456"}
                    try:
                        supabase.table("patient_visit_days").insert({
                            "facility_code": f_code,
                            "patient_id":    pid,
                            "user_name":     name,
                            "weekdays":      weekdays,
                            "ampm":          ampm,
                            "ampm_per_day":  ampm_per_day_init,
                        }).execute()
                    except:
                        pass
            registered += 1

        return jsonify({"status": "success", "count": registered})
    except Exception as e:
        print(f"bulk_register error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/guide_ledger')
@login_required
def guide_ledger():
    return render_template('guide_ledger.html')

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
            for name, bd in sorted(staff_with_birth.items()):
                is_b = len(supabase.table("blocked_devices").select("id").eq("staff_name", name).eq("facility_code", f_code).eq("is_active", True).execute().data) > 0
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

    # 掲示板編集許可リスト
    board_editors_list = []
    if authenticated:
        try:
            import json as _json
            res_be = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "board_editors").execute()
            if res_be.data and res_be.data[0].get("value"):
                board_editors_list = _json.loads(res_be.data[0]["value"])
                if not isinstance(board_editors_list, list):
                    board_editors_list = []
        except: pass

    # 管理者リスト(admin_managers)
    admin_managers_list = []
    if authenticated:
        try:
            admin_managers_list = get_admin_managers(supabase, f_code)
        except: pass

    claude_url = session.pop("claude_url", None)
    if claude_url:
        claude_url = request.host_url.rstrip('/') + claude_url

    patient_profiles = []
    try:
        pp_res = supabase.table('patient_profiles').select('id, user_name, user_name_kana, patient_number, care_level, is_discontinued').eq('facility_code', f_code).order('user_name_kana').execute()
        patient_profiles = pp_res.data or []
    except: pass

    return render_template("admin.html",
        authenticated=authenticated,
        dev_mode=False,
        patients=patients,
        patient_profiles=patient_profiles,
        blocked=blocked,
        staff_list=staff_list,
        hist_limit=hist_limit,
        error=None,
        claude_url=claude_url,
        registered_staffs=registered_staffs,
        f_code=f_code,
        board_editors=board_editors_list,
        admin_managers=admin_managers_list,
        supabase_url=os.environ.get('SUPABASE_URL', ''),
        supabase_anon_key=os.environ.get('SUPABASE_KEY', ''))

# ==========================================

@app.route('/patient_profile')
@login_required
def patient_profile():
    supabase = get_supabase()
    f_code   = session.get('f_code', '')
    sel_id   = request.args.get('id')
    try:
        res = supabase.table('patient_profiles') \
            .select('id, user_name, user_name_kana, patient_number') \
            .eq('facility_code', f_code) \
            .order('user_name_kana') \
            .execute()
        patients = res.data or []
    except Exception:
        patients = []
    selected = None
    if sel_id:
        try:
            res = supabase.table('patient_profiles') \
                .select('*') \
                .eq('id', sel_id) \
                .eq('facility_code', f_code) \
                .single() \
                .execute()
            selected = res.data
        except Exception:
            selected = None
            # patient_id と利用日データを取得
    patient_id = None
    visit_day_data = {}
    if selected:
        try:
            pr = supabase.table('patients').select('id').eq('facility_code', f_code).eq('user_name', selected['user_name']).execute()
            if pr.data:
                patient_id = pr.data[0]['id']
                vr = supabase.table('patient_visit_days').select('weekdays,ampm_per_day').eq('facility_code', f_code).eq('patient_id', patient_id).execute()
                if vr.data:
                    visit_day_data = vr.data[0]
        except Exception:
            pass
    return render_template(
        'patient_profile.html',
        patients=patients,
        selected=selected,
        supabase_url=os.environ.get('SUPABASE_URL', ''),
        patient_id=patient_id,
        visit_day_data=visit_day_data,
        supabase_anon_key=os.environ.get('SUPABASE_KEY', '')
    )

@app.route('/api/patient_profile/get_by_patient_number')
@login_required
def api_get_patient_profile_by_number():
    supabase = get_supabase()
    f_code   = session.get('f_code', '')
    p_number = request.args.get('patient_number', '')
    if not p_number:
        return jsonify({'error': 'patient_number required'}), 400
    try:
        res = supabase.table('patient_profiles') \
            .select('*') \
            .eq('facility_code', f_code) \
            .eq('patient_number', p_number) \
            .single() \
            .execute()
        return jsonify({'data': res.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
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

@app.route('/faq')
@login_required
def faq_page():
    return app.send_static_file('faq.html')

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
        update_payload = {"content": data["content"]}
        # Session 33: 休み連絡カテゴリの編集で送られたら type/relation も更新
        # (payload に含まれない場合は既存値を維持)
        if "leave_reporter_type" in data:
            _t = (data.get("leave_reporter_type") or "").strip() or None
            _r = (data.get("leave_reporter_relation") or "").strip() or None
            update_payload["leave_reporter_type"] = _t
            update_payload["leave_reporter_relation"] = _r
        if "leave_reason" in data:
            update_payload["leave_reason"] = (data.get("leave_reason") or "").strip() or None
        # leave-edit-reason-sync: 休み連絡の編集なら、日付未送信でも既存日付を補完して
        # content再生成・カレンダー同期を行えるようにする(理由だけ変更しても反映される)
        new_leave_start = (data.get("leave_date_start") or "").strip() or None
        new_leave_end = (data.get("leave_date_end") or "").strip() or None
        _is_leave_edit = ("leave_reason" in data) or ("leave_reporter_type" in data)
        if _is_leave_edit and not new_leave_start:
            try:
                _exist = supabase.table("records").select("leave_date_start,leave_date_end,category").eq("id", data["id"]).execute()
                if _exist.data:
                    _row0 = _exist.data[0]
                    if _row0.get("category") == "休み連絡":
                        new_leave_start = (_row0.get("leave_date_start") or "").strip() or None
                        new_leave_end = (_row0.get("leave_date_end") or "").strip() or None
            except Exception as _ex0:
                print(f"[休み編集 既存日付取得エラー] {_ex0}", flush=True)
        if new_leave_start:
            update_payload["leave_date_start"] = new_leave_start
            update_payload["leave_date_end"] = new_leave_end or new_leave_start
            # contentを再生成
            try:
                from datetime import datetime as _dt3
                _ls3 = _dt3.strptime(new_leave_start, "%Y-%m-%d")
                _ls3_str = f"{_ls3.month}月{_ls3.day}日"
                _type3 = (data.get("leave_reporter_type") or "").strip()
                _reason3 = (data.get("leave_reason") or "").strip()
                if new_leave_end and new_leave_end != new_leave_start:
                    _le3 = _dt3.strptime(new_leave_end, "%Y-%m-%d")
                    _period3 = f"{_ls3_str}〜{_le3.month}月{_le3.day}日"
                else:
                    _period3 = _ls3_str
                update_payload["content"] = _build_leave_content(_period3, _type3, "", _reason3)
            except Exception as _ce3:
                print(f"[休み編集content再生成エラー] {_ce3}", flush=True)
        supabase.table("records").update(update_payload).eq("id", data["id"]).execute()
        # 休み日付変更時にカレンダーイベントも同期
        if new_leave_start:
            try:
                rec_row = supabase.table("records").select("calendar_event_id,user_name").eq("id", data["id"]).execute()
                if rec_row.data:
                    cal_event_id = rec_row.data[0].get("calendar_event_id")
                    user_name_cal = rec_row.data[0].get("user_name", "")
                    if cal_event_id:
                        supabase.table("calendar_events").update({
                            "event_date": new_leave_start,
                            "end_date": new_leave_end or new_leave_start,
                            "title": f"{user_name_cal}様 お休み",
                        }).eq("id", cal_event_id).execute()
                        print(f"[休み編集] カレンダーイベント {cal_event_id} を{new_leave_start}に更新", flush=True)
            except Exception as _cal_upd:
                print(f"[休み編集カレンダー同期エラー] {_cal_upd}", flush=True)

        # Session 36: VAS データの UPSERT(全削除 → 再 INSERT)
        # payload に vas_records が含まれていれば実施。含まれていなければ既存 VAS を維持。
        if "vas_records" in data:
            try:
                # 既存の権限チェック用に records から facility_code, user_name を取得
                rec_row = supabase.table("records").select("facility_code, user_name").eq("id", data["id"]).execute()
                if rec_row.data:
                    rec_facility = rec_row.data[0]["facility_code"]
                    rec_user_name = rec_row.data[0]["user_name"]
                    # 既存 VAS を全削除
                    supabase.table("record_vas").delete().eq("record_id", data["id"]).execute()
                    # 新規 VAS を一括 INSERT(空配列なら何も入れない)
                    vas_list = data.get("vas_records") or []
                    vas_rows = []
                    for v in vas_list:
                        if not isinstance(v, dict):
                            continue
                        part = v.get("part")
                        side = v.get("side")
                        value = v.get("vas_value") if "vas_value" in v else v.get("value")
                        if not part or not side:
                            continue
                        if not isinstance(value, int) or value < 0 or value > 10:
                            continue
                        vas_rows.append({
                            "record_id": data["id"],
                            "facility_code": rec_facility,
                            "user_name": rec_user_name,
                            "part": part,
                            "side": side,
                            "vas_value": value,
                        })
                    if vas_rows:
                        supabase.table("record_vas").insert(vas_rows).execute()
                        print(f"[vas_records] updated {len(vas_rows)} entries for record {data['id']}", flush=True)
                    else:
                        print(f"[vas_records] cleared all entries for record {data['id']}", flush=True)
            except Exception as _vas_upd_err:
                print(f"[vas_records] update failed for record {data['id']}: {_vas_upd_err}", flush=True)

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
        is_admin = session.get("admin_authenticated", False)
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
    """モニタリング報告書 AIで生成（カテゴリ別 or まとめて1本）"""
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()

        u_name = data.get("user_name", "").strip()
        month_val = data.get("month", "")       # "2026-04"
        mode = data.get("mode", "category")      # "category" or "full"
        char_limit = int(data.get("char_limit", 200))
        selected_cats = data.get("categories", [])  # カテゴリ別モード時の選択リスト

        if not u_name or not month_val:
            return jsonify({"error": "利用者と対象月を指定してください"}), 400

        CATEGORIES = ["心身状況", "食事", "入浴", "排泄", "コミュニケーション", "訓練状況", "ヒヤリハット", "その他"]
        target_cats = selected_cats if selected_cats else CATEGORIES

        y, m = map(int, month_val.split("-"))
        s_date = tokyo_tz.localize(datetime(y, m, 1))
        e_date = (s_date + timedelta(days=32)).replace(day=1)

        # 記録を取得（AI統合記録・休み連絡を除外）
        res = supabase.table("records").select(
            "content, category, staff_name, created_at"
        ).eq("facility_code", f_code).eq("user_name", u_name).gte(
            "created_at", s_date.isoformat()
        ).lt("created_at", e_date.isoformat()).execute()

        records = [r for r in (res.data or [])
                   if r.get("staff_name") not in ("AI統合記録",)
                   and r.get("category") != "休み連絡"]
        def _replace_kyouha(record):
            content_text = record.get("content") or ""
            created_at = record.get("created_at") or ""
            if not created_at or "今日" not in content_text:
                return record
            try:
                from datetime import datetime as _dt3
                import pytz as _pytz
                _tz = _pytz.timezone("Asia/Tokyo")
                _dt = _dt3.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(_tz)
                _date_str = f"{_dt.month}月{_dt.day}日"
                for _old, _new in [
                    ("今日は", f"{_date_str}は"),
                    ("今日も", f"{_date_str}も"),
                    ("今日、", f"{_date_str}、"),
                    ("今日。", f"{_date_str}。"),
                    ("今日（", f"{_date_str}（"),
                    ("今日の", f"{_date_str}の"),
                    ("今日で", f"{_date_str}で"),
                    ("今日から", f"{_date_str}から"),
                    ("今日まで", f"{_date_str}まで"),
                ]:
                    content_text = content_text.replace(_old, _new)
                return {**record, "content": content_text}
            except Exception:
                return record
        records = [_replace_kyouha(r) for r in records]

        # 休み連絡レコードから実際の休日情報を取得
        leave_res = supabase.table("records").select(
            "leave_date_start, leave_date_end, leave_reporter_type, leave_reason"
        ).eq("facility_code", f_code).eq("user_name", u_name).eq(
            "category", "休み連絡"
        ).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).execute()
        leave_records = leave_res.data or []

        # 実際の休日情報をテキストに変換
        leave_notes = []
        for lr in leave_records:
            _ls = lr.get("leave_date_start")
            _le = lr.get("leave_date_end")
            if not _ls:
                continue
            try:
                from datetime import datetime as _dt2
                _ls_d = _dt2.strptime(_ls[:10], "%Y-%m-%d")
                _ls_str = f"{_ls_d.month}月{_ls_d.day}日"
                _lr_reason = (lr.get("leave_reason") or "").strip()
                _lr_type = lr.get("leave_reporter_type") or ""
                _reporter_map_n = {"self": "本人", "family": "家族", "caremanager": "ケアマネ", "other": "その他"}
                _reporter_n = _reporter_map_n.get(_lr_type, "")
                if _le and _le[:10] != _ls[:10]:
                    _le_d = _dt2.strptime(_le[:10], "%Y-%m-%d")
                    _period_n = f"{_ls_str}〜{_le_d.month}月{_le_d.day}日"
                else:
                    _period_n = _ls_str
                _note_text = _build_leave_content(_period_n, _lr_type, "", _lr_reason)
                leave_notes.append(_note_text)
            except Exception:
                pass

        if not records and not leave_notes:
            return jsonify({"error": f"{u_name}様の{y}年{m}月の記録が見つかりません"}), 404

        from utils import get_generative_model
        model = get_generative_model()

        BASE_PROMPT = (
            "あなたは介護施設のベテランケアマネジャーの補佐をしています。"
            "以下の介護記録を読み、ケアマネジャーへのモニタリング報告書として使える文章を生成してください。\n"
            "【ルール】\n"
            "・事実として記録されていること以外は絶対に書かない（ハルシネーション厳禁）\n"
            "・記録がない場合は文章を作らず「今月このカテゴリの報告はありませんでした」とだけ返す\n"
            "・職員名・利用者名・主語は不要\n"
            "・箇条書きは使わず、ひとつながりの文章で書く\n"
            "・口調はケアマネへの報告文書として適切な丁寧語（硬すぎず砕けすぎない）\n"
        )

        if mode == "full":
            # まとめて1本モード
            all_recs = "\n".join(r["content"] for r in records)
            leave_text = ("\n".join(leave_notes) + "\n") if leave_notes else ""
            leave_section = f"『休日情報』\n{leave_text}\n" if leave_text else ""
            prompt = (
                BASE_PROMPT +
                f"・全体をひとまとめにして{char_limit}文字程度で生成\n"
                + (f"・休日情報は必ず文中に含めること\n\n" if leave_text else "\n")
                + leave_section
                + f"『記録』\n{all_recs}"
            )
            result_text = model.generate_content([prompt]).text.strip()
            return jsonify({
                "mode": "full",
                "full_text": result_text,
                "record_count": len(records)
            })

        else:
            # カテゴリ別モード
            cat_records = {}
            for r in records:
                cat = r.get("category") or "その他"
                cat_records.setdefault(cat, []).append(r["content"])

            results = {}
            counts = {}
            NO_RECORD_MSG = "今月このカテゴリの報告はありませんでした"

            for cat in CATEGORIES:
                if cat not in target_cats:
                    continue
                recs_in_cat = cat_records.get(cat, [])
                counts[cat] = len(recs_in_cat)
                if not recs_in_cat:
                    results[cat] = NO_RECORD_MSG
                    continue
                cat_text = "\n".join(recs_in_cat)
                prompt = (
                    BASE_PROMPT +
                    f"・カテゴリ「{cat}」に関する記録だけをまとめて{char_limit}文字程度で生成\n\n"
                    f"【{cat}の記録】\n{cat_text}"
                )
                try:
                    results[cat] = model.generate_content([prompt]).text.strip()
                except Exception as e:
                    results[cat] = f"（生成エラー: {str(e)[:50]}）"
# 評価データ取得
            eval_res = supabase.table("patient_evaluations").select(
                "changes_by_training,issues_and_causes,special_notes,satisfaction,service_appropriateness,new_requests_exist,new_requests_detail"
            ).eq("facility_code", f_code).eq("user_name", u_name).eq("year_month", month_val).execute()
            eval_data = eval_res.data[0] if eval_res.data else {}
            NO_EVAL_MSG = "評価ページにて評価を済ませてください"
            # 訓練による変化
            changes = eval_data.get("changes_by_training") or ""
            if not changes: changes = NO_EVAL_MSG
            # 課題とその要因
            issues = eval_data.get("issues_and_causes") or ""
            if not issues: issues = NO_EVAL_MSG
            eval_extra = {
                "changes_by_training": changes,
                "issues_and_causes": issues,
                "special_notes": eval_data.get("special_notes") or "",
                "satisfaction": eval_data.get("satisfaction") or "",
                "service_appropriateness": eval_data.get("service_appropriateness") or "",
                "new_requests_exist": eval_data.get("new_requests_exist"),
                "new_requests_detail": eval_data.get("new_requests_detail") or "",
            }
            return jsonify({
                "mode": "category",
                "categories": results,
                "record_counts": counts,
                "total_records": len(records),
                "eval_extra": eval_extra
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/save_monitoring', methods=['POST'])
@login_required
def api_save_monitoring():
    """モニタリング報告書を下書き保存 or 確定保存"""
    try:
        data = request.json
        f_code = session["f_code"]
        u_name = session.get("u_name", "")
        supabase = get_supabase()

        user_name = data.get("user_name", "").strip()
        month_val = data.get("month", "")
        mode = data.get("mode", "category")
        char_limit = int(data.get("char_limit", 200))
        categories = data.get("categories", {})
        full_text = data.get("full_text", "")
        record_counts = data.get("record_counts", {})
        confirm = data.get("confirm", False)

        if not user_name or not month_val:
            return jsonify({"error": "必須項目が不足しています"}), 400

        # 既存レコードを確認（同月・同利用者）
        existing = supabase.table("monitoring_reports").select("id, confirmed_at").eq(
            "facility_code", f_code
        ).eq("user_name", user_name).eq("target_month", month_val).execute()

        payload = {
            "facility_code": f_code,
            "user_name": user_name,
            "target_month": month_val,
            "mode": mode,
            "char_limit": char_limit,
            "categories": categories,
            "full_text": full_text,
            "record_counts": record_counts,
            "updated_at": "now()",
        }
        if confirm:
            payload["confirmed_at"] = "now()"
            payload["confirmed_by"] = u_name

        if existing.data:
            rec = existing.data[0]
            if rec.get("confirmed_at") and not confirm:
                # 確定済みは上書き不可（再確定のみ）
                return jsonify({"error": "確定済みの報告書は上書きできません"}), 409
            supabase.table("monitoring_reports").update(payload).eq("id", rec["id"]).execute()
            return jsonify({"saved": True, "id": rec["id"], "confirmed": confirm})
        else:
            result = supabase.table("monitoring_reports").insert(payload).execute()
            new_id = result.data[0]["id"] if result.data else None
            return jsonify({"saved": True, "id": new_id, "confirmed": confirm})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/monitoring_history', methods=['GET'])
@login_required
def api_monitoring_history():
    """モニタリング報告書の履歴一覧を返す"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        user_name = request.args.get("user_name", "")

        q = supabase.table("monitoring_reports").select(
            "id, user_name, target_month, mode, char_limit, confirmed_at, confirmed_by, updated_at"
        ).eq("facility_code", f_code).order("target_month", desc=True)

        if user_name:
            q = q.eq("user_name", user_name)

        res = q.execute()
        return jsonify({"history": res.data or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/monitoring_detail', methods=['GET'])
@login_required
def api_monitoring_detail():
    """特定のモニタリング報告書の全文を返す"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        report_id = request.args.get("id", "")
        if not report_id:
            return jsonify({"error": "IDが必要です"}), 400

        res = supabase.table("monitoring_reports").select("*").eq(
            "facility_code", f_code
        ).eq("id", report_id).execute()

        if not res.data:
            return jsonify({"error": "見つかりません"}), 404
        return jsonify(res.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/history')
def history_redirect():
    return redirect(url_for('case_records'))

@app.route('/api/daily_records')
@login_required
def api_daily_records():
    """指定日の全利用者ケース記録を返す（ケース記録一覧画面用）"""
    f_code = session['f_code']
    supabase = get_supabase()
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.now(tokyo_tz).strftime('%Y-%m-%d')
    try:
        day_start = tokyo_tz.localize(datetime.strptime(date_str, '%Y-%m-%d'))
        day_end   = day_start + timedelta(days=1)
        res = supabase.table('records').select(
            'id, user_name, staff_name, content, category, created_at'
        ).eq('facility_code', f_code).gte(
            'created_at', day_start.isoformat()
        ).lt(
            'created_at', day_end.isoformat()
        ).neq('staff_name', 'AI統合記録').order('created_at').execute()
        records = res.data or []

        from collections import OrderedDict
        grouped = OrderedDict()
        for r in records:
            uname = r['user_name']
            if uname not in grouped:
                grouped[uname] = []
            grouped[uname].append(r)

        summaries = {}
        if grouped:
            try:
                s_res = supabase.table('daily_summaries').select(
                    'user_name, summary, last_record_at'
                ).eq('facility_code', f_code).eq(
                    'summary_date', date_str
                ).in_('user_name', list(grouped.keys())).execute()
                for s in (s_res.data or []):
                    summaries[s['user_name']] = s
            except:
                pass

        result = []
        for uname, recs in grouped.items():
            latest_record_at = recs[-1]['created_at']
            cached = summaries.get(uname)
            summary_text = None
            summary_stale = True
            if cached:
                if cached['last_record_at'] >= latest_record_at:
                    summary_text = cached['summary']
                    summary_stale = False
            result.append({
                'user_name': uname,
                'record_count': len(recs),
                'latest_record_at': latest_record_at,
                'summary': summary_text,
                'summary_stale': summary_stale,
                'records': recs
            })

        return jsonify({'date': date_str, 'patients': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/api/tts_speak', methods=['POST'])
@login_required
def api_tts_speak():
    """Google WaveNet TTSで音声合成して返す"""
    f_code = session['f_code']
    supabase = get_supabase()
    # TTS有効チェック
    try:
        res = supabase.table('admin_settings').select('value').eq(
            'facility_code', f_code).eq('key', 'tts_enabled').execute()
        enabled = res.data[0]['value'] == 'true' if res.data else False
    except:
        enabled = False
    if not enabled:
        return jsonify({'error': 'TTSはこの施設では有効ではありません'}), 403

    try:
        import requests as req_lib
        data = request.json
        text = data.get('text', '')
        if not text:
            return jsonify({'error': 'テキストがありません'}), 400

        api_key = os.environ.get('GOOGLE_TTS_API_KEY', '')
        if not api_key:
            return jsonify({'error': 'TTS APIキーが設定されていません'}), 500

        url = f'https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}'
        # DB設定を取得
        try:
            s_res = supabase.table('admin_settings').select('key, value').eq(
                'facility_code', f_code).in_('key', ['tts_voice', 'tts_speed', 'tts_pitch']).execute()
            s = {r['key']: r['value'] for r in (s_res.data or [])}
        except:
            s = {}
        voice_name = s.get('tts_voice', 'ja-JP-Wavenet-B')
        speed = float(s.get('tts_speed', '1.0'))
        pitch = float(s.get('tts_pitch', '0.0'))
        gender = 'FEMALE' if voice_name in ['ja-JP-Wavenet-A', 'ja-JP-Wavenet-B', 'ja-JP-Neural2-B', 'ja-JP-Neural2-A'] else 'MALE'

        payload = {
            'input': {'text': text},
            'voice': {
                'languageCode': 'ja-JP',
                'name': voice_name,
                'ssmlGender': gender
            },
            'audioConfig': {
                'audioEncoding': 'MP3',
                'speakingRate': speed,
                'pitch': pitch
            }
        }
        r = req_lib.post(url, json=payload, timeout=10)
        r.raise_for_status()
        audio_content = r.json().get('audioContent', '')
        return jsonify({'audioContent': audio_content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tts_settings')
@login_required
def api_tts_settings():
    """施設のTTS設定を返す"""
    f_code = session['f_code']
    supabase = get_supabase()
    try:
        res = supabase.table('admin_settings').select('key, value').eq(
            'facility_code', f_code).in_('key', ['tts_enabled', 'tts_voice', 'tts_speed', 'tts_pitch']).execute()
        settings = {r['key']: r['value'] for r in (res.data or [])}
    except:
        settings = {}
    return jsonify({
        'enabled': settings.get('tts_enabled', 'false') == 'true',
        'voice':   settings.get('tts_voice', 'ja-JP-Wavenet-B'),
        'speed':   float(settings.get('tts_speed', '1.0')),
        'pitch':   float(settings.get('tts_pitch', '0.0'))
    })


@app.route('/api/tts_settings', methods=['POST'])
@login_required
def api_tts_settings_update():
    """開発者がTTS設定を更新する"""
    if not session.get('dev_authenticated'):
        return jsonify({'error': '開発者権限が必要です'}), 403
    f_code = session['f_code']
    supabase = get_supabase()
    try:
        data = request.json
        updates = {}
        if 'enabled' in data:
            updates['tts_enabled'] = 'true' if data['enabled'] else 'false'
        if 'voice' in data:
            updates['tts_voice'] = data['voice']
        if 'speed' in data:
            updates['tts_speed'] = str(data['speed'])
        if 'pitch' in data:
            updates['tts_pitch'] = str(data['pitch'])

        for key, value in updates.items():
            res = supabase.table('admin_settings').select('id').eq(
                'facility_code', f_code).eq('key', key).execute()
            if res.data:
                supabase.table('admin_settings').update({'value': value}).eq(
                    'facility_code', f_code).eq('key', key).execute()
            else:
                supabase.table('admin_settings').insert({
                    'facility_code': f_code, 'key': key, 'value': value
                }).execute()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tts_enabled')
@login_required
def api_tts_enabled():
    """施設のTTS有効フラグを返す"""
    f_code = session['f_code']
    supabase = get_supabase()
    try:
        res = supabase.table('admin_settings').select('value').eq(
            'facility_code', f_code).eq('key', 'tts_enabled').execute()
        enabled = res.data[0]['value'] == 'true' if res.data else False
    except:
        enabled = False
    return jsonify({'enabled': enabled})


@app.route('/api/tts_toggle', methods=['POST'])
@login_required
def api_tts_toggle():
    """管理者がTTSのON/OFFを切り替える"""
    if not session.get('dev_authenticated'):
        return jsonify({'error': '開発者権限が必要です'}), 403
    f_code = session['f_code']
    supabase = get_supabase()
    try:
        data = request.json
        enabled = 'true' if data.get('enabled') else 'false'
        # 既存レコードを確認
        res = supabase.table('admin_settings').select('id').eq(
            'facility_code', f_code).eq('key', 'tts_enabled').execute()
        if res.data:
            supabase.table('admin_settings').update({'value': enabled}).eq(
                'facility_code', f_code).eq('key', 'tts_enabled').execute()
        else:
            supabase.table('admin_settings').insert({
                'facility_code': f_code, 'key': 'tts_e******', 'value': enabled
            }).execute()
        return jsonify({'enabled': enabled == 'true'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate_daily_summary', methods=['POST'])
@login_required
def api_generate_daily_summary():
    """利用者×日付のAI要約を生成してキャッシュ保存"""
    f_code = session['f_code']
    supabase = get_supabase()
    try:
        data = request.json
        user_name = data['user_name']
        date_str  = data['date']

        day_start = tokyo_tz.localize(datetime.strptime(date_str, '%Y-%m-%d'))
        day_end   = day_start + timedelta(days=1)

        res = supabase.table('records').select(
            'content, staff_name, created_at, image_urls'
        ).eq('facility_code', f_code).eq(
            'user_name', user_name
        ).gte('created_at', day_start.isoformat()).lt(
            'created_at', day_end.isoformat()
        ).neq('staff_name', 'AI統合記録').order('created_at').execute()

        records = res.data or []
        if not records:
            return jsonify({'error': '記録がありません'}), 404

        latest_record_at = records[-1]['created_at']
        force = data.get('force', False)
        try:
            cached = supabase.table('daily_summaries').select(
                'summary, last_record_at'
            ).eq('facility_code', f_code).eq(
                'user_name', user_name
            ).eq('summary_date', date_str).execute()
            if not force and cached.data and cached.data[0]['last_record_at'] >= latest_record_at:
                c_res = supabase.table('records').select('image_urls').eq('facility_code', f_code).eq('user_name', user_name).gte('created_at', day_start.isoformat()).lt('created_at', day_end.isoformat()).execute()
                c_urls = [u for r in (c_res.data or []) for u in (r.get('image_urls') or [])]
                return jsonify({'summary': cached.data[0]['summary'], 'cached': True, 'image_urls': c_urls})
        except:
            pass

        contents = [r['content'] for r in records]
        recs_text = '\n'.join(contents)
        from utils import get_generative_model
        model = get_generative_model()
        prompt = (
            f"以下は{date_str}の{user_name}さんに関する介護記録です。"
            "職員が記入した記録を、要点を押さえて簡潔に要約してください。"
            "箇条書きは使わず自然な文章で、200文字程度でまとめてください。"
            "職員名や主語は不要です。\n\n" + recs_text
        )
        summary = model.generate_content([prompt]).text.strip()

        try:
            supabase.table('daily_summaries').upsert({
                'facility_code':  f_code,
                'user_name':      user_name,
                'summary_date':   date_str,
                'summary':        summary,
                'last_record_at': latest_record_at,
                'updated_at':     datetime.now(tokyo_tz).isoformat()
            }, on_conflict='facility_code,user_name,summary_date').execute()
        except:
            pass

        all_image_urls = []
        for r in records:
            urls = r.get('image_urls') or []
            all_image_urls.extend(urls)
        return jsonify({'summary': summary, 'cached': False, 'image_urls': all_image_urls})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/dev_login', methods=['GET', 'POST'])
@login_required
def dev_login():
    error = None
    if request.method == 'POST':
        pw = request.form.get('dev_pw', '')
        dev_pw = get_secret('DEV_PASSWORD') or 'tasukaru-dev-2024'
        if pw == dev_pw:
            session['dev_authenticated'] = True
            return redirect(url_for('dev_menu'))
        else:
            error = '開発者パスワードが違います。'
    return render_template('dev_login.html', error=error)

@app.route('/dev/manual')
@login_required
def dev_manual():
    if not session.get("dev_authenticated"):
        return redirect(url_for("dev_login"))
    return render_template('dev_manual.html')
@app.route('/dev')
@login_required
def dev_menu():
    if not session.get("dev_authenticated"):
        return redirect(url_for("dev_login"))
    supabase = get_supabase()
    f_code = session["f_code"]

    # 全施設一覧
    facilities = []
    try:
        res = supabase.table("facilities").select("facility_code,facility_name,is_active,expires_at,plan,is_monitor,contract_term,trial_ends_at,discount_rate,discount_until,sekkotsu_mode_allowed").execute()  # dev-sekkotsu-allow-v1
        facilities = res.data or []
    except: pass

    # 各施設のレコード数・スタッフ数
    def _check_ledger_enabled(sb, facility_code):
        try:
            r = sb.table('admin_settings').select('value').eq('facility_code', facility_code).eq('key', 'ledger_enabled').execute()
            return bool(r.data and r.data[0].get('value') == 'true')
        except:
            return False
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
                "expires_at": fac.get("expires_at", "")[:10] if fac.get("expires_at") else "",
                "records": rec_count,
                "staffs": staff_count,
                "patients": patient_count,
                "ledger_enabled": fc == LEDGER_ALLOWED_FACILITY or _check_ledger_enabled(supabase, fc),
                "plan": fac.get("plan", "free"),
                "is_monitor": fac.get("is_monitor", False),
                "contract_term": fac.get("contract_term", 0),
                "trial_ends_at": fac.get("trial_ends_at", "")[:10] if fac.get("trial_ends_at") else "",
                "discount_rate": fac.get("discount_rate", 0) or 0,
                "discount_until": fac.get("discount_until", "")[:10] if fac.get("discount_until") else "",
                "sekkotsu_mode_allowed": fac.get("sekkotsu_mode_allowed", False),  # dev-sekkotsu-allow-v1
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
@app.route('/api/dev/update_facility_expiry', methods=['POST'])
def api_dev_update_facility_expiry():
    if not session.get('dev_authenticated'):
        return jsonify({'success': False, 'message': 'unauthorized'}), 403
    data = request.json
    fc = data.get('facility_code', '').strip()
    expires_at = data.get('expires_at', '').strip()
    if not fc or not expires_at:
        return jsonify({'success': False, 'message': 'facility_code and expires_at required'}), 400
    try:
        supabase = get_supabase()
        supabase.table('facilities').update({'expires_at': expires_at}).eq('facility_code', fc).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/api/dev/update_facility_plan', methods=['POST'])
@login_required
def api_dev_update_facility_plan():
    if not session.get("dev_authenticated"):
        return jsonify({"status": "error", "message": "unauthorized"}), 403
    try:
        data = request.json
        facility_code = data.get("facility_code")
        plan = data.get("plan", "free")
        supabase = get_supabase()
        supabase.table("facilities").update({"plan": plan}).eq("facility_code", facility_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/dev/toggle_monitor', methods=['POST'])
@login_required
def api_dev_toggle_monitor():
    if not session.get("dev_authenticated"):
        return jsonify({"status": "error", "message": "unauthorized"}), 403
    try:
        data = request.json
        facility_code = data.get("facility_code")
        is_monitor = data.get("is_monitor", False)
        supabase = get_supabase()
        supabase.table("facilities").update({"is_monitor": is_monitor}).eq("facility_code", facility_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/dev/update_discount', methods=['POST'])
@login_required
def api_dev_update_discount():
    if not session.get("dev_authenticated"):
        return jsonify({"status": "error", "message": "unauthorized"}), 403
    try:
        data = request.json
        facility_code = data.get("facility_code")
        if not facility_code:
            return jsonify({"status": "error", "message": "facility_code required"}), 400
        # discount_rate は 0 / 0.2 / 0.3 / 0.5 のみ許可（誤割引防止）
        try:
            rate = round(float(data.get("discount_rate", 0) or 0), 2)
        except (ValueError, TypeError):
            rate = 0
        if rate not in (0, 0.2, 0.3, 0.5):
            return jsonify({"status": "error", "message": "discount_rate must be 0/0.2/0.3/0.5"}), 400
        # discount_until は空なら無期限(None)、あれば日付文字列
        until = (data.get("discount_until") or "").strip()
        update_data = {"discount_rate": rate, "discount_until": until if until else None}
        supabase = get_supabase()
        supabase.table("facilities").update(update_data).eq("facility_code", facility_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/dev/toggle_sekkotsu_allowed', methods=['POST'])  # dev-sekkotsu-allow-v1
def api_dev_toggle_sekkotsu_allowed():
    if not session.get('dev_authenticated'):
        return jsonify({'success': False, 'message': 'unauthorized'}), 403
    data = request.json or {}
    fc = (data.get('facility_code') or '').strip()
    allowed = bool(data.get('allowed', False))
    if not fc:
        return jsonify({'success': False, 'message': 'facility_code required'}), 400
    try:
        supabase = get_supabase()
        supabase.table('facilities').update({'sekkotsu_mode_allowed': allowed}).eq('facility_code', fc).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/dev/toggle_facility_ledger', methods=['POST'])
def api_dev_toggle_facility_ledger():
    if not session.get('dev_authenticated'):
        return jsonify({'success': False, 'message': 'unauthorized'}), 403
    data = request.json
    fc = data.get('facility_code', '').strip()
    enabled = data.get('enabled', False)
    if not fc:
        return jsonify({'success': False, 'message': 'facility_code required'}), 400
    try:
        supabase = get_supabase()
        res = supabase.table('admin_settings').select('id').eq('facility_code', fc).eq('key', 'ledger_enabled').execute()
        if res.data:
            supabase.table('admin_settings').update({'value': 'true' if enabled else 'false'}).eq('id', res.data[0]['id']).execute()
        else:
            supabase.table('admin_settings').insert({'facility_code': fc, 'key': 'ledger_enabled', 'value': 'true' if enabled else 'false'}).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
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
@app.route('/api/update_patient_birth', methods=['POST'])
@login_required
def api_update_patient_birth():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        user_name = data.get("user_name", "").strip()
        birth_date = data.get("birth_date", "").strip()
        user_kana = data.get("user_name_kana", "").strip()
        if not user_name:
            return jsonify({"status": "error", "message": "user_name required"}), 400
        update_data = {}
        if birth_date:
            update_data["birth_date"] = birth_date
        if user_kana:
            update_data["user_kana"] = user_kana
        if update_data:
            supabase.table("patients").update(update_data).eq("facility_code", f_code).eq("user_name", user_name).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/api/goal_check')
@login_required
def api_goal_check():
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        from datetime import date, timedelta
        today = date.today()
        warning_days = 30
        res = supabase.table("patient_profiles").select(
            "id, user_name, care_level, short_goal_period_to, long_goal_period_to"
        ).eq("facility_code", f_code).execute()
        patients = []
        for p in (res.data or []):
            short_to = p.get("short_goal_period_to")
            long_to = p.get("long_goal_period_to")
            short_status = None
            long_status = None
            if short_to:
                d = date.fromisoformat(short_to)
                if d < today:
                    short_status = "期限切れ"
                elif d <= today + timedelta(days=warning_days):
                    short_status = "期限間近"
            if long_to:
                d = date.fromisoformat(long_to)
                if d < today:
                    long_status = "期限切れ"
                elif d <= today + timedelta(days=warning_days):
                    long_status = "期限間近"
            # 全体のステータス（期限切れ優先）
            if short_status == "期限切れ" or long_status == "期限切れ":
                overall_status = "期限切れ"
            elif short_status == "期限間近" or long_status == "期限間近":
                overall_status = "期限間近"
            else:
                overall_status = None
            if overall_status:
                patients.append({
                    "id": str(p["id"]),
                    "user_name": p["user_name"],
                    "care_level": p.get("care_level") or "",
                    "short_goal_to": short_to,
                    "short_status": short_status,
                    "long_goal_to": long_to,
                    "long_status": long_status,
                    "status": overall_status,
                })
        patients.sort(key=lambda x: (x["status"] != "期限切れ", x["user_name"]))

        # 目標変更: 当月または前月の評価で新目標が入力されている人（翌月10日まで表示）
        goal_changes = []
        try:
            # 表示対象月を決定（今月10日以前なら前月も対象）
            if today.day <= 10:
                target_months = [
                    today.strftime('%Y-%m'),
                    (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
                ]
            else:
                target_months = [today.strftime('%Y-%m')]

            for ym in target_months:
                ev_res = supabase.table("patient_evaluations").select(
                    "user_name, year_month, training_goal, short_goal_new, long_goal_new"
                ).eq("facility_code", f_code).eq("year_month", ym).execute()
                for ev in (ev_res.data or []):
                    # goal-minlen-fix: 前後空白を除いて評価。1文字や空白のみのゴミ入力は除外
                    tg = (ev.get("training_goal") or "").strip()
                    sg = (ev.get("short_goal_new") or "").strip()
                    lg = (ev.get("long_goal_new") or "").strip()
                    new_goal = tg or sg or lg
                    if new_goal and len(new_goal) >= 2:
                        # 重複チェック
                        if not any(g["user_name"] == ev["user_name"] for g in goal_changes):
                            goal_changes.append({
                                "user_name": ev["user_name"],
                                "year_month": ym,
                                "new_goal": new_goal,
                            })
            goal_changes.sort(key=lambda x: x["user_name"])
        except Exception:
            pass

        return jsonify({"status": "success", "patients": patients, "goal_changes": goal_changes})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/api/update_patient_care_level', methods=['POST'])
@login_required
def api_update_patient_care_level():
    try:
        data = request.json
        f_code = session["f_code"]
        supabase = get_supabase()
        user_name = data.get("user_name")
        care_classification = data.get("care_classification")
        if not user_name or not care_classification:
            return jsonify({"status": "error", "message": "パラメータ不足"}), 400
        # care_classificationからcare_levelへのマッピング
        care_map = {
            "要介護": "要介護1",
            "要支援": "要支援1",
            "事業対象者": "事業対象者"
        }
        # patient_profilesのcare_levelを更新
        supabase.table("patient_profiles").update({
            "care_level": care_map.get(care_classification, care_classification)
        }).eq("facility_code", f_code).eq("user_name", user_name).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
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
            supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin*********", "value": data["password"]}).execute()
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
        # admin_settings に (facility_code, key) のユニーク制約が無いため existing 分岐
        existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "history_limit").execute()
        if existing.data:
            supabase.table("admin_settings").update({"value": str(data["limit"])}).eq("facility_code", f_code).eq("key", "history_limit").execute()
        else:
            supabase.table("admin_settings").insert({
                "facility_code": f_code, "key": "histo********", "value": str(data["limit"])
            }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500

@app.route('/api/board/set_editors', methods=['POST'])
@login_required
def api_board_set_editors():
    """掲示板の編集削除許可リストを保存(管理者専用)"""
    try:
        # 管理者でない場合は拒否
        my_name = session.get("my_name", "")
        is_admin = session.get("admin_authenticated", False)
        if not is_admin:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        data = request.json or {}
        editors = data.get("editors", [])
        if not isinstance(editors, list):
            return jsonify({"status": "error", "message": "形式が不正です"}), 400
        f_code = session["f_code"]
        supabase = get_supabase()
        import json as _json
        value_json = _json.dumps(editors, ensure_ascii=False)
        # admin_settings に (facility_code, key) のユニーク制約が無いため
        # upsert ではなく existing確認 → update or insert で対応
        existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "board_editors").execute()
        if existing.data:
            supabase.table("admin_settings").update({"value": value_json}).eq("facility_code", f_code).eq("key", "board_editors").execute()
        else:
            supabase.table("admin_settings").insert({
                "facility_code": f_code,
                "key": "board********",
                "value": value_json
            }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/managers_info')
@login_required
def api_admin_managers_info():
    """現在の管理者リストとセーフティ情報を返す。GUI が状態表示と確認ダイアログ判定に使う。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        managers = get_admin_managers(supabase, f_code)
        # 超管理者(admin_email スタッフ)
        super_admins = []
        try:
            fac_res = supabase.table("facilities").select("admin_email").eq("facility_code", f_code).execute()
            admin_email = fac_res.data[0].get("admin_email") if fac_res.data else None
            if admin_email:
                st = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("email", admin_email).eq("is_active", True).execute()
                super_admins = [s.get("staff_name") for s in (st.data or []) if s.get("staff_name")]
        except: pass
        return jsonify({
            "managers": managers,
            "super_admins": super_admins,
            "my_name": my_name,
            "is_my_super": my_name in super_admins,
            "count": len(set(managers) | set(super_admins)),
        })
    except Exception as e:
        return jsonify({"managers": [], "super_admins": [], "count": 0, "error": str(e)})

@app.route('/api/admin/set_managers', methods=['POST'])
@login_required
def api_admin_set_managers():
    """管理者MENUに入れる人(admin_managers)の保存。管理者専用。
    セーフティ:
      - 配列が空(0人)は禁止
      - facilities.admin_email に紐づくスタッフ(超管理者)は強制的にリストに含める"""
    try:
        my_name = session.get("my_name", "")
        is_admin = session.get("admin_authenticated", False)
        if not is_admin:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        data = request.json or {}
        managers = data.get("managers", [])
        if not isinstance(managers, list):
            return jsonify({"status": "error", "message": "形式が不正です"}), 400
        f_code = session["f_code"]
        supabase = get_supabase()
        # 超管理者(admin_email スタッフ)は強制的に常に含める
        try:
            fac_res = supabase.table("facilities").select("admin_email").eq("facility_code", f_code).execute()
            admin_email = fac_res.data[0].get("admin_email") if fac_res.data else None
            if admin_email:
                st = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("email", admin_email).eq("is_active", True).execute()
                for s in (st.data or []):
                    nm = s.get("staff_name")
                    if nm and nm not in managers:
                        managers.append(nm)
        except: pass
        # 管理者ゼロは禁止(超管理者がいない場合の最終保護)
        if len(managers) == 0:
            return jsonify({"status": "error", "message": "管理者は最低1人必要です"}), 400
        import json as _json
        value_json = _json.dumps(managers, ensure_ascii=False)
        existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "admin_managers").execute()
        if existing.data:
            supabase.table("admin_settings").update({"value": value_json}).eq("facility_code", f_code).eq("key", "admin_managers").execute()
        else:
            supabase.table("admin_settings").insert({
                "facility_code": f_code,
                "key": "admin*********",
                "value": value_json
            }).execute()
        return jsonify({"status": "success", "managers": managers})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/block_staff', methods=['POST'])
@login_required
def api_block_staff():
    try:
        data = request.json
        f_code = session["f_code"]
        target_name = data.get("name", "")
        supabase = get_supabase()
        # 管理者だった場合の保護
        try:
            managers = get_admin_managers(supabase, f_code)
            if target_name in managers:
                # 他に管理者がいなければブロック拒否(超管理者も考慮)
                remaining = [m for m in managers if m != target_name]
                # 超管理者(admin_email スタッフ)が他にいれば 0 人扱いではない
                has_super = False
                try:
                    fac_res = supabase.table("facilities").select("admin_email").eq("facility_code", f_code).execute()
                    admin_email = fac_res.data[0].get("admin_email") if fac_res.data else None
                    if admin_email:
                        st = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("email", admin_email).eq("is_active", True).execute()
                        for s in (st.data or []):
                            if s.get("staff_name") and s["staff_name"] != target_name:
                                has_super = True
                                break
                except: pass
                if len(remaining) == 0 and not has_super:
                    return jsonify({
                        "status": "error",
                        "message": "このスタッフは唯一の管理者のためブロックできません。先に他のスタッフを管理者に指定してください。"
                    }), 400
                # admin_managers から自動除外
                try:
                    import json as _json
                    value_json = _json.dumps(remaining, ensure_ascii=False)
                    existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "admin_managers").execute()
                    if existing.data:
                        supabase.table("admin_settings").update({"value": value_json}).eq("facility_code", f_code).eq("key", "admin_managers").execute()
                    else:
                        supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin*********", "value": value_json}).execute()
                except: pass
        except: pass
        supabase.table("blocked_devices").insert({
            "staff_name": target_name, "facility_code": f_code,
            "is_active": True, "device_id": "NAME_LOCK"
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
        return redirect(url_for("dev_login"))

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
        res = supabase.table("board_posts").select("*").eq("facility_code", f_code).order("is_pinned", desc=True).order("created_at", desc=True).limit(5000).execute()
        all_posts = res.data or []
        # is_private=Trueの投稿は自分がmention_namesに含まれるか投稿者のみ表示
        posts = []
        for p in all_posts:
            if p.get("is_private"):
                mentions_list = p.get("mention_names") or []
                if my_name in mentions_list or p.get("staff_name") == my_name:
                    posts.append(p)
            else:
                posts.append(p)
    except Exception as e:
        print(f"board error: {e}")
    icons = get_staff_icons(supabase, f_code)
    post_ids = [p["id"] for p in posts]
    comments_count = {}
    reactions_data = {}
    read_data = {}
    checks_data = {}  # Session 32: 確認済み状態(board_checks テーブル)
    # === カテゴリー機能 ===
    board_categories = []
    post_categories = {}
    is_admin_flag = False
    try:
        is_admin_flag = is_admin_user(supabase, f_code, my_name)
    except Exception:
        is_admin_flag = False
    try:
        cat_res = supabase.table("board_categories").select("*").eq("facility_code", f_code).order("sort_order").order("id").execute()
        board_categories = cat_res.data or []
    except Exception as e:
        print(f"board_categories error: {e}")
        board_categories = []
    try:
        if post_ids:
            # 自分以外が書いた全コメントを取得(未読対象)
            ccs = supabase.table("board_comments").select("id,post_id,staff_name").in_("post_id", post_ids).eq("facility_code", f_code).execute()
            unread_comment_ids_by_post = {}
            all_other_comment_ids = []
            for c in (ccs.data or []):
                if c["staff_name"] == my_name:
                    continue
                all_other_comment_ids.append(c["id"])
                unread_comment_ids_by_post.setdefault(c["post_id"], set()).add(c["id"])
            # 自分が既読化したコメントID
            read_comment_ids = set()
            if all_other_comment_ids:
                try:
                    crres = supabase.table("board_comment_reads").select("comment_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("comment_id", all_other_comment_ids).execute()
                    read_comment_ids = set(r["comment_id"] for r in (crres.data or []))
                except: pass
            # 未読数 = 自分以外作 - 自分既読
            for pid in post_ids:
                ids = unread_comment_ids_by_post.get(pid, set())
                comments_count[pid] = len(ids - read_comment_ids)
            rres = supabase.table("board_reactions").select("*").in_("post_id", post_ids).execute()
            for r in (rres.data or []):
                pid = r["post_id"]
                em = r["reaction"]
                # Session 32 Phase 3c: ✅ は board_checks に移行済みなのでスキップ
                if em == '✅':
                    continue
                if pid not in reactions_data: reactions_data[pid] = {}
                if em not in reactions_data[pid]: reactions_data[pid][em] = []
                reactions_data[pid][em].append(r["staff_name"])
            rdres = supabase.table("board_reads").select("post_id,staff_name").in_("post_id", post_ids).execute()
            for r in (rdres.data or []):
                pid = r["post_id"]
                if pid not in read_data: read_data[pid] = []
                read_data[pid].append(r["staff_name"])
            # Session 32: 確認済み(board_checks)を取得
            try:
                chres = supabase.table("board_checks").select("post_id,staff_name").in_("post_id", post_ids).execute()
                for r in (chres.data or []):
                    pid = r["post_id"]
                    if pid not in checks_data: checks_data[pid] = []
                    checks_data[pid].append(r["staff_name"])
            except Exception as e:
                print(f"board_checks load error: {e}")
            # 投稿ごとのカテゴリー情報をマップ化
            try:
                posts_with_cat = supabase.table("board_posts").select("id,category_id").in_("id", post_ids).execute()
                for p in (posts_with_cat.data or []):
                    if p.get("category_id"):
                        post_categories[p["id"]] = p["category_id"]
            except Exception as e:
                print(f"post_categories error: {e}")
    except Exception as e:
        print(f"board detail error: {e}")
    # staffsにふりがなを追加（メンション検索でひらがな/カタカナ入力対応）
    try:
        kana_res = supabase.table("staffs").select("staff_name,staff_name_kana").eq("facility_code", f_code).eq("is_active", True).execute()
        kana_map = {r["staff_name"]: (r.get("staff_name_kana") or "") for r in (kana_res.data or [])}
    except:
        kana_map = {}
    staffs = [{"name": name, "kana": kana_map.get(name, "")} for name in icons.keys()]
    # 利用者リスト(投稿時の選択 + 検索フィルタ用)
    patient_names = []
    try:
        pat_res = supabase.table("patients").select("user_name").eq("facility_code", f_code).order("user_kana").execute()
        seen = set()
        for p in (pat_res.data or []):
            n = (p.get("user_name") or "").strip()
            if n and n not in seen:
                seen.add(n)
                patient_names.append(n)
    except Exception as e:
        print(f"board patients error: {e}")
    # 編集・削除権限: 管理者本人 or 管理画面で許可されたスタッフ
    is_admin = session.get("admin_authenticated", False)
    is_board_editor = is_admin
    if not is_board_editor:
        try:
            import json as _json
            res_be = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "board_editors").execute()
            if res_be.data and res_be.data[0].get("value"):
                editors_list = _json.loads(res_be.data[0]["value"])
                if isinstance(editors_list, list) and my_name in editors_list:
                    is_board_editor = True
        except: pass
    return render("board.html",
        posts=posts, icons=icons, my_name=my_name,
        my_color=staff_color(my_name), my_initial=staff_initial(my_name),
        comments_count=comments_count, reactions_data=reactions_data,
        read_data=read_data, checks_data=checks_data, staffs=staffs,
        board_categories=board_categories, post_categories=post_categories,
        is_admin=is_admin_flag,
        patient_names=patient_names,
        is_board_editor=is_board_editor,
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
        patient_names = _json.loads(request.form.get("patient_names", "[]"))
        if not isinstance(patient_names, list):
            patient_names = []
        image_urls = []
        if photos and photos[0].filename:
            from utils import upload_images_to_supabase
            image_urls = upload_images_to_supabase(supabase, photos, f_code)
        audio_url = ""
        if audio and audio.filename:
            from utils import upload_audio_to_supabase
            audio_url = upload_audio_to_supabase(supabase, audio.read(), audio.filename, f_code)
        pdf_url = ""
        pdf_file = request.files.get("pdf")
        if pdf_file and pdf_file.filename:
            from utils import upload_pdf_to_supabase
            pdf_url = upload_pdf_to_supabase(supabase, pdf_file, f_code)
        # カテゴリー(任意、未指定なら未分類=NULL)
        category_id_raw = request.form.get("category_id", "").strip()
        category_id = None
        if category_id_raw and category_id_raw not in ("null", "undefined", "0"):
            try:
                category_id = int(category_id_raw)
            except (TypeError, ValueError):
                category_id = None
        is_private = request.form.get("is_private", "0") == "1"
        if mentions:  # board-mention-force-private: メンションありは限定公開
            is_private = True
        insert_payload = {
            "facility_code": f_code, "staff_name": my_name,
            "content": content, "image_urls": image_urls,
            "file_urls": ([pdf_url] if pdf_url else []), "audio_url": audio_url,
            "mention_names": mentions, "patient_names": patient_names,
            "is_pinned": False,
            "is_private": is_private,
        }
        if category_id is not None:
            insert_payload["category_id"] = category_id
        res = supabase.table("board_posts").insert(insert_payload).execute()
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
        is_admin = session.get("admin_authenticated", False)
        supabase = get_supabase()
        post = supabase.table("board_posts").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not post.data: return jsonify({"status": "error", "message": "見つかりません"}), 404
        p = post.data[0]
        if p["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        # 編集可: 本人 OR 管理者 OR 掲示板編集権限ありのスタッフ
        can_edit = (p["staff_name"] == my_name) or is_board_editor_user(supabase, f_code, my_name, is_admin)
        if not can_edit:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        update_payload = {
            "content": data.get("content", ""),
            "updated_at": "now()"
        }
        # patient_names の更新(明示的に渡された場合のみ)
        if "patient_names" in data:
            pn = data.get("patient_names")
            if isinstance(pn, list):
                update_payload["patient_names"] = pn
        # category_id の更新(明示的に渡された場合のみ。null/0/undefinedはNULL扱い)
        if "category_id" in data:
            cid = data.get("category_id")
            if cid in (None, "", "null", "undefined", 0, "0"):
                update_payload["category_id"] = None
            else:
                try:
                    update_payload["category_id"] = int(cid)
                except (TypeError, ValueError):
                    update_payload["category_id"] = None
        supabase.table("board_posts").update(update_payload).eq("id", data["id"]).execute()
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
        is_admin = session.get("admin_authenticated", False)
        supabase = get_supabase()
        post = supabase.table("board_posts").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not post.data: return jsonify({"status": "error"}), 404
        p = post.data[0]
        if p["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        # 削除可: 本人 OR 管理者 OR 掲示板編集権限ありのスタッフ
        can_edit = (p["staff_name"] == my_name) or is_board_editor_user(supabase, f_code, my_name, is_admin)
        if not can_edit:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
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
        is_admin = session.get("admin_authenticated", False)
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
        is_admin = session.get("admin_authenticated", False)
        can_edit_others = is_board_editor_user(supabase, f_code, my_name, is_admin)
        icons = get_staff_icons(supabase, f_code)
        res = supabase.table("board_comments").select("*").eq("post_id", post_id).eq("facility_code", f_code).order("created_at").execute()
        comments = []
        for c in (res.data or []):
            ic = staff_icon_data(icons, c["staff_name"])
            is_mine = c["staff_name"] == my_name
            comments.append({**c, "color": ic["color"], "initial": ic["initial"],
                "emoji": ic.get("emoji",""), "image_url": ic.get("image_url",""),
                "is_mine": is_mine, "can_edit": is_mine or can_edit_others,
                "time_label": parse_jst(c["created_at"])})
        try:
            supabase.table("board_reads").upsert({
                "facility_code": f_code, "post_id": int(post_id), "staff_name": my_name
            }, on_conflict="post_id,staff_name").execute()
        except: pass
        # コメントを既読化(自分以外が書いたもののみ、まだ既読化していないもの)
        try:
            other_ids = [c["id"] for c in (res.data or []) if c["staff_name"] != my_name]
            if other_ids:
                already = supabase.table("board_comment_reads").select("comment_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("comment_id", other_ids).execute()
                already_ids = set(r["comment_id"] for r in (already.data or []))
                to_insert = [{"comment_id": cid, "facility_code": f_code, "staff_name": my_name} for cid in other_ids if cid not in already_ids]
                if to_insert:
                    supabase.table("board_comment_reads").insert(to_insert).execute()
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

@app.route("/api/board/update_comment", methods=["POST"])
@login_required
def api_board_update_comment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False)
        supabase = get_supabase()
        c = supabase.table("board_comments").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not c.data: return jsonify({"status": "error", "message": "見つかりません"}), 404
        if c.data[0]["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        # 編集可: 本人 OR 管理者 OR 掲示板編集権限ありのスタッフ
        can_edit = (c.data[0]["staff_name"] == my_name) or is_board_editor_user(supabase, f_code, my_name, is_admin)
        if not can_edit:
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        new_content = data.get("content", "").strip()
        if not new_content:
            return jsonify({"status": "error", "message": "本文が空です"}), 400
        supabase.table("board_comments").update({
            "content": new_content
        }).eq("id", data["id"]).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/delete_comment", methods=["POST"])
@login_required
def api_board_delete_comment():
    try:
        data = request.json
        f_code = session["f_code"]
        my_name = session["my_name"]
        is_admin = session.get("admin_authenticated", False)
        supabase = get_supabase()
        # facility_code も取得して別施設のコメント操作を防ぐ
        c = supabase.table("board_comments").select("staff_name,facility_code").eq("id", data["id"]).execute()
        if not c.data: return jsonify({"status": "error"}), 404
        if c.data[0]["facility_code"] != f_code: return jsonify({"status": "error"}), 403
        # 削除可: 本人 OR 管理者 OR 掲示板編集権限ありのスタッフ
        can_edit = (c.data[0]["staff_name"] == my_name) or is_board_editor_user(supabase, f_code, my_name, is_admin)
        if not can_edit:
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


# Session 32: 確認済み(board_checks)のトグル ===========================
@app.route("/api/board/toggle_check", methods=["POST"])
@login_required
def api_board_toggle_check():
    # 投稿の確認済みフラグをトグル(リアクションとは独立した board_checks テーブルを使用)
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        post_id = data.get("post_id")
        if not post_id:
            return jsonify({"status": "error", "message": "post_id is required"}), 400
        # 既に確認済みか
        existing = supabase.table("board_checks").select("id").eq("post_id", post_id).eq("staff_name", my_name).execute()
        if existing.data:
            # 削除(未確認に戻す)
            supabase.table("board_checks").delete().eq("id", existing.data[0]["id"]).execute()
            action = "removed"
        else:
            # 追加(確認済みにする)
            supabase.table("board_checks").insert({
                "facility_code": f_code, "post_id": post_id,
                "staff_name": my_name,
            }).execute()
            action = "added"
        # 最新の確認済み名前一覧を取得して返す
        cres = supabase.table("board_checks").select("staff_name").eq("post_id", post_id).execute()
        checked_names = [r["staff_name"] for r in (cres.data or [])]
        return jsonify({"status": "success", "action": action, "checked_names": checked_names})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/board/unread_count")
@login_required
def api_board_unread_count():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        # 未読投稿(Session 42: 「確認済みボタンを押す」まで未読。board_checks 基準に統一。
        #  is_private=Trueの投稿は自分がmention_namesに含まれるか投稿者のみカウント)
        all_posts = supabase.table("board_posts").select("id,is_private,mention_names,staff_name").eq("facility_code", f_code).execute()
        # is_privateフィルタリング
        visible_ids = []
        for p in (all_posts.data or []):
            if p.get("is_private"):
                mentions = p.get("mention_names") or []
                if my_name in mentions or p.get("staff_name") == my_name:
                    visible_ids.append(p["id"])
            else:
                visible_ids.append(p["id"])
        all_ids = visible_ids
        post_unread = 0
        if all_ids:
            checked_posts = supabase.table("board_checks").select("post_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
            checked_ids = set(r["post_id"] for r in (checked_posts.data or []))
            post_unread = len([i for i in all_ids if i not in checked_ids])
        # 未読コメント(自分以外作のみカウント)
        comment_unread = 0
        try:
            ccs = supabase.table("board_comments").select("id,staff_name").eq("facility_code", f_code).in_("post_id", all_ids).execute()
            other_ids = [c["id"] for c in (ccs.data or []) if c["staff_name"] != my_name]
            if other_ids:
                read_c = supabase.table("board_comment_reads").select("comment_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("comment_id", other_ids).execute()
                read_c_ids = set(r["comment_id"] for r in (read_c.data or []))
                comment_unread = len([i for i in other_ids if i not in read_c_ids])
        except: pass
        return jsonify({"count": post_unread + comment_unread})
    except Exception as e:
        return jsonify({"count": 0})


@app.route("/api/board/mark_comments_read", methods=["POST"])
@login_required
def api_board_mark_comments_read():
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        data = request.json
        post_id = data.get("post_id")
        if not post_id:
            return jsonify({"status": "error", "message": "post_id required"}), 400
        supabase = get_supabase()
        ccs = supabase.table("board_comments").select("id,staff_name").eq("facility_code", f_code).eq("post_id", post_id).execute()
        other_ids = [r["id"] for r in (ccs.data or []) if r["staff_name"] != my_name]
        if other_ids:
            existing = supabase.table("board_comment_reads").select("comment_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("comment_id", other_ids).execute()
            read_ids = set(r["comment_id"] for r in (existing.data or []))
            to_insert = [{"comment_id": cid, "facility_code": f_code, "staff_name": my_name} for cid in other_ids if cid not in read_ids]
            if to_insert:
                supabase.table("board_comment_reads").insert(to_insert).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/mark_all_read", methods=["POST"])
@login_required
def api_board_mark_all_read():
    """掲示板を開いた瞬間に全投稿+全コメントを既読にする"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        # 全投稿を既読化（is_private=Trueは自分がメンションされているもののみ）
        all_posts = supabase.table("board_posts").select("id,is_private,mention_names,staff_name").eq("facility_code", f_code).execute()
        all_ids = [
            p["id"] for p in (all_posts.data or [])
            if not p.get("is_private") or my_name in (p.get("mention_names") or []) or p.get("staff_name") == my_name
        ]
        post_added = 0
        if all_ids:
            # board_reads に書き込み
            existing_reads = supabase.table("board_reads").select("post_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
            existing_read_ids = set(r["post_id"] for r in (existing_reads.data or []))
            reads_to_insert = [{"post_id": pid, "facility_code": f_code, "staff_name": my_name} for pid in all_ids if pid not in existing_read_ids]
            if reads_to_insert:
                supabase.table("board_reads").insert(reads_to_insert).execute()
            # board_checks に自分の分だけ書き込む
            existing_checks = supabase.table("board_checks").select("post_id").eq("facility_code", f_code).eq("staff_name", my_name).execute()
            existing_check_ids = set(r["post_id"] for r in (existing_checks.data or []))
            checks_to_insert = [
                {"post_id": pid, "facility_code": f_code, "staff_name": my_name}
                for pid in all_ids
                if pid not in existing_check_ids
            ]
            if checks_to_insert:
                supabase.table("board_checks").insert(checks_to_insert).execute()
                post_added = len(checks_to_insert)
        # コメントも全既読化
        comment_added = 0
        try:
            ccs = supabase.table("board_comments").select("id,staff_name").in_("post_id", all_ids).eq("facility_code", f_code).execute()
            other_comment_ids = [c["id"] for c in (ccs.data or []) if c["staff_name"] != my_name]
            if other_comment_ids:
                existing_reads = supabase.table("board_comment_reads").select("comment_id").eq("facility_code", f_code).eq("staff_name", my_name).in_("comment_id", other_comment_ids).execute()
                read_ids = set(r["comment_id"] for r in (existing_reads.data or []))
                to_insert = [{"comment_id": cid, "facility_code": f_code, "staff_name": my_name} for cid in other_comment_ids if cid not in read_ids]
                if to_insert:
                    supabase.table("board_comment_reads").insert(to_insert).execute()
                    comment_added = len(to_insert)
        except: pass
        return jsonify({"status": "success", "count": post_added + comment_added, "posts": post_added, "comments": comment_added})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
        is_creator = (t["created_by"] == my_name)
        is_assignee = (my_name in assigned) or (not assigned)  # task-perm-empty-allowall: 空配列＝全員向けは全員操作可
        if not (is_creator or is_assignee):  # task-update-no-admin: 管理者も除外(担当/作成者のみ)
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

        task = supabase.table("tasks").select("created_by,assigned_to").eq("id", task_id).eq("facility_code", f_code).execute()  # task-del-select-assigned
        if not task.data:
            return jsonify({"status": "error"}), 404
        _assigned_del = task.data[0].get("assigned_to") or []  # task-del-no-admin
        is_creator = (task.data[0]["created_by"] == my_name)
        is_assignee = (my_name in _assigned_del) or (not _assigned_del)
        if not (is_creator or is_assignee):
            return jsonify({"status": "error", "message": "作成者または担当者のみ削除できます"}), 403

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

from monitoring_integration import register_monitoring_routes
register_monitoring_routes(app)

from patient_info_integration import register_patient_info_routes
register_patient_info_routes(app)

from patient_info_import_integration import register_import_routes
register_import_routes(app)



# ===== 掲示板カテゴリー管理API =====
@app.route("/api/board_categories", methods=["GET"])
@login_required
def api_board_categories_list():
    """カテゴリー一覧取得"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        res = supabase.table("board_categories").select("*").eq("facility_code", f_code).order("sort_order").order("id").execute()
        return jsonify({"status": "success", "categories": res.data or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board_categories/save", methods=["POST"])
@login_required
def api_board_categories_save():
    """カテゴリー作成・編集(管理者のみ)"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者のみ操作できます"}), 403
        data = request.json
        cat_id = data.get("id")
        payload = {
            "name": (data.get("name") or "").strip(),
            "color": data.get("color") or "#1a73e8",
            "sort_order": int(data.get("sort_order") or 0),
        }
        if not payload["name"]:
            return jsonify({"status": "error", "message": "カテゴリー名を入力してください"}), 400
        if cat_id:
            # 編集
            supabase.table("board_categories").update(payload).eq("id", cat_id).eq("facility_code", f_code).execute()
        else:
            # 新規作成
            payload["facility_code"] = f_code
            payload["created_by"] = my_name
            r = supabase.table("board_categories").insert(payload).execute()
            cat_id = r.data[0]["id"] if r.data else None
        return jsonify({"status": "success", "id": cat_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board_categories/delete", methods=["POST"])
@login_required
def api_board_categories_delete():
    """カテゴリー削除(管理者のみ)"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者のみ操作できます"}), 403
        data = request.json
        cat_id = data.get("id")
        if not cat_id:
            return jsonify({"status": "error", "message": "IDが必要です"}), 400
        # 削除前に、このカテゴリーを使っている投稿のcategory_idをNULLにする
        supabase.table("board_posts").update({"category_id": None}).eq("category_id", cat_id).eq("facility_code", f_code).execute()
        # カテゴリー本体を削除
        supabase.table("board_categories").delete().eq("id", cat_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ===== ケース記録カテゴリ管理API(Session 21)=====
@app.route("/api/record_categories", methods=["GET"])
@login_required
def api_record_categories_list():
    """ケース記録カテゴリ一覧取得"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        res = supabase.table("record_categories").select("*").eq("facility_code", f_code).order("sort_order").order("id").execute()
        return jsonify({"status": "success", "categories": res.data or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/record_categories/save", methods=["POST"])
@login_required
def api_record_categories_save():
    """ケース記録カテゴリ作成・編集(管理者のみ)"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者のみ操作できます"}), 403
        data = request.json
        cat_id = data.get("id")
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return jsonify({"status": "error", "message": "カテゴリ名を入力してください"}), 400
        payload = {
            "name": new_name,
            "color": data.get("color") or "#F97316",
            "sort_order": int(data.get("sort_order") or 0),
        }
        if cat_id:
            # 編集 - 旧カテゴリ名を取得して、紐づく records.category も更新
            old_res = supabase.table("record_categories").select("name").eq("id", cat_id).eq("facility_code", f_code).execute()
            old_name = old_res.data[0]["name"] if old_res.data else None
            supabase.table("record_categories").update(payload).eq("id", cat_id).eq("facility_code", f_code).execute()
            if old_name and old_name != new_name:
                supabase.table("records").update({"category": new_name}).eq("facility_code", f_code).eq("category", old_name).execute()
        else:
            # 新規作成
            payload["facility_code"] = f_code
            payload["is_default"] = False
            r = supabase.table("record_categories").insert(payload).execute()
            cat_id = r.data[0]["id"] if r.data else None
        return jsonify({"status": "success", "id": cat_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/record_categories/delete", methods=["POST"])
@login_required
def api_record_categories_delete():
    """ケース記録カテゴリ削除(管理者のみ。紐づく既存記録は「その他」に救済)"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者のみ操作できます"}), 403
        data = request.json
        cat_id = data.get("id")
        if not cat_id:
            return jsonify({"status": "error", "message": "IDが必要です"}), 400
        # 削除対象のカテゴリ情報を取得
        cat_res = supabase.table("record_categories").select("name").eq("id", cat_id).eq("facility_code", f_code).execute()
        if not cat_res.data:
            return jsonify({"status": "error", "message": "カテゴリが見つかりません"}), 404
        cat_name = cat_res.data[0]["name"]
        if cat_name == "その他":
            return jsonify({"status": "error", "message": "「その他」カテゴリは削除できません"}), 400
        # このカテゴリを使っている既存記録を「その他」に救済
        supabase.table("records").update({"category": "その他"}).eq("facility_code", f_code).eq("category", cat_name).execute()
        # カテゴリ本体を削除
        supabase.table("record_categories").delete().eq("id", cat_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/records/update_category", methods=["POST"])
@login_required
def api_record_update_category():
    """既存記録のカテゴリを変更(投稿者本人または管理者のみ)"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        record_id = data.get("record_id")
        new_category = (data.get("category") or "").strip()
        if not record_id or not new_category:
            return jsonify({"status": "error", "message": "record_id と category が必要です"}), 400
        # 権限チェック: 投稿者本人 or 管理者
        rec_res = supabase.table("records").select("staff_name").eq("id", record_id).eq("facility_code", f_code).execute()
        if not rec_res.data:
            return jsonify({"status": "error", "message": "記録が見つかりません"}), 404
        is_owner = (rec_res.data[0]["staff_name"] == my_name)
        is_admin = is_admin_user(supabase, f_code, my_name)
        if not (is_owner or is_admin):
            return jsonify({"status": "error", "message": "投稿者本人または管理者のみ変更できます"}), 403
        # カテゴリの存在確認(自施設のカテゴリリストに含まれるか)
        cat_res = supabase.table("record_categories").select("name").eq("facility_code", f_code).eq("name", new_category).execute()
        if not cat_res.data:
            return jsonify({"status": "error", "message": "そのカテゴリは存在しません"}), 400
        supabase.table("records").update({"category": new_category}).eq("id", record_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success", "category": new_category})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/board/update_category", methods=["POST"])
@login_required
def api_board_update_category():
    """投稿のカテゴリー変更(管理者または投稿者本人)"""
    try:
        f_code = session["f_code"]
        my_name = session["my_name"]
        supabase = get_supabase()
        data = request.json
        post_id = data.get("post_id")
        category_id = data.get("category_id")  # null可(未分類)
        if not post_id:
            return jsonify({"status": "error", "message": "post_idが必要です"}), 400
        # 権限チェック: 管理者 or 投稿者本人
        post_res = supabase.table("board_posts").select("staff_name").eq("id", post_id).eq("facility_code", f_code).execute()
        if not post_res.data:
            return jsonify({"status": "error", "message": "投稿が見つかりません"}), 404
        is_owner = (post_res.data[0]["staff_name"] == my_name)
        is_admin = is_admin_user(supabase, f_code, my_name)
        if not (is_owner or is_admin):
            return jsonify({"status": "error", "message": "権限がありません"}), 403
        # 更新(category_idがNoneの場合はNULLに)
        update_data = {"category_id": category_id if category_id else None}
        supabase.table("board_posts").update(update_data).eq("id", post_id).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
    app.run(host='0.0.0.0', port=8080, debug=False)


# ============================================================
# Session 31: AIカテゴリ自動振り分け
# ============================================================
@app.route('/admin/ai-categorize')
@login_required
def admin_ai_categorize():
    """管理者向け: 「その他」カテゴリの記録一覧を表示"""
    f_code = session["f_code"]
    if not session.get("admin_authenticated", False):
        return redirect(url_for("dev_login"))

    supabase = get_supabase()
    records = []
    try:
        # 「その他」カテゴリの記録を新しい順で最大100件取得
        # AI統合記録は除外
        res = supabase.table("records") \
            .select("id,content,category,staff_name,user_name,created_at") \
            .eq("facility_code", f_code) \
            .eq("category", "その他") \
            .neq("staff_name", "AI統合記録") \
            .order("created_at", desc=True) \
            .limit(100) \
            .execute()
        for r in (res.data or []):
            # JSTで created_at を整形
            try:
                created_at_jst = parse_jst(r.get("created_at", ""), fmt="%Y-%m-%d %H:%M")
            except Exception:
                created_at_jst = r.get("created_at", "")[:16]
            records.append({
                "id": r.get("id"),
                "content": (r.get("content") or "")[:300],
                "staff_name": r.get("staff_name") or "",
                "user_name": r.get("user_name") or "",
                "created_at_jst": created_at_jst,
            })
    except Exception as e:
        print(f"[admin_ai_categorize] fetch error: {e}", flush=True)

    return render("admin_ai_categorize.html", records=records)


@app.route('/api/admin/ai-categorize/judge', methods=['POST'])
@login_required
def api_admin_ai_categorize_judge():
    """選択された record_id を AI 判定し、結果を返す(DB変更はしない)。"""
    if not session.get("admin_authenticated", False):
        return jsonify({"ok": False, "error": "管理者認証が必要です"}), 403

    f_code = session["f_code"]
    payload = request.get_json(silent=True) or {}
    record_ids = payload.get("record_ids") or []

    if not isinstance(record_ids, list) or len(record_ids) == 0:
        return jsonify({"ok": False, "error": "record_ids が空です"}), 400
    if len(record_ids) > 20:
        return jsonify({"ok": False, "error": "一度に判定できるのは20件までです(フロントは通常10件ずつバッチ送信)"}), 400

    # int に正規化(Jinja から文字列で来る可能性に備え)
    try:
        record_ids = [int(x) for x in record_ids]
    except Exception:
        return jsonify({"ok": False, "error": "record_ids の形式が不正です"}), 400

    supabase = get_supabase()

    # 対象レコードを一括取得(他施設の記録を判定しないよう f_code で絞る)
    try:
        res = supabase.table("records") \
            .select("id,content,category") \
            .in_("id", record_ids) \
            .eq("facility_code", f_code) \
            .execute()
        rows = res.data or []
    except Exception as e:
        return jsonify({"ok": False, "error": f"記録取得エラー: {e}"}), 500

    # id → row のマップ
    rows_by_id = {r["id"]: r for r in rows}

    results = []
    for rid in record_ids:
        row = rows_by_id.get(rid)
        if not row:
            # 該当なし(他施設・削除済み・AI統合記録など)
            continue
        content_text = row.get("content") or ""
        current_category = row.get("category") or "その他"
        try:
            ai_result = classify_category(content_text, current_category)
        except Exception as e:
            print(f"[ai-categorize/judge] classify_category fail rid={rid}: {e}", flush=True)
            ai_result = {"category": "その他", "confidence": "low", "reason": "AI判定エラー"}
        results.append({
            "record_id": rid,
            "content": content_text[:300],
            "current_category": current_category,
            "category": ai_result.get("category", "その他"),
            "confidence": ai_result.get("confidence", "low"),
            "reason": ai_result.get("reason", ""),
        })

    return jsonify({"ok": True, "results": results, "count": len(results)})



# ============================================================
# Session 31 Step 5: AIカテゴリ自動振り分け - 適用 / 履歴 / ロールバック
# ============================================================
@app.route('/api/admin/ai-categorize/apply', methods=['POST'])
@login_required
def api_admin_ai_categorize_apply():
    """AI判定結果をDBに反映する。
    body: {items: [{record_id, new_category, ai_reason}, ...]}
    各レコードに対し:
      - records.category と records.search_tags を UPDATE
        (search_tags は新カテゴリで generate_search_tags を再生成)
      - ai_categorize_history に INSERT (同じ batch_id で全件)
    return: {ok, batch_id, applied_count, errors}
    """
    if not session.get("admin_authenticated", False):
        return jsonify({"ok": False, "error": "管理者認証が必要です"}), 403

    f_code = session["f_code"]
    my_name = session.get("my_name", "")
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []

    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"ok": False, "error": "items が空です"}), 400
    if len(items) > 100:
        return jsonify({"ok": False, "error": "一度に適用できるのは100件までです"}), 400

    # Session 33: 「休み連絡」を含む
    VALID_CATEGORIES = {"入浴", "食事", "排泄", "その他", "コミュニケーション", "心身状況", "訓練状況", "ヒヤリハット", "休み連絡"}

    normalized = []
    for it in items:
        try:
            rid = int(it.get("record_id"))
        except Exception:
            continue
        new_cat = str(it.get("new_category") or "").strip()
        if new_cat not in VALID_CATEGORIES:
            continue
        ai_reason = str(it.get("ai_reason") or "")[:200]
        normalized.append({"record_id": rid, "new_category": new_cat, "ai_reason": ai_reason})

    if len(normalized) == 0:
        return jsonify({"ok": False, "error": "有効な items がありません"}), 400

    supabase = get_supabase()
    record_ids = [n["record_id"] for n in normalized]

    try:
        res = supabase.table("records") \
            .select("id,content,category,search_tags") \
            .in_("id", record_ids) \
            .eq("facility_code", f_code) \
            .execute()
        rows = res.data or []
    except Exception as e:
        return jsonify({"ok": False, "error": f"記録取得エラー: {e}"}), 500

    rows_by_id = {r["id"]: r for r in rows}

    batch_id = str(uuid.uuid4())
    applied_count = 0
    errors = []

    for n in normalized:
        rid = n["record_id"]
        new_cat = n["new_category"]
        ai_reason = n["ai_reason"]
        row = rows_by_id.get(rid)
        if not row:
            errors.append({"record_id": rid, "error": "対象レコードなし"})
            continue
        old_cat = row.get("category") or "その他"
        old_tags = row.get("search_tags") or []
        content_text = row.get("content") or ""

        try:
            new_tags = generate_search_tags(content_text, new_cat) or []
        except Exception as e:
            print(f"[ai-categorize/apply] generate_search_tags fail rid={rid}: {e}", flush=True)
            new_tags = []

        try:
            supabase.table("records") \
                .update({"category": new_cat, "search_tags": new_tags}) \
                .eq("id", rid) \
                .eq("facility_code", f_code) \
                .execute()
        except Exception as e:
            errors.append({"record_id": rid, "error": f"UPDATE失敗: {e}"})
            continue

        try:
            supabase.table("ai_categorize_history").insert({
                "batch_id": batch_id,
                "record_id": rid,
                "old_category": old_cat,
                "new_category": new_cat,
                "old_search_tags": old_tags,
                "new_search_tags": new_tags,
                "ai_reason": ai_reason,
                "applied_by": my_name,
            }).execute()
        except Exception as e:
            print(f"[ai-categorize/apply] history insert fail rid={rid}: {e}", flush=True)
            errors.append({"record_id": rid, "error": f"履歴記録失敗(更新は完了): {e}"})

        applied_count += 1

    return jsonify({
        "ok": True,
        "batch_id": batch_id,
        "applied_count": applied_count,
        "total": len(normalized),
        "errors": errors,
    })


@app.route('/api/admin/ai-categorize/history')
@login_required
def api_admin_ai_categorize_history():
    """過去の適用batch一覧。新しい順、最大50バッチ。"""
    if not session.get("admin_authenticated", False):
        return jsonify({"ok": False, "error": "管理者認証が必要です"}), 403

    f_code = session["f_code"]
    supabase = get_supabase()

    try:
        hist_res = supabase.table("ai_categorize_history") \
            .select("id,batch_id,record_id,old_category,new_category,ai_reason,applied_by,applied_at,rolled_back_at") \
            .order("applied_at", desc=True) \
            .limit(2000) \
            .execute()
        hist_rows = hist_res.data or []
    except Exception as e:
        return jsonify({"ok": False, "error": f"履歴取得エラー: {e}"}), 500

    if not hist_rows:
        return jsonify({"ok": True, "batches": []})

    rec_ids = list({h["record_id"] for h in hist_rows})
    try:
        rec_res = supabase.table("records") \
            .select("id") \
            .in_("id", rec_ids) \
            .eq("facility_code", f_code) \
            .execute()
        my_rec_ids = {r["id"] for r in (rec_res.data or [])}
    except Exception as e:
        return jsonify({"ok": False, "error": f"records 確認エラー: {e}"}), 500

    my_hist = [h for h in hist_rows if h["record_id"] in my_rec_ids]

    batches_map = {}
    for h in my_hist:
        bid = h["batch_id"]
        if bid not in batches_map:
            batches_map[bid] = {
                "batch_id": bid,
                "applied_at": h["applied_at"],
                "applied_by": h["applied_by"],
                "count": 0,
                "rolled_back_count": 0,
                "items": [],
            }
        batches_map[bid]["count"] += 1
        if h.get("rolled_back_at"):
            batches_map[bid]["rolled_back_count"] += 1
        batches_map[bid]["items"].append({
            "history_id": h["id"],
            "record_id": h["record_id"],
            "old_category": h["old_category"],
            "new_category": h["new_category"],
            "ai_reason": h.get("ai_reason") or "",
            "rolled_back_at": h.get("rolled_back_at"),
        })

    batches = sorted(
        batches_map.values(),
        key=lambda b: b["applied_at"] or "",
        reverse=True,
    )[:50]

    return jsonify({"ok": True, "batches": batches})


@app.route('/api/admin/ai-categorize/rollback', methods=['POST'])
@login_required
def api_admin_ai_categorize_rollback():
    """ロールバック。
    body:
      {batch_id: uuid} → そのバッチの未ロールバック分を全件戻す
      {history_id: int} → そのhistory 1件だけ戻す
    """
    if not session.get("admin_authenticated", False):
        return jsonify({"ok": False, "error": "管理者認証が必要です"}), 403

    f_code = session["f_code"]
    payload = request.get_json(silent=True) or {}
    batch_id = payload.get("batch_id")
    history_id = payload.get("history_id")

    if not batch_id and not history_id:
        return jsonify({"ok": False, "error": "batch_id か history_id を指定してください"}), 400

    supabase = get_supabase()

    try:
        if history_id:
            try:
                hid = int(history_id)
            except Exception:
                return jsonify({"ok": False, "error": "history_id は整数で指定してください"}), 400
            hist_res = supabase.table("ai_categorize_history") \
                .select("*") \
                .eq("id", hid) \
                .is_("rolled_back_at", "null") \
                .execute()
        else:
            hist_res = supabase.table("ai_categorize_history") \
                .select("*") \
                .eq("batch_id", batch_id) \
                .is_("rolled_back_at", "null") \
                .execute()
        hist_rows = hist_res.data or []
    except Exception as e:
        return jsonify({"ok": False, "error": f"履歴取得エラー: {e}"}), 500

    if not hist_rows:
        return jsonify({"ok": False, "error": "対象の履歴がありません(既にロールバック済みか、存在しません)"}), 404

    rec_ids = list({h["record_id"] for h in hist_rows})
    try:
        rec_res = supabase.table("records") \
            .select("id") \
            .in_("id", rec_ids) \
            .eq("facility_code", f_code) \
            .execute()
        my_rec_ids = {r["id"] for r in (rec_res.data or [])}
    except Exception as e:
        return jsonify({"ok": False, "error": f"records 確認エラー: {e}"}), 500

    rolled_back_count = 0
    errors = []

    for h in hist_rows:
        rid = h["record_id"]
        if rid not in my_rec_ids:
            errors.append({"history_id": h["id"], "error": "他施設のレコード(無視)"})
            continue
        old_cat = h.get("old_category") or "その他"
        old_tags = h.get("old_search_tags") or []

        try:
            supabase.table("records") \
                .update({"category": old_cat, "search_tags": old_tags}) \
                .eq("id", rid) \
                .eq("facility_code", f_code) \
                .execute()
        except Exception as e:
            errors.append({"history_id": h["id"], "error": f"UPDATE失敗: {e}"})
            continue

        try:
            supabase.table("ai_categorize_history") \
                .update({"rolled_back_at": "now()"}) \
                .eq("id", h["id"]) \
                .execute()
        except Exception as e:
            print(f"[rollback] history mark fail hid={h['id']}: {e}", flush=True)
            errors.append({"history_id": h["id"], "error": f"履歴更新失敗(records戻し済): {e}"})

        rolled_back_count += 1

    return jsonify({
        "ok": True,
        "rolled_back_count": rolled_back_count,
        "total": len(hist_rows),
        "errors": errors,
    })



# ============================================================
# Session 31 Step 6: 投稿時提案 + カード上適用
# ============================================================
@app.route('/api/records/suggest_category', methods=['POST'])
@login_required
def api_records_suggest_category():
    """投稿時のAIカテゴリ提案 / カード上の判定で共通利用するAPI。
    body: {content, current_category}
    return: classify_category() の結果そのまま (category, confidence, reason)
    """
    payload = request.get_json(silent=True) or {}
    text = (payload.get("content") or "").strip()
    cur_cat = (payload.get("current_category") or "その他").strip()

    if not text:
        return jsonify({"ok": False, "error": "content が空です"}), 400

    try:
        result = classify_category(text, cur_cat)
    except Exception as e:
        print(f"[suggest_category] failed: {e}", flush=True)
        return jsonify({"ok": False, "error": "AI判定エラー"}), 500

    return jsonify({"ok": True, "result": result})


@app.route('/api/records/<int:record_id>/apply_ai_category', methods=['POST'])
@login_required
def api_records_apply_ai_category(record_id):
    """カードから個別レコードのカテゴリをAI提案で書き換え。
    権限: 投稿者本人 or 管理者
    body: {new_category, ai_reason}
    処理: records UPDATE + ai_categorize_history INSERT (履歴で一元管理)
    """
    f_code = session["f_code"]
    my_name = session.get("my_name", "")
    is_admin = session.get("admin_authenticated", False)

    payload = request.get_json(silent=True) or {}
    new_cat = (payload.get("new_category") or "").strip()
    ai_reason = str(payload.get("ai_reason") or "")[:200]

    # Session 33: 「休み連絡」を含む
    VALID_CATEGORIES = {"入浴", "食事", "排泄", "その他", "コミュニケーション", "心身状況", "訓練状況", "ヒヤリハット", "休み連絡"}
    if new_cat not in VALID_CATEGORIES:
        return jsonify({"ok": False, "error": "不正なカテゴリです"}), 400

    supabase = get_supabase()

    # 対象レコード取得
    try:
        res = supabase.table("records") \
            .select("id,content,category,search_tags,staff_name") \
            .eq("id", record_id) \
            .eq("facility_code", f_code) \
            .execute()
        rows = res.data or []
    except Exception as e:
        return jsonify({"ok": False, "error": f"記録取得エラー: {e}"}), 500

    if not rows:
        return jsonify({"ok": False, "error": "対象レコードがありません"}), 404

    row = rows[0]
    poster = row.get("staff_name") or ""

    # 権限チェック: 投稿者本人 or 管理者
    if not is_admin and poster != my_name:
        return jsonify({"ok": False, "error": "この記録を変更する権限がありません"}), 403

    old_cat = row.get("category") or "その他"
    old_tags = row.get("search_tags") or []
    content_text = row.get("content") or ""

    # search_tags 再生成
    try:
        new_tags = generate_search_tags(content_text, new_cat) or []
    except Exception as e:
        print(f"[apply_ai_category] generate_search_tags fail rid={record_id}: {e}", flush=True)
        new_tags = []

    # records UPDATE
    try:
        update_dict = {"category": new_cat, "search_tags": new_tags}
        # Session 33: 「休み連絡 → 他カテゴリ」に変えるときは leave_reporter_* を None クリア
        # (「他カテゴリ → 休み連絡」のときは値が空のまま記録されるので、編集ボタンから後入力する運用)
        if old_cat == "休み連絡" and new_cat != "休み連絡":
            update_dict["leave_reporter_type"] = None
            update_dict["leave_reporter_relation"] = None
        supabase.table("records") \
            .update(update_dict) \
            .eq("id", record_id) \
            .eq("facility_code", f_code) \
            .execute()
    except Exception as e:
        return jsonify({"ok": False, "error": f"UPDATE失敗: {e}"}), 500

    # 履歴 INSERT(個別操作なので独立batch_id)
    batch_id = str(uuid.uuid4())
    try:
        supabase.table("ai_categorize_history").insert({
            "batch_id": batch_id,
            "record_id": record_id,
            "old_category": old_cat,
            "new_category": new_cat,
            "old_search_tags": old_tags,
            "new_search_tags": new_tags,
            "ai_reason": ai_reason,
            "applied_by": my_name,
        }).execute()
    except Exception as e:
        print(f"[apply_ai_category] history insert fail rid={record_id}: {e}", flush=True)
        # 履歴INSERT失敗してもrecords更新は完了済み。エラーは返すが ok:true 維持。
        return jsonify({
            "ok": True,
            "warning": f"履歴記録失敗(更新は完了): {e}",
            "new_category": new_cat,
            "new_search_tags": new_tags,
        })

    return jsonify({
        "ok": True,
        "batch_id": batch_id,
        "new_category": new_cat,
        "new_search_tags": new_tags,
    })

# cache bust 2026年 5月16日 土曜日 20時14分56秒 JST


# ============================================================
# Session 49: 体力測定・体重記録 (fitness_tests / body_weights)
# ============================================================


def _to_half_number(v):
    """全角数字・全角記号を半角化して数値文字列に整える。
    例: '５２．４' -> '52.4' / '１８' -> '18' / '' or None -> None
    数値化できない場合は None を返す(不正値は保存しない)。"""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    # 全角数字 0-9 / 全角ピリオド / 全角マイナス / 全角空白 を半角へ
    table = str.maketrans(
        "０１２３４５６７８９．－＋　",
        "0123456789.-+ ",
    )
    s = s.translate(table).strip()
    # カンマや余分な空白を除去
    s = s.replace(",", "").replace(" ", "")
    if s == "":
        return None
    try:
        f = float(s)
    except (ValueError, TypeError):
        return None
    # 整数なら整数文字列、小数なら小数文字列で返す
    if f == int(f):
        return str(int(f))
    return str(f)
@app.route('/fitness')
@login_required
def fitness_page():
    """体力測定・体重 記録ページ (1ページ2セクション)"""
    f_code = session["f_code"]
    supabase = get_supabase()
    patients = get_patients(supabase, f_code)
    today = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
    return render(
        "fitness.html",
        patients=patients,
        today=today,
    )
@app.route('/life_check')  # life-check-page-route
@login_required
def life_check_page():
    """生活機能チェックシート (様式3-2) 入力ページ"""
    f_code = session["f_code"]
    supabase = get_supabase()
    patients = get_patients(supabase, f_code)
    today = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
    return render(
        "life_check.html",
        patients=patients,
        today=today,
        my_name=session.get("my_name", ""),  # life-evaluator-myname
    )


@app.route('/api/save_body_weight', methods=['POST'])
@login_required
def api_save_body_weight():
    """体重を1件保存 (同一利用者・同一日付は upsert)"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()

        patient_id = str(data.get("patient_id", "")).strip()
        user_name = data.get("user_name", "").strip()
        measured_date = data.get("measured_date", "").strip()
        weight_kg = _to_half_number(data.get("weight_kg", None))

        if not patient_id or not measured_date:
            return jsonify({"status": "error",
                            "message": "利用者と測定日は必須です"}), 400
        if weight_kg in (None, ""):
            return jsonify({"status": "error",
                            "message": "体重を正しく入力してください"}), 400

        payload = {
            "facility_code": f_code,
            "patient_id": patient_id,
            "user_name": user_name,
            "measured_date": measured_date,
            "weight_kg": weight_kg,
            "note": data.get("note", ""),
            "staff_name": my_name,
            "updated_at": "now()",
        }

        existing = supabase.table("body_weights").select("id").eq(
            "facility_code", f_code).eq(
            "patient_id", patient_id).eq(
            "measured_date", measured_date).execute()

        if existing.data:
            rid = existing.data[0]["id"]
            supabase.table("body_weights").update(payload).eq("id", rid).execute()
        else:
            res = supabase.table("body_weights").insert(payload).execute()
            rid = res.data[0]["id"] if res.data else None

        return jsonify({"status": "success", "id": rid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/save_fitness_test', methods=['POST'])
@login_required
def api_save_fitness_test():
    """体力測定を1件保存 (同一利用者・同一日付は upsert)。
    各指標は入力があったものだけ保存し、空欄は None で送る。"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()

        patient_id = str(data.get("patient_id", "")).strip()
        user_name = data.get("user_name", "").strip()
        measured_date = data.get("measured_date", "").strip()

        if not patient_id or not measured_date:
            return jsonify({"status": "error",
                            "message": "利用者と測定日は必須です"}), 400

        def num_or_none(v):
            return _to_half_number(v)

        metrics = {
            "grip_right": num_or_none(data.get("grip_right")),
            "grip_left": num_or_none(data.get("grip_left")),
            "standing_balance_right": num_or_none(data.get("standing_balance_right")),
            "standing_balance_left": num_or_none(data.get("standing_balance_left")),
            "tug_sec": num_or_none(data.get("tug_sec")),
            "walk_5m_sec": num_or_none(data.get("walk_5m_sec")),
            "walk_5m_max_sec": num_or_none(data.get("walk_5m_max_sec")),
            "sit_stand_30sec": num_or_none(data.get("sit_stand_30sec")),
        }

        # 全項目空ならエラー (測定値が1つもないレコードは作らない)
        if all(v is None for v in metrics.values()):
            return jsonify({"status": "error",
                            "message": "測定値を1つ以上入力してください"}), 400

        payload = {
            "facility_code": f_code,
            "patient_id": patient_id,
            "user_name": user_name,
            "measured_date": measured_date,
            "note": data.get("note", ""),
            "staff_name": my_name,
            "updated_at": "now()",
        }
        payload.update(metrics)

        existing = supabase.table("fitness_tests").select("id").eq(
            "facility_code", f_code).eq(
            "patient_id", patient_id).eq(
            "measured_date", measured_date).execute()

        if existing.data:
            rid = existing.data[0]["id"]
            supabase.table("fitness_tests").update(payload).eq("id", rid).execute()
        else:
            res = supabase.table("fitness_tests").insert(payload).execute()
            rid = res.data[0]["id"] if res.data else None

        return jsonify({"status": "success", "id": rid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/delete_fitness_test', methods=['POST'])
@login_required
def api_delete_fitness_test():
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        data = request.get_json()
        rid = data.get("id")
        if not rid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        supabase.table("fitness_tests").delete().eq("id", rid).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete_body_weight', methods=['POST'])
@login_required
def api_delete_body_weight():
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        data = request.get_json()
        rid = data.get("id")
        if not rid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        supabase.table("body_weights").delete().eq("id", rid).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/fitness_history')
@login_required
def api_fitness_history():
    """指定利用者の体重・体力測定の履歴を返す (新しい順)。
    患者は patient_id で絞る。"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        patient_id = str(request.args.get("patient_id", "")).strip()
        if not patient_id:
            return jsonify({"weights": [], "fitness": []})

        w = supabase.table("body_weights").select(
            "id, measured_date, weight_kg, note, staff_name"
        ).eq("facility_code", f_code).eq(
            "patient_id", patient_id).order(
            "measured_date", desc=True).execute()

        ft = supabase.table("fitness_tests").select(
            "id, measured_date, grip_right, grip_left, standing_balance_right, standing_balance_left, "
            "tug_sec, walk_5m_sec, walk_5m_max_sec, sit_stand_30sec, note, staff_name"
        ).eq("facility_code", f_code).eq(
            "patient_id", patient_id).order(
            "measured_date", desc=True).execute()

        return jsonify({
            "weights": w.data or [],
            "fitness": ft.data or [],
        })
    except Exception as e:
        return jsonify({"weights": [], "fitness": [], "error": str(e)}), 500


# ============================================================
# life-check-api-block : seikatsu kinou check (yoshiki 3-2) save/get API
# ADL scores are tap-selected integers from frontend; no zenkaku normalize.
# patient key = patient_id; upsert on (facility_code, patient_id, check_date).
# ============================================================

_LIFE_ADL_FIELDS = [
    "adl_eating", "adl_transfer", "adl_grooming", "adl_toilet", "adl_bathing",
    "adl_walking", "adl_wheelchair", "adl_stairs", "adl_dressing",
    "adl_bowel", "adl_bladder",
]
_LIFE_STAGE_FIELDS = [
    "iadl_cooking", "iadl_laundry", "iadl_cleaning",
    "basic_rollover", "basic_situp", "basic_sitting",
    "basic_standup", "basic_standing",
]
_LIFE_NOTE_FIELDS = [f + "_note" for f in _LIFE_ADL_FIELDS] + [
    "iadl_cooking_note", "iadl_laundry_note", "iadl_cleaning_note",
    "basic_rollover_note", "basic_situp_note", "basic_sitting_note",
    "basic_standup_note", "basic_standing_note",
]
_LIFE_META_FIELDS = [
    "visit_type", "birth_date", "gender", "evaluator", "evaluator_job",
    "care_level", "adl_independence", "dementia_independence", "note",
]


# life-save-expand-v1: Barthel official scores (mhlw) + 4-level fields
_LIFE_BARTHEL_ALLOWED = {
    "adl_eating":   {10, 5, 0},
    "adl_transfer": {15, 10, 5, 0},
    "adl_grooming": {5, 0},
    "adl_toilet":   {10, 5, 0},
    "adl_bathing":  {5, 0},
    "adl_walking":  {15, 10, 5, 0},
    "adl_stairs":   {10, 5, 0},
    "adl_dressing": {10, 5, 0},
    "adl_bowel":    {10, 5, 0},
    "adl_bladder":  {10, 5, 0},
}
_LIFE_LEVEL_FIELDS = [
    "adl_wheelchair",
    "iadl_cooking", "iadl_laundry", "iadl_cleaning",
    "basic_rollover", "basic_situp", "basic_sitting",
    "basic_standup", "basic_standing",
]
_LIFE_LEVEL_ALLOWED = {"independent", "watch", "partial", "full"}
_LIFE_ALL_ITEMS = _LIFE_ADL_FIELDS + _LIFE_STAGE_FIELDS
def _life_level_or_none(v):
    if v is None or v == "":
        return None
    s = str(v).strip()
    return s if s in _LIFE_LEVEL_ALLOWED else None
def _life_bool_or_none(v):
    if isinstance(v, bool):
        return v
    if v in (1, "1", "true", "True", "yes"):
        return True
    if v in (0, "0", "false", "False", "no"):
        return False
    return None
def _life_int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
def _life_score_validated(field, v):  # life-save-expand-v1
    iv = _life_int_or_none(v)
    if iv is None:
        return None
    allowed = _LIFE_BARTHEL_ALLOWED.get(field)
    if allowed is None:
        return None
    return iv if iv in allowed else None


@app.route('/api/save_life_check', methods=['POST'])
@login_required
def api_save_life_check():
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()

        patient_id = str(data.get("patient_id", "")).strip()
        check_date = str(data.get("check_date", "")).strip()
        if not patient_id or not check_date:
            return jsonify({"status": "error",
                            "message": "riyousha to hyoukabi ha hissu desu"}), 400

        payload = {
            "facility_code": f_code,
            "patient_id": patient_id,
            "user_name": str(data.get("user_name", "")).strip(),
            "check_date": check_date,
            "staff_name": my_name,
        }

        # life-save-expand-v1: ADL10=Barthel score (validated), others=4-level
        for f in _LIFE_BARTHEL_ALLOWED:
            payload[f] = _life_score_validated(f, data.get(f))
        for f in _LIFE_LEVEL_FIELDS:
            payload[f + "_level"] = _life_level_or_none(data.get(f + "_level"))
        # per-item issue(boolean) and env(text) for all items
        for f in _LIFE_ALL_ITEMS:
            if (f + "_issue") in data:
                payload[f + "_issue"] = _life_bool_or_none(data.get(f + "_issue"))
            if (f + "_env") in data:
                payload[f + "_env"] = data.get(f + "_env")
        # notes and meta (unchanged)
        for f in _LIFE_NOTE_FIELDS + _LIFE_META_FIELDS:
            if f in data and data.get(f) is not None:
                payload[f] = data.get(f)

        existing = supabase.table("life_function_checks").select("id").eq(
            "facility_code", f_code).eq(
            "patient_id", patient_id).eq(
            "check_date", check_date).execute()

        if existing.data:
            rid = existing.data[0]["id"]
            supabase.table("life_function_checks").update(payload).eq(
                "id", rid).execute()
        else:
            res = supabase.table("life_function_checks").insert(payload).execute()
            rid = res.data[0]["id"] if res.data else None

        return jsonify({"status": "success", "id": rid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/life_check_history')
@login_required
def api_life_check_history():
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        patient_id = str(request.args.get("patient_id", "")).strip()
        if not patient_id:
            return jsonify({"checks": []})

        res = supabase.table("life_function_checks").select("*").eq(
            "facility_code", f_code).eq(
            "patient_id", patient_id).order(
            "check_date", desc=True).execute()

        return jsonify({"checks": res.data or []})
    except Exception as e:
        return jsonify({"checks": [], "error": str(e)}), 500
@app.route('/api/delete_life_check', methods=['POST'])  # life-check-delete-api
@login_required
def api_delete_life_check():
    """生活機能チェックを削除（本人または管理者のみ）"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        rid = str(data.get("id", "")).strip()
        if not rid:
            return jsonify({"status": "error", "message": "id ga hitsuyou desu"}), 400
        rec = supabase.table("life_function_checks").select("id,staff_name").eq(
            "id", rid).eq("facility_code", f_code).execute()
        if not rec.data:
            return jsonify({"status": "error", "message": "kiroku ga mitsukarimasen"}), 404
        is_owner = (rec.data[0].get("staff_name") == my_name)
        is_admin = is_admin_user(supabase, f_code, my_name)
        if not (is_owner or is_admin):
            return jsonify({"status": "error", "message": "削除権限がありません"}), 403
        supabase.table("life_function_checks").delete().eq("id", rid).eq(
            "facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# lifecheck-alert-api-v1: 生活機能チェック 実施忘れアラート + 担当者アサイン
def _life_add_months(ym_date, months):
    """date に months か月を加算した date を返す（日は1固定で月計算）"""
    from datetime import date as _date
    y = ym_date.year + (ym_date.month - 1 + months) // 12
    m = (ym_date.month - 1 + months) % 12 + 1
    return _date(y, m, 1)


def _life_check_target_ym(latest_date_str, today_date):
    """
    最新check_date(文字列 'YYYY-MM-DD' or None) と当日 today_date(date) から
    対象月 'YYYY-MM' を返す。対象外なら None。
      - 未評価(None/空) -> 当月（即対象）
      - 評価済み -> 最新+3か月の月初が当月の月初以前なら、その月を対象月として返す
    """
    from datetime import date as _date
    cur_first = _date(today_date.year, today_date.month, 1)
    if not latest_date_str:
        return "%04d-%02d" % (cur_first.year, cur_first.month)
    try:
        parts = str(latest_date_str)[:10].split("-")
        ld = _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return "%04d-%02d" % (cur_first.year, cur_first.month)
    due_first = _life_add_months(ld, 3)
    due_first = _date(due_first.year, due_first.month, 1)
    if due_first <= cur_first:
        return "%04d-%02d" % (cur_first.year, cur_first.month)
    return None


@app.route('/api/life_check_alerts')  # lifecheck-alert-api-v1
@login_required
def api_life_check_alerts():
    """在籍利用者の生活機能チェック実施忘れ対象者を算出して返す（動的補充あり）。"""
    try:
        from datetime import date as _date
        f_code = session["f_code"]
        supabase = get_supabase()
        today_s = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
        try:
            tp = today_s.split("-")
            today_d = _date(int(tp[0]), int(tp[1]), int(tp[2]))
        except Exception:
            today_d = datetime.now(tokyo_tz).date()
        cur_ym = "%04d-%02d" % (today_d.year, today_d.month)

        patients = get_patients(supabase, f_code)
        # 在籍フィルタ: 中止でない、かつ discontinued_date が無い or 今日以降
        active = []
        for p in patients:
            if p.get("is_discontinued"):
                continue
            dd = (p.get("discontinued_date") or "").strip()
            if dd and dd < today_s:
                continue
            if p.get("id"):
                active.append(p)

        pid_list = [str(p["id"]) for p in active]
        latest_map = {}  # patient_id -> 最新 check_date 'YYYY-MM-DD'
        if pid_list:
            lc = supabase.table("life_function_checks").select(
                "patient_id,check_date").eq("facility_code", f_code).in_(
                "patient_id", pid_list).execute()
            for r in (lc.data or []):
                pid = str(r.get("patient_id") or "")
                cd = str(r.get("check_date") or "")[:10]
                if not pid or not cd:
                    continue
                if pid not in latest_map or cd > latest_map[pid]:
                    latest_map[pid] = cd

        # 対象者算出 + 動的補充（当月対象のみ）
        targets = {}  # pid -> {target_ym, last_check_date, never}
        for p in active:
            pid = str(p["id"])
            latest = latest_map.get(pid)
            tym = _life_check_target_ym(latest, today_d)
            if tym is None:
                continue
            # 当月分のみアラート対象として扱う（過去未実施は当月に集約）
            targets[pid] = {
                "target_ym": cur_ym,
                "last_check_date": latest or "",
                "never": latest is None,
                "user_name": p.get("user_name") or "",
            }

        # 動的補充: 当月 target_ym の行が無ければ unassigned で insert
        if targets:
            existing = supabase.table("life_check_appointments").select(
                "patient_id,target_ym,status,assignee_name,scheduled_date,"
                "calendar_event_id").eq("facility_code", f_code).eq(
                "target_ym", cur_ym).execute()
            existing_map = {}
            for r in (existing.data or []):
                existing_map[str(r.get("patient_id"))] = r
            for pid, info in targets.items():
                if pid in existing_map:
                    continue
                try:
                    supabase.table("life_check_appointments").insert({
                        "facility_code": f_code,
                        "patient_id": pid,
                        "target_ym": cur_ym,
                        "status": "unassigned",
                    }).execute()
                except Exception as _ins_err:
                    # UNIQUE 競合などは無視（既に補充済み）
                    print("[life_alert] insert skip: %s" % _ins_err, flush=True)
            # 補充後に再取得（calendar_event_id 等の最新状態を得る）
            existing = supabase.table("life_check_appointments").select(
                "patient_id,target_ym,status,assignee_name,scheduled_date,"
                "calendar_event_id").eq("facility_code", f_code).eq(
                "target_ym", cur_ym).execute()
            existing_map = {}
            for r in (existing.data or []):
                existing_map[str(r.get("patient_id"))] = r
        else:
            existing_map = {}

        # lifecheck-alert-orphan-v3: scheduled行のカレンダーイベント実在確認。
        # 予定が削除されていたら unassigned に戻して再度登録を促す。
        sched_eids = []
        eid_to_pid = {}
        for pid, row in existing_map.items():
            if row.get("status") == "scheduled" and row.get("calendar_event_id"):
                eid = row.get("calendar_event_id")
                sched_eids.append(eid)
                eid_to_pid[str(eid)] = pid
        if sched_eids:
            alive = set()
            try:
                ev = supabase.table("calendar_events").select("id").eq(
                    "facility_code", f_code).in_("id", sched_eids).execute()
                for r in (ev.data or []):
                    alive.add(str(r.get("id")))
            except Exception as _ev_err:
                print("[life_alert] event check failed: %s" % _ev_err, flush=True)
                alive = None  # 確認失敗時は現状維持（誤って戻さない）
            if alive is not None:
                for eid_str, pid in eid_to_pid.items():
                    if eid_str not in alive:
                        # 予定が消えている -> unassigned に戻す
                        try:
                            supabase.table("life_check_appointments").update({
                                "status": "unassigned",
                                "assignee_name": None,
                                "scheduled_date": None,
                                "calendar_event_id": None,
                                "updated_at": datetime.now(tokyo_tz).isoformat(),
                            }).eq("facility_code", f_code).eq(
                                "patient_id", pid).eq("target_ym", cur_ym).execute()
                        except Exception as _rb_err:
                            print("[life_alert] rollback failed: %s" % _rb_err, flush=True)
                        # メモリ上の existing_map も更新
                        if pid in existing_map:
                            existing_map[pid]["status"] = "unassigned"
                            existing_map[pid]["assignee_name"] = None
                            existing_map[pid]["scheduled_date"] = None
                            existing_map[pid]["calendar_event_id"] = None

        alerts = []
        pending = 0
        for pid, info in targets.items():
            row = existing_map.get(pid, {})
            status = row.get("status") or "unassigned"
            # done判定: 最新check_dateの月が当月以降なら実施済み扱い
            last = info["last_check_date"]
            is_done = bool(last and last[:7] >= cur_ym)
            if is_done:
                status = "done"
            if status not in ("done", "scheduled"):  # lifecheck-alert-fix-v2
                pending += 1
            alerts.append({
                "patient_id": pid,
                "user_name": info["user_name"],
                "target_ym": cur_ym,
                "status": status,
                "assignee_name": row.get("assignee_name") or "",
                "scheduled_date": row.get("scheduled_date") or "",
                "calendar_event_id": row.get("calendar_event_id"),
                "never_checked": info["never"],
                "last_check_date": last,
            })
        # 名前順
        alerts.sort(key=lambda a: a.get("user_name") or "")
        return jsonify({
            "alerts": alerts,
            "target_ym": cur_ym,
            "count": pending,
        })
    except Exception as e:
        print("[life_alert] error: %s" % e, flush=True)
        return jsonify({"alerts": [], "count": 0, "error": str(e)}), 200


@app.route('/api/life_check_assign', methods=['POST'])  # lifecheck-alert-api-v1
@login_required
def api_life_check_assign():
    """担当者+予定日を登録し scheduled に更新、カレンダーへ相乗りイベントを作成する。"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        patient_id = str(data.get("patient_id", "")).strip()
        target_ym = str(data.get("target_ym", "")).strip()
        assignee = str(data.get("assignee_name", "")).strip()
        sched = str(data.get("scheduled_date", "")).strip()
        if not patient_id or not target_ym or not assignee or not sched:
            return jsonify({"status": "error",
                            "message": "patient_id, target_ym, assignee_name, scheduled_date ha hissu desu"}), 400

        # 利用者名の解決（カレンダーtitle用）
        user_name = ""
        try:
            pp = supabase.table("patient_profiles").select("user_name").eq(
                "facility_code", f_code).eq("id", patient_id).execute()
            if pp.data:
                user_name = pp.data[0].get("user_name") or ""
        except Exception:
            pass

        # appointments 行を確保（無ければ作る） lifecheck-alert-fix-v2
        existing = supabase.table("life_check_appointments").select(
            "id,calendar_event_id").eq(
            "facility_code", f_code).eq("patient_id", patient_id).eq(
            "target_ym", target_ym).execute()
        prev_event_id = None
        if existing.data:
            appt_id = existing.data[0]["id"]
            prev_event_id = existing.data[0].get("calendar_event_id")
        else:
            ins = supabase.table("life_check_appointments").insert({
                "facility_code": f_code,
                "patient_id": patient_id,
                "target_ym": target_ym,
                "status": "unassigned",
            }).execute()
            appt_id = ins.data[0]["id"] if ins.data else None

        # カレンダーへ相乗りイベント作成（休み連絡と同じ作法）
        eid = None
        try:
            cal_id = _get_or_create_system_calendar(supabase, f_code, my_name)
            if cal_id:
                title = "在宅アセスメント " + (user_name + "様" if user_name else "")
                memo = "生活機能チェック 担当:" + assignee
                cal_payload = {
                    "facility_code": f_code,
                    "calendar_id": cal_id,
                    "title": title.strip(),
                    "event_date": sched,
                    "end_date": sched,
                    "all_day": True,
                    "color": "#1976d2",
                    "memo": memo,
                    "created_by": my_name,
                }
                if prev_event_id:  # lifecheck-alert-fix-v2: 既存イベントを更新（孤児防止）
                    upd_payload = {
                        "title": title.strip(),
                        "event_date": sched,
                        "end_date": sched,
                        "memo": memo,
                    }
                    supabase.table("calendar_events").update(upd_payload).eq(
                        "id", prev_event_id).eq("facility_code", f_code).execute()
                    eid = prev_event_id
                else:
                    cal_res = supabase.table("calendar_events").insert(cal_payload).execute()
                    if cal_res.data:
                        eid = cal_res.data[0]["id"]
                    else:
                        fr = supabase.table("calendar_events").select("id").eq(
                            "facility_code", f_code).eq("calendar_id", cal_id).eq(
                            "event_date", sched).eq("created_by", my_name).order(
                            "created_at", desc=True).limit(1).execute()
                        if fr.data:
                            eid = fr.data[0]["id"]
        except Exception as _cal_err:
            print("[life_assign] calendar sync failed: %s" % _cal_err, flush=True)

        # appointments を scheduled に更新
        upd = {
            "status": "scheduled",
            "assignee_name": assignee,
            "scheduled_date": sched,
            "updated_at": datetime.now(tokyo_tz).isoformat(),
        }
        if eid is not None:
            upd["calendar_event_id"] = eid
        if appt_id is not None:
            supabase.table("life_check_appointments").update(upd).eq(
                "id", appt_id).execute()
        else:
            supabase.table("life_check_appointments").update(upd).eq(
                "facility_code", f_code).eq("patient_id", patient_id).eq(
                "target_ym", target_ym).execute()

        return jsonify({"status": "success", "calendar_event_id": eid})
    except Exception as e:
        print("[life_assign] error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# life-assist-api: 生活機能チェック AI相談（補助型）
_LIFE_ASSIST_ADL = {
    "adl_eating":   ("食事",   [(10, "自立"), (5, "部分介助"), (0, "全介助")]),
    "adl_transfer": ("椅子とベッド間の移乗", [(15, "自立"), (10, "軽度の部分介助・監視"), (5, "座位可・ほぼ全介助"), (0, "全介助・不可")]),
    "adl_grooming": ("整容",   [(5, "自立"), (0, "部分介助・不可")]),
    "adl_toilet":   ("トイレ動作", [(10, "自立"), (5, "部分介助"), (0, "全介助・不可")]),
    "adl_bathing":  ("入浴",   [(5, "自立"), (0, "部分介助・不可")]),
    "adl_walking":  ("移動",   [(15, "45m以上歩行"), (10, "45m以上介助歩行"), (5, "車椅子で45m以上"), (0, "上記以外")]),
    "adl_stairs":   ("階段昃降", [(10, "自立"), (5, "介助・監視"), (0, "不能")]),
    "adl_dressing": ("更衣",   [(10, "自立"), (5, "部分介助"), (0, "上記以外")]),
    "adl_bowel":    ("排便コントロール", [(10, "失禁なし"), (5, "ときに失禁"), (0, "上記以外")]),
    "adl_bladder":  ("排尿コントロール", [(10, "失禁なし"), (5, "ときに失禁"), (0, "上記以外")]),
}
_LIFE_ASSIST_LEVEL_ITEMS = {
    "adl_wheelchair": "車椅子操作", "iadl_cooking": "調理", "iadl_laundry": "洗濯",
    "iadl_cleaning": "掃除", "basic_rollover": "寝返り", "basic_situp": "起き上がり",
    "basic_sitting": "座位", "basic_standup": "立ち上がり", "basic_standing": "立位",
}
_LIFE_ASSIST_4LEVEL = [("independent", "自立"), ("watch", "見守り"), ("partial", "一部介助"), ("full", "全介助")]

@app.route('/api/life_assist', methods=['POST'])  # life-assist-api
@login_required
def api_life_assist():
    """生活機能チェックの項目判定をAIが補助（最終判定は職員）"""
    try:
        import anthropic as _anthropic, json as _json, re as _re
        data = request.json or {}
        item_key = str(data.get("item_key", "")).strip()
        situation = str(data.get("situation", "")).strip()
        user_name = str(data.get("user_name", "")).strip()
        if not item_key:
            return jsonify({"status": "error", "message": "item_key ga hitsuyou desu"}), 400
        if not situation:
            return jsonify({"status": "error", "message": "状況を入力してください"}), 400

        if item_key in _LIFE_ASSIST_ADL:
            label, opts = _LIFE_ASSIST_ADL[item_key]
            cand_lines = "\n".join(["  - %d点: %s" % (s, t) for s, t in opts])
            cand_kind = "Barthel区分（点数）"
            cand_json_hint = '"candidate_levels": [{"score": 10, "label": "自立", "reason": "..."}]'
        elif item_key in _LIFE_ASSIST_LEVEL_ITEMS:
            label = _LIFE_ASSIST_LEVEL_ITEMS[item_key]
            cand_lines = "\n".join(["  - %s: %s" % (lv, t) for lv, t in _LIFE_ASSIST_4LEVEL])
            cand_kind = "4段階"
            cand_json_hint = '"candidate_levels": [{"level": "partial", "label": "一部介助", "reason": "..."}]'
        else:
            return jsonify({"status": "error", "message": "unknown item_key"}), 400

        prompt = """あなたは介護現場のベテラン職員で、生活機能チェックシート（様式3-2）の評価を補助します。
あなたの役割は、職員が最終判定をするための論点整理・根拠・候補提示・記載案作成です。**最終的な評価の決定は職員が行います。あなたは断定せず、候補と根拠を示してください。**

【評価項目】%s（%s）
【選択肢】
%s

【職員が観察した状況】
%s

【出力形式】JSONのみ。マークダウン不要。以下のキーを含める：
{
  "basis": "選択肢の基準に照らした、観察事実の整理（事実のみ、推測は避ける）",
  "interpretation": "論点整理・解釈（どこが判断の分かれ目か）",
  %s,
  "check_points": ["追加で確認すべきポイントを文字列で複数"],
  "record_draft": "状況・生活課題欄にそのまま記載できる案（丁寧語・1～2文）"
}
candidate_levels は複数可。可能性の高い順に並べ、それぞれ reason に根拠を簡潔に。""" % (
            label, cand_kind, cand_lines, situation, cand_json_hint)

        client = _anthropic.Anthropic()
        message = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=1500,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = message.content[0].text.strip()
        raw = _re.sub(r'^```[a-zA-Z]*\n?', '', raw).strip()
        raw = _re.sub(r'```$', '', raw).strip()
        result = _json.loads(raw)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500




# ============================================================
# Session 49: 施設情報（住所・電話・ロゴ）取得/保存
# 報告書印刷の施設欄に自動反映される
# ============================================================
@app.route('/api/admin/facility_info')
@login_required
def api_admin_facility_info():
    """現在の施設情報を返す（管理者MENU施設情報セクション用）"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        res = supabase.table("facilities").select(
            "facility_name, facility_postal_code, facility_address, "
            "facility_tel, facility_fax, facility_logo_url"
        ).eq("facility_code", f_code).execute()

        if res.data:
            d = res.data[0]
            return jsonify({
                "status": "success",
                "facility_name": d.get("facility_name") or "",
                "facility_postal_code": d.get("facility_postal_code") or "",
                "facility_address": d.get("facility_address") or "",
                "facility_tel": d.get("facility_tel") or "",
                "facility_fax": d.get("facility_fax") or "",
                "facility_logo_url": d.get("facility_logo_url") or "",
            })
        return jsonify({"status": "success",
                        "facility_name": "", "facility_postal_code": "",
                        "facility_address": "", "facility_tel": "",
                        "facility_fax": "", "facility_logo_url": ""})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/save_facility_info', methods=['POST'])
@login_required
def api_admin_save_facility_info():
    """施設情報を保存（住所・電話・FAX・郵便番号・ロゴ）。
    施設名は変更しない（登録済みのものを使用）。"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        data = request.json or {}

        # ロゴはBase64データURL想定。サイズ上限を設けて肥大を防ぐ
        logo = data.get("facility_logo_url", "")
        if logo and len(logo) > 1_500_000:  # 約1.5MB（Base64文字列長）
            return jsonify({"status": "error",
                            "message": "ロゴ画像が大きすぎます（2MB以下の画像にしてください）"}), 400

        payload = {
            "facility_postal_code": str(data.get("facility_postal_code", "")).strip(),
            "facility_address": str(data.get("facility_address", "")).strip(),
            "facility_tel": str(data.get("facility_tel", "")).strip(),
            "facility_fax": str(data.get("facility_fax", "")).strip(),
        }
        # ロゴは送られてきた時だけ更新（空送信で既存ロゴを消さない配慮）
        if "facility_logo_url" in data:
            payload["facility_logo_url"] = logo

        supabase.table("facilities").update(payload).eq(
            "facility_code", f_code).execute()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================
# Session 49: モニタリング報告書 印刷用データ集約API（ステップA）
# 利用者・年月を指定し、報告書1枚に必要な全データをまとめて返す。
# 既存APIのロジックを踏襲。既存ルートは一切変更しない。
# ============================================================
@app.route('/api/monitoring_report_data')
@login_required
def api_monitoring_report_data():
    """報告書印刷用：利用者・ケアマネ・評価・モニタリング本文・
    体力測定・体重・施設情報をまとめて返す"""
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        user_name = (request.args.get("user_name") or "").strip()
        year_month = (request.args.get("year_month") or "").strip()
        if not user_name or not year_month:
            return jsonify({"status": "error",
                            "message": "user_name と year_month が必要です"}), 400

        result = {"status": "success"}

        # ---- 1. 利用者情報＋ふりがな（get_patients から該当者を抽出） ----
        patient = None
        try:
            for p in get_patients(supabase, f_code):
                if p.get("user_name") == user_name or p.get("value") == user_name:
                    patient = p
                    break
        except Exception:
            patient = None
        result["patient"] = patient or {}

        # ---- 2. ケアマネ情報（patient_profiles） ----
        caremanager = {}
        try:
            prof = supabase.table("patient_profiles").select(
                "user_name, user_name_kana, support_office, "
                "care_manager_name, delegate_office, care_level"
            ).eq("facility_code", f_code).eq("user_name", user_name).execute()
            if prof.data:
                caremanager = prof.data[0]
        except Exception:
            caremanager = {}
        result["caremanager"] = caremanager

        # ---- 3. 評価6項目＋目標達成状況（patient_evaluations 当月） ----
        evaluation = {}
        try:
            ev = supabase.table("patient_evaluations").select("*").eq(
                "facility_code", f_code).eq(
                "user_name", user_name).eq(
                "year_month", year_month).execute()
            if ev.data:
                evaluation = ev.data[0]
        except Exception:
            evaluation = {}
        result["evaluation"] = evaluation

        # ---- 4. モニタリング本文（monitoring_reports 当月・最新1件） ----
        monitoring = {}
        try:
            mr = supabase.table("monitoring_reports").select("*").eq(
                "facility_code", f_code).eq(
                "user_name", user_name).eq(
                "year_month", year_month).order(
                "id", desc=True).limit(1).execute()
            if mr.data:
                monitoring = mr.data[0]
        except Exception:
            monitoring = {}
        result["monitoring"] = monitoring

        # ---- 5. 体力測定の推移（fitness_tests 直近6ヶ月） ----
        fitness = []
        try:
            ft = supabase.table("fitness_tests").select("*").eq(
                "facility_code", f_code).eq(
                "user_name", user_name).order(
                "measured_date", desc=True).limit(6).execute()
            if ft.data:
                fitness = list(reversed(ft.data))  # 古い順に
        except Exception:
            fitness = []
        result["fitness"] = fitness

        # ---- 6. 体重の推移（body_weights 直近6ヶ月） ----
        weights = []
        try:
            bw = supabase.table("body_weights").select("*").eq(
                "facility_code", f_code).eq(
                "user_name", user_name).order(
                "measured_date", desc=True).limit(6).execute()
            if bw.data:
                weights = list(reversed(bw.data))
        except Exception:
            weights = []
        result["weights"] = weights

        # ---- 7. 施設情報（facilities） ----
        facility = {}
        try:
            fac = supabase.table("facilities").select(
                "facility_name, facility_postal_code, facility_address, "
                "facility_tel, facility_fax, facility_logo_url"
            ).eq("facility_code", f_code).execute()
            if fac.data:
                facility = fac.data[0]
        except Exception:
            facility = {}
        result["facility"] = facility

        # ---- 8. 職員リスト（作成者プルダウン用） ----
        staff_list = []
        try:
            st = supabase.table("staffs").select("staff_name").eq(
                "facility_code", f_code).eq("is_active", True).execute()
            if st.data:
                staff_list = [s["staff_name"] for s in st.data
                              if s.get("staff_name")]
        except Exception:
            staff_list = []
        result["staff_list"] = staff_list

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/vital_bulk_temp', methods=['POST'])
@login_required
def api_vital_bulk_temp():
    """体温一括入力: 音声をAIで解析し、全員分の体温を名前で振り分けて返す"""
    try:
        from utils import get_generative_model
        f_code = session["f_code"]
        my_name = session["my_name"]
        audio = request.files.get('audio')
        if not audio:
            return jsonify({"status": "error", "message": "音声なし"})
        filename = (audio.filename or '').lower()
        audio_bytes = audio.read()
        if not audio_bytes:
            return jsonify({"status": "error", "message": "音声データが空です"})
        ext_mime = {
            '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
            '.wav': 'audio/wav',  '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',  '.webm': 'audio/webm',
            '.mp4': 'audio/mp4',
        }
        mime = next((v for k, v in ext_mime.items() if filename.endswith(k)), 'audio/webm')
        # 利用者名リストをリクエストから取得
        import json as _json
        patients_json = request.form.get('patients', '[]')
        patients = _json.loads(patients_json)
        patient_names = [p['user_name'] for p in patients if p.get('user_name')]
        # 読み仮名(user_kana)入りの名簿を作る。当て字対策の要。
        names_str = '、'.join(
            (f"{p['user_name']}（{p.get('user_kana')}）" if p.get('user_kana') else p['user_name'])
            for p in patients if p.get('user_name')
        )
        prompt = f"""これは介護施設のスタッフが利用者の体温をまとめて報告している音声です。
登録利用者名一覧: {names_str}\n（）内は名前の読み仮名です。当て字や難読名でも、必ず読み仮名で本人を判断してください。\n例:「倍子」の読みが「ますこ」の場合、音声「ますこさん」はこの人です。

音声から各利用者の体温を抽出してください。

【厳守ルール】
- 「登録利用者名一覧」にない名前は絶対に使わない（周囲の音やテレビの声は無視する）
- 登録利用者名一覧の中に明確に名前が呼ばれた人のみ体温を記録する
- 名前が呼ばれていない利用者は必ずtemperature=null（絶対に推測しない）
- 聴き取れない・不明確な名前はnull（似ている名前に当てはめない）
- 体温は小数点1桁（例:36.5）
- 数字の読み（「さんじゅうろくてんご」=36.5など）を正しく変換する
- resultsには登録利用者名一覧の全員を含める（言及なし=null）
- 【最重要】音声が無音・雑音のみ・聞き取れない場合は、絶対に内容を推測・創作しないこと。その場合は transcript を空文字 "" にし、results は全員 temperature=null にすること。聞こえないのにもっともらしい会話や数値を作ってはいけない。

JSON形式のみで返してください（説明文・コードブロック・マークダウン禁止）:
{{
  "transcript": "発話の全文書き起こし",
  "results": [
    {{"user_name": "登録利用者名をそのまま使用", "temperature": 小数 or null}},
    ...
  ]
}}"""
        model = get_generative_model()
        resp = model.generate_content([{"mime_type": mime, "data": audio_bytes}, prompt])
        import re as _re
        m = _re.search(r'\{.*\}', resp.text.strip(), _re.DOTALL)
        if not m:
            return jsonify({"status": "error", "message": "音声を認識できませんでした。もう一度お試しください。"})
        result = _json.loads(m.group())
        # AIが返した {氏名候補, 体温} を、読み仮名ベースで本人へ再照合する。
        ai_results = result.get('results', [])
        # 体温が取れているAIエントリのみ対象(言及なし=null は捨てる)
        ai_entries = [
            {'name': (r.get('user_name') or '').strip(), 'temp': r.get('temperature')}
            for r in ai_results
            if (r.get('user_name') or '').strip() and r.get('temperature') is not None
        ]
        # 無音・捏造の検出: 文字起こしが実質空で、有効な体温エントリも無い場合は
        # 「聞き取れなかった」とみなし、何も登録せず明示メッセージを返す。
        _transcript = (result.get('transcript') or '').strip()
        if not _transcript and len(ai_entries) == 0:
            return jsonify({
                "status": "error",
                "message": "音声を検出できませんでした。もう一度、利用者名と体温をはっきりお話しください。"
            })
        # 各 patient に対し、AIエントリ側から最良の照合を探す。
        # confidence: high=自動採用可 / mid=要確認(職員選択) / none=対象外
        matched = []
        used_entry_idx = set()
        for p in patients:
            pname = p.get('user_name', '')
            pid = p.get('patient_id') or p.get('id')
            best = (None, 'none', None)  # (temp, confidence, entry_idx)
            for ei, e in enumerate(ai_entries):
                cand, conf = _voice_match_temp(e['name'], [p])
                if cand is None:
                    continue
                # confidence の優先度
                rank = {'high': 2, 'mid': 1, 'none': 0}
                if rank[conf] > rank[best[1]]:
                    best = (e['temp'], conf, ei)
            entry = {
                'patient_id': pid,
                'user_name': pname,
                'temperature': best[0],
                'confidence': best[1],
            }
            if best[2] is not None:
                used_entry_idx.add(best[2])
            matched.append(entry)
        # どの利用者にも結びつかなかったAIエントリ(=該当なし)を赤として可視化
        unmatched = []
        for ei, e in enumerate(ai_entries):
            if ei not in used_entry_idx:
                unmatched.append({'spoken_name': e['name'], 'temperature': e['temp']})
        return jsonify({
            "status": "success",
            "transcript": result.get('transcript', ''),
            "results": matched,
            "unmatched": unmatched
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==================================================
# LINE Messaging API + Stripe サブスク
# ==================================================
import stripe
import hashlib
import hmac
import base64
import json as _json

def get_line_headers():
    token = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

def line_send_message(user_id, messages):
    """LINEユーザーにメッセージ送信"""
    import urllib.request
    payload = _json.dumps({
        "to": user_id,
        "messages": messages
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers=get_line_headers(),
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status == 200
    except Exception as e:
        print(f"[LINE] send error: {e}", flush=True)
        return False

# --- LINE Webhook ---
@app.route('/api/line/webhook', methods=['POST'])
def line_webhook():
    """LINEからのWebhook受信（管理者の返信で承認処理）"""
    channel_secret = get_secret("LINE_CHANNEL_SECRET")
    body = request.get_data(as_text=True)
    sig = request.headers.get("X-Line-Signature", "")

    # 署名検証
    hash_ = hmac.new(channel_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(hash_).decode("utf-8")
    if not hmac.compare_digest(expected, sig):
        return jsonify({"error": "invalid signature"}), 400

    data = request.get_json()
    for event in data.get("events", []):
        if event.get("type") == "message":
            msg = event.get("message", {}).get("text", "").strip()
            reply_token = event.get("replyToken")
            # 将来的な承認処理をここに追加
            print(f"[LINE webhook] message: {msg}", flush=True)

    return jsonify({"status": "ok"}), 200

# --- LINE 招待メッセージ送信 ---
@app.route('/api/line/send_invite', methods=['POST'])
def line_send_invite():
    """施設管理者・スタッフにLINEで招待リンクを送る"""
    f_code = session.get("facility_code")
    if not f_code:
        return jsonify({"error": "not logged in"}), 401

    data = request.get_json()
    invite_url = data.get("invite_url", "")
    target_name = data.get("target_name", "")
    role = data.get("role", "staff")  # "admin" or "staff"

    admin_line_id = get_secret("LINE_ADMIN_USER_ID")
    if not admin_line_id:
        return jsonify({"error": "LINE not configured"}), 500

    if role == "admin":
        text = "\n".join([
            "【TASUKARU】新しい施設管理者の招待",
            "",
            target_name + " 様",
            "",
            "以下のURLからTASUKARUにアクセスしてアカウントを作成してください。",
            "",
            invite_url,
            "",
            "施設コード: " + f_code,
        ])
    else:
        text = "\n".join([
            "【TASUKARU】スタッフ招待",
            "",
            target_name + " 様",
            "",
            "以下のURLからTASUKARUにログインしてください。",
            "",
            invite_url,
            "",
            "施設コード: " + f_code,
        ])

    ok = line_send_message(admin_line_id, [{"type": "text", "text": text}])
    if ok:
        return jsonify({"status": "sent"})
    else:
        return jsonify({"error": "send failed"}), 500

# --- LINE 開発者通知 ---
def line_notify_admin(message):
    """開発者（岸本さん）のLINEに通知を送る"""
    admin_line_id = get_secret("LINE_ADMIN_USER_ID")
    if not admin_line_id:
        print("[LINE] LINE_ADMIN_USER_ID not set", flush=True)
        return False
    return line_send_message(admin_line_id, [{"type": "text", "text": message}])

@app.route('/pricing')
@login_required
def pricing():
    if not session.get('f_code'):
        return redirect(url_for('login'))
    f_code = session.get('f_code', '')
    current_plan = 'free'
    trial_ends_at = None
    try:
        supabase = get_supabase()
        res = supabase.table('facilities').select('plan,trial_ends_at,expires_at').eq('facility_code', f_code).execute()
        if res.data:
            current_plan = res.data[0].get('plan', 'free')
            trial_ends_at = res.data[0].get('trial_ends_at')
    except: pass
    return render_template('pricing.html',
        current_plan=current_plan,
        trial_ends_at=trial_ends_at,
        f_code=f_code,
        my_name=session.get('my_name', ''),
    )

# --- Stripe 決済セッション作成 ---
@app.route('/api/stripe/create_checkout', methods=['POST'])
def stripe_create_checkout():
    f_code = session.get("f_code")
    if not f_code:
        return jsonify({"error": "not logged in"}), 401
    stripe.api_key = get_secret("STRIPE_SECRET_KEY")
    data = request.get_json()
    plan = (data.get("plan") or "starter").lower()
    term = (data.get("term") or "monthly").lower()
    base_url = request.host_url.rstrip("/")

    # --- プラン妥当性チェック ---
    if plan not in ("starter", "standard", "pro"):
        return jsonify({"error": "invalid plan: " + plan}), 400

    # --- term → (環境変数サフィックス, 決済モード) の明示マッピング ---
    # _M系=毎月課金(subscription) / _L系=一括(payment)
    TERM_MAP = {
        "monthly": ("M",    "subscription"),
        "1y_m":    ("1Y_M", "subscription"),
        "1y_l":    ("1Y_L", "payment"),
        "2y_m":    ("2Y_M", "subscription"),
        "2y_l":    ("2Y_L", "payment"),
        "3y_m":    ("3Y_M", "subscription"),
        "3y_l":    ("3Y_L", "payment"),
    }
    if term not in TERM_MAP:
        return jsonify({"error": "invalid term: " + term}), 400
    suffix, checkout_mode = TERM_MAP[term]

    env_key = "STRIPE_PRICE_" + plan.upper() + "_" + suffix
    price_id = get_secret(env_key)
    if not price_id:
        return jsonify({"error": "price not configured: " + env_key}), 400

    # --- 任意割引クーポンの自動適用判定 ---
    # facilities.discount_rate（0.5/0.3/0.2）と discount_until（期限・空なら無期限）を見る
    discounts = None
    applied_discount_rate = 0
    try:
        supabase = get_supabase()
        fres = supabase.table("facilities").select(
            "discount_rate,discount_until"
        ).eq("facility_code", f_code).execute()
        if fres.data:
            d_rate = fres.data[0].get("discount_rate") or 0
            d_until = fres.data[0].get("discount_until")
            in_period = True
            if d_until not in (None, "", "None"):
                try:
                    du = datetime.fromisoformat(str(d_until).replace("Z", "+00:00"))
                    in_period = du >= datetime.now(timezone.utc)
                except (ValueError, TypeError):
                    in_period = True  # 日付が壊れていても割引は活かす（安全側はユーザー利益）
            if d_rate and in_period:
                coupon_map = {0.5: "STRIPE_COUPON_50", 0.3: "STRIPE_COUPON_30", 0.2: "STRIPE_COUPON_20"}
                coupon_env = coupon_map.get(round(float(d_rate), 2))
                if coupon_env:
                    coupon_id = get_secret(coupon_env)
                    if coupon_id:
                        discounts = [{"coupon": coupon_id}]
                        applied_discount_rate = d_rate
                    else:
                        print("[Stripe] coupon env not set: " + coupon_env, flush=True)
                else:
                    # 想定外の割引率は誤割引防止のため適用しない
                    print("[Stripe] unsupported discount_rate (skipped): " + str(d_rate), flush=True)
    except Exception as e:
        print("[Stripe] discount lookup error: " + str(e), flush=True)

    try:
        params = dict(
            mode=checkout_mode,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=base_url + "/pricing?stripe=success",
            cancel_url=base_url + "/pricing?stripe=cancel",
            metadata={
                "facility_code": f_code,
                "plan": plan,
                "term": term,
                "discount_rate": str(applied_discount_rate),
            },
            locale="ja",
        )
        if discounts:
            params["discounts"] = discounts
        checkout = stripe.checkout.Session.create(**params)
        return jsonify({"url": checkout.url})
    except Exception as e:
        print("[Stripe] checkout error: " + str(e), flush=True)
        return jsonify({"error": str(e)}), 500

# --- Stripe Webhook ---
@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Stripe決済完了時のWebhook → 自動有効化"""
    stripe.api_key = get_secret("STRIPE_SECRET_KEY")
    webhook_secret = get_secret("STRIPE_WEBHOOK_SECRET")
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
    except Exception as e:
        print(f"[Stripe webhook] verify error: {e}", flush=True)
        return jsonify({"error": "invalid"}), 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        # Stripeオブジェクトはdict()変換でKeyErrorになることがあるため、
        # to_dict()→JSON経由で確実にプレーンな辞書へ変換する
        def _to_plain_dict(obj):
            try:
                return json.loads(json.dumps(obj.to_dict()))
            except Exception:
                pass
            try:
                return json.loads(json.dumps(dict(obj)))
            except Exception:
                pass
            return {}
        session_data = _to_plain_dict(session_obj)
        meta = session_data.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        f_code = meta.get("facility_code")
        plan = meta.get("plan", "starter")
        term = meta.get("term", "monthly")
        try:
            discount_rate = float(meta.get("discount_rate", 0) or 0)
        except (ValueError, TypeError):
            discount_rate = 0
        if f_code:
            try:
                supabase = get_supabase()
                from datetime import datetime, timedelta, timezone
                # 契約期間から有効期限を算出（月払い単月=30日、年契約=年数ぶん）
                TERM_DAYS = {
                    "monthly": 30,
                    "1y_m": 365, "1y_l": 365,
                    "2y_m": 730, "2y_l": 730,
                    "3y_m": 1095, "3y_l": 1095,
                }
                days = TERM_DAYS.get(term, 30)
                now = datetime.now(timezone.utc)
                contract_end = now + timedelta(days=days)
                # 契約年数（違約金計算等で参照）
                TERM_YEARS = {"1y_m": 1, "1y_l": 1, "2y_m": 2, "2y_l": 2, "3y_m": 3, "3y_l": 3}
                contract_term_years = TERM_YEARS.get(term, 0)
                payment_type = "lump" if term.endswith("_l") else "monthly"

                update_data = {
                    "is_active": True,
                    "plan": plan,
                    "expires_at": contract_end.isoformat(),
                    "contract_start": now.date().isoformat(),
                    "contract_end": contract_end.date().isoformat(),
                    "contract_term": contract_term_years,
                    "payment_type": payment_type,
                    "stripe_subscription_id": session_data.get("subscription"),
                    "stripe_customer_id": session_data.get("customer"),
                }
                supabase.table("facilities").update(update_data).eq("facility_code", f_code).execute()
                print(f"[Stripe] facility {f_code} activated (plan={plan}, term={term})", flush=True)
                line_notify_admin(
                    "\n".join([
                        "【TASUKARU】新規契約",
                        "施設コード: " + f_code,
                        "プラン: " + plan,
                        "契約: " + term + ("（割引" + str(int(discount_rate*100)) + "%）" if discount_rate else ""),
                        "",
                        "Stripeダッシュボードで確認してください。",
                    ])
                )
            except Exception as e:
                print(f"[Stripe webhook] DB update error: {e}", flush=True)

    elif event["type"] == "customer.subscription.deleted":
        # サブスク解約時
        sub_id = event["data"]["object"]["id"]
        try:
            supabase = get_supabase()
            supabase.table("facilities").update({
                "is_active": False
            }).eq("stripe_subscription_id", sub_id).execute()
            print(f"[Stripe] subscription {sub_id} cancelled", flush=True)
        except Exception as e:
            print(f"[Stripe webhook] cancel error: {e}", flush=True)

    return jsonify({"status": "ok"}), 200



# ============================================================
# 書類出力ページ
# ============================================================
@app.route('/api/check_data_bulk')
@login_required
def api_check_data_bulk():
    """書類出力: 全利用者のデータ充足チェック(モニタリング/訓練記録/体力測定/体重)を一括取得
    判定基準:
      モニタリング : monitoring_reports に当月レコードがある(生成済み)
      訓練記録    : patient_evaluations の changes_by_training と issues_and_causes が両方入力済み
      体力測定    : fitness_tests に3ヶ月以内の記録がある
      体重        : body_weights に当月の記録がある
      全OK        : 上記4項目すべてOK
    """
    import re as _re
    import calendar as _cal
    f_code = session.get("f_code", "")
    if not f_code:
        return jsonify({"status": "error", "message": "auth required"}), 401
    supabase = get_supabase()
    year_month = request.args.get("year_month", "")
    if not _re.match(r"^\d{4}-\d{2}$", year_month):
        return jsonify({"status": "error", "message": "year_monthパラメータ不正 (YYYY-MM)"}), 400
    try:
        y, m = int(year_month[:4]), int(year_month[5:7])
        last_day = _cal.monthrange(y, m)[1]
        ym_start = f"{year_month}-01"
        ym_end = f"{year_month}-{last_day:02d}"

        # --- モニタリング: 当月に monitoring_reports レコードがあるか ---
        mr = supabase.table("monitoring_reports").select("user_name").eq("facility_code", f_code).eq("target_month", year_month).execute()
        mon_set = set(r["user_name"] for r in (mr.data or []))

        # --- 訓練記録: changes_by_training と issues_and_causes が両方入力済み ---
        ev = supabase.table("patient_evaluations").select(
            "user_name, changes_by_training, issues_and_causes"
        ).eq("facility_code", f_code).eq("year_month", year_month).execute()
        eval_set = set(
            r["user_name"] for r in (ev.data or [])
            if (r.get("changes_by_training") or "").strip() and (r.get("issues_and_causes") or "").strip()
        )

        # --- 体力測定: 3ヶ月以内に記録あり ---
        # 3ヶ月前の先頭日を計算
        m3 = m - 3
        y3 = y
        if m3 <= 0:
            m3 += 12
            y3 -= 1
        fit_start = f"{y3}-{m3:02d}-01"
        ft = supabase.table("fitness_tests").select("user_name").eq("facility_code", f_code).gte("measured_date", fit_start).lte("measured_date", ym_end).execute()
        fit_set = set(r["user_name"] for r in (ft.data or []))

        # --- 体重: 当月に記録あり (user_nameで直接検索) ---
        pts = supabase.table("patients").select("user_name").eq("facility_code", f_code).execute()
        all_names = [r["user_name"] for r in (pts.data or [])]
        # 当月の体重記録を user_name で取得
        bw = supabase.table("body_weights").select("user_name").eq("facility_code", f_code).gte("measured_date", ym_start).lte("measured_date", ym_end).execute()
        weight_set = set(r["user_name"] for r in (bw.data or []) if r.get("user_name"))

        # --- 全利用者分をまとめる ---
        data = []
        for name in all_names:
            has_mon = name in mon_set
            has_eval = name in eval_set
            has_fit = name in fit_set
            has_weight = name in weight_set
            data.append({
                "user_name": name,
                "has_monitoring": has_mon,
                "has_evaluation": has_eval,
                "has_fitness": has_fit,
                "has_weight": has_weight,
                "all_ok": has_mon and has_eval and has_fit and has_weight,
            })
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/print_output')
@login_required
def print_output():
    f_code = session.get("f_code", "")
    my_name = session.get("my_name", "")
    is_admin = session.get("is_admin", False)
    supabase = get_supabase()
    patients_list = []
    try:
        res = supabase.table("patient_profiles").select(
            "user_name, user_name_kana, care_manager_name, support_office, care_level, is_discontinued, discontinued_date"
        ).eq("facility_code", f_code).order("user_name_kana").execute()
        if res.data:
            # 利用者選択リストは全員表示(月別の対象外判定は print_preview 側で行う)
            patients_list = res.data
    except Exception:
        pass
    staff_list = []
    try:
        st_res = supabase.table("staffs").select("staff_name").eq("facility_code", f_code).eq("is_active", True).order("staff_name").execute()
        if st_res.data:
            staff_list = [s["staff_name"] for s in st_res.data if s.get("staff_name")]
    except Exception:
        pass
    return render("print_output.html",
        patients=patients_list,
        staff_list=staff_list,
        my_name=my_name,
        is_admin=is_admin,
        f_code=f_code,
    )


# ============================================================
# 印刷プレビューページ
# ============================================================

def _auto_generate_monitoring(supabase, f_code, u_name, year_month, my_name):
    """print_preview用: monitoring_reportsが未生成の場合に自動生成してDBに保存"""
    import threading
    from datetime import datetime as _dt, timedelta as _td
    supabase = get_supabase()
    _monitoring_gen_lock.acquire()
    try:
        from utils import get_generative_model
        import pytz as _pytz
        tokyo_tz2 = _pytz.timezone("Asia/Tokyo")
        y, m = map(int, year_month.split("-"))
        s_date = tokyo_tz2.localize(_dt(y, m, 1))
        e_date = (s_date + _td(days=32)).replace(day=1)

        res = supabase.table("records").select(
            "content, category, staff_name, created_at"
        ).eq("facility_code", f_code).eq("user_name", u_name).gte(
            "created_at", s_date.isoformat()
        ).lt("created_at", e_date.isoformat()).execute()
        records = [r for r in (res.data or [])
                   if r.get("staff_name") not in ("AI統合記録",)
                   and r.get("category") != "休み連絡"]

        if not records:
            return {}

        CATEGORIES = ["心身状況", "食事", "入浴", "排泄", "コミュニケーション", "訓練状況", "ヒヤリハット", "その他"]
        cat_records = {}
        for r in records:
            cat = r.get("category") or "その他"
            cat_records.setdefault(cat, []).append(r["content"])

        model = get_generative_model()
        BASE_PROMPT = (
            "あなたは介護施設のベテラン介護職員です。"
            "以下の介護記録を読み、担当者会議などで他事業所のケアマネジャーに提出するモニタリング報告書として使える文章を生成してください。\n"
            "【ルール】\n"
            "・事実として記録されていること以外は絶対に書かない\n"
            "・記録がない場合は「今月このカテゴリの報告はありませんでした」とだけ返す\n"
            "・対象の利用者様の名前は必要に応じて使ってよいが、毎回主語として繰り返す必要はなく、自然な場合は主語を省いて行動や状態を書く\n"
            "・職員の名前は書かず、必要な場合は「職員」と表記する\n"
            "・この文書は他事業所のケアマネジャーに提出します。対象の利用者様以外の人名（他の利用者・他のご家族など）が記録に出てきても、実名は一切書かず「他の利用者様」と表記する\n"
            "・箇条書きは使わず、ひとつながりの文章で書く\n"
            "・口調は外部のケアマネジャーへの報告文書として適切な丁寧語\n"
        )
        NO_RECORD_MSG = "今月このカテゴリの報告はありませんでした"
        results = {}
        counts = {}
        for cat in CATEGORIES:
            recs_in_cat = cat_records.get(cat, [])
            counts[cat] = len(recs_in_cat)
            if not recs_in_cat:
                results[cat] = NO_RECORD_MSG
                continue
            cat_text = "\n".join(recs_in_cat)
            prompt = (
                BASE_PROMPT +
                f"・カテゴリ「{cat}」に関する記録だけをまとめて200文字程度で生成\n\n"
                f"【{cat}の記録】\n{cat_text}"
            )
            try:
                results[cat] = model.generate_content([prompt]).text.strip()
            except Exception:
                results[cat] = NO_RECORD_MSG

        # DBに保存
        existing = supabase.table("monitoring_reports").select("id").eq(
            "facility_code", f_code).eq("user_name", u_name).eq(
            "target_month", year_month).execute()
        payload = {
            "facility_code": f_code,
            "user_name": u_name,
            "target_month": year_month,
            "mode": "category",
            "char_limit": 200,
            "categories": results,
            "record_counts": counts,
            "updated_at": "now()",
        }
        if existing.data:
            supabase.table("monitoring_reports").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("monitoring_reports").insert(payload).execute()
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {}
    finally:
        _monitoring_gen_lock.release()

@app.route('/print_pdf')
@login_required
def print_pdf():
    """PDF出力: WeasyPrintでprint_preview.htmlをPDF化してダウンロード"""
    import json as _json
    from flask import make_response
    f_code = session.get("f_code", "")
    my_name = session.get("my_name", "")
    supabase = get_supabase()

    year_month = request.args.get("year_month", "")
    user_name_single = request.args.get("user_name", "")
    style = request.args.get("style", "color")
    sort_order = request.args.get("sort", "name")
    items_json = request.args.get("items", "{}")
    cats_json = request.args.get("cats", "{}")
    cat_order = request.args.get("cat_order", "")
    tmpl_raw = request.args.get("template", "1")
    try:
        tmpl = int(tmpl_raw)
    except (ValueError, TypeError):
        tmpl = tmpl_raw
    chart_style = request.args.get("chart_style", 1, type=int)
    try:
        items = _json.loads(items_json)
    except Exception:
        items = {}
    try:
        cats = _json.loads(cats_json)
    except Exception:
        cats = {}

    # 利用者一覧取得
    patients_all = []
    try:
        res = supabase.table("patient_profiles").select(
            "user_name, user_name_kana, support_office, care_manager_name, care_level, discontinued_date"
        ).eq("facility_code", f_code).order("user_name_kana").execute()
        if res.data:
            patients_all = res.data
    except Exception:
        pass

    if user_name_single:
        patients_all = [p for p in patients_all if p.get("user_name") == user_name_single]

    # 利用終了月より後の対象月は除外(終了月までは生成可。一括・個別とも適用)
    if year_month:
        def _active_in_month(p):
            dd = p.get("discontinued_date")
            if not dd:
                return True
            return str(dd)[:7] >= year_month  # 終了月以降(=終了月含む)は対象
        patients_all = [p for p in patients_all if _active_in_month(p)]

    if sort_order == "caremanager":
        patients_all.sort(key=lambda p: (p.get("support_office") or ""))

    # 各利用者のデータ取得
    report_data_list = []
    for p in patients_all:
        uname = p.get("user_name", "")
        data = {"patient": p}
        try:
            ev = supabase.table("patient_evaluations").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).eq(
                "year_month", year_month).execute()
            data["evaluation"] = ev.data[0] if ev.data else {}
        except Exception:
            data["evaluation"] = {}
        try:
            mr = supabase.table("monitoring_reports").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).eq(
                "target_month", year_month).order("id", desc=True).limit(1).execute()
            data["monitoring"] = mr.data[0] if mr.data else {}
        except Exception:
            data["monitoring"] = {}
        try:
            ft = supabase.table("fitness_tests").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).order(
                "measured_date", desc=True).limit(6).execute()
            data["fitness"] = list(reversed(ft.data)) if ft.data else []
        except Exception:
            data["fitness"] = []
        try:
            bw = supabase.table("body_weights").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).order(
                "measured_date", desc=True).limit(6).execute()
            data["weights"] = list(reversed(bw.data)) if bw.data else []
        except Exception:
            data["weights"] = []
        try:
            cm = supabase.table("patient_profiles").select(
                "support_office, care_manager_name, care_level, birth_date, "
                "user_name_kana, short_goal, long_goal, "
                "short_goal_function, short_goal_activity, short_goal_participation, "
                "long_goal_function, long_goal_activity, long_goal_participation"
            ).eq("facility_code", f_code).eq("user_name", uname).execute()
            data["caremanager"] = cm.data[0] if cm.data else {}
        except Exception:
            data["caremanager"] = {}
        # 対象月のケース記録から画像URLを収集
        try:
            if items.get("images", False):
                import datetime as _dt_img
                ym_parts = year_month.split("-")
                if len(ym_parts) == 2:
                    y_str, m_str = ym_parts
                    ym_start = f"{y_str}-{m_str}-01"
                    import calendar as _cal
                    last_day = _cal.monthrange(int(y_str), int(m_str))[1]
                    ym_end = f"{y_str}-{m_str}-{last_day:02d}"
                    rec_imgs = supabase.table("records").select("image_urls, created_at").eq(
                        "facility_code", f_code).eq("user_name", uname).gte(
                        "created_at", ym_start).lte("created_at", ym_end + "T23:59:59").neq(
                        "staff_name", "AI統合記録").execute()
                    all_urls = []
                    for r in (rec_imgs.data or []):
                        urls = r.get("image_urls") or []
                        for u in urls:
                            if u not in all_urls and not u.lower().split("?")[0].endswith(('.mp4','.mov','.webm','.avi','.m4v')):
                                all_urls.append(u)
                    data["available_images"] = all_urls
                    data["selected_images"] = selected_images.get(uname, [])
                    data["img_layout"] = img_layouts.get(uname, "A")
                else:
                    data["available_images"] = []
                    data["selected_images"] = []
                    data["img_layout"] = "A"
            else:
                data["available_images"] = []
                data["selected_images"] = []
                data["img_layout"] = "A"
        except Exception as _e_img:
            print(f"[image collect error] {_e_img}", flush=True)
            data["available_images"] = []
            data["selected_images"] = []
            data["img_layout"] = "A"
        report_data_list.append(data)

    # 施設情報
    facility = {}
    try:
        fac = supabase.table("facilities").select(
            "facility_name, facility_postal_code, facility_address, "
            "facility_tel, facility_fax, facility_logo_url"
        ).eq("facility_code", f_code).execute()
        if fac.data:
            facility = fac.data[0]
    except Exception:
        pass

    # HTMLレンダリング
    html_str = render("print_preview.html",
        report_data_list=report_data_list,
        facility=facility,
        year_month=year_month,
        style=style,
        items=items,
        cats=cats,
        cat_order=cat_order,
        my_name=my_name,
        author=request.args.get("author", ""),
        tmpl=tmpl,
        chart_style=chart_style,
        pdf_mode=True,
    )
    if not isinstance(html_str, str):
        html_str = html_str.get_data(as_text=True)

    # pdfkitでPDF化（wkhtmltopdf使用）
    try:
        import pdfkit
        options = {
            'encoding': 'UTF-8',
            'no-outline': None,
            'quiet': '',
            'disable-smart-shrinking': '',
            'margin-top': '0',
            'margin-right': '0',
            'margin-bottom': '0',
            'margin-left': '0',
        }
        import shutil
        wk_path = shutil.which('wkhtmltopdf') or '/usr/local/bin/wkhtmltopdf'
        config = pdfkit.configuration(wkhtmltopdf=wk_path)
        pdf_bytes = pdfkit.from_string(html_str, False, options=options, configuration=config)
        from urllib.parse import quote
        fname = f"report_{year_month}_{user_name_single or 'all'}.pdf"
        fname_ascii = f"report_{year_month}.pdf"
        fname_encoded = quote(fname)
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = "attachment; filename=\"" + fname_ascii + "\"; filename*=UTF-8''" + fname_encoded
        return response
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/print_preview')
@login_required
def print_preview():
    """印刷プレビュー：一括または1人分の報告書をA4レイアウトで表示"""
    import json as _json
    f_code = session.get("f_code", "")
    my_name = session.get("my_name", "")
    supabase = get_supabase()

    year_month = request.args.get("year_month", "")
    user_name_single = request.args.get("user_name", "")
    style = request.args.get("style", "color")
    sort_order = request.args.get("sort", "name")
    items_json = request.args.get("items", "{}")
    cats_json = request.args.get("cats", "{}")
    cat_order = request.args.get("cat_order", "")
    tmpl_raw = request.args.get("template", "1")
    try:
        tmpl = int(tmpl_raw)
    except (ValueError, TypeError):
        tmpl = tmpl_raw
    chart_style = request.args.get("chart_style", 1, type=int)
    chart_size  = request.args.get("chart_size",  2, type=int)
    author = request.args.get("author", "")
    import json as _json2
    selected_images_json = request.args.get("selected_images", "{}")
    img_layouts_json = request.args.get("img_layouts", "{}")
    try:
        selected_images = _json2.loads(selected_images_json)
    except Exception:
        selected_images = {}
    try:
        img_layouts = _json2.loads(img_layouts_json)
    except Exception:
        img_layouts = {}
    try:
        items = _json.loads(items_json)
    except Exception:
        items = {}
    try:
        cats = _json.loads(cats_json)
    except Exception:
        cats = {}

    # 利用者一覧取得
    patients_all = []
    try:
        res = supabase.table("patient_profiles").select(
            "user_name, user_name_kana, support_office, care_manager_name, care_level, discontinued_date"
        ).eq("facility_code", f_code).order("user_name_kana").execute()
        if res.data:
            patients_all = res.data
    except Exception:
        pass

    # 1人印刷の場合はその人のみ
    if user_name_single:
        patients_all = [p for p in patients_all if p.get("user_name") == user_name_single]

    # user_names_filter: 介護度トグルで絞った複数名のみを対象にする(一括印刷)
    user_names_raw = request.args.get("user_names", "")
    if user_names_raw:
        _target_names = [n for n in user_names_raw.split(",") if n]
        if _target_names:
            _name_set = set(_target_names)
            patients_all = [p for p in patients_all if p.get("user_name") in _name_set]

    # 利用終了月より後の対象月は除外(終了月までは生成可。一括・個別とも適用)
    if year_month:
        def _active_in_month(p):
            dd = p.get("discontinued_date")
            if not dd:
                return True
            return str(dd)[:7] >= year_month  # 終了月以降(=終了月含む)は対象
        patients_all = [p for p in patients_all if _active_in_month(p)]

    # ソート
    if sort_order == "caremanager":
        patients_all.sort(key=lambda p: (p.get("support_office") or ""))

    # 各利用者のデータ取得
    report_data_list = []
    for p in patients_all:
        uname = p.get("user_name", "")
        try:
            import urllib.request as _req
            url = f"http://localhost:8080/api/monitoring_report_data?user_name={uname}&year_month={year_month}"
        except Exception:
            pass
        # 直接Supabaseから取得
        data = {"patient": p}
        try:
            ev = supabase.table("patient_evaluations").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).eq(
                "year_month", year_month).execute()
            data["evaluation"] = ev.data[0] if ev.data else {}
        except Exception:
            data["evaluation"] = {}
        try:
            mr = supabase.table("monitoring_reports").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).eq(
                "target_month", year_month).order("id", desc=True).limit(1).execute()
            if mr.data:
                data["monitoring"] = mr.data[0]
            else:
                # 未生成の場合はバックグラウンドで生成開始し、今回は空で返す
                import threading
                t = threading.Thread(
                    target=_auto_generate_monitoring,
                    args=(supabase, f_code, uname, year_month, my_name),
                    daemon=True
                )
                t.start()
                data["monitoring"] = {}
                data["monitoring_generating"] = True
        except Exception:
            data["monitoring"] = {}
        try:
            ft = supabase.table("fitness_tests").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).order(
                "measured_date", desc=True).limit(6).execute()
            data["fitness"] = list(reversed(ft.data)) if ft.data else []
        except Exception:
            data["fitness"] = []
        try:
            bw = supabase.table("body_weights").select("*").eq(
                "facility_code", f_code).eq("user_name", uname).order(
                "measured_date", desc=True).limit(6).execute()
            data["weights"] = list(reversed(bw.data)) if bw.data else []
        except Exception:
            data["weights"] = []
        try:
            cm = supabase.table("patient_profiles").select(
                "support_office, care_manager_name, care_level, birth_date, "
                "user_name_kana, short_goal, long_goal, "
                "short_goal_function, short_goal_activity, short_goal_participation, "
                "long_goal_function, long_goal_activity, long_goal_participation"
            ).eq("facility_code", f_code).eq("user_name", uname).execute()
            data["caremanager"] = cm.data[0] if cm.data else {}
        except Exception:
            data["caremanager"] = {}
        # 対象月のケース記録から画像URLを収集
        try:
            if items.get("images", False):
                ym_parts = year_month.split("-")
                if len(ym_parts) == 2:
                    y_str, m_str = ym_parts
                    ym_start = f"{y_str}-{m_str}-01"
                    import calendar as _cal_pv
                    last_day = _cal_pv.monthrange(int(y_str), int(m_str))[1]
                    ym_end = f"{y_str}-{m_str}-{last_day:02d}"
                    rec_imgs = supabase.table("records").select("image_urls").eq(
                        "facility_code", f_code).eq("user_name", uname).gte(
                        "created_at", ym_start).lte(
                        "created_at", ym_end + "T23:59:59").neq(
                        "staff_name", "AI統合記録").execute()
                    all_urls = []
                    for _r in (rec_imgs.data or []):
                        for u in (_r.get("image_urls") or []):
                            if u not in all_urls and not u.lower().split("?")[0].endswith(('.mp4','.mov','.webm','.avi','.m4v')):
                                all_urls.append(u)
                    data["available_images"] = all_urls
                    data["selected_images"] = selected_images.get(uname, [])
                    data["img_layout"] = img_layouts.get(uname, "A")
                else:
                    data["available_images"] = []
                    data["selected_images"] = []
                    data["img_layout"] = "A"
            else:
                data["available_images"] = []
                data["selected_images"] = []
                data["img_layout"] = "A"
        except Exception as _e_pv:
            print(f"[pv image collect error] {_e_pv}", flush=True)
            data["available_images"] = []
            data["selected_images"] = []
            data["img_layout"] = "A"
        report_data_list.append(data)

    # 施設情報
    facility = {}
    try:
        fac = supabase.table("facilities").select(
            "facility_name, facility_postal_code, facility_address, "
            "facility_tel, facility_fax, facility_logo_url"
        ).eq("facility_code", f_code).execute()
        if fac.data:
            facility = fac.data[0]
    except Exception:
        pass

    return render("print_preview.html",
        report_data_list=report_data_list,
        facility=facility,
        year_month=year_month,
        style=style,
        items=items,
        cats=cats,
        cat_order=cat_order,
        my_name=my_name,
        author=author,
        tmpl=tmpl,
        chart_style=chart_style,
        chart_size=chart_size,
        selected_images_json=selected_images_json,
        img_layouts_json=img_layouts_json,
    )
