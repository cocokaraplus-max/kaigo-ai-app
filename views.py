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
    """TOP画面: 業務の入り口"""
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        if st.button("✍️ 記録を書く", use_container_width=True):
            st.session_state["page"] = "input"
            st.rerun()
    with col_m2:
        if st.button("📊 モニタリング生成", use_container_width=True):
            st.session_state["page"] = "history"
            st.rerun()
    
    if st.button("📅 ケース記録閲覧・統合", use_container_width=True):
        st.session_state["page"] = "daily_view"
        st.rerun()
    
    st.divider()
    
    # 管理者設定に基づく更新履歴の表示
    hist_limit = 30
    try:
        res_limit = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        if res_limit.data: hist_limit = int(res_limit.data[0]['value'])
    except: pass

    st.markdown(f"##### 📝 更新履歴 (最新{hist_limit}件)")
    try:
        res_hist = supabase.table("records").select("user_name, created_at").eq("facility_code", f_code).order("created_at", desc=True).limit(hist_limit).execute()
        if res_hist.data:
            with st.container(height=300):
                for r in res_hist.data:
                    if st.button(f"👤 {r['user_name']} ({r['created_at'][11:16]})", key=f"hist_{r['created_at']}_{uuid.uuid4()}", use_container_width=True):
                        st.session_state.update({"page": "daily_view", "dv_target_user": r['user_name']})
                        st.rerun()
        else:
            st.info("今日の記録はまだありません。")
    except:
        pass

    st.divider()
    
    if st.session_state.get("admin_authenticated"):
        if st.button("🛠️ 管理者メニュー (認証済み)", use_container_width=True):
            st.session_state["page"] = "admin_menu"
            st.rerun()
    else:
        if st.button("🛠️ 管理者メニュー", use_container_width=True):
            st.session_state["page"] = "admin_menu"
            st.rerun()

    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code")
        cookie_manager.delete("saved_my_name")
        st.session_state.clear()
        st.rerun()

def render_input(supabase, cookie_manager, f_code, my_name):
    """記録入力画面: AI連携"""
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("ip_u")
    is_edit = st.session_state.get("editing_record_id") is not None
    st.markdown(f"<div class='main-title'>{'📝 記録修正' if is_edit else '✍️ 記録入力'}</div>", unsafe_allow_html=True)
    
    # 利用者リストの取得
    p_opts = ["(未選択)"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data:
            p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}]" for r in res_p.data]
    except:
        st.error("利用者の抽出に失敗しました。")
    
    default_sel = st.session_state.get("edit_user_label", "(未選択)")
    sel = st.selectbox("👤 利用者を選択", p_opts, index=p_opts.index(default_sel) if default_sel in p_opts else 0, disabled=is_edit)
    record_date = st.date_input("📅 記録日", value=st.session_state.get("edit_date", now_tokyo.date()), disabled=is_edit)
    
    if not is_edit:
        imgs = st.file_uploader("📷 写真（最大5枚）", type=["jpg","png","jpeg"], accept_multiple_files=True)
        aud = st.audio_input("🎤 音声入力")
        if (imgs or aud) and st.button("✨ AI文章化", type="primary"):
            with st.spinner("AIが現場向けに要約中..."):
                try:
                    model = genai.GenerativeModel('models/gemini-2.0-flash')
                    prompt = "介護職が仲間に共有する申し送り口調（～です、～されています、等の丁寧な専門用語）で、事実を簡潔にまとめてください。職員名は不要です。主語は利用者様にしてください。"
                    contents = [prompt]
                    if imgs:
                        for i in imgs: contents.append(Image.open(i))
                    if aud:
                        contents.append({"mime_type": "audio/wav", "data": aud.getvalue()})
                    response = model.generate_content(contents)
                    st.session_state["edit_content"] = response.text.strip()
                    st.rerun()
                except Exception as e:
                    st.error(f"AIエラー: {e}")
    
    txt = st.text_area("記録内容", value=st.session_state.get("edit_content", ""), height=250)
    
    if st.button("💾 保存", use_container_width=True):
        if sel != "(未選択)" and txt:
            try:
                if is_edit:
                    supabase.table("records").update({"content": txt}).eq("id", st.session_state["editing_record_id"]).execute()
                else:
                    m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                    dt = tokyo_tz.localize(datetime.combine(record_date, datetime.now(tokyo_tz).time()))
                    supabase.table("records").insert({
                        "facility_code": f_code,
                        "chart_number": m.group(1),
                        "user_name": m.group(2),
                        "staff_name": my_name,
                        "content": txt,
                        "created_at": dt.isoformat()
                    }).execute()
                st.session_state.update({"page": "top", "editing_record_id": None, "edit_content": ""})
                st.rerun()
            except Exception as e:
                st.error(f"保存に失敗しました: {e}")
    back_to_top_button("ip_d")

