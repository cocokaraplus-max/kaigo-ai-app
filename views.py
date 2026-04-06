import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, timedelta
import uuid
import time
from PIL import Image # type: ignore
import re
from utils import tokyo_tz, display_logo, back_to_top_button

def render_top(supabase, cookie_manager, f_code, my_name):
    """TOP画面: 権限に応じたメニュー表示"""
    now_tokyo = datetime.now(tokyo_tz)
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col_m2:
        if st.button("📊 モニタリング生成", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    
    if st.button("📅 ケース記録閲覧", use_container_width=True): st.session_state["page"] = "daily_view"; st.rerun()
    
    st.divider()
    
    hist_limit = 30
    try:
        res_limit = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        if res_limit.data: hist_limit = int(res_limit.data[0]['value'])
    except: pass

    st.markdown(f"##### 📝 更新履歴 (最新{hist_limit}名まで)")
    if f_code:
        today_start = tokyo_tz.localize(datetime.combine(now_tokyo.date(), datetime.min.time()))
        try:
            res_today = supabase.table("records").select("user_name, created_at").eq("facility_code", f_code).gte("created_at", today_start.isoformat()).lt("created_at", (today_start + timedelta(days=1)).isoformat()).execute()
            if res_today.data:
                df = pd.DataFrame(res_today.data)
                grouped = df.groupby("user_name").agg(count=("user_name", "size"), last_time=("created_at", "max")).reset_index()
                grouped = grouped.sort_values("last_time", ascending=False).head(hist_limit)
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
    
    if st.session_state.get("admin_authenticated"):
        if st.button("🛠️ 管理者メニュー (認証済み)", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    else:
        if st.button("🛠️ 管理者メニューへログイン", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()

    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

def render_input(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
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
            with st.spinner("AIが文章に変換中..."):
                try:
                    model = genai.GenerativeModel('models/gemini-2.5-flash')
                    prompt = "あなたは介護のプロです。事実のみを読み取り、職員間の連絡に適した「丁寧なです・ます調」で簡潔に記録を書いてください。挨拶や余計な解説は不要です。"
                    contents = [prompt]
                    if t_imgs:
                        for img in t_imgs: contents.append(Image.open(img))
                    if aud: contents.append({"mime_type": "audio/wav", "data": aud.getvalue()})
                    response = model.generate_content(contents)
                    st.session_state["edit_content"] = response.text.strip()
                    st.session_state[f"txt_{kid}"] = response.text.strip()
                    st.rerun()
                except Exception as e: st.error(f"AIエラー: {e}")
            
    txt = st.text_area("内容", value=st.session_state.get(f"txt_{kid}", st.session_state["edit_content"]), height=200, key=f"txt_{kid}")
    if st.button("🆙 修正を保存" if is_edit else "💾 保存", use_container_width=True, key="btn_save"):
        if sel != "(未選択)" and txt and f_code:
            try:
                if is_edit:
                    supabase.table("records").update({"content": txt, "updated_at": now_tokyo.isoformat()}).eq("id", st.session_state["editing_record_id"]).execute()
                else:
                    m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                    dt = tokyo_tz.localize(datetime.combine(record_date, datetime.now(tokyo_tz).time()))
                    urls = []
                    if t_imgs:
                        for img in t_imgs[:5]: 
                            f_name = f"{uuid.uuid4()}.{img.name.split('.')[-1]}"
                            supabase.storage.from_("case-photos").upload(f_name, img.getvalue())
                            res_url = supabase.storage.from_("case-photos").get_public_url(f_name)
                            urls.append(res_url.public_url if hasattr(res_url, 'public_url') else str(res_url))
                    supabase.table("records").insert({"facility_code": f_code, "chart_number": str(m.group(1)), "user_name": m.group(2), "staff_name": my_name, "content": txt, "image_url": urls if urls else None, "created_at": dt.isoformat()}).execute()
                st.session_state.update({"edit_content": "", "input_key_id": str(uuid.uuid4()), "editing_record_id": None, "page": "top"})
                st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    back_to_top_button("ip_d")

def render_history(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 モニタリング生成</div>", unsafe_allow_html=True)
    p_opts = ["---"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) {r['user_name']}" for r in res_p.data]
        except: pass
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = sel.split(") ")[1]
        st.markdown("##### ✨ 1ヶ月分のAIモニタリング作成")
        month_opts = [f"{now_tokyo.year}年{m:02d}月" for m in range(now_tokyo.month, now_tokyo.month-6, -1)]
        selected_month_str = st.selectbox("対象月を選択", month_opts)
        if st.button("✨ 生成", type="primary"):
            with st.spinner("AI分析中..."):
                t_y, t_m = int(selected_month_str[:4]), int(selected_month_str[5:7])
                s_date = tokyo_tz.localize(datetime(t_y, t_m, 1))
                e_date = (s_date + timedelta(days=32)).replace(day=1)
                res = supabase.table("records").select("staff_name, content").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).execute()
                if res.data:
                    recs = "\n".join([f"[{r['staff_name']}] {r['content']}" for r in res.data])
                    model = genai.GenerativeModel('models/gemini-2.5-flash')
                    prompt = f"以下の1ヶ月分の記録を、200文字以内の自然な口語調で要約してください。挨拶は不要です。\n\n{recs}"
                    response = model.generate_content(prompt)
                    st.session_state["monitoring_result"] = response.text
                else: st.warning("記録がありません。")
        if st.session_state.get("monitoring_result"):
            edited = st.text_area("編集・コピー", value=st.session_state["monitoring_result"], height=150)
            st.session_state["monitoring_result"] = edited
            st.code(edited, language="text")
        
        st.divider()
        if st.button("📜 過去履歴を表示"):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16]} ({r['staff_name']})"):
                    st.write(r['content'])
                    if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                        if st.button("✏️ 編集", key=f"ed_h_{r['id']}"):
                            st.session_state.update({"page": "input", "editing_record_id": r['id'], "edit_content": r['content'], "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]", "edit_date": datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date()}); st.rerun()
    back_to_top_button("hs_d")

def render_daily_view(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 ケース記録閲覧</div>", unsafe_allow_html=True)
    selected_date = st.date_input("日付を選択", value=now_tokyo.date())
    if f_code:
        t_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
        res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            for user in df["user_name"].unique():
                user_recs = df[df["user_name"] == user]
                with st.expander(f"👤 {user} 様 ({len(user_recs)}件)"):
                    sum_key = f"sum_{selected_date}_{user}"
                    if sum_key not in st.session_state and len(user_recs) > 1:
                        if st.button("✨ 1日のまとめ", key=f"btn_{sum_key}"):
                            model = genai.GenerativeModel('models/gemini-2.5-flash')
                            daily_txt = "\n".join([f"[{r['staff_name']}] {r['content']}" for _, r in user_recs.iterrows()])
                            prompt = f"以下の記録を1つの申し送りに要約してください。\n\n{daily_txt}"
                            st.session_state[sum_key] = model.generate_content(prompt).text; st.rerun()
                    if sum_key in st.session_state: st.info(st.session_state[sum_key])
                    for _, r in user_recs.iterrows():
                        with st.expander(f"🕒 {r['created_at'][11:16]} ({r['staff_name']})"):
                            st.write(r['content'])
                            if r.get('image_url'):
                                for url in r['image_url']: st.image(url, use_container_width=True)
                            if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                                if st.button("✏️ 編集", key=f"ed_dv_{r['id']}"):
                                    st.session_state.update({"page": "input", "editing_record_id": r['id'], "edit_content": r['content'], "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]", "edit_date": datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date()}); st.rerun()
    back_to_top_button("dv_d")

def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    
    # 🔒 パスワード認証ロジック
    if not st.session_state.get("admin_authenticated"):
        try:
            res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
            cur_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
            ad_pw_in = st.text_input("管理者パスワードを入力", type="password")
            if st.button("認証"):
                if ad_pw_in == cur_pw:
                    st.session_state["admin_authenticated"] = True; st.rerun()
                else: st.error("パスワードが違います。")
            st.stop()
        except Exception as e: st.error(f"設定エラー: {e}"); st.stop()

    t1, t2, t3 = st.tabs(["👥 利用者/スタッフ管理", "⚙️ システム設定", "🚫 セキュリティ"])
    
    with t1:
        st.markdown("##### 👤 利用者の新規登録・管理")
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            with st.expander("🆕 利用者を新規登録"):
                with st.form("reg_user", clear_on_submit=True):
                    c, n, k = st.text_input("No"), st.text_input("氏名"), st.text_input("ふりがな")
                    if st.form_submit_button("登録"):
                        supabase.table("patients").insert({"facility_code": f_code, "chart_number": c, "user_name": n, "user_kana": k}).execute(); st.rerun()
            if res_p.data:
                for p in res_p.data:
                    c1, c2, c3 = st.columns([3, 1, 1])
                    with c1: st.write(f"**No.{p['chart_number']}** {p['user_name']}")
                    with c2:
                        if st.button("修正", key=f"pe_{p['id']}"): st.session_state[f"pedit_{p['id']}"] = True
                    with c3:
                        if st.button("削除", key=f"pd_{p['id']}"): supabase.table("patients").delete().eq("id", p['id']).execute(); st.rerun()
                    if st.session_state.get(f"pedit_{p['id']}"):
                        with st.form(f"fp_{p['id']}"):
                            un, uk, uc = st.text_input("氏名", p['user_name']), st.text_input("カナ", p['user_kana']), st.text_input("No", p['chart_number'])
                            if st.form_submit_button("確定"):
                                supabase.table("patients").update({"user_name": un, "user_kana": uk, "chart_number": uc}).eq("id", p['id']).execute(); del st.session_state[f"pedit_{p['id']}"]; st.rerun()
        except: pass

    with t2:
        st.markdown("##### ⚙️ パスワード・表示設定")
        np, cp = st.text_input("新パスワード", type="password"), st.text_input("確認", type="password")
        if st.button("パスワード更新"):
            if np == cp and np:
                supabase.table("admin_settings").upsert({"facility_code": f_code, "key": "admin_password", "value": np}, on_conflict="facility_code,key").execute()
                st.success("更新完了"); time.sleep(1); st.rerun()
        st.divider()
        res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        cur_l = int(res_l.data[0]['value']) if res_l.data else 30
        new_l = st.slider("履歴表示人数", 10, 100, cur_l, 5)
        if st.button("件数保存"):
            supabase.table("admin_settings").upsert({"facility_code": f_code, "key": "history_limit", "value": str(new_l)}, on_conflict="facility_code,key").execute()
            st.success("保存完了"); time.sleep(1); st.rerun()

    with t3:
        st.markdown("##### 🚫 端末ブロック解除")
        res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        if res_b.data:
            for b in res_b.data:
                if st.button(f"解除: {b['staff_name']} (ID:{b['device_id'][:5]})", key=f"rb_{b['id']}"):
                    supabase.table("blocked_devices").update({"is_active": False}).eq("id", b['id']).execute(); st.rerun()
        else: st.info("ブロック中の端末はありません。")
    
    if st.button("🛠️ 管理者モードを終了"):
        st.session_state["admin_authenticated"] = False; st.rerun()
    back_to_top_button("ad_d")