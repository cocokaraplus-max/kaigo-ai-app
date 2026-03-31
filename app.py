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
# アプリ名を「TASUKARU」に設定
st.set_page_config(page_title="TASUKARU ケース記録", page_icon="🦝", layout="wide")

# 外部のデザインファイル(style.css)を読み込む関数
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
    st.info("StreamlitのSecrets（SUPABASE_KEY等）を再確認してください。")
    st.stop()

# 利用者リスト取得（履歴検索用）
def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        if res.data:
            return sorted(list(set([r['user_name'] for r in res.data if r['user_name']])))
        return []
    except Exception:
        return []

# ロゴ画像を表示する関数
def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        st.image(image)
        if show_line:
            # TOP画面のみロゴの下にゴールドのアクセントラインを表示
            st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except FileNotFoundError:
        st.title("🦝 TASUKARU")

# セッション状態の管理
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
                with st.spinner("文章を作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.getvalue())
                            temp_path = f.name
                            
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        
                        prompt = f"""
                        あなたはプロの介護職員です。{user_name}さんの以下の音声を、他の職員への正確な「申し送り記録」としてまとめてください。
                        
                        【ルール】
                        1. 職員間の連絡に適した、丁寧かつ簡潔な口調（です・ます調）にすること。
                        2. 音声の内容を忠実に再現し、虚偽や過度な脚色は一切行わないこと。
                        3. 「はい、承知いたしました」などの不要な返事は含めないこと。
                        """
                        
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        st.session_state[f"t_{fid}"] = response.text
                        os.remove(temp_path)
                    except Exception as e:
                        st.error(f"❌ AI生成エラー: {e}")

    with col2:
        st.subheader("📝 記録内容の確認")
        final_content = st.text_area("修正があればここを書き換えてください", value=st.session_state["edit_content"], height=350, key=f"t_{fid}")
        btn_save = st.button("💾 クラウド保存")

    # 保存処理
    if btn_save:
        if user_name:
            st.info("⏳ クラウドへ保存中...")
            try:
                image_url = None
                if img_file:
                    file_name = f"{uuid.uuid4()}.jpg"
                    supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                    image_url = supabase.storage.from_("case-photos").get_public_url(file_name)

                record_data = {
                    "user_name": user_name,
                    "content": final_content if final_content else "（写真保存）",
                    "image_url": image_url, 
                    "created_at": target_date.isoformat()
                }
                supabase.table("records").insert(record_data).execute()
                st.success(f"✅ 【{user_name}様】の記録を保存しました")
                time.sleep(1.5)
                st.session_state["edit_content"] = ""
                st.session_state["form_id"] += 1
                st.rerun()
            except Exception as e:
                st.error(f"❌ 保存エラー: {e}")
        else:
            st.warning("⚠️ 利用者名を入力してください")

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
    with cb1: search_btn = st.button("🔍 履歴を検索", use_container_width=True)
    with cb2: moni_btn = st.button("📈 モニタリング生成(AI)", use_container_width=True)
    
    res_area = st.container()

    if search_btn or moni_btn:
        if s_user and s_user != "（未選択）":
            with st.spinner("データ取得中..."):
                try:
                    res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce').dropna()
                        df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at")

                        with res_area:
                            if moni_btn:
                                st.subheader(f"📋 {s_user}様 {s_year}年{s_month}月 モニタリング要約")
                                if not df_f.empty:
                                    all_text = "\n".join([f"【{r.created_at.date()}】: {r.content}" for _, r in df_f.iterrows()])
                                    model = genai.GenerativeModel("gemini-2.5-flash")
                                    prompt = f"{s_user}さんの1ヶ月分の介護記録に基づき、月末に提出する専門的な「モニタリング報告書」を作成してください。虚偽を含めず、事実に基づいた変化をプロの口調で記述してください。\n\nデータ:\n{all_text}"
                                    moni_text = model.generate_content(prompt).text
                                    st.info(moni_text)
                                    # 印刷/PDF保存ボタン
                                    st.button("🖨️ レポートを印刷 / PDF保存", on_click=lambda: st.components.v1.html("<script>window.print();</script>", height=0))
                                else:
                                    st.warning("対象期間の記録がありません")
                            
                            elif search_btn:
                                if not df_f.empty:
                                    for d in sorted(df_f['created_at'].dt.date.unique(), reverse=True):
                                        with st.expander(f"📅 {d}"):
                                            for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                                st.write(r['content'])
                                                if r.get("image_url"): st.image(r["image_url"], width=250)
                                else:
                                    st.info("記録なし")
                    else:
                        st.info("データが見つかりませんでした。")
                except Exception as e:
                    st.error(f"検索エラー: {e}")
        else:
            st.warning("⚠️ 利用者名を選択してください")