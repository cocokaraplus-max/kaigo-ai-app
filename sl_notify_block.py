def _sl_staff_line_ids(supabase, f_code, names):
    """職員名の一覧から、LINEのidを引く。返り値は [(名前, id), ...]。

    ★見つからない人・LINE未連携の人は黙って飛ばす。
      通知は「届けば助かる」もので、届かないことで業務が止まってはいけない。
    """
    out = []
    if not names:
        return out
    try:
        res = (supabase.table("staffs").select("staff_name,line_user_id")
               .eq("facility_code", f_code).eq("is_active", True).execute())
    except Exception as e:
        print("[login-device] 通知先の取得に失敗: %s" % e, flush=True)
        return out
    want = set(names)
    for s in (res.data or []):
        nm = (s.get("staff_name") or "").strip()
        uid = (s.get("line_user_id") or "").strip()
        if nm in want and uid:
            out.append((nm, uid))
    return out


def _sl_notify_admins_device_request(supabase, f_code, device_label, who):
    """端末の申請が来たことを、その事業所の管理者のLINEに知らせる。

    ★これが無いと、管理者は管理画面を【自分で見に行くまで】気づけない。
      職員は「申請したのに何も起きない」で止まり、電話や口頭で頼むことになる。
      仕組みの穴を人の口伝えで埋めさせていた。（HIROさん指摘 2026-08-30）

    ★通知が送れなくても、申請そのものは成立させる。
      ここで失敗を理由に申請を止めると、通知の不調が業務を止める。
    """
    try:
        names = get_admin_managers(supabase, f_code) or []
        targets = _sl_staff_line_ids(supabase, f_code, names)
        if not targets:
            print("[login-device] 管理者のLINE連絡先が見つからない（通知なし）", flush=True)
            return
        msg = ("【TASUKARU】ログイン端末の許可をお願いします\\n\\n"
               "端末: %s\\n"
               "頼んだ人: %s\\n\\n"
               "★この名前は申請した端末が自分で名乗ったものです。\\n"
               "　本人に確かめてから許可してください。\\n\\n"
               "管理者MENU →「ログイン端末の管理」から許可できます。"
               % (device_label or "（名前なし）", who or "（名乗りなし）"))
        for nm, uid in targets:
            _sl_line_push(uid, [{"type": "text", "text": msg}], "端末申請の知らせ")
    except Exception as e:
        # ★知らせられなくても申請は成立している。ここで例外を外へ出さない。
        print("[login-device] 申請の知らせに失敗: %s" % e, flush=True)


def _sl_notify_requester_approved(supabase, f_code, device_label, who):
    """端末を許可したことを、頼んだ人のLINEに知らせる。

    ★これが無いと、職員はいつ許可されたか分からず、
      何度も画面を開き直すか、管理者に電話で聞くことになる。

    ★名前は自己申告なので、職員として登録されている名前と一致したときだけ送る。
      一致しなければ何もしない（誰かに間違って送らない）。
    """
    try:
        who = (who or "").strip()
        if not who:
            return
        targets = _sl_staff_line_ids(supabase, f_code, [who])
        if not targets:
            return
        msg = ("【TASUKARU】ログイン端末が使えるようになりました\\n\\n"
               "端末: %s\\n\\n"
               "その端末で承認ログインの画面を開くと、名前の一覧が出ます。\\n"
               "★心当たりがないときは、管理者にご連絡ください。"
               % (device_label or "（名前なし）"))
        for nm, uid in targets:
            _sl_line_push(uid, [{"type": "text", "text": msg}], "許可の知らせ")
    except Exception as e:
        print("[login-device] 許可の知らせに失敗: %s" % e, flush=True)


