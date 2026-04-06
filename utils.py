import streamlit as st
import google.generativeai as genai
from supabase import create_client
import extra_streamlit_components as stx
import streamlit.components.v1 as components
from PIL import Image
import pytz
import uuid
import time

# --- 1. タイムゾーン設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')

def init_config():
    """アプリの基本設定と、ブラウザのスリープ防止・プルリロード抑制。階層維持。"""
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    
    # 徹底したスリープ防止（WakeLock + 無音動画バイナリ）
    # およびモバイルブラウザの「引っ張って更新」を無効化する詳細JS
    components.html("""
    <script>
    (function() {
        let wakeLock = null;
        async function requestWakeLock() { 
            try { if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); } } catch (err) { } 
        }
        function createNoSleepVideo() {
            const video = document.createElement('video'); 
            video.setAttribute('loop', ''); 
            video.setAttribute('playsinline', ''); 
            video.style.display = 'none';
            // 完全なスリープ防止用無音動画バイナリ
            video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
            return video;
        }
        const v = createNoSleepVideo();
        document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
        requestWakeLock();
        // 下スワイプによる意図しないリロード（プルリフレッシュ）を完全ガード
        document.body.style.overscrollBehaviorY = 'contain'; 
        document.documentElement.style.overscrollBehaviorY = 'contain';
    })();
    </script>
    """, height=0)

def apply_custom_style(primary_color="#ff4b4b"):
    """施設カラーをボタンやカレンダーに浸透させる。階層維持。"""
    st.markdown(f"""
        <style>
        .main-title {{ 
            font-size: 26px; 
            font-weight: 800; 
            color: {primary_color}; 
            border-bottom: 4px solid {primary_color}; 
            margin-bottom: 25px; 
            padding-bottom: 8px;
            display: block; 
        }}
        div.stButton > button {{ 
            border-radius: 15px !important; 
            border: 1px solid #ddd !important;
            transition: all 0.2s ease-in-out;
        }}
        div.stButton > button:active {{ transform: scale(0.95); }}
        
        .top-back-btn button {{ 
            background-color: {primary_color} !important; 
            color: white !important; 
            width: 100% !important; 
            font-weight: bold !important; 
            height: 50px !important;
            font-size: 18px !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
        }}
        
        .stTextArea textarea {{ font-size: 18px !important; line-height: 1.5 !important; }}
        
        code {{ 
            white-space: pre-wrap !important; 
            word-break: break-all !important; 
            background-color: #f8f9fb !important;
            color: #1a1c24 !important;
            padding: 10px !important;
            border-radius: 8px !important;
            display: block;
        }}

        /* 土日色分けカレンダー */
        div[data-baseweb="calendar"] [aria-label*="Sunday"] {{ color: {primary_color} !important; font-weight: bold !important; }}
        div[data-baseweb="calendar"] [aria-label*="Saturday"] {{ color: #0044ff !important; font-weight: bold !important; }}
        
        .stExpander {{ 
            border-radius: 12px !important; 
            border: 1px solid #e6e9ef !important; 
            background-color: white !important;
            margin-bottom: 12px !important;
        }}
        </style>
        """, unsafe_allow_html=True)

@st.cache_resource
def init_clients():
    """データベースとAIへの厳格な接続初期化。"""
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.error(f"⚠️ 接続エラー: {e}")
        st.stop()

def get_cookie_manager():
    """クッキーマネージャー。バージョンを最新に固定。"""
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_v38_final_fixed")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    """ロゴ画像表示。階層維持。"""
    try:
        image = Image.open(logo_path)
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
        if show_line: st.divider()
    except:
        st.markdown("<h2 style='text-align: center; color: #222;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)
        if show_line: st.divider()

def back_to_top_button(key_suffix):
    """TOP戻りボタン。状態クリア。"""
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({
            "page": "top", 
            "edit_content": "", 
            "editing_record_id": None,
            "monitoring_result": ""
        })
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def get_facility_config(supabase, f_code):
    try:
        res = supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute()
        return res.data if res.data else {}
    except:
        return {}