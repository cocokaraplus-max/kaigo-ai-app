import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime
import pytz 
from supabase import create_client, Client # type: ignore
import uuid
import time
from PIL import Image # type: ignore
import extra_streamlit_components as stx 
import unicodedata

# --- 1. 基本設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)
st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")

# Cookieマネージャー初期化
cookie_manager = stx.CookieManager()

def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except Exception: pass

load_css("style.css")

# 接続設定
try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}"); st.stop()

def normalize_chart_no(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return ""
    return unicodedata.normalize('NFKC', str(s).split('.')[0]).strip()

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

# --- 2. 状態管理 ---
if "is_authenticated" not in st.session_state: st.session_state["is_authenticated"] = False
if "facility_code" not in st.session_state: st.session_state["facility_code"] = ""
if "my_name" not in st.session_state: st.session_state["my_name"] = ""
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""

# ==========================================
# 🔐 ログイン（Cookie同期の鉄壁ガード）
# ==========================================
# Cookieを読み取るためにマネージャーを配置
cookie_manager.get_all()

# 初回アクセス時、Cookieから値を引っ張るための待機
if not st.session_state["is_authenticated"]:
    time.sleep(0.6) # ブラウザの反応を待つ
    saved_f = cookie_manager.get("saved_f_code")
    saved_n = cookie_manager.get("saved_my_name")
    
    # Cookieが存在し、まだセッションが空なら「即座に」同期してリロード
    if saved_f and saved_n and not st.session_state["facility_code"]:
        st.session_state.update({
            "is_authenticated": True,
            "facility_code": saved_f,
            "my_name": saved_n
        })
        st.rerun()

    display_logo()
    st.markdown("<h3 style='text-align: center;'>🔐 ログイン</h3>", unsafe_allow_html=True)
    with st.container(border=True):
        # Cookieがあればそれをデフォルト値にする
        f_in = st.text_input("🏢 施設コード", value=saved_f if saved_f else "cocokaraplus-5526", key="login_f_v10")
        n_in = st.text_input("👤 お名前", value=saved_n if saved_n else "", key="login_n_v10")
        
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                # ログイン時にCookieへ保存
                cookie_manager.set("saved_f_code", f_in, key="save_f_v10")
                cookie_manager.set("saved_my_name", n_in, key="save_n_v10")
                st.session_state.update({
                    "is_authenticated": True,
                    "facility_code": f_in,
                    "my_name": n_in
                })
                st.rerun()
            else:
                st.warning("施設コードとお名前を入力してください")
    st.stop()

# 【重要】ここから下は facility_code が確定している場合のみ実行される
f_code = st.session_state.get("facility_code")
if not f_code:
    st.warning("認証情報を確認中...")
    st.stop()

# ==========================================
# 🏠 TOP画面
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{st.session_state['my_name']}</b> さん</p>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✍️ 記録を書く", use_container_width=True):
            st.session_state["page"] = "input"; st.rerun()
    with col2:
        if st.button("📊 履歴・モニタリング", use_container_width=True):
            st.session_state["page"] = "history"; st.rerun()
            
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⚙️ 設定・利用者登録", use_container_width=True):
        st.session_state["page"] = "settings"; st.rerun()
    
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code")
        cookie_manager.delete("saved_my_name")
        st.session_state.clear()
        st.rerun()

# ==========================================
# ✍️ 記録入力
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("✍️ ケース記録入力")
    
    # DB通信 (f_codeが確実に存在することを保証)
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).execute()
        p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    except Exception as e:
        st.error("データの取得に失敗しました。再ログインしてください。")
        st.stop()

    if p_df.empty:
        st.warning("設定画面から利用者を登録してください"); st.stop()
    
    sel = st.selectbox("👤 利用者を選択", ["---"] + [f"No.{r['chart_number']} : {r['user_name']}" for _, r in p_df.iterrows()])
    
    st.markdown("<br>", unsafe_allow_html=True)
    c_aud, c_cam = st.columns(2)
    with c_aud:
        aud = st.audio_input("🎙️ 声で入力")
        if aud and st.button("✨ AIで文章にする", key="btn_voice_v10"):
            with st.spinner("AIが音声を解析中..."):
                try:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        f.write(aud.getvalue()); p = f.name
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    f_up = genai.upload_file(path=p)
                    # ファイル待機
                    for _ in range(15):
                        f_up = genai.get_file(f_up.name)
                        if f_up.state.name == "ACTIVE": break
                        time.sleep(2)
                    res = model.generate_content([f_up, "介護記録として整理してください。必ず日本語で出力してください。"])
                    st.session_state["edit_content"] = res.text
                    os.remove(p); st.rerun()
                except Exception as e:
                    st.error(f"解析エラーが発生しました。")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=300)
    
    if st.button("💾 クラウド保存", use_container_width=True):
        if sel == "---":
            st.error("利用者を選択してください")
        else:
            u_name = sel.split(" : ")[1]; c_no = sel.split(" : ")[0].replace("No.", "")
            supabase.table("records").insert({
                "facility_code": f_code,
                "chart_number": str(c_no), 
                "user_name": u_name,
                "staff_name": st.session_state["my_name"], # ここで名前を紐付け
                "content": content,
                "created_at": now_tokyo.isoformat()
            }).execute()
            st.success(f"保存完了！（記入者: {st.session_state['my_name']}）")
            st.session_state["edit_content"] = ""; time.sleep(1); st.session_state["page"] = "top"; st.rerun()

