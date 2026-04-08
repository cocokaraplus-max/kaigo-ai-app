import streamlit as st
import os
import uuid
import time
from supabase import create_client
from utils import init_config, init_clients, get_cookie_manager, display_logo, apply_custom_style, get_facility_config, tokyo_tz
import views

# --- 1. システム初期化 ---
init_config()

# OSの環境変数から直接取得（最強の確実性）
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().strip('"').strip("'")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip().strip('"').strip("'")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("🚨 Cloud Runの環境変数が読み込めません。設定画面を確認してください。")
    st.stop()

# 🔑 接続診断（成功したら消してもいいが、今はコッソリ表示）
st.sidebar.write(f"📡 Status: Connected (Key length: {len(SUPABASE_KEY)})")

try:
    _ = init_clients()
except Exception:
    pass

# Supabaseクライアント作成
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. アプリケーション本体 ---
cookie_manager = get_cookie_manager()

if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

cookies = cookie_manager.get_all()
if not cookies: 
    time.sleep(0.5)
    st.rerun()

device_id = cookies.get("device_id") or str(uuid.uuid4())

# ログイン・認証処理
if not st.session_state.get("is_authenticated"):
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                st.rerun()
    st.stop()

# 施設コードに基づいた動的設定
f_code = st.session_state["facility_code"]
my_name = st.session_state["my_name"]

try:
    f_config = get_facility_config(supabase, f_code)
    apply_custom_style(f_config.get("primary_color", "#ff4b4b"))
except:
    apply_custom_style("#ff4b4b")

# 各ページの表示
p = st.session_state["page"]
if p == "admin_menu":
    views.render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id)
else:
    pages = {"top": views.render_top, "input": views.render_input, "history": views.render_history, "daily_view": views.render_daily_view}
    pages[p](supabase, cookie_manager, f_code, my_name)
