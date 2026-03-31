import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime
import pytz 
from supabase import create_client, Client # type: ignore
import uuid
import time
from PIL import Image # type: ignore

# 日本時間の設定
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)

# --- 1. 接続設定とUIカスタム ---
st.set_page_config(page_title="TASUKARU ケース記録", page_icon="🦝", layout="wide")

def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except: pass

load_css("style.css")

# Supabase & Gemini 接続設定
try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続エラー: {e}")
    st.stop()

def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        return sorted(list(set([r['user_name'] for r in res.data if r['user_name']]))) if res.data else []
    except: return []

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        st.image(image)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except: st.title("🦝 TASUKARU")

# セッション状態
if "page" not in st.session_state: st.session_state["page"] = "top"
if "form_id" not in st.session_state: st.session_state["form_id"] = 0
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""

# ==========================================
# 🏠 TOP画面
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        if st.button("✍️ 今日の記録を書く\n(音声・写真対応)", use_container_width=True):
            st.session_state["page"] = "input"; st.rerun()
    with col_t2:
        if st.button("📊 過去の履歴を見る\n(検索・モニタリング)", use_container_width=True):
            st.session_state["page"] = "history"; st.rerun()

# ==========================================
# ✍️ 入力画面
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOPに戻る"):
        st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.title("ケース記録入力")
    fid = st.session_state["form_id"]
    col1, col2 = st.columns([1, 1])
    
    with col1:
        user_name = st.text_input("利用者名", placeholder="例：山田 太郎", key=f"u_{fid}")
        target_date = st.date_input("記録対象日", value=now_tokyo.date(), key=f"d_{fid}")
        img_file = st.file_uploader("📸 写真を選択", type=['jpg', 'png', 'jpeg'], key=f"i_{fid}")
        if img_file: st.image(img_file, width=250)
        st.subheader("🎙️ 音声入力")
        audio_value = st.audio_input("マイクをタップ", key=f"a_{fid}")
        
        if audio_value:
            if st.button("✨ AIで文章にする"):
                # メッセージ表示
                msg = st.info("🔄 文章を作成中。しばらくお待ちください...")
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                        f.write(audio_value.getvalue())
                        temp_path = f.name
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    sample_file = genai.upload_file(path=temp_path)
                    # 指示の厳格化
                    prompt = f"あなたは介護職員です。{user_name}さんの音声を、です・ます調の簡潔な文章にしてください。日時や記録者などの見出し、挨拶、音声にない情報は一切含めないでください。"
                    response = model.generate_content([sample_file, prompt])
                    st.session_state["edit_content"] = response.text
                    os.remove(temp_path)
                    msg.empty(); st.rerun()
                except Exception as e: st.error(f"AI生成エラー: {e}")

    with col2:
        st.subheader("📝 記録確認")
        # 手動修正を可能にするための設定
        st.session_state["edit_content"] = st.text_area("修正があれば書き換えてください", value=st.session_state["edit_content"], height=400, key=f"ta_{fid}")
        if st.button("💾 クラウド保存"):
            if user_name:
                try:
                    image_url = None
                    if img_file:
                        file_name = f"{uuid.uuid4()}.jpg"
                        supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                        image_url = supabase.storage.from_("case-photos").get_public_url(file_name)
                    record_data = {"user_name": user_name, "content": st.session_state["edit_content"], "image_url": image_url, "created_at": target_date.isoformat()}
                    supabase.table("records").insert(record_data).execute()
                    st.success("✅ 保存完了"); time.sleep(1); st.session_state["edit_content"] = ""; st.session_state["form_id"] += 1; st.rerun()
                except Exception as e: st.error(f"保存エラー: {e}")
            else: st.warning("利用者名を入力してください")

# ==========================================
# 📊 履歴表示・モニタリング画面
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOPに戻る"):
        st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.title("履歴・出力")
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3:
        users = get_user_list()
        s_user = st.selectbox("利用者を選択", ["（未選択）"] + users) if users else st.text_input("名前入力")
    with c4: s_year = st.selectbox("年", [2025, 2026], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=now_tokyo.month - 1)
    
    cb1, cb2 = st.columns(2)
    s_clicked = cb1.button("🔍 履歴検索", use_container_width=True)
    m_clicked = cb2.button("📈 モニタリング生成", use_container_width=True)
    
    if s_clicked or m_clicked:
        if s_user and s_user != "（未選択）":
            msg = st.info("🔄 しばらくお待ちください...")
            try:
                res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                if res.data:
                    df = pd.DataFrame(res.data)
                    df['created_at'] = pd.to_datetime(df['created_at'])
                    df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at")
                    msg.empty()
                    if m_clicked:
                        if not df_f.empty:
                            all_t = "\n".join([f"・{r.created_at.date()}: {r.content}" for _, r in df_f.iterrows()])
                            model = genai.GenerativeModel("gemini-1.5-flash")
                            # ケアマネ向け指示の再徹底
                            p = f"ケアマネジャー提出用の月間モニタリング報告書を200字程度で作成してください。ADL等の状況を専門用語で事実のみ記載。冒頭に【{s_year}年{s_month}月度 要約】と記載し、虚偽は含めないこと。\nデータ:\n{all_t}"
                            st.info(model.generate_content(p).text)
                            st.button("🖨️ 印刷/PDF保存", on_click=lambda: st.components.v1.html("<script>window.print();</script>", height=0))
                        else: st.warning("記録がありません")
                    else:
                        for d in sorted(df_f['created_at'].dt.date.unique(), reverse=True):
                            with st.expander(f"📅 {d}"):
                                for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                    st.write(r['content'])
                                    if r.get("image_url"): st.image(r["image_url"], width=250)
                else: msg.empty(); st.info("データが見つかりませんでした")
            except Exception as e: st.error(f"エラー: {e}")