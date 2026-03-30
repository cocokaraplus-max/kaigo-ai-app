import streamlit as st
import google.generativeai as genai
import tempfile
import os
from datetime import datetime

# Pylanceのエラーを回避しつつ読み込む設定
try:
    from supabase import create_client, Client
except ImportError:
    pass

# --- 1. セキュリティ（パスワード） ---
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
                st.error("不一致")
        return False
    return True

if not check_password():
    st.stop()

# --- 2. 接続設定（Secretsから取得） ---
st.set_page_config(page_title="AIモニタリング", page_icon="📝")

try:
    # 以前共有いただいたキーを使用
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    st.sidebar.success("✅ 接続完了")
except Exception as e:
    st.sidebar.error("❌ Secretsの設定を確認してください")
    st.stop()

# --- 3. メイン機能 ---
st.title("📋 ケアマネ報告作成AI")

user_name = st.text_input("利用者名", placeholder="例：山田 太郎")

col1, col2 = st.columns(2)
with col1:
    meal = st.selectbox("食事", ["完食", "半分程度", "欠食"])
with col2:
    activity = st.selectbox("活動", ["元気に参加", "見学", "傾眠"])

# 音声入力（録音）
st.subheader("🎙️ 音声で様子を話す")
audio_value = st.audio_input("マイクをタップして録音")

# AI生成
if audio_value:
    if st.button("AI文章を生成"):
        with st.spinner("AI作成中..."):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                    f.write(audio_value.read())
                    temp_path = f.name
                
                model = genai.GenerativeModel("gemini-1.5-flash")
                sample_file = genai.upload_file(path=temp_path)
                
                prompt = f"""
                プロの介護職として、ケアマネ向けの報告文を作って。
                名前：{user_name}
                食事：{meal}
                活動：{activity}
                音声内容：(添付ファイル)
                敬語で300文字以内。専門用語を含めて。
                """
                
                response = model.generate_content([sample_file, prompt])
                st.session_state["result_text"] = response.text
                os.remove(temp_path)
                
            except Exception as e:
                st.error(f"解析失敗。マイク許可を確認してください。")

# 表示と保存
st.divider()
final_report = st.text_area("生成結果", value=st.session_state.get("result_text", ""), height=300)

if st.button("保存する"):
    if user_name and final_report:
        # あなたのSupabaseのカラム名（id, created_atは自動）に一致させています
        data = {
            "user_name": user_name,
            "content": final_report,
            "category": "モニタリング"
        }
        try:
            supabase.table("records").insert(data).execute()
            st.success("✅ 保存しました！")
        except Exception as e:
            st.error(f"保存失敗: {e}")