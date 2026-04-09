import streamlit as st
import pytz
from google import genai
from google.genai import types
from PIL import Image
import os
import io

tokyo_tz = pytz.timezone('Asia/Tokyo')

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

def back_to_top_button(key):
    if st.button("🏠 TOP画面へ", key=key, use_container_width=True):
        st.session_state["page"] = "top"
        st.rerun()

# 試すモデルのリスト（上から順に試す）
MODELS_TO_TRY = [
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash",
]

class FastGeminiModel:
    def generate_content(self, contents):
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            raise Exception("🔑 Secrets に GEMINI_API_KEY が設定されていません。")

        client = genai.Client(api_key=api_key)

        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Image.Image):
                buf = io.BytesIO()
                item.save(buf, format="JPEG")
                parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
            elif isinstance(item, dict) and "mime_type" in item:
                parts.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))

        last_error = None
        for model_name in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=parts,
                )
                return response
            except Exception as e:
                last_error = e
                continue

        raise Exception(f"🤖 AI通信エラー: {str(last_error)}\nしばらく待ってから再試行してください。")

def get_generative_model():
    return FastGeminiModel()