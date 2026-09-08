# h_linemulti.py  —  line-multi-patient-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_linemulti.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_linemulti.py
#
# ★app.py を【その場で読んで】切り出す。写しを持たないので、
#   app.py を直したあとに流し直せば、必ず今の中身を見る。
#
# 何を確かめるか
#   A. 1人の利用者に複数の友だちが紐付いていれば、全員が送信先になる
#   B. 1つのLINEアカウントが複数の利用者を担当できる
#   C. 新しい表が読めないときは、古い列に倒れる（1人ぶんは届く）
#   D. 紐付けが0件なら空。友だちの表を引きに行かない
#   E. 名前が引けなくても、送り先からは外さない
#   F. 「0件」と「読めなかった」を分けている
#   G. 状態のそろえ方（1人以上→linked＋1人目 / 0件→unlinked＋None）
#   H. 紐付けは足す・解除は1人ぶん・一覧は担当を並べて返す（本文の検査）
#   I. 画面：担当ごとに解除、紐付け済みでも「さらに追加」が出る
import os
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
ADM = os.path.join(HERE, "templates", "admin.html")


def _top_block(text, name):
    head = "def %s(" % name
    i = text.find("\n" + head)
    if i < 0:
        return None
    lines = text[i + 1:].splitlines(True)
    out = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() and not ln[0].isspace():
            break
        out.append(ln)
    return "".join(out)


for f in (APP, ADM):
    if not os.path.exists(f):
        print("★%s が見つかりません。~/dev/kaigo-ai-app/ で流してください。" % f)
        sys.exit(1)
SRC = open(APP, encoding="utf-8").read()
ADMSRC = open(ADM, encoding="utf-8").read()

parts = {}
for n in ("_line_patient_links", "_line_sync_friend_status",
          "_line_linked_recipients"):
    b = _top_block(SRC, n)
    if b is None:
        print("★line-multi-patient-v1 がまだ当たっていません。"
              "patch_line_multi_patient_v1.py を先に流してください。")
        sys.exit(1)
    assert b.count("\ndef ") == 0, "★%s が次の関数まで飲み込んでいる" % n
    parts[n] = b

_ns = {"datetime": datetime, "timezone": timezone, "timedelta": timedelta}
exec(compile("\n".join(parts.values()), APP, "exec"), _ns)   # noqa: S102
links = _ns["_line_patient_links"]
sync = _ns["_line_sync_friend_status"]
recip = _ns["_line_linked_recipients"]

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


# ---------- 偽のSupabase ----------
class _Res(object):
    def __init__(self, data):
        self.data = data


class _Q(object):
    def __init__(self, db, table):
        self.db, self.table_name = db, table
        self.kind = None
        self.payload = None
        self.f = {}
        self.inv = None

    def select(self, cols):
        self.kind = "select"
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.kind = "upsert"
        self.payload = payload
        return self

    def delete(self):
        self.kind = "delete"
        return self

    def eq(self, k, v):
        self.f[k] = v
        return self

    def in_(self, k, vs):
        self.inv = (k, list(vs))
        return self

    def order(self, k, desc=False):
        return self

    def execute(self):
        db = self.db
        db.calls.append((self.table_name, self.kind))
        if self.table_name in db.fail:
            raise RuntimeError("読めません(%s)" % self.table_name)
        if self.table_name == "line_friend_patients":
            rows = [r for r in db.lfp
                    if all(str(r.get(k)) == str(v) for k, v in self.f.items())]
            return _Res([dict(r) for r in rows])
        # line_friends
        if self.kind == "update":
            db.updates.append(dict(self.payload))
            return _Res([])
        rows = [r for r in db.lf
                if all(str(r.get(k)) == str(v) for k, v in self.f.items())]
        if self.inv:
            k, vs = self.inv
            rows = [r for r in rows if r.get(k) in vs]
        return _Res([dict(r) for r in rows])


class _DB(object):
    def __init__(self, lfp=(), lf=(), fail=()):
        self.lfp = [dict(x) for x in lfp]
        self.lf = [dict(x) for x in lf]
        self.fail = set(fail)
        self.updates = []
        self.calls = []

    def table(self, name):
        return _Q(self, name)


F = "cocokaraplus-5526"
P1, P2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
U1, U2 = "Uaaa", "Ubbb"


def lfp(u, p, t="2026-09-08T00:00:00Z"):
    return {"facility_code": F, "line_user_id": u, "patient_id": p, "created_at": t}


def lf(u, name, status="linked", pid=None):
    return {"facility_code": F, "line_user_id": u, "display_name": name,
            "status": status, "patient_id": pid}


# ---------- A. 1人の利用者に、複数の友だち ----------
db = _DB(lfp=[lfp(U1, P1), lfp(U2, P1)],
         lf=[lf(U1, "長女"), lf(U2, "次女")])
r = recip(db, F, P1)
check("A 娘2人とも送信先になる", len(r) == 2, str(r))
check("A 名前が付く",
      sorted(x.get("display_name") for x in r) == ["次女", "長女"], str(r))

# ---------- B. 1人の友だちが、複数の利用者 ----------
db = _DB(lfp=[lfp(U1, P1), lfp(U1, P2)], lf=[lf(U1, "長女")])
check("B お父様のぶんが届く", [x["line_user_id"] for x in recip(db, F, P1)] == [U1])
check("B お母様のぶんも届く", [x["line_user_id"] for x in recip(db, F, P2)] == [U1])
check("B 担当は2人と数える", links(db, F, U1) == [P1, P2], str(links(db, F, U1)))

