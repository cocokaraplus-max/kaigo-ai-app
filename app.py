import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import date, datetime
from supabase import create_client, Client # type: ignore
from fpdf import FPDF

# --- 1. 初期設定・認証 ---
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

# --- 2. 接続設定 ---
st.set_page_config(page_title="AI介護マネージャー", page_icon="📋", layout="wide")

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
except Exception as e:
    st.error("接続設定に問題があります。")
    st.stop()

# --- 3. メイン画面のタブ構成 ---
tab1, tab2 = st.tabs(["✍️ ケース記録入力", "📊 履歴閲覧・モニタリング"])

# ==========================================
# タブ1: ケース記録入力 (既存機能の強化)
# ==========================================
with tab1:
    st.title("📓 ケース記録入力")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        user_name = st.text_input("利用者名", placeholder="例：山田 太郎")
        target_date = st.date_input("記録対象日", value=date.today(), key="input_date")
        st.subheader("🎙️ 音声入力")
        audio_value = st.audio_input("録音ボタンを押して話してください")
        
        if audio_value:
            if st.button("音声から文章を生成"):
                with st.spinner("AI解析中..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                        f.write(audio_value.read())
                        temp_path = f.name
                    sample_file = genai.upload_file(path=temp_path)
                    prompt = f"以下の音声から{user_name}さんの介護記録を、スタッフ間の申し送り口調で簡潔に作成してください。"
                    response = model.generate_content([sample_file, prompt])
                    st.session_state["current_content"] = response.text
                    os.remove(temp_path)

    with col2:
        st.subheader("📝 記録内容の確認")
        final_content = st.text_area("内容を修正して保存してください", value=st.session_state.get("current_content", ""), height=250)
        if st.button("クラウドに保存"):
            if user_name and final_content:
                data = {"user_name": user_name, "content": final_content, "created_at": target_date.isoformat(), "category": "case"}
                supabase.table("records").insert(data).execute()
                st.success("保存完了！")
                st.session_state["current_content"] = ""
            else:
                st.warning("項目を埋めてください。")

# ==========================================
# タブ2: 履歴閲覧・モニタリング (新機能)
# ==========================================
with tab2:
    st.title("📊 履歴・レポート生成")
    
    # 検索フィルター
    search_user = st.text_input("検索する利用者名", value=user_name)
    search_month = st.month_input("対象月を選択", value=date.today())
    
    if search_user:
        # Supabaseからデータ取得
        response = supabase.table("records").select("*").eq("user_name", search_user).execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df['created_at'] = pd.to_datetime(df['created_at'])
            
            # 選択された月のデータに絞り込み
            df_filtered = df[(df['created_at'].dt.year == search_month.year) & (df['created_at'].dt.month == search_month.month)]
            df_filtered = df_filtered.sort_values("created_at")

            st.write(f"### {search_user} 様の記録 ({search_month.strftime('%Y/%m')})")
            
            # --- モニタリング生成 ---
            if st.button("✨ 1ヶ月のモニタリング報告書を生成"):
                all_text = "\n".join(df_filtered['content'].tolist())
                with st.spinner("1ヶ月の記録を集約中..."):
                    m_prompt = f"以下の1ヶ月分のケース記録を分析し、ケアプランの進捗状況として200文字程度のモニタリング報告書を作成してください。利用者は{search_user}さんです。\n\n記録内容:\n{all_text}"
                    m_response = model.generate_content(m_prompt)
                    st.info(m_response.text)
                    st.session_state["monitoring_report"] = m_response.text

            st.divider()

            # --- 履歴表示・印刷用レイアウト ---
            for d in df_filtered['created_at'].dt.date.unique():
                day_records = df_filtered[df_filtered['created_at'].dt.date == d]
                with st.expander(f"📅 {d} の記録 ({len(day_records)}件)"):
                    for _, row in day_records.iterrows():
                        st.write(f"・ {row['content']}")

            # --- PDF/印刷ボタン ---
            st.button("🖨️ 画面を印刷 (Ctrl+P)", on_click=lambda: st.write('<script>window.print();</script>', unsafe_allow_html=True))
            
        else:
            st.write("記録が見つかりません。")