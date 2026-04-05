import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, date, timedelta
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
    st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_stable_v34")
cookie_manager = st.session_state["cookie_manager"]

if "input_key_id" not in st.session_state:
    st.session_state["input_key_id"] = str(uuid.uuid4())

# --- 🎨 カスタムCSS (カレンダー色分け含む全仕様維持) ---
st.markdown("""
    <style>
    .main-title { font-size: clamp(18px, 5vw, 24px); font-weight: bold; color: #ff4b4b; border-bottom: 2px solid #ff4b4b; padding-bottom: 5px; margin-bottom: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
    div.stButton > button { border-radius: 10px !important; }
    .top-back-btn button { background-color: #ff4b4b !important; color: white !important; width: 100% !important; height: 60px !important; font-weight: bold !important; font-size: 18px !important; margin-top: 20px !important; border: none !important; box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important; }
    section[data-testid="stAudioInput"] { border: 2px solid #ff4b4b !important; border-radius: 20px !important; padding: 10px !important; background-color: #fff5f5 !important; }
    code { white-space: pre-wrap !important; word-break: break-all !important; }
    .stTextArea textarea { border: 2px solid #ff4b4b !important; border-radius: 10px !important; }
    .scrollable-history { max-height: 250px; overflow-y: auto; border: 2px solid #ff4b4b; border-radius: 10px; padding: 15px; background-color: #fffaf0; }
    .history-item { font-size: 16px; margin-bottom: 10px; border-bottom: 1px dashed #ccc; padding-bottom: 5px; }
    .history-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
    div.stButton > button p, div.stButton > button div, div.stButton > button span { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; font-size: clamp(10px, 3vw, 14px) !important; }
    
    /* カレンダーの色分け */
    div[data-baseweb="calendar"] div[aria-label^="Sunday"], div[data-baseweb="calendar"] button[aria-label*="Sunday"] { color: #ff4b4b !important; }
    div[data-baseweb="calendar"] div[aria-label^="Saturday"], div[data-baseweb="calendar"] button[aria-label*="Saturday"] { color: #0000ff !important; }
    div[data-baseweb="calendar"] div[aria-label^="Monday"], div[data-baseweb="calendar"] button[aria-label*="Monday"],
    div[data-baseweb="calendar"] div[aria-label^="Tuesday"], div[data-baseweb="calendar"] button[aria-label*="Tuesday"],
    div[data-baseweb="calendar"] div[aria-label^="Wednesday"], div[data-baseweb="calendar"] button[aria-label*="Wednesday"],
    div[data-baseweb="calendar"] div[aria-label^="Thursday"], div[data-baseweb="calendar"] button[aria-label*="Thursday"],
    div[data-baseweb="calendar"] div[aria-label^="Friday"], div[data-baseweb="calendar"] button[aria-label*="Friday"] { color: #31333F !important; }
    </style>
    """, unsafe_allow_html=True)

