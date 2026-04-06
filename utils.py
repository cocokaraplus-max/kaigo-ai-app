import streamlit as st
import google.generativeai as genai
from supabase import create_client
import extra_streamlit_components as stx
import streamlit.components.v1 as components
from PIL import Image
import pytz
import uuid
import time

# タイムゾーン設定
tokyo_tz = pytz.timezone('Asia/Tokyo')

def init_config():
    """アプリの基本設定とスリープ防止"""
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    
    components.html("""
    <script>
    (function() {
        let wakeLock = null;
        async function requestWakeLock() { try { if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); } } catch (err) { } }
        function createNoSleepVideo() {
            const video = document.createElement('video'); video.setAttribute('loop', ''); video.setAttribute('playsinline', ''); video.style.display = 'none';
            video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
            return video;
        }
        const v = createNoSleepVideo();
        document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
        requestWakeLock();
        document.body.style.overscrollBehaviorY = 'contain'; 
    })();
    </script>
    """, height=0)

def apply_custom_style(primary_color="#ff4b4b"):
    """施設ごとのテーマカラーを反映"""
    st.markdown(f"""
        <style>
        .main-title {{ font-size: 24px; font-weight: bold; color: {primary_color}; border-bottom: 2px solid {primary_color}; margin-bottom: 20px; display: block; }}
        div.stButton > button {{ border-radius: 10px !important; }}
        .top-back-btn button {{ background-color: {primary_color} !important; color: white !important; width: 100% !important; font-weight: bold !important; }}
        code {{ white-space: pre-wrap !important; word-break: break-all !important; }}
        div[data-baseweb="calendar"] [aria-label*="Sunday"] {{ color: {primary_color} !important; font-weight: bold !important; }}
        div[data-baseweb="calendar"] [aria-label*="Saturday"] {{ color: #0000ff !important; font-weight: bold !important; }}
        </style>
        """, unsafe_allow_html=True)

@st.cache_resource
def init_clients():
    """DBとAIの初期接続"""
    try:
        s_url = st.secrets["SUPABASE_URL"]
        s_key = st.secrets["SUPABASE_KEY"]
        g_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=g_key)
        return create_client(s_url, s_key)
    except Exception as e:
        st.error(f"⚠️ 接続エラー: {e}")
        st.stop()

def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_v35")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    try:
        image = Image.open(logo_path)
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
    except:
        st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top", "edit_content": "", "monitoring_result": "", "editing_record_id": None})
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def get_facility_config(supabase, f_code):
    try:
        res = supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute()
        return res.data if res.data else {}
    except: return {}