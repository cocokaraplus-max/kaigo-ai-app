import pytz
from google import genai
from google.genai import types
import os
import uuid
import time as time_module

tokyo_tz = pytz.timezone('Asia/Tokyo')

def get_secret(key):
    return os.environ.get(key, "")

# ==========================================
# 写真をSupabaseストレージに保存
# ==========================================
def upload_images_to_supabase(supabase, imgs, f_code):
    image_urls = []
    for img_file in imgs:
        try:
            filename = img_file.filename
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
            file_name = f"{f_code}/{uuid.uuid4()}.{ext}"
            img_bytes = img_file.read()
            supabase.storage.from_("case-photos").upload(
                path=file_name,
                file=img_bytes,
                file_options={"content-type": img_file.content_type or "image/jpeg"}
            )
            url = supabase.storage.from_("case-photos").get_public_url(file_name)
            image_urls.append(url)
        except Exception as e:
            print(f"写真アップロードエラー: {e}")
    return image_urls

# ==========================================
# Gemini AI
# ==========================================
class GeminiResponse:
    def __init__(self, text):
        self.text = text

FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
]

class FastGeminiModel:
    def generate_content(self, contents):
        api_key = get_secret("GEMINI_API_KEY")
        if not api_key:
            raise Exception("GEMINI_API_KEY が設定されていません。")

        client = genai.Client(api_key=api_key)
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "mime_type" in item:
                parts.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))

        last_error = None
        for model_name in FALLBACK_MODELS:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(model=model_name, contents=parts)
                    text = response.candidates[0].content.parts[0].text
                    return GeminiResponse(text)
                except Exception as e:
                    error_str = str(e)
                    last_error = e
                    if "503" in error_str and attempt == 0:
                        time_module.sleep(2)
                        continue
                    elif "404" in error_str:
                        break
                    else:
                        raise Exception(f"AI通信エラー: {error_str}")

        raise Exception(f"全モデルで失敗しました: {str(last_error)}")

def get_generative_model():
    return FastGeminiModel()

def hash_password(password):
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest() == hashed
# ==========================================
# 音声をSupabaseストレージに保存
# ==========================================
def upload_audio_to_supabase(supabase, audio_bytes, filename, f_code):
    try:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'
        file_name = f"{f_code}/{uuid.uuid4()}.{ext}"
        mime_map = {'mp3':'audio/mpeg','m4a':'audio/mp4','wav':'audio/wav','aac':'audio/aac','ogg':'audio/ogg','webm':'audio/webm'}
        content_type = mime_map.get(ext, 'audio/mpeg')
        supabase.storage.from_("assessment-audio").upload(
            path=file_name,
            file=audio_bytes,
            file_options={"content-type": content_type}
        )
        return supabase.storage.from_("assessment-audio").get_public_url(file_name)
    except Exception as e:
        print(f"音声アップロードエラー: {e}")
        return ""
