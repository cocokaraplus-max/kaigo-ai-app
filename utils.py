import streamlit as st
import google.generativeai as genai
from supabase import create_client
import extra_streamlit_components as stx
import streamlit.components.v1 as components
from PIL import Image
import pytz
import uuid
import time
import os

tokyo_tz = pytz.timezone('Asia/Tokyo')

def init_config():
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    components.html("""
    <script>
    (function() {
        let wakeLock = null;
        async function requestWakeLock() { try { if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); } } catch (err) { } }
        function createNoSleepVideo() {
            const video = document.createElement('video'); 
            video.setAttribute('loop', ''); video.setAttribute('playsinline', ''); video.style.display = 'none';
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
    st.markdown(f"""<style>
        .main-title {{ font-size: 18px; font-weight: 600; color: #333; background-color: #f8f9fa; padding: 10px 15px; border-left: 5px solid {primary_color}; border-radius: 4px; margin-bottom: 20px; display: flex; align-items: center; }}
        div.stButton > button {{ border-radius: 15px !important; transition: all 0.2s; }}
        .top-back-btn button {{ background-color: {primary_color} !important; color: white !important; width: 100% !important; font-weight: bold !important; height: 50px !important; }}
        </style>""", unsafe_allow_html=True)

def get_secret(secret_name):
    value = os.environ.get(secret_name)
    if value:
        return value.strip().strip('"').strip("'")
    try:
        if secret_name in st.secrets:
            return st.secrets[secret_name].strip().strip('"').strip("'")
    except:
        pass
    return None

@st.cache_resource
def init_clients():
    try:
        gemini_key = get_secret("GEMINI_API_KEY")
        supa_url = get_secret("SUPABASE_URL")
        supa_key = get_secret("SUPABASE_KEY")
        if gemini_key: genai.configure(api_key=gemini_key)
        if supa_url and supa_key: return create_client(supa_url, supa_key)
    except:
        pass
    return None

@st.cache_resource
def get_generative_model():
    return genai.GenerativeModel('gemini-1.5-flash')

def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_v53_prod_stable")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    try:
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(Image.open(logo_path), use_container_width=True)
        if show_line: st.divider()
    except: st.divider()

def back_to_top_button(key_suffix):
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top"})
        st.rerun()

def get_facility_config(supabase, f_code):
    try: return supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute().data
    except: return {}