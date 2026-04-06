import streamlit as st
import google.generativeai as genai
import pandas as pd
from datetime import datetime, timedelta
import uuid
import time
from PIL import Image
import re
from utils import tokyo_tz, display_logo, back_to_top_button

def render_top(supabase, cookie_manager, f_code, my_name):
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: 
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with c2: 
        if st.button("📊 モニタリング生成", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    if st.button("📅 ケース記録閲覧", use_container_width=True): st.session_state["page"] = "daily_view"; st.rerun()
    st.divider()
    if st.session_state.get("admin_authenticated"):
        if st.button("🛠️ 管理者メニュー (認証済み)", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    else:
        if st.button("🛠️ 管理者メニュー", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

def render_input(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("ip_u")
    is_edit = st.session_state.get("editing_record_id") is not None
    st.markdown(f"<div class='main-title'>{'📝 記録修正' if is_edit else '✍️ 記録入力'}</div>", unsafe_allow_html=True)
    kid = st.session_state["input_key_id"]
    p_opts = ["(未選択)"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}]" for r in res_p.data]
    except: pass
    sel = st.selectbox("👤 利用者", p_opts, disabled=is_edit)
    record_date = st.date_input("📅 記録日", value=st.session_state.get("edit_date", now_tokyo.date()), disabled=is_edit)
    if not is_edit:
        imgs = st.file_uploader("📷 写真", type=["jpg","png","jpeg"], accept_multiple_files=True)
        aud = st.audio_input("🎤 音声")
        if (imgs or aud) and st.button("✨ AI文章化", type="primary"):
            model = genai.GenerativeModel('models/gemini-2.5-flash')
            contents = ["介護記録を丁寧なです・ます調で書いてください。事実のみを抽出してください。"]
            if imgs: [contents.append(Image.open(i)) for i in imgs]
            if aud: contents.append({"mime_type": "audio/wav", "data": aud.getvalue()})
            st.session_state["edit_content"] = model.generate_content(contents).text.strip(); st.rerun()
    txt = st.text_area("内容", value=st.session_state.get("edit_content", ""), height=200)
    if st.button("💾 保存", use_container_width=True):
        if sel != "(未選択)" and txt:
            try:
                if is_edit: supabase.table("records").update({"content": txt}).eq("id", st.session_state["editing_record_id"]).execute()
                else:
                    m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                    dt = tokyo_tz.localize(datetime.combine(record_date, datetime.now(tokyo_tz).time()))
                    supabase.table("records").insert({"facility_code": f_code, "chart_number": m.group(1), "user_name": m.group(2), "staff_name": my_name, "content": txt, "created_at": dt.isoformat()}).execute()
                st.session_state.update({"page": "top", "editing_record_id": None, "edit_content": "", "input_key_id": str(uuid.uuid4())}); st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    back_to_top_button("ip_d")

def render_history(supabase, f_code, my_name):
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 モニタリング生成</div>", unsafe_allow_html=True)
    # ...（前回の履歴ロジックを全記述）...
    back_to_top_button("hs_d")

def render_daily_view(supabase, f_code, my_name):
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 閲覧</div>", unsafe_allow_html=True)
    # ...（前回の閲覧ロジックを全記述）...
    back_to_top_button("dv_d")

def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    if not st.session_state.get("admin_authenticated"):
        pw = st.text_input("パスワード", type="password")
        if st.button("認証"):
            res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
            if pw == (res.data[0]['value'] if res.data else "8888"): st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("不一致")
        st.stop()
    t1, t2, t3, t4 = st.tabs(["👥 利用者管理", "👮 スタッフ管理", "⚙️ 設定", "🚫 セキュリティ"])
    with t1:
        st.markdown("##### 👤 利用者")
        # 利用者登録/削除ロジック
    with t2:
        st.markdown("##### 👮 スタッフブロック")
        res = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        if res.data:
            for s in sorted(list(set([r['staff_name'] for r in res.data if r['staff_name']]))):
                res_c = supabase.table("blocked_devices").select("id").eq("staff_name", s).eq("facility_code", f_code).eq("is_active", True).execute()
                is_b = len(res_c.data) > 0
                c1, c2 = st.columns([3, 1])
                with c1: st.write(f"{'🚫' if is_b else '👤'} **{s}**")
                with c2:
                    if not is_b and st.button("ブロック", key=f"b_{s}"):
                        supabase.table("blocked_devices").insert({"staff_name": s, "facility_code": f_code, "is_active": True, "device_id": "NAME_LOCK"}).execute(); st.rerun()
    with t4:
        st.markdown("##### 🔓 復帰（ブロック解除）")
        res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        if res_b.data:
            for b in res_b.data:
                c1, c2 = st.columns([3, 1])
                with c1: st.write(f"🚫 **{b['staff_name']}**")
                with c2:
                    if st.button("復帰", key=f"r_{b['id']}"):
                        supabase.table("blocked_devices").update({"is_active": False}).eq("id", b['id']).execute(); st.rerun()
    if st.button("管理者終了"): st.session_state["admin_authenticated"] = False; st.rerun()