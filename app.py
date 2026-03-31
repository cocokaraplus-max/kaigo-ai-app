import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, date
import pytz 
from supabase import create_client, Client # type: ignore
import uuid
import time

# 日本時間を定義
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)

# --- 1. パスワード認証 ---
PASSWORD = "admin"  
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.title("🔐 ログイン")
        pwd = st.text_input("パスワードを入力", type="password")
        if st.button("ログイン"):
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("パスワードが正しくありません")
        return False
    return True

if not check_password():
    st.stop()

# --- 2. UI非表示設定 ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

st.markdown("""
<style>
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stAppDeployButton"],
footer, #MainMenu, header { display: none !important; visibility: hidden !important; }
.block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
div.stButton > button { height: 4em !important; width: 100% !important; border-radius: 12px !important; font-weight: bold !important; font-size: 1.2rem !important; }
div.stButton > button[key="save_btn"] { background-color: #FF4B4B !important; color: white !important; border: 2px solid #D32F2F !important; box-shadow: 0 4px #991B1B !important; }
div.stButton > button[key="save_btn"]:active { background-color: #7F1D1D !important; box-shadow: 0 0px !important; transform: translateY(4px) !important; }
</style>
""", unsafe_allow_html=True)

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("❌ 接続エラー")
    st.stop()

# 利用者リスト取得（エラー回避処理付き）
def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        if res.data:
            return sorted(list(set([r['user_name'] for r in res.data if r['user_name']])))
        return []
    except:
        return []

tab1, tab2 = st.tabs(["✍️ ケース記録入力", "📊 履歴閲覧"])

# ==========================================
# タブ1: 入力（リセット機能を強化）
# ==========================================
with tab1:
    st.title("📓 ケース記録入力")
    col1, col2 = st.columns([1, 1])
    
    # セッション状態の初期化
    if "input_user_name" not in st.session_state: st.session_state["input_user_name"] = ""
    if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""

    with col1:
        # valueにセッション状態を紐付け
        user_name = st.text_input("利用者名", value=st.session_state["input_user_name"], placeholder="山田 太郎")
        target_date = st.date_input("記録対象日", value=now_tokyo.date())
        
        st.subheader("📸 写真を追加")
        img_file = st.file_uploader("写真を選択/撮影", type=['jpg', 'png', 'jpeg'], label_visibility="collapsed")
        if img_file: st.image(img_file, width=250)

        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("マイクをタップ")
        
        if audio_value:
            if st.button("✨ 声から生成"):
                with st.spinner("AI作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        prompt = f"{user_name}さんの記録を介護申し送り形式で簡潔に作成してください。"
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        st.session_state["input_user_name"] = user_name # 名前を保持
                        os.remove(temp_path)
                        st.rerun()
                    except: st.error("生成失敗")

    with col2:
        st.subheader("📝 内容の確認・修正")
        status_area = st.empty()
        
        final_content = st.text_area("内容を確認してください", value=st.session_state["edit_content"], height=300)
        
        if st.button("💾 クラウドに保存する", key="save_btn"):
            if user_name:
                status_area.warning("⏳ 保存中...")
                try:
                    image_url = None
                    if img_file:
                        file_ext = "jpg"
                        file_name = f"{uuid.uuid4()}.{file_ext}"
                        supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                        image_url = supabase.storage.from_("case-photos").get_public_url(file_name)

                    record_data = {
                        "user_name": user_name,
                        "content": final_content if final_content else "（写真保存）",
                        "image_url": image_url, 
                        "created_at": target_date.isoformat()
                    }
                    supabase.table("records").insert(record_data).execute()
                    
                    status_area.success(f"✅ 保存完了！")
                    time.sleep(1.5)
                    
                    # --- 完全リセット処理 ---
                    st.session_state["edit_content"] = ""
                    st.session_state["input_user_name"] = ""
                    st.rerun()
                    
                except Exception as e:
                    status_area.error(f"❌ 保存失敗: {e}")
            else:
                st.warning("利用者名を入力してください")

# ==========================================
# タブ2: 履歴閲覧（エラー回避強化版）
# ==========================================
with tab2:
    st.title("📊 履歴表示")
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3:
        registered_users = get_user_list()
        s_user = st.selectbox("利用者名を選択", ["（未選択）"] + registered_users) if registered_users else st.text_input("利用者名を入力")
    with c4: s_year = st.selectbox("年", [2025, 2026, 2027], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=now_tokyo.month - 1)
    
    if st.button("🔍 履歴を表示", key="search_btn"):
        if s_user and s_user != "（未選択）":
            with st.spinner("検索中..."):
                try:
                    res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                    if res.data and len(res.data) > 0:
                        df = pd.DataFrame(res.data)
                        df['created_at'] = pd.to_datetime(df['created_at'])
                        # フィルタリング
                        df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)]
                        
                        if not df_f.empty:
                            df_f = df_f.sort_values("created_at", ascending=False)
                            for d in df_f['created_at'].dt.date.unique():
                                with st.expander(f"📅 {d}"):
                                    day_recs = df_f[df_f['created_at'].dt.date == d]
                                    for _, r in day_recs.iterrows():
                                        st.write(r['content'])
                                        if r.get("image_url"): st.image(r["image_url"], width=300)
                        else:
                            st.info(f"{s_year}年{s_month}月の記録はありません。")
                    else:
                        st.info("この利用者様の記録はまだ登録されていません。")
                except Exception as e:
                    st.error("検索中にエラーが発生しました。")
        else:
            st.warning("利用者名を選択してください。")