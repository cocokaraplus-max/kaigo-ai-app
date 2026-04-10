import streamlit as st

st.set_page_config(page_title="TASUKARU", page_icon="🦝", layout="centered", initial_sidebar_state="collapsed")


import os

def load_css():
    css_path = os.path.join(os.path.dirname(__file__), 'style.css')
    if os.path.exists(css_path):
        with open(css_path) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_css()
st.markdown('<style>:root{color-scheme:light!important}</style>', unsafe_allow_html=True)
from supabase import create_client, Client
from views import render_top, render_input, render_history, render_daily_view, render_admin_menu, render_super_admin
from utils import cookie_manager, display_logo, encode_login_token, decode_login_token, get_secret, save_session, load_session, send_temp_password_email
import uuid

try:
    url = get_secret("SUPABASE_URL").strip()
    key = get_secret("SUPABASE_KEY").strip()
    if not url or not key:
        raise KeyError("SUPABASE_URL or SUPABASE_KEY not set")
    supabase = create_client(url, key)
except KeyError as e:
    st.error(f"設定が見つかりません: {e}")
    st.stop()
except Exception as e:
    st.error("データベースへの接続に失敗しました。")
    st.info(f"エラー詳細: {e}")
    st.stop()

if "page" not in st.session_state:
    st.session_state["page"] = "login"
if "device_id" not in st.session_state:
    st.session_state["device_id"] = str(uuid.uuid4())
for k in ["edit_content", "monitoring_result", "admin_authenticated"]:
    if k not in st.session_state:
        st.session_state[k] = "" if "content" in k else False

params = st.query_params
if "token" in params and st.session_state["page"] == "login":
    f, n = load_session(supabase, params["token"])
    if f and n:
        cookie_manager["saved_f_code"] = f
        cookie_manager["saved_my_name"] = n
        st.session_state["page"] = "top"

def render_register():
    import random, string
    display_logo(show_line=False)
    st.markdown("<h3 style='text-align:center'>施設新規登録</h3>", unsafe_allow_html=True)
    facility_code = st.text_input("施設コード（自分で決めてください）")
    facility_name = st.text_input("施設名")
    admin_email = st.text_input("管理者メールアドレス")
    if st.button("登録する", type="primary", use_container_width=True):
        if facility_code and facility_name and admin_email:
            try:
                existing = supabase.table("facilities").select("facility_code").eq("facility_code", facility_code).execute()
                if existing.data:
                    st.error("この施設コードはすでに使われています。別のコードを入力してください。")
                else:
                    temp_pw = "".join(random.choices(string.ascii_letters + string.digits, k=10))
                    supabase.table("facilities").insert({"facility_code": facility_code, "facility_name": facility_name, "admin_password": temp_pw, "plan_limit": 99999, "is_active": True}).execute()
                    send_temp_password_email(admin_email, facility_name, facility_code, temp_pw)
                    st.success("登録完了！メールをご確認ください。")
            except Exception as e:
                st.error(f"登録エラー: {e}")
        else:
            st.warning("全項目を入力してください。")
def render_login():
    display_logo(show_line=False)
    st.markdown("<h3 style='text-align: center;'>ログイン</h3>", unsafe_allow_html=True)
    saved_f = cookie_manager.get("saved_f_code") or ""
    f_code = st.text_input("施設コード", value=saved_f)
    password = st.text_input("パスワード", type="password")
    if st.button("ログイン", use_container_width=True, type="primary"):
        if f_code and password:
            try:
                fac = supabase.table("facilities").select("facility_name,is_active,expires_at,admin_password").eq("facility_code", f_code).execute()
                if not fac.data:
                    st.error("この施設コードは登録されていません。")
                    st.stop()
                from datetime import datetime, timezone
                fac_data = fac.data[0]
                if not fac_data.get("is_active", True):
                    st.error("この施設コードは無効です。")
                    st.stop()
                expires = datetime.fromisoformat(str(fac_data.get("expires_at","")).replace("Z","+00:00"))
                if expires < datetime.now(timezone.utc):
                    st.error("この施設コードの有効期限が切れています。")
                    st.stop()
                from utils import hash_password, verify_password
                admin_pw = fac_data.get("admin_password", "")
                staff = supabase.table("staffs").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
                matched_staff = None
                for s in staff.data:
                    if verify_password(password, s["password_hash"]):
                        matched_staff = s
                        break
                is_admin = (password == admin_pw)
                if not is_admin and not matched_staff:
                    st.error("パスワードが違います。")
                    st.stop()
                my_name = "管理者" if is_admin else matched_staff["staff_name"]
                cookie_manager["saved_f_code"] = f_code
                cookie_manager["saved_my_name"] = my_name
                token = encode_login_token(f_code, my_name)
                st.query_params["token"] = token
                save_session(supabase, token, f_code, my_name)
                st.session_state["page"] = "top"
                st.rerun()
            except Exception as e:
                if "StopException" in str(type(e).__name__):
                    raise
                raise
            except Exception as e:
                st.error("ログイン中にエラーが発生しました。")
                st.caption(f"エラー詳細: {e}")
        else:
            st.warning("施設コードとパスワードを入力してください。")
params_now = st.query_params
if "register" in params_now:
    render_register()
    st.stop()

f_code = cookie_manager.get("saved_f_code")
my_name = cookie_manager.get("saved_my_name")

if st.session_state["page"] == "login":
    render_login()
elif not f_code or not my_name:
    st.session_state["page"] = "login"
    st.rerun()
else:
    p = st.session_state["page"]
    if p == "top":
        render_top(supabase, cookie_manager, f_code, my_name)
    elif p == "input":
        render_input(supabase, cookie_manager, f_code, my_name)
    elif p == "history":
        render_history(supabase, cookie_manager, f_code, my_name)
    elif p == "daily_view":
        render_daily_view(supabase, cookie_manager, f_code, my_name)
    elif p == "admin":
        render_admin_menu(supabase, cookie_manager, f_code, my_name, st.session_state.get("device_id"))
    st.divider()
    params_now = st.query_params
    if "superadmin" in params_now:
        if not st.session_state.get("super_authenticated"):
            pw = st.text_input("開発者パスワード", type="password", key="super_pw")
            if st.button("認証", key="super_auth_btn"):
                if pw == get_secret("SUPER_ADMIN_PASSWORD"):
                    st.session_state["super_authenticated"] = True
                    st.rerun()
                else:
                    st.error("パスワードが違います。")
        else:
            render_super_admin(supabase)
    elif st.button("管理者MENU", key="admin_access_btn"):
        st.session_state["page"] = "admin"
        st.rerun()