def render_history(supabase, cookie_manager, f_code, my_name):
    """モニタリング生成画面: 1ヶ月要約"""
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 モニタリング生成</div>", unsafe_allow_html=True)
    
    p_opts = ["---"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data:
            p_opts += [f"(No.{r['chart_number']}) {r['user_name']}" for r in res_p.data]
    except: pass
    
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = sel.split(") ")[1]
        month_opts = [f"{now_tokyo.year}年{m:02d}月" for m in range(now_tokyo.month, now_tokyo.month-6, -1)]
        selected_month_str = st.selectbox("対象月", month_opts)
        
        if st.button("✨ 1ヶ月の申し送り文を生成", type="primary"):
            with st.spinner("AIが集計・要約中..."):
                t_y, t_m = int(selected_month_str[:4]), int(selected_month_str[5:7])
                s_date = tokyo_tz.localize(datetime(t_y, t_m, 1))
                e_date = (s_date + timedelta(days=32)).replace(day=1)
                res = supabase.table("records").select("content").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).execute()
                
                if res.data:
                    recs_text = "\n".join([r['content'] for r in res.data])
                    model = genai.GenerativeModel('models/gemini-2.0-flash')
                    prompt = f"以下の1ヶ月分の介護記録を、介護職員が仲間に報告する専門的な口調で、一つの連続した文章にまとめてください。職員の名前や『担当』といった言葉は一切含めないでください。主語は利用者様にしてください。\n\n【記録データ】\n{recs_text}"
                    st.session_state["monitoring_result"] = model.generate_content(prompt).text
                else:
                    st.warning("指定期間内に記録が見つかりませんでした。")
        
        if st.session_state.get("monitoring_result"):
            res_txt = st.text_area("生成結果（編集可能）", value=st.session_state["monitoring_result"], height=250)
            st.code(res_txt, language="text")

        if st.button("📜 この利用者の過去全履歴を表示"):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16]} ({r['staff_name']})"):
                    st.write(r['content'])
                    if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                        if st.button("✏️ 編集", key=f"ed_h_{r['id']}"):
                            st.session_state.update({
                                "page": "input",
                                "editing_record_id": r['id'],
                                "edit_content": r['content'],
                                "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]",
                                "edit_date": datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date()
                            })
                            st.rerun()
    back_to_top_button("hs_d")

def render_daily_view(supabase, cookie_manager, f_code, my_name):
    """日別閲覧 ＆ ケース記録自動統合機能"""
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 ケース記録閲覧・統合</div>", unsafe_allow_html=True)
    
    selected_date = st.date_input("日付選択", value=st.session_state.get("dv_target_date", now_tokyo.date()))
    
    if f_code:
        t_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
        try:
            # 修正したクエリ: asc=Trueの文法ミスを修正し時系列順に取得
            res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at").execute()
            
            if res.data:
                df = pd.DataFrame(res.data)
                target_u = st.session_state.get("dv_target_user")
                
                for user in df["user_name"].unique():
                    with st.expander(f"👤 {user} 様", expanded=(user == target_u)):
                        user_recs = df[df["user_name"] == user]
                        
                        # 🚀 ケース記録の自動統合機能
                        if st.button(f"✨ 今日の {user} 様の記録を一つにまとめる", key=f"gen_{user}_{selected_date}"):
                            with st.spinner("文章統合中..."):
                                recs_combined = "\n".join([r['content'] for _, r in user_recs.iterrows()])
                                model = genai.GenerativeModel('models/gemini-2.0-flash')
                                prompt = f"以下の今日の複数の介護記録を、介護職員が仲間に伝える口調で、一つの自然な文章にまとめてください。職員名は不要です。主語は利用者様にしてください。\n\n【今日の各記録】\n{recs_combined}"
                                summary = model.generate_content(prompt).text
                                st.info(f"**【AI統合ケース記録】**\n\n{summary}")
                                st.code(summary)
                        
                        st.divider()
                        
                        # 元の記録一覧
                        for _, r in user_recs.iterrows():
                            with st.container(border=True):
                                st.caption(f"🕒 {r['created_at'][11:16]} ({r['staff_name']})")
                                st.write(r['content'])
                                if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                                    if st.button("✏️ 編集", key=f"ed_dv_{r['id']}"):
                                        st.session_state.update({
                                            "page": "input",
                                            "editing_record_id": r['id'],
                                            "edit_content": r['content'],
                                            "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]",
                                            "edit_date": selected_date
                                        })
                                        st.rerun()
            else:
                st.info("選択された日付に記録はありません。")
        except Exception as e:
            st.error(f"閲覧エラー: {e}")
    back_to_top_button("dv_d")

