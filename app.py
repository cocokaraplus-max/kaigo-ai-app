import streamlit as st
import os
import uuid
import time
from supabase import create_client
from utils import init_config, init_clients, get_cookie_manager, display_logo, apply_custom_style, get_facility_config, tokyo_tz
import views

# --- 1. システム初期化 ---
init_config()

def get_secret(secret_name):
    # まずはOSの環境変数（Cloud Runの設定）を最優先で見る
    value = os.environ.get(secret_name)
    if value:
        return value.strip().strip('"').strip("'")
    # 次にStreamlitのsecretsを見る
    try:
        if secret_name in st.secrets:
            return st.secrets[secret_name].strip().strip('"').strip("'")
    except Exception:
        pass
    return None

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("🚨 設定が見つかりません！")
    st.stop()

# 🔑 鍵が正しく届いているか、サイドバーに「長さ」だけコッソリ出す
st.sidebar.write(f"DEBUG: Key Length = {len(SUPABASE_KEY)}")

try:
    _ = init_clients()
except Exception:
    pass

# 本物のクライアントを作成！
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 以下、通常のアプリ処理 ---
cookie_manager = get_cookie_manager()
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False
if "input_key_id" not in st.session_state: st.session_state["input_key_id"] = str(uuid.uuid4())
if "dv_target_user" not in st.session_state: st.session_state["dv_target_user"] = None
if "dv_target_date" not in st.session_state: st.session_state["dv_target_date"] = None

cookies = cookie_manager.get_all()
if not cookies: 
    time.sleep(0.5)
    st.rerun()

device_id = cookies.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="set_cookie_device_id")

# ログイン後のメイン処理へ...
f_code, my_name = st.session_state.get("facility_code", "cocokaraplus-5526"), st.session_state.get("my_name", "管理者")
try:
    # ここでエラーが出るなら、DB内の設定取得に問題がある
    f_config = get_facility_config(supabase, f_code)
    apply_custom_style(f_config.get("primary_color", "#ff4b4b"))
except:
    apply_custom_style("#ff4b4b")

# ... (以降、元の views.render 処理などを呼び出し)
p = st.session_state["page"]
if not st.session_state.get("is_authenticated"):
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
            st.rerun()
    st.stop()

if p == "admin_menu":
    views.render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id)
else:
    pages = {"top": views.render_top, "input": views.render_input, "history": views.render_history, "daily_view": views.render_daily_view}
    pages[p](supabase, cookie_manager, f_code, my_name)
