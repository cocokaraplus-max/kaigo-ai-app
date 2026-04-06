import streamlit as st
import google.generativeai as genai
from supabase import create_client
import extra_streamlit_components as stx
import streamlit.components.v1 as components
from PIL import Image
import pytz
import uuid
import time

# --- タイムゾーン設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')

def init_config():
    """アプリの基本設定と、ブラウザのスリープ防止・プルリロード抑制"""
    st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")
    
    # モバイル端末での使い勝手を向上させるJavaScript
    # スリープ防止動画の再生と、下スワイプでの意図しないリロードを防止する
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
            video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
            return video;
        }
        const v = createNoSleepVideo();
        document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
        requestWakeLock();
        // モバイルでの「引っ張って更新」を無効化
        document.body.style.overscrollBehaviorY = 'contain'; 
    })();
    </script>
    """, height=0)

def apply_custom_style(primary_color="#ff4b4b"):
    """
    施設ごとのテーマカラーを画面に反映させる詳細CSS。
    カレンダーの曜日色付けやボタンの挙動まで制御。
    """
    st.markdown(f"""
        <style>
        /* メインタイトル装飾 */
        .main-title {{ 
            font-size: 24px; 
            font-weight: bold; 
            color: {primary_color}; 
            border-bottom: 3px solid {primary_color}; 
            margin-bottom: 20px; 
            padding-bottom: 5px;
            display: block; 
        }}
        
        /* 全ボタンの角丸統一 */
        div.stButton > button {{ 
            border-radius: 12px !important; 
            border: 1px solid #ddd !important;
        }}
        
        /* TOPに戻るボタン専用スタイル */
        .top-back-btn button {{ 
            background-color: {primary_color} !important; 
            color: white !important; 
            width: 100% !important; 
            font-weight: bold !important; 
            height: 45px !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        /* テキストエリアの文字を大きく（現場の視認性向上） */
        .stTextArea textarea {{ font-size: 16px !important; }}
        
        /* コピー用コードブロックの折り返し設定 */
        code {{ 
            white-space: pre-wrap !important; 
            word-break: break-all !important; 
            background-color: #f0f2f6 !important;
        }}

        /* カレンダーの日曜（赤）と土曜（青）を強調 */
        div[data-baseweb="calendar"] [aria-label*="Sunday"] {{ color: {primary_color} !important; font-weight: bold !important; }}
        div[data-baseweb="calendar"] [aria-label*="Saturday"] {{ color: #0000ff !important; font-weight: bold !important; }}
        
        /* アコーディオン（Expander）の枠線を整える */
        .stExpander {{ 
            border-radius: 10px !important; 
            border: 1px solid #eee !important; 
            margin-bottom: 8px !important; 
        }}
        </style>
        """, unsafe_allow_html=True)

@st.cache_resource
def init_clients():
    """SupabaseとGeminiの初期接続（安全性チェック付き）"""
    try:
        # Secretsの欠落を厳格にチェック
        for key in ["SUPABASE_URL", "SUPABASE_KEY", "GEMINI_API_KEY"]:
            if key not in st.secrets:
                st.error(f"❌ 設定が見つかりません: {key}")
                st.stop()
            
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.error(f"⚠️ 接続エラーが発生しました: {e}")
        st.stop()

def get_cookie_manager():
    """端末のセッション維持用マネージャー。キーの重複を避ける。"""
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_v36_stable")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    """ロゴの表示。画像がない場合はスタイリッシュなテキストを表示。"""
    try:
        image = Image.open(logo_path)
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
        if show_line: st.divider()
    except:
        st.markdown("<h2 style='text-align: center; color: #444;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)
        if show_line: st.divider()

def back_to_top_button(key_suffix):
    """全画面共通の「TOPに戻る」ボタン。状態リセット付き。"""
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({
            "page": "top", 
            "edit_content": "", 
            "monitoring_result": "", 
            "editing_record_id": None
        })
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def get_facility_config(supabase, f_code):
    """施設ごとのカスタム設定（テーマカラー等）をDBから取得。"""
    try:
        res = supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute()
        return res.data if res.data else {}
    except:
        return {}

# 🚀 将来のLINE通知機能の予約枠
def send_line_api(line_id, message):
    """
    ここに将来 LINE Messaging API との通信ロジックを実装する。
    """
    pass