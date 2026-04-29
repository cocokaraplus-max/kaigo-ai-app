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
            print(f"写真アップロードエラー: {e}", flush=True)
    return image_urls

# ==========================================
# Gemini AI
# ==========================================
class GeminiResponse:
    def __init__(self, text):
        self.text = text

# 優先順:速い→重い→軽い→旧世代軽量→latest別名
FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
]

# 一時的な高負荷・レート制限と判定するエラー
TRANSIENT_KEYWORDS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "high demand", "overloaded")

def _is_transient(error_str: str) -> bool:
    es = error_str or ""
    return any(k in es for k in TRANSIENT_KEYWORDS)

class FastGeminiModel:
    def generate_content(self, contents):
        api_key = get_secret("GEMINI_API_KEY")
        if not api_key:
            raise Exception("GEMINI_API_KEY が設定されていません。")

        client = genai.Client(api_key=api_key)

        # contents を SDK の parts に組み立て
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "mime_type" in item:
                parts.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))

        last_error = None
        last_error_str = ""

        # 各モデルについて、503系なら指数バックオフで3回まで再試行 → ダメなら次のモデルへ
        for model_idx, model_name in enumerate(FALLBACK_MODELS):
            for attempt in range(3):  # 0, 1, 2 → 計3回
                try:
                    response = client.models.generate_content(model=model_name, contents=parts)
                    # 安全フィルタなどでcandidatesが空のときに備えて防御的に取る
                    try:
                        text = response.candidates[0].content.parts[0].text
                    except Exception:
                        text = getattr(response, "text", None) or ""
                    if not text:
                        raise Exception("応答テキストが空でした(安全フィルタの可能性)")
                    if model_idx > 0 or attempt > 0:
                        print(f"[gemini ok] model={model_name} attempt={attempt+1}", flush=True)
                    return GeminiResponse(text)

                except Exception as e:
                    error_str = str(e)
                    last_error = e
                    last_error_str = error_str

                    if _is_transient(error_str):
                        # 一時的なエラー: 同モデルで指数バックオフ(1s, 2s, 4s)
                        wait = 1 << attempt  # 1, 2, 4 秒
                        print(
                            f"[gemini transient] model={model_name} attempt={attempt+1}/3 "
                            f"wait={wait}s err={error_str[:120]}",
                            flush=True,
                        )
                        if attempt < 2:
                            time_module.sleep(wait)
                            continue
                        # attempt=2 まで全滅 → 内側ループ抜けて次のモデルへ
                        break

                    if "404" in error_str or "NOT_FOUND" in error_str:
                        # モデル名が無効 → 即次のモデルへ
                        print(f"[gemini 404] model={model_name} not found, trying next", flush=True)
                        break

                    # その他の致命的エラー(認証エラー等)は再試行しても無駄なので即終了
                    print(f"[gemini fatal] model={model_name} err={error_str[:200]}", flush=True)
                    raise Exception(f"AI通信エラー: {error_str}")

            # 次のモデルに進む前にログ
            print(f"[gemini fallback] {model_name} 全失敗、次のモデルへ", flush=True)

        # 全モデル全リトライ失敗
        raise Exception(
            f"現在Gemini APIが混雑しており、しばらくしてから再度お試しください。"
            f"(全モデルで失敗: {last_error_str[:200]})"
        )


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
        print(f"音声アップロードエラー: {e}", flush=True)
        return ""
