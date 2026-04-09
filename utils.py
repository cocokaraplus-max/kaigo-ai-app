import streamlit as st
import pytz
from google import genai
from google.genai import types
from PIL import Image
import os
import io

tokyo_tz = pytz.timezone('Asia/Tokyo')

# ==========================================
# 🍪 ログイン情報の永続化
# localStorageを使ってリブート後もログイン維持
# ==========================================
def get_cookie(key):
    return st.session_state.get(f"cookie_{key}", "")

def set_cookie(key, value):
    st.session_state[f"cookie_{key}"] = value

def delete_cookie(key):
    if f"cookie_{key}" in st.session_state:
        del st.session_state[f"cookie_{key}"]

def load_from_local_storage():
    """localStorageからログイン情報を読み込む"""
    st.components.v1.html("""
        <script>
            const fCode = localStorage.getItem('tasukaru_f_code');
            const myName = localStorage.getItem('tasukaru_my_name');
            if (fCode && myName) {
                window.parent.postMessage({
                    type: 'streamlit:setComponentValue',
                    value: fCode + '|||' + myName
                }, '*');
            }
        </script>
    """, height=0)

def save_to_local_storage(f_code, my_name):
    """localStorageにログイン情報を保存"""
    st.components.v1.html(f"""
        <script>
            localStorage.setItem('tasukaru_f_code', '{f_code}');
            localStorage.setItem('tasukaru_my_name', '{my_name}');
        </script>
    """, height=0)

def clear_local_storage():
    """localStorageのログイン情報を削除"""
    st.components.v1.html("""
        <script>
            localStorage.removeItem('tasukaru_f_code');
            localStorage.removeItem('tasukaru_my_name');
        </script>
    """, height=0)

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
# 🖼️ 画像を圧縮する関数
# ==========================================
def compress_image(img, max_size=(800, 800), quality=75):
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail(max_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()

# ==========================================
# 🤖 Gemini AI モデル
# ==========================================
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
                img_bytes = compress_image(item)
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
            elif isinstance(item, dict) and "mime_type" in item:
                parts.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=parts,
            )
            return response
        except Exception as e:
            raise Exception(f"🤖 AI通信エラー: {str(e)}\nしばらく待ってから再試行してください。")

def get_generative_model():
    return FastGeminiModel()