import streamlit as st
from supabase import create_client, Client
import views
from utils import cookie_manager, display_logo
import os

st.set_page_config(page_title="TASUKARU", page_icon="🦝", layout="centered")

# データベース接続
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"データベース接続エラー: {e}")
    st.stop()

if "page" not in st.session_state:
    st.session_state["page"] = "top"
if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False

f_code = cookie_manager.get("saved_f_code")
my_name = cookie_manager.get("saved_my_name")

if not f_code or not my_name:
    display_logo(show_line=True)
    st.info("施設コードと名前を入力してログインしてください。")
    with st.form("login_form"):
        f_in = st.text_input("施設コード")
        n_in = st.text_input("名前")
        if st.form_submit_button("ログイン"):
            cookie_manager["saved_f_code"] = f_in
            cookie_manager["saved_my_name"] = n_in
            cookie_manager.save()
            st.rerun()
else:
    p = st.session_state["page"]
    try:
        if p == "admin_menu":
            views.render_admin_menu(supabase, cookie_manager, f_code, my_name, "WEB")
        elif p == "input":
            views.render_input(supabase, cookie_manager, f_code, my_name)
        elif p == "daily_view":
            views.render_daily_view(supabase, cookie_manager, f_code, my_name)
        elif p == "history":
            views.render_history(supabase, cookie_manager, f_code, my_name)
        else:
            views.render_top(supabase, cookie_manager, f_code, my_name)
    except Exception as e:
        st.error(f"画面の表示中にエラーが発生しました: {e}")
        if st.button("🏠 TOP画面へ戻る"):
            st.session_state["page"] = "top"
            st.rerun()