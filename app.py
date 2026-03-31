import streamlit as st
import google.generativeai as genai
import tempfile
import os
from datetime import date
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
                st.error("パスワードが正しくありません")
        return False
    return True

if not check_password():
    st.stop()

# --- 2. 接続設定（Secrets） ---
st.set_page_config(page_title="AIケース記録", page_icon="📓")

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    st.sidebar.success("✅ システム接続完了")
except Exception as e:
    st.sidebar.error("❌ 接続エラー：Secretsを確認してください")
    st.stop()

# --- 3. メイン画面 ---
st.title("📓 AIケース記録 (運用版)")

user_name = st.text_input("利用者名", placeholder="例：山田 太郎")
target_date = st.date_input("記録対象日", value=date.today())

st.divider()

# --- 4. 音声入力セクション ---
st.subheader("🎙️ 音声で入力")
audio_value = st.audio_input("マイクをタップして話してください")

if audio_value:
    if st.button("音声から文章を生成"):
        with st.spinner("AIが文章を作成中..."):
            try:
                # 一時ファイルに保存
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                    f.write(audio_value.read())
                    temp_path = f.name
                
                # アカウントで利用可能な最新の高速モデル
                model = genai.GenerativeModel("gemini-2.5-flash")
                
                # ファイルアップロード
                sample_file = genai.upload_file(path=temp_path)
                
                # 【最終調整】ありのまま・申し送り口調・水増し禁止
                prompt = f"""
                以下の音声データから、{target_date.strftime('%Y/%m/%d')}のケース記録（対象者：{user_name}）を作成してください。
                
                【厳守するルール】
                1. 音声で話された内容を「なるべくありのまま」抽出し、絶対に勝手な推測や事実の追加（話の膨張）をしないでください。
                2. 現場の介護職員同士で情報共有（申し送り）をする際の、分かりやすく自然な口調（「〜でした」「〜とのことです」「〜の様子です」など）でまとめてください。
                3. 無駄な前置きや挨拶、AIとしての感想は一切不要です。結果だけを出力してください。
                4. 話された内容が短い場合は、無理に文字数を増やさず、短いまま出力してください。
                """
                
                # 生成実行
                response = model.generate_content([sample_file, prompt])
                st.session_state["edit_content"] = response.text
                
                # 一時ファイルの削除
                os.remove(temp_path)
                
            except Exception as e:
                st.error(f"AI解析エラーが発生しました。")
                st.info(f"詳細ログ: {e}")

st.divider()

# --- 5. 手入力・修正エリア ---
st.subheader("📝 記録内容（手入力・修正）")
final_content = st.text_area(
    "内容を確認・修正してください", 
    value=st.session_state.get("edit_content", ""), 
    height=300,
    placeholder="ここに直接入力するか、音声入力を利用してください..."
)

# --- 6. 保存ボタン ---
if st.button("クラウド(Supabase)に保存"):
    if user_name and final_content:
        save_date = target_date.isoformat()
        
        record_data = {
            "user_name": user_name,
            "content": final_content,
            "category": "ケース記録",
            "created_at": save_date
        }
        
        try:
            supabase.table("records").insert(record_data).execute()
            st.success(f"✅ {save_date} の記録として保存しました！")
            if "edit_content" in st.session_state:
                del st.session_state["edit_content"]
        except Exception as e:
            st.error(f"保存エラー: {e}")
    else:
        st.warning("「利用者名」と「記録内容」を入力してください。")