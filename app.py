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
import re
import streamlit.components.v1 as components

# --- 1. 基本設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)
st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")

if "cookie_manager" not in st.session_state:
    st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_stable_v13")
cookie_manager = st.session_state["cookie_manager"]

# --- 🎨 カスタムCSS（維持） ---
st.markdown("""
    <style>
    .main-title { font-size: clamp(18px, 5vw, 24px); font-weight: bold; color: #ff4b4b; border-bottom: 2px solid #ff4b4b; padding-bottom: 5px; margin-bottom: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
    div.stButton > button { border-radius: 10px !important; }
    .top-back-btn button { background-color: #ff4b4b !important; color: white !important; width: 100% !important; height: 60px !important; font-weight: bold !important; font-size: 18px !important; margin-top: 20px !important; border: none !important; box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important; }
    section[data-testid="stAudioInput"] { border: 2px solid #ff4b4b !important; border-radius: 20px !important; padding: 10px !important; background-color: #fff5f5 !important; }
    code { white-space: pre-wrap !important; word-break: break-all !important; }
    .stTextArea textarea { border: 2px solid #ff4b4b !important; border-radius: 10px !important; }
    </style>
    """, unsafe_allow_html=True)

# 💡 スリープ防止（維持）
components.html("""
<script>
(function() {
    let wakeLock = null;
    async function requestWakeLock() { try { if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); } } catch (err) { } }
    function createNoSleepVideo() {
        const video = document.createElement('video'); video.setAttribute('loop', ''); video.setAttribute('playsinline', ''); video.style.display = 'none';
        video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
        return video;
    }
    const v = createNoSleepVideo();
    document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
    requestWakeLock();
})();
</script>
""", height=0)

try:
    s_url, s_key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e: st.error(f"⚠️ 接続エラー: {e}"); st.stop()

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# ==========================================
# 🔐 ログイン・端末認証
# ==========================================
cookies = cookie_manager.get_all()
if not cookies:
    time.sleep(0.5); st.rerun()

device_id = cookies.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="save_dev_v13")

if device_id:
    try:
        res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
        if res_block.data: st.error("🚫 アクセス制限中。"); st.stop()
    except: pass

if not st.session_state.get("is_authenticated"):
    sf, sn = cookies.get("saved_f_code"), cookies.get("saved_my_name")
    if sf and sn:
        st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn}); st.rerun()
    
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526", key="f_login")
        n_in = st.text_input("👤 あなたのお名前", key="n_login")
        if st.button("利用を開始する", use_container_width=True, key="btn_login"):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in, key="f_sv_v13")
                cookie_manager.set("saved_my_name", n_in, key="n_sv_v13")
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                time.sleep(0.5); st.rerun()
    st.stop()

f_code, my_name = st.session_state["facility_code"], st.session_state["my_name"]
if not f_code: st.stop()

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top", "edit_content": "", "monitoring_result": ""}); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 🏠 画面遷移
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: 
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with c2: 
        if st.button("📊 履歴・モニタリング", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    st.divider()
    if st.button("🛠️ 管理者メニュー", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

elif st.session_state["page"] == "input":
    back_to_top_button("ip_u")
    st.markdown("<div class='main-title'>✍️ ケース記録入力</div>", unsafe_allow_html=True)
    p_opts = ["(未選択)"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for r in res_p.data]
        except: pass
    
    sel = st.selectbox("👤 利用者を選択", p_opts)
    st.markdown("---")
    t_img = st.file_uploader("📷 写真（背面カメラ）", type=["jpg", "png", "jpeg"])
    st.write("🎙️ **指でボタンを押して録音を開始してください**")
    st.caption("※画面のスリープ機能がある場合には画面に触れながら話してください")
    aud = st.audio_input("録音ボタン")
    
    if (t_img or aud) and st.button("✨ AIで文章にする", type="primary"):
        with st.spinner("整理中..."):
            try:
                # 🚀 最新モデル gemini-2.0-flash-exp に更新
                model = genai.GenerativeModel("models/gemini-2.0-flash-exp")
                ins = ["解説なし、ナレーションなし。内容のみ介護記録の口調で。"]
                if t_img: ins.append(Image.open(t_img))
                if aud:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(aud.getvalue()); tmp_p = tmp.name
                    f = genai.upload_file(path=tmp_p)
                    while f.state.name != "ACTIVE": time.sleep(1); f = genai.get_file(f.name)
                    ins.append(f)
                r = model.generate_content(ins)
                st.session_state["edit_content"] = r.text
                if aud: os.remove(tmp_p)
                st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
            
    txt = st.text_area("内容", value=st.session_state["edit_content"], height=200)
    if st.button("💾 クラウドに保存", use_container_width=True):
        if sel != "(未選択)" and txt and f_code:
            m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(m.group(1)), "user_name": m.group(2), "staff_name": my_name, "content": txt, "created_at": now_tokyo.isoformat()}).execute()
            st.success("✅ 保存完了"); st.session_state["edit_content"] = ""; time.sleep(1); st.rerun()
    back_to_top_button("ip_d")

elif st.session_state["page"] == "history":
    back_to_top_button("hs_u")
    st.markdown("<div class='main