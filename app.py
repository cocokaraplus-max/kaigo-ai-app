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
from cryptography.fernet import Fernet  # line-crypto-v1

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

# ===== upload-ext-guard-v1 : アップロード拡張子ホワイトリスト検査 =====
# 許可: 画像 / 音声 / PDF / 表計算。それ以外(実行可能スクリプト等)は拒否。
_UPLOAD_ALLOWED_EXTS = {
    # 画像
    '.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.gif',
    # 音声
    '.m4a', '.mp3', '.wav', '.webm', '.ogg', '.aac', '.mp4',
    # 文書
    '.pdf',
    # 表計算
    '.csv', '.xlsx', '.xls',
}
# 明示的に危険とみなす拡張子(名前のどこかに含まれていても拒否 = 二重拡張子偽装対策)
_UPLOAD_DANGEROUS_EXTS = {
    '.php', '.phtml', '.php3', '.php4', '.php5', '.pht',
    '.exe', '.sh', '.bat', '.cmd', '.com', '.cgi', '.pl',
    '.py', '.rb', '.jsp', '.asp', '.aspx', '.htaccess',
    '.js', '.mjs', '.html', '.htm', '.svg', '.xhtml', '.shtml',
}

@app.before_request
def _upload_ext_guard():  # upload-ext-guard-v1
    from flask import request, jsonify
    try:
        if not request.files:
            return None
        for _key in request.files:
            for _fs in request.files.getlist(_key):
                name = (getattr(_fs, 'filename', '') or '').strip().lower()
                if not name:
                    continue  # ファイル未選択フィールドは素通り
                # 危険拡張子が名前のどこかに含まれる(.php.jpg 等の偽装)なら拒否
                parts = name.split('.')
                tokens = {'.' + p for p in parts[1:]}
                if tokens & _UPLOAD_DANGEROUS_EXTS:
                    return jsonify({'error': 'file_type_not_allowed',
                        'message': 'このファイル形式はアップロードできません。'}), 400
                # 末尾拡張子がホワイトリストに無ければ拒否
                dot = name.rfind('.')
                ext = name[dot:] if dot >= 0 else ''
                if ext not in _UPLOAD_ALLOWED_EXTS:
                    return jsonify({'error': 'file_type_not_allowed',
                        'message': 'このファイル形式はアップロードできません。画像・音声・PDF・CSV/Excelのみ対応しています。'}), 400
    except Exception as _e:
        # 判定ロジック自体の例外では通す(既存アップロード機能の全滅を防ぐ fail-open)
        print('[upload-ext-guard] check skipped due to error: ' + str(_e), flush=True)
        return None
    return None

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

# ===== line-crypto-v1 : LINE設定の暗号化と施設別取得/保存 =====
_line_fernet_cache = None
def _line_get_fernet():
    """LINE_TOKEN_ENC_KEY から Fernet を作る(キャッシュ)。"""
    global _line_fernet_cache
    if _line_fernet_cache is None:
        key = get_secret('LINE_TOKEN_ENC_KEY').strip()
        if not key:
            raise RuntimeError('LINE_TOKEN_ENC_KEY が設定されていません')
        _line_fernet_cache = Fernet(key.encode())
    return _line_fernet_cache

def _line_encrypt(plain):
    """平文を暗号化して文字列で返す。空はそのまま返す。"""
    if plain is None or plain == '':
        return None
    return _line_get_fernet().encrypt(plain.encode()).decode()

def _line_decrypt(enc):
    """暗号文を復号して平文で返す。失敗時は None。"""
    if not enc:
        return None
    try:
        return _line_get_fernet().decrypt(enc.encode()).decode()
    except Exception as e:
        print(f'line decrypt error: {e}', flush=True)
        return None

def get_line_settings(supabase, f_code):
    """施設の line_settings を取得し、token/secret を復号して返す。無ければ None。"""
    try:
        res = supabase.table('line_settings').select('*').eq('facility_code', f_code).execute()
        if not res.data:
            return None
        row = res.data[0]
        return {
            'facility_code': row.get('facility_code'),
            'channel_access_token': _line_decrypt(row.get('channel_access_token_enc')),
            'channel_secret': _line_decrypt(row.get('channel_secret_enc')),
            'line_oa_name': row.get('line_oa_name') or '',
            'enabled': bool(row.get('enabled')),
            'has_token': bool(row.get('channel_access_token_enc')),
            'has_secret': bool(row.get('channel_secret_enc')),
        }
    except Exception as e:
        print(f'get_line_settings error: {e}', flush=True)
        return None

def save_line_settings(supabase, f_code, token=None, secret=None, oa_name=None, enabled=None):
    """施設のLINE設定を upsert。token/secret が空の場合は既存値を温存。"""
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = None
    try:
        r = supabase.table('line_settings').select('*').eq('facility_code', f_code).execute()
        existing = r.data[0] if r.data else None
    except Exception as e:
        print(f'save_line_settings select error: {e}', flush=True)
    payload = {'facility_code': f_code, 'updated_at': now_iso}
    if token:
        payload['channel_access_token_enc'] = _line_encrypt(token)
    if secret:
        payload['channel_secret_enc'] = _line_encrypt(secret)
    if oa_name is not None:
        payload['line_oa_name'] = oa_name
    if enabled is not None:
        payload['enabled'] = bool(enabled)
    if existing:
        supabase.table('line_settings').update(payload).eq('facility_code', f_code).execute()
    else:
        payload['created_at'] = now_iso
        supabase.table('line_settings').insert(payload).execute()
    return True

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
# ===== login-lockout-v1 : ログイン失敗ロック(施設コード+IP単位) =====
def _login_client_ip():
    from flask import request
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'

_LOGIN_FAIL_LIMIT = 10
_LOGIN_LOCK_MINUTES = 15

def _login_is_locked(supabase, f_code, ip):
    """ロック中なら True。副作用なし(判定のみ)。"""
    try:
        res = supabase.table('login_attempts').select('locked_until').eq(
            'facility_code', f_code).eq('ip', ip).execute()
        rows = res.data or []
        if not rows:
            return False
        lu = rows[0].get('locked_until')
        if not lu:
            return False
        lu_dt = datetime.fromisoformat(str(lu).replace('Z', '+00:00'))
        if lu_dt.tzinfo is None:
            lu_dt = lu_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < lu_dt
    except Exception as e:
        print(f'[login-lockout] is_locked error: {e}', flush=True)
        return False

def _login_record_fail(supabase, f_code, ip):
    """失敗を+1。限界到達で15分ロック。"""
    try:
        now = datetime.now(timezone.utc)
        res = supabase.table('login_attempts').select('id,fail_count').eq(
            'facility_code', f_code).eq('ip', ip).execute()
        rows = res.data or []
        if rows:
            cnt = (rows[0].get('fail_count') or 0) + 1
            upd = {'fail_count': cnt, 'updated_at': now.isoformat()}
            if cnt >= _LOGIN_FAIL_LIMIT:
                upd['locked_until'] = (now + timedelta(minutes=_LOGIN_LOCK_MINUTES)).isoformat()
            supabase.table('login_attempts').update(upd).eq('id', rows[0]['id']).execute()
        else:
            supabase.table('login_attempts').insert({
                'facility_code': f_code, 'ip': ip, 'fail_count': 1,
                'updated_at': now.isoformat(),
            }).execute()
    except Exception as e:
        print(f'[login-lockout] record_fail error: {e}', flush=True)

def _login_clear_fail(supabase, f_code, ip):
    """成功時: 該当(施設コード+IP)の失敗カウンタをリセット。"""
    try:
        supabase.table('login_attempts').update({
            'fail_count': 0, 'locked_until': None,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('facility_code', f_code).eq('ip', ip).execute()
    except Exception as e:
        print(f'[login-lockout] clear_fail error: {e}', flush=True)

# ===== admin-2fa-v1 : 管理者ログインの2段階認証(LINE 6桁コード) =====
_ADMIN_2FA_TTL_MIN = 5
_ADMIN_2FA_MAX_ATTEMPTS = 5

def _admin_2fa_hash(code):
    import hashlib
    return hashlib.sha256(str(code).encode()).hexdigest()

def _admin_2fa_gen_code():
    import secrets
    return f"{secrets.randbelow(1000000):06d}"

def _admin_2fa_issue(supabase, f_code, staff_name, line_user_id):
    """6桁コード生成→ハッシュ保存→LINE送信。送信成功でTrue。"""
    try:
        code = _admin_2fa_gen_code()
        now = datetime.now(timezone.utc)
        exp = (now + timedelta(minutes=_ADMIN_2FA_TTL_MIN)).isoformat()
        row = {
            'facility_code': f_code, 'staff_name': staff_name,
            'code_hash': _admin_2fa_hash(code), 'expires_at': exp,
            'attempts': 0, 'created_at': now.isoformat(),
        }
        # UNIQUE(facility_code, staff_name) 前提: 既存を消してから作り直す
        supabase.table('admin_2fa_codes').delete().eq(
            'facility_code', f_code).eq('staff_name', staff_name).execute()
        supabase.table('admin_2fa_codes').insert(row).execute()
        msg = (
            '【TASUKARU】管理者ログインの認証コードです。\n\n'
            f'認証コード: {code}\n\n'
            'この番号を画面に入力してください（5分間有効）。\n'
            'お心当たりがない場合はこのメッセージを無視してください。'
        )
        return line_send_message(line_user_id, [{'type': 'text', 'text': msg}])
    except Exception as e:
        print(f'[admin-2fa] issue error: {e}', flush=True)
        return False

def _admin_2fa_verify(supabase, f_code, staff_name, code):
    """照合。戻り値: (ok:bool, reason:str)。試行回数を消費。"""
    try:
        res = supabase.table('admin_2fa_codes').select('*').eq(
            'facility_code', f_code).eq('staff_name', staff_name).execute()
        rows = res.data or []
        if not rows:
            return (False, 'no_code')
        r = rows[0]
        # 期限
        exp_dt = datetime.fromisoformat(str(r['expires_at']).replace('Z', '+00:00'))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp_dt:
            return (False, 'expired')
        # 試行回数
        if (r.get('attempts') or 0) >= _ADMIN_2FA_MAX_ATTEMPTS:
            return (False, 'too_many')
        # 照合
        if _admin_2fa_hash(code) == r.get('code_hash'):
            supabase.table('admin_2fa_codes').delete().eq('id', r['id']).execute()
            return (True, 'ok')
        # 失敗: 試行数+1
        supabase.table('admin_2fa_codes').update(
            {'attempts': (r.get('attempts') or 0) + 1}).eq('id', r['id']).execute()
        return (False, 'mismatch')
    except Exception as e:
        print(f'[admin-2fa] verify error: {e}', flush=True)
        return (False, 'error')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("f_code") or not session.get("my_name"):
            if request.args.get("partial"):
                return jsonify({"redirect": "/login"})
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ===== line-api-move-v1 : LINE設定API(login_required定義後に配置) =====
# ===== line-settings-api-v1 : LINE設定の取得/保存API(管理者限定) =====
@app.route('/api/line/settings', methods=['GET'])  # line-settings-api-v1
@login_required
def api_line_settings_get():
    try:
        f_code = session['f_code']
        my_name = session.get('my_name', '')
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({'status': 'error', 'message': '管理者権限がありません'}), 403
        s = get_line_settings(supabase, f_code)
        if not s:
            return jsonify({'status': 'success', 'enabled': False, 'line_oa_name': '',
                            'has_token': False, 'has_secret': False})
        # token/secret の値そのものは返さない(マスク)
        return jsonify({'status': 'success',
                        'enabled': s['enabled'],
                        'line_oa_name': s['line_oa_name'],
                        'has_token': s['has_token'],
                        'has_secret': s['has_secret']})
    except Exception as e:
        print(f'api_line_settings_get error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/line/settings', methods=['POST'])  # line-settings-api-v1
@login_required
def api_line_settings_save():
    try:
        f_code = session['f_code']
        my_name = session.get('my_name', '')
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({'status': 'error', 'message': '管理者権限がありません'}), 403
        data = request.json or {}
        oa_name = data.get('line_oa_name')
        token = (data.get('channel_access_token') or '').strip()
        secret = (data.get('channel_secret') or '').strip()
        enabled = data.get('enabled')
        # 空文字は None 扱い(既存値温存)
        save_line_settings(supabase, f_code,
                           token=token or None,
                           secret=secret or None,
                           oa_name=oa_name,
                           enabled=enabled)
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f'api_line_settings_save error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== line-friends-api-v1 : LINE友だち管理API(一覧/紐付/解除、管理者限定) =====
def _line_patient_name_map(supabase, f_code):
    """id(UUID) -> 表示名 のマップを get_patients から作る。"""
    m = {}
    try:
        for p in get_patients(supabase, f_code):
            pid = p.get('id')
            if pid:
                m[str(pid)] = {
                    'user_name': p.get('user_name') or '',
                    'user_name_kana': p.get('user_name_kana') or '',
                    'patient_number': p.get('patient_number') or '',
                }
    except Exception as e:
        print(f'_line_patient_name_map error: {e}', flush=True)
    return m


@app.route('/api/line/friends', methods=['GET'])  # line-friends-api-v1
@login_required
def api_line_friends_list():
    try:
        f_code = session['f_code']
        my_name = session.get('my_name', '')
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({'status': 'error', 'message': '管理者権限がありません'}), 403
        r = supabase.table('line_friends').select('*').eq('facility_code', f_code).order('updated_at', desc=True).execute()
        rows = r.data or []
        name_map = _line_patient_name_map(supabase, f_code)
        friends = []
        for row in rows:
            pid = row.get('patient_id')
            pinfo = name_map.get(str(pid)) if pid else None
            friends.append({
                'line_user_id': row.get('line_user_id'),
                'display_name': row.get('display_name') or '',
                'status': row.get('status') or 'unlinked',
                'patient_id': pid,
                'patient_name': (pinfo['user_name'] if pinfo else ''),
                'linked_by': row.get('linked_by') or '',
                'updated_at': row.get('updated_at') or '',
            })
        return jsonify({'status': 'success', 'friends': friends})
    except Exception as e:
        print(f'api_line_friends_list error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/line/friends/link', methods=['POST'])  # line-friends-api-v1
@login_required
def api_line_friends_link():
    try:
        f_code = session['f_code']
        my_name = session.get('my_name', '')
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({'status': 'error', 'message': '管理者権限がありません'}), 403
        data = request.json or {}
        uid = (data.get('line_user_id') or '').strip()
        pid = (data.get('patient_id') or '').strip()
        if not uid or not pid:
            return jsonify({'status': 'error', 'message': 'line_user_id と patient_id が必要です'}), 400
        # patient_id が当該施設の利用者か検証(誤紐付防止)
        name_map = _line_patient_name_map(supabase, f_code)
        if str(pid) not in name_map:
            return jsonify({'status': 'error', 'message': 'この利用者は施設に存在しません'}), 400
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        # facility_code + line_user_id の二条件guard
        supabase.table('line_friends').update({
            'patient_id': pid,
            'status': 'linked',
            'linked_by': my_name,
            'updated_at': now_iso,
        }).eq('facility_code', f_code).eq('line_user_id', uid).execute()
        return jsonify({'status': 'success', 'patient_name': name_map[str(pid)]['user_name']})
    except Exception as e:
        print(f'api_line_friends_link error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/line/friends/unlink', methods=['POST'])  # line-friends-api-v1
@login_required
def api_line_friends_unlink():
    try:
        f_code = session['f_code']
        my_name = session.get('my_name', '')
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({'status': 'error', 'message': '管理者権限がありません'}), 403
        data = request.json or {}
        uid = (data.get('line_user_id') or '').strip()
        if not uid:
            return jsonify({'status': 'error', 'message': 'line_user_id が必要です'}), 400
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table('line_friends').update({
            'patient_id': None,
            'status': 'unlinked',
            'linked_by': None,
            'updated_at': now_iso,
        }).eq('facility_code', f_code).eq('line_user_id', uid).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f'api_line_friends_unlink error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== renraku-line-send-v1 : 連絡帳をLINEで送る(テキスト・第一段階) =====
def _line_push(token, to_user_id, messages):
    """施設トークンで push。1回最大3吹き出し(messagesは最大3個)。成功でTrue。"""
    import urllib.request, json as _json
    if not token or not to_user_id or not messages:
        return False
    try:
        payload = _json.dumps({'to': to_user_id, 'messages': messages[:5]}).encode('utf-8')  # renraku-line-photo-v1 : LINE上限は5
        req = urllib.request.Request(
            'https://api.line.me/v2/bot/message/push',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status == 200
    except Exception as e:
        print(f'_line_push error: {e}', flush=True)
        return False


def _rk_chips_text(v):
    """items の chips 値(文字列 or 配列)を読みやすい文字列に。"""
    if v is None:
        return ''
    if isinstance(v, list):
        return '、'.join([str(x) for x in v if str(x).strip()])
    return str(v).strip()


def _line_image_messages(image_urls):
    """公開URL配列から LINE imageMessage を生成。renraku-line-photo-v1"""
    msgs = []
    for u in (image_urls or []):
        if not u or not str(u).startswith('https://'):
            continue
        msgs.append({'type': 'image', 'originalContentUrl': u, 'previewImageUrl': u})
    return msgs


def _line_push_chunked(token, to_user_id, messages):
    """messages を 5件ずつに分割して順に push。全部成功で True。renraku-line-photo-v1"""
    ok = True
    any_sent = False
    for i in range(0, len(messages), 5):
        chunk = messages[i:i+5]
        if not chunk:
            continue
        any_sent = True
        if not _line_push(token, to_user_id, chunk):
            ok = False
    return ok and any_sent


def _renraku_to_line_text(note, vitals, patient_name):
    """連絡帳を家族向けテキストに整形する。"""
    items = (note or {}).get('items') or {}
    lines = []
    lines.append(f'{patient_name}様の連絡帳です。')
    lines.append('')

    # 行った場所
    places = _rk_chips_text(items.get('places'))
    if places:
        lines.append(f'【行った場所】{places}')
    # 食事量
    mm = _rk_chips_text(items.get('meal_main'))
    ms = _rk_chips_text(items.get('meal_side'))
    if mm or ms:
        parts = []
        if mm: parts.append(f'主食 {mm}')
        if ms: parts.append(f'副食 {ms}')
        lines.append('【お食事】' + '、'.join(parts))
    water = _rk_chips_text(items.get('water'))
    if water:
        lines.append(f'【水分】{water}')
    # 入浴
    bath = _rk_chips_text(items.get('bath'))
    if bath:
        lines.append(f'【入浴】{bath}')
    # 排泄
    toilet = _rk_chips_text(items.get('toilet'))
    if toilet:
        lines.append(f'【排泄】{toilet}')
    # 機能訓練
    training = _rk_chips_text(items.get('training'))
    if training:
        lines.append(f'【機能訓練・運動】{training}')

    # バイタル(数値テキスト)
    if vitals:
        vlines = []
        for v in vitals:
            seg = []
            if v.get('temperature') is not None:
                seg.append(f"体温{v.get('temperature')}")
            if v.get('bp_high') is not None and v.get('bp_low') is not None:
                seg.append(f"血圧{v.get('bp_high')}/{v.get('bp_low')}")
            if v.get('pulse') is not None:
                seg.append(f"脈拍{v.get('pulse')}")
            if v.get('spo2') is not None:
                seg.append(f"SpO2 {v.get('spo2')}%")
            if seg:
                vlines.append('・' + '、'.join(seg))
        if vlines:
            lines.append('')
            lines.append('【体調・バイタル】')
            lines.extend(vlines)

    # 特記事項
    special = (note or {}).get('special_note') or ''
    if special.strip():
        lines.append('')
        lines.append('【連絡事項】')
        lines.append(special.strip())

    # ご家族へのメッセージ
    fam = (note or {}).get('family_message') or ''
    if fam.strip():
        lines.append('')
        lines.append(fam.strip())

    # 次回
    nv = (note or {}).get('next_visit') or ''
    if nv.strip():
        lines.append('')
        lines.append(f'【次回ご利用】{nv.strip()}')

    return '\n'.join(lines).strip()


def _renraku_fetch_for_line(supabase, f_code, patient_id, note_date):
    """連絡帳 note + vitals + 利用者名 を取得(renraku_print と同様)。"""
    nres = (supabase.table('renraku_notes').select('*')
            .eq('facility_code', f_code).eq('patient_id', patient_id).eq('note_date', note_date).execute())
    note = nres.data[0] if nres.data else None
    vres = (supabase.table('vitals')
            .select('measured_at,temperature,bp_high,bp_low,pulse,spo2')
            .eq('facility_code', f_code).eq('patient_id', patient_id).eq('measured_date', note_date)
            .order('measured_at', desc=False).execute())
    vitals = vres.data or []
    name_map = _line_patient_name_map(supabase, f_code)
    pname = (name_map.get(str(patient_id)) or {}).get('user_name', '') if name_map else ''
    return note, vitals, pname


def _line_linked_recipients(supabase, f_code, patient_id):
    """その利用者に linked な友だち(userId, display_name)のリスト。"""
    r = (supabase.table('line_friends').select('line_user_id,display_name,status,patient_id')
         .eq('facility_code', f_code).eq('patient_id', patient_id).eq('status', 'linked').execute())
    return r.data or []


@app.route('/api/renraku/line_preview', methods=['POST'])  # renraku-line-send-v1
@login_required
def api_renraku_line_preview():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        data = request.json or {}
        patient_id = str(data.get('patient_id') or '')
        note_date = data.get('note_date')
        if not patient_id or not note_date:
            return jsonify({'status': 'error', 'message': 'patient_id と note_date が必要です'}), 400
        note, vitals, pname = _renraku_fetch_for_line(supabase, f_code, patient_id, note_date)
        if not note:
            return jsonify({'status': 'error', 'message': 'この日の連絡帳がまだありません'}), 400
        text = _renraku_to_line_text(note, vitals, pname)
        recipients = _line_linked_recipients(supabase, f_code, patient_id)
        recip_view = [{'display_name': r.get('display_name') or '(名前未取得)',
                        'user_id_tail': (r.get('line_user_id') or '')[-6:]} for r in recipients]
        _photo_count = len([u for u in ((note or {}).get('image_urls') or []) if u])  # renraku-line-photo-v1
        return jsonify({'status': 'success', 'text': text,
                        'patient_name': pname,
                        'recipient_count': len(recipients),
                        'recipients': recip_view,
                        'photo_count': _photo_count})
    except Exception as e:
        print(f'api_renraku_line_preview error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/renraku/line_send', methods=['POST'])  # renraku-line-send-v1
@login_required
def api_renraku_line_send():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        data = request.json or {}
        patient_id = str(data.get('patient_id') or '')
        note_date = data.get('note_date')
        text = (data.get('text') or '').strip()
        _image_urls = data.get('image_urls') or []  # renraku-line-photo-v1

        if not patient_id or not note_date or not text:
            return jsonify({'status': 'error', 'message': 'patient_id / note_date / text が必要です'}), 400
        # 施設のLINE設定(有効・トークン)
        s = get_line_settings(supabase, f_code)
        if not s or not s.get('enabled') or not s.get('channel_access_token'):
            return jsonify({'status': 'error', 'message': 'LINE連携が有効でないかトークン未登録です'}), 400
        token = s['channel_access_token']
        # 安全ルール: linked のみ送信
        recipients = _line_linked_recipients(supabase, f_code, patient_id)
        if not recipients:
            return jsonify({'status': 'error', 'message': '紐付け済みのご家族がいません'}), 400
        messages = [{'type': 'text', 'text': text}]
        try:
            messages += _line_image_messages(_image_urls)  # renraku-line-photo-v1
        except Exception as _img_e:
            print(f'line image msg build error: {_img_e}', flush=True)
        sent = 0
        failed = 0
        for r in recipients:
            uid = r.get('line_user_id')
            if not uid:
                continue
            if _line_push_chunked(token, uid, messages):  # renraku-line-photo-v1
                sent += 1
            else:
                failed += 1
        return jsonify({'status': 'success', 'sent': sent, 'failed': failed,
                        'recipient_count': len(recipients)})
    except Exception as e:
        print(f'api_renraku_line_send error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== renraku-photo-api-v1 : 連絡帳写真アップロード(case-photos・公開URL) =====
@app.route('/api/renraku/upload_photo', methods=['POST'])  # renraku-photo-api-v1
@login_required
def api_renraku_upload_photo():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        files = request.files.getlist('photos')
        if not files:
            single = request.files.get('photo')
            if single:
                files = [single]
        files = [f for f in files if f and f.filename]
        if not files:
            return jsonify({'status': 'error', 'message': '画像がありません'}), 400
        from utils import upload_images_to_supabase
        urls = upload_images_to_supabase(supabase, files, f_code)
        return jsonify({'status': 'success', 'urls': urls or []})
    except Exception as e:
        print(f'api_renraku_upload_photo error: {e}', flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== line-profile-v1 : LINEプロフィール取得(display_name) =====
def _line_get_profile(token, user_id):
    """施設トークンで GET /v2/bot/profile/{userId}。取得できたら displayName、失敗したら None。例外は投げない。"""
    if not token or not user_id:
        return None
    import urllib.request, json as _json
    try:
        req = urllib.request.Request(
            'https://api.line.me/v2/bot/profile/' + user_id,
            headers={'Authorization': 'Bearer ' + token},
            method='GET'
        )
        with urllib.request.urlopen(req, timeout=3) as res:
            if res.status == 200:
                data = _json.loads(res.read().decode('utf-8'))
                return data.get('displayName')
    except Exception as e:
        print(f'_line_get_profile error: {e}', flush=True)
    return None

# ===== line-webhook-v1 : LINE Webhook 受信(公開・署名検証・未紐付保存) =====
def _line_save_friend(supabase, f_code, user_id, display_name=None):
    """line_friends に userId を未紐付(unlinked)で upsert。既存は status を触らず updated_at のみ更新。"""
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        r = supabase.table('line_friends').select('id,status').eq('facility_code', f_code).eq('line_user_id', user_id).execute()
        if r.data:
            upd = {'updated_at': now_iso}
            if display_name:
                upd['display_name'] = display_name
            supabase.table('line_friends').update(upd).eq('facility_code', f_code).eq('line_user_id', user_id).execute()
        else:
            supabase.table('line_friends').insert({
                'facility_code': f_code,
                'line_user_id': user_id,
                'display_name': display_name,
                'status': 'unlinked',
                'created_at': now_iso,
                'updated_at': now_iso,
            }).execute()
    except Exception as e:
        print(f'_line_save_friend error: {e}', flush=True)


@app.route('/line/webhook/<facility_code>', methods=['POST'])  # line-webhook-v1
def line_webhook(facility_code):
    import hmac, hashlib
    try:
        supabase = get_supabase()
        s = get_line_settings(supabase, facility_code)
        # 設定なし or 無効 or secret 未登録なら 401(イベントは処理しない)
        if not s or not s.get('channel_secret'):
            print(f'line_webhook: no settings/secret for {facility_code}', flush=True)
            return 'ng', 401
        body = request.get_data()  # bytes(署名検証は生ボディで行う)
        sig = request.headers.get('X-Line-Signature', '')
        mac = hmac.new(s['channel_secret'].encode('utf-8'), body, hashlib.sha256).digest()
        expected = base64.b64encode(mac).decode('utf-8')
        if not hmac.compare_digest(expected, sig):
            print(f'line_webhook: bad signature for {facility_code}', flush=True)
            return 'ng', 401
        # 署名OK。イベント処理
        payload = request.get_json(silent=True) or {}
        events = payload.get('events', []) or []
        for ev in events:
            etype = ev.get('type')
            src = ev.get('source', {}) or {}
            uid = src.get('userId')
            if not uid:
                continue
            # follow(友だち追加) / message で userId を未紐付保存
            if etype in ('follow', 'message'):
                # line-profile-v1: 可能なら display_name を取得(失敗しても保存は実行)
                dname = _line_get_profile(s.get('channel_access_token'), uid)
                _line_save_friend(supabase, facility_code, uid, display_name=dname)
        return 'ok', 200
    except Exception as e:
        print(f'line_webhook error: {e}', flush=True)
        # エラーでも200を返しLINE側のリトライ暴走を避ける(要件に応じて要検討)
        return 'ok', 200


# staff-line-webhook-v1 : TASUKARUアカウント用webhook(職員LINE紐付け・パスワード再発行)
@app.route('/line/webhook/tasukaru', methods=['POST'])
def line_webhook_tasukaru():
    import hmac as _hm, hashlib as _hl, secrets as _sc, re as _re
    from datetime import datetime as _dt, timezone as _tz, timedelta as _tdl
    try:
        secret = get_secret("LINE_CHANNEL_SECRET")
        if not secret:
            print("line_webhook_tasukaru: no LINE_CHANNEL_SECRET", flush=True)
            return "ng", 401
        body = request.get_data()
        sig = request.headers.get("X-Line-Signature", "")
        mac = _hm.new(secret.encode("utf-8"), body, _hl.sha256).digest()
        expected = base64.b64encode(mac).decode("utf-8")
        if not _hm.compare_digest(expected, sig):
            print("line_webhook_tasukaru: bad signature", flush=True)
            return "ng", 401
        payload = request.get_json(silent=True) or {}
        events = payload.get("events", []) or []
        supabase = get_supabase()
        base_url = request.host_url.rstrip("/").replace("http://", "https://")
        for ev in events:
            etype = ev.get("type")
            src = ev.get("source", {}) or {}
            uid = src.get("userId")
            if not uid:
                continue
            if etype == "follow":
                line_send_message(uid, [{"type": "text", "text":
                    "TASUKARUです。職員アカウントとの連携をご希望の場合は、管理者から渡された6桁のコードを送信してください。"}])
                continue
            if etype != "message":
                continue
            msg = ev.get("message", {}) or {}
            if msg.get("type") != "text":
                continue
            text = (msg.get("text") or "").strip()
            # 1) 6桁数字 → 紐付けコード照合
            if _re.fullmatch(r"[0-9]{6}", text):
                now_iso = _dt.now(_tz.utc).isoformat()
                res = supabase.table("staffs").select(
                    "id,staff_name,facility_code,link_code,link_code_expires,is_active"
                ).eq("link_code", text).eq("is_active", True).execute()
                rows = res.data or []
                matched = None
                for r in rows:
                    exp = r.get("link_code_expires")
                    if not exp:
                        continue
                    try:
                        ed = _dt.fromisoformat(str(exp).replace("Z", "+00:00"))
                        if ed.tzinfo is None:
                            ed = ed.replace(tzinfo=_tz.utc)
                        if _dt.now(_tz.utc) <= ed:
                            matched = r
                            break
                    except Exception:
                        continue
                if not matched:
                    line_send_message(uid, [{"type": "text", "text":
                        "コードが無効か、有効期限が切れています。管理者に再発行を依頼してください。"}])
                    continue
                supabase.table("staffs").update({
                    "line_user_id": uid,
                    "link_code": None,
                    "link_code_expires": None,
                }).eq("id", matched["id"]).execute()
                line_send_message(uid, [{"type": "text", "text":
                    matched.get("staff_name", "") + " さんのアカウントと連携しました。\n"
                    "パスワードを忘れたときは「パスワード」と送ってください。再設定用のリンクをお送りします。"}])
                continue
            # 2) 「パスワード」を含む → 紐付け済みなら再発行
            if "パスワード" in text or "ぱすわーど" in text:
                res = supabase.table("staffs").select(
                    "id,staff_name,facility_code,is_active"
                ).eq("line_user_id", uid).eq("is_active", True).execute()
                rows = res.data or []
                if not rows:
                    line_send_message(uid, [{"type": "text", "text":
                        "このLINEはまだ職員アカウントと連携されていません。管理者から6桁コードを受け取り、先に連携してください。"}])
                    continue
                st = rows[0]
                token = _sc.token_urlsafe(32)
                exp = (_dt.now(_tz.utc) + _tdl(hours=24)).isoformat()
                supabase.table("staffs").update({
                    "setup_token": token,
                    "setup_token_expires": exp,
                }).eq("id", st["id"]).execute()
                setup_url = base_url + "/setup?token=" + token
                line_send_message(uid, [{"type": "text", "text":
                    "\n".join([
                        st.get("staff_name", "") + " さんのパスワード再設定リンクです(24時間有効)。",
                        "下のリンクから新しいパスワードを設定してください。",
                        setup_url,
                    ])}])
                continue
            # staff-kaizen-reply-v1 : 「アプリ改善依頼」→ 受付案内を返信
            if "アプリ改善依頼" in text or "改善依頼" in text or "要望" in text:
                line_send_message(uid, [{"type": "text", "text":
                    "\n".join([
                        "ご要望・お困りごとをお聞かせください。",
                        "このトークにそのままメッセージを送っていただければ、担当者が確認します。",
                        "（画面の使いにくい点・追加してほしい機能など、なんでもお気軽にどうぞ）",
                    ])}])
                continue
            # 3) それ以外 → 使い方ガイド
            line_send_message(uid, [{"type": "text", "text":
                "パスワードを再発行するには「パスワード」と送ってください。\n"
                "初めての方は、管理者から渡された6桁コードを送信して連携してください。"}])
        return "ok", 200
    except Exception as e:
        print(f"line_webhook_tasukaru error: {e}", flush=True)
        return "ok", 200


# staff-linkcode-api-v1 : 管理者が対象職員のLINE紐付けコード(6桁)を発行
@app.route('/api/admin/issue_link_code', methods=['POST'])
def api_issue_link_code():
    import random as _rnd
    from datetime import datetime as _dt2, timezone as _tz2, timedelta as _td2
    f_code = session.get("f_code")
    if not f_code:
        return jsonify({"error": "not logged in"}), 401
    data = request.get_json(silent=True) or {}
    staff_name = (data.get("staff_name") or "").strip()
    if not staff_name:
        return jsonify({"error": "staff_name required"}), 400
    try:
        supabase = get_supabase()
        res = supabase.table("staffs").select("id,staff_name").eq(
            "facility_code", f_code).eq("staff_name", staff_name).eq("is_active", True).execute()
        rows = res.data or []
        if not rows:
            return jsonify({"error": "staff not found"}), 404
        code = "".join([str(_rnd.randint(0, 9)) for _ in range(6)])
        exp = (_dt2.now(_tz2.utc) + _td2(hours=24)).isoformat()
        supabase.table("staffs").update({
            "link_code": code,
            "link_code_expires": exp,
        }).eq("id", rows[0]["id"]).execute()
        return jsonify({"status": "ok", "code": code, "staff_name": staff_name})
    except Exception as e:
        print(f"issue_link_code error: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


# staff-start-link-v1 : 職員利用開始 3点照合API + LIFF器
@app.route('/api/staff/start_link', methods=['POST'])
def api_staff_start_link():
    """職員利用開始: 施設コード + 職員名 + 6桁コード + userId の3点(+userId)照合。
    一致で line_user_id 紐付け -> setup_token 発行 -> /setup リンク返却。"""
    import hashlib as _ss_hashlib  # noqa: F401 (未使用でも将来用)
    import secrets as _ss_secrets
    from datetime import datetime as _ss_dt, timezone as _ss_tz, timedelta as _ss_td
    data = request.get_json(silent=True) or {}
    facility_code = (data.get("facility_code") or "").strip()
    staff_name = (data.get("staff_name") or "").strip()
    link_code = (data.get("link_code") or "").strip()
    line_user_id = (data.get("line_user_id") or "").strip()
    if not facility_code or not staff_name or not link_code:
        return jsonify({"error": "missing_fields"}), 400
    if not re.fullmatch(r"[0-9]{6}", link_code):
        return jsonify({"error": "bad_code"}), 400
    if not line_user_id:
        return jsonify({"error": "no_line_user"}), 400
    try:
        supabase = get_supabase()
        # 3点照合: facility_code + staff_name + link_code (is_active)
        res = supabase.table("staffs").select(
            "id,staff_name,facility_code,link_code,link_code_expires,is_active"
        ).eq("facility_code", facility_code).eq(
            "staff_name", staff_name).eq(
            "link_code", link_code).eq("is_active", True).execute()
        rows = res.data or []
        if not rows:
            return jsonify({"error": "no_match"}), 404
        st = rows[0]
        # 有効期限チェック
        exp = st.get("link_code_expires")
        if not exp:
            return jsonify({"error": "expired"}), 400
        try:
            ed = _ss_dt.fromisoformat(str(exp).replace("Z", "+00:00"))
            if ed.tzinfo is None:
                ed = ed.replace(tzinfo=_ss_tz.utc)
            if _ss_dt.now(_ss_tz.utc) > ed:
                return jsonify({"error": "expired"}), 400
        except Exception:
            return jsonify({"error": "expired"}), 400
        # setup_token 発行
        token = _ss_secrets.token_urlsafe(32)
        token_exp = (_ss_dt.now(_ss_tz.utc) + _ss_td(hours=24)).isoformat()
        # line_user_id 紐付け + setup_token 発行 + 6桁コード消費
        supabase.table("staffs").update({
            "line_user_id": line_user_id,
            "setup_token": token,
            "setup_token_expires": token_exp,
            "link_code": None,
            "link_code_expires": None,
        }).eq("id", st["id"]).execute()
        setup_url = request.host_url.rstrip("/") + "/setup?token=" + token
        return jsonify({
            "status": "ok",
            "staff_name": st.get("staff_name", ""),
            "setup_url": setup_url,
        })
    except Exception as e:
        print(f"staff_start_link error: {e}", flush=True)
        return jsonify({"error": "server_error"}), 500


@app.route('/staff_start')
def staff_start_page():
    """職員利用開始 LIFF 画面の器"""
    return render_template("staff_start.html")


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
    # leave-reporter-display-v1: 連絡者はcontent文章には入れず、daily_viewのバッジでのみ表示する。
    # 日付・理由の文章は従来通り。reporter_type/other_detail は互換性のため引数に残す。
    base = f"{period}はお休みです。"
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


# extra-use-content-helper-v1
# ==========================================
# 追加利用連絡content生成ヘルパー
# ==========================================
def _build_extra_content(period, extra_reason):
    """追加利用連絡のcontent文字列を生成する共通関数。"""
    base = f"{period}は追加利用です。"
    if extra_reason:
        base += f"理由：{extra_reason}"
    return base
def _build_extra_content_multi(dates, extra_reason):
    """複数日(飛び日含む)の追加利用連絡content文字列を生成する。"""
    period = _format_leave_period(dates)
    return _build_extra_content(period, extra_reason)

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


@app.route('/api/admin/toggle_timecard_hidden', methods=['POST'])  # timecard-hidden-icon-v1
def api_toggle_timecard_hidden():
    """職員を打刻画面に表示する/しないを切り替え。admin_settings(timecard_hidden)の名前リスト。"""
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "msg": "権限がありません"}), 403
    import json as _json
    f_code = session["f_code"]
    data = request.get_json() or {}
    staff_name = data.get("staff_name")
    hidden = data.get("hidden", False)  # True=表示しない
    if not staff_name:
        return jsonify({"success": False, "msg": "staff_name required"}), 400
    try:
        supabase = get_supabase()  # timecard-hidden-fix-v1
        res = supabase.table("admin_settings").select("value").eq(
            "facility_code", f_code).eq("key", "timecard_hidden").execute()
        current = _json.loads(res.data[0].get("value") or "[]") if res.data else []
        if not isinstance(current, list):
            current = []
        if hidden:
            if staff_name not in current:
                current.append(staff_name)
        else:
            current = [n for n in current if n != staff_name]
        new_value = _json.dumps(current, ensure_ascii=False)
        if res.data:
            supabase.table("admin_settings").update({"value": new_value}).eq(
                "facility_code", f_code).eq("key", "timecard_hidden").execute()
        else:
            supabase.table("admin_settings").insert({
                "facility_code": f_code, "key": "timecard_hidden", "value": new_value
            }).execute()
        return jsonify({"success": True, "msg": f"{staff_name} のタイムカード表示設定を更新"})
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
        _login_ip = _login_client_ip()  # login-lockout-v1

        if not f_code or not password:
            error = "施設コードとパスワードを入力してください。"
        elif _login_is_locked(get_supabase(), f_code, _login_ip):  # login-lockout-v1
            error = "ログインに何度も失敗したため、しばらくロックされています。約15分後に再度お試しください。"
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
                                _login_record_fail(supabase, f_code, _login_ip)  # login-lockout-v1
                                error = "パスワードが違います。"
                            else:
                                my_name = matched_staff["staff_name"]
                                _login_clear_fail(supabase, f_code, _login_ip)  # login-lockout-v1
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

# onboard-setup-route-v1 : 初回パスワード設定(オンボーディングでLINE送信されたリンク)
@app.route('/setup', methods=['GET', 'POST'])
def onboard_setup():
    import hashlib as _su_hashlib
    from datetime import datetime as _su_dt, timezone as _su_tz
    supabase = get_supabase()
    token = (request.values.get("token") or "").strip()
    if not token:
        return render_template("setup.html", state="invalid")
    try:
        res = supabase.table("staffs").select(
            "id,staff_name,facility_code,setup_token,setup_token_expires,is_active"
        ).eq("setup_token", token).eq("is_active", True).execute()
        rows = res.data or []
    except Exception as e:
        print(f"[Setup] lookup error: {e}", flush=True)
        return render_template("setup.html", state="invalid")
    if not rows:
        return render_template("setup.html", state="invalid")
    row = rows[0]
    # 期限チェック
    exp = row.get("setup_token_expires")
    if exp:
        try:
            exp_dt = _su_dt.fromisoformat(str(exp).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=_su_tz.utc)
            if _su_dt.now(_su_tz.utc) > exp_dt:
                return render_template("setup.html", state="expired")
        except Exception:
            pass
    if request.method == "POST":
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if not pw or len(pw) < 8:
            return render_template("setup.html", state="form", token=token,
                                   staff_name=row.get("staff_name", ""),
                                   error="パスワードは8文字以上で設定してください。")
        if pw != pw2:
            return render_template("setup.html", state="form", token=token,
                                   staff_name=row.get("staff_name", ""),
                                   error="確認用パスワードが一致しません。")
        pw_hash = _su_hashlib.sha256(pw.encode()).hexdigest()
        try:
            supabase.table("staffs").update({
                "password_hash": pw_hash,
                "setup_token": None,
                "setup_token_expires": None,
            }).eq("id", row["id"]).execute()
        except Exception as e:
            print(f"[Setup] update error: {e}", flush=True)
            return render_template("setup.html", state="form", token=token,
                                   staff_name=row.get("staff_name", ""),
                                   error="保存に失敗しました。時間をおいて再度お試しください。")
        return render_template("setup.html", state="done",
                               facility_code=row.get("facility_code", ""),
                               staff_name=row.get("staff_name", ""))
    return render_template("setup.html", state="form", token=token,
                           staff_name=row.get("staff_name", ""))


# onboard-liff-page-v1 : LIFFエンドポイントの器(この後フォーム+LIFF SDKを載せる)
@app.route('/onboard')
def onboard_page():
    return render_template("onboard.html")
# onboard-done-v1 : 決済後の完了ページ(LIFF非読込。LINEで開くループ回避)
@app.route('/onboard/done')
def onboard_done_page():
    st = (request.args.get("st") or "success").strip()
    return render_template("onboard_done.html", st=st)


@app.route('/register', methods=['GET', 'POST'])
def register():
    # onboard-register-retire-v1 : 旧経路を無効化。正規オンボーディング(/onboard)へ誘導。
    # 以前は平文パスワードで施設を作成し決済も経ない抜け穴だった。以降のコードは到達不能。
    return redirect(url_for("onboard"))
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
        if not sel or sel == "" or (not content and _cat_for_check != "休み連絡" and _cat_for_check != "追加利用連絡"):  # extra-server-validate-v1
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
                    # extra-use-save-content-v1: 追加利用連絡の値取得とcontent生成
                    extra_date_start_val = (request.form.get("extra_date_start", "") or "").strip()
                    extra_date_end_val = (request.form.get("extra_date_end", "") or "").strip()
                    extra_reason_val = (request.form.get("extra_reason", "") or "").strip() if category == "追加利用連絡" else ""
                    extra_dates_raw = (request.form.get("extra_dates", "") or "").strip()
                    extra_dates_list = []
                    if extra_dates_raw:
                        extra_dates_list = [d.strip() for d in extra_dates_raw.split(",") if d.strip()]
                    if category == "追加利用連絡" and extra_dates_list:
                        try:
                            from datetime import datetime as _dtx0
                            _sortedx = sorted(extra_dates_list, key=lambda x: _dtx0.strptime(x, "%Y-%m-%d"))
                            extra_date_start_val = _sortedx[0]
                            extra_date_end_val = _sortedx[-1]
                            content = _build_extra_content_multi(extra_dates_list, extra_reason_val)
                        except Exception as _cex:
                            print(f"[追加利用連絡content生成エラー(複数日)] {_cex}", flush=True)
                    elif category == "追加利用連絡" and extra_date_start_val:
                        try:
                            from datetime import datetime as _dtx
                            _lsx = _dtx.strptime(extra_date_start_val, "%Y-%m-%d")
                            _lsx_str = f"{_lsx.month}月{_lsx.day}日"
                            if extra_date_end_val and extra_date_end_val != extra_date_start_val:
                                _lex = _dtx.strptime(extra_date_end_val, "%Y-%m-%d")
                                _periodx = f"{_lsx_str}〜{_lex.month}月{_lex.day}日"
                            else:
                                _periodx = _lsx_str
                            content = _build_extra_content(_periodx, extra_reason_val)
                        except Exception as _cex2:
                            print(f"[追加利用連絡content生成エラー] {_cex2}", flush=True)
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
                        # extra-use-insert-cols-v1
                        "extra_date_start": extra_date_start_val if category == "追加利用連絡" else None,
                        "extra_date_end": (extra_date_end_val or extra_date_start_val) if category == "追加利用連絡" else None,
                        "extra_reason": extra_reason_val if category == "追加利用連絡" else None,
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

                    # extra-use-cal-register-v1: 追加利用連絡カテゴリはカレンダーに自動登録(青色)
                    if category == "追加利用連絡" and new_id:
                        try:
                            user_name_for_cal_x = m.group(2)
                            if extra_dates_list:
                                _xcal_dates = sorted(set(extra_dates_list))
                            else:
                                _xs0 = (request.form.get("extra_date_start", "") or "").strip()
                                _xe0 = (request.form.get("extra_date_end", "") or "").strip()
                                _xcal_dates = [_xs0] if _xs0 else []
                                _xsingle_end = _xe0 or _xs0
                            if _xcal_dates:
                                xcal_id = _get_or_create_system_calendar(supabase, f_code, my_name)
                                if xcal_id:
                                    xfirst_event_id = None
                                    for _xidx, _xcd in enumerate(_xcal_dates):
                                        if extra_dates_list:
                                            _xev_end = _xcd
                                        else:
                                            _xev_end = _xsingle_end or _xcd
                                        xcal_payload = {
                                            "facility_code": f_code,
                                            "calendar_id": xcal_id,
                                            "title": f"{user_name_for_cal_x}様 追加利用",
                                            "event_date": _xcd,
                                            "end_date": _xev_end,
                                            "all_day": True,
                                            "color": "#1e88e5",
                                            "memo": content,
                                            "created_by": my_name,
                                            "record_id": new_id,
                                        }
                                        xcal_res = supabase.table("calendar_events").insert(xcal_payload).execute()
                                        _xeid = None
                                        if xcal_res.data:
                                            _xeid = xcal_res.data[0]["id"]
                                        else:
                                            xfetch_res = supabase.table("calendar_events").select("id").eq("facility_code", f_code).eq("calendar_id", xcal_id).eq("event_date", _xcd).eq("created_by", my_name).order("id", desc=True).limit(1).execute()
                                            if xfetch_res.data:
                                                _xeid = xfetch_res.data[0]["id"]
                                        if _xeid and xfirst_event_id is None:
                                            xfirst_event_id = _xeid
                                    if xfirst_event_id:
                                        supabase.table("records").update(
                                            {"calendar_event_id": xfirst_event_id}
                                        ).eq("id", new_id).execute()
                                        print(f"[extra calendar sync] linked record {new_id} to {len(_xcal_dates)} event(s), first={xfirst_event_id}", flush=True)
                        except Exception as _xcal_err:
                            print(f"[extra calendar sync] failed: {_xcal_err}", flush=True)

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
                # chatroom-key-render-removed-v1: Realtime用キー受け渡しを削除(ポーリングで動作)
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

# ===== visit-mgmt-v1 / visit-mgmt-idfix-v1: 利用管理(予定×実績 月間集約・閲覧ハブ) =====
def _visit_weekday_of(date_str):
    """date_str(YYYY-MM-DD)の曜日を JS getDay基準(日曜=0〜土曜=6)で返す。"""
    from datetime import datetime as _dt
    d = _dt.strptime(date_str, "%Y-%m-%d")
    return (d.weekday() + 1) % 7  # Python月=0..日=6 → 日=0..土=6

def _visit_is_planned_weekday(weekdays, date_str):
    """weekdays(例 '135', 日曜=0基準の数字並び)に その日の曜日が含まれるか。"""
    if not weekdays:
        return False
    return str(_visit_weekday_of(date_str)) in str(weekdays)

def _visit_planned_weekdays_for(supabase, f_code, patient_int_id):
    """指定患者(patients.id=patient_int_id)の weekdays 文字列を返す。"""
    try:
        res = supabase.table("patient_visit_days").select("weekdays").eq("facility_code", f_code).eq("patient_id", patient_int_id).execute()
        if res.data:
            return res.data[0].get("weekdays") or ""
    except Exception as e:
        print(f"visit planned weekdays error: {e}", flush=True)
    return ""

def _visit_auto_upsert(supabase, f_code, patient_pid, date_str, staff_name, patient_int_id):
    """バイタル保存時の自動実績。予定曜日なら present、予定外なら transfer。
    手動(source=manual)レコードは上書きしない。"""
    try:
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).isoformat()
        weekdays = _visit_planned_weekdays_for(supabase, f_code, patient_int_id) if patient_int_id else ""
        status = 'present' if _visit_is_planned_weekday(weekdays, date_str) else 'transfer'
        existing = supabase.table('visit_records').select('id,status,source').eq('facility_code', f_code).eq('patient_id', str(patient_pid)).eq('visit_date', date_str).execute()
        if existing.data:
            row = existing.data[0]
            if row.get('source') == 'manual':
                return  # 手動は尊重
            supabase.table('visit_records').update({'status': status, 'source': 'vital_auto', 'checked_at': now_iso, 'updated_at': now_iso}).eq('id', row['id']).execute()
        else:
            supabase.table('visit_records').insert({
                'facility_code': f_code, 'patient_id': str(patient_pid), 'visit_date': date_str,
                'status': status, 'source': 'vital_auto', 'checked_at': now_iso, 'staff_name': staff_name,
            }).execute()
    except Exception as e:
        print(f"visit auto upsert error: {e}", flush=True)

def _visit_cleanup_on_vital_delete(supabase, f_code, patient_pid, date_str):
    """バイタル削除後、その日に他バイタルが無ければ vital_auto の visit_records を削除。"""
    try:
        if not patient_pid or not date_str:
            return
        remain = supabase.table('vitals').select('id').eq('facility_code', f_code).eq('patient_id', patient_pid).eq('measured_date', date_str).execute()
        if remain.data:
            return  # まだバイタルが残っている
        # 自動分のみ削除(手動は残す)
        supabase.table('visit_records').delete().eq('facility_code', f_code).eq('patient_id', str(patient_pid)).eq('visit_date', date_str).eq('source', 'vital_auto').execute()
    except Exception as e:
        print(f"visit cleanup on vital delete error: {e}", flush=True)

# ===== renraku-v1: 連絡帳(フェーズ1) =====
@app.route('/renraku/print')  # renraku-print-route-v1
@login_required
def renraku_print_page():
    """\u9023\u7d61\u5e33\u5370\u5237\u30da\u30fc\u30b8\u3002date \u3068 ids(\u30ab\u30f3\u30de\u533a\u5207\u308a) \u3092\u53d7\u3051\u308b\u3002"""
    import json as _json
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        date = request.args.get('date') or datetime.now(tokyo_tz).strftime('%Y-%m-%d')
        ids_raw = request.args.get('ids') or ''
        ids = [s.strip() for s in ids_raw.split(',') if s.strip()]
        plist = get_patients(supabase, f_code)
        fac_vis = _renraku_facility_visible(supabase, f_code)
        out = []
        for pid in ids:
            nres = (supabase.table('renraku_notes').select('*')
                    .eq('facility_code', f_code).eq('patient_id', pid).eq('note_date', date).execute())
            note = nres.data[0] if nres.data else None
            vres = (supabase.table('vitals')
                    .select('id,measured_at,temperature,bp_high,bp_low,pulse,spo2,note,staff_name')
                    .eq('facility_code', f_code).eq('patient_id', pid).eq('measured_date', date)
                    .order('measured_at', desc=False).execute())
            vitals = vres.data or []
            prof = next((p for p in plist if str(p['id']) == str(pid)), None)
            pat_vis = _renraku_patient_visible(supabase, f_code, pid)
            visible = pat_vis if pat_vis is not None else (fac_vis or {})
            out.append({
                'patient': {
                    'patient_id': pid,
                    'user_name': (prof or {}).get('user_name', ''),
                    'user_kana': (prof or {}).get('user_kana', ''),
                    'patient_number': (prof or {}).get('patient_number', ''),
                    'care_level': (prof or {}).get('care_level', ''),
                },
                'note': note,
                'vitals': vitals,
                'visible': visible,
            })
        fac_name = ''
        try:
            fr = supabase.table('facilities').select('facility_name').eq('facility_code', f_code).execute()
            if fr.data:
                fac_name = fr.data[0].get('facility_name', '') or ''
        except Exception:
            fac_name = ''
        return render_template('renraku_print.html',
                               print_data_json=_json.dumps(out, ensure_ascii=False, default=str),
                               date_json=_json.dumps(date, ensure_ascii=False),
                               facility_name_json=_json.dumps(fac_name, ensure_ascii=False))
    except Exception as e:
        print(f"renraku print error: {e}", flush=True)
        return f"\u5370\u5237\u30da\u30fc\u30b8\u306e\u751f\u6210\u306b\u5931\u6557\u3057\u307e\u3057\u305f: {e}", 500


@app.route('/renraku')
@login_required
def renraku_page():  # renraku-v1
    return render_template('renraku.html')


@app.route('/api/renraku/list', methods=['GET'])  # renraku-v1
@login_required
def api_renraku_list():
    """指定日にバイタルがある利用者の一覧を返す。各自の連絡帳記入済みフラグ・測定回数付き。"""
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        date = request.args.get('date') or datetime.now(tokyo_tz).strftime('%Y-%m-%d')
        # その日のバイタル(全回)を取得
        vres = (supabase.table('vitals')
                .select('patient_id,user_name,measured_at,temperature,bp_high,bp_low,pulse,spo2')
                .eq('facility_code', f_code).eq('measured_date', date).execute())
        vitals = vres.data or []
        # patient_id ごとに集約
        by_pid = {}
        for v in vitals:
            pid = str(v.get('patient_id'))
            by_pid.setdefault(pid, []).append(v)
        # 利用者名の解決(patient_profiles)
        plist = get_patients(supabase, f_code)
        pmap = {str(p['id']): p for p in plist}
        # 連絡帳の記入済み状況
        nres = (supabase.table('renraku_notes')
                .select('patient_id')
                .eq('facility_code', f_code).eq('note_date', date).execute())
        noted = set(str(r['patient_id']) for r in (nres.data or []))
        items = []
        for pid, vs in by_pid.items():
            prof = pmap.get(pid)
            name = (prof or {}).get('user_name') or (vs[0].get('user_name') if vs else '') or ''
            kana = (prof or {}).get('user_kana') or ''
            chart = (prof or {}).get('patient_number') or ''
            items.append({
                'patient_id': pid,
                'user_name': name,
                'user_kana': kana,
                'patient_number': chart,
                'vital_count': len(vs),
                'noted': pid in noted,
            })
        # かな順
        items.sort(key=lambda x: (x.get('user_kana') or x.get('user_name') or ''))
        return jsonify({'status': 'success', 'date': date, 'patients': items})
    except Exception as e:
        print(f"renraku list error: {e}", flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/renraku/get', methods=['GET'])  # renraku-v1
@login_required
def api_renraku_get():
    """単一利用者の連絡帳+その日の全バイタル(measured_at昇順)を返す。"""
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        patient_id = str(request.args.get('patient_id') or '')
        date = request.args.get('date') or datetime.now(tokyo_tz).strftime('%Y-%m-%d')
        if not patient_id:
            return jsonify({'status': 'error', 'message': 'patient_id は必須です'}), 400
        # 連絡帳本体
        nres = (supabase.table('renraku_notes')
                .select('*')
                .eq('facility_code', f_code).eq('patient_id', patient_id).eq('note_date', date).execute())
        note = nres.data[0] if nres.data else None
        # その日の全バイタル(複数回, 時刻昇順)
        vres = (supabase.table('vitals')
                .select('id,measured_at,temperature,bp_high,bp_low,pulse,spo2,note,staff_name')
                .eq('facility_code', f_code).eq('patient_id', patient_id).eq('measured_date', date)
                .order('measured_at', desc=False).execute())
        vitals = vres.data or []
        # 利用者プロフィール
        plist = get_patients(supabase, f_code)
        prof = next((p for p in plist if str(p['id']) == patient_id), None)
        # renraku-get-visible-v1: 表示項目(個別→施設既定→全表示) を解決
        _pat_vis = _renraku_patient_visible(supabase, f_code, patient_id)
        if _pat_vis is not None:
            _visible, _vis_src = _pat_vis, 'patient'
        else:
            _fac_vis = _renraku_facility_visible(supabase, f_code)
            _visible, _vis_src = (_fac_vis, 'facility') if _fac_vis else ({}, 'default')
        return jsonify({
            'status': 'success',
            'date': date,
            'patient': {
                'patient_id': patient_id,
                'user_name': (prof or {}).get('user_name', ''),
                'user_kana': (prof or {}).get('user_kana', ''),
                'patient_number': (prof or {}).get('patient_number', ''),
                'care_level': (prof or {}).get('care_level', ''),
            },
            'note': note,
            'vitals': vitals,
            'visible': _visible,
            'visible_source': _vis_src,
        })
    except Exception as e:
        print(f"renraku get error: {e}", flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/renraku/save', methods=['POST'])  # renraku-v1
@login_required
def api_renraku_save():
    """連絡帳を upsert(facility_code+patient_id+note_date)。"""
    try:
        f_code = session['f_code']
        my_name = session['my_name']
        supabase = get_supabase()
        data = request.json or {}
        patient_id = str(data.get('patient_id') or '')
        note_date = data.get('note_date')
        if not patient_id or not note_date:
            return jsonify({'status': 'error', 'message': 'patient_id と note_date は必須です'}), 400
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            'facility_code': f_code,
            'patient_id': patient_id,
            'note_date': note_date,
            'items': data.get('items') or {},
            'special_note': data.get('special_note', ''),
            'family_message': data.get('family_message', ''),
            'next_visit': data.get('next_visit', ''),
            'image_urls': data.get('image_urls') or [],  # renraku-photo-api-v1
            'staff_name': my_name,
            'updated_at': now_iso,
        }
        existing = (supabase.table('renraku_notes').select('id')
                    .eq('facility_code', f_code).eq('patient_id', patient_id).eq('note_date', note_date).execute())
        if existing.data:
            rid = existing.data[0]['id']
            supabase.table('renraku_notes').update(payload).eq('id', rid).execute()
        else:
            payload['created_at'] = now_iso
            res = supabase.table('renraku_notes').insert(payload).execute()
            rid = res.data[0]['id'] if res.data else None
        return jsonify({'status': 'success', 'id': rid})
    except Exception as e:
        print(f"renraku save error: {e}", flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== renraku-settings-v1: 表示項目設定(一括=施設既定 / 個別=利用者ごと) =====
def _renraku_facility_visible(supabase, f_code):
    """施設既定の visible(dict) を返す。無ければ {}。"""
    try:
        res = supabase.table('renraku_settings').select('visible').eq('facility_code', f_code).execute()
        if res.data and isinstance(res.data[0].get('visible'), dict):
            return res.data[0]['visible']
    except Exception as e:
        print(f"renraku facility visible error: {e}", flush=True)
    return {}


def _renraku_patient_visible(supabase, f_code, patient_id):
    """利用者ごとの visible(dict) を返す。無ければ None。"""
    try:
        res = (supabase.table('renraku_patient_settings').select('visible')
               .eq('facility_code', f_code).eq('patient_id', patient_id).execute())
        if res.data and isinstance(res.data[0].get('visible'), dict):
            return res.data[0]['visible']
    except Exception as e:
        print(f"renraku patient visible error: {e}", flush=True)
    return None


@app.route('/api/renraku/settings', methods=['GET'])  # renraku-settings-v1
@login_required
def api_renraku_settings_get():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        return jsonify({'status': 'success', 'visible': _renraku_facility_visible(supabase, f_code)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/renraku/settings', methods=['POST'])  # renraku-settings-v1
@login_required
def api_renraku_settings_save():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        data = request.json or {}
        visible = data.get('visible') or {}
        if not isinstance(visible, dict):
            return jsonify({'status': 'error', 'message': 'visible は辞書である必要があります'}), 400
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table('renraku_settings').upsert({
            'facility_code': f_code, 'visible': visible, 'updated_at': now_iso,
        }, on_conflict='facility_code').execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"renraku settings save error: {e}", flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/renraku/patient_settings', methods=['GET'])  # renraku-settings-v1
@login_required
def api_renraku_patient_settings_get():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        patient_id = str(request.args.get('patient_id') or '')
        if not patient_id:
            return jsonify({'status': 'error', 'message': 'patient_id は必須です'}), 400
        return jsonify({'status': 'success', 'visible': _renraku_patient_visible(supabase, f_code, patient_id)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/renraku/patient_settings', methods=['POST'])  # renraku-settings-v1
@login_required
def api_renraku_patient_settings_save():
    try:
        f_code = session['f_code']
        supabase = get_supabase()
        data = request.json or {}
        patient_id = str(data.get('patient_id') or '')
        visible = data.get('visible') or {}
        if not patient_id:
            return jsonify({'status': 'error', 'message': 'patient_id は必須です'}), 400
        if not isinstance(visible, dict):
            return jsonify({'status': 'error', 'message': 'visible は辞書である必要があります'}), 400
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table('renraku_patient_settings').upsert({
            'facility_code': f_code, 'patient_id': patient_id, 'visible': visible, 'updated_at': now_iso,
        }, on_conflict='facility_code,patient_id').execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"renraku patient settings save error: {e}", flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== renraku-ai-family-v1: ご家族へのメッセージ AI下書き生成 =====
RENRAKU_FAMILY_PROMPT = """あなたは介護施設(デイサービス)の介護職員です。ご利用者「{user}」様について、ご家族へお渡しする連絡帳の「ご家族へのメッセージ」を作成します。  # renraku-ai-family-prompt-v3

【対象の確認(最重要)】
この連絡帳の対象は「{user}」様です。文章は必ず「{user}」様ご本人の本日の様子として書いてください。記録には複数の介護職員が登場し、他のご利用者の名前が含まれることもありますが、対象は常に「{user}」様です。主語を取り違えないでください。

【与えられる材料の見方】
下記のケース記録は、各行が「記録者(職員) / 対象(ご利用者) / 内容」で構成されています。記録者は職員、対象はそのことを書かれたご利用者です。これは誰が誰について書いたかを正しく理解するための情報です。

【厳守事項】
- 文章は「{user}」様ご本人の様子として書くこと。記録した職員を主語にしない。
- 記録した職員の名前は、必要が無ければ本文に出さないこと(通常は出さない)。
- 本文に「{user}」様ご本人の名前は書かないこと(ご家族が読むため、様子のみを述べる)。
- 記録の中に他のご利用者の名前が出てきた場合は、その名前を書かず必ず「他の利用者様」と表現すること。
- ケース記録に書かれた事実だけを使うこと。記録に無いことは推測・脚色・創作しない(ハルシネーション禁止)。
- ご家族に向けた、やさしく分かりやすい敬体(です・ます)にすること。二重敬語や過剰な敬語(「お〜になられる」「〜していただかれる」「ございました」等)は避け、「〜でした」「〜されていました」「ご案内しました」程度の自然な丁寧さにとどめること。  # prompt-tone-v1
- 1〜3文程度に簡潔にまとめること。医療的な診断・断定は避け、観察された事実を伝えること。
- 署名・日付・宛名・記録形式(【】等)は本文に持ち込まないこと。本文のみを出力すること。

【本日のケース記録】
{records}

上記の事実だけをもとに、「{user}」様の本日の様子を、ご家族へのメッセージ本文として出力してください。本文のみを出力してください。"""


@app.route('/api/renraku/generate_family', methods=['POST'])  # renraku-ai-family-v1
@login_required
def api_renraku_generate_family():
    try:
        import datetime as _dt
        from datetime import time as _dt_time, timedelta as _timedelta
        f_code = session['f_code']
        supabase = get_supabase()
        data = request.json or {}
        patient_id = str(data.get('patient_id') or '')
        date = data.get('date')
        if not patient_id or not date:
            return jsonify({'status': 'error', 'message': 'patient_id と date は必須です'}), 400
        # 利用者名を解決(records は user_name で引く)
        plist = get_patients(supabase, f_code)
        prof = next((p for p in plist if str(p['id']) == patient_id), None)
        if not prof:
            return jsonify({'status': 'error', 'message': '利用者が見つかりません'}), 404
        user = prof.get('user_name')
        try:
            selected_date = _dt.datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({'status': 'error', 'message': '日付の形式が正しくありません'}), 400
        t_start = tokyo_tz.localize(_dt.datetime.combine(selected_date, _dt_time.min))
        res = (supabase.table('records').select('*')
               .eq('facility_code', f_code).eq('user_name', user)
               .gte('created_at', t_start.isoformat())
               .lt('created_at', (t_start + _timedelta(days=1)).isoformat()).execute())
        recs = res.data or []
        # AI統合記録があれば優先、なければ通常記録を結合
        ai_recs = [r for r in recs if r.get('staff_name') == 'AI統合記録']
        normal_recs = [r for r in recs if r.get('staff_name') != 'AI統合記録']
        if ai_recs:
            recs_text = "\n".join([f"記録者: AI統合記録 / 対象: {user}様 / 内容: {r.get('content','')}" for r in ai_recs])  # renraku-ai-family-prompt-v3
        elif normal_recs:
            recs_text = "\n".join([f"記録者: {r.get('staff_name','')} / 対象: {user}様 / 内容: {r.get('content','')}" for r in normal_recs])  # renraku-ai-family-prompt-v3
        else:
            return jsonify({'status': 'error', 'message': 'この日のケース記録がありません。先にケース記録を入力してください。'}), 200
        from utils import get_generative_model
        model = get_generative_model()
        resp = model.generate_content([RENRAKU_FAMILY_PROMPT.format(user=user, records=recs_text)])
        text = (resp.text or '').strip()
        return jsonify({'status': 'success', 'message_text': text})
    except Exception as e:
        print(f"renraku generate_family error: {e}", flush=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/visit')
@login_required
def visit_page():  # visit-page-v1
    return render_template('visit.html')

@app.route('/api/visit/month', methods=['GET'])
@login_required
def api_visit_month():
    """指定利用者・月の 予定/休み/実績 を日ごとに集約して返す(閲覧用)。"""
    f_code = session.get('f_code')
    supabase = get_supabase()
    try:
        from datetime import datetime as _dt, date as _date
        import calendar as _cal
        pid = request.args.get('patient_id')          # patient_profiles.id
        year = int(request.args.get('year'))
        month = int(request.args.get('month'))
        if not pid:
            return jsonify({'status': 'error', 'message': 'patient_id必須'}), 400
        # patient_profiles.id → user_name → patients.id(patient_int_id) を解決
        patients = get_patients(supabase, f_code)
        pobj = next((p for p in patients if str(p['id']) == str(pid)), None)
        if not pobj:
            return jsonify({'status': 'error', 'message': '利用者が見つかりません'}), 404
        patient_int_id = pobj.get('patient_int_id')
        weekdays = _visit_planned_weekdays_for(supabase, f_code, patient_int_id) if patient_int_id else ""
        # 月の日数
        ndays = _cal.monthrange(year, month)[1]
        first = '%04d-%02d-01' % (year, month)
        last = '%04d-%02d-%02d' % (year, month, ndays)
        # 実績(visit_records): patient_profiles.id 基準
        rec_map = {}
        rec = supabase.table('visit_records').select('visit_date,status,source').eq('facility_code', f_code).eq('patient_id', str(pid)).gte('visit_date', first).lte('visit_date', last).execute()
        for r in (rec.data or []):
            rec_map[str(r['visit_date'])] = r
        # 休み連絡(records, category=休み連絡): user_name で引く。期間 leave_date_start〜end。
        leave_days = {}  # date_str -> record_id
        try:
            lv = supabase.table('records').select('id,leave_date_start,leave_date_end').eq('facility_code', f_code).eq('user_name', pobj.get('user_name')).eq('category', '休み連絡').execute()
            for r in (lv.data or []):
                ds = r.get('leave_date_start'); de = r.get('leave_date_end') or ds
                if not ds:
                    continue
                d0 = _dt.strptime(str(ds)[:10], '%Y-%m-%d').date()
                d1 = _dt.strptime(str(de)[:10], '%Y-%m-%d').date()
                cur = d0
                from datetime import timedelta as _td
                while cur <= d1:
                    if cur.year == year and cur.month == month:
                        leave_days[cur.isoformat()] = r.get('id')
                    cur = cur + _td(days=1)
        except Exception as _le:
            print(f"visit month leave fetch error: {_le}", flush=True)
        # 日ごとに組み立て
        days = []
        for d in range(1, ndays + 1):
            ds = '%04d-%02d-%02d' % (year, month, d)
            wd = _visit_weekday_of(ds)
            planned = _visit_is_planned_weekday(weekdays, ds)
            leave_id = leave_days.get(ds)
            rec = rec_map.get(ds)
            days.append({
                'date': ds, 'day': d, 'weekday': wd,
                'planned': planned,
                'leave': bool(leave_id),
                'leave_record_id': leave_id,
                'actual': (rec.get('status') if rec else None),
            })
        return jsonify({'status': 'success', 'patient_id': str(pid),
                        'user_name': pobj.get('user_name', ''), 'user_kana': pobj.get('user_kana', ''),
                        'year': year, 'month': month, 'days': days})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

        # visit-mgmt-v1: バイタル保存で来所自動記録(予定曜日=出席/予定外=振替)
        try:
            _vp = next((p for p in get_patients(supabase, f_code) if str(p["id"]) == str(data.get("patient_id"))), None)
            _vint = _vp.get("patient_int_id") if _vp else None
            _visit_auto_upsert(supabase, f_code, data.get("patient_id"), data.get("measured_date"), my_name, _vint)
        except Exception:
            pass
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
        # visit-mgmt-v1: バイタル保存で来所自動記録
        try:
            _vp = next((p for p in get_patients(supabase, f_code) if str(p["id"]) == str(data.get("patient_id"))), None)
            _vint = _vp.get("patient_int_id") if _vp else None
            _visit_auto_upsert(supabase, f_code, data.get("patient_id"), data.get("measured_date"), my_name, _vint)
        except Exception:
            pass
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
        # visit-mgmt-v1: 削除対象の患者・日付を控えてから削除し、実績を後始末
        _vrow = None
        try:
            _vq = supabase.table("vitals").select("patient_id,measured_date").eq("id", rid).execute()
            _vrow = _vq.data[0] if _vq.data else None
        except Exception:
            _vrow = None
        supabase.table("vitals").delete().eq("id", rid).execute()
        if _vrow:
            try:
                _visit_cleanup_on_vital_delete(supabase, session.get("f_code"), _vrow.get("patient_id"), _vrow.get("measured_date"))
            except Exception:
                pass
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
                    elif rec_q.data and rec_q.data[0].get("category") == "追加利用連絡":
                        # extra-use-cal-edit-sync-v1: 追加利用連絡のカレンダー→ケース記録同期(複数日)
                        _xrec_q = supabase.table("records").select("extra_reason").eq("id", _linked_record_id).execute()
                        _x_reason = (_xrec_q.data[0].get("extra_reason") if _xrec_q.data else "") or ""
                        all_ev_x = supabase.table("calendar_events").select("id,event_date").eq("facility_code", f_code).eq("record_id", _linked_record_id).execute()
                        _dates_all_x = sorted([r["event_date"] for r in (all_ev_x.data or []) if r.get("event_date")])
                        if _dates_all_x:
                            _new_content_x = _build_extra_content_multi(_dates_all_x, _x_reason)
                            supabase.table("records").update({
                                "content": _new_content_x,
                                "extra_date_start": _dates_all_x[0],
                                "extra_date_end": _dates_all_x[-1],
                            }).eq("id", _linked_record_id).execute()
                            for r in (all_ev_x.data or []):
                                supabase.table("calendar_events").update({"memo": _new_content_x}).eq("id", r["id"]).execute()
                            print(f"[カレンダー同期(追加利用複数日)] record {_linked_record_id} を {len(_dates_all_x)} 日で再生成", flush=True)
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
                    elif rec0.get("category") == "追加利用連絡":
                        # extra-use-cal-delete-sync-v1: 追加利用連絡のイベント削除→残日でケース記録を作り直す
                        _xrec_d = supabase.table("records").select("extra_reason").eq("id", target_record_id).execute()
                        _x_reason_d = (_xrec_d.data[0].get("extra_reason") if _xrec_d.data else "") or ""
                        _dates_x = sorted([r["event_date"] for r in remain_rows if r.get("event_date")])
                        if _dates_x:
                            new_content_x = _build_extra_content_multi(_dates_x, _x_reason_d)
                            supabase.table("records").update({
                                "content": new_content_x,
                                "extra_date_start": _dates_x[0],
                                "extra_date_end": _dates_x[-1],
                                "calendar_event_id": remain_rows[0]["id"],
                            }).eq("id", target_record_id).execute()
                            for r in remain_rows:
                                supabase.table("calendar_events").update({"memo": new_content_x}).eq("id", r["id"]).execute()
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
・フィラー(「あー」「えー」等)や言いよどみ・無意味な繰り返しは除去し、読みやすい記録に整える（ただし発言内容は変えない・要約や補完はしない）  # eval-transcribe-filler-v1
"""
            else:
                prompt = """これは介護施設の機能訓練指導員が月次評価について口頭で述べた音声です。
発話内容をそのまま文字起こししてください。

【厳守ルール】
・文字起こしに徹する。要約・整理・補完・推測・創作を一切しない
・1人の発話として素直に文字起こしする
・聞き取れない箇所は[聞き取り不明瞭]と記載する（補完・推測は禁止）
・フィラー(「あー」「えー」等)や言いよどみ・無意味な繰り返しは除去し、読みやすい記録に整える（ただし発言内容は変えない・要約や補完はしない）  # eval-transcribe-filler-v1
"""

            resp = model.generate_content([prompt, {"mime_type": mime, "data": file_bytes}])  # eval-ingest-order-v1
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
            "・機能訓練指導員（理学療法士・作業療法士・言語聴覚士・柔道整復師・看護師等）として、医学的視点と機能訓練の専門的観点（身体機能・ADL・関節可動域・筋力・バランス・歩行・認知/嚥下機能等）を踏まえてケアマネージャーへ伝える\n"  # eval-aifill-medical-v1
            "・硬すぎず砕けすぎず、現場感のある自然な丁寧語（です・ます調）。二重敬語は使わない\n"  # eval-aifill-tone-v1
            "・専門的だが堅苦しくなりすぎない、ケアマネージャーが読みやすい自然な文章にする\n"
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
        # ledger-credit-method-v1: 記録方法(null/receipt/csv)をそのまま返す
        settings['credit_input_method'] = settings.get('credit_input_method')
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
        # ledger-credit-method-v1: 記録方法の保存（receipt/csv/null のみ、それ以外は無視）
        if 'credit_input_method' in data:
            _m = data.get('credit_input_method')
            if _m in ('receipt', 'csv'):
                payload['credit_input_method'] = _m
            elif _m is None or _m == '':
                payload['credit_input_method'] = None
        # ledger-fiscal-month-api-v1: 決算月(1〜12)の保存。範囲外は無視
        if 'fiscal_year_end_month' in data:
            try:
                _fm = int(data.get('fiscal_year_end_month'))
                if 1 <= _fm <= 12:
                    payload['fiscal_year_end_month'] = _fm
            except (TypeError, ValueError):
                pass
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


# ledger-recalc-lock-v1: 施設単位の再計算ロック(同一施設の再計算を直列化し二重補填を防ぐ)
_ledger_recalc_locks = {}
_ledger_recalc_locks_guard = threading.Lock()
def _ledger_recalc_lock_for(f_code):
    with _ledger_recalc_locks_guard:
        lk = _ledger_recalc_locks.get(f_code)
        if lk is None:
            lk = threading.Lock()
            _ledger_recalc_locks[f_code] = lk
        return lk

def _ledger_recalc_day(supabase, f_code, target_date):
    """現金残高再計算(ロック付ラッパ)。同一施設の再計算を直列化する。"""
    lock = _ledger_recalc_lock_for(f_code)
    lock.acquire()
    try:
        _ledger_recalc_day_inner(supabase, f_code, target_date)
    finally:
        lock.release()

def _ledger_recalc_day_inner(supabase, f_code, target_date):  # ledger-cumulative-cashfill-v1
    """決算期内を期初残高起点で累積再計算し、現金補填を立て直す。
    現金が残っている限りそれを消化し、不足分だけを接骨院から補填する。
    ロックは呼び出し側ラッパー(_ledger_recalc_day)で直列化済み。"""
    try:
        import datetime as _dt
        # 設定確認
        s_res = supabase.table('ledger_settings').select('auto_cash_fill,cash_fill_division_id').eq('facility_code', f_code).execute()
        if not s_res.data or not s_res.data[0].get('auto_cash_fill'):
            return
        fill_div_id = s_res.data[0].get('cash_fill_division_id')

        # 現金科目
        cash_res = supabase.table('accounts').select('id,name').eq('facility_code', f_code).eq('code', '101').execute()
        if not cash_res.data:
            return
        cash_id = cash_res.data[0]['id']
        # 事業主借(フォールバック用)
        owner_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('name', '\u4e8b\u696d\u4e3b\u501f').execute()
        if owner_res.data:
            owner_id = owner_res.data[0]['id']
        else:
            _io = supabase.table('accounts').insert({'facility_code': f_code, 'code': '300', 'name': '\u4e8b\u696d\u4e3b\u501f', 'category': '\u7d14\u8cc7\u7523', 'tax_type': 'none'}).execute()
            owner_id = _io.data[0]['id'] if _io.data else cash_id
        # 事業間移動科目
        transfer_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('name', '\u4e8b\u696d\u9593\u79fb\u52d5').execute()
        if transfer_res.data:
            transfer_id = transfer_res.data[0]['id']
        else:
            _it = supabase.table('accounts').insert({'facility_code': f_code, 'code': '199', 'name': '\u4e8b\u696d\u9593\u79fb\u52d5', 'category': '\u8cc7\u7523', 'tax_type': 'none'}).execute()
            transfer_id = _it.data[0]['id'] if _it.data else cash_id

        # 補填元未設定時は旧フォールバック(単日・事業主借)
        if not fill_div_id:
            _af = supabase.table('journal_entries').select('id').eq('facility_code', f_code).eq('entry_date', target_date).in_('source', ['auto_fill', 'transfer']).execute()
            for _r in (_af.data or []):
                supabase.table('journal_entries').delete().eq('id', _r['id']).eq('facility_code', f_code).execute()
            _all = supabase.table('journal_entries').select('amount,debit_account_id,credit_account_id,source,debit:debit_account_id(code,category),credit:credit_account_id(code,category)').eq('facility_code', f_code).eq('entry_date', target_date).execute()
            _man = [e for e in (_all.data or []) if e.get('source') not in ('auto_fill', 'transfer')]
            _exp = sum(e['amount'] for e in _man if e.get('credit') and e['credit_account_id'] == cash_id and e.get('debit') and e['debit'].get('category') == '\u8cbb\u7528')
            _b2c = sum(e['amount'] for e in _man if e.get('debit') and e['debit_account_id'] == cash_id and e.get('credit') and e['credit'].get('code') == '102')
            _short = _exp - _b2c
            if _short > 0:
                supabase.table('journal_entries').insert({'facility_code': f_code, 'entry_date': target_date, 'debit_account_id': cash_id, 'credit_account_id': owner_id, 'amount': _short, 'tax_amount': 0, 'description': '\u73fe\u91d1\u81ea\u52d5\u88dc\u586b', 'source': 'auto_fill', 'created_by': 'system', 'division_id': None}).execute()
            return

        fill_div_id = int(fill_div_id)
        # 決算期の範囲を決定
        ref = _dt.date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
        period_start = _ledger_fiscal_period_start(f_code, ref)
        period_end = _dt.date(period_start.year + 1, period_start.month, 1) - _dt.timedelta(days=1)
        today = datetime.now(tokyo_tz).date()
        calc_end = min(period_end, today)
        if calc_end < period_start:
            return
        ps_iso = period_start.isoformat()
        ce_iso = calc_end.isoformat()

        # 期間内のauto_fill/transferを全削除(作り直す)
        _af = supabase.table('journal_entries').select('id').eq('facility_code', f_code).gte('entry_date', ps_iso).lte('entry_date', ce_iso).in_('source', ['auto_fill', 'transfer']).execute()
        for _r in (_af.data or []):
            supabase.table('journal_entries').delete().eq('id', _r['id']).eq('facility_code', f_code).execute()

        # 期間内の手動仕訳を一括取得
        man_res = supabase.table('journal_entries').select(
            'amount,debit_account_id,credit_account_id,source,division_id,entry_date,'
            'credit:credit_account_id(code,category)'
        ).eq('facility_code', f_code).gte('entry_date', ps_iso).lte('entry_date', ce_iso).execute()
        man_entries = [e for e in (man_res.data or []) if e.get('source') not in ('auto_fill', 'transfer')]

        # 補填対象事業部 = 期間内の手動仕訳に登場する「補填元以外」の事業部
        target_divs = sorted({
            e.get('division_id') for e in man_entries
            if e.get('division_id') is not None and int(e.get('division_id')) != fill_div_id
        }, key=lambda x: int(x))
        if not target_divs:
            return

        # 期初残高を事業部別に取得
        ob_res = supabase.table('ledger_opening_balances').select('division_id,amount').eq('facility_code', f_code).eq('period_start', ps_iso).execute()
        opening = {}
        for r in (ob_res.data or []):
            if r.get('division_id') is not None:
                opening[int(r['division_id'])] = int(r.get('amount') or 0)

        # 日付リスト(期初〜計算終了日)
        def _daterange(d0, d1):
            cur = d0
            while cur <= d1:
                yield cur
                cur = cur + _dt.timedelta(days=1)

        # 事業部ごとに、期初残高起点で累積
        for div in target_divs:
            div = int(div)
            balance = opening.get(div, 0)
            # 当該事業部の手動仕訳を日付ごとに集計
            by_date = {}
            for e in man_entries:
                if e.get('division_id') is None or int(e['division_id']) != div:
                    continue
                d = e.get('entry_date')
                if d not in by_date:
                    by_date[d] = {'exp': 0, 'w': 0}
                # 現金支出: 貸方=現金
                if e.get('credit') and e['credit_account_id'] == cash_id:
                    by_date[d]['exp'] += e['amount']
                # ledger-cashfill-allin-v1: 現金収入 = 借方=現金の手動仕訳すべて
                # (普通預金引出も売上の現金受取も含む。man_entriesは補填除外済み)
                if e['debit_account_id'] == cash_id:
                    by_date[d]['w'] += e['amount']

            for cur in _daterange(period_start, calc_end):
                d_iso = cur.isoformat()
                day = by_date.get(d_iso, {'exp': 0, 'w': 0})
                E = day['exp']
                W = day['w']
                shortage = E - (balance + W)
                if shortage > 0:
                    # 接骨院(補填元)→当該事業部へ 不足分を補填
                    supabase.table('journal_entries').insert({'facility_code': f_code, 'entry_date': d_iso, 'debit_account_id': transfer_id, 'credit_account_id': cash_id, 'amount': shortage, 'tax_amount': 0, 'description': '\u73fe\u91d1\u88dc\u586b\uff08\u51fa\u91d1\uff09', 'source': 'auto_fill', 'created_by': 'system', 'division_id': fill_div_id}).execute()
                    supabase.table('journal_entries').insert({'facility_code': f_code, 'entry_date': d_iso, 'debit_account_id': cash_id, 'credit_account_id': transfer_id, 'amount': shortage, 'tax_amount': 0, 'description': '\u73fe\u91d1\u88dc\u586b\uff08\u5165\u91d1\uff09', 'source': 'auto_fill', 'created_by': 'system', 'division_id': div}).execute()
                    balance = 0
                else:
                    balance = (balance + W) - E
    except Exception as e:
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


@app.route('/api/ledger/account_next_code', methods=['GET'])  # ledger-acct-autocode-v1
@login_required
def api_ledger_account_next_code():
    """カテゴリの番号帯で空いている次のコードを返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    try:
        category = (request.args.get('category') or '').strip()
        # \u30ab\u30c6\u30b4\u30ea -> \u756a\u53f7\u5e2f\u306e\u5148\u982d\u6570\u5b57
        band = {
            '\u8cc7\u7523': 1, '\u8ca0\u50b5': 2, '\u7d14\u8cc7\u7523': 3,
            '\u53ce\u76ca': 4, '\u8cbb\u7528': 5,
        }.get(category)
        if band is None:
            return jsonify({'status': 'error', 'message': 'bad_category'}), 400
        lo = band * 100
        hi = band * 100 + 99
        res = supabase.table('accounts').select('code')\
            .eq('facility_code', f_code).execute()
        max_in_band = None
        for r in (res.data or []):
            c = str(r.get('code') or '').strip()
            if not c.isdigit():
                continue
            n = int(c)
            if lo <= n <= hi:
                if max_in_band is None or n > max_in_band:
                    max_in_band = n
        nxt = (max_in_band + 1) if max_in_band is not None else (lo + 1)
        return jsonify({'status': 'success', 'code': str(nxt)})
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


def _esc(s):  # ledger-subledger-pdf-v1 HTML escape helper
    s = '' if s is None else str(s)
    return (s.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


@app.route('/api/ledger/subledger_pdf', methods=['GET'])  # ledger-subledger-pdf-v1
@login_required
def api_ledger_subledger_pdf():
    """\u88dc\u52a9\u5143\u5e33(\u73fe\u91d1/\u9810\u91d1/\u7d4c\u8cbb\u30af\u30ec\u30ab/\u58f2\u4e0a)\u3092PDF\u5316\u3057\u3066\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u3002"""
    import json as _json
    from flask import make_response
    from urllib.parse import quote
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    try:
        sub_type = (request.args.get('type') or '').strip()
        year_month = (request.args.get('month') or '').strip()
        div_filter = request.args.get('division_id')
        cfg = {
            'cash': {'label': '\u73fe\u91d1\u51fa\u7d0d\u5e33', 'acct': '\u73fe\u91d1', 'bal': '\u6b8b\u9ad8'},
            'bank': {'label': '\u9810\u91d1\u51fa\u7d0d\u5e33', 'acct': '\u666e\u901a\u9810\u91d1', 'bal': '\u6b8b\u9ad8'},
            'card': {'label': '\u7d4c\u8cbb\u30af\u30ec\u30ab\u5e33', 'acct': '\u672a\u6255\u91d1', 'bal': '\u672a\u6255\u6b8b\u9ad8'},
            'sales': {'label': '\u58f2\u4e0a\u53f0\u5e33', 'acct': '\u58f2\u4e0a', 'bal': '\u58f2\u4e0a\u7d2f\u8a08'},
        }.get(sub_type)
        if cfg is None:
            return jsonify({'status': 'error', 'message': 'bad_type'}), 400
        # entries\u53d6\u5f97(entries API\u3068\u540c\u3058\u6761\u4ef6)
        query = supabase.table('journal_entries').select(
            '*, debit:debit_account_id(code,name,category), credit:credit_account_id(code,name,category)'
        ).eq('facility_code', f_code)
        if year_month:
            y, m = year_month.split('-')
            from datetime import date as _date
            start = _date(int(y), int(m), 1).isoformat()
            if int(m) == 12:
                end = _date(int(y)+1, 1, 1).isoformat()
            else:
                end = _date(int(y), int(m)+1, 1).isoformat()
            query = query.gte('entry_date', start).lt('entry_date', end)
        if div_filter == 'none':
            query = query.is_('division_id', 'null')
        elif div_filter and div_filter != 'all':
            query = query.eq('division_id', int(div_filter))
        res = query.order('entry_date', desc=False).execute()
        rows_data = res.data or []
        # \u4e8b\u696d\u540d\u89e3\u6c7a
        dv = supabase.table('ledger_divisions').select('id,name').eq('facility_code', f_code).execute()
        div_map = {d['id']: d['name'] for d in (dv.data or [])}
        acct = cfg['acct']

        def _match(e):
            d = (e.get('debit') or {})
            c = (e.get('credit') or {})
            if sub_type == 'sales':
                return (c.get('category') == '\u53ce\u76ca')
            return (d.get('name') == acct) or (c.get('name') == acct)

        ents = [e for e in rows_data if _match(e)]
        # ledger-subledger-pdf-layout-v1: \u753b\u9762/Excel\u3068\u540c\u3058\u4e26\u3073\u9806\u306b(\u65e5\u4ed8\u9806\uff0b\u540c\u65e5\u5185\u306f\u5165\u91d1\u512a\u5148)
        def _is_out(e):
            # \u5165\u91d1(\u501f\u65b9=\u5bfe\u8c61\u79d1\u76ee\u307e\u305f\u306fsales)=0, \u51fa\u91d1=1
            if sub_type == 'sales':
                return 0
            d = (e.get('debit') or {})
            return 0 if d.get('name') == acct else 1
        ents = sorted(
            list(enumerate(ents)),
            key=lambda t: (str(t[1].get('entry_date') or ''), _is_out(t[1]), t[0])
        )
        ents = [t[1] for t in ents]
        # \u4e8b\u696d\u90e8\u3067\u7d5e\u3063\u3066\u3044\u308b\u304b(\u7279\u5b9a\u4e8b\u696d\u90e8) \u2192 \u4e8b\u696d\u90e8\u5217\u3092\u7701\u304d\u30d8\u30c3\u30c0\u30fc\u306b\u51fa\u3059
        single_div_name = ''
        show_div_col = True
        if div_filter and div_filter not in ('all', 'none'):
            try:
                single_div_name = div_map.get(int(div_filter), '')
            except (TypeError, ValueError):
                single_div_name = ''
            show_div_col = False
        # \u884c\u751f\u6210\uff0b\u6b8b\u9ad8
        balance = 0
        total_in = 0
        total_out = 0
        body_rows = []
        for e in ents:
            d = (e.get('debit') or {})
            c = (e.get('credit') or {})
            in_amt = 0
            out_amt = 0
            amt = e.get('amount') or 0
            if sub_type == 'sales':
                in_amt = amt
            elif d.get('name') == acct:
                in_amt = amt
            else:
                out_amt = amt
            balance += in_amt - out_amt
            total_in += in_amt
            total_out += out_amt
            if sub_type == 'sales':
                opposite = d.get('name') or ''
            else:
                opposite = (c.get('name') if d.get('name') == acct else d.get('name')) or ''
            div_name = div_map.get(e.get('division_id'), '') if e.get('division_id') else ''
            _div_cell = ('<td class="divcol">' + _esc(div_name) + '</td>') if show_div_col else ''
            body_rows.append(
                '<tr><td class="datecol">' + str(e.get('entry_date') or '') + '</td>'
                + _div_cell
                + '<td class="acctcol">' + _esc(opposite) + '</td>'
                + '<td>' + _esc(e.get('description') or '') + '</td>'
                + '<td class="num">' + (('\uffe5' + format(in_amt, ',')) if in_amt else '') + '</td>'
                + '<td class="num">' + (('\uffe5' + format(out_amt, ',')) if (out_amt and sub_type != 'sales') else '') + '</td>'
                + '<td class="num">\uffe5' + format(balance, ',') + '</td></tr>'
            )
        in_label = '\u58f2\u4e0a' if sub_type == 'sales' else '\u5165\u91d1'
        out_label = '' if sub_type == 'sales' else '\u51fa\u91d1'
        # ledger-subledger-pdf-layout-v1: \u4e8b\u696d\u90e8\u5217\u306e\u51fa\u3057\u5206\u3051\u30fb\u5217\u5e45\u30fb\u6298\u308a\u8fd4\u3057\u6291\u5236
        _div_th = '<th class="divcol">\u4e8b\u696d\u90e8</th>' if show_div_col else ''
        _ncols = 7 if show_div_col else 6
        _foot_span = 4 if show_div_col else 3
        # colgroup\u3067\u5217\u5e45\u3092\u660e\u793a(\u7e26\u66f8\u304d\u9632\u6b62)
        if show_div_col:
            _colgroup = ('<colgroup><col style="width:62px"><col style="width:96px">'
                         '<col style="width:84px"><col><col style="width:74px">'
                         '<col style="width:74px"><col style="width:80px"></colgroup>')
        else:
            _colgroup = ('<colgroup><col style="width:62px"><col style="width:96px"><col>'
                         '<col style="width:74px"><col style="width:74px"><col style="width:80px"></colgroup>')
        _subtitle = (_esc(f_code) + ' / \u5bfe\u8c61\u6708: ' + _esc(year_month))
        if single_div_name:
            _subtitle += ' / \u4e8b\u696d\u90e8: ' + _esc(single_div_name)
        html_str = (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            'body{font-family:sans-serif;font-size:11pt;margin:14mm;}'
            'h2{font-size:15pt;margin:0 0 2px;}'
            'p{font-size:10pt;color:#555;margin:0 0 10px;}'
            'table{width:100%;border-collapse:collapse;table-layout:fixed;}'
            'th{background:#e8f0fe;padding:5px 6px;text-align:left;font-size:9pt;border-bottom:1px solid #ccc;}'
            'td{padding:5px 6px;border-bottom:1px solid #eee;font-size:9pt;vertical-align:top;word-break:break-all;}'
            'td.num{text-align:right;white-space:nowrap;}'
            'td.datecol,td.divcol,td.acctcol{white-space:nowrap;}'
            'td.acctcol{word-break:keep-all;}'
            'tfoot td{font-weight:bold;background:#f8f9fa;}'
            '@page{size:A4 landscape;margin:10mm;}'
            '</style></head><body>'
            + '<h2>' + cfg['label'] + '</h2>'
            + '<p>' + _subtitle + '</p>'
            + '<table>' + _colgroup + '<thead><tr>'
            + '<th>\u65e5\u4ed8</th>' + _div_th + '<th>\u76f8\u624b\u79d1\u76ee</th><th>\u6458\u8981</th>'
            + '<th class="num">' + in_label + '</th><th class="num">' + out_label + '</th><th class="num">' + cfg['bal'] + '</th>'
            + '</tr></thead><tbody>'
            + (''.join(body_rows) if body_rows else ('<tr><td colspan="' + str(_ncols) + '">\u30c7\u30fc\u30bf\u306f\u3042\u308a\u307e\u305b\u3093</td></tr>'))
            + '</tbody><tfoot><tr>'
            + '<td colspan="' + str(_foot_span) + '">\u5408\u8a08</td>'
            + '<td class="num">\uffe5' + format(total_in, ',') + '</td>'
            + '<td class="num">' + (('\uffe5' + format(total_out, ',')) if sub_type != 'sales' else '') + '</td>'
            + '<td class="num">\uffe5' + format(balance, ',') + '</td>'
            + '</tr></tfoot></table></body></html>'
        )
        import pdfkit, shutil  # ledger-subledger-pdf-fix-v1
        options = {'encoding': 'UTF-8', 'no-outline': None, 'quiet': ''}
        wk_path = shutil.which('wkhtmltopdf') or '/usr/local/bin/wkhtmltopdf'
        config = pdfkit.configuration(wkhtmltopdf=wk_path)
        pdf_bytes = pdfkit.from_string(html_str, False, options=options, configuration=config)
        fname = cfg['label'] + '_' + (year_month or 'all') + '.pdf'
        fname_ascii = 'subledger_' + sub_type + '_' + (year_month or 'all') + '.pdf'
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename="' + fname_ascii + '"; filename*=UTF-8\'\'' + quote(fname)
        return response
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/orico_pdf', methods=['GET'])  # ledger-orico-pdf-v1
@login_required
def api_ledger_orico_pdf():
    """クレカ明細をPDF出力する(支払日セクション×明細表)。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    if not is_credit_csv_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': 'クレカ明細モードが有効ではありません'}), 403
    try:
        flt = request.args.get('filter', 'all')
        res = supabase.table('ledger_orico_statements').select(
            'id,payment_date,used_date,used_for,amount,amazon_detail,account_id'
        ).eq('facility_code', f_code).order('payment_date', desc=True).order('used_date').execute()
        rows = res.data or []
        # フィルタ(仕訳状態 = account_id 有無)
        def _linked(r):
            a = r.get('account_id')
            return a is not None and a != ''
        if flt == 'unlinked':
            rows = [r for r in rows if not _linked(r)]
        elif flt == 'linked':
            rows = [r for r in rows if _linked(r)]
        # 科目名解決
        acc_res = supabase.table('accounts').select('id,name').eq('facility_code', f_code).execute()
        acc_map = {a['id']: a.get('name') or '' for a in (acc_res.data or [])}
        # Amazon商品名抽出
        def _amz(raw):
            if not raw:
                return ''
            try:
                import json as _json
                d = _json.loads(raw)
            except Exception:
                return str(raw)
            if not isinstance(d, dict):
                return str(raw)
            items = d.get('items') or []
            if items:
                return ' / '.join(str(x) for x in items)
            return d.get('summary') or ''
        # 支払日でグループ化
        groups = {}
        for r in rows:
            key = r.get('payment_date') or '\u4e0d\u660e'
            groups.setdefault(key, []).append(r)
        grand_total = 0
        sections = []
        for key in sorted(groups.keys(), reverse=True):
            items = groups[key]
            sub_total = sum((it.get('amount') or 0) for it in items)
            grand_total += sub_total
            body = []
            for it in items:
                body.append(
                    '<tr>'
                    + '<td class="datecol">' + _esc(it.get('used_date') or '') + '</td>'
                    + '<td class="forcol">' + _esc(it.get('used_for') or '') + '</td>'
                    + '<td class="num">\uffe5' + format(it.get('amount') or 0, ',') + '</td>'
                    + '<td class="acctcol">' + _esc(acc_map.get(it.get('account_id'), '')) + '</td>'
                    + '<td>' + _esc(_amz(it.get('amazon_detail'))) + '</td>'
                    + '</tr>'
                )
            sections.append(
                '<div class="sec">' + _esc(key) + ' \u652f\u6255\u3044\u5206'
                + ' <span class="sectot">\uffe5' + format(sub_total, ',') + '</span></div>'
                + '<table><colgroup><col style="width:70px"><col style="width:150px">'
                + '<col style="width:80px"><col style="width:90px"><col></colgroup>'
                + '<thead><tr><th>\u5229\u7528\u65e5</th><th>\u5229\u7528\u5148</th>'
                + '<th class="num">\u91d1\u984d</th><th>\u52d8\u5b9a\u79d1\u76ee</th><th>Amazon\u5546\u54c1\u540d</th></tr></thead>'
                + '<tbody>' + (''.join(body) if body else '<tr><td colspan="5">\u660e\u7d30\u306a\u3057</td></tr>') + '</tbody></table>'
            )
        html_str = (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            'body{font-family:sans-serif;font-size:11pt;margin:10mm;}'
            'h2{font-size:15pt;margin:0 0 2px;}'
            'p{font-size:10pt;color:#555;margin:0 0 10px;}'
            '.sec{font-size:11pt;font-weight:bold;color:#1a73e8;border-bottom:2px solid #1a73e8;'
            'padding:6px 2px 3px;margin:12px 0 4px;}'
            '.sectot{float:right;font-size:10pt;}'
            'table{width:100%;border-collapse:collapse;table-layout:fixed;}'
            'th{background:#e8f0fe;padding:4px 6px;text-align:left;font-size:9pt;border-bottom:1px solid #ccc;}'
            'td{padding:4px 6px;border-bottom:1px solid #eee;font-size:9pt;vertical-align:top;word-break:break-all;}'
            'td.num,th.num{text-align:right;white-space:nowrap;}'
            'td.datecol,td.acctcol{white-space:nowrap;}'
            '@page{size:A4 landscape;margin:10mm;}'
            '</style></head><body>'
            + '<h2>\u30af\u30ec\u30ab\u660e\u7d30</h2>'
            + '<p>' + _esc(f_code) + ' / \u5408\u8a08 \uffe5' + format(grand_total, ',') + '</p>'
            + (''.join(sections) if sections else '<p>\u660e\u7d30\u306f\u3042\u308a\u307e\u305b\u3093</p>')
            + '</body></html>'
        )
        from flask import make_response  # ledger-orico-pdf-fix-v1
        from urllib.parse import quote  # ledger-orico-pdf-fix-v1
        import pdfkit, shutil
        options = {'encoding': 'UTF-8', 'no-outline': None, 'quiet': ''}
        wk_path = shutil.which('wkhtmltopdf') or '/usr/local/bin/wkhtmltopdf'
        config = pdfkit.configuration(wkhtmltopdf=wk_path)
        pdf_bytes = pdfkit.from_string(html_str, False, options=options, configuration=config)
        today = datetime.now(tokyo_tz).strftime('%Y-%m-%d')
        fname = 'クレカ明細_' + today + '.pdf'
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename="credit_statement_' + today + '.pdf"; filename*=UTF-8\'\'' + quote(fname)
        return response
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/monthly_balance', methods=['GET'])  # ledger-monthly-balance-api-v1
@login_required
def api_ledger_monthly_balance_get():
    """月初残高(帳尻合わせ表示補正)を事業部別に返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        ledger_type = request.args.get('ledger_type', 'cash')
        month = request.args.get('month')
        if not month:
            return jsonify({'status': 'error', 'message': 'monthが必要です'}), 400
        res = (supabase.table('ledger_monthly_balances')
               .select('division_id,amount')
               .eq('facility_code', f_code).eq('ledger_type', ledger_type).eq('month', month)
               .execute())
        rows = res.data or []
        total = sum(int(r.get('amount') or 0) for r in rows)
        return jsonify({'status': 'success', 'balances': rows, 'total': total})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/monthly_balance', methods=['POST'])  # ledger-monthly-balance-api-v1
@login_required
def api_ledger_monthly_balance_save():
    """月初残高を事業部別にupsertする。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        ledger_type = data.get('ledger_type', 'cash')
        month = data.get('month')
        if not month:
            return jsonify({'status': 'error', 'message': 'monthが必要です'}), 400
        _raw_div = data.get('division_id')
        division_id = int(_raw_div) if _raw_div else None
        amount = int(data.get('amount') or 0)
        payload = {
            'facility_code': f_code,
            'division_id': division_id,
            'ledger_type': ledger_type,
            'month': month,
            'amount': amount,
        }
        supabase.table('ledger_monthly_balances').upsert(
            payload, on_conflict='facility_code,division_id,ledger_type,month').execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

def _ledger_fiscal_period_start(f_code, ref_date=None):  # ledger-opening-balance-api-v1
    """決算月から、ref_date(既定=今日)が属する決算期の開始日(date)を返す。
    例: 決算月1「10」 → 期初=11/1。当月が決算月以下なら前年の(決算月+1)月から、
    超えていれば当年の(決算月+1)月から。"""
    supabase = get_supabase()
    fem = 10
    try:
        s = supabase.table('ledger_settings').select('fiscal_year_end_month').eq('facility_code', f_code).execute()
        if s.data and s.data[0].get('fiscal_year_end_month'):
            fem = int(s.data[0]['fiscal_year_end_month'])
    except Exception:
        fem = 10
    if not (1 <= fem <= 12):
        fem = 10
    if ref_date is None:
        ref_date = datetime.now(tokyo_tz).date()
    start_month = fem % 12 + 1  # 決算月の翌月
    y = ref_date.year
    # ref_date の月が期初月以上ならその年の期初、未満なら前年の期初
    if ref_date.month >= start_month:
        py = y
    else:
        py = y - 1
    import datetime as _dt
    return _dt.date(py, start_month, 1)

# === ledger-fiscal-close-v1: 決算確定 中核ヘルパー & API ===
def _ledger_period_bounds(f_code, period_start_iso=None, ref_date=None):
    """period_start(iso) を起点に (period_start, period_end) を date で返す。
    period_start_iso 省略時は ref_date(既定=今日) が属する期を使う。"""
    import datetime as _dt
    if period_start_iso:
        ps = _dt.date.fromisoformat(period_start_iso)
    else:
        ps = _ledger_fiscal_period_start(f_code, ref_date)
    pe = _dt.date(ps.year + 1, ps.month, 1) - _dt.timedelta(days=1)
    return ps, pe


def _ledger_period_end_balances(supabase, f_code, period_start_iso):
    """事業部別の期末現金残高を算出して {division_id(str): amount} で返す。
    期初残高 + 期間内の全仕訳(auto_fill/transfer含む)の現金増減。
    現金=借方なら+、貸方なら-。確定済みの帳簿実態をそのまま積算する。"""
    import datetime as _dt
    ps, pe = _ledger_period_bounds(f_code, period_start_iso)
    ps_iso, pe_iso = ps.isoformat(), pe.isoformat()
    # 現金科目
    cash_res = supabase.table('accounts').select('id').eq('facility_code', f_code).eq('code', '101').execute()
    if not cash_res.data:
        return {}
    cash_id = cash_res.data[0]['id']
    # 期初残高
    ob_res = (supabase.table('ledger_opening_balances')
              .select('division_id,amount')
              .eq('facility_code', f_code).eq('period_start', ps_iso).execute())
    bal = {}
    for r in (ob_res.data or []):
        if r.get('division_id') is not None:
            bal[int(r['division_id'])] = int(r.get('amount') or 0)
    # 期間内の全仕訳（現金が絡むものだけ集計）
    je = (supabase.table('journal_entries')
          .select('amount,debit_account_id,credit_account_id,division_id')
          .eq('facility_code', f_code)
          .gte('entry_date', ps_iso).lte('entry_date', pe_iso).execute())
    for e in (je.data or []):
        div = e.get('division_id')
        if div is None:
            continue
        div = int(div)
        amt = int(e.get('amount') or 0)
        if e.get('debit_account_id') == cash_id:
            bal[div] = bal.get(div, 0) + amt
        if e.get('credit_account_id') == cash_id:
            bal[div] = bal.get(div, 0) - amt
    return {str(k): int(v) for k, v in bal.items()}


def _ledger_is_period_closed(supabase, f_code, entry_date):
    """entry_date(iso str or date) が確定済み期に属するなら True。
    確定ガードの共通判定。例外時は安全側で False（ブロックしない）。"""
    try:
        import datetime as _dt
        d = _dt.date.fromisoformat(entry_date) if isinstance(entry_date, str) else entry_date
        ps = _ledger_fiscal_period_start(f_code, d)
        res = (supabase.table('ledger_fiscal_closes')
               .select('is_closed')
               .eq('facility_code', f_code).eq('period_start', ps.isoformat())
               .eq('is_closed', True).execute())
        return bool(res.data)
    except Exception:
        return False


@app.route('/api/ledger/fiscal_close', methods=['GET'])  # ledger-fiscal-close-v1
@login_required
def api_ledger_fiscal_close_list():
    """直近の決算期一覧（過去5期＋当期）と確定状態を返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        import datetime as _dt
        today = datetime.now(tokyo_tz).date()
        cur_ps = _ledger_fiscal_period_start(f_code)
        # 当期を含む過去6期分を列挙
        periods = []
        ps = cur_ps
        for _i in range(6):
            pe = _dt.date(ps.year + 1, ps.month, 1) - _dt.timedelta(days=1)
            periods.append((ps, pe))
            ps = _dt.date(ps.year - 1, ps.month, 1)
        # 確定状態を取得
        closes = (supabase.table('ledger_fiscal_closes')
                  .select('period_start,is_closed,closed_at,closed_by')
                  .eq('facility_code', f_code).execute())
        closed_map = {}
        for c in (closes.data or []):
            closed_map[c.get('period_start')] = c
        items = []
        for (p_s, p_e) in periods:
            ps_iso = p_s.isoformat()
            c = closed_map.get(ps_iso)
            is_closed = bool(c and c.get('is_closed'))
            label = f"{p_s.year}年{p_s.month}月～{p_e.year}年{p_e.month}月期"
            # 決算月超過で未確定なら overdue フラグ
            overdue = (not is_closed) and (today > p_e)
            items.append({
                'period_start': ps_iso,
                'period_end': p_e.isoformat(),
                'label': label,
                'is_closed': is_closed,
                'closed_at': (c or {}).get('closed_at'),
                'closed_by': (c or {}).get('closed_by'),
                'is_current': (p_s == cur_ps),
                'overdue': overdue,
            })
        return jsonify({'status': 'success', 'periods': items})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/fiscal_close', methods=['POST'])  # ledger-fiscal-close-v1
@login_required
def api_ledger_fiscal_close_do():
    """決算確定。期末残高を算出して翌期初へ上書きコピー、スナップショット保存。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        import datetime as _dt
        data = request.json or {}
        ps_iso = data.get('period_start')
        if not ps_iso:
            return jsonify({'status': 'error', 'message': 'period_start が必要です'}), 400
        ps, pe = _ledger_period_bounds(f_code, ps_iso)
        # 期末残高を算出
        end_bal = _ledger_period_end_balances(supabase, f_code, ps_iso)
        # 確定レコードを upsert
        supabase.table('ledger_fiscal_closes').upsert({
            'facility_code': f_code,
            'period_start': ps.isoformat(),
            'period_end': pe.isoformat(),
            'is_closed': True,
            'closed_at': datetime.now(tokyo_tz).isoformat(),
            'closed_by': my_name,
            'closing_balances': end_bal,
        }, on_conflict='facility_code,period_start').execute()
        # 翌期初 = 期末日の翌日
        next_ps = (pe + _dt.timedelta(days=1)).isoformat()
        # 翌期初残高へ事業部別に上書きコピー
        copied = []
        for div_str, amt in end_bal.items():
            supabase.table('ledger_opening_balances').upsert({
                'facility_code': f_code,
                'period_start': next_ps,
                'division_id': int(div_str),
                'amount': int(amt),
            }, on_conflict='facility_code,period_start,division_id').execute()
            copied.append({'division_id': int(div_str), 'amount': int(amt)})
        # 翌期が当期なら累積補填を再計算（期初が変わったため）
        try:
            _today = datetime.now(tokyo_tz).date()
            _next_ps_d = _dt.date.fromisoformat(next_ps)
            if _ledger_fiscal_period_start(f_code) == _next_ps_d:
                _ledger_recalc_day(supabase, f_code, next_ps)
        except Exception as _re:
            import logging
            logging.warning(f'fiscal_close autorecalc error: {_re}')
        return jsonify({
            'status': 'success',
            'message': f"{ps.year}年{ps.month}月期を確定しました。期末残高を翌期初へ反映しました。",
            'period_start': ps.isoformat(),
            'next_period_start': next_ps,
            'copied': copied,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/fiscal_close/cancel', methods=['POST'])  # ledger-fiscal-close-v1
@login_required
def api_ledger_fiscal_close_cancel():
    """決算確定の解除。is_closed=False に更新（翌期初残高は変更しない）。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        ps_iso = data.get('period_start')
        if not ps_iso:
            return jsonify({'status': 'error', 'message': 'period_start が必要です'}), 400
        supabase.table('ledger_fiscal_closes').update({
            'is_closed': False,
        }).eq('facility_code', f_code).eq('period_start', ps_iso).execute()
        return jsonify({'status': 'success', 'message': '決算確定を解除しました。'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/opening_balance', methods=['GET'])  # ledger-opening-balance-api-v1
@login_required
def api_ledger_opening_balance_get():
    """期初残高(累積補填の起点)を事業部別に返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        ps_arg = request.args.get('period_start')
        if ps_arg:
            period_start = ps_arg
        else:
            period_start = _ledger_fiscal_period_start(f_code).isoformat()
        res = (supabase.table('ledger_opening_balances')
               .select('division_id,amount')
               .eq('facility_code', f_code).eq('period_start', period_start)
               .execute())
        rows = res.data or []
        # 期末(期初の1年後の前日)もラベル用に算出
        import datetime as _dt
        _ps = _dt.date.fromisoformat(period_start)
        _pe = _dt.date(_ps.year + 1, _ps.month, 1) - _dt.timedelta(days=1)
        label = f"{_ps.year}年{_ps.month}月～{_pe.year}年{_pe.month}月期"
        return jsonify({'status': 'success', 'period_start': period_start, 'period_label': label, 'balances': rows})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/opening_balance', methods=['POST'])  # ledger-opening-balance-api-v1
@login_required
def api_ledger_opening_balance_save():
    """期初残高を事業部別にupsertする。period_start省略時は現在期。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        ps_arg = data.get('period_start')
        if ps_arg:
            period_start = ps_arg
        else:
            period_start = _ledger_fiscal_period_start(f_code).isoformat()
        _raw_div = data.get('division_id')
        division_id = int(_raw_div) if _raw_div else None
        amount = int(data.get('amount') or 0)
        payload = {
            'facility_code': f_code,
            'division_id': division_id,
            'period_start': period_start,
            'amount': amount,
        }
        supabase.table('ledger_opening_balances').upsert(
            payload, on_conflict='facility_code,division_id,period_start').execute()
        # ledger-opening-autorecalc-v1: 期初残高保存後、当該決算期の累積補填を自動再計算
        try:
            _ledger_recalc_day(supabase, f_code, period_start)
        except Exception as _re:
            import logging as _lg
            _lg.warning(f'opening_balance autorecalc error: {_re}')
        return jsonify({'status': 'success', 'period_start': period_start})
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
        # ledger-fiscal-close-guard-v1: 確定済み期への事業間移動をブロック
        if _ledger_is_period_closed(supabase, f_code, entry_date):
            return jsonify({'status': 'error', 'code': 'fiscal_closed',
                            'message': 'この日付の決算期は確定済みです。決算確定を解除してください。'}), 409
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
        # ledger-fiscal-close-guard-v1: 確定済み期への保存/編集をブロック
        _g_newdate = data.get('entry_date')
        if _g_newdate and _ledger_is_period_closed(supabase, f_code, _g_newdate):
            return jsonify({'status': 'error', 'code': 'fiscal_closed',
                            'message': 'この日付の決算期は確定済みです。編集するには決算確定を解除してください。'}), 409
        _g_eid = data.get('id')
        if _g_eid:
            try:
                _g_old = supabase.table('journal_entries').select('entry_date').eq('id', _g_eid).eq('facility_code', f_code).execute()
                _g_olddate = _g_old.data[0]['entry_date'] if _g_old.data else None
                if _g_olddate and _ledger_is_period_closed(supabase, f_code, _g_olddate):
                    return jsonify({'status': 'error', 'code': 'fiscal_closed',
                                    'message': 'この仕訳が属する決算期は確定済みです。編集するには決算確定を解除してください。'}), 409
            except Exception:
                pass
        # ledger-credit-ocrguard-v1: CSV方式はOCRクレカの仕訳化を弾く(クレカはCSVが正)
        _rcpt_id = data.get('receipt_id')
        if _rcpt_id and not data.get('id') and is_credit_csv_enabled(supabase, f_code):
            try:
                _rc = supabase.table('receipts').select('ocr_result').eq('id', _rcpt_id).eq('facility_code', f_code).execute()
                _ocr = (_rc.data[0].get('ocr_result') if _rc.data else None) or {}
                if isinstance(_ocr, dict) and _ocr.get('payment_method') == 'credit':
                    return jsonify({'status': 'error', 'code': 'credit_csv_blocked',
                                    'message': 'クレジットカードの利用はクレカ明細(CSV取込)で記録します。この領収書は保管庫に保管されます。'}), 409
            except Exception:
                pass
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
            # ledger-receipt-link-v1: OCRレシート由来なら receipts.entry_id を紐付け
            _rid = data.get('receipt_id')
            if _rid and new_id:
                try:
                    supabase.table('receipts').update({'entry_id': new_id}).eq('id', _rid).eq('facility_code', f_code).execute()
                except Exception:
                    pass
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
        # ledger-fiscal-close-guard-v1: 確定済み期の削除をブロック
        if del_date and _ledger_is_period_closed(supabase, f_code, del_date):
            return jsonify({'status': 'error', 'code': 'fiscal_closed',
                            'message': 'この仕訳が属する決算期は確定済みです。削除するには決算確定を解除してください。'}), 409
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
                    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    partial_item = []  # ledger-credit-itempartial-v1
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
            elif mt == 'partial' and kt == 'item':  # ledger-credit-itempartial-v1
                partial_item.append((key, aid))
            elif kt == 'item':
                exact_item[key] = aid
            elif kt == 'store':
                exact_store[key] = aid
    except Exception:
        pass
    return exact_item, exact_store, partial, partial_item  # ledger-credit-itempartial-v1


def _cr_suggest_one(used_for, amazon_detail, rules):
    """1明細の科目推定。 (account_id, matched_by) を返す。未割当は (None,'none')。"""
    # ledger-credit-itempartial-v1: 4要素(item部分一致を追加)。後方互換で3要素も許容
    if len(rules) == 4:
        exact_item, exact_store, partial, partial_item = rules
    else:
        exact_item, exact_store, partial = rules
        partial_item = []
    item = _cr_norm(_cr_item_from_detail(amazon_detail))
    store = _cr_norm(used_for)
    if item and item in exact_item:
        return exact_item[item], 'item_exact'
    if store and store in exact_store:
        return exact_store[store], 'store_exact'
    for kw, aid in partial_item:  # ledger-credit-itempartial-v1: 品名部分一致
        if kw and item and kw in item:
            return aid, 'item_partial'
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    if not is_credit_csv_enabled(supabase, f_code):
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
    partial_item = []  # ledger-credit-itempartial-v1
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
            elif mt == 'partial' and kt == 'item':  # ledger-credit-itempartial-v1
                partial_item.append((key, did))
            elif kt == 'item':
                exact_item[key] = did
            elif kt == 'store':
                exact_store[key] = did
    except Exception:
        pass
    return exact_item, exact_store, partial, partial_item  # ledger-credit-itempartial-v1


def _dr_suggest_one(used_for, amazon_detail, rules):
    """1明細の事業推定。(division_id, matched_by)。未割当は(None,'none')。"""  # ledger-credit-3b-div-v1
    # ledger-credit-itempartial-v1: 4要素対応
    if len(rules) == 4:
        exact_item, exact_store, partial, partial_item = rules
    else:
        exact_item, exact_store, partial = rules
        partial_item = []
    item = _cr_norm(_cr_item_from_detail(amazon_detail))
    store = _cr_norm(used_for)
    if item and item in exact_item:
        return exact_item[item], 'item_exact'
    if store and store in exact_store:
        return exact_store[store], 'store_exact'
    for kw, did in partial_item:  # ledger-credit-itempartial-v1
        if kw and item and kw in item:
            return did, 'item_partial'
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
    if not is_credit_csv_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        # 科目のpartial(store/item両方)  # ledger-credit-itempartial-v1
        cr = supabase.table('ledger_credit_rules').select('key_text,account_id,key_type')\
            .eq('facility_code', f_code).in_('key_type', ['store', 'item'])\
            .eq('match_type', 'partial').execute()
        # 事業のpartial(store/item両方)  # ledger-credit-itempartial-v1
        dr = supabase.table('ledger_division_rules').select('key_text,division_id,key_type')\
            .eq('facility_code', f_code).in_('key_type', ['store', 'item'])\
            .eq('match_type', 'partial').execute()
        acc = supabase.table('accounts').select('id,code,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        acc_map = {a['id']: a for a in (acc.data or [])}
        dv = supabase.table('ledger_divisions').select('id,name')\
            .eq('facility_code', f_code).eq('is_active', True).execute()
        div_map = {d['id']: d for d in (dv.data or [])}
        merged = {}  # ledger-credit-itempartial-v1: (key_type, keyword) 単位で区別
        for r in (cr.data or []):
            k = _cr_norm(r.get('key_text'))
            kt = r.get('key_type') or 'store'
            if not k:
                continue
            mk = (kt, k)
            merged.setdefault(mk, {'keyword': k, 'key_type': kt, 'account': None, 'division': None})
            aid = r.get('account_id')
            if aid is not None and aid in acc_map:
                a = acc_map[aid]
                merged[mk]['account'] = {'id': a['id'], 'code': a['code'], 'name': a['name']}
        for r in (dr.data or []):
            k = _cr_norm(r.get('key_text'))
            kt = r.get('key_type') or 'store'
            if not k:
                continue
            mk = (kt, k)
            merged.setdefault(mk, {'keyword': k, 'key_type': kt, 'account': None, 'division': None})
            did = r.get('division_id')
            if did is not None and did in div_map:
                d = div_map[did]
                merged[mk]['division'] = {'id': d['id'], 'name': d['name']}
        rules = sorted(merged.values(), key=lambda x: (x['key_type'], x['keyword']))
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
    if not is_credit_csv_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        import datetime as _dt
        data = request.json or {}
        kw = _cr_norm(data.get('keyword'))
        aid = data.get('account_id')
        did = data.get('division_id')
        kt = data.get('key_type') or 'store'  # ledger-credit-itempartial-v1
        if kt not in ('store', 'item'):
            kt = 'store'
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
            .eq('facility_code', f_code).eq('key_type', kt)\
            .eq('match_type', 'partial').eq('key_text', kw).execute()  # ledger-credit-itempartial-v1
        if _e.data:
            supabase.table('ledger_credit_rules').update({
                'account_id': aid, 'match_type': 'partial', 'updated_at': now,
            }).eq('id', _e.data[0]['id']).execute()
        else:
            supabase.table('ledger_credit_rules').insert({
                'facility_code': f_code, 'key_type': kt, 'key_text': kw,
                'match_type': 'partial', 'account_id': aid, 'source': 'manual',
            }).execute()
        # 事業 partial upsert(division_idが渡されたときのみ)
        if did is not None:
            _dchk = supabase.table('ledger_divisions').select('id').eq('id', did)\
                .eq('facility_code', f_code).eq('is_active', True).execute()
            if _dchk.data:
                _de = supabase.table('ledger_division_rules').select('id')\
                    .eq('facility_code', f_code).eq('key_type', kt)\
                    .eq('match_type', 'partial').eq('key_text', kw).execute()  # ledger-credit-itempartial-v1
                if _de.data:
                    supabase.table('ledger_division_rules').update({
                        'division_id': did, 'match_type': 'partial', 'updated_at': now,
                    }).eq('id', _de.data[0]['id']).execute()
                else:
                    supabase.table('ledger_division_rules').insert({
                        'facility_code': f_code, 'key_type': kt, 'key_text': kw,
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
    if not is_credit_csv_enabled(supabase, f_code):
        return jsonify({'status': 'error', 'message': '\u30af\u30ec\u30ab\u660e\u7d30\u30e2\u30fc\u30c9\u304c\u6709\u52b9\u3067\u306f\u3042\u308a\u307e\u305b\u3093'}), 403
    try:
        data = request.json or {}
        kw = _cr_norm(data.get('keyword'))
        kt = data.get('key_type') or 'store'  # ledger-credit-itempartial-v1
        if kt not in ('store', 'item'):
            kt = 'store'
        if not kw:
            return jsonify({'status': 'error', 'message': 'keyword required'}), 400
        supabase.table('ledger_credit_rules').delete()\
            .eq('facility_code', f_code).eq('key_type', kt)\
            .eq('match_type', 'partial').eq('key_text', kw).execute()
        supabase.table('ledger_division_rules').delete()\
            .eq('facility_code', f_code).eq('key_type', kt)\
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
    if not is_credit_csv_enabled(supabase, f_code):
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
        for r in (res.data or []):  # ledger-credit-3bpp-v1
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
            # ledger-credit-3bpp-v1: 全件モードでは「推定が現在の割当と同じ」明細はスキップ
            if not only_unassigned:
                same_a = (cur_a == aid) or (aid is None)
                same_d = (cur_d == did) or (did is None)
                if cur_a is not None and same_a and same_d:
                    continue
            acct = None
            if aid is not None and aid in acc_map:
                a = acc_map[aid]
                acct = {'id': a['id'], 'code': a['code'], 'name': a['name']}
            dvv = None
            if did is not None and did in div_map:
                d = div_map[did]
                dvv = {'id': d['id'], 'name': d['name']}
            # ledger-credit-3bpp-v1: 現在の割当(全件モードの差分表示用)
            cur_acct = None
            if cur_a is not None and cur_a in acc_map:
                _ca = acc_map[cur_a]
                cur_acct = {'id': _ca['id'], 'code': _ca['code'], 'name': _ca['name']}
            cur_dvv = None
            if cur_d is not None and cur_d in div_map:
                _cd = div_map[cur_d]
                cur_dvv = {'id': _cd['id'], 'name': _cd['name']}
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
                'current_account': cur_acct,  # ledger-credit-3bpp-v1
                'current_division': cur_dvv,  # ledger-credit-3bpp-v1
                'is_change': (cur_a is not None),  # ledger-credit-3bpp-v1 True=既存を上書き
            })
        return jsonify({'status': 'success', 'previews': out})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _rcpt_suggest(supabase, f_code, vendor, description, rules, drules):
    """領収書用の推定。vendor=店名, description=内容。
    商品名完全 -> 店名完全 -> 店名部分 の順。 (account_id, by) / (division_id, dby)。"""  # ledger-receipt-learn-v1
    exact_item, exact_store, partial = rules
    d_item, d_store, d_partial = drules
    item = _cr_norm(description)
    store = _cr_norm(vendor)

    def _pick(ei, es, pa):
        if item and item in ei:
            return ei[item], 'item_exact'
        if store and store in es:
            return es[store], 'store_exact'
        for kw, v in pa:
            if kw and kw in store:
                return v, 'store_partial'
        return None, 'none'

    aid, by = _pick(exact_item, exact_store, partial)
    did, dby = _pick(d_item, d_store, d_partial)
    return aid, by, did, dby


@app.route('/api/ledger/receipt_suggest', methods=['POST'])  # ledger-receipt-learn-v1
@login_required
def api_ledger_receipt_suggest():
    """領収書OCRの vendor/description から借方科目・事業を推定して返す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    try:
        data = request.json or {}
        vendor = data.get('vendor') or ''
        description = data.get('description') or ''
        rules = _cr_load_rules(supabase, f_code)
        drules = _dr_load_rules(supabase, f_code)
        aid, by, did, dby = _rcpt_suggest(supabase, f_code, vendor, description, rules, drules)
        acct = None
        if aid is not None:
            _a = supabase.table('accounts').select('id,code,name')\
                .eq('id', aid).eq('facility_code', f_code).eq('is_active', True).execute()
            if _a.data:
                a = _a.data[0]
                acct = {'id': a['id'], 'code': a['code'], 'name': a['name']}
        dvv = None
        if did is not None:
            _d = supabase.table('ledger_divisions').select('id,name')\
                .eq('id', did).eq('facility_code', f_code).eq('is_active', True).execute()
            if _d.data:
                d = _d.data[0]
                dvv = {'id': d['id'], 'name': d['name']}
        # ledger-receipt-pay-v1: 支払方法に応じた貫方候補(credit->未払金202 / それ以外->現金101)
        pay = (data.get('payment_method') or '').strip().lower()
        _cred_code = '202' if pay == 'credit' else '101'
        _cacc = supabase.table('accounts').select('id,code,name')\
            .eq('facility_code', f_code).eq('code', _cred_code)\
            .eq('is_active', True).execute()
        credit_acct = None
        if _cacc.data:
            _c = _cacc.data[0]
            credit_acct = {'id': _c['id'], 'code': _c['code'], 'name': _c['name']}
        return jsonify({'status': 'success',
                        'suggested_account': acct, 'matched_by': by,
                        'suggested_division': dvv, 'division_matched_by': dby,
                        'credit_account': credit_acct, 'payment_method': pay})  # ledger-receipt-pay-v1
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ledger/receipt_learn', methods=['POST'])  # ledger-receipt-learn-v1
@login_required
def api_ledger_receipt_learn():
    """領収書仕訳保存後に vendor/description -> 科目/事業 を学習辞書にupsert。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    try:
        import datetime as _dt
        data = request.json or {}
        vendor = data.get('vendor') or ''
        description = data.get('description') or ''
        aid = data.get('account_id')
        did = data.get('division_id')
        if aid is None:
            return jsonify({'status': 'success', 'learned': 0})  # 何もしない
        # 学習キー: 内容があれば item、無ければ 店名 store
        item = _cr_norm(description)
        if item:
            key_type, key_text = 'item', item
        else:
            key_type, key_text = 'store', _cr_norm(vendor)
        if not key_text:
            return jsonify({'status': 'success', 'learned': 0})
        now = _dt.datetime.utcnow().isoformat()
        learned = 0
        # 科目は費用科目のときのみ学習(安全弁)
        _a = supabase.table('accounts').select('id,category')\
            .eq('id', aid).eq('facility_code', f_code).eq('is_active', True).execute()
        if _a.data and _a.data[0].get('category') == '\u8cbb\u7528':
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
                    'account_id': aid, 'source': 'receipt',
                }).execute()
            learned += 1
        # 事業(division_idが渡されたときのみ)
        if did is not None:
            _dchk = supabase.table('ledger_divisions').select('id').eq('id', did)\
                .eq('facility_code', f_code).eq('is_active', True).execute()
            if _dchk.data:
                _de = supabase.table('ledger_division_rules').select('id')\
                    .eq('facility_code', f_code).eq('key_type', key_type)\
                    .eq('key_text', key_text).execute()
                if _de.data:
                    supabase.table('ledger_division_rules').update({
                        'division_id': did, 'updated_at': now,
                    }).eq('id', _de.data[0]['id']).execute()
                else:
                    supabase.table('ledger_division_rules').insert({
                        'facility_code': f_code, 'key_type': key_type,
                        'key_text': key_text, 'match_type': 'exact',
                        'division_id': did, 'source': 'receipt',
                    }).execute()
                learned += 1
        return jsonify({'status': 'success', 'learned': learned})
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


def is_credit_enabled(supabase, f_code):  # ledger-credit-mode-v1 / ledger-credit-method-v1
    """クレカ機能が使えるか: 記録方法(credit_input_method)を選択済みならTrue。
    接骨院モードには依存しない(全施設開放)。null=未選択=未有効。"""
    try:
        ls = supabase.table('ledger_settings').select('credit_input_method').eq('facility_code', f_code).execute()
        return bool(ls.data and ls.data[0].get('credit_input_method'))
    except Exception:
        return False


def is_credit_csv_enabled(supabase, f_code):  # ledger-credit-csvguard-v1
    """クレカCSV方式か: credit_input_method == 'csv' のときのみ True。
    オリコ明細CSV取込・Amazon突合・明細への科目割当等、CSV方式専用APIのガード。
    OCR方式/未選択の施設では False（二重計上防止）。"""
    try:
        ls = supabase.table('ledger_settings').select('credit_input_method').eq('facility_code', f_code).execute()
        return bool(ls.data and ls.data[0].get('credit_input_method') == 'csv')
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


@app.route('/api/ledger/receipts', methods=['GET'])  # ledger-receipt-vault-v1
@login_required
def api_ledger_receipts_list():
    """レシート保管庫: receipts 一覧。entry_id の有無で仕訳済み/未仕訳を判別。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    try:
        supabase = get_supabase()
        res = (supabase.table('receipts')
               .select('id,image_url,ocr_result,entry_id,created_by,created_at')
               .eq('facility_code', f_code)
               .order('created_at', desc=True)
               .execute())
        rows = res.data or []
        items = []
        for r in rows:
            ocr = r.get('ocr_result') or {}
            if not isinstance(ocr, dict):
                ocr = {}
            items.append({
                'id': r.get('id'),
                'image_url': r.get('image_url') or '',
                'entry_id': r.get('entry_id'),
                'is_journaled': bool(r.get('entry_id')),
                'created_by': r.get('created_by') or '',
                'created_at': r.get('created_at') or '',
                'date': ocr.get('date'),
                'amount': ocr.get('amount') or 0,
                'tax_amount': ocr.get('tax_amount') or 0,
                'vendor': ocr.get('vendor') or '',
                'description': ocr.get('description') or '',
                'payment_method': ocr.get('payment_method') or '',
                'ocr': ocr,
            })
        return jsonify({'status': 'success', 'receipts': items})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/receipt_entry', methods=['GET'])  # ledger-receipt-entry-api-v1
@login_required
def api_ledger_receipt_entry():
    """receipt_id に紐付く仕訳の有無と内容を返す。重複防止(上書き判定)用。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '権限がありません'}), 403
    try:
        supabase = get_supabase()
        rid = request.args.get('receipt_id')
        if not rid:
            return jsonify({'status': 'error', 'message': 'receipt_idが必要です'}), 400
        rc = (supabase.table('receipts').select('id,entry_id')
              .eq('id', rid).eq('facility_code', f_code).execute())
        if not rc.data:
            return jsonify({'status': 'success', 'entry_id': None, 'entry': None})
        eid = rc.data[0].get('entry_id')
        if not eid:
            return jsonify({'status': 'success', 'entry_id': None, 'entry': None})
        # 紐付く仕訳の実体を取得(削除済なら entry:null)
        er = (supabase.table('journal_entries')
              .select('id,entry_date,debit_account_id,credit_account_id,amount,tax_amount,description,division_id')
              .eq('id', eid).eq('facility_code', f_code).execute())
        if not er.data:
            return jsonify({'status': 'success', 'entry_id': None, 'entry': None})
        return jsonify({'status': 'success', 'entry_id': eid, 'entry': er.data[0]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/ledger/receipt/<int:receipt_id>', methods=['DELETE'])  # ledger-receipt-delete-v1
@login_required
def api_ledger_receipt_delete(receipt_id):
    """レシート保管庫から領収書を削除する。
    HIRO方針: 領収書(receipts行)のみ削除。紐付く仕訳は会計記録として残す。"""
    f_code = session.get('f_code')
    my_name = session.get('my_name')
    _ok = (f_code == LEDGER_ALLOWED_FACILITY and my_name == LEDGER_ALLOWED_USER)
    _dev = (f_code == LEDGER_DEV_FACILITY and my_name == LEDGER_DEV_USER)
    if not _ok and not _dev:
        return jsonify({'status': 'error', 'message': '\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093'}), 403
    supabase = get_supabase()
    try:
        # 存在確認（facility_code を必ず突き合わせ）
        rc = (supabase.table('receipts').select('id,entry_id')
              .eq('id', receipt_id).eq('facility_code', f_code).execute())
        if not rc.data:
            return jsonify({'status': 'error', 'message': '\u9818\u53ce\u66f8\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093'}), 404
        had_entry = bool(rc.data[0].get('entry_id'))
        # 領収書行のみ削除（仕訳は残す）
        supabase.table('receipts').delete().eq('id', receipt_id).eq('facility_code', f_code).execute()
        msg = '\u9818\u53ce\u66f8\u3092\u524a\u9664\u3057\u307e\u3057\u305f\u3002'
        if had_entry:
            msg += '\uff08\u7d10\u4ed8\u304f\u4ed5\u8a33\u306f\u4f1a\u8a08\u8a18\u9332\u3068\u3057\u3066\u6b8b\u3057\u3066\u3044\u307e\u3059\uff09'
        return jsonify({'status': 'success', 'message': msg, 'kept_entry': had_entry})
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
                "この領収書・レシートから以下の情報をJSONで抽出してください。\n"  # ledger-receipt-pay-v1
                '{"date":"YYYY-MM-DD","amount":0,"tax_amount":0,"vendor":"店名","description":"内容","tax_rate":10,"payment_method":"cash"}\n'
                "payment_methodは支払方法で、クレジットカード(VISA/JCB/Master/AMEX/クレジット/カード表記)ならcredit、"
                "電子マネー(PayPay/楽天ペイ/Suica/iD/QUICPay等)ならemoney、現金ならcash、不明ならunknownを入れてください。\n"
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
    # admin-lockout-v1 : 認証段ごとに失敗ロック(施設コード#段 + IP)
    _al_ip = _login_client_ip()
    _al_key = f"{f_code}#dev" if mode == "dev" else f"{f_code}#admin"
    if _login_is_locked(get_supabase(), _al_key, _al_ip):
        return render_template("admin.html",
            authenticated=False, dev_mode=(mode == "dev"),
            patients=[], blocked=[], staff_list=[],
            hist_limit=30,
            error="認証に何度も失敗したため、しばらくロックされています。約15分後に再度お試しください。",
            claude_url=None, registered_staffs=[], f_code=f_code,
            board_editors=[], admin_managers=[])

    # 開発者認証
    if mode == "dev":
        dev_pw = get_secret("DEV_PASSWORD") or "tasukaru-dev-2024"
        if pw == dev_pw:
            _login_clear_fail(get_supabase(), _al_key, _al_ip)  # admin-lockout-v1
            session["dev_authenticated"] = True
            return redirect(url_for("dev_menu"))
        else:
            _login_record_fail(get_supabase(), _al_key, _al_ip)  # admin-lockout-v1
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
        staff_res = supabase.table("staffs").select("staff_name,password_hash,email,line_user_id").eq(  # admin-2fa-select-fix-v1
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
            _login_record_fail(supabase, _al_key, _al_ip)  # admin-lockout-v1
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

        _login_clear_fail(supabase, _al_key, _al_ip)  # admin-lockout-v1
        # ===== admin-2fa-v1 : パスワード+権限OK。ここで2FAゲート =====
        _2fa_line_uid = (s.get("line_user_id") or "").strip()
        if not _2fa_line_uid:
            # 厳格: LINE未紐付けの管理者は入れない
            return render_template("admin.html",
                authenticated=False, dev_mode=False,
                patients=[], blocked=[], staff_list=[],
                hist_limit=30,
                error="管理者機能の利用にはLINEの紐づけが必要です。リッチメニューの「利用開始」からLINE連携を完了してから再度お試しください。",
                claude_url=None, registered_staffs=[], f_code=f_code,
                board_editors=[], admin_managers=[])
        # コード発行 + LINE送信
        if not _admin_2fa_issue(supabase, f_code, my_name, _2fa_line_uid):
            return render_template("admin.html",
                authenticated=False, dev_mode=False,
                patients=[], blocked=[], staff_list=[],
                hist_limit=30,
                error="認証コードのLINE送信に失敗しました。時間をおいて再度お試しください。",
                claude_url=None, registered_staffs=[], f_code=f_code,
                board_editors=[], admin_managers=[])
        # 認証保留状態をセッションに置く(まだ admin_authenticated にしない)
        session["pending_admin_2fa"] = {"f_code": f_code, "staff_name": my_name}
        return render_template("admin_2fa.html", staff_name=my_name, error=None)
    except Exception as e:
        return render_template("admin.html",
            authenticated=False, dev_mode=False,
            patients=[], blocked=[], staff_list=[],
            hist_limit=30, error=f"認証中にエラーが発生しました: {e}",
            claude_url=None, registered_staffs=[], f_code=f_code,
            board_editors=[], admin_managers=[])

@app.route('/admin_2fa_verify', methods=['POST'])  # admin-2fa-v1
@login_required
def admin_2fa_verify():
    pend = session.get("pending_admin_2fa") or {}
    f_code = session.get("f_code")
    my_name = session.get("my_name", "")
    # 保留状態の整合性チェック
    if not pend or pend.get("f_code") != f_code or pend.get("staff_name") != my_name:
        return redirect(url_for("admin"))
    code = (request.form.get("code", "") or "").strip()
    supabase = get_supabase()
    ok, reason = _admin_2fa_verify(supabase, f_code, my_name, code)
    if ok:
        session.pop("pending_admin_2fa", None)
        session["admin_authenticated"] = True
        return redirect(url_for("admin"))
    msg_map = {
        "expired": "コードの有効期限が切れました。最初からやり直してください。",
        "too_many": "入力回数の上限に達しました。最初からやり直してください。",
        "no_code": "有効なコードがありません。最初からやり直してください。",
    }
    if reason in ("expired", "too_many", "no_code"):
        session.pop("pending_admin_2fa", None)
        return render_template("admin.html",
            authenticated=False, dev_mode=False,
            patients=[], blocked=[], staff_list=[],
            hist_limit=30, error=msg_map.get(reason),
            claude_url=None, registered_staffs=[], f_code=f_code,
            board_editors=[], admin_managers=[])
    return render_template("admin_2fa.html", staff_name=my_name,
        error="認証コードが違います。もう一度入力してください。")

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

# ==========================================
# admin-patient-api-v1: 利用者管理サーバAPI (admin.htmlの直叩き置換)
# patient_profiles のみを操作(現状挙動を維持)。
# facility_code はサーバ側で session 値を強制適用し、
# フロント由来の値は信用しない。
# ==========================================
# ==========================================
# patients-sync-b1: patients連動ヘルパ(方針B 第1段)
# profilesに利用者を追加したら patients にも行を作る(孤児防止)。
# chart_number = profiles.patient_number をコピー(空ならフォールバック採番)。
# 同名patients行があれば何もしない(重複防止)。曜日は作らない(第2段)。
# ==========================================
# patient-number-zerofill-v1: 利用者番号の最低3桁ゼロ埋め整形
def _normalize_patient_number(pn):
    """数字のみなら最低3桁ゼロ埋め。3桁以上/英字含む/空はそのまま。"""
    s = (str(pn) if pn is not None else "").strip()
    if s.isdigit():
        return s.zfill(3)
    return s


# ==========================================
# clh-history-v1: 介護度履歴の記録ヘルパ
# care_level_history に「介護度＋適用開始日」を積む。
# 最新履歴と同じ介護度なら何もしない（重複防止）。
# valid_from は 'YYYY-MM-DD' 文字列 or None（Noneなら本日）。
# ==========================================
def _record_care_level_history(supabase, f_code, patient_id, new_level, valid_from=None):
    """clh-history-v1: 介護度が変わったときだけ care_level_history に1件追加。"""
    try:
        nl = (new_level or "").strip()
        if not nl:
            return False
        if not patient_id:
            return False
        # 既存履歴の最新(care_level)を取得
        prev = supabase.table("care_level_history") \
            .select("care_level") \
            .eq("facility_code", f_code).eq("patient_id", patient_id) \
            .order("valid_from", desc=True).limit(1).execute()
        prev_level = (prev.data[0]["care_level"] if prev.data else None)
        if prev_level is not None and (prev_level or "").strip() == nl:
            return False  # 変化なし
        vf = (valid_from or "").strip() or datetime.now(tokyo_tz).date().isoformat()
        supabase.table("care_level_history").insert({
            "facility_code": f_code,
            "patient_id": patient_id,
            "care_level": nl,
            "valid_from": vf,
        }).execute()
        return True
    except Exception as e:
        print("_record_care_level_history error: %s" % e, flush=True)
        return False


def _ensure_patient_row(supabase, f_code, profile_row):
    """profile_row(dict: user_name/user_name_kana/birth_date/patient_number)に対応する
    patients行を必要なら作成する。戻り値: 作成したら True / 既存なら False。"""
    try:
        name = (profile_row.get("user_name") or "").strip()
        if not name:
            return False
        # 既に同名のpatients行があれば作らない
        exist = supabase.table("patients").select("id").eq("facility_code", f_code).eq("user_name", name).execute()
        if exist.data:
            return False
        # chart_number: patient_number をコピー。空ならフォールバック採番
        chart = str(profile_row.get("patient_number") or "").strip()
        if not chart:
            ex = supabase.table("patients").select("chart_number").eq("facility_code", f_code).execute()
            nums = []
            for p in (ex.data or []):
                try: nums.append(int(p["chart_number"]))
                except: pass
            chart = str(max(nums, default=0) + 1).zfill(3)
        birth = profile_row.get("birth_date") or None
        supabase.table("patients").insert({
            "facility_code": f_code,
            "user_name":     name,
            "user_kana":     profile_row.get("user_name_kana") or "",
            "birth_date":    birth,
            "chart_number":  chart,
        }).execute()
        return True
    except Exception as e:
        print(f"_ensure_patient_row error: {e}", flush=True)
        return False


@app.route('/api/admin/patient/add', methods=['POST'])
@login_required
def api_admin_patient_add():
    """1名手入力登録 (patient_profiles)"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        name = (data.get("user_name") or "").strip()
        # patient-number-zerofill-v1: 利用者番号を整形
        if data.get("patient_number"):
            data["patient_number"] = _normalize_patient_number(data.get("patient_number"))
        if not name:
            return jsonify({"status": "error", "message": "氏名は必須です"}), 400
        row = {
            "facility_code":  f_code,
            "patient_number": (data.get("patient_number") or None),
            "user_name":      name,
            "user_name_kana": (data.get("user_name_kana") or None),
            "birth_date":     (data.get("birth_date") or None),
            "care_level":     (data.get("care_level") or None),
            "updated_at":     datetime.now(tokyo_tz).isoformat(),
        }
        supabase = get_supabase()
        supabase.table("patient_profiles").insert(row).execute()
        # patients-sync-b1: patients連動
        _ensure_patient_row(supabase, f_code, row)
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_patient_add error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/patient/save', methods=['POST'])
@login_required
def api_admin_patient_save():
    """admin-patient-save-v1: 利用者情報の保存 (patient_profiles)。
    idあり=update / idなし=insert。facility_codeはサーバ側で強制。
    フロントが組み立てたフィールドをそのまま通す(現状挙動を維持)。"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        pid = (data.get("id") or "").strip()
        # idは書き込み対象カラムから除外し、facility_codeは強制
        # clh-history-v1-fix1: care_level_valid_from は履歴用なので patient_profiles へは書かない
        row = {k: v for k, v in data.items() if k not in ("id", "facility_code", "care_level_valid_from")}
        row["facility_code"] = f_code
        row["updated_at"] = datetime.now(tokyo_tz).isoformat()
        # patient-number-zerofill-v1: 利用者番号を整形
        if row.get("patient_number"):
            row["patient_number"] = _normalize_patient_number(row.get("patient_number"))

        # user_name 必須(新規時)
        if not pid and not (row.get("user_name") or "").strip():
            return jsonify({"status": "error", "message": "氏名は必須です"}), 400

        supabase = get_supabase()
        if pid:
            # 更新: id + facility_code の二条件でログイン施設のみ
            res = supabase.table("patient_profiles").update(row) \
                .eq("id", pid).eq("facility_code", f_code).execute()
            if not res.data:
                return jsonify({"status": "error", "message": "対象が見つかりません"}), 404
            # clh-history-v1: 介護度履歴を記録（変わったときだけ）
            if "care_level" in row:
                _record_care_level_history(supabase, f_code, pid, row.get("care_level"), data.get("care_level_valid_from"))
            return jsonify({"status": "success", "id": pid})
        else:
            # 新規: insert して id を返す
            res = supabase.table("patient_profiles").insert(row).execute()
            new_id = res.data[0]["id"] if res.data else None
            # patients-sync-b1: patients連動(新規時のみ)
            _ensure_patient_row(supabase, f_code, row)
            # clh-history-v1: 初回介護度履歴を記録。valid_fromは認定開始日→無ければ本日
            if new_id and row.get("care_level"):
                _vf = data.get("care_level_valid_from") or row.get("certification_start_date")
                _record_care_level_history(supabase, f_code, new_id, row.get("care_level"), _vf)
            return jsonify({"status": "success", "id": new_id})
    except Exception as e:
        print(f"admin_patient_save error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/patient/delete', methods=['POST'])
@login_required
def api_admin_patient_delete():
    """1名削除 (patient_profiles)。ログイン施設のレコードのみ削除可。"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        pid = (data.get("id") or "").strip()
        if not pid:
            return jsonify({"status": "error", "message": "idが必要です"}), 400
        supabase = get_supabase()
        supabase.table("patient_profiles").delete() \
            .eq("id", pid).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_patient_delete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/patient/bulk_import', methods=['POST'])
@login_required
def api_admin_patient_bulk_import():
    """CSV一括取込 (patient_profiles upsert / merge-duplicates)。
    パース済み records[] を受け、facility_code はサーバ側で強制上書き。"""
    try:
        data = request.json or {}
        f_code = session["f_code"]
        records = data.get("records", []) or []
        if not records:
            return jsonify({"status": "error", "message": "取込データがありません"}), 400
        now_iso = datetime.now(tokyo_tz).isoformat()
        clean = []
        for r in records:
            if not isinstance(r, dict):
                continue
            row = dict(r)
            # facility_code はフロント由来を捨ててsession値で強制
            row["facility_code"] = f_code
            row["updated_at"] = now_iso
            # patient-number-zerofill-v1: 利用者番号を整形
            if row.get("patient_number"):
                row["patient_number"] = _normalize_patient_number(row.get("patient_number"))
            clean.append(row)
        if not clean:
            return jsonify({"status": "error", "message": "取込データがありません"}), 400
        supabase = get_supabase()
        supabase.table("patient_profiles").upsert(clean).execute()
        # patients-sync-b1: 各行をpatients連動
        for _r in clean:
            _ensure_patient_row(supabase, f_code, _r)
        return jsonify({"status": "success", "count": len(clean)})
    except Exception as e:
        print(f"admin_patient_bulk_import error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


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
    # timecard-hidden-icon-v1: タイムカード非表示リスト
    timecard_hidden_list = []
    if authenticated:
        try:
            import json as _json
            res_th = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "timecard_hidden").execute()
            if res_th.data and res_th.data[0].get("value"):
                timecard_hidden_list = _json.loads(res_th.data[0]["value"])
                if not isinstance(timecard_hidden_list, list):
                    timecard_hidden_list = []
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
        timecard_hidden=timecard_hidden_list,
        admin_managers=admin_managers_list)

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
        patient_id=patient_id,
        visit_day_data=visit_day_data
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
                _reporter_map_n = {"self": "本人", "family": "家族", "caremanager": "ケアマネ", "other": "その他", "none": "連絡なし"}  # leave-reporter-display-v1
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

        BASE_PROMPT = (  # prompt-tone-v1
            "あなたは介護施設のベテランケアマネジャーの補佐をしています。"
            f"【対象の確認(最重要)】\n"
            f"この報告の対象はご利用者「{u_name}」様です。記録には複数の職員や他のご利用者が登場することがありますが、報告対象は常に「{u_name}」様です。主語を取り違えないでください。\n"
            "以下の介護記録を読み、ケアマネジャーへのモニタリング報告書として使える文章を生成してください。\n"
            "【ルール】\n"
            "・事実として記録されていること以外は絶対に書かない（ハルシネーション厳禁）\n"
            "・記録がない場合は文章を作らず「今月このカテゴリの報告はありませんでした」とだけ返す\n"
            "・職員名・利用者名・主語は不要\n"
            "・記録の中に他のご利用者の名前が出てきた場合は、その名前を書かず必ず「他の利用者様」と表現する\n"
            "・箇条書きは使わず、ひとつながりの文章で書く\n"
            "・口調は報告文書として読みやすい丁寧語(です・ます)。二重敬語や過剰な敬語(「お〜になられる」「ございました」等)は避け、硬すぎず砕けすぎない自然な丁寧さにとどめる\n"
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

@app.route('/api/admin_login', methods=['POST'])  # admin-lockout-v1 : disabled legacy route
@login_required
def api_admin_login():
    # admin-lockout-v1 : この経路は未使用かつ権限チェック無しの緩い実装だったため無効化。
    # 管理者認証は /admin_auth (個人PW + is_admin_user + 失敗ロック) に一本化。
    return jsonify({"status": "error", "message": "この経路は無効です。"}), 403

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
        res = supabase.table("facilities").select("facility_code,facility_name,is_active,expires_at,plan,is_monitor,contract_term,trial_ends_at,discount_rate,discount_until,sekkotsu_mode_allowed,timecard_enabled").execute()  # dev-sekkotsu-allow-v1 / timecard-devtoggle-v1
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
                "timecard_enabled": fac.get("timecard_enabled", False),  # timecard-devtoggle-v1
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


@app.route('/api/dev/toggle_timecard', methods=['POST'])  # timecard-devtoggle-v1
def api_dev_toggle_timecard():
    """施設ごとのタイムカード機能ON/OFF(課金管理)。開発者認証必須。"""
    if not session.get('dev_authenticated'):
        return jsonify({'success': False, 'message': 'unauthorized'}), 403
    data = request.json or {}
    fc = (data.get('facility_code') or '').strip()
    enabled = bool(data.get('enabled', False))
    if not fc:
        return jsonify({'success': False, 'message': 'facility_code required'}), 400
    try:
        supabase = get_supabase()
        supabase.table('facilities').update({'timecard_enabled': enabled}).eq('facility_code', fc).execute()
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

# board-paginate-helper-v1: Supabaseのデフォルト行数上限(1000)による
# 取りこぼしを防ぐための共通ページング取得ヘルパー。
# make_query: 毎回新しいクエリビルダを返す関数(ラムダ)。
#   例: lambda: supabase.table('x').select('*').eq('facility_code', f_code)
# .range()/.execute() はヘルパー内で付与するので渡さないこと。
def _fetch_all_paginated(make_query, page_size=1000, max_pages=50):
    rows = []
    page = 0
    while True:
        lo = page * page_size
        res = make_query().range(lo, lo + page_size - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
        if page >= max_pages:
            break
    return rows


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
            # 自分以外が書いた全コメントを取得(未読対象) [board-paginate-helper-v1: ページング]
            _ccs_rows = _fetch_all_paginated(lambda: supabase.table("board_comments").select("id,post_id,staff_name").eq("facility_code", f_code).in_("post_id", post_ids))
            unread_comment_ids_by_post = {}
            all_other_comment_ids = []
            for c in _ccs_rows:
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
            # [board-paginate-helper-v1: ページング + facility_code絞り]
            _rres_rows = _fetch_all_paginated(lambda: supabase.table("board_reactions").select("*").eq("facility_code", f_code).in_("post_id", post_ids))
            for r in _rres_rows:
                pid = r["post_id"]
                em = r["reaction"]
                # Session 32 Phase 3c: ✅ は board_checks に移行済みなのでスキップ
                if em == '✅':
                    continue
                if pid not in reactions_data: reactions_data[pid] = {}
                if em not in reactions_data[pid]: reactions_data[pid][em] = []
                reactions_data[pid][em].append(r["staff_name"])
            # [board-paginate-helper-v1: ページング + facility_code絞り]
            _rdres_rows = _fetch_all_paginated(lambda: supabase.table("board_reads").select("post_id,staff_name").eq("facility_code", f_code).in_("post_id", post_ids))
            for r in _rdres_rows:
                pid = r["post_id"]
                if pid not in read_data: read_data[pid] = []
                read_data[pid].append(r["staff_name"])
            # Session 32: 確認済み(board_checks)を取得
            # board-checks-pagination-v1: Supabaseのデフォルト1000行上限で古い投稿の
            # 確認済みが取りこぼされ、画面は未確認なのにDBは確認済みというゴーストが発生していた。
            # range()で全件をページング取得し、facility_codeでも絞る。
            try:
                _chk_rows = _fetch_all_paginated(lambda: supabase.table("board_checks").select("post_id,staff_name").eq("facility_code", f_code).in_("post_id", post_ids))
                for r in _chk_rows:
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
        # board-key-render-removed-v1: Realtime用キー受け渡しを削除(ポーリングで動作)
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



# ===== keiyaku-calc-api-v1 : 契約書・重要事項説明書 料金計算と設定API =====
import math as _kk_math

# --- 基本単位数マスタ（国コード表 令和8年6月施行版で確認済み） ---
# keiyaku-timeclass-app-v1: 地域密着型通所介護 基本単位数を国の所要時間区分(time_class)で保持。
# 出典: 介護給付費単位数等サービスコード表(令和8年6月施行版) 78 1xxx 地域密着型通所介護費(本体)。
_KK_BASE = {
    "3-4h": {1: 416, 2: 478, 3: 540, 4: 600, 5: 663},
    "4-5h": {1: 436, 2: 501, 3: 566, 4: 629, 5: 695},
    "5-6h": {1: 657, 2: 776, 3: 896, 4: 1013, 5: 1134},
    "6-7h": {1: 678, 2: 801, 3: 925, 4: 1049, 5: 1172},
    "7-8h": {1: 753, 2: 890, 3: 1032, 4: 1172, 5: 1312},
    "8-9h": {1: 783, 2: 925, 3: 1072, 4: 1220, 5: 1365},
}
# keiyaku-timeclass-app-v1: 旧種別キー(han/ichi)→time_class 後方互換マッピング。
_KK_LEGACY_TC = {"han": "3-4h", "ichi": "7-8h"}
_KK_KUNREN1_PER_VISIT = 56   # 個別機能訓練加算Ⅰイ 56単位/回（毎回）
_KK_KUNREN2_MONTHLY   = 20   # 個別機能訓練加算Ⅱ 20単位/月
_KK_KAGAKU_MONTHLY    = 40   # 科学的介護推進体制加算 40単位/月
_KK_SHOGUU_RATE       = 0.125  # 後方互換: 既定率(Ⅱロ 125/1000)。
# keiyaku-timeclass-app-v1: 介護職員等処遇改善加算 6区分の率(/1000)。既定はⅡロ(2ro)=12.5%。
_KK_SHOGUU_RATES = {
    "1i": 0.117, "1ro": 0.127, "2i": 0.115, "2ro": 0.125, "3": 0.105, "4": 0.089,
}

# ===== keiyaku-addmaster-app-v1 : 加算マスタ（keiyaku_render.py と同一方針） =====
# calc: per_visit=単位×月回数 / per_month=月1回定額 /
#       per_month_cap=単位×min(回数,cap) / rate_on_total=処遇改善(月総単位×率)
# in_fee_default: 料金表(要介護別月額自己負担)に金額で織り込む既定。
#   True=毎月確実 → 料金表に反映。False=頻度/利用者依存 → 一覧表に単位×条件のみ。
# C-1では現状4加算をマスタ駆動で従来と完全一致させる。C-2以降で他加算を追加。
_KK_ADD_MASTER = {
    "kunren1": {"units": _KK_KUNREN1_PER_VISIT, "calc": "per_visit",
                "scope": "service", "group": "kunren_kobetsu", "in_fee_default": True,  # keiyaku-c2-adds-app-v1
                "label": "個別機能訓練加算Ⅰ１", "note": "56単位／回（利用日ごと）"},
    "kunren2": {"units": _KK_KUNREN2_MONTHLY, "calc": "per_month",
                "scope": "service", "in_fee_default": True,
                "label": "個別機能訓練加算Ⅱ", "note": "20単位／月"},
    "kagaku":  {"units": _KK_KAGAKU_MONTHLY, "calc": "per_month",
                "scope": "service", "in_fee_default": True,
                "label": "科学的介護推進体制加算", "note": "40単位／月"},
    "shoguu":  {"calc": "rate_on_total", "scope": "facility",
                "in_fee_default": True, "label": "介護職員等処遇改善加算",
                "note": "月総単位数に所定の率を乗じて算定"},
    # keiyaku-c2-adds-app-v1: C-2追加5加算（毎回算定 per_visit・料金表に反映）。
    "kunren1ro": {"units": 76, "calc": "per_visit", "scope": "service",
                  "group": "kunren_kobetsu", "in_fee_default": True,
                  "label": "個別機能訓練加算Ⅰ２（Ⅰロ）",
                  "note": "76単位／回（利用日ごと。Ⅰ１と排他）"},
    "chuju":   {"units": 45, "calc": "per_visit", "scope": "service",
                "in_fee_default": True, "label": "中重度者ケア体制加算",
                "note": "45単位／回（利用日ごと。利用者全員に算定可）"},
    "ninchi":  {"units": 60, "calc": "per_visit", "scope": "service",
                "in_fee_default": True, "label": "認知症加算",
                "note": "60単位／回（利用日ごと。要件を満たす場合）"},
    "nyuyoku1": {"units": 40, "calc": "per_visit", "scope": "service",
                 "group": "nyuyoku", "in_fee_default": True,
                 "label": "入浴介助加算Ⅰ",
                 "note": "40単位／回（入浴介助実施日。Ⅱと排他）"},
    "nyuyoku2": {"units": 55, "calc": "per_visit", "scope": "service",
                 "group": "nyuyoku", "in_fee_default": True,
                 "label": "入浴介助加算Ⅱ",
                 "note": "55単位／回（入浴介助実施日。Ⅰと排他）"},
    # keiyaku-c4a-koukuu-app-v1: 限度つき・低頻度。既定 in_fee:False（料金表でなく一覧表へ）。
    "koukuu1": {"units": 150, "calc": "per_month_cap", "cap": 2, "scope": "service",
                "group": "koukuu", "in_fee_default": False,
                "label": "口腔機能向上加算Ⅰ",
                "note": "150単位／回（月2回を限度。Ⅱと排他）"},
    "koukuu2": {"units": 160, "calc": "per_month_cap", "cap": 2, "scope": "service",
                "group": "koukuu", "in_fee_default": False,
                "label": "口腔機能向上加算Ⅱ",
                "note": "160単位／回（月2回を限度。Ⅰと排他。LIFE提出要件）"},
    # keiyaku-c4b-adds-app-v1: 栄養・連携・ADL・若年性・生活相談員（共生型）。
    "eiyou_assess": {"units": 50, "calc": "per_month", "scope": "service",
                     "in_fee_default": False,
                     "label": "栄養アセスメント加算", "note": "50単位／月（LIFE提出要件）"},
    "eiyou_kaizen": {"units": 200, "calc": "per_month_cap", "cap": 2, "scope": "service",
                     "in_fee_default": False,
                     "label": "栄養改善加算", "note": "200単位／回（月2回を限度）"},
    "screening1": {"units": 20, "calc": "low_freq", "scope": "service",
                   "group": "screening", "in_fee_default": False,
                   "label": "口腔・栄養スクリーニング加算Ⅰ",
                   "note": "20単位／回（6月に1回を限度）"},
    "renkei1": {"units": 100, "calc": "low_freq", "scope": "service",
                "group": "renkei", "in_fee_default": False,
                "label": "生活機能向上連携加算Ⅰ",
                "note": "100単位／回（原則3月に1回を限度。Ⅱと排他）"},
    "renkei2": {"units": 200, "calc": "per_month", "scope": "service",
                "group": "renkei", "in_fee_default": False,
                "label": "生活機能向上連携加算Ⅱ", "note": "200単位／月（Ⅰと排他）"},
    "adl1": {"units": 30, "calc": "per_month", "scope": "service",
             "group": "adl", "in_fee_default": False,
             "label": "ADL維持等加算Ⅰ", "note": "30単位／月（Ⅱと排他。LIFE提出要件）"},
    "adl2": {"units": 60, "calc": "per_month", "scope": "service",
             "group": "adl", "in_fee_default": False,
             "label": "ADL維持等加算Ⅱ", "note": "60単位／月（Ⅰと排他。LIFE提出要件）"},
    "jakunen": {"units": 60, "calc": "per_visit", "scope": "service",
                "in_fee_default": False,
                "label": "若年性認知症利用者受入加算",
                "note": "60単位／回（利用日ごと。要件を満たす場合）"},
    "soudan": {"units": 13, "calc": "per_visit", "scope": "service",
               "in_fee_default": False,
               "label": "生活相談員配置等加算",
               "note": "13単位／回（利用日ごと。※共生型地域密着型通所介護のみ算定可。"
                       "共生型は基本報酬が所定単位の93/100となる点に留意）"},
}


def _kk_add_state(adds, key):
    """keiyaku-addmaster-app-v1: adds[key] を {on, in_fee} に正規化。
    旧bool形式 adds={kunren1:True} は {on:True, in_fee:マスタ既定} に読み替え。
    新dict形式 adds={kunren1:{on,in_fee}} は値を尊重。"""
    m = _KK_ADD_MASTER.get(key, {})
    in_fee_def = bool(m.get("in_fee_default"))
    v = adds.get(key)
    if isinstance(v, dict):
        st = {"on": bool(v.get("on")),
              "in_fee": bool(v.get("in_fee", in_fee_def))}
    else:
        st = {"on": bool(v), "in_fee": in_fee_def}
    # keiyaku-c4b-adds-app-v1: low_freq（超低頻度）は料金表に載せず一覧専用→in_fee強制False。
    if m.get("calc") == "low_freq":
        st["in_fee"] = False
    return st


def _kk_add_master_public():
    """keiyaku-c3-master-api-v1: UI配信用に加算マスタのメタ情報を抜き出す。
    dict挿入順=表示順を維持。計算内部値も含め安全な範囲で返す。"""
    out = {}
    for k, m in _KK_ADD_MASTER.items():
        out[k] = {
            "label": m.get("label", k),
            "note": m.get("note", ""),
            "group": m.get("group"),
            "scope": m.get("scope", "service"),
            "calc": m.get("calc"),
            "units": m.get("units"),
            "cap": m.get("cap"),  # keiyaku-c4a-koukuu-app-v1
            "in_fee_default": bool(m.get("in_fee_default")),
        }
    return out


def _kk_resolve_tc(service_type, F=None):
    """keiyaku-timeclass-app-v1: 種別キー/旧キーから _KK_BASE 参照キー(time_class)を解決。
    優先順: 既に time_class → F['service'][key]['time_class'] → 旧キー(han/ichi)変換 → 既定3-4h。"""
    if service_type in _KK_BASE:
        return service_type
    if isinstance(F, dict):
        sv = F.get("service", {})
        if isinstance(sv, dict):
            node = sv.get(service_type)
            if isinstance(node, dict) and node.get("time_class") in _KK_BASE:
                return node["time_class"]
    if service_type in _KK_LEGACY_TC:
        return _KK_LEGACY_TC[service_type]
    return "3-4h"


def _kk_shoguu_rate(adds):
    """keiyaku-timeclass-app-v1 / addmaster-app-v1: 処遇改善率を取得。
    on 判定は _kk_add_state 経由で旧bool/新dict両形式に対応。率は shoguu_type 優先。"""
    if not _kk_add_state(adds, "shoguu")["on"]:  # keiyaku-addmaster-app-v1
        return 0.0
    stype = adds.get("shoguu_type", "2ro")
    return _KK_SHOGUU_RATES.get(stype, _KK_SHOGUU_RATES["2ro"])
_KK_JINKENHI_RATIO    = 0.45   # 通所介護 人件費割合
_KK_AREA_UPLIFT = {1: 0.20, 2: 0.16, 3: 0.15, 4: 0.12, 5: 0.10, 6: 0.06, 7: 0.03, 0: 0.00}
_KK_DEFAULT_VISITS_PER_MONTH = 4
_KK_FEE_TABLE_NOTE = "月4回（週1回）利用の場合の目安です。利用回数により金額は変わります。"

def _kk_round_half_up(x):
    return _kk_math.floor(x + 0.5)

def _kk_tanka(area_level):
    """1単位単価 = 四捨五入(10×(1+上乗せ率×人件費割合), 小数2位)。豊田市3級地→10.68円"""
    uplift = _KK_AREA_UPLIFT.get(area_level, 0.0)
    raw = 10 * (1 + uplift * _KK_JINKENHI_RATIO)
    return _kk_math.floor(raw * 100 + 0.5) / 100

def _kk_monthly_units(service_type, level, visits_per_month, adds, F=None):
    # keiyaku-addmaster-app-v1: 加算マスタ駆動。処遇改善(rate_on_total)は含めず
    # 月総単位を返す（処遇改善は _kk_calc_monthly 側で最後に乗算）。
    # 料金表に金額で織り込むのは on かつ in_fee の加算のみ。従来4加算と完全一致。
    per_visit = _KK_BASE[_kk_resolve_tc(service_type, F)][level]
    monthly_fixed = 0
    for _k, _m in _KK_ADD_MASTER.items():
        _s = _kk_add_state(adds, _k)
        if not (_s["on"] and _s["in_fee"]):
            continue
        _c = _m.get("calc")
        if _c == "per_visit":
            per_visit += _m["units"]
        elif _c == "per_month":
            monthly_fixed += _m["units"]
        elif _c == "per_month_cap":
            monthly_fixed += _m["units"] * min(visits_per_month,
                                               _m.get("cap", visits_per_month))
    return per_visit * visits_per_month + monthly_fixed

def _kk_calc_per_visit(service_type, level, wari, adds, area_level=3, F=None):
    """1回あたりの自己負担額（参考値）。基本＋毎回加算（per_visit）のみ。"""
    # keiyaku-addmaster-app-v1: per_visit 加算を on かつ in_fee のものだけ合算。
    units = _KK_BASE[_kk_resolve_tc(service_type, F)][level]
    for _k, _m in _KK_ADD_MASTER.items():
        if _m.get("calc") != "per_visit":
            continue
        _s = _kk_add_state(adds, _k)
        if _s["on"] and _s["in_fee"]:
            units += _m["units"]
    price = _kk_tanka(area_level)
    total_yen = _kk_math.floor(units * price)
    kyufu = _kk_math.floor(total_yen * (10 - wari) / 10)
    return {"units": units, "total_yen": total_yen, "kyufu": kyufu,
            "jiko": total_yen - kyufu, "unit_price": price}

def _kk_calc_monthly(service_type, level, wari, visits_per_month, adds, area_level=3, F=None):
    """月額目安（正規計算＝請求基準）。月総単位で処遇改善まで含めて算出。"""
    m_units = _kk_monthly_units(service_type, level, visits_per_month, adds, F)  # keiyaku-timeclass-app-v1
    _rate = _kk_shoguu_rate(adds)  # keiyaku-timeclass-app-v1: 6区分から率を取得
    shoguu = _kk_round_half_up(m_units * _rate) if _rate else 0
    total_units = m_units + shoguu
    price = _kk_tanka(area_level)
    total_yen = _kk_math.floor(total_units * price)
    kyufu = _kk_math.floor(total_yen * (10 - wari) / 10)
    return {"visits": visits_per_month, "total_units": total_units,
            "total_yen": total_yen, "kyufu": kyufu,
            "jiko": total_yen - kyufu, "unit_price": price}

def _kk_build_fee_table(service_type, adds, area_level=3, visits_per_month=None, F=None):
    """料金表データを生成。要介護1〜5×(1回単価 / 月額目安1・2・3割)。"""
    if visits_per_month is None:
        visits_per_month = _KK_DEFAULT_VISITS_PER_MONTH
    _tc = _kk_resolve_tc(service_type, F)  # keiyaku-timeclass-app-v1
    rows = []
    for lv in range(1, 6):
        pv = _kk_calc_per_visit(service_type, lv, 1, adds, area_level, F)
        m = {w: _kk_calc_monthly(service_type, lv, w, visits_per_month, adds, area_level, F)
             for w in (1, 2, 3)}
        rows.append({
            "level": lv,
            "base_units": _KK_BASE[_tc][lv],
            "per_visit_jiko": pv["jiko"],
            "monthly": {str(w): m[w]["jiko"] for w in (1, 2, 3)},
        })
    return {
        "service_type": service_type,
        "unit_price": _kk_tanka(area_level),
        "area_level": area_level,
        "visits_per_month": visits_per_month,
        "note": _KK_FEE_TABLE_NOTE,
        "rows": rows,
    }

# --- 設定の読み書き（admin_settings の4キー。既存パターン: update→無ければinsert） ---
_KK_KEYS = ("keiyaku_facility", "keiyaku_jihi", "keiyaku_staff", "keiyaku_adds")

def _kk_get_setting(supabase, f_code, key):
    """admin_settings から1キー読み出し。JSON文字列はパースして返す。無ければ None。"""
    try:
        res = supabase.table("admin_settings").select("value").eq(
            "facility_code", f_code).eq("key", key).execute()
        if res.data and len(res.data) > 0:
            raw = res.data[0].get("value")
            if raw is None or raw == "":
                return None
            try:
                return json.loads(raw)
            except Exception:
                return raw
    except Exception as e:
        print(f"_kk_get_setting error ({key}): {e}", flush=True)
    return None

def _kk_save_setting(supabase, f_code, key, value):
    """admin_settings へ1キー保存。dict/list は JSON 文字列化。
    (facility_code,key) のユニーク制約が無いため existing 分岐。"""
    if isinstance(value, (dict, list)):
        value_json = json.dumps(value, ensure_ascii=False)
    else:
        value_json = value
    existing = supabase.table("admin_settings").select("id").eq(
        "facility_code", f_code).eq("key", key).execute()
    if existing.data and len(existing.data) > 0:
        supabase.table("admin_settings").update({"value": value_json}).eq(
            "facility_code", f_code).eq("key", key).execute()
    else:
        supabase.table("admin_settings").insert({
            "facility_code": f_code, "key": key, "value": value_json}).execute()

# --- 設定API: GET（設定＋計算済み料金表を返す） ---
# ===== keiyaku-page-v1 : 契約書・重要事項説明書 設定UI画面 =====
@app.route("/admin/keiyaku")
@login_required
def admin_keiyaku():
    """keiyaku-page-v1: 契約書・重要事項説明書の設定UI＋プレビュー(管理者MENU)。"""
    if not session.get("admin_authenticated", False):
        return redirect(url_for("dev_login"))
    return render("admin_keiyaku.html")
# ===== /keiyaku-page-v1 =====


# ===== keiyaku-print-v1 : 契約書・重要事項説明書 印刷ルート（PDF生成） =====
@app.route("/admin/keiyaku/print")
@login_required
def admin_keiyaku_print():
    """keiyaku-print-v1: 契約書・重説を設定値から生成しPDF/HTMLで返す(管理者限定)。
    ?doc=juyo|keiyaku|both  &type=han|ichi  &format=pdf|html
    """
    if not session.get("admin_authenticated", False):
        return redirect(url_for("dev_login"))
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return ("管理者権限がありません", 403)

        doc = request.args.get("doc", "both")
        if doc not in ("juyo", "keiyaku", "both"):
            doc = "both"
        # keiyaku-service-order-v1: st の確定は facility 読み出し後（_order 参照のため）に後送り。
        st_req = request.args.get("type", "")
        out_format = request.args.get("format", "pdf")

        # 4キーを読み出して統合 F dict を構築（keiyaku_render が期待する形）
        facility = _kk_get_setting(supabase, f_code, "keiyaku_facility") or {}
        if not isinstance(facility, dict):
            facility = {}
        facility = _kk_ensure_service_order(facility)  # keiyaku-service-migrate-v1
        jihi = _kk_get_setting(supabase, f_code, "keiyaku_jihi") or []
        staff = _kk_get_setting(supabase, f_code, "keiyaku_staff") or []
        adds = _kk_get_setting(supabase, f_code, "keiyaku_adds") or {
            "kunren1": True, "kunren2": True, "kagaku": True, "shoguu": True}

        F = dict(facility)
        F["jihi"] = jihi
        F["staff"] = staff
        F["adds"] = adds
        # area_level / visits_per_month は facility 側にある想定。無ければ既定。
        F.setdefault("area_level", int(facility.get("area_level", 3)) if isinstance(facility, dict) else 3)
        F.setdefault("visits_per_month", int(facility.get("visits_per_month", 4)) if isinstance(facility, dict) else 4)

        # keiyaku-service-order-v1: 種別キー st を facility.service._order で解決。
        _svc = facility.get("service", {}) if isinstance(facility, dict) else {}
        _order = _svc.get("_order") if isinstance(_svc, dict) else None
        if not (isinstance(_order, list) and _order):
            _order = [k for k in ("han", "ichi") if isinstance(_svc, dict) and k in _svc] or ["han"]
        if st_req and st_req in _svc and st_req != "_order":
            st = st_req
        elif st_req in ("han", "ichi") and st_req in _svc:
            st = st_req
        else:
            st = _order[0]

        import keiyaku_render as _kr
        html_str = _kr.render_print_html(F, doc, st)

        if out_format == "html":
            return html_str

        # PDF生成（既存作法: pdfkit + wkhtmltopdf。日本語フォントはイメージに導入済み）
        import pdfkit
        import shutil as _sh
        options = {
            "encoding": "UTF-8",
            "no-outline": None,
            "quiet": "",
            "disable-smart-shrinking": "",
            "margin-top": "0",
            "margin-right": "0",
            "margin-bottom": "0",
            "margin-left": "0",
        }
        wk_path = _sh.which("wkhtmltopdf") or "/usr/local/bin/wkhtmltopdf"
        config = pdfkit.configuration(wkhtmltopdf=wk_path)
        pdf_bytes = pdfkit.from_string(html_str, False, options=options, configuration=config)

        from flask import make_response  # keiyaku-print-makeresp-fix-v1
        from urllib.parse import quote
        doc_label = {"juyo": "重要事項説明書", "keiyaku": "利用契約書", "both": "契約書一式"}.get(doc, "書類")
        # keiyaku-service-order-v1: 表示名は種別の label を優先、無ければ旧辞書、無ければ空。
        _node = _svc.get(st) if isinstance(_svc, dict) else None
        if isinstance(_node, dict) and _node.get("label"):
            type_label = str(_node.get("label"))
        else:
            type_label = {"han": "半日型", "ichi": "1日型"}.get(st, "")
        fname = f"{doc_label}_{type_label}.pdf"
        fname_ascii = "keiyaku.pdf"
        fname_encoded = quote(fname)
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = (
            'inline; filename="' + fname_ascii + '"; filename*=UTF-8\'\'' + fname_encoded)
        return response
    except Exception as e:
        print(f"admin_keiyaku_print error: {e}", flush=True)
        return (f"PDF生成エラー: {e}", 500)
# ===== /keiyaku-print-v1 =====


# ===== keiyaku-seed-v1 : ココカラプラス初期データ投入API（管理者限定） =====
@app.route("/admin/keiyaku/seed", methods=["POST"])
@login_required
def api_keiyaku_seed():
    """keiyaku-seed-v1: ココカラプラスの契約書・重説初期データを4キーに投入。
    既に keiyaku_facility がある施設は force!=1 のとき skip。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403

        force = request.args.get("force", "0") == "1"
        existing = _kk_get_setting(supabase, f_code, "keiyaku_facility")
        if existing and not force:
            return jsonify({
                "status": "skipped",
                "message": "既に keiyaku_facility が存在します。上書きするには ?force=1 を付けてください。",
            })

        import keiyaku_seed_cocokara as _seed
        _kk_save_setting(supabase, f_code, "keiyaku_facility", _seed.KEIYAKU_FACILITY)
        _kk_save_setting(supabase, f_code, "keiyaku_jihi", _seed.KEIYAKU_JIHI)
        _kk_save_setting(supabase, f_code, "keiyaku_staff", _seed.KEIYAKU_STAFF)
        _kk_save_setting(supabase, f_code, "keiyaku_adds", _seed.KEIYAKU_ADDS)

        return jsonify({
            "status": "success",
            "message": f"初期データを投入しました（facility/jihi/staff/adds）。施設: {f_code}",
            "forced": force,
        })
    except Exception as e:
        print(f"api_keiyaku_seed error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500
# ===== /keiyaku-seed-v1 =====


@app.route("/admin/keiyaku/settings", methods=["GET"])  # keiyaku-calc-api-v1
@login_required
def api_keiyaku_settings_get():
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403

        facility = _kk_get_setting(supabase, f_code, "keiyaku_facility") or {}
        facility = _kk_ensure_service_order(facility)  # keiyaku-service-migrate-v1
        jihi = _kk_get_setting(supabase, f_code, "keiyaku_jihi") or []
        staff = _kk_get_setting(supabase, f_code, "keiyaku_staff") or []
        adds = _kk_get_setting(supabase, f_code, "keiyaku_adds") or {
            "kunren1": True, "kunren2": True, "kagaku": True, "shoguu": True}

        area_level = int(facility.get("area_level", 3)) if isinstance(facility, dict) else 3
        vpm = int(facility.get("visits_per_month", _KK_DEFAULT_VISITS_PER_MONTH)) if isinstance(facility, dict) else _KK_DEFAULT_VISITS_PER_MONTH

        # keiyaku-timeclass-app-v1: service._order があれば各種別キーで、無ければ旧 han/ichi 既定。
        _svc = facility.get("service", {}) if isinstance(facility, dict) else {}
        _order = _svc.get("_order") if isinstance(_svc, dict) else None
        if not (isinstance(_order, list) and _order):
            _order = ["han", "ichi"]
        _F_for_fee = {"service": _svc}
        fee = {st: _kk_build_fee_table(st, adds, area_level, vpm, _F_for_fee) for st in _order}

        return jsonify({
            "status": "success",
            "facility": facility, "jihi": jihi, "staff": staff, "adds": adds,
            "area_level": area_level, "visits_per_month": vpm,
            "unit_price": _kk_tanka(area_level),
            "fee": fee,
            "add_master": _kk_add_master_public(),  # keiyaku-c3-master-api-v1
        })
    except Exception as e:
        print(f"api_keiyaku_settings_get error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 設定API: POST（4キーを保存） ---
@app.route("/admin/keiyaku/settings", methods=["POST"])  # keiyaku-calc-api-v1
@login_required
def api_keiyaku_settings_save():
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403

        data = request.get_json(silent=True) or {}
        if "facility" in data:
            _kk_save_setting(supabase, f_code, "keiyaku_facility", data["facility"])
        if "jihi" in data:
            _kk_save_setting(supabase, f_code, "keiyaku_jihi", data["jihi"])
        if "staff" in data:
            _kk_save_setting(supabase, f_code, "keiyaku_staff", data["staff"])
        if "adds" in data:
            _kk_save_setting(supabase, f_code, "keiyaku_adds", data["adds"])

        return jsonify({"status": "success"})
    except Exception as e:
        print(f"api_keiyaku_settings_save error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500



# ===== keiyaku-service-migrate-v1 : service 構造補完ヘルパ＋移行API =====
_KK_SERVICE_DEFAULT_LABEL = {"han": "半日型（3時間）", "ichi": "1日型（7時間）"}
_KK_SERVICE_DEFAULT_TC = {"han": "3-4h", "ichi": "7-8h"}


def _kk_ensure_service_order(facility):
    """facility["service"] に _order/label/time_class を補完したコピーを返す（非破壊）。
    旧 han/ichi のみのデータでも種別構造として扱えるようにする。"""
    if not isinstance(facility, dict):
        return facility
    svc = facility.get("service")
    if not isinstance(svc, dict):
        return facility
    svc = dict(svc)  # 浅いコピー
    # _order 補完: 既存の種別キー（_order 以外の dict 値）を han,ichi 優先＋出現順で。
    keys = [k for k in svc.keys() if k != "_order" and isinstance(svc.get(k), dict)]
    order = svc.get("_order")
    if not (isinstance(order, list) and order):
        ordered = [k for k in ("han", "ichi") if k in keys]
        ordered += [k for k in keys if k not in ordered]
        order = ordered or ["han"]
    else:
        # _order にあるが実体が無いキーを除外、実体はあるが _order に無いキーを末尾追加。
        order = [k for k in order if k in keys] + [k for k in keys if k not in order]
        if not order:
            order = ["han"]
    svc["_order"] = order
    # 各種別の label / time_class 補完。
    for k in order:
        node = dict(svc.get(k) or {})
        if not node.get("label"):
            node["label"] = _KK_SERVICE_DEFAULT_LABEL.get(k, k)
        if not node.get("time_class"):
            node["time_class"] = _KK_SERVICE_DEFAULT_TC.get(k, "3-4h")
        svc[k] = node
    out = dict(facility)
    out["service"] = svc
    return out


@app.route("/admin/keiyaku/migrate_service", methods=["POST"])
@login_required
def api_keiyaku_migrate_service():
    """keiyaku-service-migrate-v1: 既存 service を _order/label/time_class 付き構造へ
    永続化する管理者限定API。既に _order があり force!=1 なら skip。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403

        force = request.args.get("force", "0") == "1"
        facility = _kk_get_setting(supabase, f_code, "keiyaku_facility") or {}
        if not isinstance(facility, dict):
            return jsonify({"status": "error", "message": "keiyaku_facility がありません"}), 400

        svc = facility.get("service", {})
        already = isinstance(svc, dict) and isinstance(svc.get("_order"), list) and svc.get("_order")
        if already and not force:
            return jsonify({"status": "skipped",
                            "message": "既に _order があります。上書きは ?force=1。",
                            "service_order": svc.get("_order")})

        migrated = _kk_ensure_service_order(facility)
        _kk_save_setting(supabase, f_code, "keiyaku_facility", migrated)
        return jsonify({"status": "success",
                        "message": "service を _order/label/time_class 構造へ移行しました。",
                        "service_order": migrated.get("service", {}).get("_order"),
                        "forced": force})
    except Exception as e:
        print(f"api_keiyaku_migrate_service error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500
# ===== /keiyaku-service-migrate-v1 =====
# ===== /keiyaku-calc-api-v1 =====



# ===== timecard-api-v1 : タイムカード機能 Phase 1 =====
# 打刻画面は公開ルート(ログイン不要)。有効デバイストークン必須。承認/設定は管理者限定。
from datetime import datetime as _tc_dt, timezone as _tc_tz, timedelta as _tc_td

_TC_PUNCH_TYPES = ("in", "out", "break_start", "break_end")
_TC_JST = _tc_tz(_tc_td(hours=9))


def _tc_now_jst():
    return _tc_dt.now(_TC_JST)


def _tc_today_range_jst(base=None):
    """JSTの当日 [00:00, 翌00:00) を UTC ISO 文字列で返す。"""
    d = (base or _tc_now_jst()).astimezone(_TC_JST)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + _tc_td(days=1)
    return start.astimezone(_tc_tz.utc).isoformat(), end.astimezone(_tc_tz.utc).isoformat()


def _tc_device_lookup(supabase, token):
    """有効なデバイスなら行(dict)を返す。無ければ None。"""
    if not token:
        return None
    try:
        res = supabase.table("timecard_devices").select("*").eq(
            "device_token", token).eq("is_active", True).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f"_tc_device_lookup error: {e}", flush=True)
        return None


def _tc_facility_enabled(supabase, f_code):
    try:
        res = supabase.table("facilities").select("timecard_enabled").eq(
            "facility_code", f_code).execute()
        rows = res.data or []
        return bool(rows and rows[0].get("timecard_enabled"))
    except Exception as e:
        print(f"_tc_facility_enabled error: {e}", flush=True)
        return False


def _tc_hidden_names(supabase, f_code):
    """timecard-hidden-icon-v1: 打刻画面に出さない職員名リスト(admin_settings)。"""
    try:
        import json as _json
        res = supabase.table("admin_settings").select("value").eq(
            "facility_code", f_code).eq("key", "timecard_hidden").execute()
        if res.data and res.data[0].get("value"):
            v = _json.loads(res.data[0]["value"])
            return set(v) if isinstance(v, list) else set()
        return set()
    except Exception as e:
        print(f"_tc_hidden_names error: {e}", flush=True)
        return set()


def _tc_staff_list(supabase, f_code):
    """timecard-hidden-icon-v1: 在籍職員(is_active)から timecard_hidden を除外。
    アイコンは icon_image_url(画像) を優先、無ければ icon_emoji。"""
    try:
        hidden = _tc_hidden_names(supabase, f_code)
        res = supabase.table("staffs").select(
            "staff_name,icon_emoji,icon_image_url").eq(
            "facility_code", f_code).eq("is_active", True).execute()
        out = []
        for r in (res.data or []):
            nm = r.get("staff_name")
            if not nm or nm in hidden:
                continue
            out.append({"name": nm,
                        "emoji": r.get("icon_emoji") or "",
                        "image": r.get("icon_image_url") or ""})
        return out
    except Exception as e:
        print(f"_tc_staff_list error: {e}", flush=True)
        return []


def _tc_today_punches(supabase, f_code, staff_name=None):
    """当日(JST)の打刻明細(論理削除除く)を時刻昇順で返す。"""
    start_iso, end_iso = _tc_today_range_jst()
    try:
        q = supabase.table("timecard_records").select("*").eq(
            "facility_code", f_code).eq("is_deleted", False).gte(
            "punched_at", start_iso).lt("punched_at", end_iso)
        if staff_name:
            q = q.eq("staff_name", staff_name)
        res = q.order("punched_at", desc=False).execute()
        return res.data or []
    except Exception as e:
        print(f"_tc_today_punches error: {e}", flush=True)
        return []


def _tc_staff_state(punches):
    """打刻列から現在状態を判定。'out'(未出勤/退勤済) 'working' 'break' のいずれか。
    最後の in/out と break の対応で素直に決める。"""
    state = "out"
    for p in punches:
        t = p.get("punch_type")
        if t == "in":
            state = "working"
        elif t == "out":
            state = "out"
        elif t == "break_start":
            if state == "working":
                state = "break"
        elif t == "break_end":
            if state == "break":
                state = "working"
    return state


@app.route("/timecard")
def timecard_page():
    """打刻画面(公開)。実際の可否はクライアントから /timecard/bootstrap で判定。"""
    return render_template("timecard.html")


@app.route("/timecard/bootstrap", methods=["POST"])
def timecard_bootstrap():
    """デバイストークンを照合し、有効なら施設名・職員リスト・各人の当日状態を返す。
    未登録/無効なら registered:false を返し職員情報は出さない(情報露出を避ける)。"""
    try:
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        supabase = get_supabase()
        dev = _tc_device_lookup(supabase, token)
        if not dev:
            return jsonify({"status": "ok", "registered": False})
        f_code = dev.get("facility_code")
        if not _tc_facility_enabled(supabase, f_code):
            return jsonify({"status": "ok", "registered": True,
                            "enabled": False,
                            "message": "この施設ではタイムカード機能が有効になっていません。"})
        # 施設名
        fac_name = f_code
        try:
            fr = supabase.table("facilities").select("facility_name").eq(
                "facility_code", f_code).execute()
            if fr.data and fr.data[0].get("facility_name"):
                fac_name = fr.data[0]["facility_name"]
        except Exception:
            pass
        # last_used_at 更新(失敗は無視)
        try:
            supabase.table("timecard_devices").update(
                {"last_used_at": _tc_now_jst().astimezone(_tc_tz.utc).isoformat()}
            ).eq("id", dev["id"]).execute()
        except Exception:
            pass
        staff = _tc_staff_list(supabase, f_code)
        punches = _tc_today_punches(supabase, f_code)
        by_staff = {}
        for p in punches:
            by_staff.setdefault(p.get("staff_name"), []).append(p)
        for s in staff:
            s["state"] = _tc_staff_state(by_staff.get(s["name"], []))
        return jsonify({"status": "ok", "registered": True, "enabled": True,
                        "facility_code": f_code, "facility_name": fac_name,
                        "device_label": dev.get("device_label") or "",
                        "staff": staff})
    except Exception as e:
        print(f"timecard_bootstrap error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/timecard/punch", methods=["POST"])
def timecard_punch():
    """打刻1件を記録(公開・有効token必須)。punch_type妥当性と施設有効を確認。"""
    try:
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        staff_name = (data.get("staff_name") or "").strip()
        punch_type = (data.get("punch_type") or "").strip()
        supabase = get_supabase()
        dev = _tc_device_lookup(supabase, token)
        if not dev:
            return jsonify({"status": "error", "message": "このデバイスは登録されていません。"}), 403
        f_code = dev.get("facility_code")
        if not _tc_facility_enabled(supabase, f_code):
            return jsonify({"status": "error", "message": "タイムカード機能が無効です。"}), 403
        if punch_type not in _TC_PUNCH_TYPES:
            return jsonify({"status": "error", "message": "打刻種別が不正です。"}), 400
        if not staff_name:
            return jsonify({"status": "error", "message": "職員が選択されていません。"}), 400
        # 職員が在籍しているか確認
        names = {s["name"] for s in _tc_staff_list(supabase, f_code)}
        if staff_name not in names:
            return jsonify({"status": "error", "message": "職員が見つかりません。"}), 400
        # 状態の簡易整合(二重出勤や break の入れ子崩れを防ぐ)
        punches = _tc_today_punches(supabase, f_code, staff_name)
        state = _tc_staff_state(punches)
        ok = {
            "in": state == "out",
            "out": state in ("working", "break"),
            "break_start": state == "working",
            "break_end": state == "break",
        }.get(punch_type, False)
        if not ok:
            msg = {"in": "すでに出勤済みです。", "out": "出勤打刻がありません。",
                   "break_start": "出勤中のみ休憩を開始できます。",
                   "break_end": "休憩中ではありません。"}.get(punch_type, "打刻できません。")
            return jsonify({"status": "error", "message": msg}), 409
        now_iso = _tc_now_jst().astimezone(_tc_tz.utc).isoformat()
        supabase.table("timecard_records").insert({
            "facility_code": f_code, "staff_name": staff_name,
            "punch_type": punch_type, "punched_at": now_iso,
            "device_token": token,
        }).execute()
        new_state = _tc_staff_state(_tc_today_punches(supabase, f_code, staff_name))
        return jsonify({"status": "success", "state": new_state,
                        "punched_at": now_iso})
    except Exception as e:
        print(f"timecard_punch error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/devices", methods=["GET"])
@login_required
def admin_timecard_devices():
    """施設のデバイス一覧(承認/未承認)。管理者限定。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        res = supabase.table("timecard_devices").select("*").eq(
            "facility_code", f_code).order("created_at", desc=True).execute()
        return jsonify({"status": "success", "devices": res.data or []})
    except Exception as e:
        print(f"admin_timecard_devices error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/timecard/device/request", methods=["POST"])
def timecard_device_request():
    """未登録デバイスの承認申請。client生成のtokenを is_active=false で登録。
    既に存在すれば何もしない(冪等)。管理者が後で承認する。"""
    try:
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        f_code = (data.get("facility_code") or "").strip()
        label = (data.get("label") or "").strip()
        if not token or not f_code:
            return jsonify({"status": "error", "message": "token と facility_code が必要です。"}), 400
        supabase = get_supabase()
        existing = supabase.table("timecard_devices").select("id,is_active").eq(
            "facility_code", f_code).eq("device_token", token).execute()
        if existing.data:
            return jsonify({"status": "ok", "message": "申請済みです。管理者の承認をお待ちください。"})
        supabase.table("timecard_devices").insert({
            "facility_code": f_code, "device_token": token,
            "device_label": label or "新しいデバイス", "is_active": False,
        }).execute()
        return jsonify({"status": "ok", "message": "申請しました。管理者の承認をお待ちください。"})
    except Exception as e:
        print(f"timecard_device_request error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/device/approve", methods=["POST"])
@login_required
def admin_timecard_device_approve():
    """デバイスを承認(is_active=true)。ラベルも更新可。管理者限定。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        data = request.get_json(silent=True) or {}
        dev_id = data.get("id")
        label = (data.get("label") or "").strip()
        if not dev_id:
            return jsonify({"status": "error", "message": "id が必要です。"}), 400
        upd = {"is_active": True, "approved_by": my_name}
        if label:
            upd["device_label"] = label
        supabase.table("timecard_devices").update(upd).eq(
            "id", dev_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_timecard_device_approve error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/device/revoke", methods=["POST"])
@login_required
def admin_timecard_device_revoke():
    """デバイスを無効化(is_active=false)。管理者限定。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        data = request.get_json(silent=True) or {}
        dev_id = data.get("id")
        if not dev_id:
            return jsonify({"status": "error", "message": "id が必要です。"}), 400
        supabase.table("timecard_devices").update({"is_active": False}).eq(
            "id", dev_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_timecard_device_revoke error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard", methods=["GET"])
@login_required
def admin_timecard_page():
    """当日の全職員打刻一覧(管理者画面)。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return redirect(url_for("admin"))
        return render_template("admin_timecard.html")
    except Exception as e:
        print(f"admin_timecard_page error: {e}", flush=True)
        return redirect(url_for("admin"))


@app.route("/admin/timecard/today", methods=["GET"])
@login_required
def admin_timecard_today():
    """当日(JST)の全職員打刻と状態(JSON)。管理者限定。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        punches = _tc_today_punches(supabase, f_code)
        by_staff = {}
        for p in punches:
            by_staff.setdefault(p.get("staff_name"), []).append(p)
        staff = _tc_staff_list(supabase, f_code)
        out = []
        for s in staff:
            ps = by_staff.get(s["name"], [])
            out.append({"name": s["name"], "emoji": s["emoji"],
                        "state": _tc_staff_state(ps),
                        "punches": [{"id": p["id"], "type": p["punch_type"],
                                     "at": p["punched_at"]} for p in ps]})
        return jsonify({"status": "success", "staff": out})
    except Exception as e:
        print(f"admin_timecard_today error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----- timecard-monthly-v1 : 月次労働時間集計 -----
def _tc_month_range_jst(year, month):
    """指定年月(JST)の [当月1日00:00, 翌月1日00:00) を UTC ISO で返す。"""
    start = _tc_dt(year, month, 1, 0, 0, 0, tzinfo=_TC_JST)
    if month == 12:
        end = _tc_dt(year + 1, 1, 1, 0, 0, 0, tzinfo=_TC_JST)
    else:
        end = _tc_dt(year, month + 1, 1, 0, 0, 0, tzinfo=_TC_JST)
    return start.astimezone(_tc_tz.utc).isoformat(), end.astimezone(_tc_tz.utc).isoformat()


def _tc_parse_iso(s):
    """SupabaseのISO文字列を aware datetime に。失敗時 None。"""
    if not s:
        return None
    try:
        t = s.replace("Z", "+00:00")
        return _tc_dt.fromisoformat(t)
    except Exception:
        try:
            return _tc_dt.fromisoformat(s[:19] + "+00:00")
        except Exception:
            return None


def _tc_day_key(iso):
    """打刻時刻(UTC ISO)を JST の YYYY-MM-DD に。"""
    dtv = _tc_parse_iso(iso)
    if not dtv:
        return None
    return dtv.astimezone(_TC_JST).strftime("%Y-%m-%d")


def _tc_compute_day(punches):
    """1日分の打刻列(時刻昇順)から労働時間(分)を計算。
    返り値: {"minutes": int|None, "incomplete": bool, "flags": [..],
             "in": iso|None, "out": iso|None, "break_min": int}
    欠損は補完しない: in欠落/out欠落/break_end欠落 は incomplete=True, minutes=None。"""
    flags = []
    in_t = None
    out_t = None
    work_min = 0
    break_min = 0
    cur_in = None
    cur_break = None
    incomplete = False

    for p in punches:
        t = p.get("punch_type")
        at = _tc_parse_iso(p.get("punched_at"))
        if at is None:
            continue
        if t == "in":
            if cur_in is not None:
                flags.append("二重出勤")
                incomplete = True
            cur_in = at
            if in_t is None:
                in_t = at
        elif t == "out":
            if cur_in is None:
                flags.append("出勤なしで退勤")
                incomplete = True
            else:
                # 退勤時に休憩が開いていれば未クローズ→補完せず印
                if cur_break is not None:
                    flags.append("休憩終了の打刻なし")
                    incomplete = True
                    cur_break = None
                work_min += int((at - cur_in).total_seconds() // 60)
                cur_in = None
            out_t = at
        elif t == "break_start":
            if cur_in is None:
                flags.append("勤務外の休憩")
                incomplete = True
            if cur_break is not None:
                flags.append("休憩が連続")
                incomplete = True
            cur_break = at
        elif t == "break_end":
            if cur_break is None:
                flags.append("休憩開始なしで終了")
                incomplete = True
            else:
                break_min += int((at - cur_break).total_seconds() // 60)
                cur_break = None

    # 走査後に開いたままの勤務/休憩がある → 退勤漏れ等
    if cur_in is not None:
        flags.append("退勤の打刻なし")
        incomplete = True
    if cur_break is not None:
        flags.append("休憩終了の打刻なし")
        incomplete = True

    minutes = None if incomplete else max(0, work_min - break_min)
    # 重複フラグを除去(順序維持)
    seen = set()
    uniq = []
    for fl in flags:
        if fl not in seen:
            seen.add(fl)
            uniq.append(fl)
    return {"minutes": minutes, "incomplete": incomplete, "flags": uniq,
            "in": in_t.isoformat() if in_t else None,
            "out": out_t.isoformat() if out_t else None,
            "break_min": break_min}


@app.route("/admin/timecard/monthly", methods=["GET"])
@login_required
def admin_timecard_monthly():
    """職員別・日別の労働時間と月合計(JSON)。管理者限定。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        now = _tc_now_jst()
        try:
            year = int(request.args.get("year", now.year))
            month = int(request.args.get("month", now.month))
        except (TypeError, ValueError):
            year, month = now.year, now.month
        if not (1 <= month <= 12):
            return jsonify({"status": "error", "message": "月が不正です。"}), 400

        start_iso, end_iso = _tc_month_range_jst(year, month)
        res = supabase.table("timecard_records").select("*").eq(
            "facility_code", f_code).eq("is_deleted", False).gte(
            "punched_at", start_iso).lt("punched_at", end_iso).order(
            "punched_at", desc=False).execute()
        rows = res.data or []

        # staff -> day -> punches
        by_staff = {}
        for r in rows:
            sn = r.get("staff_name")
            dk = _tc_day_key(r.get("punched_at"))
            if not sn or not dk:
                continue
            by_staff.setdefault(sn, {}).setdefault(dk, []).append(r)

        staff_master = _tc_staff_list(supabase, f_code)
        name_order = [s["name"] for s in staff_master]
        emoji_map = {s["name"]: s["emoji"] for s in staff_master}
        # 明細にしか出てこない退職者等も拾う
        for sn in by_staff.keys():
            if sn not in name_order:
                name_order.append(sn)

        result = []
        for sn in name_order:
            days_map = by_staff.get(sn, {})
            days = []
            total_min = 0
            worked_days = 0
            incomplete_days = 0
            for dk in sorted(days_map.keys()):
                comp = _tc_compute_day(days_map[dk])
                if comp["minutes"] is not None:
                    total_min += comp["minutes"]
                    if comp["minutes"] > 0:
                        worked_days += 1
                if comp["incomplete"]:
                    incomplete_days += 1
                days.append({"date": dk, "minutes": comp["minutes"],
                             "incomplete": comp["incomplete"], "flags": comp["flags"],
                             "in": comp["in"], "out": comp["out"],
                             "break_min": comp["break_min"]})
            result.append({"name": sn, "emoji": emoji_map.get(sn, ""),
                           "days": days, "total_minutes": total_min,
                           "worked_days": worked_days,
                           "incomplete_days": incomplete_days})

        return jsonify({"status": "success", "year": year, "month": month,
                        "staff": result})
    except Exception as e:
        print(f"admin_timecard_monthly error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/report", methods=["GET"])
@login_required
def admin_timecard_report_page():
    """月次集計の管理画面。"""
    try:
        f_code = session["f_code"]
        my_name = session.get("my_name", "")
        supabase = get_supabase()
        if not is_admin_user(supabase, f_code, my_name):
            return redirect(url_for("admin"))
        return render_template("admin_timecard_report.html")
    except Exception as e:
        print(f"admin_timecard_report_page error: {e}", flush=True)
        return redirect(url_for("admin"))

# ----- timecard-edit-v1 : 管理者による打刻編集(UPDATE方式・編集者/メモ記録) -----
def _tc_jst_to_utc_iso(date_str, time_str):
    """ "YYYY-MM-DD" + "HH:MM"(JST) を UTC ISO に。失敗時 None。"""
    try:
        y, mo, d = [int(x) for x in date_str.split("-")]
        hh, mm = [int(x) for x in time_str.split(":")]
        jst = _tc_dt(y, mo, d, hh, mm, 0, tzinfo=_TC_JST)
        return jst.astimezone(_tc_tz.utc).isoformat()
    except Exception:
        return None


def _tc_admin_guard():
    """(f_code, my_name, supabase) を返す。管理者でなければ (None,...)。"""
    f_code = session["f_code"]
    my_name = session.get("my_name", "")
    supabase = get_supabase()
    if not is_admin_user(supabase, f_code, my_name):
        return None, my_name, supabase
    return f_code, my_name, supabase


@app.route("/admin/timecard/edit", methods=["POST"])
@login_required
def admin_timecard_edit():
    """既存打刻の時刻を修正。punched_at を上書きし edited_by/note を記録。"""
    try:
        f_code, my_name, supabase = _tc_admin_guard()
        if f_code is None:
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        data = request.get_json(silent=True) or {}
        rec_id = data.get("id")
        date_str = (data.get("date") or "").strip()
        time_str = (data.get("time") or "").strip()
        note = (data.get("note") or "").strip()
        if not rec_id or not date_str or not time_str:
            return jsonify({"status": "error", "message": "id・date・time が必要です。"}), 400
        iso = _tc_jst_to_utc_iso(date_str, time_str)
        if not iso:
            return jsonify({"status": "error", "message": "日時の形式が不正です。"}), 400
        # 自施設の行のみ更新
        upd = {"punched_at": iso, "edited_by": my_name,
               "updated_at": _tc_now_jst().astimezone(_tc_tz.utc).isoformat()}
        if note:
            upd["note"] = note
        supabase.table("timecard_records").update(upd).eq(
            "id", rec_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_timecard_edit error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/add", methods=["POST"])
@login_required
def admin_timecard_add():
    """打刻を追加(打刻漏れの補完)。"""
    try:
        f_code, my_name, supabase = _tc_admin_guard()
        if f_code is None:
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        data = request.get_json(silent=True) or {}
        staff_name = (data.get("staff_name") or "").strip()
        punch_type = (data.get("punch_type") or "").strip()
        date_str = (data.get("date") or "").strip()
        time_str = (data.get("time") or "").strip()
        note = (data.get("note") or "").strip()
        if punch_type not in _TC_PUNCH_TYPES:
            return jsonify({"status": "error", "message": "打刻種別が不正です。"}), 400
        if not staff_name or not date_str or not time_str:
            return jsonify({"status": "error", "message": "職員・日付・時刻が必要です。"}), 400
        iso = _tc_jst_to_utc_iso(date_str, time_str)
        if not iso:
            return jsonify({"status": "error", "message": "日時の形式が不正です。"}), 400
        supabase.table("timecard_records").insert({
            "facility_code": f_code, "staff_name": staff_name,
            "punch_type": punch_type, "punched_at": iso,
            "edited_by": my_name, "note": note or "管理者が追加",
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_timecard_add error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/delete", methods=["POST"])
@login_required
def admin_timecard_delete():
    """打刻を論理削除(is_deleted=true)。"""
    try:
        f_code, my_name, supabase = _tc_admin_guard()
        if f_code is None:
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        data = request.get_json(silent=True) or {}
        rec_id = data.get("id")
        note = (data.get("note") or "").strip()
        if not rec_id:
            return jsonify({"status": "error", "message": "id が必要です。"}), 400
        upd = {"is_deleted": True, "edited_by": my_name,
               "updated_at": _tc_now_jst().astimezone(_tc_tz.utc).isoformat()}
        if note:
            upd["note"] = note
        supabase.table("timecard_records").update(upd).eq(
            "id", rec_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_timecard_delete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/admin/timecard/day", methods=["GET"])
@login_required
def admin_timecard_day():
    """指定職員・指定日(JST)の打刻明細(編集用。論理削除除く)。"""
    try:
        f_code, my_name, supabase = _tc_admin_guard()
        if f_code is None:
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        staff_name = (request.args.get("staff_name") or "").strip()
        date_str = (request.args.get("date") or "").strip()
        if not staff_name or not date_str:
            return jsonify({"status": "error", "message": "staff_name・date が必要です。"}), 400
        start_iso = _tc_jst_to_utc_iso(date_str, "00:00")
        end_dt = _tc_parse_iso(start_iso) + _tc_td(days=1)
        end_iso = end_dt.isoformat()
        res = supabase.table("timecard_records").select("*").eq(
            "facility_code", f_code).eq("staff_name", staff_name).eq(
            "is_deleted", False).gte("punched_at", start_iso).lt(
            "punched_at", end_iso).order("punched_at", desc=False).execute()
        out = [{"id": r["id"], "type": r["punch_type"], "at": r["punched_at"],
                "edited_by": r.get("edited_by"), "note": r.get("note")}
               for r in (res.data or [])]
        return jsonify({"status": "success", "punches": out})
    except Exception as e:
        print(f"admin_timecard_day error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/admin/timecard/device/delete", methods=["POST"])  # timecard-devdel-v1
def admin_timecard_device_delete():
    """不要なデバイス登録を物理削除。打刻記録は別テーブルなので残る。"""
    try:
        f_code, my_name, supabase = _tc_admin_guard()
        if f_code is None:
            return jsonify({"status": "error", "message": "管理者権限がありません"}), 403
        data = request.get_json(silent=True) or {}
        dev_id = data.get("id")
        if not dev_id:
            return jsonify({"status": "error", "message": "id が必要です。"}), 400
        # 自施設のデバイスのみ削除
        supabase.table("timecard_devices").delete().eq(
            "id", dev_id).eq("facility_code", f_code).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"admin_timecard_device_delete error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----- /timecard-edit-v1 -----

# ----- /timecard-monthly-v1 -----

# ===== /timecard-api-v1 =====


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
    VALID_CATEGORIES = {"入浴", "食事", "排泄", "その他", "コミュニケーション", "心身状況", "訓練状況", "ヒヤリハット", "休み連絡", "追加利用連絡"}  # extra-valid-categories-v1

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
    VALID_CATEGORIES = {"入浴", "食事", "排泄", "その他", "コミュニケーション", "心身状況", "訓練状況", "ヒヤリハット", "休み連絡", "追加利用連絡"}  # extra-valid-categories-v1
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


# fitness-check-api-v1
@app.route("/api/fitness_check")
@login_required
def api_fitness_check():  # fitness-check-username-v1
    """指定月の体重・体力測定の充足チェック一覧を返す。
    対象: その月にvitals(来所実績)がある利用者。
    実績なく休み連絡がある人は status=absent(休)。
    突き合わせは user_name ベース(patient_id は整数/UUID混在のため使わない)。"""
    import calendar as _cal
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        try:
            year = int(request.args.get("year"))
            month = int(request.args.get("month"))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "year/month必須"}), 400
        ndays = _cal.monthrange(year, month)[1]
        first = "%04d-%02d-01" % (year, month)
        last = "%04d-%02d-%02d" % (year, month, ndays)

        # ① 患者マスタ(user_name, chart_number, かな順)
        pts = supabase.table("patients").select("user_name, chart_number, user_kana").eq("facility_code", f_code).order("user_kana").execute()
        patients = pts.data or []

        # ② 当月 vitals → 実績のある user_name
        vit = supabase.table("vitals").select("user_name").eq("facility_code", f_code).gte("measured_date", first).lte("measured_date", last).execute()
        visited_names = set((r.get("user_name") or "").strip() for r in (vit.data or []) if r.get("user_name"))

        # ③ 当月の休み連絡(user_name) → 休み集合
        lv = supabase.table("records").select("user_name, leave_date_start, leave_date_end, created_at").eq("facility_code", f_code).eq("category", "休み連絡").execute()
        absent_names = set()
        for r in (lv.data or []):
            nm = (r.get("user_name") or "").strip()
            if not nm:
                continue
            ds = (r.get("leave_date_start") or "")[:10]
            de = (r.get("leave_date_end") or ds)[:10]
            ca = (r.get("created_at") or "")[:10]
            if (ds and first <= ds <= last) or (de and first <= de <= last) or (ca and first <= ca <= last):
                absent_names.add(nm)

        # ④ 当月 body_weights → 測定済 user_name
        bw = supabase.table("body_weights").select("user_name").eq("facility_code", f_code).gte("measured_date", first).lte("measured_date", last).execute()
        weight_done_names = set((r.get("user_name") or "").strip() for r in (bw.data or []) if r.get("user_name"))

        # ⑤ fitness_tests 全件(user_name, measured_date) → 各人の測定日リスト
        ftall = supabase.table("fitness_tests").select("user_name, measured_date").eq("facility_code", f_code).execute()
        fit_dates = {}
        for r in (ftall.data or []):
            nm = (r.get("user_name") or "").strip(); md = (r.get("measured_date") or "")[:10]
            if nm and md:
                fit_dates.setdefault(nm, []).append(md)
        for nm in fit_dates:
            fit_dates[nm].sort()
        fit_done_names = set()
        for nm, ds in fit_dates.items():
            if any(first <= d <= last for d in ds):
                fit_done_names.add(nm)

        # ⑥ fitness 設定(admin_settings)
        cycle_mode = "A"; base_months = [1, 4, 7, 10]
        try:
            st = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "fitness_check_settings").execute()
            if st.data:
                import json as _json
                sv = st.data[0].get("value")
                if isinstance(sv, str):
                    sv = _json.loads(sv)
                if isinstance(sv, dict):
                    cycle_mode = sv.get("cycle_mode", "A")
                    if isinstance(sv.get("base_months"), list) and sv.get("base_months"):
                        base_months = sv.get("base_months")
        except Exception as _se:
            print("[fitness_check] settings load error: %s" % _se, flush=True)

        def _is_fit_target(nm):
            if cycle_mode == "B":
                return month in base_months
            ds = fit_dates.get(nm) or []
            prev = [d for d in ds if d < first]
            if not prev:
                return True
            last_d = prev[-1]
            ly, lm = int(last_d[:4]), int(last_d[5:7])
            target_ym = ly * 12 + (lm - 1) + 3
            cur_ym = year * 12 + (month - 1)
            return cur_ym >= target_ym

        weight_rows = []
        fitness_rows = []
        for p in patients:
            nm = (p.get("user_name") or "").strip()
            chart = p.get("chart_number")
            if not nm:
                continue
            visited = nm in visited_names
            absent = (not visited) and (nm in absent_names)
            if not visited and not absent:
                continue
            base = {"patient_id": nm, "user_name": nm, "chart_number": chart}
            if absent:
                w_status = "absent"
            elif nm in weight_done_names:
                w_status = "done"
            else:
                w_status = "missing"
            wr = dict(base); wr["status"] = w_status; weight_rows.append(wr)
            if absent:
                f_status = "absent"
            elif nm in fit_done_names:
                f_status = "done"
            elif _is_fit_target(nm):
                f_status = "missing"
            else:
                f_status = "not_target"
            fr = dict(base); fr["status"] = f_status; fitness_rows.append(fr)

        return jsonify({
            "status": "success",
            "year": year, "month": month,
            "cycle_mode": cycle_mode,
            "base_months": base_months,
            "weights": weight_rows,
            "fitness": fitness_rows,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# fitness-check-settings-api-v1
@app.route("/api/fitness_check_settings", methods=["GET", "POST"])
@login_required
def api_fitness_check_settings():
    """体力測定サイクル設定の取得/保存(admin_settings: fitness_check_settings)"""
    import json as _json
    try:
        f_code = session["f_code"]
        supabase = get_supabase()
        if request.method == "GET":
            cycle_mode = "A"; base_months = [1, 4, 7, 10]
            st = supabase.table("admin_settings").select("value").eq("facility_code", f_code).eq("key", "fitness_check_settings").execute()
            if st.data:
                sv = st.data[0].get("value")
                if isinstance(sv, str):
                    sv = _json.loads(sv)
                if isinstance(sv, dict):
                    cycle_mode = sv.get("cycle_mode", "A")
                    if isinstance(sv.get("base_months"), list) and sv.get("base_months"):
                        base_months = sv.get("base_months")
            return jsonify({"status": "success", "cycle_mode": cycle_mode, "base_months": base_months})
        # POST
        data = request.json or {}
        cycle_mode = data.get("cycle_mode", "A")
        if cycle_mode not in ("A", "B"):
            cycle_mode = "A"
        base_months = data.get("base_months", [1, 4, 7, 10])
        if not isinstance(base_months, list):
            base_months = [1, 4, 7, 10]
        base_months = sorted(set(int(m) for m in base_months if isinstance(m, (int, float)) and 1 <= int(m) <= 12))
        if not base_months:
            base_months = [1, 4, 7, 10]
        value_json = _json.dumps({"cycle_mode": cycle_mode, "base_months": base_months})
        existing = supabase.table("admin_settings").select("id").eq("facility_code", f_code).eq("key", "fitness_check_settings").execute()
        if existing.data:
            supabase.table("admin_settings").update({"value": value_json}).eq("facility_code", f_code).eq("key", "fitness_check_settings").execute()
        else:
            supabase.table("admin_settings").insert({"facility_code": f_code, "key": "fitness_check_settings", "value": value_json}).execute()
        return jsonify({"status": "success", "cycle_mode": cycle_mode, "base_months": base_months})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
    "sheet_mode",  # lc-bi-mode-save-v1: 様式3-2(full)/BI(bi)
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
# ============================================================
# monitoring-pdf-endpoint-v1: モニタリング報告書サーバーサイドPDF生成
# クライアントで構築済みの#rep-root HTML断片を受け取り、画面の
# nav・入力フォームを含まない独立文書としてpdfkitでPDF化する。
# 印刷用CSSはmonitoring.htmlの.rep-*定義をパッチ適用時に自動抽出。
# ============================================================
_MONITORING_REPORT_CSS = """
.rep-root { font-family:'Hiragino Sans','Noto Sans JP',sans-serif; color:#202124; font-size:12px; line-height:1.5; width:100%; }
.rep-root, .rep-root table { width:100% !important; }
.rep-head { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; margin-bottom:10px; }
.rep-title { font-size:17px; font-weight:600; color:#0C447C; letter-spacing:0.04em; text-align:center; grid-column:2; }
.rep-date { font-size:10px; color:#888780; text-align:right; grid-column:3; }
.rep-date b { color:#202124; font-size:11px; font-weight:600; }
.rep-2col { display:flex; gap:10px; margin-bottom:8px; align-items:stretch; min-height:72px; }
.rep-box { flex:1; border:0.5px solid #C9C7BD; border-radius:4px; padding:12px 16px; }
.rep-box.fac { background:#FBFAF6; display:flex; align-items:center; gap:9px; }
.rep-fac-logo { width:40px; height:40px; border-radius:4px; object-fit:contain; flex-shrink:0; background:#E6F1FB; }
.rep-cm-office { font-size:15px; font-weight:700; color:#202124; border-left:3px solid #1a73e8; padding-left:8px; }
.rep-cm-name { font-size:13px; font-weight:600; margin-top:6px; color:#202124; padding-left:11px; }
.rep-fac-cat { font-size:9px; color:#5F5E5A; }
.rep-fac-name { font-size:12px; font-weight:600; }
.rep-fac-addr { font-size:9px; color:#5F5E5A; margin-top:2px; }
.rep-user { display:flex; border: 2px solid #1a73e8; border-radius:3px; margin-bottom:8px; background: #e8f0fe; overflow:hidden; }
.rep-user-main { flex:1; padding:6px 11px; display:flex; flex-wrap:wrap; gap:4px 18px; align-items:center; font-size:10px; }
.rep-user-kana { font-size:8px; color:#888780; display:block; line-height:1.2; }
.rep-user-name { font-size:13px; font-weight:600; color:#202124; display:block; line-height:1.2; }
.rep-user-meta-l { color:#888780; font-size:9px; margin-right:5px; }
        .rep-care-badge { display: inline-block; border: 1.5px solid #1a73e8; color: #1a73e8; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 1px 7px; margin-left: 2px; }
.rep-user-author { min-width:96px; padding:6px 9px; border-left:0.5px solid #C9C7BD; background:#fff; display:flex; flex-direction:column; justify-content:center; }
.rep-user-author span:first-child { color:#888780; font-size:8px; }
.rep-user-author span:last-child { font-size:11px; font-weight:600; margin-top:2px; }
.rep-goals { display:flex; gap:8px; margin-bottom:8px; }
.rep-goal-col { flex:1; }
.rep-goal-h { font-size:11px; font-weight:600; color:#0C447C; margin-bottom:4px; }
.rep-goal-h small { font-size:9px; color:#888780; font-weight:400; }
.rep-tbl { width:100%; border-collapse:collapse; font-size:9px; }
.rep-tbl td { border:0.5px solid #E0E0E0; padding:4px 5px; }
.rep-tbl td.k { width:38px; background:#FAFBFF; color:#5F5E5A; font-weight:600; }
.rep-tbl td.st { width:58px; text-align:center; font-weight:700; font-size:9px; }
.rep-tbl-cont { width:38px; text-align:center; font-size:9px; font-weight:700; border-radius:3px; }
.rep-tbl-cont.cont-keep { color:#5F6368; background:#F1F3F4; }
.rep-tbl-cont.cont-chg  { color:#E65100; background:#FFF3E0; }
.rep-tbl td.st-cont  { color:#BA7517; background:#FFF8E7; }
.rep-tbl td.st-done  { color:#1a7a3c; background:#E6F4EA; }
.rep-tbl td.st-part  { color:#1a55a8; background:#E8F0FE; }
.rep-tbl td.st-fail  { color:#c0392b; background:#FCE8E6; }
.rep-tbl td.st-other { color:#5f6368; }
.rep-free2 { display:flex; gap:8px; margin-bottom:8px; }
.rep-free { flex:1; border:0.5px solid #E0E0E0; border-radius:3px; padding:6px 9px; min-height: 80px; }
.rep-free-h { font-size: 11px; font-weight: 600; color: #0c447c; border-left: 3px solid #378add; padding-left: 7px; margin: 0 0 5px; }
.rep-free-b { font-size: 11px; line-height:1.55; white-space:pre-wrap; }
.rep-sec-h { font-size:11px; font-weight:600; color:#0C447C; border-left:3px solid #378ADD; padding-left:7px; margin:0 0 5px; }
.rep-mon-tbl { width:100%; border-collapse:collapse; font-size:9px; margin-bottom:8px; }
.rep-mon-tbl td { border:0.5px solid #E0E0E0; padding:5px 7px; vertical-align:top; min-height: 72px; }
.rep-mon-tbl td.cat { width:74px; background:#FAFBFF; color:#5F5E5A; font-weight:600; }
.rep-fit-h { display:flex; justify-content:space-between; align-items:baseline; border-left:3px solid #1D9E75; padding-left:7px; margin-bottom:5px; }
.rep-fit-h span:first-child { font-size:11px; font-weight:600; color:#04342C; }
.rep-fit-h span:last-child { font-size:8px; color:#888780; }
.rep-fit-grid { display:flex; gap:5px; margin-bottom:8px; flex-wrap:wrap; }
.rep-fit-card { flex:1; min-width:90px; border:0.5px solid #E0E0E0; border-radius:3px; padding:4px 6px; }
.rep-fit-card-h { font-size:8px; color:#5F5E5A; display:flex; justify-content:space-between; }
.rep-fit-card-h b { color:#0F6E56; }
.rep-special { border:0.5px solid #E0E0E0; border-radius:3px; padding:6px 9px; margin-bottom:8px; font-size:9px; }
.rep-special b { color:#04342C; font-weight:600; }
.rep-req { border:0.5px solid #C9C7BD; border-radius:3px; overflow:hidden; margin-bottom:6px; }
.rep-req-top { display:flex; align-items:center; border-bottom:0.5px solid #E0E0E0; }
.rep-req-top .l { flex:1; padding:5px 9px; font-size:9px; }
.rep-req-top .r { padding:5px 11px; font-size:9px; border-left:0.5px solid #E0E0E0; display:flex; gap:14px; }
.rep-req-body { display:flex; }
.rep-req-body .l { width:96px; padding:5px 9px; font-size:9px; color:#5F5E5A; background:#FAFBFF; border-right:0.5px solid #E0E0E0; }
.rep-req-body .r { flex:1; padding:5px 9px; font-size:9px; min-height:22px; }
.rep-sat { display:flex; gap:8px; align-items:stretch; font-size:9px; margin-bottom:6px; }
.rep-sat-box { border:0.5px solid #C9C7BD; border-radius:3px; padding:5px 11px; display:flex; align-items:center; gap:6px; }
.rep-sat-box .v { font-size:13px; font-weight:600; color:#0F6E56; }
.rep-sat-leg { flex:1; display:flex; align-items:center; justify-content:flex-end; font-size:7px; color:#B4B2A9; }
.rep-foot { border-top:0.5px solid #E0E0E0; padding-top:6px; margin-top:8px; text-align:right; font-size:8px; color:#888780; }
"""

@app.route('/api/monitoring_report_pdf', methods=['POST'])
@login_required
def api_monitoring_report_pdf():
    """モニタリング報告書をサーバーサイドでPDF化して返す。
    body: {"html": "<div id=\\"rep-root\\">...</div>", "filename": "..."}
    """
    try:
        data = request.get_json(force=True) or {}
        rep_html = data.get("html", "")
        if not rep_html or "rep-root" not in rep_html:
            return jsonify({"status": "error", "message": "invalid html"}), 400

        # 簡易サニタイズ: scriptタグ等は除去（PDF化用途のみのため最小限）
        import re as _re
        safe_html = _re.sub(r'<script[\s\S]*?</script>', '', rep_html, flags=_re.IGNORECASE)
        safe_html = _re.sub(r'\son\w+\s*=\s*"[^"]*"', '', safe_html, flags=_re.IGNORECASE)
        safe_html = _re.sub(r"\son\w+\s*=\s*'[^']*'", '', safe_html, flags=_re.IGNORECASE)

        # monitoring-pdf-margin-fix-v1: wkhtmltopdfは@pageのCSS margin指定を正しく解釈しないため、
        # @page{margin:0}にし、.page-padの実寸paddingで余白を作る
        # （既存の契約書PDF(keiyaku_render.py)と同じ技法）。
        # monitoring-pdf-fitgrid-table-v1: wkhtmltopdfはFlexboxのサポートが不完全で
        # .rep-fit-grid(体力測定カード)が横並びにならず縦積みになり
        # ページを大幅に消費する不具合が発生したため、PDF生成時のみ
        # table/table-cellレイアウトに上書きする(画面表示には影響しない)。
        # monitoring-pdf-compact-v1: A4 1ページにできるだけ収まるよう、PDF生成時のみ
        # フォントサイズをわずかに縮小し、各セクションの余白を詰める。
        # monitoring-pdf-fitlevel-server-v1: fit_levelに応じてCSSを切り替える（自動フィット機能の土台）
        try:
            fit_level = int(data.get("fit_level", 2))
        except (TypeError, ValueError):
            fit_level = 2
        fit_level = max(0, min(8, fit_level))  # monitoring-pdf-fitlevel-extend4-server-v1

        # monitoring-pdf-free2-stack-server-v1: 個別機能訓練実施による変化/課題とその要因の
        # 2カラム表示は各枠にmin-height:80pxがあり、文章が短いと
        # 大きな空白ができてページを消費するため、PDF生成時は
        # 縦積み・全幅表示に変更し、折り返し行数と空白を減らす。
        _FITGRID_FIX_CSS = (
            '.rep-fit-grid { display:table !important; width:100% !important; '
            'table-layout:fixed !important; border-collapse:separate !important; '
            'border-spacing:5px 0 !important; } '
            '.rep-fit-card { display:table-cell !important; flex:none !important; '
            'width:auto !important; vertical-align:top !important; } '
            '.rep-free2 { display:block !important; } '
            '.rep-free { width:100% !important; min-height:0 !important; } '
            '.rep-free + .rep-free { margin-top:5px !important; } '
            # monitoring-pdf-font-fix-v1: 'Hiragino Sans'/'Noto Sans JP'はサーバー上に存在せず、
            # 意図しないフォールバックフォントで幅広く描画されていたため、
            # 実際にインストール済みの'Noto Sans CJK JP'を明示指定する。
            '.rep-root { font-family: "Noto Sans CJK JP", "Noto Sans JP", sans-serif !important; }'
        )

        _FITLEVEL_CSS = {
            0: '',
            1: (
                '.rep-fit-grid { margin-bottom:6px !important; } '
                '.rep-root { font-size:11.5px !important; } '
                '.rep-2col { margin-bottom:6px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:6px !important; } '
                '.rep-goals { margin-bottom:6px !important; } '
                '.rep-free2 { margin-bottom:6px !important; } '
                '.rep-free { min-height:0 !important; padding:5px 8px !important; } '
                '.rep-mon-tbl { margin-bottom:6px !important; } '
                '.rep-mon-tbl td { padding:4px 7px !important; min-height:0 !important; '
                'line-height:1.4 !important; } '
                '.rep-fit-h { margin-bottom:3px !important; } '
                '.rep-special { margin-bottom:4px !important; padding:5px 8px !important; } '
                '.rep-sat { margin-bottom:3px !important; } '
                '.rep-req { margin-bottom:4px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:4px 8px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:4px 8px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:5px !important; padding-top:4px !important; }'
            ),
            2: (
                '.rep-fit-grid { margin-bottom:5px !important; } '
                '.rep-root { font-size:11px !important; } '
                '.rep-2col { margin-bottom:5px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:5px !important; } '
                '.rep-goals { margin-bottom:5px !important; } '
                '.rep-free2 { margin-bottom:5px !important; } '
                '.rep-free { min-height:0 !important; padding:4px 7px !important; } '
                '.rep-mon-tbl { margin-bottom:5px !important; } '
                '.rep-mon-tbl td { padding:4px 6px !important; min-height:0 !important; '
                'line-height:1.3 !important; } '
                '.rep-fit-h { margin-bottom:2px !important; } '
                '.rep-special { margin-bottom:3px !important; padding:4px 7px !important; } '
                '.rep-sat { margin-bottom:2px !important; } '
                '.rep-req { margin-bottom:3px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:3px 7px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:3px 7px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:3px !important; padding-top:3px !important; }'
            ),
            3: (
                '.rep-fit-grid { margin-bottom:4px !important; } '
                '.rep-root { font-size:10.5px !important; } '
                '.rep-2col { margin-bottom:4px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:4px !important; } '
                '.rep-goals { margin-bottom:4px !important; } '
                '.rep-free2 { margin-bottom:4px !important; } '
                '.rep-free { min-height:0 !important; padding:3px 6px !important; } '
                '.rep-mon-tbl { margin-bottom:4px !important; } '
                '.rep-mon-tbl td { padding:3px 5px !important; min-height:0 !important; '
                'line-height:1.25 !important; } '
                '.rep-fit-h { margin-bottom:2px !important; } '
                '.rep-special { margin-bottom:2px !important; padding:3px 6px !important; } '
                '.rep-sat { margin-bottom:2px !important; } '
                '.rep-req { margin-bottom:2px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:2px 6px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:2px 6px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:2px !important; padding-top:2px !important; } '
                # monitoring-pdf-chart-height-cap-server-v1
                '.rep-fit-card svg, .rep-fit-card img { max-height:48px !important; '
                'width:auto !important; display:block !important; margin:0 auto !important; }'
            ),
            4: (
                '.rep-fit-grid { margin-bottom:3px !important; } '
                '.rep-root { font-size:10px !important; } '
                '.rep-2col { margin-bottom:3px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:3px !important; } '
                '.rep-goals { margin-bottom:3px !important; } '
                '.rep-free2 { margin-bottom:3px !important; } '
                '.rep-free { min-height:0 !important; padding:3px 5px !important; } '
                '.rep-mon-tbl { margin-bottom:3px !important; } '
                '.rep-mon-tbl td { padding:2px 4px !important; min-height:0 !important; '
                'line-height:1.2 !important; } '
                '.rep-fit-h { margin-bottom:1px !important; } '
                '.rep-special { margin-bottom:2px !important; padding:2px 5px !important; } '
                '.rep-sat { margin-bottom:1px !important; } '
                '.rep-req { margin-bottom:2px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:2px 5px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:2px 5px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:2px !important; padding-top:2px !important; } '
                '.rep-fit-card svg, .rep-fit-card img { max-height:36px !important; '
                'width:auto !important; display:block !important; margin:0 auto !important; }'
            ),
            5: (
                '.rep-fit-grid { margin-bottom:2px !important; } '
                '.rep-root { font-size:9.5px !important; } '
                '.rep-2col { margin-bottom:2px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:2px !important; } '
                '.rep-goals { margin-bottom:2px !important; } '
                '.rep-free2 { margin-bottom:2px !important; } '
                '.rep-free { min-height:0 !important; padding:2px 4px !important; } '
                '.rep-mon-tbl { margin-bottom:2px !important; } '
                '.rep-mon-tbl td { padding:2px 3px !important; min-height:0 !important; '
                'line-height:1.15 !important; } '
                '.rep-fit-h { margin-bottom:1px !important; } '
                '.rep-special { margin-bottom:1px !important; padding:2px 4px !important; } '
                '.rep-sat { margin-bottom:1px !important; } '
                '.rep-req { margin-bottom:1px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:1px 4px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:1px 4px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:1px !important; padding-top:1px !important; } '
                '.rep-fit-card svg, .rep-fit-card img { max-height:28px !important; '
                'width:auto !important; display:block !important; margin:0 auto !important; }'
            ),
            6: (
                '.rep-fit-grid { margin-bottom:1px !important; } '
                '.rep-root { font-size:9px !important; } '
                '.rep-2col { margin-bottom:1px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:1px !important; } '
                '.rep-goals { margin-bottom:1px !important; } '
                '.rep-free2 { margin-bottom:1px !important; } '
                '.rep-free { min-height:0 !important; padding:2px 3px !important; } '
                '.rep-mon-tbl { margin-bottom:1px !important; } '
                '.rep-mon-tbl td { padding:1px 3px !important; min-height:0 !important; '
                'line-height:1.1 !important; } '
                '.rep-fit-h { margin-bottom:1px !important; } '
                '.rep-special { margin-bottom:1px !important; padding:1px 3px !important; } '
                '.rep-sat { margin-bottom:1px !important; } '
                '.rep-req { margin-bottom:1px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:1px 3px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:1px 3px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:1px !important; padding-top:1px !important; } '
                '.rep-fit-card svg, .rep-fit-card img { max-height:22px !important; '
                'width:auto !important; display:block !important; margin:0 auto !important; }'
            ),
            7: (
                '.rep-fit-grid { margin-bottom:1px !important; } '
                '.rep-root { font-size:8.5px !important; } '
                '.rep-2col { margin-bottom:1px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:1px !important; } '
                '.rep-goals { margin-bottom:1px !important; } '
                '.rep-free2 { margin-bottom:1px !important; } '
                '.rep-free { min-height:0 !important; padding:1px 3px !important; } '
                '.rep-mon-tbl { margin-bottom:1px !important; } '
                '.rep-mon-tbl td { padding:1px 2px !important; min-height:0 !important; '
                'line-height:1.05 !important; } '
                '.rep-fit-h { margin-bottom:0px !important; } '
                '.rep-special { margin-bottom:1px !important; padding:1px 2px !important; } '
                '.rep-sat { margin-bottom:0px !important; } '
                '.rep-req { margin-bottom:1px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:1px 2px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:1px 2px !important; min-height:0 !important; } '
                '.rep-foot { margin-top:1px !important; padding-top:1px !important; } '
                '.rep-fit-card svg, .rep-fit-card img { max-height:18px !important; '
                'width:auto !important; display:block !important; margin:0 auto !important; }'
            ),
            8: (
                '.rep-fit-grid { margin-bottom:0px !important; } '
                '.rep-root { font-size:8px !important; } '
                '.rep-2col { margin-bottom:0px !important; min-height:0 !important; } '
                '.rep-user { margin-bottom:0px !important; } '
                '.rep-goals { margin-bottom:0px !important; } '
                '.rep-free2 { margin-bottom:0px !important; } '
                '.rep-free { min-height:0 !important; padding:1px 2px !important; } '
                '.rep-mon-tbl { margin-bottom:0px !important; } '
                '.rep-mon-tbl td { padding:1px 2px !important; min-height:0 !important; '
                'line-height:1.0 !important; } '
                '.rep-fit-h { margin-bottom:0px !important; } '
                '.rep-special { margin-bottom:0px !important; padding:1px 2px !important; } '
                '.rep-sat { margin-bottom:0px !important; } '
                '.rep-req { margin-bottom:0px !important; } '
                '.rep-req-top .l, .rep-req-top .r { padding:1px 2px !important; font-size:8px !important; } '
                '.rep-req-body .l, .rep-req-body .r { padding:1px 2px !important; min-height:0 !important; font-size:8px !important; } '
                '.rep-foot { margin-top:0px !important; padding-top:0px !important; } '
                '.rep-fit-card svg, .rep-fit-card img { max-height:16px !important; '
                'width:auto !important; display:block !important; margin:0 auto !important; } '
                # monitoring-pdf-tail-squeeze-server-v1: これまで対象外だったrep-sat-box/rep-req-topの固定値を縮小
                '.rep-sat-box { padding:2px 6px !important; } '
                '.rep-sat-box .v { font-size:10px !important; } '
                '.rep-sat-leg { font-size:6px !important; }'
            ),
        }

        # monitoring-pdf-verify-loop-v1: 実際にPDFを生成しpdfinfoでページ数を確認、
        # 1枚に収まらなければfit_levelを上げて再生成する(最大レベル8まで)。
        # ブラウザ側計測とサーバー側レンダリングの食い違いを吸収するため。
        import pdfkit, shutil as _sh
        options = {
            "encoding": "UTF-8",
            "no-outline": None,
            "quiet": "",
            "disable-smart-shrinking": "",
            "margin-top": "0",
            "margin-right": "0",
            "margin-bottom": "0",
            "margin-left": "0",
        }
        wk_path = _sh.which("wkhtmltopdf") or "/usr/local/bin/wkhtmltopdf"
        config = pdfkit.configuration(wkhtmltopdf=wk_path)

        def _count_pdf_pages(_pdf_bytes):
            import tempfile, subprocess
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf") as _tf:
                    _tf.write(_pdf_bytes)
                    _tf.flush()
                    _out = subprocess.run(
                        ["pdfinfo", _tf.name], capture_output=True, text=True, timeout=10
                    )
                    for _line in _out.stdout.splitlines():
                        if _line.startswith("Pages:"):
                            return int(_line.split(":")[1].strip())
            except Exception:
                return None
            return None

        # monitoring-pdf-readable-cap-v1: フォント縮小は読みやすさを保てる範囲(レベル4=10.5px)
        # までに制限。それでも1ページに収まらない場合はフォントを
        # これ以上縮めず、体力測定グラフだけを文末(2ページ目)に移動し、
        # それより後ろにあった特記事項・希望・満足度等のテキストは
        # 元の位置のまま1ページ目側に残す（実質的に引き上げられる）。
        _READABLE_MAX_LEVEL = 4
        _PAGE_BREAK_BEFORE_FIT_CSS = (
            '.rep-fit-h { page-break-before: always !important; '
            'break-before: page !important; }'
        )

        def _extract_div_block(_html, _class_name):
            import re as __re
            _pat = __re.compile(r'<div[^>]*\bclass="' + __re.escape(_class_name) + r'"[^>]*>')
            _m = _pat.search(_html)
            if not _m:
                return None
            _start = _m.start()
            _pos = _m.end()
            _depth = 1
            _tag_re = __re.compile(r'<div\b|</div>')
            for _tm in _tag_re.finditer(_html, _pos):
                if _tm.group() == '</div>':
                    _depth -= 1
                    if _depth == 0:
                        _end = _tm.end()
                        return (_start, _end, _html[_start:_end])
                else:
                    _depth += 1
            return None

        def _move_fitness_section_to_end(_html):
            _fit_h = _extract_div_block(_html, 'rep-fit-h')
            _fit_grid = _extract_div_block(_html, 'rep-fit-grid')
            if not _fit_h or not _fit_grid:
                return _html
            _blocks = sorted([_fit_h, _fit_grid], key=lambda _b: _b[0])
            _early, _late = _blocks[0], _blocks[1]
            _reordered = _html[:_late[0]] + _html[_late[1]:]
            _reordered = _reordered[:_early[0]] + _reordered[_early[1]:]
            _combined = _early[2] + _late[2]
            _last_close = _reordered.rfind('</div>')
            if _last_close != -1:
                _reordered = _reordered[:_last_close] + _combined + _reordered[_last_close:]
            else:
                _reordered = _reordered + _combined
            return _reordered

        def _build_full_html(_body_html, _extra_css):
            return (
                '<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<style>@page { size: A4 portrait; margin: 0; } '
                'html, body { margin:0; padding:0; } '
                '.page-pad { padding: 8mm; box-sizing: border-box; } '
                + _MONITORING_REPORT_CSS + _extra_css +
                '</style></head><body><div class="page-pad">' + _body_html + '</div></body></html>'
            )

        _level = min(fit_level, _READABLE_MAX_LEVEL)
        pdf_bytes = None
        _fits_one_page = False
        while _level <= _READABLE_MAX_LEVEL:
            _extra_css = _FITGRID_FIX_CSS + _FITLEVEL_CSS.get(_level, _FITLEVEL_CSS[_READABLE_MAX_LEVEL])
            _full_html = _build_full_html(safe_html, _extra_css)
            pdf_bytes = pdfkit.from_string(_full_html, False, options=options, configuration=config)
            _pages = _count_pdf_pages(pdf_bytes)
            if _pages is None:
                _fits_one_page = True
                break
            if _pages <= 1:
                _fits_one_page = True
                break
            _level += 1

        if not _fits_one_page:
            # monitoring-pdf-remove-forced-break-v1: 強制改ページを外し、並び替えのみで自然な流れに任せる。
            _reordered_html = _move_fitness_section_to_end(safe_html)
            _extra_css = (
                _FITGRID_FIX_CSS
                + _FITLEVEL_CSS.get(_READABLE_MAX_LEVEL, _FITLEVEL_CSS[4])
            )
            _full_html = _build_full_html(_reordered_html, _extra_css)
            pdf_bytes = pdfkit.from_string(_full_html, False, options=options, configuration=config)

        from flask import make_response
        from urllib.parse import quote
        fname = (data.get("filename") or "monitoring_report.pdf").strip() or "monitoring_report.pdf"
        if not fname.endswith(".pdf"):
            fname += ".pdf"
        fname_encoded = quote(fname)
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = (
            f"attachment; filename=monitoring_report.pdf; filename*=UTF-8''{fname_encoded}"
        )
        return response
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
@app.route('/api/line/webhook', methods=['POST'])  # line-webhook-legacy-rename-v1 (legacy/unused)
def line_webhook_legacy():
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


# onboard-checkout-v1 : 施設オンボーディング用 Checkout 作成(ログイン不要)
# LIFFフォームから施設名・管理者名・LINE userId・plan・term を受け取り、
# onboard_id を発番して metadata に載せる。決済完了で stripe_webhook の
# onboard-webhook-v1 分岐が施設を自動発行する。
@app.route('/api/onboard/create_checkout', methods=['POST'])
def onboard_create_checkout():
    import secrets as _oc_secrets
    stripe.api_key = get_secret("STRIPE_SECRET_KEY")
    data = request.get_json(silent=True) or {}
    facility_name = (data.get("facility_name") or "").strip()
    admin_name = (data.get("admin_name") or "").strip()
    contact_email = (data.get("email") or "").strip()  # onboard-email-v1
    line_user_id = (data.get("line_user_id") or "").strip()
    plan = (data.get("plan") or "starter").lower()
    term = (data.get("term") or "monthly").lower()
    base_url = request.host_url.rstrip("/")

    if not facility_name or not admin_name:
        return jsonify({"error": "facility_name and admin_name required"}), 400
    # onboard-line-required-v1 : 初回管理者を必ず2FA可能にするため line_user_id を必須化
    if not line_user_id:
        return jsonify({"error": "line_required",
            "message": "お申し込みにはLINEの友だち追加が必要です。LINEから開いてやり直してください。"}), 400
    if plan not in ("starter", "standard", "pro"):
        return jsonify({"error": "invalid plan: " + plan}), 400

    # 既存 create_checkout と同一の term マッピング
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

    onboard_id = _oc_secrets.token_urlsafe(24)
    try:
        params = dict(
            mode=checkout_mode,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=base_url + "/onboard/done?st=success",
            cancel_url=base_url + "/onboard/done?st=cancel",
            metadata={
                "onboard_id": onboard_id,
                "facility_name": facility_name,
                "admin_name": admin_name,
                "line_user_id": line_user_id,
                "plan": plan,
                "term": term,
                "email": contact_email,
            },
            locale="ja",
        )
        # subscription のときは1ヶ月無料トライアルを付与(初月無課金)
        if contact_email:  # onboard-email-v1 : Stripe顧客にもメールを設定
            params["customer_email"] = contact_email
        if checkout_mode == "subscription":
            params["subscription_data"] = {
                "trial_period_days": 30,
                "metadata": {"onboard_id": onboard_id},
            }
        checkout = stripe.checkout.Session.create(**params)
        return jsonify({"url": checkout.url})
    except Exception as e:
        print("[Onboard] checkout error: " + str(e), flush=True)
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
        # onboard-webhook-v1 : 新規施設オンボーディング(まだ施設が存在しない状態での決済)
        onboard_id = meta.get("onboard_id")
        if onboard_id:
            try:
                import secrets as _ob_secrets
                import hashlib as _ob_hashlib
                from datetime import datetime as _ob_dt, timedelta as _ob_td, timezone as _ob_tz
                supabase = get_supabase()
                # 冪等: 同じ onboard_id の施設が既にあれば再発行しない(Stripeの再送対策)
                dup = supabase.table("facilities").select("facility_code").eq("onboard_id", onboard_id).execute()
                if dup.data:
                    print(f"[Onboard] onboard_id {onboard_id} already provisioned; skip", flush=True)
                    return jsonify({"status": "ok"}), 200
                ob_plan = meta.get("plan", "starter")
                ob_term = meta.get("term", "monthly")
                ob_fac_name = (meta.get("facility_name") or "").strip() or "新規施設"
                ob_admin_name = (meta.get("admin_name") or "").strip() or "管理者"
                ob_user_id = (meta.get("line_user_id") or "").strip()
                # 施設コード: 意味を持たないランダム(f + 10桁hex)。衝突時は数回リトライ
                new_code = None
                for _ in range(5):
                    cand = "f" + _ob_secrets.token_hex(5)
                    ex = supabase.table("facilities").select("facility_code").eq("facility_code", cand).execute()
                    if not ex.data:
                        new_code = cand
                        break
                if not new_code:
                    print("[Onboard] failed to allocate facility_code", flush=True)
                    return jsonify({"status": "ok"}), 200
                _ob_now = _ob_dt.now(_ob_tz.utc)
                # 1ヶ月無料トライアル: 初月はトライアル、有効期限=トライアル終了日
                trial_end = _ob_now + _ob_td(days=30)
                supabase.table("facilities").insert({
                    "facility_code": new_code,
                    "facility_name": ob_fac_name,
                    "plan": ob_plan,
                    "is_active": True,
                    "trial_ends_at": trial_end.isoformat(),
                    "expires_at": trial_end.isoformat(),
                    "stripe_subscription_id": session_data.get("subscription"),
                    "stripe_customer_id": session_data.get("customer"),
                    "onboard_id": onboard_id,
                    "contact_email": (meta.get("email") or "").strip() or None,  # onboard-email-v1
                }).execute()
                # 管理者職員を作成(パスワードは未設定=空。初回設定リンクで本人が設定する)
                setup_token = _ob_secrets.token_urlsafe(32)
                setup_exp = (_ob_now + _ob_td(hours=24)).isoformat()
                supabase.table("staffs").insert({
                    "facility_code": new_code,
                    "staff_name": ob_admin_name,
                    "password_hash": "",
                    "is_active": True,
                    "setup_token": setup_token,
                    "setup_token_expires": setup_exp,
                    "email": (meta.get("email") or "").strip() or None,  # onboard-email-v1
                    "line_user_id": ob_user_id or None,  # onboard-admin-line-link-v1 : 初回管理者を2FA可能に紐付け
                }).execute()
                # LINEで初回設定リンクを本人(userId)に送信。パスワードは送らない=履歴に残さない
                setup_url = request.host_url.rstrip("/") + "/setup?token=" + setup_token
                if ob_user_id:
                    line_send_message(ob_user_id, [{
                        "type": "text",
                        "text": "\n".join([
                            "【TASUKARU】ご登録ありがとうございます。",
                            "",
                            "施設名: " + ob_fac_name,
                            "施設コード: " + new_code,
                            "管理者: " + ob_admin_name,
                            "",
                            "下のリンクから初回パスワードを設定してください(24時間有効)。",
                            setup_url,
                        ])
                    }])
                # 開発者にも新規契約を通知(施設コードのみ。トークン等は載せない)
                line_notify_admin("\n".join([
                    "【TASUKARU】新規オンボーディング",
                    "施設名: " + ob_fac_name,
                    "施設コード: " + new_code,
                    "プラン: " + ob_plan,
                ]))
                print(f"[Onboard] provisioned {new_code} (plan={ob_plan})", flush=True)
            except Exception as _ob_e:
                print(f"[Onboard] error: {_ob_e}", flush=True)
            return jsonify({"status": "ok"}), 200

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
        BASE_PROMPT = (  # prompt-tone-v1
            "あなたは介護施設のベテラン介護職員です。"
            f"【対象の確認(最重要)】\n"
            f"この報告の対象はご利用者「{u_name}」様です。記録には複数の職員や他のご利用者が登場することがありますが、報告対象は常に「{u_name}」様です。主語を取り違えないでください。\n"
            "以下の介護記録を読み、担当者会議などで他事業所のケアマネジャーに提出するモニタリング報告書として使える文章を生成してください。\n"
            "【ルール】\n"
            "・事実として記録されていること以外は絶対に書かない\n"
            "・記録がない場合は「今月このカテゴリの報告はありませんでした」とだけ返す\n"
            "・対象の利用者様の名前は必要に応じて使ってよいが、毎回主語として繰り返す必要はなく、自然な場合は主語を省いて行動や状態を書く\n"
            "・職員の名前は書かず、必要な場合は「職員」と表記する\n"
            "・この文書は他事業所のケアマネジャーに提出します。対象の利用者様以外の人名（他の利用者・他のご家族など）が記録に出てきても、実名は一切書かず「他の利用者様」と表記する\n"
            "・箇条書きは使わず、ひとつながりの文章で書く\n"
            "・口調は外部のケアマネジャーへの報告文書として読みやすい丁寧語(です・ます)。二重敬語や過剰な敬語(「お〜になられる」「ございました」等)は避け、硬すぎず砕けすぎない自然な丁寧さにとどめる\n"
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
    print("[DEBUG] cats_json from URL:", cats_json, flush=True)
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
    # cats-default-init: cats が空の場合、全カテゴリをデフォルト true で初期化
    if not cats:
        CATEGORIES_PRINT = ["心身状況", "食事", "入浴", "排泄", "コミュニケーション", "訓練状況", "ヒヤリハット", "その他"]
        cats = {cat: True for cat in CATEGORIES_PRINT}

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
    print("[DEBUG] cats_json from URL:", cats_json, flush=True)
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
    # cats-default-init: cats が空の場合、全カテゴリをデフォルト true で初期化
    if not cats:
        CATEGORIES_PRINT = ["心身状況", "食事", "入浴", "排泄", "コミュニケーション", "訓練状況", "ヒヤリハット", "その他"]
        cats = {cat: True for cat in CATEGORIES_PRINT}

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


# ==========================================
# jisseki-clsummary-v1: 実績集計(第2段階A) 介護度別の実人数・延べ人数
# 集計源: vitals(来所実績) / 判定軸: care_level_history(月末時点の介護度)
# 保険/自費の区別は未実装(2Bで追加)
# ==========================================
import calendar as _jis_cal
from datetime import date as _jis_date

# 提出帳票の介護度区分(表示順)
_JIS_CARE_ORDER = [
    "\u4e8b\u696d\u5bfe\u8c61\u8005",  # 事業対象者
    "\u8981\u652f\u63f41",            # 要支援1
    "\u8981\u652f\u63f42",            # 要支援2
    "\u8981\u4ecb\u8b771",            # 要介護1
    "\u8981\u4ecb\u8b772",            # 要介護2
    "\u8981\u4ecb\u8b773",            # 要介護3
    "\u8981\u4ecb\u8b774",            # 要介護4
    "\u8981\u4ecb\u8b775",            # 要介護5
]


def _jis_level_at_month_end(history_rows, month_end_iso):
    """その利用者の履歴行(list of dict)から、
    month_end_iso(月末日 'YYYY-MM-DD')時点で有効な care_level を返す。
    valid_from <= 月末日 の中で valid_from 最大(同日なら id 最大)を採用。"""
    best = None
    for h in history_rows:
        vf = (h.get("valid_from") or "")[:10]
        if not vf or vf > month_end_iso:
            continue
        if best is None:
            best = h
        else:
            bvf = (best.get("valid_from") or "")[:10]
            if vf > bvf or (vf == bvf and (h.get("id") or 0) > (best.get("id") or 0)):
                best = h
    return (best.get("care_level") if best else None)



# === jisseki-archive-api-v1: 過去月アーカイブ参照ヘルパ ===
def _jisseki_archive_lookup(supabase, f_code, year, month, kind):
    """対象月のアーカイブ payload[kind] を返す。無ければ None。
    kind: 'care_level_summary' or 'service_time_summary'。
    既存集計には影響しない読み取り専用。"""
    try:
        res = supabase.table("jisseki_archive").select("payload") \
            .eq("facility_code", f_code).eq("year", year).eq("month", month) \
            .limit(1).execute()
        rows = res.data or []
        if not rows:
            return None
        payload = rows[0].get("payload") or {}
        return payload.get(kind)
    except Exception as _e:
        print("_jisseki_archive_lookup error: %s" % _e, flush=True)
        return None


@app.route("/api/jisseki/care_level_summary", methods=["GET"])
@login_required
def api_jisseki_care_level_summary():
    """jisseki-clsummary-v1: 対象月の介護度別 実人数/延べ人数/割合を返す。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        year = int(request.args.get("year"))
        month = int(request.args.get("month"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "year/month\u5fc5\u9808"}), 400
    try:
        ndays = _jis_cal.monthrange(year, month)[1]
        first = "%04d-%02d-01" % (year, month)
        last = "%04d-%02d-%02d" % (year, month, ndays)

        # 1) vitals から 来所日(patient_id, measured_date) を取得
        vit = supabase.table("vitals").select("patient_id, measured_date") \
            .eq("facility_code", f_code) \
            .gte("measured_date", first).lte("measured_date", last).execute()
        # (patient_id, date) をユニーク化 → 来所日集合
        visit_days = {}  # patient_id -> set(date)
        for r in (vit.data or []):
            pid = r.get("patient_id")
            md = (r.get("measured_date") or "")[:10]
            if not pid or not md:
                continue
            visit_days.setdefault(pid, set()).add(md)

        patient_ids = list(visit_days.keys())
        if not patient_ids:
            # jisseki-archive-api-v1: vitals空ならアーカイブ参照(あれば返す)
            _arch = _jisseki_archive_lookup(supabase, f_code, year, month, "care_level_summary")
            if _arch is not None:
                return jsonify(_arch)
            # データ無しでも区分は0埋めで返す
            rows = [{"care_level": lv, "jin": 0, "nobe": 0, "jin_pct": 0.0, "nobe_pct": 0.0} for lv in _JIS_CARE_ORDER]
            return jsonify({"status": "success", "year": year, "month": month,
                            "rows": rows, "no_level": {"jin": 0, "nobe": 0},
                            "total": {"jin": 0, "nobe": 0}})

        # 2) care_level_history を 対象利用者分一括取得(N+1回避)
        #    patient_id は uuid カラムだが文字列で in 指定可能
        hist_map = {}  # patient_id(str) -> list of history dict
        CHUNK = 100
        for i in range(0, len(patient_ids), CHUNK):
            chunk = patient_ids[i:i + CHUNK]
            hres = supabase.table("care_level_history") \
                .select("patient_id, care_level, valid_from, id") \
                .eq("facility_code", f_code).in_("patient_id", chunk).execute()
            for h in (hres.data or []):
                hist_map.setdefault(str(h.get("patient_id")), []).append(h)

        # 3) 介護度別に集計
        agg = {lv: {"jin": 0, "nobe": 0} for lv in _JIS_CARE_ORDER}
        no_level = {"jin": 0, "nobe": 0}
        for pid, dates in visit_days.items():
            nobe = len(dates)  # 来所日数
            lv = _jis_level_at_month_end(hist_map.get(str(pid), []), last)
            if lv in agg:
                agg[lv]["jin"] += 1
                agg[lv]["nobe"] += nobe
            else:
                no_level["jin"] += 1
                no_level["nobe"] += nobe

        total_jin = sum(a["jin"] for a in agg.values()) + no_level["jin"]
        total_nobe = sum(a["nobe"] for a in agg.values()) + no_level["nobe"]

        def _pct(n, d):
            return round((n * 100.0 / d), 1) if d else 0.0

        rows = []
        for lv in _JIS_CARE_ORDER:
            a = agg[lv]
            rows.append({
                "care_level": lv,
                "jin": a["jin"],
                "nobe": a["nobe"],
                "jin_pct": _pct(a["jin"], total_jin),
                "nobe_pct": _pct(a["nobe"], total_nobe),
            })

        return jsonify({
            "status": "success",
            "year": year, "month": month,
            "rows": rows,
            "no_level": no_level,
            "total": {"jin": total_jin, "nobe": total_nobe},
        })
    except Exception as e:
        print("api_jisseki_care_level_summary error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-page-v1: 実績集計 画面
# ==========================================
@app.route("/admin/jisseki")
@login_required
def admin_jisseki():
    """jisseki-page-v1: 実績集計表の表示(管理者MENU)。"""
    if not session.get("admin_authenticated", False):
        return redirect(url_for("dev_login"))
    return render("admin_jisseki.html")


# ==========================================
# jisseki-svctime-v1: 提供時間の曜日設定(施設単位)
# weekday: 0=日 .. 6=土 (JS Date.getDay() と揃える)
# ==========================================
@app.route("/api/jisseki/service_time_settings", methods=["GET"])
@login_required
def api_jisseki_svctime_get():
    """jisseki-svctime-v1: 施設の曜日→提供時間設定を返す。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        res = supabase.table("service_time_settings") \
            .select("weekday, time_category").eq("facility_code", f_code).execute()
        settings = {}
        for r in (res.data or []):
            settings[str(r.get("weekday"))] = r.get("time_category")
        return jsonify({"status": "success", "settings": settings})
    except Exception as e:
        print("api_jisseki_svctime_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/jisseki/service_time_settings", methods=["POST"])
@login_required
def api_jisseki_svctime_save():
    """jisseki-svctime-v1: 7曜日分の提供時間設定を保存(upsert/削除)。
    body: {settings: {"0":"7-8h", "1":"3-4h", ...}} 空文字列/nullは「営業なし」=削除。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        data = request.json or {}
        settings = data.get("settings") or {}
        for wd in range(0, 7):
            key = str(wd)
            cat = (settings.get(key) or "").strip()
            if cat:
                # upsert(facility_code, weekday の UNIQUE で上書き)
                supabase.table("service_time_settings").upsert({
                    "facility_code": f_code,
                    "weekday": wd,
                    "time_category": cat,
                }, on_conflict="facility_code,weekday").execute()
            else:
                # 営業なし = その曜日の設定を削除
                supabase.table("service_time_settings").delete() \
                    .eq("facility_code", f_code).eq("weekday", wd).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print("api_jisseki_svctime_save error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-svctime-summary-v1: 提供時間別 延べ人数の集計(step2)
# 介護サービス(要介護)=時間幅区分別 / 総合事業(要支援・事業対象者)=5h未満/5-7h/7h以上
# 保険分のみ集計。自費は別カウント。
# ==========================================
_JIS_TIME_CATS = ['2-3h','3-4h','4-5h','5-6h','6-7h','7-8h','8-9h','9-10h','10-11h','11-12h','12-13h','13-14h']
_JIS_KAIGO_LEVELS = set(['\u8981\u4ecb\u8b771','\u8981\u4ecb\u8b772','\u8981\u4ecb\u8b773','\u8981\u4ecb\u8b774','\u8981\u4ecb\u8b775'])
_JIS_SOGO_LEVELS = set(['\u4e8b\u696d\u5bfe\u8c61\u8005','\u8981\u652f\u63f41','\u8981\u652f\u63f42'])


def _jis_time_lower_bound(cat):
    """\'3-4h\' -> 3 (\u4e0b\u9650\u6642\u6570)\u3002\u4e0d\u660e\u306f None\u3002"""
    try:
        return int(str(cat).split('-')[0])
    except Exception:
        return None


def _jis_sogo_bucket(cat):
    """\u6642\u9593\u5e45\u533a\u5206 -> \u7dcf\u5408\u4e8b\u696d\u306e\u7c97\u533a\u5206(\u4e0b\u9650\u3067\u5224\u5b9a)\u3002"""
    lb = _jis_time_lower_bound(cat)
    if lb is None:
        return None
    if lb < 5:
        return '5h\u672a\u6e80'
    if lb < 7:
        return '5-7h'
    return '7h\u4ee5\u4e0a'


@app.route("/api/jisseki/service_time_summary", methods=["GET"])
@login_required
def api_jisseki_svctime_summary():
    """jisseki-svctime-summary-v1: 提供時間別 延べ人数を返す(保険分のみ+自費別カウント)。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        year = int(request.args.get("year"))
        month = int(request.args.get("month"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "year/month\u5fc5\u9808"}), 400
    try:
        import calendar as _c
        from datetime import date as _d
        ndays = _c.monthrange(year, month)[1]
        first = "%04d-%02d-01" % (year, month)
        last = "%04d-%02d-%02d" % (year, month, ndays)

        # 1) vitals: (patient_id, measured_date) ユニーク
        vit = supabase.table("vitals").select("patient_id, measured_date") \
            .eq("facility_code", f_code) \
            .gte("measured_date", first).lte("measured_date", last).execute()
        visit_days = {}  # patient_id -> set(date_iso)
        for r in (vit.data or []):
            pid = r.get("patient_id"); md = (r.get("measured_date") or "")[:10]
            if pid and md:
                visit_days.setdefault(pid, set()).add(md)
        patient_ids = list(visit_days.keys())

        # 空ならゼロで返す
        def _empty():
            kaigo = {c: 0 for c in _JIS_TIME_CATS}
            sogo = {'5h\u672a\u6e80': 0, '5-7h': 0, '7h\u4ee5\u4e0a': 0}
            return kaigo, sogo
        if not patient_ids:
            # jisseki-archive-api-v1: vitals空ならアーカイブ参照(あれば返す)
            _arch = _jisseki_archive_lookup(supabase, f_code, year, month, "service_time_summary")
            if _arch is not None:
                return jsonify(_arch)
            kaigo, sogo = _empty()
            return jsonify({"status": "success", "year": year, "month": month,
                            "kaigo": kaigo, "sogo": sogo,
                            "jihi": {"kaigo": 0, "sogo": 0},
                            "unclassified": 0})

        # 2) care_level_history 一括(月末時点の介護度)
        hist_map = {}
        CHUNK = 100
        for i in range(0, len(patient_ids), CHUNK):
            chunk = patient_ids[i:i+CHUNK]
            hres = supabase.table("care_level_history") \
                .select("patient_id, care_level, valid_from, id") \
                .eq("facility_code", f_code).in_("patient_id", chunk).execute()
            for h in (hres.data or []):
                hist_map.setdefault(str(h.get("patient_id")), []).append(h)

        def level_at(pid):
            best = None
            for h in hist_map.get(str(pid), []):
                vf = (h.get("valid_from") or "")[:10]
                if not vf or vf > last:
                    continue
                if best is None or vf > (best.get("valid_from") or "")[:10] or \
                   (vf == (best.get("valid_from") or "")[:10] and (h.get("id") or 0) > (best.get("id") or 0)):
                    best = h
            return (best.get("care_level") if best else None)

        # 3) service_time_settings(施設の曜日→提供時間)
        sts = supabase.table("service_time_settings").select("weekday, time_category") \
            .eq("facility_code", f_code).execute()
        wd_cat = {}  # weekday(int) -> time_category
        for r in (sts.data or []):
            wd_cat[int(r.get("weekday"))] = r.get("time_category")

        # 4) patient_jihi_weekdays(利用者×曜日の自費)
        pjw = {}  # patient_id -> set(weekday)
        for i in range(0, len(patient_ids), CHUNK):
            chunk = patient_ids[i:i+CHUNK]
            pres = supabase.table("patient_jihi_weekdays").select("patient_id, weekday") \
                .eq("facility_code", f_code).in_("patient_id", chunk).execute()
            for r in (pres.data or []):
                pjw.setdefault(str(r.get("patient_id")), set()).add(int(r.get("weekday")))

        # 5) visit_day_overrides(来所日ごとの上書き)
        ovr = {}  # (patient_id, date_iso) -> {time_category, payment_type}
        for i in range(0, len(patient_ids), CHUNK):
            chunk = patient_ids[i:i+CHUNK]
            ores = supabase.table("visit_day_overrides") \
                .select("patient_id, visit_date, time_category, payment_type") \
                .eq("facility_code", f_code).in_("patient_id", chunk) \
                .gte("visit_date", first).lte("visit_date", last).execute()
            for r in (ores.data or []):
                key = (str(r.get("patient_id")), (r.get("visit_date") or "")[:10])
                ovr[key] = {"time_category": r.get("time_category"), "payment_type": r.get("payment_type")}

        # 6) 集計
        kaigo, sogo = _empty()
        jihi_kaigo = 0
        jihi_sogo = 0
        unclassified = 0

        for pid, dates in visit_days.items():
            lv = level_at(pid)
            is_kaigo = lv in _JIS_KAIGO_LEVELS
            is_sogo = lv in _JIS_SOGO_LEVELS
            jihi_wds = pjw.get(str(pid), set())
            for ds in dates:
                o = ovr.get((str(pid), ds), {})
                # 提供時間区分
                cat = o.get("time_category")
                if not cat:
                    wd = _d.fromisoformat(ds).weekday()  # Mon=0..Sun=6
                    # service_time_settings は 0=日..6=土 なので換算: JS getDayと揃える
                    js_wd = (wd + 1) % 7  # Python Mon=0 -> JSは Mon=1; Sun: Py=6 -> JS=0
                    cat = wd_cat.get(js_wd)
                # 保険/自費判定
                ptype = o.get("payment_type")
                if not ptype:
                    wd = _d.fromisoformat(ds).weekday()
                    js_wd = (wd + 1) % 7
                    ptype = "jihi" if js_wd in jihi_wds else "hoken"
                # 集計
                if ptype == "jihi":
                    if is_kaigo: jihi_kaigo += 1
                    elif is_sogo: jihi_sogo += 1
                    continue
                # 保険分
                if not cat:
                    unclassified += 1
                    continue
                if is_kaigo:
                    if cat in kaigo: kaigo[cat] += 1
                    else: unclassified += 1
                elif is_sogo:
                    b = _jis_sogo_bucket(cat)
                    if b: sogo[b] += 1
                    else: unclassified += 1
                else:
                    unclassified += 1

        return jsonify({"status": "success", "year": year, "month": month,
                        "kaigo": kaigo, "sogo": sogo,
                        "jihi": {"kaigo": jihi_kaigo, "sogo": jihi_sogo},
                        "unclassified": unclassified})
    except Exception as e:
        print("api_jisseki_svctime_summary error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-jihi-wd-v1: 利用者の自費曜日設定 (patient_jihi_weekdays)
# weekday: 0=日 .. 6=土 (JS Date.getDay() と揃える)
# ==========================================
@app.route("/api/jisseki/patient_jihi_weekdays", methods=["GET"])
@login_required
def api_jisseki_jihi_wd_get():
    """jisseki-jihi-wd-v1: 指定利用者の自費曜日を返す。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    pid = (request.args.get("patient_id") or "").strip()
    if not pid:
        return jsonify({"status": "error", "message": "patient_id\u5fc5\u9808"}), 400
    try:
        res = supabase.table("patient_jihi_weekdays").select("weekday") \
            .eq("facility_code", f_code).eq("patient_id", pid).execute()
        weekdays = sorted([int(r.get("weekday")) for r in (res.data or [])])
        return jsonify({"status": "success", "weekdays": weekdays})
    except Exception as e:
        print("api_jisseki_jihi_wd_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/jisseki/patient_jihi_weekdays", methods=["POST"])
@login_required
def api_jisseki_jihi_wd_save():
    """jisseki-jihi-wd-v1: 利用者の自費曜日を保存(全削除→再挿入)。
    body: {patient_id: "...", weekdays: [0,6]}"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        data = request.json or {}
        pid = (data.get("patient_id") or "").strip()
        if not pid:
            return jsonify({"status": "error", "message": "patient_id\u5fc5\u9808"}), 400
        wds = data.get("weekdays") or []
        # 既存を全削除してから再挿入(シンプル・確実)
        supabase.table("patient_jihi_weekdays").delete() \
            .eq("facility_code", f_code).eq("patient_id", pid).execute()
        rows = []
        seen = set()
        for w in wds:
            try:
                wi = int(w)
            except (TypeError, ValueError):
                continue
            if wi < 0 or wi > 6 or wi in seen:
                continue
            seen.add(wi)
            rows.append({"facility_code": f_code, "patient_id": pid, "weekday": wi})
        if rows:
            supabase.table("patient_jihi_weekdays").insert(rows).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print("api_jisseki_jihi_wd_save error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-visit-override-v1: 来所日ごとの保険/自費上書き (visit_day_overrides)
# patient_id = patient_profiles.id (uuid、vitalsと同基準)
# ==========================================
@app.route("/api/jisseki/visit_overrides", methods=["GET"])
@login_required
def api_jisseki_visit_overrides_get():
    """jisseki-visit-override-v1: 指定日の全上書きを返す(一括)。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    date = (request.args.get("date") or "").strip()
    if not date:
        return jsonify({"status": "error", "message": "date\u5fc5\u9808"}), 400
    try:
        res = supabase.table("visit_day_overrides") \
            .select("patient_id, payment_type, time_category") \
            .eq("facility_code", f_code).eq("visit_date", date).execute()
        overrides = {}
        for r in (res.data or []):
            overrides[str(r.get("patient_id"))] = {
                "payment_type": r.get("payment_type"),
                "time_category": r.get("time_category"),
            }
        return jsonify({"status": "success", "overrides": overrides})
    except Exception as e:
        print("api_jisseki_visit_overrides_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/jisseki/visit_override", methods=["POST"])
@login_required
def api_jisseki_visit_override_save():
    """jisseki-visit-override-v1: 1件の上書きを upsert。
    body: {patient_id(uuid), visit_date, payment_type?('hoken'|'jihi'), time_category?}
    payment_type と time_category が両方 null/空 なら行を削除。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        data = request.json or {}
        pid = (data.get("patient_id") or "").strip()
        vdate = (data.get("visit_date") or "").strip()
        if not pid or not vdate:
            return jsonify({"status": "error", "message": "patient_id/visit_date\u5fc5\u9808"}), 400
        ptype = data.get("payment_type")
        if ptype not in ("hoken", "jihi", None, ""):
            return jsonify({"status": "error", "message": "payment_type\u4e0d\u6b63"}), 400
        ptype = ptype or None
        tcat = (data.get("time_category") or None)
        # 両方空なら行削除(デフォルトに戻す)
        if not ptype and not tcat:
            supabase.table("visit_day_overrides").delete() \
                .eq("facility_code", f_code).eq("patient_id", pid).eq("visit_date", vdate).execute()
            return jsonify({"status": "success", "deleted": True})
        supabase.table("visit_day_overrides").upsert({
            "facility_code": f_code,
            "patient_id": pid,
            "visit_date": vdate,
            "payment_type": ptype,
            "time_category": tcat,
        }, on_conflict="facility_code,patient_id,visit_date").execute()
        return jsonify({"status": "success"})
    except Exception as e:
        print("api_jisseki_visit_override_save error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-jihi-all-v1: 施設全体の自費曜日デフォルトを一括取得
# ==========================================
@app.route("/api/jisseki/jihi_weekdays_all", methods=["GET"])
@login_required
def api_jisseki_jihi_all_get():
    """jisseki-jihi-all-v1: {patient_id: [weekday,...]} を返す。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    try:
        res = supabase.table("patient_jihi_weekdays").select("patient_id, weekday") \
            .eq("facility_code", f_code).execute()
        out = {}
        for r in (res.data or []):
            out.setdefault(str(r.get("patient_id")), []).append(int(r.get("weekday")))
        return jsonify({"status": "success", "data": out})
    except Exception as e:
        print("api_jisseki_jihi_all_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-voverride-range-v1: 来所日上書きを月範囲で一括取得(利用管理ページ用)
# ==========================================
@app.route("/api/jisseki/visit_overrides_range", methods=["GET"])
@login_required
def api_jisseki_voverride_range_get():
    """jisseki-voverride-range-v1: 指定利用者の start〜end の上書きを {date: {...}} で返す。"""
    f_code = session.get("f_code")
    supabase = get_supabase()
    pid = (request.args.get("patient_id") or "").strip()
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    if not pid or not start or not end:
        return jsonify({"status": "error", "message": "patient_id/start/end\u5fc5\u9808"}), 400
    try:
        res = supabase.table("visit_day_overrides") \
            .select("visit_date, payment_type, time_category") \
            .eq("facility_code", f_code).eq("patient_id", pid) \
            .gte("visit_date", start).lte("visit_date", end).execute()
        out = {}
        for r in (res.data or []):
            out[str(r.get("visit_date"))] = {
                "payment_type": r.get("payment_type"),
                "time_category": r.get("time_category"),
            }
        return jsonify({"status": "success", "overrides": out})
    except Exception as e:
        print("api_jisseki_voverride_range_get error: %s" % e, flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# jisseki-print-route-v1: 実績集計の印刷専用ページ
# ==========================================
# --- meetings-transcribe-summarize-v1 : 会議 録音→文字起こし / 議事録生成 ---
def _meetings_gate_ok():
    """meetings_enabled ゲート。OKなら(True, f_code, my_name)。"""
    if "f_code" not in session:
        return (False, None, None)
    f_code = session["f_code"]
    my_name = session.get("my_name", "")
    try:
        supabase = get_supabase()
        g = supabase.table("admin_settings").select("value")\
            .eq("facility_code", f_code).eq("key", "meetings_enabled").execute()
        enabled = False
        if g.data:
            v = g.data[0].get("value")
            enabled = (v is True) or (str(v).lower() in ("true", "1", '"true"'))
        return (enabled, f_code, my_name)
    except Exception:
        return (False, f_code, my_name)


# meetings-transcribe-chunk-v1
@app.route("/api/meeting/transcribe", methods=["POST"])
@login_required
def api_meeting_transcribe():
    """会議録音のチャンク1個を受け取り、Storageに保存しつつGeminiで文字起こし。
    長時間会議はフロントで時間分割(方式1)し、このAPIを順次呼ぶ。
    受け取り: audio(file), session_id(録音セッションUUID), chunk_index(0始まり)。"""
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        from utils import get_generative_model
        audio = request.files.get("audio")
        if not audio:
            return jsonify({"status": "error", "message": "音声なし"})
        filename = (audio.filename or "").lower()
        audio_bytes = audio.read()
        if not audio_bytes:
            return jsonify({"status": "error", "message": "音声データが空です"})
        if len(audio_bytes) < 2048:
            return jsonify({"status": "error", "message": "音声が短すぎます。もう一度お話しください。"})
        ext_mime = {
            ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".wav": "audio/wav",  ".aac": "audio/aac",
            ".ogg": "audio/ogg",  ".webm": "audio/webm",
            ".mp4": "audio/mp4",
        }
        mime = next((v for k, v in ext_mime.items() if filename.endswith(k)), "audio/webm")

        # --- チャンク音声を Storage に保存 (assessment-audio バケット流用) ---
        import re as _re2
        session_id = (request.form.get("session_id") or "").strip()
        # session_id はフロント発行のUUID。安全のため英数-のみ許可。
        session_id = _re2.sub(r"[^0-9a-zA-Z\-]", "", session_id)[:64]
        try:
            chunk_index = int(request.form.get("chunk_index") or 0)
        except Exception:
            chunk_index = 0
        ext = mime.split("/")[-1]
        if ext == "mpeg":
            ext = "mp3"
        audio_url = ""
        if session_id:
            try:
                supabase = get_supabase()
                path = f"{f_code}/meetings/{session_id}/{chunk_index:04d}.{ext}"
                supabase.storage.from_("assessment-audio").upload(
                    path=path, file=audio_bytes,
                    file_options={"content-type": mime}
                )
                audio_url = supabase.storage.from_("assessment-audio").get_public_url(path)
            except Exception as _ue:
                # 保存失敗しても文字起こしは続行(fail-safe)。
                print(f"[meeting] chunk upload failed: {_ue}", flush=True)
                audio_url = ""

        prompt = """これは介護施設の担当者会議(サービス担当者会議)の録音です。
発話内容を、話し言葉のフィラー(えー・あのー等)を除いて、正確に文字起こししてください。
・発言者が判別できる場合は「ケアマネ:」「指導員:」等の話者ラベルを付けてよい(不明なら省略)。
・数値・固有名詞(利用者名・薬名・部位名)は聞き取れた通りに残す。
・要約や解釈はせず、あくまで発話の文字起こしに徹する。
出力は文字起こし本文のみ。前置き・説明・マークダウンは不要。"""
        model = get_generative_model()
        resp = model.generate_content([{"mime_type": mime, "data": audio_bytes}, prompt])
        text = (resp.text or "").strip()
        # 無音チャンク等でテキストが空でもエラーにしない(連結時に飛ばせるよう空文字返す)
        return jsonify({"status": "success", "transcript": text,
                        "chunk_index": chunk_index, "audio_url": audio_url,
                        "session_id": session_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _mtg_parse_minutes_struct(text):  # meetings-minutes-struct-parse-v1 / fix meetings-minutes-struct-parse-fix-v1
    """第4表議事録本文(■ 見出し)を構造化dictに分解。Gemini不要・高速。"""
    import re as _re_p
    if not text:
        return None
    # ■ で始まる見出しごとに分割
    sections = {}
    cur = None
    buf = []
    for line in text.split("\n"):
        s = line.strip()
        m = _re_p.match(r"^[■◆●]\s*(.+)$", s)
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur = m.group(1).strip()
            buf = []
        else:
            if cur is not None:
                buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()

    def _find(*keys):
        for k, v in sections.items():
            for key in keys:
                if key in k:
                    return v
        return ""

    def _to_list(block):
        out = []
        for ln in (block or "").split("\n"):
            t = ln.strip().lstrip("・.-　 ").strip()
            if t:
                out.append(t)
        return out

    # 開催情報からheaderを抽出
    kaisai = _find("開催情報")
    header = {"date": "（記載なし）", "place": "（記載なし）", "attendees": [], "absentees": "（記載なし）"}
    if kaisai:
        att_mode = False
        for ln in kaisai.split("\n"):
            t = ln.strip()
            if not t:
                continue
            if "開催日" in t:
                header["date"] = t.split("：", 1)[-1].split(":", 1)[-1].split("/", 1)[-1].strip() or "（記載なし）"
                att_mode = False
            elif "開催場所" in t:
                header["place"] = t.split("：", 1)[-1].split(":", 1)[-1].strip() or "（記載なし）"
                att_mode = False
            elif "欠席" in t:
                header["absentees"] = t.split("：", 1)[-1].split(":", 1)[-1].strip() or "（記載なし）"
                att_mode = False
            elif "出席者" in t:
                v = t.split("：", 1)[-1].split(":", 1)[-1].strip()
                if v:
                    header["attendees"].append(v)
                att_mode = True
            elif att_mode:
                cand = t.lstrip("・.-　 ").strip()
                if cand and "（記載なし）" not in cand:
                    header["attendees"].append(cand)

    return {
        "header": header,
        "items": _to_list(_find("検討した項目", "検討項目")),
        "discussion": _find("検討内容") or "（記載なし）",
        "conclusions": _to_list(_find("結論", "決定事項")),
        "issues": _find("残された課題", "次回") or "（記載なし）",
    }


@app.route("/api/meeting/summarize", methods=["POST"])
@login_required
def api_meeting_summarize():
    """文字起こし→担当者会議の議事録を生成(Gemini)。"""
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        from utils import get_generative_model
        data = request.get_json(silent=True) or {}
        transcript = (data.get("transcript") or "").strip()
        if not transcript:
            return jsonify({"status": "error", "message": "文字起こしテキストがありません"}), 400
        prompt = f"""あなたは介護支援専門員(ケアマネジャー)です。以下は担当者会議(サービス担当者会議)の文字起こしです。
これを、厚生労働省の標準様式「第4表 サービス担当者会議の要点」に準拠した正式な議事録に整えてください。
末尾には、後からICF(国際生活機能分類)で分類するための「本人の状態整理」を付けます。

【最重要ルール】
・これは正式な書類です。文字起こしに書かれていない情報を創作・推測で埋めてはいけません。
・出席者の氏名・所属、開催場所、開催日時など、文字起こしから読み取れない項目は「（記載なし）」と書く。勝手に埋めない。
・議事録の基本は「誰が・何を・どのように決めたか」を明確に残すこと。逐語ではなく要点を整理する。
・専門用語に置き換えず、会議で語られた具体的な様子(例:「杖で20m歩ける」)をそのまま残す。

【出力する構成(この見出しで出力する)】
■ 開催情報
　開催日 / 開催場所 / 出席者(所属・職種と氏名。本人・家族の出席有無も) / 欠席者と理由。読み取れない項目は（記載なし）。
■ 検討した項目
　この会議で検討した議題を箇条書き。
■ 検討内容
　各項目についてどう話し合われたか。サービス内容だけでなく、提供方法・留意点・頻度・担当者などが語られていれば具体的に。誰の発言かが分かる場合は職種を添える。
■ 結論(決定事項)
　会議で決まったこと。誰が何をいつまでにするか。方針。
■ 残された課題・次回に向けて
　解決していない課題(未充足ニーズ)、次回開催時期や次回検討事項。語られていなければ（記載なし）。

■ 本人の状態整理(ICF分類用)
　本人の状態を以下の区分で箇条書き整理(会議で語られた事実のみ):
　・心身機能(痛み・可動域・認知・気分・睡眠など)
　・身体構造(部位の状態)
　・活動と参加(歩行・移動・入浴・更衣・食事・排泄・レク参加など、できること/介助が必要なこと)
　・環境因子(家族の支援・住環境・福祉用具・サービスなど)

出力は議事録本文のみ。前置き・説明は不要。

【文字起こし】
{transcript[:8000]}"""  # meetings-summarize-form4-v1
        model = get_generative_model()  # meetings-minutes-struct-parse-v1
        resp = model.generate_content(prompt)
        minutes = (resp.text or "").strip()
        if not minutes:
            return jsonify({"status": "error", "message": "議事録を生成できませんでした。"})
        struct = _mtg_parse_minutes_struct(minutes)  # meetings-minutes-struct-parse-v1
        return jsonify({"status": "success", "minutes": minutes, "minutes_struct": struct})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# --- /meetings-transcribe-summarize-v1 ---


# --- meetings-page-route-v1 : 担当者会議 画面(管理者MENU) ---
@app.route("/admin/meetings")
@login_required
def admin_meetings():
    """担当者会議 ICF分類 画面。meetings_enabled の施設のみ。"""
    if not session.get("admin_authenticated", False):
        return redirect(url_for("dev_login"))
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return redirect(url_for("admin"))
    return render("admin_meetings.html")
# --- /meetings-page-route-v1 ---


# --- meetings-save-list-get-v1 : 会議の一括保存 / 一覧 / 読み込み ---
import re as _re_uuid_mod
_UUID_RE = _re_uuid_mod.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@app.route("/api/meeting/save", methods=["POST"])
@login_required
def api_meeting_save():
    """会議1件 + 付箋(meeting_icf_links)を一括保存(案X)。"""
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        supabase = get_supabase()
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip() or "担当者会議"
        meeting_date = (data.get("meeting_date") or "").strip() or None
        patient_id = (data.get("patient_id") or "").strip()
        patient_id = patient_id if _UUID_RE.match(patient_id) else None
        transcript = data.get("transcript") or ""
        minutes = data.get("minutes") or ""
        audio_session_id = (data.get("audio_session_id") or "").strip() or None
        stickies = data.get("stickies") or []
        if not isinstance(stickies, list):
            return jsonify({"status": "error", "message": "stickies の形式が不正です"}), 400

        # 会議レコードをinsert
        _assessment = data.get("assessment")  # meetings-assessment-wire-v1
        if _assessment is not None and not isinstance(_assessment, str):
            import json as _json_a
            _assessment = _json_a.dumps(_assessment, ensure_ascii=False)
        _minutes_struct = data.get("minutes_struct")  # meetings-minutes-struct-save-v1
        if _minutes_struct is not None and not isinstance(_minutes_struct, str):
            import json as _json_ms
            _minutes_struct = _json_ms.dumps(_minutes_struct, ensure_ascii=False)
        m_row = {
            "facility_code": f_code,
            "patient_id": patient_id,
            "title": title,
            "meeting_date": meeting_date,
            "transcript": transcript,
            "minutes": minutes,
            "minutes_struct": _minutes_struct,
            "assessment": _assessment,
            "audio_session_id": audio_session_id,
            "status": "confirmed",
            "created_by": my_name,
        }
        m_res = supabase.table("meetings").insert(m_row).execute()
        if not (m_res.data and m_res.data[0].get("id")):
            return jsonify({"status": "error", "message": "会議の保存に失敗しました"}), 500
        meeting_id = m_res.data[0]["id"]

        # 付箋を一括insert。icf_codeがマスタに無いものはコードnull(手動メモ付箋)として保存。
        _valid = set()
        try:
            _mc = supabase.table("icf_codes").select("code").eq("level", 2).execute()
            _valid = {r["code"] for r in (_mc.data or [])}
        except Exception:
            _valid = set()

        saved = 0
        for s in stickies:
            if not isinstance(s, dict):
                continue
            code = (str(s.get("icf_code") or "").strip()) or None
            if code and code not in _valid:
                # マスタ外コードは握りつぶさず、コードnull + noteに退避(データ健全性優先)
                _n = s.get("note") or ""
                s = dict(s); s["note"] = (f"[未確定:{code}] " + _n).strip()
                code = None
            alt = (str(s.get("alt_icf_code") or "").strip()) or None
            if alt and alt not in _valid:
                alt = None
            link = {
                "meeting_id": meeting_id,
                "icf_code": code,
                "source_text": s.get("source_text") or None,
                "note": s.get("note") or None,
                "confidence": s.get("confidence") or "auto",
                "confirmed": bool(s.get("confirmed", False)),
                "board_component": (str(s.get("board_component") or "").strip() or None),
                "board_slot": (str(s.get("board_slot") or "").strip() or None),  # meetings-board-slot-api-v1
                "sort_order": int(s.get("sort_order") or 0),
                "alt_icf_code": alt,
                "alt_reason": s.get("alt_reason") or None,
            }
            supabase.table("meeting_icf_links").insert(link).execute()
            saved += 1

        return jsonify({"status": "success", "meeting_id": meeting_id, "saved_stickies": saved})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/meeting/list", methods=["GET"])
@login_required
def api_meeting_list():
    """施設の会議一覧(新しい順)。"""
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        supabase = get_supabase()
        r = supabase.table("meetings")\
            .select("id,title,meeting_date,patient_id,status,created_at")\
            .eq("facility_code", f_code)\
            .order("meeting_date", desc=True)\
            .order("created_at", desc=True)\
            .limit(200).execute()
        return jsonify({"status": "success", "meetings": r.data or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/meeting/get", methods=["GET"])
@login_required
def api_meeting_get():
    """会議1件 + 付箋を読み込み(ボード復元)。他施設IDは弾く。"""
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        supabase = get_supabase()
        meeting_id = (request.args.get("meeting_id") or "").strip()
        if not _UUID_RE.match(meeting_id):
            return jsonify({"status": "error", "message": "meeting_id が不正です"}), 400
        mr = supabase.table("meetings").select("*")\
            .eq("id", meeting_id).eq("facility_code", f_code).execute()
        if not mr.data:
            return jsonify({"status": "error", "message": "会議が見つかりません"}), 404
        meeting = mr.data[0]
        lr = supabase.table("meeting_icf_links").select("*")\
            .eq("meeting_id", meeting_id)\
            .order("board_slot").order("sort_order").execute()  # meetings-board-slot-api-v1
        return jsonify({"status": "success", "meeting": meeting, "stickies": lr.data or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# --- /meetings-save-list-get-v1 ---


# --- meetings-icf-master-v1 : ICF第2レベル全件(手動追加のコード選択用) ---
@app.route("/api/meeting/icf_master", methods=["GET"])
@login_required
def api_meeting_icf_master():
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        supabase = get_supabase()
        r = supabase.table("icf_codes").select("code,title_ja,component,chapter")\
            .eq("level", 2).order("sort_order").execute()
        return jsonify({"status": "success", "codes": r.data or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# --- /meetings-icf-master-v1 ---


# --- meetings-assessment-api-v1 : 議事録+文字起こし→課題分析23項目アセスメント ---
@app.route("/api/meeting/assessment", methods=["POST"])
@login_required
def api_meeting_assessment():
    """課題分析標準項目23項目のアセスメントをJSON配列で生成(Gemini)。
    ハルシネーション厳禁。語られていない項目は recorded:false / body:「（未記載）」。"""
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        from utils import get_generative_model
        import re as _re, json as _json
        data = request.get_json(silent=True) or {}
        minutes = (data.get("minutes") or "").strip()
        transcript = (data.get("transcript") or "").strip()
        if not minutes and not transcript:
            return jsonify({"status": "error", "message": "議事録または文字起こしがありません"}), 400

        # 23項目の見出し(表示順は現場が読みやすい順)
        items = [
            "基本情報（氏名・生年月日・住所・連絡先・家族構成等）",
            "これまでの生活と現在の状況（生活歴・職歴・趣味・価値観等）",
            "社会保障制度の利用状況（介護保険・医療保険・年金・障害等）",
            "現在利用している支援や社会資源（フォーマル/インフォーマル）",
            "日常生活自立度（障害・認知症）",
            "主訴・意向（本人・家族等の要望）",
            "認定情報（要介護度・審査会意見・区分支給限度額等）",
            "今回のアセスメントの理由（初回・更新・区分変更・状態変化等）",
            "健康状態（既往・服薬・主治医意見・身長体重BMI血圧等）",
            "ADL（寝返り・起き上がり・移乗・歩行・着衣・入浴・排泄等）",
            "IADL（調理・掃除・買物・金銭管理・服薬管理・交通機関利用等）",
            "認知機能や判断能力",
            "コミュニケーション（視覚・聴覚・言語等の理解と表出）",
            "生活リズム（1日/1週間・睡眠・活動と休息）",
            "排泄の状況",
            "じょくそう・皮膚の問題",
            "口腔内の状況（歯・義歯・咀嚼・嚥下・口腔衛生）",
            "食事摂取の状況（栄養・水分・食形態・摂取方法等）",
            "社会との関わり（社会活動への参加・役割・孤独感等）",
            "家族等の状況（介護者の有無・介護力・負担感・支援参加意思等）",
            "居住環境（住宅改修の必要性・危険箇所・生活動線等）",
            "その他留意すべき事項（虐待・経済的困窮・医療依存度・看取り等）",
            "特記事項・まとめ",
        ]
        items_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(items)])

        prompt = f"""あなたは介護支援専門員です。以下の担当者会議の【議事録】と【文字起こし】から、
介護の課題分析標準項目に沿ったアセスメントシートを作成してください。

【絶対厳守のルール(最重要)】
・議事録と文字起こしに実際に書かれている・語られている事実だけを記載する。
・推測・一般論・創作は一切禁止。情報が無い項目は、必ず body を「（未記載）」とし recorded を false にする。
・「たぶん」「思われる」で埋めてはいけない。語られていなければ未記載。これは正式書類であり、事実でない記載は重大な誤りになる。
・曖昧語(しっかり・適宜・時々)を避け、語られた具体的事実(数量・頻度・条件・介助度)をそのまま書く。
・ADLは語られた介助度(自立/見守り/一部介助/全介助 等)を残す。

【出力する項目(この23項目すべてを必ず出力)】
{items_text}

【出力形式】
JSON配列のみ。前置き・説明・マークダウンの```は一切禁止。
各要素: {{"id": 連番, "heading": "項目名", "body": "内容 または （未記載）", "recorded": true/false}}
recorded は body に実際の情報がある場合 true、「（未記載）」の場合 false。

【議事録】
{minutes[:6000]}

【文字起こし】
{transcript[:6000]}"""

        model = get_generative_model()
        resp = model.generate_content(prompt)
        raw = (resp.text or "").strip()
        raw = _re.sub(r"^```[a-zA-Z]*\n?", "", raw).strip()
        raw = _re.sub(r"```$", "", raw).strip()
        m = _re.search(r"\[.*\]", raw, _re.DOTALL)
        if not m:
            return jsonify({"status": "error", "message": "アセスメントを生成できませんでした"}), 500
        parsed = _json.loads(m.group())
        # 正規化(id採番・型担保)
        out = []
        for i, it in enumerate(parsed):
            if not isinstance(it, dict):
                continue
            body = str(it.get("body") or "").strip() or "（未記載）"
            rec = bool(it.get("recorded", False)) and body != "（未記載）"
            out.append({
                "id": i + 1,
                "heading": str(it.get("heading") or "").strip(),
                "body": body,
                "recorded": rec,
            })
        return jsonify({"status": "success", "assessment": out})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# --- /meetings-assessment-api-v1 ---


# --- meetings-pdf-v1 : 会議3成果物のPDF出力(議事録/アセスメント/ICFボード) ---
def _mtg_pdf_esc(s):
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("\n", "<br>"))

_MTG_PDF_BASE_CSS = """
  * { box-sizing: border-box; }
  body { font-family: 'Noto Sans CJK JP','IPAexGothic',sans-serif; color:#222;
         padding: 14mm 12mm; font-size: 11pt; line-height: 1.6; }
  h1 { font-size: 15pt; text-align:center; margin: 0 0 4mm; }
  .sub { text-align:center; font-size: 10pt; color:#444; margin-bottom: 6mm; }
  .meta { width:100%; border-collapse:collapse; margin-bottom: 5mm; font-size: 10pt; }
  .meta td { padding: 2px 6px; }
  .sec { margin: 4mm 0 1mm; font-weight:bold; font-size: 11.5pt;
         border-left: 4px solid #2e7d32; padding-left: 6px; }
  .box { border:1px solid #cfd8cf; border-radius:4px; padding: 6px 8px; margin-bottom: 3mm;
         white-space: normal; }
  table.grid { width:100%; border-collapse:collapse; margin-bottom: 3mm; }
  table.grid td, table.grid th { border:1px solid #b9c7bb; padding:5px 7px; vertical-align:top; font-size:10pt; }
  table.grid th { background:#eef4ee; text-align:left; width: 34%; }
  .unrec { color:#999; }
  .foot { margin-top: 8mm; font-size: 9pt; color:#666; text-align:right; }
"""


def _mtg_pdf_extract_body(html):  # meetings-pdf-all-v1
    """完全HTMLから<body>...</body>の中身だけ取り出す。"""
    import re as _re_b
    m = _re_b.search(r"<body[^>]*>(.*)</body>", html, _re_b.DOTALL | _re_b.IGNORECASE)
    return m.group(1) if m else html


def _mtg_pdf_render(html_str):  # meetings-pdf-all-merge-v1
    """HTML文字列をPDFバイトに(pdfkit)。ICF等の@pageはHTML側CSSが効く。"""
    import pdfkit, shutil as _sh_p
    _opts = {"encoding": "UTF-8", "no-outline": None, "quiet": ""}
    _wk = _sh_p.which("wkhtmltopdf") or "/usr/local/bin/wkhtmltopdf"
    _cfg = pdfkit.configuration(wkhtmltopdf=_wk)
    return pdfkit.from_string(html_str, False, options=_opts, configuration=_cfg)


def _mtg_pdf_merge(pdf_bytes_list):  # meetings-pdf-all-merge-v1 / robust: meetings-pdf-merge-robust-v1
    """複数PDFバイト列を1つに結合。向き混在OK。
    pdfunite(poppler) → PyMuPDF(fitz) → 先頭のみ、の順にフォールバック。"""
    _blobs = [b for b in pdf_bytes_list if b]
    if not _blobs:
        return b""
    if len(_blobs) == 1:
        return _blobs[0]
    # 1) pdfunite(poppler-utils, 依存追加なし)
    import shutil as _sh_m
    if _sh_m.which("pdfunite"):
        import tempfile, os, subprocess
        _tmp = tempfile.mkdtemp()
        try:
            _ins = []
            for _i, _b in enumerate(_blobs):
                _p = os.path.join(_tmp, f"in_{_i}.pdf")
                with open(_p, "wb") as _f:
                    _f.write(_b)
                _ins.append(_p)
            _out = os.path.join(_tmp, "out.pdf")
            _r = subprocess.run(["pdfunite"] + _ins + [_out],
                                capture_output=True, timeout=30)
            if _r.returncode == 0 and os.path.exists(_out):
                with open(_out, "rb") as _f:
                    return _f.read()
        except Exception:
            pass
        finally:
            try:
                _sh_m.rmtree(_tmp, ignore_errors=True)
            except Exception:
                pass
    # 2) PyMuPDF(fitz)
    try:
        import fitz
        _out = fitz.open()
        for _b in _blobs:
            _src = fitz.open(stream=_b, filetype="pdf")
            _out.insert_pdf(_src)
            _src.close()
        _data = _out.tobytes()
        _out.close()
        return _data
    except Exception:
        pass
    # 3) 最終フォールバック: 先頭PDFのみ返す(結合不可環境)
    return _blobs[0]


def _mtg_pdf_html_minutes(meeting, style="a"):  # meetings-pdf-minutes-styles-v1
    import json as _json_m
    title = _mtg_pdf_esc(meeting.get("title") or "担当者会議")
    date = _mtg_pdf_esc(meeting.get("meeting_date") or "")
    # 構造化データ
    st = None
    raw = meeting.get("minutes_struct")
    if raw:
        try:
            st = _json_m.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            st = None
    # フォールバック: 構造化が無ければ従来の全文box
    if not st or not isinstance(st, dict):
        minutes = _mtg_pdf_esc(meeting.get("minutes") or "（議事録なし）")
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_MTG_PDF_BASE_CSS}</style></head><body>
        <h1>サービス担当者会議の要点</h1>
        <div class="sub">{title}　開催日: {date}</div>
        <div class="box">{minutes}</div>
        <div class="foot">TASUKARU にて作成</div>
        </body></html>"""

    header = st.get("header") or {}
    h_date = _mtg_pdf_esc(header.get("date") or "（記載なし）")
    h_place = _mtg_pdf_esc(header.get("place") or "（記載なし）")
    atts = header.get("attendees") or []  # meetings-pdf-attendees-fix-v1
    def _fmt_att(a):
        if isinstance(a, dict):
            role = (a.get("role") or "").strip()
            name = (a.get("name") or "").strip()
            if name and name not in ("（氏名なし）", "（記載なし）"):
                return (role + "（" + name + "）") if role else name
            return role or name or ""
        return str(a).strip()
    _att_list = [x for x in (_fmt_att(a) for a in atts) if x]
    h_att = _mtg_pdf_esc("、".join(_att_list) if _att_list else "（記載なし）")
    h_abs = _mtg_pdf_esc(header.get("absentees") or "（記載なし）")
    items = st.get("items") or []
    disc = _mtg_pdf_esc(st.get("discussion") or "（記載なし）")
    concl = st.get("conclusions") or []
    issues = _mtg_pdf_esc(st.get("issues") or "（記載なし）")
    care_level = _mtg_pdf_esc(meeting.get("care_level") or "")

    items_html = "".join(f"<li>{_mtg_pdf_esc(x)}</li>" for x in items) or "<li>（記載なし）</li>"
    concl_html = "".join(f"<li>{_mtg_pdf_esc(x)}</li>" for x in concl) or "<li>（記載なし）</li>"

    if style == "c":
        # 案C: 公的様式風の罫線
        css = _MTG_PDF_BASE_CSS + """
          .cwrap { border:2px solid #333; }
          .ctitle { text-align:center; font-size:14pt; font-weight:bold; padding:8px; border-bottom:1px solid #333; }
          table.ct { width:100%; border-collapse:collapse; }
          table.ct td { border:1px solid #333; padding:5px 8px; font-size:10pt; vertical-align:top; }
          table.ct td.lbl { background:#f0f0f0; font-weight:bold; width:20%; }
          table.ct ul { margin:0; padding-left:16px; }
        """
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>
        <div class="cwrap">
        <div class="ctitle">サービス担当者会議の要点</div>
        <table class="ct">
          <tr><td class="lbl">利用者名</td><td>{title}</td><td class="lbl">開催日</td><td>{h_date if h_date!='（記載なし）' else date}</td></tr>
          <tr><td class="lbl">開催場所</td><td>{h_place}</td><td class="lbl">欠席者</td><td>{h_abs}</td></tr>
          <tr><td class="lbl">出席者</td><td colspan="3">{h_att}</td></tr>
          <tr><td class="lbl">検討した項目</td><td colspan="3"><ul>{items_html}</ul></td></tr>
          <tr><td class="lbl">検討内容</td><td colspan="3">{disc}</td></tr>
          <tr><td class="lbl">結論(決定事項)</td><td colspan="3"><ul>{concl_html}</ul></td></tr>
          <tr><td class="lbl">残された課題</td><td colspan="3">{issues}</td></tr>
        </table>
        </div>
        <div class="foot">TASUKARU にて作成</div>
        </body></html>"""

    if style == "b":
        # 案B: 決定事項を番号強調(ビジネス)
        concl_num = "".join(
            f'<div class="bnum"><span class="bn">{i+1}</span><span>{_mtg_pdf_esc(x)}</span></div>'
            for i, x in enumerate(concl)
        ) or '<div class="bnum"><span>（記載なし）</span></div>'
        css = _MTG_PDF_BASE_CSS + """
          .bhead { display:flex; justify-content:space-between; border-bottom:1px solid #333; padding-bottom:6px; margin-bottom:10px; }
          .btitle { font-size:14pt; font-weight:bold; }
          .bmeta { font-size:9pt; color:#666; }
          table.bi { width:100%; font-size:10pt; margin-bottom:10px; }
          table.bi td.l { color:#666; width:18%; }
          .bbox { background:#f5f8f5; border-radius:5px; padding:8px 10px; margin-bottom:10px; }
          .bboxt { font-weight:bold; color:#1e5e26; margin-bottom:5px; }
          .bnum { display:flex; gap:7px; margin-bottom:4px; align-items:flex-start; }
          .bn { background:#2e7d32; color:#fff; border-radius:50%; width:16px; height:16px;
                display:inline-block; text-align:center; line-height:16px; font-size:9pt; flex-shrink:0; }
          .bsec { font-weight:bold; margin:8px 0 3px; }
          table.bi ul { margin:2px 0; padding-left:16px; }
        """
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>
        <div class="bhead"><div class="btitle">サービス担当者会議 議事録</div><div class="bmeta">作成: {date} ／ TASUKARU</div></div>
        <table class="bi">
          <tr><td class="l">利用者</td><td>{title}{('（'+care_level+'）') if care_level else ''}</td></tr>
          <tr><td class="l">開催場所</td><td>{h_place}</td></tr>
          <tr><td class="l">出席者</td><td>{h_att}</td></tr>
        </table>
        <div class="bbox"><div class="bboxt">◆ 決定事項</div>{concl_num}</div>
        <div class="bsec">検討した項目</div><ul>{items_html}</ul>
        <div class="bsec">検討内容</div><div>{disc}</div>
        <div class="bsec">残された課題・次回に向けて</div><div>{issues}</div>
        <div class="foot">TASUKARU にて作成</div>
        </body></html>"""

    # 案A(既定): ヘッダー表＋見出し区切り(バランス)
    css = _MTG_PDF_BASE_CSS + """
      .atitle { text-align:center; font-size:14pt; font-weight:bold; letter-spacing:1px;
                padding-bottom:8px; border-bottom:2px solid #2e7d32; margin-bottom:10px; }
      table.ah { width:100%; border-collapse:collapse; font-size:10pt; margin-bottom:12px; }
      table.ah td { border:1px solid #cdd6cf; padding:5px 8px; vertical-align:top; }
      table.ah td.lbl { background:#f1f6f1; font-weight:bold; color:#2e5e33; width:20%; }
      .asec { font-weight:bold; color:#2e5e33; border-left:4px solid #2e7d32; padding-left:8px; margin:12px 0 4px; }
      .asec + ul, .asec + div { padding-left:10px; margin-top:2px; }
      ul { margin:2px 0; padding-left:20px; }
    """
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>
    <div class="atitle">サービス担当者会議 議事録</div>
    <table class="ah">
      <tr><td class="lbl">利用者名</td><td>{title}</td><td class="lbl">開催日</td><td>{h_date if h_date!='（記載なし）' else date}</td></tr>
      <tr><td class="lbl">開催場所</td><td>{h_place}</td><td class="lbl">欠席者</td><td>{h_abs}</td></tr>
      <tr><td class="lbl">出席者</td><td colspan="3">{h_att}</td></tr>
    </table>
    <div class="asec">1. 検討した項目</div><ul>{items_html}</ul>
    <div class="asec">2. 検討内容</div><div>{disc}</div>
    <div class="asec">3. 結論(決定事項)</div><ul>{concl_html}</ul>
    <div class="asec">4. 残された課題・次回に向けて</div><div>{issues}</div>
    <div class="foot">TASUKARU にて作成</div>
    </body></html>"""


def _mtg_pdf_html_assessment(meeting):
    import json as _json_p
    title = _mtg_pdf_esc(meeting.get("title") or "担当者会議")
    date = _mtg_pdf_esc(meeting.get("meeting_date") or "")
    items = []
    raw = meeting.get("assessment")
    if raw:
        try:
            items = _json_p.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            items = []
    rows = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        head = _mtg_pdf_esc(it.get("heading") or "")
        body = it.get("body") or "（未記載）"
        cls = ' class="unrec"' if (not it.get("recorded")) or body == "（未記載）" else ""
        rows.append(f'<tr><th>{head}</th><td{cls}>{_mtg_pdf_esc(body)}</td></tr>')
    body_html = "".join(rows) or '<tr><td colspan="2">（アセスメント項目なし）</td></tr>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_MTG_PDF_BASE_CSS}</style></head><body>
    <h1>アセスメントシート（課題分析標準項目）</h1>
    <div class="sub">{title}　作成日: {date}</div>
    <table class="grid">{body_html}</table>
    <div class="foot">TASUKARU にて作成／未記載項目は職員が確認・補完してください</div>
    </body></html>"""


def _mtg_pdf_html_icf(meeting, stickies, name_map=None):  # meetings-pdf-rich-icf-v1
    nm = name_map or {}
    SLOT_STYLE = {
        "health": ("#F1EFE8", "#2C2C2A", "#5F5E5A"),
        "bs": ("#EEEDFE", "#26215C", "#3C3489"),
        "activity": ("#FAECE7", "#4A1B0C", "#993C1D"),
        "participation": ("#FBEAF0", "#4B1528", "#72243E"),
        "environment": ("#E6F1FB", "#042C53", "#185FA5"),
        "personal": ("#E1F5EE", "#04342C", "#0F6E56"),
    }
    title = _mtg_pdf_esc(meeting.get("title") or "担当者会議")
    date = _mtg_pdf_esc(meeting.get("meeting_date") or "")

    _total = len([s for s in stickies if (s.get("board_slot") or "")])  # meetings-pdf-icf-fit-v1
    if _total <= 12:
        _dz = {"chip_fs": "9pt", "src_fs": "7.5pt", "pad": "4px 7px", "mb": "4px", "zt": "10pt", "srclen": 60}
    elif _total <= 20:
        _dz = {"chip_fs": "8pt", "src_fs": "6.8pt", "pad": "3px 6px", "mb": "3px", "zt": "9.5pt", "srclen": 44}
    elif _total <= 30:
        _dz = {"chip_fs": "7pt", "src_fs": "6pt", "pad": "2px 5px", "mb": "2px", "zt": "9pt", "srclen": 32}
    else:
        _dz = {"chip_fs": "6.2pt", "src_fs": "5.4pt", "pad": "2px 4px", "mb": "2px", "zt": "8.5pt", "srclen": 24}
    def chips(slot_key):
        lst = [s for s in stickies if (s.get("board_slot") or "") == slot_key]
        inner = []
        for s in lst:
            code = s.get("icf_code") or ""
            note = _mtg_pdf_esc(s.get("note") or "")
            if code:
                nm_ja = _mtg_pdf_esc(nm.get(code, ""))
                label = '<span class="cc">' + _mtg_pdf_esc(code) + '</span> ' + nm_ja
            else:
                label = note or "メモ"
            _bg = SLOT_STYLE.get(slot_key, ("#f4f7f4", "#333", "#2e7d32"))
            _src = s.get("source_text") or ""
            _srct = _src[:_dz["srclen"]] + ("…" if len(_src) > _dz["srclen"] else "")  # meetings-pdf-icf-fit-v1
            _src_html = ('<div class="csrc">' + _mtg_pdf_esc(_srct) + '</div>') if _src else ""
            inner.append(f'<div class="chip" style="background:{_bg[0]};color:{_bg[1]};">{label}{_src_html}</div>')
        return "".join(inner) or '<div class="empty">（言及なし）</div>'

    def zone(slot_key, slot_name, colspan=1):
        cs = f' colspan="{colspan}"' if colspan > 1 else ""
        _z = SLOT_STYLE.get(slot_key, ("#f4f7f4", "#333", "#2e7d32"))
        return f'<td class="zone"{cs}><div class="zt" style="color:{_z[2]};">{slot_name}</div>{chips(slot_key)}</td>'

    top = "<tr>" + zone("health", "健康状態", 3) + "</tr>"
    mid = "<tr>" + zone("bs", "心身機能・身体構造") + zone("activity", "活動") + zone("participation", "参加") + "</tr>"
    bot = "<tr>" + zone("environment", "環境因子") + zone("personal", "個人因子", 2) + "</tr>"

    css = _MTG_PDF_BASE_CSS + f"""
      @page {{ size: A4 landscape; margin: 8mm; }}
      table.icf {{ width:100%; border-collapse:collapse; margin-top:2mm; table-layout:fixed; }}
      table.icf td.zone {{ border:1.2px solid #9fb3a2; padding:4px; vertical-align:top; width:33.33%;
                           background:#fbfdfb; word-break:break-word; overflow-wrap:anywhere; }}
      .zt {{ font-weight:bold; font-size:{_dz['zt']}; margin-bottom:3px; padding-bottom:2px; border-bottom:1px solid #dbe6dd; }}
      .chip {{ border-radius:5px; padding:{_dz['pad']}; margin-bottom:{_dz['mb']}; font-size:{_dz['chip_fs']};
               line-height:1.3; word-break:break-word; overflow-wrap:anywhere; }}
      .chip .cc {{ font-weight:bold; }}
      .chip .csrc {{ font-size:{_dz['src_fs']}; opacity:0.72; margin-top:1px; }}
      .empty {{ color:#aaa; font-size:8pt; font-style:italic; }}
      .arrow {{ text-align:center; color:#7aa17e; font-size:11pt; padding:0.5mm 0; font-weight:bold; }}
      h1 {{ font-size:14pt; margin:0 0 1mm; }}
      .sub {{ font-size:9pt; margin-bottom:1mm; }}
    """
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>
    <h1>ICF 生活機能モデル図</h1>
    <div class="sub">{title}　{date}</div>
    <table class="icf">{top}</table>
    <div class="arrow">↕</div>
    <table class="icf">{mid}</table>
    <div class="arrow">↕</div>
    <table class="icf">{bot}</table>
    <div class="foot">TASUKARU にて作成／↕は各要素の相互作用（ICF生活機能モデル）</div>
    </body></html>"""


@app.route("/api/meeting/pdf", methods=["GET"])
@login_required
def api_meeting_pdf():
    ok, f_code, my_name = _meetings_gate_ok()
    if not ok:
        return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    try:
        import re as _re_p
        supabase = get_supabase()
        meeting_id = (request.args.get("meeting_id") or "").strip()
        ptype = (request.args.get("type") or "minutes").strip()
        if not _re_p.match(r"^[0-9a-fA-F-]{36}$", meeting_id):
            return jsonify({"status": "error", "message": "meeting_id が不正です"}), 400
        mr = supabase.table("meetings").select("*")\
            .eq("id", meeting_id).eq("facility_code", f_code).execute()
        if not mr.data:
            return jsonify({"status": "error", "message": "会議が見つかりません"}), 404
        meeting = mr.data[0]

        _combined_pdf = None  # meetings-pdf-all-merge-v1
        if ptype == "all":
            _style = (request.args.get("style") or "a").strip().lower()
            if _style not in ("a", "b", "c"):
                _style = "a"
            _lr = supabase.table("meeting_icf_links").select("*").eq("meeting_id", meeting_id).execute()
            _mm = supabase.table("icf_codes").select("code,title_ja").eq("level", 2).execute()
            _name_map = {r["code"]: r["title_ja"] for r in (_mm.data or [])}
            # 縦: 議事録 + アセスメント(page-break区切り)
            _h_min = _mtg_pdf_extract_body(_mtg_pdf_html_minutes(meeting, _style))
            _h_asm = _mtg_pdf_extract_body(_mtg_pdf_html_assessment(meeting))
            _pb = '<div style="page-break-before:always;"></div>'
            _portrait_html = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                              '<style>' + _MTG_PDF_BASE_CSS + '</style></head><body>'
                              + _h_min + _pb + _h_asm + '</body></html>')
            _portrait_pdf = _mtg_pdf_render(_portrait_html)
            # 横: ICF図(ビルダーが@page landscape/自動縮小を内包)
            _icf_html = _mtg_pdf_html_icf(meeting, _lr.data or [], _name_map)
            _icf_pdf = _mtg_pdf_render(_icf_html)
            # 結合(縦→横)
            _combined_pdf = _mtg_pdf_merge([_portrait_pdf, _icf_pdf])
            label = "担当者会議一式"
            html_str = ""
        elif ptype == "assessment":
            html_str = _mtg_pdf_html_assessment(meeting)
            label = "アセスメントシート"
        elif ptype == "icf":
            lr = supabase.table("meeting_icf_links").select("*").eq("meeting_id", meeting_id).execute()
            _mm = supabase.table("icf_codes").select("code,title_ja").eq("level", 2).execute()
            _name_map = {r["code"]: r["title_ja"] for r in (_mm.data or [])}
            html_str = _mtg_pdf_html_icf(meeting, lr.data or [], _name_map)
            label = "ICF分類"
        else:
            _style = (request.args.get("style") or "a").strip().lower()  # meetings-pdf-minutes-styles-v1
            if _style not in ("a", "b", "c"):
                _style = "a"
            html_str = _mtg_pdf_html_minutes(meeting, _style)
            label = "議事録"

        import pdfkit, shutil as _sh_p
        from urllib.parse import quote as _quote_p
        from flask import make_response  # meetings-pdf-makeresp-fix-v1
        options = {"encoding": "UTF-8", "no-outline": None, "quiet": ""}
        wk_path = _sh_p.which("wkhtmltopdf") or "/usr/local/bin/wkhtmltopdf"
        config = pdfkit.configuration(wkhtmltopdf=wk_path)
        if _combined_pdf is not None:  # meetings-pdf-all-merge-v1
            pdf_bytes = _combined_pdf
        else:
            pdf_bytes = pdfkit.from_string(html_str, False, options=options, configuration=config)
        fname = label + "_" + (meeting.get("meeting_date") or "") + ".pdf"
        fname_ascii = "meeting_" + ptype + ".pdf"
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"  # meetings-pdf-rich-icf-v1
        response.headers["Content-Disposition"] = 'attachment; filename="' + fname_ascii + "\"; filename*=UTF-8''" + _quote_p(fname)
        return response
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# --- /meetings-pdf-v1 ---


# --- meetings-icf-classify-v1 : 担当者会議 議事録→ICF分類 (PRO予定) ---
@app.route("/api/meeting/classify_icf", methods=["POST"])
def api_meeting_classify_icf():
    if "f_code" not in session:
        return jsonify({"status": "error", "message": "ログインが必要です"}), 401
    f_code = session["f_code"]
    my_name = session.get("my_name", "")
    supabase = get_supabase()
    # 設定ゲート: admin_settings の meetings_enabled=true の施設のみ。
    # (当面は自施設のみtrueにして実質限定運用。将来PROプランで解放)
    try:
        _g = supabase.table("admin_settings").select("value")\
            .eq("facility_code", f_code).eq("key", "meetings_enabled").execute()
        _enabled = False
        if _g.data:
            _v = _g.data[0].get("value")
            _enabled = (_v is True) or (str(_v).lower() in ("true", "1", '"true"'))
        if not _enabled:
            return jsonify({"status": "error", "message": "この機能は有効化されていません"}), 403
    except Exception:
        return jsonify({"status": "error", "message": "設定確認に失敗しました"}), 500

    try:
        import anthropic as _anthropic, json as _json, re as _re
        data = request.get_json(silent=True) or {}
        # meetings-assessment-wire-v1: minutes_text が無ければ source_text(アセスメント等)を使う
        minutes_text = (data.get("minutes_text") or data.get("source_text") or "").strip()
        if not minutes_text:
            return jsonify({"status": "error", "message": "分類する会議情報がありません"}), 400

        # ICFマスタ(第2レベル)を動的取得。マスタ更新に自動追従。
        _m = supabase.table("icf_codes").select("code,title_ja,component,chapter")\
            .eq("level", 2).order("sort_order").execute()
        master = _m.data or []
        if not master:
            return jsonify({"status": "error", "message": "ICFマスタが未投入です"}), 500
        master_list = "\n".join(
            [f"{r['code']} {r['title_ja']} (component={r['component']}, chapter={r['chapter']})"
             for r in master]
        )
        valid_codes = {r["code"] for r in master}

        prompt = f"""あなたは介護の担当者会議の会議情報(議事録またはアセスメント)をICF(国際生活機能分類)に分類する専門家です。
以下の【ICFマスタ】に載っているコードの中からのみ選んでください。
マスタに無いコードや、あなたの記憶にあるコードを創作してはいけません。
1つの発言が複数コードに該当する場合は複数返して構いません。
意味が近くて迷うコードがある場合は、次点候補(alt)を1つだけ添えてください。
該当が曖昧・確信が持てないものは confidence を "needs_review" にしてください。

出力は以下のJSON配列のみ。前置き・説明・マークダウンの```は一切禁止。
[
  {{
    "icf_code": "d450",
    "source_text": "議事録中の根拠となった箇所を短く引用",
    "confidence": "auto",
    "alt_icf_code": "d460",
    "alt_reason": "移動全般とも取れるため"
  }}
]
次点候補が無ければ alt_icf_code と alt_reason は null。
該当が1件も無ければ [] を返す。

【ICFマスタ】
{master_list}

【会議情報】
{minutes_text[:6000]}"""

        client = _anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        raw = _re.sub(r"^```[a-zA-Z]*\n?", "", raw).strip()
        raw = _re.sub(r"```$", "", raw).strip()
        parsed = _json.loads(raw)

        # マスタに無いコードは弾く(創作防止)。componentも付けて返す。
        code_to_comp = {r["code"]: r["component"] for r in master}
        code_to_title = {r["code"]: r["title_ja"] for r in master}
        results = []
        for s in parsed:
            c = str(s.get("icf_code") or "").strip()
            if c not in valid_codes:
                continue
            alt = str(s.get("alt_icf_code") or "").strip()
            if alt and alt not in valid_codes:
                alt = ""
            results.append({
                "icf_code": c,
                "title_ja": code_to_title.get(c, ""),
                "component": code_to_comp.get(c, ""),
                "source_text": s.get("source_text", ""),
                "confidence": s.get("confidence", "auto"),
                "alt_icf_code": alt or None,
                "alt_title_ja": code_to_title.get(alt, "") if alt else None,
                "alt_reason": (s.get("alt_reason") if alt else None),
            })
        # 保存はフロントの承認後(別API)で。ここでは候補を返すのみ(人が承認思想)。
        return jsonify({"status": "success", "count": len(results), "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# --- /meetings-icf-classify-v1 ---


@app.route("/admin/jisseki/print")
@login_required
def admin_jisseki_print():
    """jisseki-print-route-v1: 印刷最適化した実績集計ページ。"""
    supabase = get_supabase()
    f_code = session.get("f_code", "")
    facility_name = ""
    try:
        fr = supabase.table("facilities").select("facility_name").eq("facility_code", f_code).execute()
        if fr.data:
            facility_name = fr.data[0].get("facility_name") or ""
    except Exception as e:
        print("admin_jisseki_print facility_name error: %s" % e, flush=True)
    year = request.args.get("year", "")
    month = request.args.get("month", "")
    scope = request.args.get("scope", "both")
    return render_template("admin_jisseki_print.html",
                           facility_name=facility_name,
                           year=year, month=month, scope=scope)
