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

# CSSでボタンの色と挙動、英語排除を強制指定
st.markdown("""
<style>
/* ヘッダー・ツールバー非表示 */
[data-testid="stHeader"], [data-testid="stToolbar"], footer {display: none !important;}
.block-container {padding-top: 1.5rem !important;}

/* --- 保存ボタン（赤）のスタイル強化 --- */
div.stButton > button:first-child {
    background-color: #FF4B4B !important;
    color: white !important;
    height: 4.5em !important;
    width: 100% !important;
    border-radius: 12px !important;
    font-weight: bold !important;
    font-size: 1.3rem !important;
    border: 2px solid #D32F2F !important;
    box-shadow: 0 4px #991B1B !important;
    transition: all 0.1s !important;
}
/* ボタンを押した時の「カチッ」とした反応 */
div.stButton > button:first-child:active {
    background-color: #991B1B !important;
    box-shadow: 0 0px #991B1B !important;
    transform: translateY(4px) !important;
}

/* --- 英語表記の徹底排除（カメラ・ファイル選択） --- */
/* Drag and drop を消す */
[data-testid="stFileUploadDropzone"] div div span {display:none !important;}
[data-testid="stFileUploadDropzone"]::before {
    content: "📷 ここをタップして写真を選択してください";
    font-weight: bold;
    color: #444;
    display: block;
    text-align: center;
    padding: 10px;
}
/* Browse files ボタンを日本語化 */
[data-testid="stFileUploadDropzone"] button {font-size: 0 !important;}
[data-testid="stFileUploadDropzone"] button::after {
    content: "ファイルを選ぶ";
    font-size: 1rem !important;
    visibility: visible;
}
/* カメラ入力の英語（Take Photo）を隠す */
[data-testid="stCameraInput"] button {font-size: 0 !important;}
[data-testid="stCameraInput"] button::after {
    content: "📸 シャッターを切る";
    font-size: 1.2rem !important;
    visibility: visible;
}
</style>
""", unsafe_allow_html=True)

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("❌ 接続エラー")
    st.stop()

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
        use_camera = st.checkbox("カメラを使用する")
        if use_camera:
            img_file = st.camera_input("撮影", label_visibility="collapsed")
        else:
            img_file = st.file_uploader("写真を選択", type=['jpg', 'png', 'jpeg'], label_visibility="collapsed")
        
        if img_file:
            st.image(img_file, caption="準備完了", width=250)

        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("マイクをタップして話してください")
        
        if audio_value:
            if st.button("✨ 声から記録を自動生成"):
                with st.spinner("AIが文章を作成しています..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        prompt = f"{user_name}さんの記録を簡潔な申し送り口調で作成してください。"
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        os.remove(temp_path)
                        st.rerun()
                    except:
                        st.error("生成に失敗しました。もう一度話してください。")

    with col2:
        st.subheader("📝 内容の確認・修正")
        # 状態表示用のエリアを上部に固定
        status_area = st.empty()
        
        final_content = st.text_area("修正があれば書き換えてください", value=st.session_state.get("edit_content", ""), height=300)
        
        # --- 保存ボタンの実行 ---
        if st.button("💾 クラウドに保存する"):
            if user_name:
                # 視覚的フィードバック開始
                status_area.warning("⏳ 保存中... 指を離してお待ちください")
                
                try:
                    image_url = None
                    if img_file:
                        file_ext = "jpg"
                        file_name = f"{uuid.uuid4()}.{file_ext}"
                        supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                        image_url = supabase.storage.from_("case-photos").get_public_url(file_name)

                    record_data = {
                        "user_name": user_name,
                        "content": final_content if final_content else "（写真のみ）",
                        "image_url": image_url, 
                        "created_at": target_date.isoformat()
                    }
                    supabase.table("records").insert(record_data).execute()
                    
                    # 成功メッセージ
                    status_area.success(f"✅ 【{user_name}様】の記録を「保存完了」しました！")
                    time.sleep(2.0)
                    
                    # 画面リセット
                    st.session_state["edit_content"] = ""
                    st.session_state["user_name_val"] = ""
                    st.rerun()
                    
                except Exception as e:
                    status_area.error(f"❌ 保存できませんでした！通信状況を確認してください。({e})")
            else:
                st.warning("「利用者名」が空欄です。入力してください。")

# ==========================================
# タブ2: 履歴閲覧
# ==========================================
with tab2:
    st.title("📊 履歴表示")
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3: s_user = st.text_input("検索する利用者名")
    with c4: s_year = st.selectbox("年", [2025, 2026, 2027], index=1)
    with c5: s_month = st.selectbox("月", range(1, 13), index=date.today().month - 1)
    
    if st.button("🔍 履歴を表示"):
        try:
            res = supabase.table("records").select("*").eq("user_name", s_user).execute()
            if res.data:
                df = pd.DataFrame(res.data)
                df['created_at'] = pd.to_datetime(df['created_at'])
                df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at", ascending=False)
                if not df_f.empty:
                    for d in df_f['created_at'].dt.date.unique():
                        with st.expander(f"📅 {d}"):
                            for _, r in df_f[df_f['created_at'].dt.date == d].iterrows():
                                st.write(r['content'])
                                if r.get("image_url"): st.image(r["image_url"], width=300)
                else:
                    st.info("該当月の記録はありません。")
        except:
            st.error("データの取得に失敗しました。")