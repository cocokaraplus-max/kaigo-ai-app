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
    except Exception:
        pass

load_css("style.css")

# Supabase & Gemini 接続設定
try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}")
    st.stop()

def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        if res.data:
            return sorted(list(set([r['user_name'] for r in res.data if r['user_name']])))
        return []
    except Exception: return []

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        st.image(image)
        if show_line:
            st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except FileNotFoundError:
        st.title("🦝 TASUKARU")

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
            st.session_state["page"] = "input"
            st.rerun()
    with col_t2:
        if st.button("📊 過去の履歴を見る\n(検索・モニタリング)", use_container_width=True):
            st.session_state["page"] = "history"
            st.rerun()

# ==========================================
# ✍️ 入力画面
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOPに戻る"):
        st.session_state["page"] = "top"
        st.rerun()
    display_logo()
    st.title("ケース記録入力")
    fid = st.session_state["form_id"]
    col1, col2 = st.columns([1, 1])
    
    with col1:
        user_name = st.text_input("利用者名", placeholder="例：山田 太郎", key=f"u_{fid}")
        target_date = st.date_input("記録対象日", value=now_tokyo.date(), key=f"d_{fid}")
        img_file = st.file_uploader("📸 写真を選択/撮影", type=['jpg', 'png', 'jpeg'], key=f"i_{fid}")
        if img_file: st.image(img_file, width=250)
        
        st.subheader("🎙️ 音声入力")
        audio_value = st.audio_input("マイクをタップして話してください", key=f"a_{fid}")
        
        if audio_value:
            if st.button("✨ AIで文章にする"):
                # ★ メッセージ表示を確実にするためのプレースホルダー ★
                msg_placeholder = st.empty()
                with msg_placeholder.container():
                    st.info("🔄 文章を作成中。しばらくお待ちください...")
                
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                        f.write(audio_value.getvalue())
                        temp_path = f.name
                    
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    sample_file = genai.upload_file(path=temp_path)
                    
                    # AIへの指示を厳格化（余計なテンプレを排除）
                    prompt = f"""
                    あなたは介護記録の文字起こしアシスタントです。{user_name}さんの以下の音声を記録として整理してください。
                    
                    【厳守ルール】
                    1. 音声の中で話されている事実のみを、です・ます調の簡潔な文章にしてください。
                    2. 「日時」「記録者」「申し送り記録」といった見出しや、〇月〇日のような空欄テンプレは絶対に含めないでください。
                    3. AIとしての挨拶（承知いたしました等）は一切不要です。
                    4. 音声がない、または不明瞭な場合は、推測せず聞こえた範囲だけで記述してください。
                    """
                    
                    response = model.generate_content([sample_file, prompt])
                    st.session_state["edit_content"] = response.text
                    os.remove(temp_path)
                    msg_placeholder.empty() # メッセージを消去
                    st.rerun() # 画面を更新してテキストエリアに反映
                except Exception as e:
                    st.error(f"❌ AI生成エラー: {e}")

    with col2:
        st.subheader("📝 記録内容の確認")
        # テキストエリア：セッション状態から読み込むことで手動修正が可能
        final_content = st.text_area(
            "修正があればここを書き換えてください", 
            value=st.session_state["edit_content"], 
            height=400, 
            key=f"text_area_{fid}"
        )
        # 手動で書き換えた内容をセッションに同期
        st.session_state["edit_content"] = final_content

        if st.button("💾 クラウド保存"):
            if user_name:
                try:
                    image_url = None
                    if img_file:
                        file_name = f"{uuid.uuid4()}.jpg"
                        supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                        image_url = supabase.storage.from_("case-photos").get_public_url(file_name)
                    
                    record_data = {
                        "user_name": user_name, 
                        "content": st.session_state["edit_content"], 
                        "image_url": image_url, 
                        "created_at": target_date.isoformat()
                    }
                    supabase.table("records").insert(record_data).execute()
                    st.success(f"✅ 保存完了")
                    time.sleep(1.2)
                    # 初期化
                    st.session_state["edit_content"] = ""
                    st.session_state["form_id"] += 1
                    st.rerun()
                except Exception as e: st.error(f"❌ 保存エラー: {e}")
            else: st.warning("利用者名を入力してください")

# ==========================================
# 📊 履歴表示・モニタリング画面
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOPに戻る"):
        st.session_state["page"] = "top"
        st.rerun()
    display_logo()
    st.title("履歴表示・出力")
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3:
        users = get_user_list()
        s_user = st.selectbox("利用者名を選択", ["（未選択）"] + users) if users else st.text_input("名前を入力")
    with c4: s_year = st.selectbox("年", [2025, 2026, 2027], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=now_tokyo.month - 1)
    
    cb1, cb2 = st.columns(2)
    search_clicked = cb1.button("🔍 履歴を検索", use_container_width=True)
    moni_clicked = cb2.button("📈 モニタリング生成(AI)", use_container_width=True)
    
    res_area = st.container()
    
    if search_clicked or moni_clicked:
        if s_user and s_user != "（未選択）":
            msg_p = st.empty()
            loading_text = "🔄 モニタリングを生成しています。しばらくお待ちください..." if moni_clicked else "🔄 検索中。しばらくお待ちください..."
            msg_p.info(loading_text)
            
            try:
                res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                if res.data:
                    df = pd.DataFrame(res.data)
                    df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce').dropna()
                    df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at")
                    
                    msg_p.empty()
                    with res_area:
                        if moni_clicked:
                            if not df_f.empty:
                                st.subheader(f"📋 ケアマネ提出用モニタリング要約 ({s_year}/{s_month})")
                                all_text = "\n".join([f"・{r.created_at.date()}: {r.content}" for _, r in df_f.iterrows()])
                                model = genai.GenerativeModel("gemini-2.5-flash")
                                prompt = f"""
                                熟練の介護職員としてケアマネジャー向けの月間モニタリング報告書を作成してください。
                                1. 200文字程度の要約として、専門用語を用いて事実のみを記述すること。
                                2. 推測や虚偽は含めない。
                                3. 冒頭に「【{s_year}年{s_month}月度 モニタリング要約】」と記載。
                                データ:\n{all_text}
                                """
                                moni_text = model.generate_content(prompt).text
                                st.info(moni_text)
                                st.button("🖨️ レポートを印刷 / PDF保存", on_click=lambda: st.components.v1.html("<script>window.print();</script>", height=0))
                            else: st.warning("対象期間の記録がありません")
                        elif search_clicked:
                            if not df_f.empty:
                                for d in sorted(df_f['created_at'].dt.date.unique(), reverse=True):
                                    with st.expander(f"📅 {d}"):
                                        for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                            st.write(r['content'])
                                            if r.get("image_url"): st.image(r["image_url"], width=250)
                            else: st.info("記録なし")
            except Exception as e:
                msg_p.empty()
                st.error(f"エラー: {e}")