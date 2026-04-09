import streamlit as st
import pytz
import google.generativeai as genai
from PIL import Image
import os

tokyo_tz = pytz.timezone('Asia/Tokyo')

# ==========================================
# 🍪 クッキーの代替：session_stateで管理
# ==========================================
def get_cookie(key):
    return st.session_state.get(f"cookie_{key}", "")

def set_cookie(key, value):
    st.session_state[f"cookie_{key}"] = value

def delete_cookie(key):
    if f"cookie_{key}" in st.session_state:
        del st.session_state[f"cookie_{key}"]

class SimpleCookieManager:
    def get(self, key):
        return get_cookie(key)

    def __setitem__(self, key, value):
        set_cookie(key, value)

    def save(self):
        pass

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
            raise Exception("🔑 Secrets に GEMINI_API_KEY が設定されていません。")

        # ✅ 修正：APIクライアントを新しい書き方に変更
        client = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"temperature": 0.7}
        )
        genai.configure(api_key=api_key)

        try:
            response = client.generate_content(contents)
            return response
        except Exception as e:
            # モデルが見つからない場合は別のモデルで再試行
            try:
                genai.configure(api_key=api_key)
                fallback = genai.GenerativeModel("gemini-pro")
                return fallback.generate_content(contents)
            except Exception as e2:
                raise Exception(f"🤖 AI通信エラー: {str(e)}\nしばらく待ってから再試行してください。")

def get_generative_model():
    return FastGeminiModel()