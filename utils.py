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
    """
    アプリの基本設定と、ブラウザのスリープ防止・プルリロード抑制
    現場での「画面が勝手に消える」「指が滑ってリロードされる」ストレスをゼロにする。
    """
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    
    # 徹底したスリープ防止（WakeLock API + 無音動画ループ）
    # およびモバイルブラウザの「引っ張って更新」を物理的に無効化するJS
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
            // 最小サイズの無音MP4データ
            video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
            return video;
        }
        const v = createNoSleepVideo();
        // 最初のタップで動画再生とスリープ防止を起動
        document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
        requestWakeLock();
        // 下スワイプ（プルリロード）をCSSとJSで徹底ガード
        document.body.style.overscrollBehaviorY = 'contain'; 
        document.documentElement.style.overscrollBehaviorY = 'contain';
    })();
    </script>
    """, height=0)

def apply_custom_style(primary_color="#ff4b4b"):
    """
    施設ごとのテーマカラーをUI全体に浸透させる。
    カレンダーの土日色分け、ボタンの立体感、テキストエリアの視認性など。
    """
    st.markdown(f"""
        <style>
        /* メインタイトルの装飾 */
        .main-title {{ 
            font-size: 26px; 
            font-weight: 800; 
            color: {primary_color}; 
            border-bottom: 4px solid {primary_color}; 
            margin-bottom: 25px; 
            padding-bottom: 8px;
            display: block; 
        }}
        
        /* ボタン全体のモダンな角丸とアニメーション */
        div.stButton > button {{ 
            border-radius: 15px !important; 
            border: 1px solid #ddd !important;
            transition: transform 0.1s ease-in-out;
        }}
        div.stButton > button:active {{ transform: scale(0.96); }}
        
        /* TOPに戻るボタンの専用スタイル（固定色・存在感） */
        .top-back-btn button {{ 
            background-color: {primary_color} !important; 
            color: white !important; 
            width: 100% !important; 
            font-weight: bold !important; 
            height: 50px !important;
            font-size: 18px !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
        }}
        
        /* 現場用：入力エリアの文字を大きくし、入力を楽にする */
        .stTextArea textarea {{ font-size: 18px !important; line-height: 1.5 !important; }}
        
        /* AI生成コード等のコピーエリア設定 */
        code {{ 
            white-space: pre-wrap !important; 
            word-break: break-all !important; 
            background-color: #f8f9fb !important;
            color: #1a1c24 !important;
            border: 1px solid #e0e4e8 !important;
            padding: 10px !important;
            border-radius: 8px !important;
        }}

        /* カレンダーUIの土日色付け（重要） */
        div[data-baseweb="calendar"] [aria-label*="Sunday"] {{ color: {primary_color} !important; font-weight: bold !important; }}
        div[data-baseweb="calendar"] [aria-label*="Saturday"] {{ color: #0044ff !important; font-weight: bold !important; }}
        
        /* アコーディオンの視認性向上 */
        .stExpander {{ 
            border-radius: 12px !important; 
            border: 1px solid #e6e9ef !important; 
            background-color: white !important;
            margin-bottom: 12px !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
        }}
        </style>
        """, unsafe_allow_html=True)

@st.cache_resource
def init_clients():
    """データベース(Supabase)とAI(Gemini)の初期接続。エラー時はアプリを安全に止める。"""
    try:
        if "SUPABASE_URL" not in st.secrets:
            st.error("⚠️ Supabaseの設定がSecretsに登録されていません。")
            st.stop()
            
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.error(f"⚠️ 接続エラー: {e}")
        st.stop()

def get_cookie_manager():
    """端末IDを保持するためのクッキー管理。バージョンキーを更新して安定。"""
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_v37_prod_stable")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    """ロゴの表示。施設ごとのブランディングの第一歩。"""
    try:
        image = Image.open(logo_path)
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
        if show_line: st.divider()
    except:
        st.markdown("<h2 style='text-align: center; color: #222; font-weight: 900;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)
        if show_line: st.divider()

def back_to_top_button(key_suffix):
    """全画面共通の「TOPに戻る」ボタン。入力状態のクリアも兼ねる。"""
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
    """施設固有の設定情報を取得。"""
    try:
        res = supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute()
        return res.data if res.data else {}
    except:
        return {}