import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import date
from supabase import create_client, Client # type: ignore
import uuid

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

# --- 2. 接続設定とUI非表示設定 ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

hide_streamlit_style = """
<style>
[data-testid="stHeader"] {display: none !important;}
[data-testid="stToolbar"] {display: none !important;}
footer {visibility: hidden !important;}
.block-container {padding-top: 2rem !important;}
/* ボタンを大きく押しやすく調整 */
.stButton > button {width: 100% !important; border-radius: 10px !important; height: 3em !important;}
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
# タブ1: ケース記録入力 (写真・音声対応)
# ==========================================
with tab1:
    st.title("📓 ケース記録入力")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if "user_name_val" not in st.session_state:
            st.session_state["user_name_val"] = ""
        
        user_name = st.text_input("利用者名", value=st.session_state["user_name_val"], placeholder="例：山田 太郎")
        target_date = st.date_input("記録対象日", value=date.today())
        
        # --- 写真撮影/アップロード機能 ---
        st.subheader("📸 写真を追加")
        use_camera = st.checkbox("カメラを起動する")
        if use_camera:
            img_file = st.camera_input("シャッターを押してください")
        else:
            img_file = st.file_uploader("画像を選択（またはライブラリから）", type=['jpg', 'png', 'jpeg'])
        
        if img_file:
            st.image(img_file, caption="プレビュー", width=300)

        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("マイクをタップして話してください")
        
        if audio_value:
            if st.button("✨ 音声から文章を生成"):
                with st.spinner("AIが文章を作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        
                        prompt = f"{target_date.strftime('%Y/%m/%d')}の{user_name}さんの介護記録を、プロフェッショナルかつ温かみのある申し送り口調で簡潔に作成してください。"
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        os.remove(temp_path)
                        st.rerun()
                    except Exception as e:
                        st.error("AI文章生成に失敗しました。")

    with col2:
        st.subheader("📝 内容の確認・修正")
        final_content = st.text_area("AIが作成した内容（修正も可能です）", value=st.session_state.get("edit_content", ""), height=300)
        
        if st.button("💾 クラウドに保存する", type="primary"):
            if user_name and (final_content or img_file):
                try:
                    image_url = None
                    # 画像のアップロード処理
                    if img_file:
                        file_ext = "jpg"
                        file_name = f"{uuid.uuid4()}.{file_ext}"
                        supabase.storage.from_("case-photos").upload(file_name, img_file.getvalue())
                        image_url = supabase.storage.from_("case-photos").get_public_url(file_name)

                    # データベースへの保存
                    record_data = {
                        "user_name": user_name,
                        "content": final_content,
                        "image_url": image_url, 
                        "created_at": target_date.isoformat()
                    }
                    supabase.table("records").insert(record_data).execute()
                    st.success("✅ 正常に保存されました！")
                    
                    # 入力欄のクリア
                    st.session_state["edit_content"] = ""
                    st.session_state["user_name_val"] = ""
                    st.rerun()
                except Exception as e:
                    st.error(f"保存エラーが発生しました: {e}")
            else:
                st.warning("「利用者名」と「内容」または「写真」が必要です。")

# ==========================================
# タブ2: 履歴閲覧 (写真表示対応)
# ==========================================
with tab2:
    st.title("📊 履歴・レポート生成")
    col3, col4, col5 = st.columns([2, 1, 1])
    with col3: search_user = st.text_input("検索する利用者名（空欄で全員）")
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
                        with st.expander(f"📅 {d.strftime('%Y年%m月%d日')} の記録"):
                            day_recs = df_filtered[df_filtered['created_at'].dt.date == d]
                            for _, row in day_recs.iterrows():
                                st.write(f"**【{row['user_name']}様】**")
                                st.write(row['content'])
                                if row.get("image_url"):
                                    st.image(row["image_url"], caption="現場写真", width=400)
                                st.divider()
                else:
                    st.info("該当する期間の記録はありません。")
            else:
                st.info("データが登録されていません。")
        except Exception as e:
            st.error(f"データ取得エラー: {e}")