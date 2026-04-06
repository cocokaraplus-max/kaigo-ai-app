import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client # type: ignore
import extra_streamlit_components as stx 
import streamlit.components.v1 as components
from PIL import Image # type: ignore
import pytz
import uuid
import time

# タイムゾーン設定
tokyo_tz = pytz.timezone('Asia/Tokyo')

def init_config():
    """アプリの基本設定とスリープ防止スクリプト"""
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    
    # スリープ防止 & プルリロード抑制 JavaScript
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
    """
    施設ごとのテーマカラーを反映するCSS。
    市販化の際、施設ごとに色を変えられるように引数化。
    """
    st.markdown(f"""
        <style>
        /* メインタイトルと枠線 */
        .main-title {{ 
            font-size: clamp(18px, 5vw, 24px); 
            font-weight: bold; 
            color: {primary_color}; 
            border-bottom: 2px solid {primary_color}; 
            padding-bottom: 5px; 
            margin-bottom: 20px; 
            white-space: nowrap; 
            overflow: hidden; 
            text-overflow: ellipsis; 
            display: block; 
        }}
        
        /* ボタンのデザイン */
        div.stButton > button {{ 
            border-radius: 10px !important; 
        }}
        
        /* TOPに戻るボタンの強調 */
        .top-back-btn button {{ 
            background-color: {primary_color} !important; 
            color: white !important; 
            width: 100% !important; 
            height: 60px !important; 
            font-weight: bold !important; 
            font-size: 18px !important; 
            margin-top: 20px !important; 
            border: none !important; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important; 
        }}
        
        /* 音声入力枠 */
        section[data-testid="stAudioInput"] {{ 
            border: 2px solid {primary_color} !important; 
            border-radius: 20px !important; 
            padding: 10px !important; 
            background-color: #fffaf0 !important; 
        }}
        
        /* テキストエリア */
        .stTextArea textarea {{ 
            border: 2px solid {primary_color} !important; 
            border-radius: 10px !important; 
        }}
        
        /* 履歴スクロールエリア */
        .scrollable-history {{ 
            max-height: 250px; 
            overflow-y: auto; 
            border: 2px solid {primary_color}; 
            border-radius: 10px; 
            padding: 15px; 
            background-color: #fffaf0; 
        }}
        
        /* コードブロック（コピー用）の折り返し設定 */
        code {{ white-space: pre-wrap !important; word-break: break-all !important; }}

        /* カレンダーの曜日別色分け */
        div[data-baseweb="calendar"] [aria-label*="Sunday"] {{ color: {primary_color} !important; font-weight: bold !important; }}
        div[data-baseweb="calendar"] [aria-label*="Saturday"] {{ color: #0000ff !important; font-weight: bold !important; }}
        
        /* ボタン内テキストのレスポンシブ設定 */
        div.stButton > button p, div.stButton > button div, div.stButton > button span {{ 
            white-space: nowrap !important; 
            overflow: hidden !important; 
            text-overflow: ellipsis !important; 
            font-size: clamp(10px, 3vw, 14px) !important; 
        }}
        </style>
        """, unsafe_allow_html=True)

@st.cache_resource
def init_clients():
    """SupabaseとGeminiの初期接続（キャッシュして高速化）"""
    try:
        s_url, s_key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        g_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=g_key)
        return create_client(s_url, s_key)
    except Exception as e:
        st.error(f"⚠️ 接続エラー: {e}")
        st.stop()

def get_cookie_manager():
    """クッキーマネージャーの取得（セッション維持用）"""
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_stable_v34")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    """
    ロゴの表示。
    市販化を見据え、パスを変更可能に。画像がない場合はテキストロゴを表示。
    """
    try:
        image = Image.open(logo_path)
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
        if show_line:
            st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
    except Exception:
        st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

def back_to_top_button(key_suffix):
    """共通の「TOPに戻る」ボタン"""
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top", "edit_content": "", "monitoring_result": "", "editing_record_id": None})
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def get_facility_config(supabase, f_code):
    """
    施設ごとの個別設定をDBから取得する。
    （テーマカラー、カスタムロゴURL、施設正式名称など）
    """
    try:
        # ※Supabase側に facility_settings テーブルがある想定
        res = supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute()
        return res.data if res.data else {}
    except:
        return {}