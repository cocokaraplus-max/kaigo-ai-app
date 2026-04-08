import streamlit as st
import pytz
import google.generativeai as genai
from PIL import Image
from streamlit_cookies_manager import EncryptedCookieManager
import os

tokyo_tz = pytz.timezone('Asia/Tokyo')

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
    if st.button("🏠 TOP画面へ", key=key):
        st.session_state["page"] = "top"
        st.rerun()

# 🚀 魔法の仕掛け：views.pyを一切いじらずにNotFoundエラーを自動回避する！
class SafeGeminiModel:
    def generate_content(self, contents):
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            return model.generate_content(contents)
        except Exception as e:
            # NotFoundエラーが出たら、安定版の旧モデルに自動で切り替える
            if "NotFound" in str(type(e).__name__) or "404" in str(e):
                model = genai.GenerativeModel('gemini-pro')
                return model.generate_content(contents)
            raise e

def get_generative_model():
    return SafeGeminiModel()