def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    """管理者メニュー: 全機能（利用者・スタッフ・設定・セキュリティ）"""
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    
    # パスワード認証
    if not st.session_state.get("admin_authenticated"):
        try:
            res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
            cur_pw = res.data[0]['value'] if res.data else "8888"
            ad_pw_in = st.text_input("管理者パスワードを入力してください", type="password")
            if st.button("認証"):
                if ad_pw_in == cur_pw:
                    st.session_state["admin_authenticated"] = True
                    st.rerun()
                else:
                    st.error("パスワードが正しくありません。")
            st.stop()
        except:
            st.error("認証システムの読み込みに失敗しました。")
            st.stop()

    t1, t2, t3, t4 = st.tabs(["👥 利用者管理", "👮 スタッフ管理", "⚙️ 設定", "🚫 セキュリティ"])
    
    with t1:
        st.markdown("##### 👤 利用者の登録・修正・削除")
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        
        with st.expander("🆕 利用者を新規登録"):
            with st.form("reg_user", clear_on_submit=True):
                c = st.text_input("チャート番号 (No.)")
                n = st.text_input("氏名")
                k = st.text_input("ふりがな")
                if st.form_submit_button("登録実行"):
                    if c and n:
                        supabase.table("patients").insert({"facility_code": f_code, "chart_number": c, "user_name": n, "user_kana": k}).execute()
                        st.success(f"{n} 様を登録しました。")
                        st.rerun()
        
        if res_p.data:
            for p in res_p.data:
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1: st.write(f"**No.{p['chart_number']}** {p['user_name']}")
                with c2:
                    if st.button("修正", key=f"p_edit_{p['id']}"): st.session_state[f"pedit_active_{p['id']}"] = True
                with c3:
                    if st.button("削除", key=f"p_del_{p['id']}"):
                        supabase.table("patients").delete().eq("id", p['id']).execute()
                        st.rerun()
                
                if st.session_state.get(f"pedit_active_{p['id']}"):
                    with st.form(f"form_edit_{p['id']}"):
                        un = st.text_input("氏名", p['user_name'])
                        uk = st.text_input("かな", p['user_kana'])
                        uc = st.text_input("No", p['chart_number'])
                        if st.form_submit_button("更新を保存"):
                            supabase.table("patients").update({"user_name": un, "user_kana": uk, "chart_number": uc}).eq("id", p['id']).execute()
                            del st.session_state[f"pedit_active_{p['id']}"]
                            st.rerun()

    with t2:
        st.markdown("##### 👮 スタッフのアクセス制限（ブロック）")
        st.caption("退職者や異動者の名前をリストから選択してブロックできます。")
        res_staff = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        if res_staff.data:
            unique_staff = sorted(list(set([r['staff_name'] for r in res_staff.data if r.get('staff_name')])))
            for s in unique_staff:
                res_check = supabase.table("blocked_devices").select("id").eq("staff_name", s).eq("facility_code", f_code).eq("is_active", True).execute()
                is_blocked = len(res_check.data) > 0
                col_s1, col_s2 = st.columns([3, 1])
                with col_s1: st.write(f"{'🚫' if is_blocked else '👤'} **{s}** {'(ブロック中)' if is_blocked else ''}")
                with col_s2:
                    if not is_blocked:
                        if st.button("ブロック", key=f"blk_btn_{s}"):
                            supabase.table("blocked_devices").insert({"staff_name": s, "facility_code": f_code, "is_active": True, "device_id": "NAME_LOCK"}).execute()
                            st.rerun()

    with t3:
        st.markdown("##### ⚙️ パスワード ＆ 表示件数設定")
        new_pw = st.text_input("新しい管理者パスワード", type="password")
        conf_pw = st.text_input("パスワード（確認）", type="password")
        if st.button("パスワードを更新する"):
            if new_pw == conf_pw and new_pw:
                supabase.table("admin_settings").upsert({"facility_code": f_code, "key": "admin_password", "value": new_pw}, on_conflict="facility_code,key").execute()
                st.success("パスワードを更新しました。")
            else: st.error("パスワードが一致しません。")
        
        st.divider()
        res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        cur_limit = int(res_l.data[0]['value']) if res_l.data else 30
        new_limit = st.slider("履歴表示人数（TOP画面）", 10, 100, cur_limit, 5)
        if st.button("表示件数を保存"):
            supabase.table("admin_settings").upsert({"facility_code": f_code, "key": "history_limit", "value": str(new_limit)}, on_conflict="facility_code,key").execute()
            st.success("保存しました。")

    with t4:
        st.markdown("##### 🔓 ブロック解除 ＆ 復帰")
        st.caption("制限がかかっている端末やスタッフを復帰させます。")
        res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        if res_b.data:
            for b in res_b.data:
                target = b['staff_name'] if b['staff_name'] else b['device_id']
                col_b1, col_b2 = st.columns([3, 1])
                with col_b1: st.write(f"🚫 **{target}**")
                with col_b2:
                    if st.button("復帰させる", key=f"restore_{b['id']}"):
                        supabase.table("blocked_devices").update({"is_active": False}).eq("id", b['id']).execute()
                        st.rerun()
        else:
            st.info("現在、制限中のスタッフ・端末はありません。")
    
    if st.button("管理者モードを終了する"):
        st.session_state["admin_authenticated"] = False
        st.session_state["page"] = "top"
        st.rerun()
    back_to_top_button("ad_d")