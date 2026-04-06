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
    
    # モバイル端末での使い勝手を向上させるJavaScript注入
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
        // ユーザーが画面に触れたら動画再生とWakeLockを開始
        document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
        requestWakeLock();
        // 下スワイプによるリロードを抑制（誤操作防止）
        document.body.style.overscrollBehaviorY = 'contain'; 
    })();
    </script>
    """, height=0)

def apply_custom_style(primary_color="#ff4b4b"):
    """
    施設ごとのテーマカラーを画面に反映させる詳細CSS。
    """
    st.markdown(f"""
        <style>
        /* メインタイトル */
        .main-title {{ 
            font-size: 24px; 
            font-weight: bold; 
            color: {primary_color}; 
            border-bottom: 3px solid {primary_color}; 
            margin-bottom: 20px; 
            padding-bottom: 5px;
            display: block; 
        }}
        
        /* ボタン全般の角丸と影 */
        div.stButton > button {{ 
            border-radius: 12px !important; 
            transition: all 0.3s ease;
        }}
        
        /* TOPに戻るボタン（目立たせる） */
        .top-back-btn button {{ 
            background-color: {primary_color} !important; 
            color: white !important; 
            width: 100% !important; 
            font-weight: bold !important; 
            border: none !important;
            height: 45px !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        /* 記録内容（テキストエリア等）のフォントサイズ調整 */
        .stTextArea textarea {{ font-size: 16px !important; }}
        
        /* コードブロック（コピー枠）の読みやすさ */
        code {{ 
            white-space: pre-wrap !important; 
            word-break: break-all !important; 
            background-color: #f0f2f6 !important;
            color: #31333f !important;
        }}

        /* カレンダーの日曜（赤）と土曜（青） */
        div[data-baseweb="calendar"] [aria-label*="Sunday"] {{ color: {primary_color} !important; font-weight: bold !important; }}
        div[data-baseweb="calendar"] [aria-label*="Saturday"] {{ color: #0000ff !important; font-weight: bold !important; }}
        
        /* アコーディオンの余白調整 */
        .stExpander {{ border-radius: 10px !important; border: 1px solid #ddd !important; margin-bottom: 10px !important; }}
        </style>
        """, unsafe_allow_html=True)

@st.cache_resource
def init_clients():
    """データベースとAIの接続初期化（厳格なチェック付き）"""
    try:
        # Secretsの存在確認
        required_keys = ["SUPABASE_URL", "SUPABASE_KEY", "GEMINI_API_KEY"]
        for key in required_keys:
            if key not in st.secrets:
                st.error(f"❌ 設定（Secrets）に {key} が見つかりません。")
                st.stop()
            
        s_url = st.secrets["SUPABASE_URL"]
        s_key = st.secrets["SUPABASE_KEY"]
        g_key = st.secrets["GEMINI_API_KEY"]
        
        # AI設定
        genai.configure(api_key=g_key)
        
        # クライアント生成
        return create_client(s_url, s_key)
    except Exception as e:
        st.error(f"⚠️ システム接続に失敗しました: {e}")
        st.stop()

def get_cookie_manager():
    """端末のクッキー情報を管理。キーを更新して安定性を確保。"""
    if "cookie_manager" not in st.session_state:
        # キーをユニークにしてキャッシュ干渉を防ぐ
        st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_v36_prod")
    return st.session_state["cookie_manager"]

def display_logo(logo_path='logo.png', show_line=False):
    """ロゴの表示ロジック。画像がない場合の代替表示も完備。"""
    try:
        image = Image.open(logo_path)
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
        if show_line:
            st.divider()
    except Exception:
        st.markdown("<h2 style='text-align: center; color: #333;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)
        if show_line: st.divider()

def back_to_top_button(key_suffix):
    """全画面共通：入力をリセットしてTOPへ戻る魔法のボタン"""
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        # 状態をリセットしてから画面遷移
        st.session_state.update({
            "page": "top", 
            "edit_content": "", 
            "monitoring_result": "", 
            "editing_record_id": None,
            "show_history_list": False
        })
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def get_facility_config(supabase, f_code):
    """データベースから施設の独自設定を読み込む。"""
    try:
        res = supabase.table("facility_settings").select("*").eq("facility_code", f_code).single().execute()
        return res.data if res.data else {}
    except Exception:
        # 設定がない場合は空の辞書を返す（エラーで止めない）
        return {}

# 🚀 【予告】LINE Messaging API 連携用
def send_line_notification(line_user_id, message_text):
    """将来、ここからご家族のLINEへ直接メッセージを飛ばす。"""
    # TODO: LINE DevelopersでChannel Access Tokenを取得後に実装
    pass