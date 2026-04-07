import streamlit as st
import os
import uuid
import time
import urllib.request
import urllib.error
from supabase import create_client
from utils import init_config, init_clients, get_cookie_manager, display_logo, apply_custom_style, get_facility_config, tokyo_tz
import views

# --- 1. システム初期化 ---
init_config()

# ▼▼▼ エジソン特製：環境変数対応 ＆ 記号完全除去の最強セキュリティ ▼▼▼
def get_secret(secret_name):
    value = os.environ.get(secret_name)
    if value:
        return value.strip().strip('"').strip("'")
    try:
        if secret_name in st.secrets:
            return st.secrets[secret_name].strip().strip('"').strip("'")
    except Exception:
        pass
    return None

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("🚨 SupabaseのURLまたは鍵が見つかりません！Cloud Runの環境変数設定を確認してください。")
    st.stop()

try:
    _ = init_clients()
except Exception:
    pass

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
# ▲▲▲ ここまでエジソンの魔法 ▲▲▲

# 🕵️‍♂️ 究極の生身通信テスト（エジソン用）
if st.sidebar.checkbox("🔧 究極の生身通信テスト（エジソン用）"):
    st.sidebar.write(f"URL設定済み: {'はい' if SUPABASE_URL else 'いいえ'}")
    st.sidebar.write(f"KEY設定済み: {'はい' if SUPABASE_KEY else 'いいえ'}")
    
    # 🔍 鍵の「健康診断」：見えないゴミが混じっていないか丸裸にする！
    if SUPABASE_KEY:
        st.sidebar.write(f"🔑 鍵の長さ: {len(SUPABASE_KEY)} 文字")
        st.sidebar.write(f"🟢 先頭5文字: {SUPABASE_KEY[:5]}")
        st.sidebar.write(f"🔴 末尾5文字: {SUPABASE_KEY[-5:]}")
        
    # 翻訳機を使わず、直接URLを組み立てる
    url = f"{SUPABASE_URL}/rest/v1/facility_settings?select=*"
    st.sidebar.write("🚀 送信先URL:", url)
    
    req = urllib.request.Request(url)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    
    try:
        # 直接、門番に鍵を突きつける！
        with urllib.request.urlopen(req) as response:
            st.sidebar.success(f"✅ 通信大成功！ステータス: {response.status}")
    except urllib.error.HTTPError as e:
        st.sidebar.error(f"❌ HTTPエラー: {e.code}")
        st.sidebar.write("エラー詳細:", e.read().decode("utf-8"))
    except Exception as e:
        st.sidebar.error(f"❌ 謎のエラー: {e}")

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

if device_id:
    try:
        res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
        if res_block.data:
            st.error("🚫 この端末はアクセスが制限されています。")
            st.stop()
    except:
        pass

def register_device_to_db(d_id, f_code, s_name):
    try:
        res = supabase.table("devices").select("id").eq("device_id", d_id).execute()
        if not res.data:
            supabase.table("devices").insert({"device_id": d_id, "facility_code": f_code, "device_name": s_name}).execute()
    except:
        pass

if not st.session_state.get("is_authenticated"):
    sf, sn = cookies.get("saved_f_code"), cookies.get("saved_my_name")
    if sf and sn:
        try:
            res_c = supabase.table("blocked_devices").select("*").eq("staff_name", sn).eq("facility_code", sf).eq("is_active", True).execute()
            if not res_c.data:
                st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn})
                register_device_to_db(device_id, sf, sn)
                st.rerun()
        except:
            st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn})
            register_device_to_db(device_id, sf, sn)
            st.rerun()
    
    apply_custom_style("#ff4b4b")
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                cookie_manager.set("saved_f_code", f_in, key="set_cookie_f_code")
                cookie_manager.set("saved_my_name", n_in, key="set_cookie_my_name")
                register_device_to_db(device_id, f_in, n_in)
                time.sleep(0.5); st.rerun()
    st.stop()

f_code, my_name = st.session_state["facility_code"], st.session_state["my_name"]
f_config = get_facility_config(supabase, f_code)
apply_custom_style(f_config.get("primary_color", "#ff4b4b"))

p = st.session_state["page"]
if p == "admin_menu":
    views.render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id)
else:
    pages = {"top": views.render_top, "input": views.render_input, "history": views.render_history, "daily_view": views.render_daily_view}
    pages[p](supabase, cookie_manager, f_code, my_name)
