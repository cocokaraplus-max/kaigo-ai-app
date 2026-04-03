import streamlit as st
import google.generativeai as genai

st.title("🔍 Gemini モデル調査")

# 接続設定
try:
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    
    st.write("### 📋 利用可能なモデル一覧:")
    
    # サーバーから利用可能なモデルを取得
    models = genai.list_models()
    
    model_data = []
    for m in models:
        # generateContent がサポートされているモデルのみ抽出
        if 'generateContent' in m.supported_generation_methods:
            model_data.append({
                "名前": m.name,
                "表示名": m.display_name,
                "説明": m.description
            })
    
    if model_data:
        st.table(model_data)
    else:
        st.warning("利用可能なモデルが見つかりませんでした。APIキーの権限を確認してください。")

except Exception as e:
    st.error(f"❌ エラーが発生しました: {e}")