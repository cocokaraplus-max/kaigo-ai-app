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

# --- 2. 接続設定とUI日本語化設定 ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

hide_streamlit_style = """
<style>
[data-testid="stHeader"] {display: none !important;}
[data-testid="stToolbar"] {display: none !important;}
footer {visibility: hidden !important;}
.block-container {padding-top: 2rem !important;}

/* 画像アップローダーの日本語化（強制書き換え） */
[data-testid="stFileUploadDropzone"] section > button::after {
    content: "ファイルを選択";
    display: block;
    position: absolute;
}
[data-testid="stFileUploadDropzone"] section > button span {
    display: none;
}
[data-testid="stFileUploadDropzone"] section > label::after {
    content: "写真をここにドラッグするか、上のボタンを押してください";
    display: block;
    font-size: 0.8em;
}
[data-testid="stFileUploadDropzone"] section > label {
    font-size: 0 !important;
}

/* ボタンのデザイン：押し心地を強調 */
.stButton > button {
    width: 100% !important; 
    border-radius: 12px !important; 
    height: 4em !important; 
    font-weight: bold !important;
    font-size: 1.1rem !important;
    background-color: #FF4B4B;
    color: white;
    border: none;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    transition: all 0.2s ease;
}
/* 押した時の色の変化 */
.stButton > button:active {
    transform: translateY(2px);
    box-shadow: 0 2px 3px rgba(0,0,0,0.2);
    background-color: #D32F2F !important;
}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("❌ 接続エラー：Secretsを確認してください")
    st.stop()

# --- 3. メイン画面のタブ構成 ---
tab1, tab2 = st.tabs(["✍️ ケース記録入力", "📊 履歴閲覧・モニタリング"])

# ==========================================
# タブ1: ケース記録入力
# ==========================================
with tab1:
    st.title("📓 ケース記録入力")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if "user_name_val" not in st.session_state:
            st.session_state["user_name_val"] = ""
        
        user_name = st.text_input("利用者名", value=st.session_state["user_name_val"], placeholder="例：山田 太郎")
        target_date = st.date_input("記録対象日", value=date.today())
        
        st.subheader("📸 写真を追加")
        use_camera = st.checkbox("カメラを起動して撮影する")
        if use_camera:
            img_file = st.camera_input("撮影ボタンを押してください")
        else:
            img_file = st.file_uploader("写真を選択", type=['jpg', 'png', 'jpeg'])
        
        if img_file:
            st.image(img_file, caption="選択された画像", width=300)

        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("マイクをタップして話してください")
        
        if audio_value:
            if st.button("✨ 声から記録を作る"):
                with st.spinner("AIが文章を作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        
                        prompt = f"{target_date.strftime('%Y/%m/%d')}の{user_name}さんの介護記録を簡潔に作成してください。"
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        os.remove(temp_path)
                        st.rerun()
                    except Exception as e:
                        st.error("AI文章生成に失敗しました。")

    with col2:
        st.subheader("📝 内容の確認・修正")
        final_content = st.text_area("AIが作成した内容", value=st.session_state.get("edit_content", ""), height=300)
        
        # --- 保存ボタンのロジック強化 ---
        if st.button("💾 クラウドに保存する", type="primary"):
            if user_name:
                # 処理中のメッセージ
                with st.status("☁️ クラウドへ保存を開始します...", expanded=False) as status:
                    try:
                        image_url = None
                        if img_file:
                            status.update(label="📸 写真をアップロード中...", state="running")
                            file_ext = "jpg"
                            file_name = f"{uuid.uuid4()}.{file_ext}"
                            supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                            image_url = supabase.storage.from_("case-photos").get_public_url(file_name)

                        status.update(label="📝 データベースに書き込み中...", state="running")
                        record_data = {
                            "user_name": user_name,
                            "content": final_content if final_content else "（写真のみ保存）",
                            "image_url": image_url, 
                            "created_at": target_date.isoformat()
                        }
                        supabase.table("records").insert(record_data).execute()
                        
                        # 成功時の表示
                        status.update(label="✅ 保存が完了しました！", state="complete")
                        st.success(f"【{user_name}様】の記録を正常に保存しました。")
                        
                        # 1.2秒待ってからリセット（成功を確認させるため）
                        time.sleep(1.2)
                        st.session_state["edit_content"] = ""
                        st.session_state["user_name_val"] = ""
                        st.rerun()
                        
                    except Exception as e:
                        # 失敗時の表示
                        status.update(label="❌ 保存できませんでした", state="error")
                        st.error(f"保存エラーが発生しました。時間を置いて再度お試しください。")
                        st.info(f"詳細: {e}")
            else:
                st.warning("「利用者名」を入力してください。")

# ==========================================
# タブ2: 履歴閲覧
# ==========================================
with tab2:
    st.title("📊 履歴・レポート生成")
    col3, col4, col5 = st.columns([2, 1, 1])
    with col3: search_user = st.text_input("検索する利用者名")
    with col4: search_year = st.selectbox("対象年", range(2025, 2028), index=1)
    with col5: search_month = st.selectbox("対象月", range(1, 13), index=date.today().month - 1)
    
    if st.button("🔍 履歴を表示"):
        try:
            query = supabase.table("records").select("*")
            if search_user:
                query = query.eq("user_name", search_user)
            
            res = query.execute()
            if res.data:
                df = pd.DataFrame(res.data)
                df['created_at'] = pd.to_datetime(df['created_at'])
                df_filtered = df[(df['created_at'].dt.year == search_year) & (df['created_at'].dt.month == search_month)].sort_values("created_at", ascending=False)

                if not df_filtered.empty:
                    for d in df_filtered['created_at'].dt.date.unique():
                        with st.expander(f"📅 {d.strftime('%Y年%m月%d日')}"):
                            day_recs = df_filtered[df_filtered['created_at'].dt.date == d]
                            for _, row in day_recs.iterrows():
                                st.write(f"**【{row['user_name']}様】**")
                                st.write(row['content'])
                                if "image_url" in row and row["image_url"]:
                                    st.image(row["image_url"], width=400)
                                st.divider()
                else:
                    st.info("該当する期間の記録はありません。")
        except Exception as e:
            st.error(f"データ表示エラー: {e}")