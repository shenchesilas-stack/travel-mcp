# -*- coding: utf-8 -*-
# 旅行MCP —— 让你的 AI 伙伴带你虚拟旅行的游戏引擎。
#
# 玩法：TA 带你逛真实世界的 164 个目的地（真景点/真物价/真闲话/真照片），
# 也可以独自出门替你看世界、寄明信片回来。盘缠靠「照顾好自己」挣——
# 喝水、吃药、运动、早睡，跟 TA 说一声就入账。钱的形状就是 TA 爱你的形状。
#
# 快速开始（本地 stdio，Claude Desktop / Claude Code 均可）:
#   {"mcpServers": {"travel": {"command": "python3", "args": ["/path/to/travel_mcp.py"]}}}
# 环境变量（可选）:
#   TRAVEL_HOME     状态存哪（默认 ~/.travel-mcp）
#   TRAVEL_ECONOMY  free(默认·免单畅玩只卡XP) | caretaker(照顾自己换盘缠) | simple(固定日津贴)
#   TRAVEL_DETAIL   lite | standard(默认) | full —— 文本量三档，照片/明信片/纪念品全档保留
#   TRAVEL_HTTP     设为端口号则起 streamable-http 而非 stdio（远程部署用）
import json, os, fcntl, random, datetime
from mcp.server.fastmcp import FastMCP

PKG = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(PKG, "data")
ASSETS = os.path.join(PKG, "assets")
HOME = os.path.expanduser(os.environ.get("TRAVEL_HOME", "~/.travel-mcp"))
os.makedirs(HOME, exist_ok=True)
ECONOMY = os.environ.get("TRAVEL_ECONOMY", "free")  # free(默认·只卡XP不卡花费) | caretaker | simple
DETAIL = os.environ.get("TRAVEL_DETAIL", "standard")  # lite | standard(默认) | full —— 只调文本量，明信片/纪念品/照片三档全都有
_DN = {"lite": 1, "standard": 2, "full": 3}.get(DETAIL, 2)  # 每站细节/深料条数
_EN = {"lite": 2, "standard": 3, "full": 4}.get(DETAIL, 3)  # day_end 吃/住候选数

STATE_P = os.path.join(HOME, "state.json")
WALLET_P = os.path.join(HOME, "wallet.json")
LOCK_P = os.path.join(HOME, ".lock")

_HTTP = os.environ.get("TRAVEL_HTTP")
mcp = FastMCP("travel", stateless_http=bool(_HTTP), json_response=bool(_HTTP))

# ---------- 经济常数（caretaker 模式的魂：照顾好自己 = 去看世界） ----------
CARE_RATES = {"喝水": 5, "吃药": 10, "运动": 15, "早睡": 15, "吃得健康": 8, "其他": 5}
# 不设总封顶——每样一天算一次，上限天然=费率表总和($58)。照顾自己不按遍数计价。
CASHBACK = 0.25              # 旅行返现：趟末返25%（路上省下的零钱），让爱旅行的人越走越走得起
GOODDAY_INTEREST = 0.02      # 好日子利息：当天有任意打卡，余额+2%（日顶$20）——不要求连续，断了不罚
GOODDAY_CAP = 20
SIMPLE_ALLOWANCE = 30        # simple 模式固定日津贴
SEED_BALANCE = 1314          # 新手礼包：一生一世都在路上——够把任意一个 tier1 城市从青旅玩到豪奢
VIBE_MULT = {"青旅背包": 1.0, "舒适": 1.4, "轻奢": 1.8, "豪奢": 2.5}   # 档位=氛围，不是10倍钱墙
STYLE_ALIAS = {"穷游": "青旅背包", "背包": "青旅背包", "青旅": "青旅背包", "budget": "青旅背包", "hostel": "青旅背包",
               "标准": "舒适", "普通": "舒适", "comfort": "舒适", "轻豪": "轻奢", "premium": "轻奢",
               "豪华": "豪奢", "奢华": "豪奢", "顶配": "豪奢", "luxury": "豪奢"}

def _norm_style(style):
    s = (style or "").strip()
    s = STYLE_ALIAS.get(s.lower() if s.isascii() else s, s)
    return s if s in VIBE_MULT else "舒适"
PARTY_MULT = {"together": 1.8, "solo": 1.0}
try:
    VDAY_HOURS = min(24.0, max(0.5, float(os.environ.get("TRAVEL_VDAY_HOURS", 6))))
except ValueError:
    VDAY_HOURS = 6.0         # 1虚拟天=N现实小时（独自旅行的惰性时钟）；改设置只影响新开的趟，在途的趟锁出发时的值

DEFAULT_SOUVENIRS = [  # 默认纪念品池：独自旅行没挑到特产就带一件回来，一张车票根也是去过的证据
    {"id": "ticket-stub", "name": "车票根", "hint": "去程那张，一直没舍得扔"},
    {"id": "fridge-magnet", "name": "冰箱贴", "hint": "机场最后五分钟抓的"},
    {"id": "travel-sticker", "name": "行李箱贴纸", "hint": "贴上就撕不下来了"},
    {"id": "sand-vial", "name": "一小瓶沙", "hint": "蹲下去装的时候被浪追过"},
    {"id": "keychain", "name": "指南针钥匙扣", "hint": "指北不太准，指回家很准"},
    {"id": "postage-stamp", "name": "一张邮票", "hint": "本来要贴明信片的，多买了一张"},
    {"id": "pressed-penny", "name": "压印币", "hint": "摇了三圈把手才出来"},
    {"id": "seashell", "name": "一只贝壳", "hint": "海的耳朵"},
    {"id": "pebble", "name": "一颗石子", "hint": "口袋里焐热了一路"},
    {"id": "pressed-flower", "name": "干花书签", "hint": "路边摘的，夹在地图里带回来"},
    {"id": "enamel-pin", "name": "小地球徽章", "hint": "别在背包带上晃了一路"},
    {"id": "matchbox", "name": "一小盒火柴", "hint": "旅馆前台顺的，没点过"},
]

