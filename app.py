import streamlit as st
import uuid
import time
from utils import init_config, init_clients, get_cookie_manager, display_logo
import views

# --- 1. 初期設定とデータベース接続 ---
init_config()
supabase = init_clients()
cookie_manager = get_cookie_manager()

# --- 2. セッションステート（記憶）の初期化 ---
if "input_key_id" not in st.session_state: st.session_state["input_key_id"] = str(uuid.uuid4())
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# --- 3. セキュリティとログイン認証 ---
cookies = cookie_manager.get_all()
if not cookies: time.sleep(0.5); st.rerun()

device_id = cookies.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="save_dev_v34")

if device_id:
    try:
        res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
        if res_block.data: st.error("🚫 この端末はアクセスが制限されています。"); st.stop()
    except: pass

if not st.session_state.get("is_authenticated"):
    sf, sn = cookies.get("saved_f_code"), cookies.get("saved_my_name")
    if sf and sn: 
        st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn})
        st.rerun()
    
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526", key="f_login")
        n_in = st.text_input("👤 あなたのお名前", key="n_login")
        if st.button("利用を開始する", use_container_width=True, key="btn_login"):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in, key="f_sv_v34")
                cookie_manager.set("saved_my_name", n_in, key="n_sv_v34")
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                time.sleep(0.5); st.rerun()
    st.stop()

f_code = st.session_state["facility_code"]
my_name = st.session_state["my_name"]

# --- 4. ルーティング (画面の切り替え) ---
if st.session_state["page"] == "top":
    views.render_top(supabase, cookie_manager, f_code, my_name)
elif st.session_state["page"] == "input":
    views.render_input(supabase, f_code, my_name)
elif st.session_state["page"] == "history":
    views.render_history(supabase, f_code, my_name)
elif st.session_state["page"] == "daily_view":
    views.render_daily_view(supabase, f_code, my_name)
elif st.session_state["page"] == "admin_menu":
    views.render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id)