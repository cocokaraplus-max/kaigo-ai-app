import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime
import pytz 
from supabase import create_client, Client # type: ignore
import uuid
import time
from PIL import Image # type: ignore
import extra_streamlit_components as stx 
import unicodedata

# --- 1. 基本設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)
st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")

# Cookieマネージャー初期化
cookie_manager = stx.CookieManager()

def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except Exception: pass

load_css("style.css")

# 接続設定
try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    # 2026年の標準的な接続設定
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}"); st.stop()

def normalize_chart_no(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return ""
    return unicodedata.normalize('NFKC', str(s).split('.')[0]).strip()

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

# --- 2. 状態管理 ---
if "is_authenticated" not in st.session_state: st.session_state["is_authenticated"] = False
if "facility_code" not in st.session_state: st.session_state["facility_code"] = ""
if "my_name" not in st.session_state: st.session_state["my_name"] = ""
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""

# ==========================================
# 🔐 ログイン & Cookie同期
# ==========================================
cookie_manager.get_all()

if not st.session_state["is_authenticated"]:
    time.sleep(0.7) 
    saved_f = cookie_manager.get("saved_f_code")
    saved_n = cookie_manager.get("saved_my_name")
    
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n})
        st.rerun()

    display_logo()
    st.markdown("<h3 style='text-align: center;'>🔐 ログイン</h3>", unsafe_allow_html=True)
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526", key="login_f_final")
        n_in = st.text_input("👤 お名前", key="login_n_final")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in, key="set_f_final")
                cookie_manager.set("saved_my_name", n_in, key="set_n_final")
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                st.rerun()
    st.stop()

# 施設コード・名前の確保
f_code = st.session_state.get("facility_code")
my_name = st.session_state.get("my_name")

# ==========================================
# 🏠 画面遷移
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col2:
        if st.button("📊 履歴・モニタリング", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
        st.session_state.clear(); st.rerun()

elif st.session_state["page"] == "input":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("✍️ ケース記録入力")
    
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    if p_df.empty: st.warning("利用者を登録してください"); st.stop()
    sel = st.selectbox("👤 利用者を選択", ["---"] + [f"No.{r['chart_number']} : {r['user_name']}" for _, r in p_df.iterrows()])
    
    aud = st.audio_input("🎙️ 声で入力")
    if aud and st.button("✨ AIで文章にする", key="ai_btn_final"):
        with st.spinner("最新AI (Gemini 2.5) が解析中..."):
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(aud.getvalue())
                    tmp_path = tmp.name
                
                # 【確定した最新モデルを使用】
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                f_up = genai.upload_file(path=tmp_path)
                
                # ファイル準備待ち
                for _ in range(10):
                    f_up = genai.get_file(f_up.name)
                    if f_up.state.name == "ACTIVE": break
                    time.sleep(1)
                
                response = model.generate_content([f_up, "介護記録として整理してください。出力は日本語のみ。"])
                st.session_state["edit_content"] = response.text
                os.remove(tmp_path)
                st.rerun()
            except Exception as e:
                st.error(f"AI解析エラー: {e}")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=300)
    if st.button("💾 クラウド保存", use_container_width=True):
        if sel != "---" and content:
            u_name = sel.split(" : ")[1]; c_no = sel.split(" : ")[0].replace("No.", "")
            supabase.table("records").insert({
                "facility_code": f_code, "chart_number": str(c_no), "user_name": u_name,
                "staff_name": my_name, "content": content, "created_at": now_tokyo.isoformat()
            }).execute()
            st.success("保存完了！"); st.session_state["edit_content"] = ""; time.sleep(1); st.session_state["page"] = "top"; st.rerun()

elif st.session_state["page"] == "history":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo()
    res = supabase.table("records").select("*").eq("facility_code", f_code).order("created_at", desc=True).execute()
    if res.data:
        for r in res.data:
            with st.expander(f"📅 {r['created_at'][:10]} - {r['user_name']} (記: {r.get('staff_name','--')})"):
                st.write(r['content'])