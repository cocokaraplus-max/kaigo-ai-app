import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, date
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

# --- 🎨 カスタムCSS（視認性向上・ライトモード対応） ---
st.markdown("""
    <style>
    /* 管理者メニューの大見出し */
    .admin-title {
        font-size: 22px;
        font-weight: bold;
        color: #ff4b4b !important;
        padding-bottom: 10px;
        border-bottom: 2px solid #ff4b4b;
        margin-bottom: 20px;
        display: block;
    }
    
    /* タブの文字色を強制的に濃いグレー（#31333F）に固定 */
    .stTabs [data-baseweb="tab-list"] button {
        color: #31333F !important;
        font-size: 16px !important;
        font-weight: 600 !important;
    }
    
    /* 選択中のタブの文字を赤く強調 */
    .stTabs [aria-selected="true"] {
        color: #ff4b4b !important;
    }

    /* フォームのラベル（説明文）を黒系に固定して白背景で見やすく */
    .stMarkdown p, .stText, label {
        color: #31333F !important;
    }
    
    /* セレクトボックス内の文字を見やすく */
    div[data-baseweb="select"] > div {
        color: #31333F !important;
    }
    </style>
    """, unsafe_allow_html=True)

try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}"); st.stop()

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
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# ==========================================
# 🔐 セキュリティ・端末チェック
# ==========================================
cookie_manager.get_all()
time.sleep(1.2) # スマホでのCookie読み込み待ち

# 端末IDの取得とブロック確認
device_id = cookie_manager.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id)

res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
if res_block.data:
    st.error("🚫 この端末は管理者によってブロックされています。")
    st.stop()

# ログイン認証
if not st.session_state.get("is_authenticated"):
    saved_f = cookie_manager.get("saved_f_code")
    saved_n = cookie_manager.get("saved_my_name")
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n})
        st.rerun()
    
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
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
            st.session_state["page"] = "history"; st.rerun()
    
    st.divider()
    if st.button("🛠️ 管理者メニューを開く", use_container_width=True):
        st.session_state["page"] = "admin_menu"; st.session_state["admin_authenticated"] = False; st.rerun()

    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
        st.session_state.clear(); st.rerun()

