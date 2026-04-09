import streamlit as st
import pytz
import google.generativeai as genai
from PIL import Image
import os

tokyo_tz = pytz.timezone('Asia/Tokyo')

# ==========================================
# 🍪 クッキーの代替：session_stateで管理
# ==========================================
# streamlit-cookies-managerを廃止し、
# st.session_stateで安定したログイン維持を実現

def get_cookie(key):
    """session_stateからログイン情報を取得"""
    return st.session_state.get(f"cookie_{key}", "")

def set_cookie(key, value):
    """session_stateにログイン情報を保存"""
    st.session_state[f"cookie_{key}"] = value

def delete_cookie(key):
    """session_stateからログイン情報を削除"""
    if f"cookie_{key}" in st.session_state:
        del st.session_state[f"cookie_{key}"]

# 後方互換性のためのcookie_managerオブジェクト
class SimpleCookieManager:
    def get(self, key):
        return get_cookie(key)

    def __setitem__(self, key, value):
        set_cookie(key, value)

    def save(self):
        pass  # session_stateは自動保存なので不要

    def delete(self, key):
        delete_cookie(key)

cookie_manager = SimpleCookieManager()

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