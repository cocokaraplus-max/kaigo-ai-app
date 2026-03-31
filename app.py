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

# --- 2. 接続設定（Secretsから取得） ---
st.set_page_config(page_title="AIケース記録", page_icon="📓")

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    st.sidebar.success("✅ システム接続完了")
except Exception as e:
    st.sidebar.error("❌ 接続エラー：Secretsを確認してください")
    st.stop()

# --- 3. メイン画面：ケース記録入力 ---
st.title("📓 AIケース記録システム")

# 1. 利用者名
user_name = st.text_input("利用者名", placeholder="例：山田 太郎")

# 2. 日付指定（カレンダー）
# 初期値はNone（未入力状態）に設定したいところですが、Streamlitの仕様上、
# 視覚的に分かりやすく「今日」をデフォルトにし、変更可能にします。
target_date = st.date_input("記録対象日（空欄なら今日として処理されます）", value=date.today())

# 3. 音声入力セクション
st.subheader("🎙️ 音声で入力する")
audio_value = st.audio_input("マイクをタップして話してください")

# AI解析実行
if audio_value:
    if st.button("音声から文章を生成"):
        with st.spinner("AIがプロの文章に変換中..."):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                    f.write(audio_value.read())
                    temp_path = f.name
                
                model = genai.GenerativeModel("gemini-1.5-flash")
                sample_file = genai.upload_file(path=temp_path)
                
                # プロンプト（指示文）
                prompt = f"""
                あなたは優秀な介護スタッフです。以下の音声内容から、プロフェッショナルな「ケース記録」を作成してください。
                対象者：{user_name}
                日付：{target_date.strftime('%Y年%m月%d日')}
                
                【ルール】
                ・丁寧な敬語（～されました、～の様子です）を使用。
                ・専門用語を適切に使い、客観的な事実を中心にまとめる。
                ・300文字程度。
                """
                
                response = model.generate_content([sample_file, prompt])
                st.session_state["edit_content"] = response.text
                os.remove(temp_path)
                
            except Exception as e:
                st.error(f"AI解析エラー: {e}")

st.divider()

# 4. 手入力・修正セクション
st.subheader("📝 記録内容の確認・手入力")
# 音声解析結果が入るが、手動で書き換えたり最初から手入力も可能
final_content = st.text_area(
    "こちらに直接入力・修正が可能です", 
    value=st.session_state.get("edit_content", ""), 
    height=300,
    placeholder="音声入力するか、ここに直接記録を書いてください..."
)

# 5. 保存実行
if st.button("クラウド(Supabase)に保存"):
    if user_name and final_content:
        # 日付が選択されているか、デフォルト（今日）かを確認して保存
        save_date = target_date.isoformat() if target_date else date.today().isoformat()
        
        record_data = {
            "user_name": user_name,
            "content": final_content,
            "category": "ケース記録",
            "created_at": save_date
        }
        
        try:
            supabase.table("records").insert(record_data).execute()
            st.success(f"✅ {save_date} の記録として正常に保存されました。")
            # 保存後は入力欄をクリアするためにセッションを削除
            if "edit_content" in st.session_state:
                del st.session_state["edit_content"]
        except Exception as e:
            st.error(f"保存エラー: {e}")
    else:
        st.warning("「利用者名」と「記録内容」を入力してください。")