# ==========================================
# 🛠️ 管理者設定メニュー（パスワード・視認性・ブロック）
# ==========================================
elif st.session_state["page"] == "admin_menu":
    if st.button("◀ TOPに戻る"): st.session_state["page"] = "top"; st.rerun()
    
    # 1. パスワード認証
    if not st.session_state["admin_authenticated"]:
        st.markdown("<div class='admin-title'>🛠️ 管理者認証</div>", unsafe_allow_html=True)
        admin_pw = st.text_input("管理者パスワードを入力してください", type="password")
        if st.button("認証"):
            if admin_pw == "8888": # パスワード変更時はここを書き換える
                st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("パスワードが違います")
        st.stop()

    # 2. 認証後のメニュー
    st.markdown("<div class='admin-title'>🛠️ 管理者設定メニュー</div>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["👥 利用者登録", "🚫 端末ブロック", "🔄 復活・解除"])

    with tab1:
        st.write("利用者のマスター情報を登録します。ふりがなは「ひらがな」で入力してください。")
        with st.form("reg_master_v8"):
            c_no = st.text_input("カルテ番号")
            u_na = st.text_input("氏名 (漢字)")
            u_ka = st.text_input("ふりがな (ひらがな)")
            if st.form_submit_button("マスターに登録"):
                if c_no and u_na and u_ka:
                    supabase.table("patients").insert({"facility_code": f_code, "chart_number": c_no, "user_name": u_na, "user_kana": u_ka}).execute()
                    st.success("登録が完了しました"); time.sleep(1); st.rerun()

    with tab2:
        st.write("不適切な利用があった場合、この端末からのアクセスを永久に禁止します。")
        res_staff = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        staff_names = list(set([r['staff_name'] for r in res_staff.data])) if res_staff.data else []
        target_staff = st.selectbox("ブロック対象の職員名", ["(選択してください)"] + staff_names)
        if st.button("🚨 この端末を永久ブロック", type="primary", use_container_width=True):
            if target_staff != "(選択してください)":
                supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": target_staff, "facility_code": f_code, "is_active": True}).execute()
                cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
                st.session_state.clear(); time.sleep(2); st.rerun()

    with tab3:
        st.write("現在ブロックされている端末の一覧です。復活させる場合はボタンを押してください。")
        res_list = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        if res_list.data:
            for b in res_list.data:
                col_b1, col_b2 = st.columns([3, 1])
                with col_b1: st.write(f"🚫 {b['staff_name']} (ID: {b['device_id'][:8]})")
                with col_b2:
                    if st.button("復活", key=b['device_id']):
                        supabase.table("blocked_devices").update({"is_active": False}).eq("device_id", b['device_id']).execute()
                        st.success("解除しました"); time.sleep(1); st.rerun()
        else: st.info("ブロック中の端末はありません。")

# ==========================================
# ✍️ 記録入力（現場申し送り口調）
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("✍️ ケース記録入力")
    st.info(f"✍️ 記入者: {my_name}")

    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    patient_options = ["(未選択)"] + [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("👤 利用者を選択", patient_options)
    
    aud = st.audio_input("🎙️ 声で入力")
    if aud and st.button("✨ AIで文章にする"):
        with st.spinner("整理中..."):
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(aud.getvalue()); tmp_path = tmp.name
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                f_up = genai.upload_file(path=tmp_path)
                for _ in range(10):
                    f_up = genai.get_file(f_up.name); 
                    if f_up.state.name == "ACTIVE": break
                    time.sleep(1.5)
                # 申し送り口調のプロンプト
                prompt = ("不要な言葉を削除し、介護職員が仲間に送る自然な口調で、話した内容のみを正確に記録として整えてください。")
                response = model.generate_content([f_up, prompt])
                st.session_state["edit_content"] = response.text
                os.remove(tmp_path); st.rerun()
            except Exception as e: st.error(f"解析エラー: {e}")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=250)
    if st.button("💾 クラウド保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no = match.group(1); u_name = match.group(2)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(c_no), "user_name": u_name, "staff_name": my_name, "content": content, "created_at": now_tokyo.isoformat()}).execute()
            st.success("保存完了！"); st.session_state["edit_content"] = ""; time.sleep(1); st.session_state["page"] = "top"; st.rerun()

# ==========================================
# 📊 履歴・モニタリング（支援内容重視）
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("📊 履歴・モニタリング")

    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    sel = st.selectbox("利用者を選択", ["---"] + [f"(No.{r['chart_number']}) {r['user_name']}" for _, r in p_df.iterrows()])
    
    if sel != "---":
        u_name = re.search(r'\) (.*)', sel).group(1)
        
        st.markdown("#### 📅 記録の集計・モニタリング生成")
        col_date, col_btn = st.columns([2, 2])
        with col_date:
            target_date = st.date_input("集計日を選択", value=date.today())
        with col_btn:
            if st.button("✨ 指定日のまとめ作成", use_container_width=True):
                date_str = target_date.strftime('%Y-%m-%d')
                next_day = (target_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", date_str).lt("created_at", next_day).execute()
                if res.data:
                    with st.spinner("AIで統合中..."):
                        all_txt = "\n".join([r['content'] for r in res.data])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        prompt = f"以下の{target_date}の介護記録を、200字程度で要約してください。特に『支援内容』『実施した対応』は漏らさず全て含めてください。報告書口調（〜です、〜でした）とし、事実のみを整理してください。"
                        resp = model.generate_content(prompt + "\n\n" + all_txt)
                        st.info(f"📅 {target_date} 要約結果:\n\n{resp.text}")
                else: st.warning(f"{target_date} の記録がありません。")

        if st.button("📈 ケアマネ向け1ヶ月モニタリング作成", use_container_width=True):
            # 直近の記録40件を取得
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).limit(40).execute()
            if res.data:
                with st.spinner("モニタリング文を作成中..."):
                    all_txt = "\n".join([f"{r['created_at'][:10]}: {r['content']}" for r in res.data])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    prompt = "ケアマネジャー報告用の200字程度の月間モニタリング文を作成してください。【最重要】: ケース記録に含まれる『支援内容』『介入事項』は漏れなく全て記載してください。飛躍せず事実のみを使い、コピペ用の本文のみを出力してください。"
                    resp = model.generate_content(prompt + "\n\n" + all_txt)
                    st.session_state["monitoring_result"] = resp.text
            else: st.warning("記録データが足りません。")

        if st.session_state["monitoring_result"]:
            st.markdown("---")
            with st.container(border=True):
                st.write(st.session_state["monitoring_result"])
                st.markdown("<br>", unsafe_allow_html=True)
                st.caption("📋 以下の枠内の右上のボタンでコピーできます")
                st.code(st.session_state["monitoring_result"], language=None)

        st.divider()
        if st.button("📜 過去の履歴を表示する" if not st.session_state["show_history_list"] else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state["show_history_list"]
        if st.session_state["show_history_list"]:
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            if res.data:
                for r in res.data:
                    with st.expander(f"📅 {r['created_at'][:16].replace('T',' ')} - 記: {r.get('staff_name','--')}"):
                        st.write(r['content'])