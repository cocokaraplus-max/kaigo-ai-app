import streamlit as st
import google.generativeai as genai
import tempfile
import os
from datetime import datetime, date
from supabase import create_client, Client # type: ignore

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
                st.error("不一致")
        return False
    return True

if not check_password():
    st.stop()

# --- 2. 接続設定（Secrets） ---
st.set_page_config(page_title="AIケース記録", page_icon="📓")

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    st.sidebar.success("✅ 接続完了")
except Exception as e:
    st.sidebar.error("❌ 設定エラー")
    st.stop()

# --- 3. メイン画面：ケース記録入力 ---
st.title("📓 AIケース記録（日付指定）")

# 利用者名と日付の入力
col_name, col_date = st.columns([2, 1])
with col_name:
    user_name = st.text_input("利用者名", placeholder="例：山田 太郎")
with col_date:
    # 日付指定（初期値は今日）
    target_date = st.date_input("記録対象日", value=date.today())

# 音声入力
st.subheader("🎙️ 音声で様子を記録")
audio_value = st.audio_input("マイクをタップして話してください")

# AI文章作成
if audio_value:
    if st.button("AI報告文を生成"):
        with st.spinner("AI作成中..."):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                    f.write(audio_value.read())
                    temp_path = f.name
                
                model = genai.GenerativeModel("gemini-1.5-flash")
                sample_file = genai.upload_file(path=temp_path)
                
                # 日付を文章に含める
                formatted_date = target_date.strftime("%Y年%m月%d日")
                prompt = f"""
                あなたはプロの介護職です。{formatted_date}のケース記録を作成してください。
                利用者名：{user_name}
                音声内容：(添付ファイル)
                
                【ルール】
                ・ケアマネジャーや家族が読むことを想定した丁寧な敬語。
                ・専門用語を交え、客観的な事実を中心に300文字程度で作成。
                """
                
                response = model.generate_content([sample_file, prompt])
                st.session_state["case_result"] = response.text
                os.remove(temp_path)
                
            except Exception as e:
                st.error(f"解析失敗: {e}")

# 生成結果の表示と保存
st.divider()
final_report = st.text_area("生成された記録（修正可能）", 
                            value=st.session_state.get("case_result", ""), 
                            height=300)

if st.button("クラウドに保存"):
    if user_name and final_report:
        # 保存するデータの作成
        # 指定された日付をISOフォーマット（YYYY-MM-DD）にして保存
        data = {
            "user_name": user_name,
            "content": final_report,
            "category": "ケース記録",
            "created_at": target_date.isoformat() 
        }
        try:
            # Supabaseのrecordsテーブルへ挿入
            supabase.table("records").insert(data).execute()
            st.success(f"✅ {target_date.strftime('%m/%d')}の記録として保存しました！")
            if "case_result" in st.session_state:
                del st.session_state["case_result"]
        except Exception as e:
            st.error(f"保存失敗: {e}")
    else:
        st.warning("名前と内容を入力してください。")