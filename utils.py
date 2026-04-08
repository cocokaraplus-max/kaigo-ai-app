import streamlit as st
import pytz
import google.generativeai as genai
from PIL import Image
from streamlit_cookies_manager import EncryptedCookieManager
import os

# タイムゾーン設定
tokyo_tz = pytz.timezone('Asia/Tokyo')

# クッキー管理
cookie_manager = EncryptedCookieManager(
    password=os.environ.get("COOKIES_PASSWORD", "ST_COOKIES_PWD_DEFAULT_12345"),
)
if not cookie_manager.ready():
    st.stop()

def display_logo(show_line=True):
    try:
        img = Image.open("logo.png")
        st.image(img, use_container_width=True)
    except:
        st.markdown("<h1 style='text-align: center;'>🦝 TASUKARU</h1>", unsafe_allow_html=True)
    if show_line:
        st.divider()

def back_to_top_button(key):
    if st.button("🏠 TOP画面へ", key=key, use_container_width=True):
        st.session_state["page"] = "top"
        st.rerun()

# 🚀 【最強版】エラーを自動で回避するAI呼び出し関数
def call_gemini_ai(contents):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 使える可能性のあるモデルを新しい順に試す
    models_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-flash-latest',
        'gemini-1.0-pro',
        'gemini-pro'
    ]
    
    last_error = None
    for m_name in models_to_try:
        try:
            model = genai.GenerativeModel(m_name)
            response = model.generate_content(contents)
            return response.text.strip()
        except Exception as e:
            last_error = e
            # NotFound (404) エラーなら次のモデルを試す
            if "NotFound" in str(type(e).__name__) or "404" in str(e):
                continue
            else:
                # APIキー間違いなどの致命的エラーはそのまま出す
                raise e
                
    # 全滅した場合
    raise Exception(f"利用可能なAIモデルが見つかりませんでした。詳細: {last_error}")