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
st.components.v1.html("""
<script>
const saved = localStorage.getItem('tasukaru_token');
if (saved) {
    const url = new URL(window.parent.location.href);
    if (!url.searchParams.get('token')) {
        url.searchParams.set('token', saved);
        window.parent.location.replace(url.toString());
    }
}
</script>
""", height=0)
from supabase import create_client, Client
from views import render_top, render_input, render_history, render_daily_view, render_admin_menu
from utils import cookie_manager, display_logo, encode_login_token, decode_login_token, get_secret, save_session, load_session
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
    st.write(f"DEBUG: token={params['token'][:20]}...")
    f, n = load_session(supabase, params["token"])
    if f and n:
        cookie_manager["saved_f_code"] = f
        cookie_manager["saved_my_name"] = n
        st.session_state["page"] = "top"

def render_login():
    display_logo(show_line=False)
    st.markdown("<h3 style='text-align: center;'>施設コードを入力してください</h3>", unsafe_allow_html=True)
    saved_f = cookie_manager.get("saved_f_code") or ""
    saved_n = cookie_manager.get("saved_my_name") or ""
    f_code = st.text_input("施設コード", value=saved_f)
    my_name = st.text_input("あなたの名前", value=saved_n)
    if st.button("ログイン", use_container_width=True, type="primary"):
        if f_code and my_name:
            try:
                res = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
                blocked = any(b.get("device_id") == st.session_state.get("device_id") or b.get("staff_name") == my_name for b in res.data)
                if blocked:
                    st.error("この端末またはユーザーは利用できません。")
                else:
                    cookie_manager["saved_f_code"] = f_code
                    cookie_manager["saved_my_name"] = my_name
                    token = encode_login_token(f_code, my_name)
                    st.query_params["token"] = token
                    save_session(supabase, token, f_code, my_name)
                    st.components.v1.html(f"""<script>localStorage.setItem('tasukaru_token', '{token}');</script>""", height=0)
                    st.session_state["page"] = "top"
                    st.rerun()
            except Exception as e:
                st.error("ログイン中にエラーが発生しました。")
                st.caption(f"エラー詳細: {e}")
        else:
            st.warning("施設コードと名前を入力してください。")

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
    if st.button("管理者メニュー", key="admin_access_btn"):
        st.session_state["page"] = "admin"
        st.rerun()
