import streamlit as st
import pytz
import google.generativeai as genai
from PIL import Image
from streamlit_cookies_manager import EncryptedCookieManager
import os

tokyo_tz = pytz.timezone('Asia/Tokyo')

# ==========================================
# 🍪 クッキー管理
# ==========================================
cookie_manager = EncryptedCookieManager(
    prefix="tasukaru_",
    password=st.secrets.get("COOKIES_PASSWORD", os.environ.get("COOKIES_PASSWORD", "ST_COOKIES_PWD_DEFAULT_12345")),
)

def init_cookie_manager():
    """
    クッキーマネージャーの初期化。
    ready()でない場合は最大3秒待ってリトライし、
    それでもダメなら警告だけ出して続行する。
    """
    if not cookie_manager.ready():
        # st.stop()をやめて、自動リロードで再試行する
        st.markdown(
            "<meta http-equiv='refresh' content='1'>",
            unsafe_allow_html=True
        )
        st.warning("⏳ 読み込み中です。そのままお待ちください...")
        st.stop()

# ==========================================
# 🖼️ ロゴ表示
# ==========================================
def display_logo(show_line=True):
    if os.path.exists("logo.png"):
        try:
            img = Image.open("logo.png")
            st.image(img, use_container_width=True)
        except:
            st.markdown("<h1 style='text-align: center;'>🦝 TASUKARU</h1>", unsafe_allow_html=True)
    else:
        st.markdown("<h1 style='text-align: center;'>🦝 TASUKARU</h1>", unsafe_allow_html=True)

    if show_line:
        st.divider()

# ==========================================
# 🏠 TOPへ戻るボタン
# ==========================================
def back_to_top_button(key):
    if st.button("🏠 TOP画面へ", key=key, use_container_width=True):
        st.session_state["page"] = "top"
        st.rerun()

# ==========================================
# 🤖 Gemini AI モデル
# ==========================================
class FastGeminiModel:
    def generate_content(self, contents):
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            raise Exception("🔑 Secrets に GEMINI_API_KEY が設定されていません。\n管理者に連絡してください。")

        genai.configure(api_key=api_key)
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            return model.generate_content(contents)
        except Exception as e:
            raise Exception(f"🤖 AI通信エラー: {str(e)}\nしばらく待ってから再試行してください。")

def get_generative_model():
    return FastGeminiModel()