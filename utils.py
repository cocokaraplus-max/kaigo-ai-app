import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client # type: ignore
import extra_streamlit_components as stx 
import streamlit.components.v1 as components
from PIL import Image # type: ignore
import pytz

tokyo_tz = pytz.timezone('Asia/Tokyo')

def init_config():
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    st.markdown("""
        <style>
        .main-title { font-size: clamp(18px, 5vw, 24px); font-weight: bold; color: #ff4b4b; border-bottom: 2px solid #ff4b4b; padding-bottom: 5px; margin-bottom: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
        div.stButton > button { border-radius: 10px !important; }
        .top-back-btn button { background-color: #ff4b4b !important; color: white !important; width: 100% !important; height: 60px !important; font-weight: bold !important; font-size: 18px !important; margin-top: 20px !important; border: none !important; box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important; }
        section[data-testid="stAudioInput"] { border: 2px solid #ff4b4b !important; border-radius: 20px !important; padding: 10px !important; background-color: #fff5f5 !important; }
        code { white-space: pre-wrap !important; word-break: break-all !important; }
        .stTextArea textarea { border: 2px solid #ff4b4b !important; border-radius: 10px !important; }
        .scrollable-history { max-height: 250px; overflow-y: auto; border: 2px solid #ff4b4b; border-radius: 10px; padding: 15px; background-color: #fffaf0; }
        div.stButton > button p, div.stButton > button div, div.stButton > button span { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; font-size: clamp(10px, 3vw, 14px) !important; }
        
        /* カレンダー色分け */
        div[data-baseweb="calendar"] [aria-label*="Sunday"] { color: #ff4b4b !important; font-weight: bold !important; }
        div[data-baseweb="calendar"] [aria-label*="Saturday"] { color: #0000ff !important; font-weight: bold !important; }
        div[data-baseweb="calendar"] [aria-label*="Monday"], div[data-baseweb="calendar"] [aria-label*="Tuesday"],
        div[data-baseweb="calendar"] [aria-label*="Wednesday"], div[data-baseweb="calendar"] [aria-label*="Thursday"],
        div[data-baseweb="calendar"] [aria-label*="Friday"] { color: #31333F !important; }
        </style>
        """, unsafe_allow_html=True)
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

@st.cache_resource
def init_clients():
    try:
        s_url, s_key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        g_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=g_key)
        return create_client(s_url, s_key)
    except Exception as e:
        st.error(f"⚠️ 接続エラー: {e}")
        st.stop()

def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_stable_v34")
    return st.session_state["cookie_manager"]

def display_logo(show_line=False):
    try:
        try: image = Image.open('logo.png')
        except: image = Image.open('logo.jpg')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top", "edit_content": "", "monitoring_result": "", "editing_record_id": None})
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)