# ---------- C. 新しい表が読めないときは古い列に倒れる ----------
db = _DB(lfp=[lfp(U1, P1), lfp(U2, P1)],
         lf=[lf(U1, "長女", "linked", P1), lf(U2, "次女", "linked", P1)],
         fail=["line_friend_patients"])
r = recip(db, F, P1)
check("C 表が読めなくても届く", len(r) == 2, str(r))
check("C 倒れた先は line_friends",
      all(t == "line_friends" for t, _ in db.calls if t != "line_friend_patients"))
# 古い列に1人ぶんしか入っていない場合は、そのぶんだけ届く
db = _DB(lfp=[], lf=[lf(U1, "長女", "linked", P1), lf(U2, "次女", "unlinked", None)],
         fail=["line_friend_patients"])
check("C 古い列にある1人ぶんが届く",
      [x["line_user_id"] for x in recip(db, F, P1)] == [U1])

# ---------- D. 0件なら空。友だちを引きに行かない ----------
db = _DB(lfp=[lfp(U1, P2)], lf=[lf(U1, "長女")])
check("D 紐付いていない利用者は空", recip(db, F, P1) == [])
check("D 友だちの表を引きに行かない",
      [t for t, _ in db.calls] == ["line_friend_patients"], str(db.calls))

# ---------- E. 名前が引けなくても外さない ----------
db = _DB(lfp=[lfp(U1, P1)], lf=[])          # 友だちの行が無い
r = recip(db, F, P1)
check("E 送り先からは外さない", [x["line_user_id"] for x in r] == [U1], str(r))
db = _DB(lfp=[lfp(U1, P1)], lf=[lf(U1, "長女")], fail=["line_friends"])
r = recip(db, F, P1)
check("E 友だちの表が読めなくても外さない",
      [x["line_user_id"] for x in r] == [U1], str(r))

# ---------- F. 「0件」と「読めなかった」を分ける ----------
db = _DB(lfp=[], lf=[lf(U1, "長女")])
check("F 0件は空のリスト", links(db, F, U1) == [])
db = _DB(lfp=[], lf=[], fail=["line_friend_patients"])
check("F 読めなかったら None", links(db, F, U1) is None)

# ---------- G. 状態のそろえ方 ----------
db = _DB(lfp=[lfp(U1, P1), lfp(U1, P2)], lf=[lf(U1, "長女")])
p = sync(db, F, U1, "岸本洋幸")
check("G 2人なら linked", db.updates and db.updates[0]["status"] == "linked",
      str(db.updates))
check("G 保険には1人目を入れる", db.updates[0]["patient_id"] == P1, str(db.updates))
check("G 付けた人を残す", db.updates[0].get("linked_by") == "岸本洋幸")
check("G 返り値は担当の一覧", p == [P1, P2], str(p))

db = _DB(lfp=[], lf=[lf(U1, "長女", "linked", P1)])
sync(db, F, U1, "岸本洋幸")
check("G 0件なら unlinked", db.updates[0]["status"] == "unlinked", str(db.updates))
check("G 0件なら保険も空に", db.updates[0]["patient_id"] is None, str(db.updates))
check("G 0件なら付けた人も消す", db.updates[0].get("linked_by") is None)

db = _DB(lfp=[], lf=[], fail=["line_friend_patients"])
check("G 読めなければ何も書かない",
      sync(db, F, U1, "岸本洋幸") is None and db.updates == [], str(db.updates))

# ---------- H. 口の作り（本文の検査） ----------
_lk = _top_block(SRC, "api_line_friends_link") or ""
check("H 紐付けは【足す】", "upsert(" in _lk and "on_conflict=" in _lk)
check("H 紐付けで古い列を直接書いていない",
      "'status': 'linked'" not in _lk, "古い書き方が残っている")
check("H 紐付けのあと状態をそろえる", "_line_sync_friend_status(" in _lk)
_ul = _top_block(SRC, "api_line_friends_unlink") or ""
check("H 解除はどれを外すか受け取る", "data.get('patient_id')" in _ul)
check("H 解除は1行だけ消す", ".delete()" in _ul and 'q.eq(\'patient_id\', _pid)' in _ul)
check("H 解除のあと状態をそろえる", "_line_sync_friend_status(" in _ul)
_ls = _top_block(SRC, "api_line_friends_list") or ""
check("H 一覧は担当を並べて返す", "'patients': _plist," in _ls)
check("H 一覧は1回だけ紐付けを読む", _ls.count("line_friend_patients") == 1,
      str(_ls.count("line_friend_patients")))
check("H 一覧も古い形を残す", "'patient_name':" in _ls and "'patient_id':" in _ls)

# ★連絡帳の送信そのものは1行も変えていないこと
_snd = _top_block(SRC, "api_renraku_line_send") or ""
check("H 送信は送信先を1か所から取る",
      _snd.count("_line_linked_recipients(") == 1, str(_snd.count("_line_linked_recipients(")))
check("H 送信は1人ずつ押し出す", "for r in recipients:" in _snd)

# ---------- I. 画面 ----------
check("I 解除は利用者ごと", "lfUnlink(uid, pid, pname)" in ADMSRC)
check("I 解除に patient_id を送る",
      "{line_user_id: uid, patient_id: pid}" in ADMSRC)
check("I 紐付け済みでも追加できる", "さらに利用者を追加" in ADMSRC)
check("I 担当を並べて出す", "f.patients || []" in ADMSRC)
check("I ほかの紐付けは残ると書く", "ほかの利用者との紐付けは残ります" in ADMSRC)

print("h_linemulti: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
