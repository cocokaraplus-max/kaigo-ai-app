import streamlit as st
import pytz
from google import genai
from google.genai import types
from PIL import Image
import os
import io
import uuid
import base64
import json
import time as time_module

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

def encode_login_token(f_code, my_name):
    data = json.dumps({"f": f_code, "n": my_name})
    token = base64.urlsafe_b64encode(data.encode()).decode()
    return token

def decode_login_token(token):
    try:
        data = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        return data.get("f", ""), data.get("n", "")
    except Exception:
        return "", ""

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
    image_urls = []
    for img_file in imgs:
        try:
            ext = img_file.name.split(".")[-1].lower()
            file_name = f"{f_code}/{uuid.uuid4()}.{ext}"
            img_bytes = img_file.read()
            supabase.storage.from_("case-photos").upload(
                path=file_name,
                file=img_bytes,
                file_options={"content-type": img_file.type}
            )
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
# 複数モデルを順番に試して安定性を向上
# ==========================================

# 使用するモデルの優先順位
# 503混雑時は次のモデルに自動切り替え
FALLBACK_MODELS = [
    "gemini-2.5-flash",       # メイン：高性能
    "gemini-2.5-flash-lite",  # 軽量版：混雑しにくい
    "gemini-2.0-flash-lite",  # さらに軽量
    "gemini-flash-latest",    # 最新フラッシュ
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
            elif isinstance(item, dict) and "mime_type" in item:
                parts.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))

        last_error = None

        for model_name in FALLBACK_MODELS:
            # 各モデルで最大2回リトライ
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=parts,
                    )
                    text = response.candidates[0].content.parts[0].text
                    return GeminiResponse(text)
                except Exception as e:
                    error_str = str(e)
                    last_error = e
                    if "503" in error_str:
                        # 503は少し待ってリトライ or 次のモデルへ
                        if attempt == 0:
                            time_module.sleep(2)
                            continue
                        else:
                            # 2回失敗したら次のモデルへ
                            break
                    elif "404" in error_str:
                        # モデルが存在しない場合は即次のモデルへ
                        break
                    else:
                        # その他のエラーは即エラー
                        raise Exception(f"🤖 AI通信エラー: {error_str}\nしばらく待ってから再試行してください。")

        raise Exception(f"🤖 AI通信エラー: 全モデルで失敗しました。しばらく待ってから再試行してください。\n詳細: {str(last_error)}")

def get_generative_model():
    return FastGeminiModel()