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
import re

# --- 1. 基本設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)
st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")

cookie_manager = stx.CookieManager()

def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except Exception: pass

load_css("style.css")

try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}"); st.stop()

def normalize_text(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return ""
    return unicodedata.normalize('NFKC', str(s).strip())

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

# --- 2. 状態管理 ---
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "show_history_list" not in st.session_state: st.session_state["show_history_list"] = False

# 職員リスト（必要に応じて増やしてください）
STAFF_LIST = ["管理者", "サービス提供責任者", "介護職員A", "介護職員B", "看護師"]

# ==========================================
# 🔐 ログイン & Cookie同期
# ==========================================
cookie_manager.get_all()
time.sleep(0.5)
saved_f = cookie_manager.get("saved_f_code")
saved_n = cookie_manager.get("saved_my_name")

if not st.session_state.get("is_authenticated"):
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n})
        st.rerun()
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.selectbox("👤 あなたのお名前 (職員)", STAFF_LIST)
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in); cookie_manager.set("saved_my_name", n_in)
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                st.rerun()
    st.stop()

f_code = st.session_state["facility_code"]
my_name = st.session_state["my_name"]

# ==========================================
# 🏠 TOP画面
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col2:
        if st.button("📊 履歴・モニタリング", use_container_width=True): 
            st.session_state["page"] = "history"
            st.session_state["show_history_list"] = False # 初期状態はリスト非表示
            st.rerun()
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⚙️ 利用者マスター登録", use_container_width=True): st.session_state["page"] = "settings"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
        st.session_state.clear(); st.rerun()

# ==========================================
# ✍️ 記録入力（職員プルダウン対応）
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("✍️ ケース記録入力")
    
    # 職員名選択（ログイン時以外でも変更可能にする）
    current_staff = st.selectbox("記入者", STAFF_LIST, index=STAFF_LIST.index(my_name) if my_name in STAFF_LIST else 0)

    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    if p_df.empty: st.warning("利用者を登録してください"); st.stop()
    
    patient_options = ["(未選択)"]
    for _, r in p_df.iterrows():
        patient_options.append(f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]")
    
    sel = st.selectbox("👤 利用者を選択", patient_options)
    
    aud = st.audio_input("🎙️ 声で入力")
    if aud and st.button("✨ AIで文章にする"):
        with st.spinner("音声を整理中..."):
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(aud.getvalue()); tmp_path = tmp.name
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                f_up = genai.upload_file(path=tmp_path)
                for _ in range(10):
                    f_up = genai.get_file(f_up.name)
                    if f_up.state.name == "ACTIVE": break
                    time.sleep(1)
                
                prompt = (
                    "あなたは介護現場の記録作成アシスタントです。以下のルールで音声をテキスト化し、整えてください：\n"
                    "1. 話していない内容を付け加えたり、推測で情報を補完したりしないでください。\n"
                    "2. 「えーっと」「あー」などの不要な言葉（フィラー）はすべて削除してください。\n"
                    "3. 口調は介護職員が仲間に申し送るような、自然な話し言葉（〜でした、〜のようです、等）にしてください。\n"
                    "4. 箇条書きなどの報告書形式ではなく、一続きの「記録」としての文章にまとめてください。"
                )
                response = model.generate_content([f_up, prompt])
                st.session_state["edit_content"] = response.text
                os.remove(tmp_path); st.rerun()
            except Exception as e: st.error(f"解析エラー: {e}")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=250)
    
    if st.button("💾 クラウド保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no = match.group(1); u_name = match.group(2)
            supabase.table("records").insert({
                "facility_code": f_code, "chart_number": str(c_no), "user_name": u_name,
                "staff_name": current_staff, "content": content, "created_at": now_tokyo.isoformat()
            }).execute()
            st.success("保存完了！"); st.session_state["edit_content"] = ""; time.sleep(1); st.session_state["page"] = "top"; st.rerun()

# ==========================================
# 📊 履歴・モニタリング（AI自動まとめ・モニタリング生成）
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("📊 履歴・モニタリング")

    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    sel = st.selectbox("利用者を選択", ["---"] + [f"(No.{r['chart_number']}) {r['user_name']}" for _, r in p_df.iterrows()])
    
    if sel != "---":
        u_name = re.search(r'\) (.*)', sel).group(1)
        
        col_act1, col_act2 = st.columns(2)
        with col_act1:
            if st.button("📅 今日の記録を1つにまとめる", use_container_width=True):
                # 本日の全記録を取得
                today_str = now_tokyo.strftime('%Y-%m-%d')
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", today_str).execute()
                if res.data:
                    with st.spinner("AIで本日の記録を統合中..."):
                        all_txt = "\n".join([r['content'] for r in res.data])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        resp = model.generate_content(f"以下の本日のバラバラな記録を、1日のまとめケース記録として整理して。話していないことは追加せず、時系列順の自然な申し送り口調で書いて。\n\n{all_txt}")
                        st.session_state["daily_summary"] = resp.text
                        st.info(f"✨ 本日のまとめ生成結果:\n\n{resp.text}")
                else: st.warning("本日の記録がありません。")

        with col_act2:
            if st.button("📈 1ヶ月のモニタリング生成", use_container_width=True):
                # 過去30日分の記録を取得
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).limit(50).execute()
                if res.data:
                    with st.spinner("月間モニタリング作成中..."):
                        all_txt = "\n".join([f"{r['created_at'][:10]}: {r['content']}" for r in res.data])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        resp = model.generate_content(f"{u_name}さんの1ヶ月の記録から、変化やケアのポイントを専門的に分析してモニタリング文を作成して。\n\n{all_txt}")
                        st.success("📈 生成完了"); st.write(resp.text)
                else: st.warning("データが不足しています。")

        st.divider()
        
        # 履歴表示（ボタンを押した時だけ表示）
        if st.button("📜 過去の履歴を表示する" if not st.session_state["show_history_list"] else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state["show_history_list"]

        if st.session_state["show_history_list"]:
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            if res.data:
                for r in res.data:
                    with st.expander(f"📅 {r['created_at'][:16].replace('T',' ')} - 記: {r.get('staff_name','--')}"):
                        st.write(r['content'])
            else: st.info("表示できる履歴がありません。")

# ==========================================
# ⚙️ 設定（変更なし）
# ==========================================
elif st.session_state["page"] == "settings":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("⚙️ 利用者マスター登録")
    with st.form("reg_master"):
        c_no = st.text_input("カルテ番号")
        u_na = st.text_input("氏名 (漢字)")
        u_ka = st.text_input("ふりがな (カタカナ)")
        if st.form_submit_button("登録"):
            if c_no and u_na and u_ka:
                supabase.table("patients").insert({"facility_code": f_code, "chart_number": c_no, "user_name": u_na, "user_kana": u_ka}).execute()
                st.success("完了"); time.sleep(1); st.rerun()