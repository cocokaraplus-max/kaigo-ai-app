import streamlit as st
import uuid
import time
from utils import init_config, init_clients, get_cookie_manager, display_logo, apply_custom_style, get_facility_config, tokyo_tz
import views

# --- 1. システム初期化 ---
init_config()
supabase = init_clients()
cookie_manager = get_cookie_manager()

# セッション状態の維持
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False
if "input_key_id" not in st.session_state: st.session_state["input_key_id"] = str(uuid.uuid4())
if "dv_target_user" not in st.session_state: st.session_state["dv_target_user"] = None
if "dv_target_date" not in st.session_state: st.session_state["dv_target_date"] = None

# --- 2. 端末・セキュリティチェック ---
cookies = cookie_manager.get_all()
if not cookies: 
    time.sleep(0.5)
    st.rerun()

device_id = cookies.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="dev_v53_final")

if device_id:
    try:
        res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
        if res_block.data:
            st.error("🚫 この端末はアクセスが制限されています。")
            st.stop()
    except:
        pass

# --- 3. ログイン認証 ---
if not st.session_state.get("is_authenticated"):
    sf, sn = cookies.get("saved_f_code"), cookies.get("saved_my_name")
    if sf and sn:
        try:
            res_c = supabase.table("blocked_devices").select("*").eq("staff_name", sn).eq("facility_code", sf).eq("is_active", True).execute()
            if res_c.data:
                cookie_manager.delete("saved_f_code")
                cookie_manager.delete("saved_my_name")
                st.error(f"🚫 {sn} 様は制限中のため再ログインが必要です。")
            else:
                st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn})
                st.rerun()
        except:
            st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn}); st.rerun()
    
    apply_custom_style("#ff4b4b")
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                try:
                    res_n = supabase.table("blocked_devices").select("*").eq("staff_name", n_in).eq("facility_code", f_in).eq("is_active", True).execute()
                    if res_n.data: st.error("🚫 アクセス制限中です。"); st.stop()
                except: pass
                cookie_manager.set("saved_f_code", f_in)
                cookie_manager.set("saved_my_name", n_in)
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                time.sleep(0.5); st.rerun()
    st.stop()

# --- 4. 画面描画 ---
f_code, my_name = st.session_state["facility_code"], st.session_state["my_name"]
f_config = get_facility_config(supabase, f_code)
apply_custom_style(f_config.get("primary_color", "#ff4b4b"))

p = st.session_state["page"]
if p == "admin_menu":
    views.render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id)
else:
    pages = {"top": views.render_top, "input": views.render_input, "history": views.render_history, "daily_view": views.render_daily_view}
    pages[p](supabase, cookie_manager, f_code, my_name)