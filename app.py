import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
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

# --- 2. 接続設定とUI絶対非表示設定 ---
st.set_page_config(page_title="AIケース記録", page_icon="📓", layout="wide")

# ▼▼▼ あらゆるバージョンのStreamlit UIを根こそぎ消し去る最強のCSS ▼▼▼
hide_streamlit_style = """
<style>
/* ヘッダー全体（上の余白やメニュー）を完全に消す */
[data-testid="stHeader"] {display: none !important;}
/* 右上のツールバー（開発者マーク、王冠、Deploy等）を消す */
[data-testid="stToolbar"] {display: none !important;}
[data-testid="manage-app-button"] {display: none !important;}
/* Deployボタンを消す */
[data-testid="stAppDeployButton"] {display: none !important;}
.stDeployButton {display: none !important;}
/* 古いメニュークラスも念のため消す */
#MainMenu {visibility: hidden !important;}
/* フッター（Made with Streamlit）を消す */
footer {visibility: hidden !important;}
/* 右下のアバターやバッジも徹底的に消す */
.viewerBadge_container {display: none !important;}
.viewerBadge_link {display: none !important;}
[data-testid="viewerBadge"] {display: none !important;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
# ▲▲▲ ここまで ▲▲▲

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
    
    # 画面を左右に分割（左: 入力, 右: 確認・保存）
    col1, col2 = st.columns([1, 1])
    
    with col1:
        user_name = st.text_input("利用者名", placeholder="例：山田 太郎")
        target_date = st.date_input("記録対象日", value=date.today(), key="input_date")
        
        st.subheader("🎙️ 音声で入力")
        audio_value = st.audio_input("マイクをタップして話してください")
        
        if audio_value:
            if st.button("音声から文章を生成"):
                with st.spinner("AIが文章を作成中..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                            f.write(audio_value.read())
                            temp_path = f.name
                        
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        sample_file = genai.upload_file(path=temp_path)
                        
                        prompt = f"""
                        以下の音声データから、{target_date.strftime('%Y/%m/%d')}のケース記録（対象者：{user_name}）を作成してください。
                        
                        【厳守するルール】
                        1. 音声で話された内容を「なるべくありのまま」抽出し、絶対に勝手な推測や事実の追加（話の膨張）をしないでください。
                        2. 現場の介護職員同士で情報共有（申し送り）をする際の、分かりやすく自然な口調（「〜でした」「〜とのことです」「〜の様子です」など）でまとめてください。
                        3. 無駄な前置きや挨拶、AIとしての感想は一切不要です。結果だけを出力してください。
                        4. 話された内容が短い場合は、無理に文字数を増やさず、短いまま出力してください。
                        """
                        
                        response = model.generate_content([sample_file, prompt])
                        st.session_state["edit_content"] = response.text
                        os.remove(temp_path)
                        
                    except Exception as e:
                        st.error("AI解析エラーが発生しました。")
                        st.info(f"詳細ログ: {e}")

    with col2:
        st.subheader("📝 記録内容（手入力・修正）")
        final_content = st.text_area(
            "内容を確認・修正してください", 
            value=st.session_state.get("edit_content", ""), 
            height=300,
            placeholder="ここに直接入力するか、音声入力を利用してください..."
        )
        
        if st.button("クラウド(Supabase)に保存", type="primary"):
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
                    # 保存後にテキストエリアを空にする
                    if "edit_content" in st.session_state:
                        del st.session_state["edit_content"]
                except Exception as e:
                    st.error(f"保存エラー: {e}")
            else:
                st.warning("「利用者名」と「記録内容」を入力してください。")


# ==========================================
# タブ2: 履歴閲覧・モニタリング
# ==========================================
with tab2:
    st.title("📊 履歴・レポート生成")
    
    # 検索フィルター（年・月をドロップダウンで選択）
    col3, col4, col5 = st.columns([2, 1, 1])
    with col3:
        search_user = st.text_input("検索する利用者名（完全一致）", placeholder="例：山田 太郎", key="search_user")
    with col4:
        today = date.today()
        search_year = st.selectbox("対象年", range(today.year - 2, today.year + 2), index=2)
    with col5:
        search_month = st.selectbox("対象月", range(1, 13), index=today.month - 1)
    
    if search_user:
        try:
            # Supabaseから該当利用者のデータを全件取得
            response_db = supabase.table("records").select("*").eq("user_name", search_user).execute()
            
            if response_db.data:
                # データを表計算形式（Pandas DataFrame）に変換
                df = pd.DataFrame(response_db.data)
                df['created_at'] = pd.to_datetime(df['created_at'])
                
                # 選択された「年・月」のデータだけに絞り込み、日付順に並べ替え
                df_filtered = df[(df['created_at'].dt.year == search_year) & (df['created_at'].dt.month == search_month)]
                df_filtered = df_filtered.sort_values("created_at")

                st.subheader(f"📋 {search_user} 様の記録 ({search_year}年{search_month}月)")
                
                if not df_filtered.empty:
                    # --- 月末モニタリング生成機能 ---
                    st.write("▼ AIがこの1ヶ月の全記録を分析し、月末の報告書を作成します")
                    if st.button("✨ 1ヶ月のモニタリング報告書を生成", type="primary"):
                        all_text = "\n".join([f"[{row['created_at'].strftime('%Y/%m/%d')}] {row['content']}" for _, row in df_filtered.iterrows()])
                        
                        with st.spinner("記録を集約し、報告書を作成中..."):
                            model = genai.GenerativeModel("gemini-2.5-flash")
                            m_prompt = f"""
                            あなたは優秀なケアマネージャーです。
                            以下の1ヶ月分のケース記録（日々の申し送り事項）を分析し、ケアプランの進捗状況として【200文字程度】のモニタリング報告書を作成してください。
                            利用者は{search_user}さんです。
                            
                            【ルール】
                            ・客観的事実に基づき、体調の変化や生活の様子を総括すること。
                            ・「だ・である」調、または「〜の様子であった」などのプロフェッショナルな文体にすること。
                            
                            記録内容:
                            {all_text}
                            """
                            m_response = model.generate_content(m_prompt)
                            st.success("✅ モニタリング報告書の生成が完了しました！")
                            st.info(m_response.text)
                    
                    st.divider()

                    # --- 履歴一覧表示 ---
                    st.write("▼ 日々の記録一覧")
                    for d in df_filtered['created_at'].dt.date.unique():
                        day_records = df_filtered[df_filtered['created_at'].dt.date == d]
                        # 1日ごとに折りたたみメニュー（アコーディオン）で表示
                        with st.expander(f"📅 {d.strftime('%Y年%m月%d日')} の記録 ({len(day_records)}件)"):
                            for _, row in day_records.iterrows():
                                st.write(f"・ {row['content']}")
                    
                    st.divider()
                    
                    # --- 印刷ボタン（ブラウザの標準印刷を呼び出す） ---
                    st.button("🖨️ この画面を印刷 / PDFで保存", on_click=lambda: st.components.v1.html("<script>window.parent.print();</script>", height=0))

                else:
                    st.warning(f"{search_year}年{search_month}月の記録はまだありません。")
            else:
                st.warning(f"「{search_user}」様の記録が見つかりません。名前が間違っていないか確認してください。")
                
        except Exception as e:
            st.error("データの取得中にエラーが発生しました。")
            st.info(f"詳細: {e}")