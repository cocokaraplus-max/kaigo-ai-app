import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import date
from supabase import create_client, Client # type: ignore
import uuid
import time

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

# --- 2. 接続設定とUI設定 ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

st.markdown("""
<style>
[data-testid="stHeader"], [data-testid="stToolbar"], footer {display: none !important;}
.block-container {padding-top: 1.5rem !important;}

/* 保存ボタン・検索ボタンの共通スタイル */
div.stButton > button {
    height: 4em !important;
    width: 100% !important;
    border-radius: 12px !important;
    font-weight: bold !important;
    font-size: 1.2rem !important;
    transition: all 0.05s !important;
}

/* 保存ボタン（赤） */
div.stButton > button[key="save_btn"] {
    background-color: #FF4B4B !important;
    color: white !important;
    border: 2px solid #D32F2F !important;
    box-shadow: 0 6px #991B1B !important;
}
div.stButton > button[key="save_btn"]:active {
    background-color: #7F1D1D !important;
    box-shadow: 0 1px #7F1D1D !important;
    transform: translateY(5px) !important;
}

/* 履歴を表示ボタン（青） */
div.stButton > button[key="search_btn"] {
    background-color: #007BFF !important;
    color: white !important;
    border: 2px solid #0056b3 !important;
    box-shadow: 0 6px #004085 !important;
}
div.stButton > button[key="search_btn"]:active {
    background-color: #004085 !important;
    box-shadow: 0 1px #004085 !important;
    transform: translateY(5px) !important;
}
</style>
""", unsafe_allow_html=True)

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("❌ 接続エラーが発生しました")
    st.stop()

# 利用者リストを取得する関数
def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        if res.data:
            users = sorted(list(set([r['user_name'] for r in res.data if r['user_name']])))
            return users
        return []
    except:
        return []

tab1, tab2 = st.tabs(["✍️ ケース記録入力", "📊 履歴閲覧"])

# ==========================================
# タブ1: 入力
# ==========================================
with tab1:
    st.title("📓 ケース記録入力")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if "user_name_val" not in st.session_state:
            st.session_state["user_name_val"] = ""
        
        user_name = st.text_input("利用者名", value=st.session_state["user_name_val"], placeholder="山田 太郎")
        target_date = st.date_input("記録対象日", value=date.today())
        
        st.subheader("📸 写真を追加")
        img_file = st.file_uploader("写真を撮る、または選択", type=['jpg', 'png', 'jpeg'])
        
        if img_file:
            st.image(img_file, caption="撮影・選択済み", width=250)

        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("話してください")
        
        if audio_value:
            if st.button("✨ 声から生成"):
                with st.spinner("AI作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        prompt = f"{user_name}さんの記録を介護申し送り形式で作成してください。"
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        os.remove(temp_path)
                        st.rerun()
                    except:
                        st.error("生成失敗")

    with col2:
        st.subheader("📝 内容の確認・修正")
        status_area_1 = st.empty() 
        final_content = st.text_area("内容の最終確認", value=st.session_state.get("edit_content", ""), height=300)
        
        if st.button("💾 クラウドに保存する", key="save_btn"):
            if user_name:
                status_area_1.warning("⏳ クラウドに保存しています...")
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
                    
                    status_area_1.success(f"✅ 保存完了しました！")
                    time.sleep(1.5)
                    st.session_state["edit_content"] = ""
                    st.session_state["user_name_val"] = ""
                    st.rerun()
                except Exception as e:
                    status_area_1.error(f"❌ 保存失敗 ({e})")
            else:
                st.warning("利用者名を入力してください")

# ==========================================
# タブ2: 履歴閲覧
# ==========================================
with tab2:
    st.title("📊 履歴表示")
    
    # 検索条件エリア
    c3, c4, c5 = st.columns([2, 1, 1])
    
    with c3:
        # 登録済みの名前をプルダウンで表示
        registered_users = get_user_list()
        if registered_users:
            s_user = st.selectbox("利用者名を選択", ["（未選択）"] + registered_users)
        else:
            s_user = st.text_input("利用者名を入力（まだデータがありません）")
            
    with c4: s_year = st.selectbox("年", [2025, 2026, 2027], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=date.today().month - 1)
    
    status_area_2 = st.empty() # 検索メッセージ用
    
    if st.button("🔍 履歴を表示", key="search_btn"):
        if s_user == "（未選択）" or not s_user:
            st.warning("利用者を選択してください")
        else:
            status_area_2.info(f"🔍 {s_user}様の履歴を検索しています...")
            try:
                res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                if res.data:
                    df = pd.DataFrame(res.data)
                    df['created_at'] = pd.to_datetime(df['created_at'])
                    df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at", ascending=False)
                    
                    if not df_f.empty:
                        status_area_2.success(f"✅ {len(df_f)}件の記録が見つかりました")
                        for d in df_f['created_at'].dt.date.unique():
                            with st.expander(f"📅 {d.strftime('%Y年%m月%d日')}"):
                                for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                    st.write(r['content'])
                                    if r.get("image_url"): st.image(r["image_url"], width=300)
                    else:
                        status_area_2.warning("該当する期間の記録はありませんでした。")
                else:
                    status_area_2.warning("記録が見つかりませんでした。")
            except Exception as e:
                status_area_2.error(f"検索エラーが発生しました: {e}")