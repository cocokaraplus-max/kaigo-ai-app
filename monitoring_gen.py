"""
モニタリング書類用 AI整文モジュール (Gemini版)
既存 utils.get_generative_model() を使用
モック切替: TASUKARU_AI_MOCK=1
"""
import os
import json
import re
from datetime import date, datetime


def _build_prompt(raw_text, mapping, context):
    fields = mapping.get("fields", {})
    schema_lines = []
    for key, info in fields.items():
        line = f'  "{key}": ({info["type"]}) {info["label"]}'
        if info.get("options"):
            line += f' — {"/".join(info["options"])}のいずれか'
        if info.get("max_chars"):
            line += f' — {info["max_chars"]}文字以内'
        if info.get("ai_hint"):
            line += f' — {info["ai_hint"]}'
        if info.get("ai_generated"):
            line += " ★AI整文対象"
        schema_lines.append(line)

    ctx_line = ""
    if context:
        parts = []
        if context.get("user_name"):
            parts.append(f"利用者名: {context['user_name']}")
        if context.get("period_year") and context.get("period_month"):
            parts.append(f"対象期間: {context['period_year']}年{context['period_month']}月")
        if context.get("staff_name"):
            parts.append(f"担当者: {context['staff_name']}")
        ctx_line = "\n# コンテキスト\n" + "\n".join(parts) + "\n"

    return f"""あなたは介護事業所のベテラン相談員です。
以下の介護記録を元に、モニタリング報告書の各項目を整えて出力してください。
{ctx_line}
# 入力（期間中の介護記録）
{raw_text}

# 出力フォーマット（JSON、キーは厳守）
{{
{chr(10).join(schema_lines)}
}}

# ルール
- 文章項目は敬体で書く（事実ベース、推測は避ける）
- ★AI整文対象の項目を記録内容から具体的にまとめる
- 記録に無い情報は空文字列 ""
- 数値項目は数値のみ
- max_chars超過しない
- 有効なJSONのみ返す（説明文・markdown装飾なし）
"""


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last + 1]
    return json.loads(text)


def _mock_generate(raw_text, mapping, context):
    result = {k: "" for k in mapping.get("fields", {}).keys()}
    if context.get("user_name"):
        for key in ["client_name", "client_name_kanji", "user_name"]:
            if key in result:
                result[key] = context["user_name"]
    if context.get("staff_name"):
        if "staff_name" in result:
            result["staff_name"] = context["staff_name"]

    pos_kw = ["元気", "笑顔", "歩行", "安定", "向上", "意欲"]
    neg_kw = ["疲れ", "しんどい", "痛み", "不安", "低下"]
    mood = "pos" if any(k in raw_text for k in pos_kw) else \
           "neg" if any(k in raw_text for k in neg_kw) else "neutral"

    texts = {
        "changes_by_training": {
            "pos": "機能訓練を継続的に実施した結果、身体機能の維持・向上がみられました。歩行や立位保持に安定感が出ており、表情も明るくなっています。",
            "neg": "機能訓練には取り組めておりますが、一部疲労の訴えや動作時の違和感があり、訓練強度の調整を行いながら継続しています。",
            "neutral": "機能訓練への参加は継続できており、現状の身体機能は維持できております。"
        },
        "issues_and_causes": {
            "pos": "現時点で特筆すべき課題はみられませんが、今後も体調変化に注意しながら継続していきます。",
            "neg": "体調の変化や痛みの訴えがみられ、訓練内容の個別調整と生活リズムの見直しが課題です。",
            "neutral": "大きな課題は認めませんが、機能維持のための意欲喚起を継続する必要があります。"
        },
        "special_notes": {
            "pos": "ご本人の意欲は高く、ご家族からも前向きな評価をいただいております。引き続き現行プランで継続します。",
            "neg": "一時的な体調不良はありましたが、現在は回復傾向です。ご家族とも状況を共有しています。",
            "neutral": "特記事項はありません。継続して様子を観察していきます。"
        },
    }
    for key, opts in texts.items():
        if key in result:
            result[key] = opts[mood]

    defaults = {
        "monitoring_item_1": "機能訓練の取り組み状況",
        "monitoring_item_2": "日常生活動作の変化",
        "monitoring_item_3": "意欲・参加状況",
        "monitoring_item_4": "家族との連携状況",
        "new_requests_exist": "なし",
        "satisfaction": "満足" if mood != "neg" else "概ね満足",
        "service_appropriateness": "適切",
    }
    for k, v in defaults.items():
        if k in result and not result[k]:
            result[k] = v

    for key in mapping.get("fields", {}):
        if key.endswith("_status") and key in result and not result[key]:
            result[key] = "達成" if mood == "pos" else "未達成"

    return result


def _call_gemini(raw_text, mapping, context):
    from utils import get_generative_model
    model = get_generative_model()
    prompt = _build_prompt(raw_text, mapping, context)
    response = model.generate_content([prompt])
    return _extract_json(response.text)


def generate_structured_data(raw_text, mapping, context=None):
    if context is None:
        context = {}
    use_mock = os.environ.get("TASUKARU_AI_MOCK", "").strip() in ("1", "true", "yes")
    try:
        if use_mock:
            return _mock_generate(raw_text, mapping, context)
        return _call_gemini(raw_text, mapping, context)
    except Exception as e:
        print(f"[monitoring_gen] Gemini失敗、モック使用: {e}")
        return _mock_generate(raw_text, mapping, context)