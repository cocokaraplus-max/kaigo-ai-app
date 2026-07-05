import pytz
from google import genai
from google.genai import types
import os
import uuid
# upload-heic-jpeg-normalize-v1 : 画像正立+JPEG変換用
import io as _img_io
try:
    from PIL import Image as _PILImage, ImageOps as _PILImageOps
    try:
        import pillow_heif as _pillow_heif
        _pillow_heif.register_heif_opener()
        _HEIC_OK = True
    except Exception as _heic_e:
        _HEIC_OK = False
        print('[img-normalize] pillow_heif 未使用: ' + str(_heic_e), flush=True)
    _PIL_OK = True
except Exception as _pil_e:
    _PIL_OK = False
    print('[img-normalize] PIL 未使用: ' + str(_pil_e), flush=True)

def _normalize_image_to_jpeg(raw_bytes):
    """画像バイトをEXIF正立補正しJPEGに統一変換して返す。
    失敗時は None を返し、呼び出し側が元バイトにフォールバックする。"""
    if not _PIL_OK:
        return None
    try:
        im = _PILImage.open(_img_io.BytesIO(raw_bytes))
        im = _PILImageOps.exif_transpose(im)  # 向きを正立に
        if im.mode not in ('RGB', 'L'):
            im = im.convert('RGB')
        # 長辺2048にリサイズ(大きすぎる写真の軽量化。小さい画像はそのまま)
        max_side = 2048
        w, h = im.size
        if max(w, h) > max_side:
            if w >= h:
                nw, nh = max_side, int(h * max_side / w)
            else:
                nw, nh = int(w * max_side / h), max_side
            im = im.resize((nw, nh), _PILImage.LANCZOS)
        out = _img_io.BytesIO()
        im.save(out, format='JPEG', quality=85, optimize=True)
        return out.getvalue()
    except Exception as _e:
        print('[img-normalize] 変換失敗(元バイトで保存): ' + str(_e), flush=True)
        return None

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
            # upload-heic-jpeg-normalize-v1 : 正立+JPEG統一変換。失敗時は元バイト・元拡張子で保存(従来動作)。
            img_bytes = img_file.read()
            _jpeg = _normalize_image_to_jpeg(img_bytes)
            if _jpeg is not None:
                img_bytes = _jpeg
                ext = 'jpg'
                content_type = 'image/jpeg'
            else:
                filename = img_file.filename or ''
                ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
                content_type = img_file.content_type or 'image/jpeg'
            file_name = f"{f_code}/{uuid.uuid4()}.{ext}"
            supabase.storage.from_("case-photos").upload(
                path=file_name,
                file=img_bytes,
                file_options={"content-type": content_type}
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
def upload_pdf_to_supabase(supabase, pdf_file, f_code):
    try:
        file_name = f"{f_code}/{uuid.uuid4()}.pdf"
        pdf_bytes = pdf_file.read()
        supabase.storage.from_("board-files").upload(
            path=file_name,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"}
        )
        return supabase.storage.from_("board-files").get_public_url(file_name)
    except Exception as e:
        print(f"PDFアップロードエラー: {e}", flush=True)
        return ""

# ==========================================
# Session 29 (B-4): ケース記録のAI検索タグ自動生成
# ==========================================
def generate_search_tags(content, category=""):
    """
    ケース記録の本文(+カテゴリ)から検索用タグを生成する。

    形式: 1つの概念につき [漢字, ひらがな, カタカナ] の3バリエーションを抽出。
    複数概念があれば全部にそれぞれ3バリエーションを付ける。
    例:
      入力: "食事の様子。褥瘡の発赤あり。"
      出力: ["食事","しょくじ","ショクジ","褥瘡","じょくそう","ジョクソウ","発赤","ほっせき","ホッセキ"]

    モデル: Gemini 2.5 Flash (FastGeminiModel のフォールバックで)
    失敗時は空配列を返す(呼び出し側のメイン処理を止めない)。

    Args:
        content (str): ケース記録の本文
        category (str): カテゴリ名(任意)。"その他" 以外なら先頭タグとして含める。

    Returns:
        list[str]: タグ配列。失敗時は []。
    """
    if not content or not content.strip():
        return []

    try:
        prompt = (
            "以下の介護記録から、検索用のキーワードタグを抽出してください。\n\n"
            "【ルール】\n"
            "1. 本文中の重要な概念(症状・行為・状態・出来事・身体部位など)を抽出してください\n"
            "2. 各概念について、必ず3バリエーション(漢字表記・ひらがな表記・カタカナ表記)を出してください\n"
            "3. 概念が複数あれば、それぞれ3バリエーションずつ出してください\n"
            "4. 一般的すぎる語(「今日」「とても」「様子」など)は除外してください\n"
            "5. JSON配列のみを返してください(説明文・コードブロック不要)\n\n"
            "【入力】\n"
            f"カテゴリ: {category or '(指定なし)'}\n"
            f"本文: {content}\n\n"
            "【出力例】\n"
            "本文「入浴介助中に右足首に発赤あり。褥瘡の初期と判断。」\n"
            '出力: ["入浴","にゅうよく","ニュウヨク","発赤","ほっせき","ホッセキ","褥瘡","じょくそう","ジョクソウ"]\n\n'
            "【出力】"
        )
        model = get_generative_model()
        resp = model.generate_content([prompt])
        text = (resp.text or "").strip()

        import re as _re
        import json as _json

        # ```json ... ``` で囲まれていても拾えるよう、最初の [ から最後の ] までを抜く
        m = _re.search(r'\[.*\]', text, _re.DOTALL)
        if not m:
            return []

        tags_raw = _json.loads(m.group())
        if not isinstance(tags_raw, list):
            return []

        # サニタイズ: 文字列のみ・空除外・重複除外・長すぎ除外・上限30個
        seen = set()
        result = []
        # カテゴリは最初に入れる("その他"は意味が薄いので除外)
        if category and category.strip() and category.strip() != "その他":
            cat = category.strip()
            seen.add(cat)
            result.append(cat)
        for t in tags_raw:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or len(t) > 30 or t in seen:
                continue
            seen.add(t)
            result.append(t)
            if len(result) >= 30:
                break
        return result

    except Exception as e:
        # メイン処理を止めないため、ログだけ出して空配列を返す
        print(f"[generate_search_tags] failed: {e}", flush=True)
        return []
# === Session 31: AIカテゴリ自動振り分け ===
# Session 33: 「休み連絡」を追加(誰からの連絡かまではAIに推測させない)

# 9カテゴリと、それぞれの判定基準(プロンプト内で使う)
AI_CATEGORY_DEFINITIONS = {
    "入浴": "入浴・清拭・シャワー浴・足浴など、体を洗う/拭く行為そのものに関する記録",
    "食事": "食事介助・食事摂取量・水分摂取・嚥下・好き嫌い・食事中の様子に関する記録",
    "排泄": "排尿・排便・トイレ介助・オムツ交換・失禁・便秘・下痢に関する記録",
    "コミュニケーション": "利用者本人の自発的・能動的な他者交流(他利用者との会話・談笑、家族との面会・連絡、社会参加など)、または職員が意図的に働きかけて生まれた交流に関する記録。職員が一方的にサービスを提供しただけの場面は対象外。",
    "心身状況": "バイタル測定値、体調の変化、認知症状、精神状態、ADL/IADLの変化、睡眠状況など、利用者の心身の状態を記述した記録",
    "訓練状況": "リハビリ・機能訓練・歩行訓練・口腔体操・レクリエーションを通じた機能維持など、訓練に関する記録",
    "ヒヤリハット": "転倒・転落・誤薬・誤嚥・離設・けが・事故未遂など、安全に関わるインシデントの記録",
    "休み連絡": "本人または家族からの『今日は休む』『欠席する』『遅刻する』『早退する』といった利用予定の変更連絡に関する記録。誰からの連絡かまでは判定しなくてよい。",
    "その他": "上記8カテゴリのいずれにも明確に当てはまらない記録",
}


def classify_category(content: str, current_category: str = "その他") -> dict:
    """
    ケース記録の本文から、推奨カテゴリを判定する。
    保守的判定: 確信が持てない場合は必ず「その他」を返す。
    無理に8カテゴリのどれかに押し込まない。

    Args:
        content (str): ケース記録の本文
        current_category (str): 現在のカテゴリ(参考情報。判定には影響させない)

    Returns:
        dict: {
            "category": str,        # 推奨カテゴリ(9カテゴリのいずれか)
            "confidence": str,      # "high" or "low"
            "reason": str,          # 判定理由(短文)
        }
        confidence == "low" の時は category は必ず "その他"。
        失敗時は {"category": "その他", "confidence": "low", "reason": "AI判定エラー"}。
    """
    if not content or not content.strip():
        return {"category": "その他", "confidence": "low", "reason": "本文が空"}

    try:
        # カテゴリ定義をプロンプトに埋め込む
        category_lines = "\n".join(
            f"- {name}: {desc}" for name, desc in AI_CATEGORY_DEFINITIONS.items()
        )

        prompt = (
            "あなたは介護記録のカテゴリ分類を行うアシスタントです。\n"
            "以下の本文を読み、最もふさわしいカテゴリを9つの中から1つだけ選んでください。\n\n"
            "【最重要原則】\n"
            "・**保守的に判定してください**。明確に当てはまる場合のみ8カテゴリ(入浴/食事/排泄/コミュニケーション/心身状況/訓練状況/ヒヤリハット/休み連絡)に分類してください。\n"
            "・少しでも迷う、複数カテゴリにまたがる、文脈が短すぎて判断できない、といった場合は **必ず「その他」** を返してください。\n"
            "・無理に8カテゴリに押し込めるよりも、「その他」のままで残すほうが安全です。\n"
            "・**「休み連絡」を選んだ場合、誰からの連絡か(本人/家族/関係性)までは判定しないでください**。カテゴリだけ正しく分類すれば十分で、誰からの連絡かは人間が後から編集で入力します。\n\n"
            "【カテゴリ定義】\n"
            f"{category_lines}\n\n"
            "【出力形式】\n"
            "以下のJSONのみを返してください(説明文・コードブロック不要):\n"
            '{"category": "<カテゴリ名>", "confidence": "<high または low>", "reason": "<30文字以内の判定理由>"}\n\n'
            "・confidence: 8カテゴリのいずれかにハッキリ当てはまるなら \"high\"、それ以外は \"low\"\n"
            "・confidence が \"low\" の場合、category は必ず \"その他\" にしてください\n\n"
            "【入力】\n"
            f"本文: {content}\n\n"
            "【出力】"
        )

        model = get_generative_model()
        resp = model.generate_content([prompt])
        text = (resp.text or "").strip()

        import re as _re
        import json as _json

        # ```json ... ``` で囲まれていても拾えるよう、最初の { から最後の } までを抜く
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if not m:
            return {"category": "その他", "confidence": "low", "reason": "AI応答パース失敗"}

        data = _json.loads(m.group())
        if not isinstance(data, dict):
            return {"category": "その他", "confidence": "low", "reason": "AI応答が辞書形式でない"}

        category = str(data.get("category", "その他")).strip()
        confidence = str(data.get("confidence", "low")).strip().lower()
        reason = str(data.get("reason", "")).strip()[:60]  # 30文字指示だが余裕を持って60で切る

        # バリデーション: カテゴリは8つのいずれかでなければ「その他」に正規化
        if category not in AI_CATEGORY_DEFINITIONS:
            return {"category": "その他", "confidence": "low", "reason": f"未知のカテゴリ: {category}"}

        # confidence は high/low のいずれか
        if confidence not in ("high", "low"):
            confidence = "low"

        # confidence == low の場合、category は必ず「その他」に強制
        if confidence == "low":
            category = "その他"

        # confidence == high で「その他」が返ってきた場合 → low に正規化(矛盾防止)
        if confidence == "high" and category == "その他":
            confidence = "low"

        return {"category": category, "confidence": confidence, "reason": reason or "(理由なし)"}

    except Exception as e:
        # メイン処理を止めないため、ログだけ出してデフォルト値を返す
        print(f"[classify_category] failed: {e}", flush=True)
        return {"category": "その他", "confidence": "low", "reason": "AI判定エラー"}