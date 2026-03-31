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

# 日本時間の設定
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)

# --- 1. 接続設定とUIカスタム ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

st.markdown("""
<style>
/* 共通：Streamlitパーツ非表示 */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stAppDeployButton"],
footer, #MainMenu, header { display: none !important; visibility: hidden !important; }

/* メッセージ（Status/Success/Error）を画面最上部に固定 */
[data-testid="stNotification"] {
    position: fixed !important;
    top: 10px !important;
    left: 5% !important;
    right: 5% !important;
    width: 90% !important;
    z-index: 1000000 !important;
    box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
    border-radius: 10px !important;
}

/* TOP画面のメニューボタン */
div.stButton > button.top-menu-btn {
    height: 8em !important;
    font-size: 1.5rem !important;
    border-radius: 20px !important;
    background-color: #f0f2f6 !important;
    color: #31333F !important;
    border: 2px solid #d1d5db !important;
}

/* スマホ用：保存ボタンを右下固定 */
@media (max-width: 768px) {
    div.stButton > button:has(div p:contains("クラウド保存")) {
        position: fixed !important;
        bottom: 30px !important;
        right: 20px !important;
        width: 150px !important;
        height: 70px !important;
        border-radius: 35px !important;
        z-index: 999999 !important;
        background-color: #FF4B4B !important;
        color: white !important;
        border: 2px solid white !important;
        box-shadow: 0 10px 25px rgba(0,0,0,0.4) !important;
    }
}
</style>
""", unsafe_allow_html=True)

# Supabase & Gemini 接続
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("❌ 接続エラー：APIキーを確認してください")
    st.stop()

# 利用者リスト取得
def get_user_list():
    try:
        res = supabase.table("records").select("user_name").execute()
        return sorted(list(set([r['user_name'] for r in res.data if r['user_name']]))) if res.data else []
    except: return []

# セッション状態
if "page" not in st.session_state: st.session_state["page"] = "top"
if "form_id" not in st.session_state: st.session_state["form_id"] = 0
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""

# ==========================================
# 🏠 TOP画面
# ==========================================
if st.session_state["page"] == "top":
    st.title("📓 AIケース記録システム")
    st.subheader("メニューを選択してください")
    st.write("---")
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        if st.button("✍️ 今日の記録を書く\n(音声・写真対応)", use_container_width=True):
            st.session_state["page"] = "input"
            st.rerun()
            
    with col_t2:
        if st.button("📊 過去の履歴を見る\n(検索・閲覧)", use_container_width=True):
            st.session_state["page"] = "history"
            st.rerun()

# ==========================================
# ✍️ 入力画面
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOPに戻る"):
        st.session_state["page"] = "top"
        st.rerun()

    st.title("✍️ ケース記録入力")
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
                        # 1. 確実なアップロード方式を使用（getvalueでデータ欠落を防ぐ）
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.getvalue())
                            temp_path = f.name
                            
                        # 2. AIモデルに送信
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        prompt = f"{user_name}さんの介護記録を簡潔に作成してください。"
                        
                        response = model.generate_content([sample_file, prompt])
                        
                        # 3. Streamlitの仕様対策：テキストエリアの「キー(ID)」に直接流し込む！
                        st.session_state["edit_content"] = response.text
                        st.session_state[f"t_{fid}"] = response.text
                        
                        # 後片付け
                        os.remove(temp_path)
                        
                    except Exception as e:
                        st.error(f"❌ AI生成エラー: {e}")

    with col2:
        st.subheader("📝 記録内容の確認")
        final_content = st.text_area("修正があればここを書き換えてください", value=st.session_state["edit_content"], height=300, key=f"t_{fid}")
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
                
                st.success(f"✅ 【{user_name}様】の記録を正常に保存しました！")
                time.sleep(1.8)
                
                # 完全リセット
                st.session_state["edit_content"] = ""
                st.session_state["form_id"] += 1
                st.rerun()
            except Exception as e:
                st.error(f"❌ 保存に失敗しました: {e}")
        else:
            st.warning("⚠️ 利用者名を入力してください")

# ==========================================
# 📊 履歴表示画面
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOPに戻る"):
        st.session_state["page"] = "top"
        st.rerun()

    st.title("📊 履歴表示")
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3:
        users = get_user_list()
        s_user = st.selectbox("利用者名を選択", ["（未選択）"] + users) if users else st.text_input("名前を入力")
    with c4: s_year = st.selectbox("年", [2025, 2026, 2027], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=now_tokyo.month - 1)
    
    if st.button("🔍 検索開始"):
        if s_user and s_user != "（未選択）":
            with st.spinner("検索中..."):
                try:
                    res = supabase.table("records").select("*").eq("user_name", s_user).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce').dropna()
                        df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at", ascending=False)
                        if not df_f.empty:
                            for d in df_f['created_at'].dt.date.unique():
                                with st.expander(f"📅 {d}"):
                                    for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                        st.write(r['content'])
                                        if r.get("image_url"): st.image(r["image_url"], width=300)
                        else: st.info("記録なし")
                except: st.error("検索エラー")