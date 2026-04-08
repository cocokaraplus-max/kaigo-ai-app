import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import time
from PIL import Image
import re
from utils import tokyo_tz, display_logo, back_to_top_button, call_gemini_ai

def parse_jst(iso_str, fmt='%H:%M'):
    try:
        dt = datetime.fromisoformat(str(iso_str).replace('Z', '+00:00'))
        return dt.astimezone(tokyo_tz).strftime(fmt)
    except:
        return str(iso_str)[11:16]

def go_to_daily_view(u_name, target_d):
    st.session_state["page"] = "daily_view"
    st.session_state["dv_target_user"] = u_name
    st.session_state["dv_target_date"] = target_d

# --- 1. TOP画面 ---
def render_top(supabase, cookie_manager, f_code, my_name):
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: 
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with c2: 
        if st.button("📊 モニタリング生成", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    if st.button("📅 ケース記録閲覧・統合", use_container_width=True): st.session_state["page"] = "daily_view"; st.rerun()
    
    st.divider()
    hist_limit = 30
    try:
        res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        if res_l.data: hist_limit = int(res_l.data[0]['value'])
    except: pass

    st.markdown(f"##### 📝 更新履歴 (最新{hist_limit}件)")
    try:
        res_hist = supabase.table("records").select("id, user_name, staff_name, created_at").eq("facility_code", f_code).order("created_at", desc=True).limit(hist_limit * 2).execute()
        if res_hist.data:
            filtered_hist = [r for r in res_hist.data if r['staff_name'] != "AI統合記録"][:hist_limit]
            with st.container(height=300):
                for r in filtered_hist:
                    time_str = parse_jst(r['created_at'])
                    try:
                        dt_obj = datetime.fromisoformat(str(r['created_at']).replace('Z', '+00:00')).astimezone(tokyo_tz)
                        target_d = dt_obj.date()
                    except:
                        target_d = datetime.now(tokyo_tz).date()
                    st.button(f"👤 {r['user_name']} ({time_str})", key=f"hist_btn_{r['id']}", use_container_width=True, on_click=go_to_daily_view, args=(r['user_name'], target_d))
    except: pass

    st.divider()
    btn_label = "🛠️ 管理者MENU" + (" (認証済)" if st.session_state.get("admin_authenticated") else "")
    if st.button(btn_label, use_container_width=True):
        st.session_state["page"] = "admin_menu"
        st.rerun()
        
    if st.button("🚪 ログアウト", use_container_width=True):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

# --- 2. 入力画面 ---
def render_input(supabase, cookie_manager, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    st.markdown("<div class='main-title'>✍️ 記録入力</div>", unsafe_allow_html=True)
    
    p_opts = ["(未選択)"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data:
            for r in res_p.data:
                kana = r.get('user_kana') or ""
                p_opts.append(f"(No.{r['chart_number']}) [{r['user_name']}] {kana}")
    except:
        st.error("利用者の抽出に失敗しました。")

    sel = st.selectbox("👤 利用者を選択 (ひらがな検索OK)", p_opts)
    record_date = st.date_input("📅 記録日", value=now_tokyo.date())
    
    imgs = st.file_uploader("📷 写真（最大5枚）", type=["jpg","png","jpeg"], accept_multiple_files=True)
    aud = st.audio_input("🎤 音声入力")
    
    if (imgs or aud) and st.button("✨ AI文章化", type="primary"):
        with st.spinner("AI変換中..."):
            try:
                prompt = "介護職の申し送り口調で事実を簡潔にまとめて。職員名や『利用者様は』などの主語は不要。"
                contents = [prompt]
                if imgs: [contents.append(Image.open(i)) for i in imgs]
                if aud: contents.append({"mime_type": "audio/wav", "data": aud.getvalue()})
                
                # 🚀 確実に call_gemini_ai を使う！
                st.session_state["edit_content"] = call_gemini_ai(contents)
                st.rerun()
            except Exception as e:
                st.error(f"AI変換エラー: {e}")
    
    txt = st.text_area("内容", value=st.session_state.get("edit_content", ""), height=200)
    if st.button("💾 保存", use_container_width=True):
        if sel != "(未選択)" and txt:
            try:
                m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                if m:
                    record_time = datetime.now(tokyo_tz).time()
                    dt = tokyo_tz.localize(datetime.combine(record_date, record_time))
                    supabase.table("records").insert({"facility_code": f_code, "chart_number": m.group(1), "user_name": m.group(2), "staff_name": my_name, "content": txt, "created_at": dt.isoformat()}).execute()
                    
                    st.success("💾 保存完了しました！")
                    time.sleep(1.0)
                    st.session_state.update({"edit_content": ""})
                    st.session_state["page"] = "daily_view"
                    st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
            
    st.divider()
    back_to_top_button("ip_d")

# --- 3. モニタリング生成 ---
def render_history(supabase, cookie_manager, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    st.markdown("<div class='main-title'>📊 モニタリング生成</div>", unsafe_allow_html=True)
    p_opts = ["---"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data: 
            for r in res_p.data:
                kana = r.get('user_kana') or ""
                p_opts.append(f"(No.{r['chart_number']}) [{r['user_name']}] {kana}")
    except: pass
    
    sel = st.selectbox("利用者を選択 (ひらがな検索OK)", p_opts)
    if sel != "---":
        m = re.search(r'\[(.*?)\]', sel)
        u_name = m.group(1) if m else ""
        
        month_opts = [f"{now_tokyo.year}年{m:02d}月" for m in range(now_tokyo.month, now_tokyo.month-6, -1)]
        selected_month_str = st.selectbox("対象月", month_opts)
        char_limit = st.radio("生成する文字数の目安", ["100文字", "200文字", "300文字"], horizontal=True)
        
        if st.button("✨ 1ヶ月の要約を生成", type="primary"):
            with st.spinner("AI集計中..."):
                t_y, t_m = int(selected_month_str[:4]), int(selected_month_str[5:7])
                s_date = tokyo_tz.localize(datetime(t_y, t_m, 1)); e_date = (s_date + timedelta(days=32)).replace(day=1)
                res = supabase.table("records").select("content, staff_name").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).execute()
                if res.data:
                    filtered_recs = [r['content'] for r in res.data if r['staff_name'] != "AI統合記録"]
                    recs = "\n".join(filtered_recs)
                    if recs.strip():
                        prompt = f"以下の介護記録を報告口調で一つの文章にまとめて。『支援内容』として記録されている事柄は積極的に盛り込んでください。職員名や『利用者様は』などの主語は不要。おおよそ{char_limit}程度で作成してください。\n\n{recs}"
                        try:
                            # 🚀 確実に call_gemini_ai を使う！
                            st.session_state["monitoring_result"] = call_gemini_ai([prompt])
                        except Exception as e:
                            st.error(f"AI生成エラー: {e}")
                    else: st.warning("対象の記録がありません")
                else: st.warning("記録なし")
        
        if st.session_state.get("monitoring_result"):
            res_txt = st.text_area("結果（編集可能）", value=st.session_state["monitoring_result"], height=200)
            st.session_state["monitoring_result"] = res_txt
            st.code(res_txt, language="text")

    st.divider()
    back_to_top_button("hs_d")

# --- 4. 閲覧・統合画面 ---
def render_daily_view(supabase, cookie_manager, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    st.markdown("<div class='main-title'>📅 ケース記録閲覧・統合</div>", unsafe_allow_html=True)
    
    target_date = st.session_state.get("dv_target_date", now_tokyo.date())
    if target_date is None: target_date = now_tokyo.date()
    selected_date = st.date_input("日付選択", value=target_date)
    
    if f_code:
        t_start = tokyo_tz.localize(datetime.combine(selected_date, dt_time.min))
        try:
            res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at").execute()
            if res.data:
                df = pd.DataFrame(res.data)
                target_u = st.session_state.get("dv_target_user")
                
                for user in df["user_name"].unique():
                    with st.expander(f"👤 {user} 様", expanded=(user == target_u)):
                        user_recs = df[df["user_name"] == user]
                        ai_recs = user_recs[user_recs["staff_name"] == "AI統合記録"]
                        normal_recs = user_recs[user_recs["staff_name"] != "AI統合記録"]
                        
                        if not ai_recs.empty:
                            ai_rec = ai_recs.iloc[0]
                            with st.container(border=True):
                                col_txt, col_btn = st.columns([4, 1])
                                with col_txt:
                                    st.markdown("✨ **AI統合ケース記録**")
                                    st.write(ai_rec['content'])
                                with col_btn:
                                    if st.session_state.get("admin_authenticated"):
                                        if st.button("🗑️", key=f"ai_del_{ai_rec['id']}", help="AI記録を削除"):
                                            supabase.table("records").delete().eq("id", ai_rec['id']).execute(); st.rerun()
                        else:
                            if st.button(f"✨ 今日のまとめを生成して確定", key=f"gen_{user}"):
                                if not normal_recs.empty:
                                    with st.spinner("AI集計中..."):
                                        recs_text = "\n".join([r['content'] for _, r in normal_recs.iterrows()])
                                        prompt = f"今日の介護記録を一つの文章にまとめて。職員名や『利用者様は』などの主語は不要。\n\n{recs_text}"
                                        try:
                                            # 🚀 確実に call_gemini_ai を使う！
                                            summary = call_gemini_ai([prompt])
                                            c_num = normal_recs.iloc[0]['chart_number']
                                            dt = tokyo_tz.localize(datetime.combine(selected_date, dt_time(23, 59, 59)))
                                            supabase.table("records").insert({"facility_code": f_code, "chart_number": c_num, "user_name": user, "staff_name": "AI統合記録", "content": summary, "created_at": dt.isoformat()}).execute(); st.rerun()
                                        except Exception as e:
                                            st.error(f"AI生成エラー: {e}")

                        st.divider()
                        st.markdown("###### 📝 個別のケース記録")
                        for _, r in normal_recs.iterrows():
                            with st.container():
                                time_str = parse_jst(r['created_at'])
                                st.caption(f"🕒 {time_str} ({r['staff_name']})")
                                
                                edit_key = f"edit_active_{r['id']}"
                                if st.session_state.get(edit_key):
                                    new_txt = st.text_area("内容を修正", value=r['content'], key=f"ta_{r['id']}")
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        if st.button("💾 確定", key=f"sv_{r['id']}", type="primary"):
                                            supabase.table("records").update({"content": new_txt}).eq("id", r['id']).execute()
                                            st.session_state[edit_key] = False
                                            st.rerun()
                                    with c2:
                                        if st.button("❌ キャンセル", key=f"cc_{r['id']}"):
                                            st.session_state[edit_key] = False
                                            st.rerun()
                                else:
                                    st.write(r['content'])
                                    is_owner = (str(r['staff_name']) == str(my_name))
                                    is_admin = st.session_state.get("admin_authenticated")
                                    if is_owner or is_admin:
                                        c1, c2, _ = st.columns([1, 1, 4])
                                        with c1:
                                            if st.button("✏️ 編集", key=f"btn_ed_{r['id']}"):
                                                st.session_state[edit_key] = True
                                                st.rerun()
                                        with c2:
                                            if st.button("🗑️ 削除", key=f"btn_del_{r['id']}"):
                                                supabase.table("records").delete().eq("id", r['id']).execute()
                                                st.rerun()
                            st.markdown("---")
            else: st.info("記録なし")
        except Exception as e: st.error(f"エラー: {e}")

    st.divider()
    back_to_top_button("dv_d")

# --- 5. 管理者メニュー ---
def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    if not st.session_state.get("admin_authenticated"):
        res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res.data[0]['value'] if res.data else "8888"
        pw = st.text_input("パスワード", type="password")
        if st.button("認証"):
            if pw == cur_pw: st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("不一致")
        st.stop()
    
    t1, t2, t3, t4 = st.tabs(["👥 利用者管理", "👮 スタッフ管理", "⚙️ 設定", "🚫 セキュリティ"])
    with t1:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        with st.expander("🆕 新規登録"):
            with st.form("reg"):
                c, n, k = st.text_input("No"), st.text_input("氏名"), st.text_input("かな")
                if st.form_submit_button("登録"):
                    supabase.table("patients").insert({"facility_code":f_code, "chart_number":c, "user_name":n, "user_kana":k}).execute(); st.rerun()
        for p in res_p.data:
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1: st.write(f"No.{p['chart_number']} {p['user_name']}")
            with c2: 
                if st.button("修正", key=f"pe_{p['id']}"): st.session_state[f"pedit_{p['id']}"] = True
            with c3: 
                if st.button("削除", key=f"pd_{p['id']}"): supabase.table("patients").delete().eq("id", p['id']).execute(); st.rerun()
            if st.session_state.get(f"pedit_{p['id']}"):
                with st.form(f"f_{p['id']}"):
                    un, uk, uc = st.text_input("氏名", p['user_name']), st.text_input("かな", p['user_kana']), st.text_input("No", p['chart_number'])
                    if st.form_submit_button("確定"): supabase.table("patients").update({"user_name":un, "user_kana":uk, "chart_number":uc}).eq("id", p['id']).execute(); st.rerun()

    with t2:
        st.markdown("##### 👮 スタッフ管理")
        res_s = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        if res_s.data:
            staff_list = sorted(list(set([r['staff_name'] for r in res_s.data if r['staff_name'] and r['staff_name'] != "AI統合記録"])))
            for s in staff_list:
                is_b = len(supabase.table("blocked_devices").select("id").eq("staff_name", s).eq("facility_code", f_code).eq("is_active", True).execute().data) > 0
                c1, c2 = st.columns([3, 1])
                with c1: st.write(f"{'🚫' if is_b else '👤'} **{s}**")
                with c2:
                    if not is_b and st.button("ブロック", key=f"blk_{s}"):
                        supabase.table("blocked_devices").insert({"staff_name":s, "facility_code":f_code, "is_active":True, "device_id":"NAME_LOCK"}).execute(); st.rerun()
    with t3:
        np = st.text_input("新パスワード", type="password")
        if st.button("更新") and np:
            supabase.table("admin_settings").upsert({"facility_code":f_code, "key":"admin_password", "value":np}, on_conflict="facility_code,key").execute(); st.success("完了")
        res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        cur_l = int(res_l.data[0]['value']) if res_l.data else 30
        new_l = st.slider("表示件数", 10, 100, cur_l)
        if st.button("件数保存"):
            supabase.table("admin_settings").upsert({"facility_code":f_code, "key":"history_limit", "value":str(new_l)}, on_conflict="facility_code,key").execute(); st.rerun()
    with t4:
        res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        for b in res_b.data:
            c1, c2 = st.columns([3, 1])
            with c1: st.write(f"🚫 **{b['staff_name'] if b['staff_name'] else b['device_id']}**")
            with c2:
                if st.button("復帰", key=f"res_{b['id']}"):
                    supabase.table("blocked_devices").update({"is_active":False}).eq("id", b['id']).execute(); st.rerun()
    
    st.divider()
    c_out, c_top = st.columns(2)
    with c_out:
        if st.button("管理者終了", use_container_width=True): st.session_state["admin_authenticated"] = False; st.rerun()
    with c_top:
        back_to_top_button("ad_d2")