# 💡 スリープ防止 & 下に引っ張ってリロード有効化JavaScript
components.html("""
<script>
(function() {
    // スリープ防止
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

    // 🚀 スマホの「引っ張ってリロード」をより自然に許可する設定
    document.body.style.overscrollBehaviorY = 'contain'; 
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
        try: image = Image.open('logo.png')
        except: image = Image.open('logo.jpg')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# 🔐 ログイン・認証
cookies = cookie_manager.get_all()
if not cookies: time.sleep(0.5); st.rerun()
device_id = cookies.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="save_dev_v34")
if device_id:
    try:
        res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
        if res_block.data: st.error("🚫 この端末はアクセスが制限されています。"); st.stop()
    except: pass
if not st.session_state.get("is_authenticated"):
    sf, sn = cookies.get("saved_f_code"), cookies.get("saved_my_name")
    if sf and sn: st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn}); st.rerun()
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526", key="f_login")
        n_in = st.text_input("👤 あなたのお名前", key="n_login")
        if st.button("利用を開始する", use_container_width=True, key="btn_login"):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in, key="f_sv_v34")
                cookie_manager.set("saved_my_name", n_in, key="n_sv_v34")
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                time.sleep(0.5); st.rerun()
    st.stop()

f_code, my_name = st.session_state["facility_code"], st.session_state["my_name"]

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top", "edit_content": "", "monitoring_result": "", "editing_record_id": None}); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- 🏠 TOP画面 ---
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col_m2:
        if st.button("📊 ケース記録/モニタリング生成", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    if st.button("📅 日別記録閲覧", use_container_width=True): st.session_state["page"] = "daily_view"; st.rerun()
    st.divider()
    st.markdown("##### 📝 更新履歴 (最新30名まで)")
    if f_code:
        today_start = tokyo_tz.localize(datetime.combine(now_tokyo.date(), datetime.min.time()))
        today_end = today_start + timedelta(days=1)
        try:
            res_today = supabase.table("records").select("user_name, created_at").eq("facility_code", f_code).gte("created_at", today_start.isoformat()).lt("created_at", today_end.isoformat()).execute()
            if res_today.data:
                df = pd.DataFrame(res_today.data)
                grouped = df.groupby("user_name").agg(count=("user_name", "size"), last_time=("created_at", "max")).reset_index()
                grouped = grouped.sort_values("last_time", ascending=False).head(30)
                with st.container(height=250):
                    for _, row in grouped.iterrows():
                        try:
                            dt_utc = datetime.fromisoformat(str(row['last_time']).replace('Z', '+00:00'))
                            time_str = dt_utc.astimezone(tokyo_tz).strftime('%m/%d %H:%M')
                        except: time_str = str(row['last_time'])[5:16].replace('-', '/')
                        if st.button(f"👤 {row['user_name']} 様 ({row['count']}件) 最終 {time_str}", key=f"h_{row['user_name']}", use_container_width=True):
                            st.session_state.update({"page": "daily_view", "dv_target_user": row['user_name'], "dv_target_date": now_tokyo.date()}); st.rerun()
            else: st.info("本日の記録はまだありません。")
        except: pass
    st.divider()
    if st.button("🛠️ 管理者メニュー", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

# --- ✍️ 記録入力・編集画面 ---
elif st.session_state["page"] == "input":
    back_to_top_button("ip_u")
    is_edit = st.session_state.get("editing_record_id") is not None
    st.markdown(f"<div class='main-title'>{'📝 記録を修正' if is_edit else '✍️ ケース記録入力'}</div>", unsafe_allow_html=True)
    kid = st.session_state["input_key_id"]
    p_opts = ["(未選択)"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for r in res_p.data]
        except: pass
    default_sel = st.session_state.get("edit_user_label", "(未選択)")
    default_date = st.session_state.get("edit_date", now_tokyo.date())
    sel = st.selectbox("👤 利用者を選択", p_opts, index=p_opts.index(default_sel) if default_sel in p_opts else 0, key=f"sel_{kid}", disabled=is_edit)
    record_date = st.date_input("📅 記録日", value=default_date, key=f"date_{kid}", disabled=is_edit)
    st.markdown("---")
    if not is_edit:
        t_imgs = st.file_uploader("📷 写真（最大5枚）", type=["jpg", "png", "jpeg"], accept_multiple_files=True, key=f"img_{kid}")
        aud = st.audio_input("録音ボタン", key=f"aud_{kid}")
        if (t_imgs or aud) and st.button("✨ AIで文章にする", type="primary", key="btn_ai"):
            with st.spinner("整理中..."):
                try:
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    ins = ["音声や画像にある事実のみを文章化し、推測や事実以外の追加情報は絶対に書かないこと。「え〜」「あ〜」などの無意味な言葉（フィラー）は完全に削除すること。介護職員が職場の仲間に申し送りをするような、簡潔で分かりやすい「です・ます調」で出力すること。解説や挨拶などの余計な文章は一切不要。"]
                    if t_imgs:
                        for img in t_imgs: ins.append(Image.open(img))
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
    txt = st.text_area("内容", value=st.session_state["edit_content"], height=200, key=f"txt_{kid}")
    if st.button("🆙 修正を保存" if is_edit else "💾 クラウドに保存", use_container_width=True, key="btn_save"):
        if sel != "(未選択)" and txt and f_code:
            try:
                if is_edit:
                    supabase.table("records").update({"content": txt, "updated_at": now_tokyo.isoformat()}).eq("id", st.session_state["editing_record_id"]).execute()
                    st.success("✅ 修正完了")
                else:
                    m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                    dt = tokyo_tz.localize(datetime.combine(record_date, datetime.now(tokyo_tz).time()))
                    urls = []
                    if t_imgs:
                        for img in t_imgs[:5]: 
                            f_name = f"{uuid.uuid4()}.{img.name.split('.')[-1]}"
                            supabase.storage.from_("case-photos").upload(f_name, img.getvalue())
                            res_url = supabase.storage.from_("case-photos").get_public_url(f_name)
                            if hasattr(res_url, 'public_url'): urls.append(res_url.public_url)
                            else: urls.append(str(res_url))
                    supabase.table("records").insert({"facility_code": f_code, "chart_number": str(m.group(1)), "user_name": m.group(2), "staff_name": my_name, "content": txt, "image_url": urls if urls else None, "created_at": dt.isoformat()}).execute()
                    st.success("✅ 保存完了")
                st.session_state.update({"edit_content": "", "input_key_id": str(uuid.uuid4()), "editing_record_id": None, "page": "top"})
                time.sleep(0.5); st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    back_to_top_button("ip_d")

# --- 📊 ケース記録/モニタリング生成 ---
elif st.session_state["page"] == "history":
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 ケース記録/モニタリング生成</div>", unsafe_allow_html=True)
    p_opts = ["---"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) {r['user_name']} [{r['user_kana']}]" for r in res_p.data]
        except: pass
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = re.search(r'\) (.*?) \[', sel).group(1) if '[' in sel else re.search(r'\) (.*)', sel).group(1)
        st.divider()
        if st.button("📜 過去の履歴を表示" if not st.session_state.get("show_history_list") else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state.get("show_history_list", False); st.rerun()
        if st.session_state.get("show_history_list") and f_code:
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                try: t_str = datetime.fromisoformat(str(r['created_at']).replace('Z', '+00:00')).astimezone(tokyo_tz).strftime('%Y-%m-%d %H:%M')
                except: t_str = str(r['created_at'])[:16].replace('T', ' ')
                with st.expander(f"📅 {t_str} (担当: {r['staff_name']})"):
                    st.write(r['content'])
                    if r.get('image_url') and isinstance(r['image_url'], list):
                        cols = st.columns(min(len(r['image_url']), 5))
                        for idx, url in enumerate(r['image_url']):
                            with cols[idx]: st.image(url, use_container_width=True)
                    if r['staff_name'] == my_name or st.session_state["admin_authenticated"]:
                        if st.button("✏️ 編集", key=f"ed_h_{r['id']}"):
                            st.session_state.update({"page": "input", "editing_record_id": r['id'], "edit_content": r['content'], "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]", "edit_date": datetime.fromisoformat(str(r['created_at']).replace('Z', '+00:00')).date()}); st.rerun()
    back_to_top_button("hs_d")

# --- 📅 日別記録閲覧 ---
elif st.session_state["page"] == "daily_view":
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 日別記録閲覧</div>", unsafe_allow_html=True)
    dv_date = st.session_state.pop("dv_target_date", now_tokyo.date())
    selected_date = st.date_input("表示する日付を選択", value=dv_date)
    if selected_date and f_code:
        try:
            t_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
            res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at", desc=True).execute()
            if res.data:
                df = pd.DataFrame(res.data).fillna("不明")
                # 🚀 【エラー修正済み】変数参照の修正
                unique_users_view = df["user_name"].unique()
                st.write(f"✅ {selected_date} は **{len(unique_users_view)}名** の記録があります")
                st.divider()
                target_u = st.session_state.pop("dv_target_user", None)
                for target_user in unique_users_view:
                    user_records = df[df["user_name"] == target_user]
                    is_expanded = (target_user == target_u)
                    with st.expander(f"👤 {target_user} 様 ({len(user_records)}件)", expanded=is_expanded):
                        for _, row in user_records.iterrows():
                            try: t_s = datetime.fromisoformat(str(row['created_at']).replace('Z', '+00:00')).astimezone(tokyo_tz).strftime('%H:%M')
                            except: t_s = str(row['created_at'])[11:16]
                            st.markdown(f"**🕒 {t_s}** (担当: {row['staff_name']})")
                            st.info(str(row['content']))
                            if row.get('image_url') and isinstance(row['image_url'], list):
                                cols = st.columns(min(len(row['image_url']), 5))
                                for idx, url in enumerate(row['image_url']):
                                    with cols[idx]: st.image(url, use_container_width=True)
                            if row['staff_name'] == my_name or st.session_state["admin_authenticated"]:
                                if st.button("✏️ 編集", key=f"ed_dv_{row['id']}"):
                                    st.session_state.update({"page": "input", "editing_record_id": row['id'], "edit_content": row['content'], "edit_user_label": f"(No.{row['chart_number']}) [{row['user_name']}]", "edit_date": datetime.fromisoformat(str(row['created_at']).replace('Z', '+00:00')).date()}); st.rerun()
            else: st.info("📭 記録は見つかりませんでした。")
        except Exception as e: st.error(f"失敗: {e}")
    back_to_top_button("dv_d")

# --- 🛠️ 管理者メニュー ---
elif st.session_state["page"] == "admin_menu":
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    if f_code:
        res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
        if not st.session_state["admin_authenticated"]:
            ad_pw_in = st.text_input("パスワードを入力してください", type="password", key="ad_pass_field")
            if st.button("認証", key="btn_admin_auth"):
                if ad_pw_in == cur_pw: st.session_state["admin_authenticated"] = True; st.rerun()
                else: st.error("パスワードが違います。")
            st.stop()
        t1, t2, t3, t4 = st.tabs(["👥 利用者管理", "👮 職員管理", "🔑 パス設定", "🚫 セキュリティ"])
        with t1:
            st.markdown("##### 👤 利用者の新規登録・編集・削除")
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            with st.expander("🆕 新規登録"):
                with st.form("ad_reg", clear_on_submit=True):
                    c, n, k = st.text_input("No"), st.text_input("氏名"), st.text_input("ふりがな")
                    if st.form_submit_button("登録"): supabase.table("patients").insert({"facility_code": f_code, "chart_number": c, "user_name": n, "user_kana": k}).execute(); st.rerun()
            if res_p.data:
                for p in res_p.data:
                    c1, c2, c3 = st.columns([3, 1, 1])
                    with c1: st.write(f"**No.{p['chart_number']}** {p['user_name']}")
                    with c2:
                        if st.button("修正", key=f"p_e_{p['id']}"): st.session_state[f"p_edit_{p['id']}"] = True
                    with c3:
                        if st.button("削除", key=f"p_d_{p['id']}"): supabase.table("patients").delete().eq("id", p['id']).execute(); st.rerun()
                    if st.session_state.get(f"p_edit_{p['id']}"):
                        with st.form(f"f_p_{p['id']}"):
                            un, uk, uc = st.text_input("氏名", value=p['user_name']), st.text_input("カナ", value=p['user_kana']), st.text_input("No", value=p['chart_number'])
                            if st.form_submit_button("確定"): supabase.table("patients").update({"user_name": un, "user_kana": uk, "chart_number": uc}).eq("id", p['id']).execute(); del st.session_state[f"p_edit_{p['id']}"]; st.rerun()
        with t2:
            st.markdown("##### 👮 職員・端末管理 (退職者のブロック)")
            res_staff = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
            unique_staff = sorted(list(set([r['staff_name'] for r in res_staff.data if r.get('staff_name')]))) if res_staff.data else []
            for s in unique_staff:
                c_s1, c_s2 = st.columns([3, 1])
                with c_s1: st.write(f"👤 **{s}** さん")
                with c_s2:
                    if st.button("削除 (ブロック)", key=f"blk_btn_{s}"):
                        supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": s, "facility_code": f_code, "is_active": True}).execute()
                        st.warning(f"{s}さんの端末をブロックしました。"); time.sleep(1); st.rerun()
        with t3:
            st.markdown("##### 🔑 管理パスワード変更")
            np, cp = st.text_input("新パス", type="password"), st.text_input("確認", type="password")
            if st.button("パスワードを更新"):
                if np == cp:
                    if res_pw.data: supabase.table("admin_settings").update({"value": np}).eq("key", "admin_password").eq("facility_code", f_code).execute()
                    else: supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": np}).execute()
                    st.success("更新しました。"); st.rerun()
        with t4:
            st.markdown("##### 🔄 ブロック解除 (復帰)")
            res_l = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
            for b in res_l.data:
                if st.button(f"復帰: {b['staff_name']} (端末ID:{b['device_id'][:5]})", key=f"re_{b['id']}"):
                    supabase.table("blocked_devices").update({"is_active": False}).eq("id", b['id']).execute(); st.success("復帰させました。"); time.sleep(1); st.rerun()
            if not res_l.data: st.info("現在ブロック中の端末はありません。")

    back_to_top_button("ad_d")