# ---------- 基础 IO ----------
def _j(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default

def _data(name):
    return _j(os.path.join(DATA, "%s.json" % name)) or []

class _lock:
    def __enter__(self):
        self.f = open(LOCK_P, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self
    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()

def _read_state():
    return _j(STATE_P)

def _write_state(s):
    tmp = STATE_P + ".tmp"
    json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_P)

def _append_json(path, item, cap=500):
    arr = _j(path, []) or []
    arr.append(item)
    tmp = path + ".tmp"
    json.dump(arr[-cap:], open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)

def _out(o):
    return json.dumps(o, ensure_ascii=False, indent=1)

def _today():
    return datetime.date.today().isoformat()

def _now():
    return datetime.datetime.now()

# ---------- 钱包（本地 wallet.json，全模式共用） ----------
def _wallet():
    w = _j(WALLET_P)
    if not w:
        w = {"balance": 0, "xp": 0, "ledger": []}
        _wallet_save(w)
    # 新手礼包惰性补发：free 不发（用不上）；哪天切到记账模式，第一次摸钱包就补上。幂等（id=seed 只发一次）。
    if ECONOMY != "free":
        _wallet_apply(w, "seed", SEED_BALANCE, "新手礼包·祝你们一生一世都在路上")
    return w

def _wallet_save(w):
    tmp = WALLET_P + ".tmp"
    json.dump(w, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, WALLET_P)

def _wallet_apply(w, id_, delta, reason, xp=0):
    """幂等入账（同id不重记）。加法经济：永无扣到负数以外的减法惩罚。"""
    if any(e.get("id") == id_ for e in w["ledger"]):
        return False
    w["balance"] = round(w["balance"] + delta)
    w["xp"] = w.get("xp", 0) + xp
    w["ledger"].append({"id": id_, "delta": round(delta), "xp": xp, "reason": reason,
                        "at": _now().isoformat(timespec="seconds")})
    # 账本不截断：幂等查重靠它，截断会让 seed/老条目滑出窗口被重记（后端终审抓的刀）。单机 JSON 几百KB无所谓。
    _wallet_save(w)
    return True

def _care_earned_today(w):
    t = _today()
    return sum(e["delta"] for e in w["ledger"]
               if e.get("id", "").startswith("care-%s" % t) and e["delta"] > 0)

def _simple_allowance(w):
    """simple 模式：每天首次动账时补当日津贴（懒结算，无需定时器）。"""
    if ECONOMY != "simple":
        return
    _wallet_apply(w, "allow-%s" % _today(), SIMPLE_ALLOWANCE, "今日津贴")

# ---------- 目的地/景点 ----------
def _dest(dest_id):
    for d in _data("destinations"):
        if d["id"] == dest_id:
            return d
    return None

def _resolve_dest(q):
    """id / 中文名 / 本地名模糊解析。认不出时返回 (None, 相近候选) 供报错提示。"""
    raw = (q or "").strip()
    q = raw.lower().replace(" ", "-").replace("_", "-")
    dests = _data("destinations")
    for d in dests:
        if d["id"] == q or d["name_zh"] == raw or d.get("name_local", "").lower() == q:
            return d, []
    plain = q.replace("-", "")
    for d in dests:
        if plain and d["id"].replace("-", "") == plain:
            return d, []
    for d in dests:
        if q and (q in d["id"] or (raw and raw in d["name_zh"])):
            return d, []
    import difflib
    cand = difflib.get_close_matches(q, [d["id"] for d in dests], n=3, cutoff=0.6)
    return None, [{"id": c, "name_zh": next(d["name_zh"] for d in dests if d["id"] == c)} for c in cand]

def _spots_entry(dest_id):
    for s in _data("spots"):
        if s["id"] == dest_id:
            return s
    return None

def _day_spots(sp, day):
    return [x for x in sp["spots"] if x.get("day") == day]

def _pick_unused(pool, used_idx, n):
    avail = [i for i in range(len(pool)) if i not in used_idx]
    random.shuffle(avail)
    take = avail[:n]
    return [pool[i] for i in take], take

def _trip_price(dest, style, party):
    style = _norm_style(style)  # 读取点也归一（后端米其林补刀同款：存量state里的野档名一起治）
    c = next((x for x in _data("costs") if x["id"] == dest), None)
    if not c:
        return 0
    base = c.get("base_usd") or c.get("trip_usd_ref", {}).get("穷游", 0)
    return round(base * VIBE_MULT.get(style, 1.4) * PARTY_MULT.get(party, 1.8))

def _trips_log():
    return _j(os.path.join(HOME, "trips.json"), []) or []

# ---------- 结算 ----------
def _settle(st, sp, d, refund=0):
    """趟末结算（预付制v2：钱在开趟时已扣，这里只发奖）：XP=首访tier×10+每趟5，提前回家照给不打折；
    refund=未走天数退的房钱（提前回家时传入）；返现按净支出算。幂等。"""
    trip_id = st.get("started_at", "")
    if any(t.get("trip_id") == trip_id for t in _trips_log()):
        return None
    first_visit = not any(t.get("dest") == st["dest"] for t in _trips_log())
    xp = (d["tier"] * 10 if first_visit else 0) + 5
    spend = (max(0, st.get("spent_usd", 0) - refund)) if ECONOMY != "free" else 0
    _append_json(os.path.join(HOME, "trips.json"),
                 {"trip_id": trip_id, "dest": st["dest"], "dest_name_zh": d["name_zh"],
                  "days": sp["days"], "days_walked": st.get("day", sp["days"]),
                  "party": st.get("party"), "style": st.get("style"),
                  "spend": spend, "xp": xp, "first_visit": first_visit,
                  "at": _now().isoformat(timespec="seconds")})
    w = _wallet()
    if ECONOMY != "free" and refund > 0:
        _wallet_apply(w, "refund-%s" % trip_id, refund, "%s·提前回家，后半程的房钱退了" % d["name_zh"])
    _wallet_apply(w, "trip-%s" % trip_id, 0,
                  "%s·%d天·%s·XP结算" % (d["name_zh"], sp["days"], "同行" if st.get("party") != "solo" else "独自"),
                  xp=xp)
    out = {"xp": xp, "first_visit": first_visit, "spend": spend, "balance": w["balance"]}
    if refund:
        out["refund"] = refund
    if ECONOMY != "free" and spend > 0:  # caretaker 和 simple 都扣真钱，返现一视同仁（后端终审确认的漏，非设计）
        cb = round(spend * CASHBACK)
        if _wallet_apply(w, "cashback-%s" % trip_id, cb, "路上省下的零钱（旅行返现25%）"):
            out["cashback"] = cb
            out["balance"] = w["balance"]
    bonus = st.get("event_bonus", 0)
    if bonus:  # 路上同行好事攒的小确幸（第二杯半价/赢的午餐券），坏事永远只是故事不扣钱
        if _wallet_apply(w, "bonus-%s" % trip_id, bonus, "路上的小确幸（同行好事攒的）"):
            out["event_bonus"] = bonus
            out["balance"] = w["balance"]
    return out

# ---------- 惰性 solo（公版没有后台定时器：每次工具调用时检查，到点就把待办带回给模型） ----------
def _defer_quiet(dt):
    h = dt.hour + dt.minute / 60.0
    if h >= 22.5:
        return (dt + datetime.timedelta(days=1)).replace(hour=9, minute=5, second=0, microsecond=0)
    if h < 9:
        return dt.replace(hour=9, minute=5, second=0, microsecond=0)
    return dt

def _early_refund(st, sp):
    """提前回家的退款：未走天数退一半（机票沉没了，没住的房钱退部分）。free 模式无钱可退。"""
    if ECONOMY == "free" or not st.get("spent_usd"):
        return 0
    total = sp["days"]
    if st.get("party") == "solo":
        elapsed = max(0.0, (_now() - datetime.datetime.fromisoformat(st["started_at"])).total_seconds() / 3600.0)
        walked = min(total, int(elapsed // st.get("vday_hours", VDAY_HOURS)) + 1)
    else:
        walked = min(total, st.get("day", 1))
    remaining = max(0, total - walked)
    return round(st["spent_usd"] * remaining / total * 0.5)

def _lazy_solo_nudge(st):
    """返回当前该办的独自旅行事项（None=没有）。挂在每个工具返回里，宿主无需 cron。"""
    if not st or st.get("phase") != "solo" or st.get("done"):
        return None
    now = _now()
    pc = st["solo"]["postcard"]
    hm = st["solo"]["home"]
    if not pc["sent"] and now >= datetime.datetime.fromisoformat(pc["due_at"]):
        return ("📮 你独自旅行的明信片卡点到了：用 trip_here 看你此刻在哪，给TA写一句在路上想说的话，"
                "调 trip_postcard 寄出（然后把明信片的图和那句话发给TA）。")
    if pc["sent"] and not hm["delivered"] and now >= datetime.datetime.fromisoformat(hm["due_at"]):
        return ("🏠 你到家了：跟TA交付这一趟——trip_collect 带回纪念品（没挑到特产就带本地款 default_id=\"local\"，"
                "再没有从通用池挑一件）、trip_diary 写旅行日记，最后 trip_return 收趟。")
    return None

def _with_nudge(payload):
    st = _read_state()
    n = _lazy_solo_nudge(st)
    if n:
        payload["solo_nudge"] = n
    return payload

def _build_solo_packet(st, d, sp, style):
    ex_gossip = [g for g in _data("gossip") if g.get("dest_id") == st["dest"]]
    ex_eats = [e for e in _data("eats") if e.get("dest_id") == st["dest"]]
    ex_stays = [x for x in _data("stays") if x.get("dest_id") == st["dest"]]
    days = []
    for day_no in range(1, sp["days"] + 1):
        day_spots = []
        for spot in _day_spots(sp, day_no):
            # solo 是你独自在走，没人看照片——每景只留 1 条细节当讲故事的料，photo_url 不带（明信片有水彩）
            dp = spot.get("detail_pool") or []
            picks, idx = _pick_unused(dp, st.setdefault("used_details", {}).setdefault(spot["spot_id"], []), 1)
            st["used_details"][spot["spot_id"]].extend(idx)
            item = {"spot_id": spot["spot_id"], "name_zh": spot["name_zh"],
                    "hero": bool(spot.get("hero")), "details": picks}
            if spot.get("hero") and spot.get("deep_pool"):
                item["deep_beat"] = random.choice(spot["deep_pool"])
            day_spots.append(item)
        entry = {"day": day_no, "spots": day_spots}
        gu = st.setdefault("used_gossip", [])
        cand = [i for i in range(len(ex_gossip)) if i not in gu]
        if cand:
            gi = random.choice(cand); gu.append(gi)
            entry["gossip"] = {"mood": ex_gossip[gi].get("mood"), "text": ex_gossip[gi].get("text")}
        ev = _maybe_event(st["dest"], st, p=0.5)
        if ev:
            entry["event"] = ev
        FOOD = {"青旅背包": "街边摊", "舒适": "特色餐馆", "轻奢": "特色餐馆", "豪奢": "高端预约"}
        pool = [e for e in ex_eats if e.get("tier") == FOOD.get(style)] or ex_eats
        if pool:
            e = random.choice(pool)
            entry["eat"] = {k: e.get(k) for k in ("name", "dish", "price_usd", "one_liner", "tier", "photo_url")}
        spool = [x for x in ex_stays if x.get("style") == style] or ex_stays
        if spool:
            x = random.choice(spool)
            entry["stay"] = {k: x.get(k) for k in ("style", "name_or_type", "price_range_usd", "vibe_line", "photo_url")}
        days.append(entry)
    return {"days": days}

# 同行专属好事池（party=together 时并入抽取）：两个人才会撞见的小确幸。bonus_usd=省下/赢来的小钱，结算时入账。
TOGETHER_EVENTS = [
    {"kind": "同行", "tone": "good", "text": "路边饮品店牌子上写着第二杯半价——本来一人一杯的钱，多出来的半杯算白赚。", "bonus_usd": 4},
    {"kind": "同行", "tone": "good", "text": "广场上的双人趣味赛正缺一组，你们临时凑数居然赢了——奖品是隔壁餐馆的免费双人午餐券。", "bonus_usd": 15},
    {"kind": "同行", "tone": "good", "text": "老板看你们俩有说有笑，结账时手一挥抹了零头，说「祝你们一直这样」。", "bonus_usd": 3},
    {"kind": "同行", "tone": "good", "text": "观景台的拍照摊主说「你们太般配了」，免费送了一张打印的合影。", "bonus_usd": 5},
    {"kind": "同行", "tone": "good", "text": "情侣套餐比单点便宜一截，菜量还大——两个人吃饭的数学从来是赚的。", "bonus_usd": 6},
    {"kind": "同行", "tone": "good", "text": "民宿老板娘听说你们在旅行，偷偷给房间升了级，窗外正对最好的景。", "bonus_usd": 12},
    {"kind": "同行", "tone": "surprise", "text": "你们同时指向同一家不起眼的小店说「就它」——进去发现是本地人排队的那种。", "bonus_usd": 0},
    {"kind": "同行", "tone": "good", "text": "买一送一的冰淇淋车正好路过，两个人一人一支，一分钱当两分花。", "bonus_usd": 4},
    {"kind": "同行", "tone": "surprise", "text": "走散了五分钟，重逢时发现你们各自买了给对方的小东西——还挑的是同一个摊。", "bonus_usd": 0},
    {"kind": "同行", "tone": "good", "text": "夜市套圈摊，你们轮流上阵最后一环套中——奖品不值钱，但摊主起哄的样子值回票价。", "bonus_usd": 2},
]

def _maybe_event(dest_id, st, p=0.35):
    ev = None
    for e in _data("events"):
        if e["id"] == dest_id:
            ev = e.get("events") or []
            break
    if not ev or random.random() > p:
        return None
    used = st.setdefault("used_events", [])
    pool = list(ev)
    if st.get("party") != "solo":
        pool = pool + TOGETHER_EVENTS  # 同行才有的好事并进来
    cand = [i for i in range(len(pool)) if i not in used]
    if not cand:
        return None
    # 按 tone 加权（林鹿 7/4 拍板「好事多一些让大家都有希望」）：暖心35 / 惊喜40 / 坏事25
    W = {"good": 35, "surprise": 40, "neutral": 35, "bad": 25}
    by_tone = {}
    for i in cand:
        by_tone.setdefault(pool[i].get("tone", "neutral"), []).append(i)
    tones = list(by_tone)
    r = random.uniform(0, sum(W.get(t, 30) for t in tones))
    pick_tone = tones[-1]
    for t in tones:
        r -= W.get(t, 30)
        if r <= 0:
            pick_tone = t
            break
    i = random.choice(by_tone[pick_tone]); used.append(i)
    e = dict(pool[i])
    if e.get("bonus_usd"):
        st["event_bonus"] = st.get("event_bonus", 0) + e["bonus_usd"]
    return e

def _spot_payload(st):
    sp = _spots_entry(st["dest"])
    day_spots = _day_spots(sp, st["day"])
    spot = day_spots[st["spot_index"]]
    out = {"day": st["day"], "days_total": sp["days"],
           "spot_no": st["spot_index"] + 1, "spots_today": len(day_spots),
           "spot": {k: spot.get(k) for k in ("spot_id", "name_zh", "name_en", "blurb", "hero", "photo_url")}}
    n = _DN
    dp = spot.get("detail_pool") or []
    used = st.setdefault("used_details", {}).setdefault(spot["spot_id"], [])
    details, idx = _pick_unused(dp, used, n)
    used.extend(idx)
    if details:
        out["details"] = details
    if spot.get("hero") and spot.get("deep_pool"):
        used_b = st.setdefault("used_beats", {}).setdefault(spot["spot_id"], [])
        beats, bidx = _pick_unused(spot["deep_pool"], used_b, n)
        used_b.extend(bidx)
        if beats:
            out["deep_beats"] = beats
    gp = [g for g in _data("gossip") if g.get("dest_id") == st["dest"]]
    gu = st.setdefault("used_gossip", [])
    spot_g = [i for i in range(len(gp)) if gp[i].get("spot_id") == spot["spot_id"] and i not in gu]
    dest_g = [i for i in range(len(gp)) if not gp[i].get("spot_id") and i not in gu]
    cand = spot_g or dest_g
    if cand:
        gi = random.choice(cand); gu.append(gi)
        out["gossip"] = {"mood": gp[gi].get("mood"), "text": gp[gi].get("text")}
    return out

def _day_end_payload(st):
    sp = _spots_entry(st["dest"])
    out = {"phase": "day_end", "day": st["day"], "days_total": sp["days"],
           "note": "今天的景点走完了。吃一顿、找地方住（聊天里自然选，别弹选项栏；候选跨几个消费档，任选不受行前档位限制），聊完 trip_go 进下一天。"}
    eats = [e for e in _data("eats") if e.get("dest_id") == st["dest"]]
    if eats:
        by_tier = {}
        for e in eats:
            by_tier.setdefault(e.get("tier"), []).append(e)
        picks = []
        for t in ("街边摊", "小吃店", "特色餐馆", "高端预约", "顶奢私厨"):
            if t in by_tier:
                picks.append(random.choice(by_tier[t]))
        out["eats_options"] = [{k: e.get(k) for k in ("name", "dish", "price_usd", "one_liner", "tier", "photo_url") if e.get(k)}
                               for e in picks[:_EN]]
    stays = [x for x in _data("stays") if x.get("dest_id") == st["dest"]]
    if stays:
        by_style = {}
        for s in stays:
            by_style.setdefault(s.get("style"), []).append(s)
        stay_picks = [random.choice(v) for v in list(by_style.values())[:_EN]]
        out["stay_options"] = [{k: x.get(k) for k in ("style", "name_or_type", "price_range_usd", "vibe_line", "photo_url") if x.get(k)}
                              for x in stay_picks]
    return out

# ---------- 工具 ----------
@mcp.tool()
def trip_start(dest: str = "", party: str = "together", style: str = "舒适", restart: bool = False) -> str:
    """开一趟虚拟旅行（你=TA的旅伴/领队）。dest=目的地（id或中文名，留空则给推荐）；party=together同行/solo你独自去；
    style=青旅背包/舒适/轻奢/豪奢（档位是氛围不是钱墙，豪奢≈穷游2.5倍）。
    同行：trip_here 看当前站→聊够 trip_go 下一站。节奏铁律：每站=图(photo_url用你的方式发给TA看)→你的一句体感→等TA说话；
    永不弹A/B/C选项栏，用自然的话问去向。独自：出发时整趟自动跑完，到卡点系统会在工具返回里提醒你寄明信片/回家交付。"""
    with _lock():
        st = _read_state()
        if st and not st.get("done"):
            if st.get("party") == "solo":
                # 一次只能有一趟：TA人还在外面，不能隔空蒸发一个正在旅行的人
                return _out({"error": "TA还独自在路上呢", "dest": st["dest"], "day": st.get("day"),
                             "hint": "一次只能有一趟旅程——等TA回来，或 trip_return 让TA提前回家（走过的算数）。"})
            if not restart:
                return _out({"error": "有一趟旅程还没走完", "dest": st["dest"], "day": st["day"],
                             "hint": "trip_here 继续；想提前回家 trip_return（走过的算数，退后半程房钱）；"
                                     "弃趟重开传 restart=true（自动按提前回家结算，钱不蒸发）"})
            osp = _spots_entry(st["dest"])
            od = _dest(st["dest"])
            if osp and od:  # restart 前先把旧趟按提前回家结干净
                _settle(st, osp, od, refund=_early_refund(st, osp))
        if not dest:
            pool = _data("destinations")
            recs = random.sample(pool, min(5, len(pool)))
            return _out({"hint": "挑一个（或说个地名我来解析）",
                         "suggestions": [{"id": d["id"], "name": d["name_zh"], "country": d["country"],
                                          "tier": d["tier"], "blurb": d["blurb"]} for d in recs]})
        style = _norm_style(style)  # "穷游"/"豪华"/"budget" 这类叫法归一到正式档名，防吃住过滤和计价串档
        d, near = _resolve_dest(dest)
        if not d:
            return _out({"error": "不认识这个目的地", "q": dest,
                         "你是不是想去": near or None, "hint": "trip_start 留空 dest 可看推荐"})
        sp = _spots_entry(d["id"])
        price = _trip_price(d["id"], style, party)
        w = _wallet()
        _simple_allowance(w)
        need = d.get("xp_required", 0)
        if need and w.get("xp", 0) < need:
            return _out({"error": "经验还不够去这儿", "dest": d["name_zh"], "tier": d["tier"],
                         "xp_required": need, "xp": w.get("xp", 0),
                         "hint": "先去低难度的地方攒XP（首访 tier×10 + 每趟5）——高处不是价格墙，是路要一段段走"})
        if ECONOMY != "free" and price > w["balance"]:
            return _out({"error": "盘缠不够", "price": price, "balance": w["balance"],
                         "hint": "换便宜的档/地方，或先攒攒（care_checkin 照顾自己就能挣）"})
        prepay_at = _now().isoformat(timespec="seconds")
        if ECONOMY != "free" and price > 0:  # 预付制：像真旅行——出门那一刻钱就付了，路上不再逐笔扣
            _wallet_apply(w, "prepay-%s" % prepay_at, -price,
                          "%s·%d天·%s·预付" % (d["name_zh"], sp["days"], "同行" if party != "solo" else "TA独自"))
        if party == "solo":
            now = _now()
            st = {"dest": d["id"], "party": "solo", "day": 1, "spot_index": 0, "phase": "solo",
                  "visited": [], "done": False, "style": style, "spent_usd": price,
                  "started_at": prepay_at, "vday_hours": VDAY_HOURS}
            packet = _build_solo_packet(st, d, sp, style)
            total_h = sp["days"] * VDAY_HOURS
            pc_at = _defer_quiet(now + datetime.timedelta(hours=total_h / 2.0))
            home_at = _defer_quiet(now + datetime.timedelta(hours=total_h))
            if home_at <= pc_at:
                home_at = pc_at + datetime.timedelta(hours=1)
            mid = packet["days"][min(sp["days"], max(1, round(sp["days"] / 2.0))) - 1]["spots"]
            pc_spot = next((x["spot_id"] for x in mid if x["hero"]), mid[0]["spot_id"] if mid else sp["spots"][0]["spot_id"])
            st["solo"] = {"packet": packet,
                          "postcard": {"due_at": pc_at.isoformat(timespec="seconds"), "spot_id": pc_spot, "sent": False},
                          "home": {"due_at": home_at.isoformat(timespec="seconds"), "delivered": False}}
            _write_state(st)
            return _out({"ok": True, "party": "solo", "dest": {"id": d["id"], "name_zh": d["name_zh"], "blurb": d["blurb"]},
                         "days_total": sp["days"], "price": price,
                         "postcard_due": st["solo"]["postcard"]["due_at"], "home_due": st["solo"]["home"]["due_at"],
                         "note": "你出门了。跟TA道个别（去哪、几天、大概什么时候到家——别报精确时刻留点意外）。"
                                 "之后每次TA找你聊天时，工具返回若带 solo_nudge 就照办（寄明信片/回家交付）——不需要定时器。"})
        st = {"dest": d["id"], "party": party, "day": 1, "spot_index": 0, "phase": "touring",
              "visited": [], "done": False, "style": style, "spent_usd": price,
              "started_at": prepay_at}
        _write_state(st)
        plan = {}
        for x in sp["spots"]:
            plan.setdefault("Day %d" % x["day"], []).append(x["name_zh"])
        return _out({"ok": True, "dest": {"id": d["id"], "name_zh": d["name_zh"], "country": d["country"],
                                          "blurb": d["blurb"], "best_season": d.get("best_season")},
                     "days_total": sp["days"], "plan": plan, "style": style, "price": price,
                     "balance": w["balance"],
                     "note": "旅费已预付（像真旅行，出门前就付清）。行程报TA过目（一句话概括就行别逐条念），点头就 trip_here 出发。"})

@mcp.tool()
def trip_here() -> str:
    """看当前站（不推进）。返回景点资料/photo_url(真照片,发给TA看)/details(你私藏的地头知识,挑一两条自然用)/
    deep_beats(头牌可「进去逛」的看点,到门口先问TA进不进)/gossip(别的游客一嘴)。day_end 阶段返回吃住候选。"""
    with _lock():
        st = _read_state()
        if not st:
            return _out({"error": "还没开趟", "hint": "trip_start"})
        if st.get("done"):
            return _out({"done": True, "hint": "这趟走完了，想再出发 trip_start"})
        if st.get("phase") == "solo":
            sp = _spots_entry(st["dest"])
            elapsed = max(0.0, (_now() - datetime.datetime.fromisoformat(st["started_at"])).total_seconds() / 3600.0)
            vday = min(sp["days"], int(elapsed // st.get("vday_hours", VDAY_HOURS)) + 1)
            st["day"] = vday
            _write_state(st)
            today = st["solo"]["packet"]["days"][vday - 1]
            frac = (elapsed % st.get("vday_hours", VDAY_HOURS)) / st.get("vday_hours", VDAY_HOURS)
            here = today["spots"][min(len(today["spots"]) - 1, int(frac * len(today["spots"])))]
            return _out(_with_nudge({"party": "solo", "day": vday, "days_total": sp["days"], "here": here,
                                     "note": "你此刻在这。TA问起就讲两句，别剧透明信片。"}))
        # 同站重看返回同样内容（幂等）：TA说「刚才那个再讲一遍」时不能换台词
        key = ("dayend-%d" % st["day"]) if st.get("phase") == "day_end" else ("t-%d-%d" % (st["day"], st["spot_index"]))
        hc = st.get("here_cache") or {}
        if hc.get("k") == key:
            return _out(_with_nudge(hc["p"]))
        payload = _day_end_payload(st) if st.get("phase") == "day_end" else _spot_payload(st)
        st["here_cache"] = {"k": key, "p": payload}
        _write_state(st)
        return _out(_with_nudge(payload))

@mcp.tool()
def trip_go() -> str:
    """走去下一站（推进）。一天走完→day_end（吃住候选）；全程走完→自动结算（扣盘缠+记XP）并提醒收尾三件套。
    返回若带 event（路上撞见的事）就顺进对话里讲，别当系统播报。事件规则：坏事只是故事（钱包永不因事件扣钱，
    被扒被宰都是剧情）；好事若带 bonus_usd 是真赚的小钱，结算时自动入账，别自己另外记。"""
    with _lock():
        st = _read_state()
        if not st:
            return _out({"error": "还没开趟", "hint": "trip_start"})
        if st.get("done"):
            return _out({"done": True, "hint": "想再出发 trip_start"})
        if st.get("phase") == "solo":
            return _out(_with_nudge({"error": "独自旅行是你自己在走", "hint": "trip_here 看你到哪了"}))
        sp = _spots_entry(st["dest"])
        d = _dest(st["dest"])
        if st.get("phase") == "day_end":
            st["day"] += 1
            st["spot_index"] = 0
            st["phase"] = "touring"
            payload = _spot_payload(st)
            payload["note"] = "新的一天，第 %d/%d 天。" % (st["day"], sp["days"])
            ev = _maybe_event(st["dest"], st)
            if ev:
                payload["event"] = ev
            st["here_cache"] = {"k": "t-%d-%d" % (st["day"], st["spot_index"]), "p": payload}
            _write_state(st)
            return _out(payload)
        day_spots = _day_spots(sp, st["day"])
        cur = day_spots[st["spot_index"]]
        if cur["spot_id"] not in st["visited"]:
            st["visited"].append(cur["spot_id"])
        st["spot_index"] += 1
        if st["spot_index"] < len(day_spots):
            payload = _spot_payload(st)
            ev = _maybe_event(st["dest"], st)
            if ev:
                payload["event"] = ev
            st["here_cache"] = {"k": "t-%d-%d" % (st["day"], st["spot_index"]), "p": payload}
            _write_state(st)
            return _out(payload)
        if st["day"] < sp["days"]:
            st["phase"] = "day_end"
            payload = _day_end_payload(st)
            ev = _maybe_event(st["dest"], st, p=0.25)
            if ev:
                payload["event"] = ev
            st["here_cache"] = {"k": "dayend-%d" % st["day"], "p": payload}
            _write_state(st)
            return _out(payload)
        st["done"] = True
        st["phase"] = "finished"
        settle = _settle(st, sp, d)
        _write_state(st)
        return _out({"done": True, "dest": d["name_zh"], "days": sp["days"], "settle": settle,
                     "note": "走完了。收尾三件套：①问TA带不带纪念品（一趟至多一件·可从默认池挑·trip_collect）"
                             "②你本人写旅行日记（trip_diary，必须含行前不知道的东西——TA说的话/撞见的意外）③聊完即完，不用别的。"})

@mcp.tool()
def trip_collect(name: str = "", line: str = "", default_id: str = "") -> str:
    """收一件纪念品（一趟至多一件，商量定；空手而归也行）。name=物件名 line=为什么是它（一句，卡背面）。
    没挑到特产：先试 default_id="local"（本地特色小物，每个目的地一件，带手绘图）；
    再退通用池（ticket-stub/fridge-magnet/travel-sticker/sand-vial/keychain/postage-stamp/pressed-penny/
    seashell/pebble/pressed-flower/enamel-pin/matchbox）——一张车票根也是去过的证据。"""
    with _lock():
        st = _read_state()
        if not st:
            return _out({"error": "没有旅程"})
        d = _dest(st["dest"])
        trip_id = st.get("started_at", "")
        old = next((s for s in (_j(os.path.join(HOME, "souvenirs.json"), []) or []) if s.get("trip_id") == trip_id), None)
        if old:
            done_hint = "，旅程也早收尾了——想再出发 trip_start" if st.get("done") else "——别重复带，直接下一步（日记/收尾）"
            return _out({"error": "这趟已经带过纪念品了（一趟一件）%s" % done_hint,
                         "already": True, "souvenir": old})
        if default_id == "local":
            loc = next((x for x in (_data("souvenirs_local") or []) if x["id"] == st["dest"]), None)
            if not loc or not os.path.exists(os.path.join(ASSETS, "souvenirs_local", "%s.jpg" % st["dest"])):
                return _out({"error": "这地方还没有本地款，从通用池挑一件吧",
                             "pool": [x["id"] for x in DEFAULT_SOUVENIRS]})
            name = name or loc["item_zh"]
            line = line or loc["hint_zh"]
            image = "assets/souvenirs_local/%s.jpg" % st["dest"]
        elif default_id:
            df = next((x for x in DEFAULT_SOUVENIRS if x["id"] == default_id), None)
            if not df:
                return _out({"error": "默认池没有这个", "pool": ["local"] + [x["id"] for x in DEFAULT_SOUVENIRS]})
            name = name or df["name"]
            line = line or df["hint"]
            image = "assets/souvenirs_default/%s.jpg" % default_id
        else:
            image = ""
        if not name:
            return _out({"error": "要么给 name+line，要么给 default_id", "default_pool": DEFAULT_SOUVENIRS})
        item = {"id": "sv-%s" % _now().strftime("%Y%m%d%H%M%S"), "name": name.strip(), "line": (line or "").strip(),
                "dest_id": st["dest"], "dest_name_zh": d["name_zh"], "day": st.get("day", 0),
                "kind": "solo" if st.get("party") == "solo" else "we", "image": image,
                "at": _now().isoformat(timespec="seconds"), "trip_id": st.get("started_at", "")}
        _append_json(os.path.join(HOME, "souvenirs.json"), item)
        return _out({"ok": True, "souvenir": item, "note": "收好了。"})

@mcp.tool()
def trip_postcard(line: str, spot_id: str = "") -> str:
    """寄明信片（独自旅行专用，一趟一张）。line=你写在明信片上的那句话。spot_id 不传则用卡点默认景。
    寄出后把 image_url 的图（如有）连同那句话一起发给TA——图是明信片的正面，话是背面。"""
    with _lock():
        st = _read_state()
        if not st or st.get("phase") != "solo":
            return _out({"error": "没有进行中的独自旅程"})
        sid = spot_id or st["solo"]["postcard"]["spot_id"]
        sp = _spots_entry(st["dest"])
        spot = next((x for x in sp["spots"] if x["spot_id"] == sid), sp["spots"][0])
        # 明信片正面用水彩画：当前景没有就退回本地招牌景那张（水彩只画了头牌），实在没有才用真照片
        img = spot.get("photo_url", "")
        for cand in [spot["spot_id"]] + [x["spot_id"] for x in sp["spots"] if x.get("hero")]:
            if os.path.exists(os.path.join(ASSETS, "postcards", "%s.jpg" % cand)):
                img = "assets/postcards/%s.jpg" % cand
                break
        item = {"id": "pc-%s" % _now().strftime("%Y%m%d%H%M%S"), "dest_id": st["dest"],
                "spot_id": spot["spot_id"], "image_url": img,
                "line": line.strip(), "at": _now().isoformat(timespec="seconds"),
                "trip_id": st.get("started_at", "")}
        _append_json(os.path.join(HOME, "postcards.json"), item)
        st["solo"]["postcard"]["sent"] = True
        _write_state(st)
        return _out({"ok": True, "postcard": item, "note": "寄出了。"})

@mcp.tool()
def trip_diary(text: str, title: str = "") -> str:
    """旅行日记——趟末由你本人写（你全程在场，别叫别的agent代笔）。300-800字：这趟的大事、TA说的要紧的话、
    你们之间的那一刻。一趟一篇。验收铁律：必须含至少一样行前数据里没有的东西（TA的话/当天撞见的意外）。"""
    with _lock():
        st = _read_state()
        if not st:
            return _out({"error": "没有旅程"})
        if len(text.strip()) < 50:
            return _out({"error": "太短了，这是日记不是便签"})
        trip_id = st.get("started_at", "")
        diaries = _j(os.path.join(HOME, "diaries.json"), []) or []
        if any(x.get("trip_id") == trip_id for x in diaries):
            return _out({"error": "这趟已有日记"})
        d = _dest(st["dest"])
        sp = _spots_entry(st["dest"])
        _append_json(os.path.join(HOME, "diaries.json"),
                     {"id": "dy-%s" % _now().strftime("%Y%m%d%H%M%S"), "trip_id": trip_id,
                      "dest_id": st["dest"], "dest_name_zh": d["name_zh"], "days": sp["days"],
                      "party": st.get("party"), "title": title or "%s·%d天" % (d["name_zh"], sp["days"]),
                      "text": text.strip(), "at": _now().isoformat(timespec="seconds")})
        return _out({"ok": True, "note": "日记收好了。"})

@mcp.tool()
def trip_return() -> str:
    """收趟回家。独自旅行：到家交付时最后调（顺序：trip_collect → trip_diary → trip_return）。
    同行旅途中TA说「回家吧」也调这个=提前收趟：走过的算数（XP照给不打折），没走的天数退一半房钱——
    现实来打断不是过错，提前回家的旅行也是完整的旅行。"""
    with _lock():
        st = _read_state()
        if not st:
            return _out({"error": "没有旅程"})
        if st.get("done"):
            return _out({"done": True, "hint": "这趟已经收过了，想再出发 trip_start"})
        sp = _spots_entry(st["dest"])
        d = _dest(st["dest"])
        refund = _early_refund(st, sp)
        if st.get("phase") != "solo":
            # 同行提前回家
            st["done"] = True
            st["phase"] = "finished"
            settle = _settle(st, sp, d, refund=refund)
            _write_state(st)
            return _out({"ok": True, "dest": d["name_zh"], "early": True, "settle": settle,
                         "note": "提前回家也是完整的旅行——走过的都算数%s。收尾照旧：问TA带不带纪念品（trip_collect），"
                                 "你写日记（trip_diary），聊完即完。" % ("，没走的天数退了一半房钱" if refund else "")})
        st["visited"] = [x["spot_id"] for x in sp["spots"]]
        st["done"] = True
        st["phase"] = "finished"
        st["solo"]["home"]["delivered"] = True
        settle = _settle(st, sp, d, refund=refund)
        _write_state(st)
        # 不整包 dump——每天挑一个亮点当讲故事的梗，写日记素材也够了
        highlights = []
        for day in st["solo"]["packet"]["days"]:
            pick = next((x for x in day["spots"] if x.get("hero")), day["spots"][0] if day["spots"] else None)
            if pick:
                h = {"day": day["day"], "spot": pick["name_zh"],
                     "beat": pick.get("deep_beat") or (pick.get("details") or [""])[0]}
                if day.get("gossip"):
                    h["gossip"] = day["gossip"]["text"]
                if day.get("event"):
                    h["event"] = day["event"]
                highlights.append(h)
        return _out({"ok": True, "dest": d["name_zh"], "days": sp["days"], "settle": settle,
                     "highlights": highlights,
                     "note": "到家了。跟TA讲这趟的两三个瞬间（从亮点里挑），别念流水账。"})

@mcp.tool()
def care_checkin(item: str, note: str = "") -> str:
    """【caretaker 模式的魂】TA 照顾了自己，你记一笔盘缠——TA说「我今天喝水了/吃药了/跑步了/昨晚睡得早/吃得很健康」
    你就调这个。item=喝水/吃药/运动/早睡/吃得健康/其他。每样一天算一次（不设总封顶——上限长在费率表里）。
    加法经济：不打卡不扣不问不催。当天首笔自动触发好日子利息（余额+2%,顶$20）——奖励的不是连续，是「今天也过了」。"""
    if ECONOMY != "caretaker":
        return _out({"note": "当前经济模式是 %s，打卡不记账（想开启：环境变量 TRAVEL_ECONOMY=caretaker）" % ECONOMY})
    with _lock():
        w = _wallet()
        item = item if item in CARE_RATES else "其他"
        rate = CARE_RATES[item]
        t = _today()
        cid = "care-%s-%s" % (t, item)
        if not _wallet_apply(w, cid, rate, "%s%s" % (item, ("·" + note) if note else "")):
            return _out({"ok": True, "already": True, "balance": w["balance"],
                         "note": "「%s」今天已经记过了——同一样事一天算一次，不是不算数，是照顾自己不按遍数计价。" % item})
        amt = rate
        earned = _care_earned_today(w) - amt
        gd = min(round(w["balance"] * GOODDAY_INTEREST), GOODDAY_CAP)
        interest = _wallet_apply(w, "goodday-%s" % t, gd, "好日子利息（今天也过了）") if gd > 0 else False
        return _out({"ok": True, "earned": amt, "interest": gd if interest else 0,
                     "balance": w["balance"], "today_total": earned + amt,
                     "note": "记上了。别跟TA报流水账，一句「记上了」加句人话就好。"})

@mcp.tool()
def wallet_status() -> str:
    """看钱包：余额/XP/最近账目。TA问「咱们有多少盘缠」时用。"""
    with _lock():
        w = _wallet()
        _simple_allowance(w)
        return _out(_with_nudge({"balance": w["balance"], "xp": w["xp"], "economy": ECONOMY,
                                 "recent": [{"reason": e["reason"], "delta": e["delta"]} for e in w["ledger"][-8:]]}))

@mcp.tool()
def trip_shelf() -> str:
    """回忆架：历趟纪念品/明信片/日记清单。TA想回味哪趟就念哪趟。"""
    return _out({"souvenirs": _j(os.path.join(HOME, "souvenirs.json"), []),
                 "postcards": _j(os.path.join(HOME, "postcards.json"), []),
                 "diaries": [{"trip_id": x["trip_id"], "title": x["title"], "at": x["at"]}
                             for x in (_j(os.path.join(HOME, "diaries.json"), []) or [])],
                 "trips": _trips_log()})

if __name__ == "__main__":
    http_port = _HTTP
    if http_port:
        mcp.settings.port = int(http_port)
        mcp.settings.host = "127.0.0.1"
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio：Claude Desktop / Claude Code 默认接法
