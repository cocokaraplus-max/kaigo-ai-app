import streamlit as st
import pytz
from google import genai
from google.genai import types
from PIL import Image
import os
import io
import uuid

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

def save_to_local_storage(f_code, my_name):
    st.components.v1.html(f"""
        <script>
            localStorage.setItem('tasukaru_f_code', '{f_code}');
            localStorage.setItem('tasukaru_my_name', '{my_name}');
        </script>
    """, height=0)

def clear_local_storage():
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
# 📷 写真をSupabaseストレージに保存
# ==========================================
def upload_images_to_supabase(supabase, imgs, f_code):
    """
    写真をSupabaseのcase-photosバケットに保存し
    公開URLのリストを返す
    """
    image_urls = []
    for img_file in imgs:
        try:
            # ファイル名をユニークに生成
            ext = img_file.name.split(".")[-1].lower()
            file_name = f"{f_code}/{uuid.uuid4()}.{ext}"

            # ファイルをバイト列として読み込む
            img_bytes = img_file.read()

            # Supabaseストレージにアップロード
            supabase.storage.from_("case-photos").upload(
                path=file_name,
                file=img_bytes,
                file_options={"content-type": img_file.type}
            )

            # 公開URLを取得
            url = supabase.storage.from_("case-photos").get_public_url(file_name)
            image_urls.append(url)

        except Exception as e:
            st.warning(f"⚠️ 写真のアップロードに失敗しました: {e}")

    return image_urls

# ==========================================
# 🤖 Gemini レスポンスラッパー
# ==========================================
class GeminiResponse:
    def __init__(self, text):
        self.text = text

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
            elif isinstance(item, dict) and "mime_type" in item:
                parts.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=parts,
            )
            text = response.candidates[0].content.parts[0].text
            return GeminiResponse(text)
        except Exception as e:
            raise Exception(f"🤖 AI通信エラー: {str(e)}\nしばらく待ってから再試行してください。")

def get_generative_model():
    return FastGeminiModel()