# ==========================================
# 📊 履歴・モニタリング
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("📊 履歴・モニタリング")
    
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    sel = st.selectbox("利用者を選択", ["---"] + [f"No.{r['chart_number']} : {r['user_name']}" for _, r in p_df.iterrows()])
    
    if sel != "---":
        u_name = sel.split(" : ")[1]
        c_yr, c_mt = st.columns(2)
        with c_yr: s_year = st.selectbox("年", [2024, 2025, 2026], index=2)
        with c_mt: s_month = st.selectbox("月", range(1, 13), index=now_tokyo.month-1)
        mode = st.radio("表示形式", ["日ごと (まとめ)", "投稿ごと (詳細)"], horizontal=True)
        
        res = supabase.table("records").select("*").eq("user_name", u_name).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['created_at'] = pd.to_datetime(df['created_at'])
            df_f = df[(df['created_at'].dt.year == s_year) & (df['created_at'].dt.month == s_month)].sort_values("created_at", ascending=False)
            
            if st.button("📈 モニタリング生成", use_container_width=True):
                if not df_f.empty:
                    with st.spinner("AI分析中..."):
                        all_t = "\n".join([f"{str(r['content'])}" for _, r in df_f.iterrows()])
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        resp = model.generate_content(f"{u_name}さんの記録からモニタリングを作成:\n{all_t}")
                        st.info(resp.text)
            
            st.divider()
            for d, group in df_f.groupby(df_f['created_at'].dt.date):
                with st.expander(f"📅 {d}"):
                    if mode == "日ごと (まとめ)":
                        st.write(" ".join(group['content'].astype(str).tolist()))
                    else:
                        for _, r in group.sort_values("created_at").iterrows():
                            st.markdown(f"**✍️ 記入:** {r.get('staff_name', '---')}")
                            st.write(r['content']); st.markdown("---")

# ==========================================
# ⚙️ 設定
# ==========================================
elif st.session_state["page"] == "settings":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("⚙️ 利用者登録")
    with st.form("reg_v10"):
        c_no = st.text_input("カルテ番号"); u_na = st.text_input("氏名"); u_ka = st.text_input("ふりがな")
        if st.form_submit_button("登録"):
            supabase.table("patients").insert({
                "facility_code": f_code, 
                "chart_number": normalize_chart_no(c_no), 
                "user_name": u_na, "user_kana": u_ka
            }).execute()
            st.success("登録完了！"); st.rerun()