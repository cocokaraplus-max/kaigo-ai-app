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

# --- 2. 究極のUIカスタマイズ（フロートボタン実装） ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

st.markdown("""
<style>
/* Streamlitパーツ非表示 */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stAppDeployButton"],
footer, #MainMenu, header { display: none !important; visibility: hidden !important; }

/* 画面下の余白（キーボード対策） */
.main .block-container {
    padding-bottom: 300px !important;
}

/* ★ 追いかけてくる「保存ボタン」の魔法 ★ */
div.stButton > button[key="save_btn"] {
    position: fixed !important;
    bottom: 30px !important;   /* 画面下から30px */
    right: 20px !important;    /* 画面右から20px */
    width: 150px !important;   /* 押しやすい幅 */
    height: 70px !important;   /* 押しやすい高さ */
    z-index: 999999 !important; /* 他のパーツより一番上に表示 */
    background-color: #FF4B4B !important;
    color: white !important;
    border-radius: 35px !important; /* 丸みを持たせて「浮いてる感」を出す */
    font-size: 1.1rem !important;
    font-weight: bold !important;
    box-shadow: 0 8px 16px rgba(0,0,0,0.3) !important; /* 影を付けて浮かす */
    border: 2px solid white !important;
    transition: all 0.1s !important;
}

/* ボタンを押した時の反応 */
div.stButton > button[key="save_btn"]:active {
    transform: scale(0.9) !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2) !important;
}
</style>
""", unsafe_allow_html=True)

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("❌ 接続エラー")
    st.stop()

def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        return sorted(list(set([r['user_name'] for r in res.data if r['user_name']]))) if res.data else []
    except: return []

if "form_id" not in st.session_state: st.session_state["form_id"] = 0
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""

tab1, tab2 = st.tabs(["✍️ ケース記録入力", "📊 履歴閲覧"])

# ==========================================
# タブ1: 入力（フロートボタンで快適操作）
# ==========================================
with tab1:
    st.title("📓 ケース記録入力")
    
    # 状態表示エリア（ここを上に置くことで保存中かどうかわかるようにします）
    status_area = st.empty()
    fid = st.session_state["form_id"]

    # 💡 右下に常に浮いている「保存ボタン」
    if st.button("💾 クラウド保存", key="save_btn"):
        st.session_state["do_save"] = True
    else:
        st.session_state["do_save"] = False

    col1, col2 = st.columns([1, 1])
    with col1:
        user_name = st.text_input("利用者名", placeholder="山田 太郎", key=f"user_{fid}")
        target_date = st.date_input("記録対象日", value=now_tokyo.date(), key=f"date_{fid}")
        
        st.subheader("📸 写真を追加")
        img_file = st.file_uploader("写真を選択", type=['jpg', 'png', 'jpeg'], key=f"img_{fid}")
        if img_file: st.image(img_file, width=200)

        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("マイクをタップ", key=f"audio_{fid}")
        
        if audio_value:
            if st.button("✨ 声から生成", key=f"gen_{fid}"):
                with st.spinner("AI作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        prompt = f"{user_name}さんの記録を簡潔に作成してください。"
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        os.remove(temp_path)
                        st.rerun()
                    except: st.error("生成失敗")

    with col2:
        st.subheader("📝 内容の確認・修正")
        final_content = st.text_area("修正があれば書き換えてください", value=st.session_state["edit_content"], height=300, key=f"text_{fid}")

    # 保存処理（浮いているボタンが押されたとき）
    if st.session_state.get("do_save"):
        if user_name:
            status_area.warning("⏳ クラウドへ保存中...")
            try:
                image_url = None
                if img_file:
                    file_ext = "jpg"
                    file_name = f"{uuid.uuid4()}.{file_ext}"
                    supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                    image_url = supabase.storage.from_("case-photos").get_public_url(file_name)

                record_data = {
                    "user_name": user_name,
                    "content": final_content if final_content else "（画像のみ保存）",
                    "image_url": image_url, 
                    "created_at": target_date.isoformat()
                }
                supabase.table("records").insert(record_data).execute()
                
                status_area.success(f"✅ 保存が完了しました！")
                time.sleep(1.5)
                
                # 完全リセット
                st.session_state["edit_content"] = ""
                st.session_state["form_id"] += 1
                st.rerun()
            except Exception as e:
                status_area.error(f"❌ エラー: {e}")
        else:
            status_area.error("利用者名を入力してください")

# ==========================================
# タブ2: 履歴閲覧
# ==========================================
with tab2:
    st.title("📊 履歴表示")
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3:
        user_list = get_user_list()
        s_user = st.selectbox("利用者名を選択", ["（未選択）"] + user_list) if user_list else st.text_input("利用者名を入力")
    with c4: s_year = st.selectbox("年", [2025, 2026, 2027], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=now_tokyo.month - 1)
    
    if st.button("🔍 履歴を表示", key="search_btn"):
        if s_user and s_user != "（未選択）":
            with st.spinner("検索中..."):
                try:
                    res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')
                        df = df.dropna(subset=['created_at'])
                        df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at", ascending=False)
                        for d in df_f['created_at'].dt.date.unique():
                            with st.expander(f"📅 {d}"):
                                for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                    st.write(r['content'])
                                    if r.get("image_url"): st.image(r["image_url"], width=250)
                except: st.error("検索エラー")