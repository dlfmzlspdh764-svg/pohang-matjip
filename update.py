#!/usr/bin/env python3
"""포항 맛집 앱 데이터 갱신 (GitHub Actions에서 매일 06:00 KST 실행, 로컬 재실행도 가능).

수집 (네이버 플레이스 공개 모바일 페이지, 식당마다 홈·메뉴·리뷰 탭):
  - 방문자 리뷰 수 / 블로그·카페 리뷰 수 / 평점 / 전화 / 주소 / 영업시간·휴무 / 주차 / 편의시설 / 좌석(단체석·룸)
  - 메뉴: 홈 메뉴 → 메뉴 탭(네이버·배민 메뉴) → 다이닝코드(네이버에 연결된 경우) 순서로 채움
  - '이런 점이 좋았어요' 키워드 투표 상위, 리뷰에 많이 언급된 메뉴
  - 사진 최대 8장 (업체 등록·방문자 사진, 메뉴 사진) → img/<hash>.jpg (변경 없으면 재다운로드 안 함)
  - X 최근 7일 언급 수: X_BEARER_TOKEN 있으면 측정, 없으면 sns_snapshot.json 마지막 값 유지
순위: (방문자 리뷰, 블로그 리뷰, X 언급) 사전식 내림차순.
섹션 TOP10: 회식(‘단체모임 하기 좋아요’ 투표 → 리뷰 수), 치킨(업종), 과메기(상호·업종·메뉴·리뷰 언급메뉴).
네이버가 막히는 경우: 실패한 식당은 직전 data.json 값을 유지(stale 표시). 절반 이상 실패하면 data.json을 덮어쓰지 않음.
옵션: --no-photos (사진 다운로드 생략), --only N (앞 N곳만, 테스트용)
"""
import json, re, os, sys, subprocess, urllib.parse, datetime, io, hashlib, html as H, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
NA = "정보 없음"
DAYS = ["월", "화", "수", "목", "금", "토", "일"]
KST = datetime.timezone(datetime.timedelta(hours=9))
MAXPH = 8

def get(url, binary=False, headers=(), tries=2):
    for i in range(tries):
        cmd = ["curl", "-sL", "--compressed", "--max-time", "30", "-A", UA, "-H", "Accept-Language: ko-KR,ko;q=0.9"]
        for h in headers: cmd += ["-H", h]
        out = subprocess.run(cmd + [url], capture_output=True).stdout
        if out: return out if binary else out.decode("utf-8", "ignore")
        time.sleep(2)
    return b"" if binary else ""

def apollo(url):
    h = get(url)
    m = re.search(r"window.__APOLLO_STATE__\s*=\s*(\{.*?\});\s*window", h, re.S)
    try: return json.loads(m.group(1)) if m else None
    except Exception: return None

def deref(st, x): return st.get(x["__ref"], {}) if isinstance(x, dict) and "__ref" in x else x
def pdetail(st): return next((v for k, v in st.get("ROOT_QUERY", {}).items() if k.startswith("placeDetail(")), {})

def fmt_hours(nbh):
    if not nbh: return NA, NA
    groups, off, extra = {}, [], []
    for blk in nbh:
        for d in blk.get("businessHours") or []:
            day, bh, desc = d.get("day"), d.get("businessHours"), d.get("description") or ""
            if day not in DAYS and not (bh and bh.get("start")):
                if desc: extra.append(f"{day} {desc}")
                continue
            if bh and bh.get("start"):
                t = f"{bh['start']}~{bh['end']}"
                br = d.get("breakHours") or []
                if br: t += " (브레이크 " + ", ".join(f"{b['start']}~{b['end']}" for b in br) + ")"
                groups.setdefault(t, []).append(day)
            elif "휴무" in desc or not bh: off.append(day)
        if blk.get("comingRegularClosedDays"): extra.append(str(blk["comingRegularClosedDays"]) + " 휴무")
        if blk.get("freeText"): extra.append(str(blk["freeText"]))
    o = lambda d: DAYS.index(d) if d in DAYS else -1
    dl = lambda v: "매일" if set(DAYS) <= set(v) else "·".join(sorted(v, key=o))
    hours = " / ".join(f"{dl(v)} {k}" for k, v in groups.items()) or NA
    hol = ", ".join(sorted(set(off), key=o)) + " 휴무" if off else ("휴무일 표기 없음" if groups else NA)
    for e in extra:
        if "휴무" in e or "휴일" in e: hol = (hol + " · " if hol not in (NA, "휴무일 표기 없음") else "") + e
    return hours, hol

def price_num(t):
    m = re.search(r"\d[\d,]*", str(t or "")); return int(m.group().replace(",", "")) if m else None
def won(n): return f"{n:,}원"

def menus_from_state(st):
    out = []
    for k, v in st.items():
        if not isinstance(v, dict): continue
        if v.get("__typename") == "PlaceMenuItem":
            out.append({"name": v.get("name"), "price": ((v.get("price") or {}).get("displayText") or NA),
                        "repr": "repr" in (v.get("badges") or []), "img": v.get("thumbnailUrl")})
        elif v.get("__typename") == "PlaceDetail_BaeminMenu":
            p = price_num(v.get("price"))
            out.append({"name": v.get("name"), "price": won(p) if p else NA, "repr": bool(v.get("isRepresentative")),
                        "img": (v.get("images") or [None])[0], "src": "배달의민족 메뉴(네이버 연동)"})
    seen, uniq = set(), []
    for m in out:
        if m["name"] and m["name"] not in seen: seen.add(m["name"]); uniq.append(m)
    return uniq

def menus_diningcode(url):
    h = get(url)
    out = []
    for m in re.finditer(r"<span class='restaurant-menu'>(.*?)</span>.*?<p class=\"restaurant-price\">([\d,]+)", h, re.S):
        out.append({"name": H.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip(), "price": m.group(2) + "원", "repr": False,
                    "img": None, "src": "다이닝코드"})
    return out[:60]

def collect(pid):
    st = apollo(f"https://m.place.naver.com/restaurant/{pid}/home")
    if not st or f"PlaceDetailBase:{pid}" not in st: return None
    base = st[f"PlaceDetailBase:{pid}"]; pd = pdetail(st)
    menus = menus_from_state(st); msrc = "네이버 플레이스"
    rel = {l.get("name"): l.get("url") for l in pd.get("relatedLinks") or []}
    if not menus:
        mst = apollo(f"https://m.place.naver.com/restaurant/{pid}/menu/list")
        if mst: menus = menus_from_state(mst)
        if menus: msrc = "네이버 플레이스 메뉴 탭" + (" (배민 연동 메뉴)" if any(m.get("src") for m in menus) else "")
    if not menus and rel.get("다이닝코드"):
        menus = menus_diningcode(rel["다이닝코드"]); msrc = "다이닝코드" if menus else msrc
    reprs = [m for m in menus if m["repr"]] or menus[:3]
    rep_menu = [{"name": m["name"], "price": m["price"]} for m in reprs[:3]]
    nums = [price_num(m["price"]) for m in reprs if price_num(m["price"])]
    pr = (won(min(nums)) if min(nums) == max(nums) else f"{won(min(nums))[:-1]}~{won(max(nums))}") if nums else NA
    hours, hol = fmt_hours(pd.get("newBusinessHours"))
    # 리뷰 탭: 키워드 투표
    keywords, group_votes = [], 0
    rst = apollo(f"https://m.place.naver.com/restaurant/{pid}/review/visitor")
    stats = {}
    for src in (rst or {}, st):
        for k, v in src.items():
            if k.startswith("VisitorReviewStatsResult") and isinstance(v, dict) and v.get("analysis"): stats = v; break
        if stats.get("analysis", {}).get("votedKeyword"): break
    an = stats.get("analysis") or {}
    for d in ((an.get("votedKeyword") or {}).get("details") or []):
        keywords.append({"label": d.get("displayName"), "count": d.get("count")})
        if "단체" in (d.get("displayName") or "") or "회식" in (d.get("displayName") or ""): group_votes += d.get("count") or 0
    menu_mentions = [{"label": m.get("label"), "count": m.get("count")} for m in (an.get("menus") or [])[:8]]
    # 편의·좌석·주차
    it = pd.get("informationTab") or {}
    facilities = [deref(st, f).get("name") for f in it.get("facilities") or []] or base.get("conveniences") or []
    seats = [{"name": deref(st, s).get("name"), "desc": deref(st, s).get("description") or ""}
             for s in ((pd.get("restaurantInfoTabDetails") or {}).get("seat") or [])]
    pk = it.get("parkingInfo") or {}
    if pk:
        bp = pk.get("basicParking") or {}
        parking = ("무료 주차" if bp.get("isFree") else "주차 가능" if bp else "주차 정보") + (f" · {pk['description']}" if pk.get("description") else "")
        if pk.get("valetParking"): parking += " · 발렛"
    elif "주차" in (base.get("conveniences") or []): parking = "주차 가능"
    else: parking = NA
    # 사진
    photos = []
    for x in (pd.get("topPhotos") or {}).get("items") or []:
        x = deref(st, x)
        if x.get("mediaFormat") == "image" and x.get("originalUrl"):
            photos.append({"url": x["originalUrl"], "kind": {"business": "업체 사진", "visitor": "방문자 사진"}.get(x.get("mediaSource"), "사진")})
    for im in ((pd.get("images") or {}).get("images") or []):
        if im.get("origin"): photos.append({"url": im["origin"], "kind": "업체 사진"})
    for m in menus:
        if m.get("img"): photos.append({"url": m["img"], "kind": f"메뉴 · {m['name']}"})
    seen, ph = set(), []
    for p in photos:
        if p["url"] not in seen: seen.add(p["url"]); ph.append(p)
    co = base.get("coordinate") or {}
    return {"naver_name": base.get("name"), "category": base.get("category") or NA,
            "address": base.get("roadAddress") or base.get("address") or NA,
            "phone": (pd.get("phoneInfo") or {}).get("phone") or base.get("virtualPhone") or base.get("phone") or NA,
            "reviews": base.get("visitorReviewsTotal"), "rating": base.get("visitorReviewsScore"), "blogs": base.get("cafeBlogReviewsTotal"),
            "menus": [{"name": m["name"], "price": m["price"]} for m in menus], "menu_source": msrc if menus else None,
            "rep_menu": rep_menu, "price_range": pr, "hours": hours, "holiday": hol, "parking": parking,
            "facilities": facilities, "seats": seats, "keywords": keywords[:6], "menu_mentions": menu_mentions,
            "group_votes": group_votes, "micro": (base.get("microReviews") or [None])[0],
            "description": (pd.get("description") or "")[:300] or None,
            "photo_srcs": ph[:MAXPH + 4], "lat": co.get("y"), "lng": co.get("x"),
            "menu_note": "메뉴판 사진만 등록되어 있어요" if not menus and pd.get("menuImages") else None,
            "menu_images": [m.get("imageUrl") for m in (pd.get("menuImages") or [])][:3],
            "menu_url": f"https://m.place.naver.com/restaurant/{pid}/menu/list",
            "naver_url": f"https://m.place.naver.com/restaurant/{pid}/home", "dc_url": rel.get("다이닝코드"),
            "siksin_url": rel.get("식신")}

def save_photo(url, size=560):
    from PIL import Image
    name = "img/" + hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    path = os.path.join(HERE, name)
    if os.path.exists(path): return name
    raw = get(url, binary=True)
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB"); im.thumbnail((size, size))
        if im.width < 120: return None
        im.save(path, "JPEG", quality=72, optimize=True, progressive=True); return name
    except Exception: return None

def x_count(q):
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok: return None
    u = "https://api.x.com/2/tweets/counts/recent?granularity=day&query=" + urllib.parse.quote(q)
    try: return json.loads(get(u, headers=[f"Authorization: Bearer {tok}"]))["meta"]["total_tweet_count"]
    except Exception: return None

def text_has(r, word):
    blob = " ".join([r.get("name") or "", r.get("category") or ""] + [m["name"] or "" for m in r.get("menus") or []]
                    + [m["label"] or "" for m in r.get("menu_mentions") or []])
    return word in blob

def main():
    args = sys.argv[1:]
    no_photos = "--no-photos" in args
    only = int(args[args.index("--only") + 1]) if "--only" in args else None
    seeds = json.load(open(os.path.join(HERE, "seeds.json")))
    if only: seeds = seeds[:only]
    snap_p = os.path.join(HERE, "sns_snapshot.json")
    snap = json.load(open(snap_p)) if os.path.exists(snap_p) else {}
    dp = os.path.join(HERE, "data.json")
    old = {r["name"]: r for r in json.load(open(dp))["restaurants"]} if os.path.exists(dp) else {}
    now = datetime.datetime.now(KST); today = now.date().isoformat()
    os.makedirs(os.path.join(HERE, "img"), exist_ok=True)

    def work(s):
        d = None
        if s.get("naver_id"):
            try: d = collect(s["naver_id"])
            except Exception as e: print("  err", s["name"], e)
        return s, d
    with ThreadPoolExecutor(3) as ex: results = list(ex.map(work, seeds))
    for rnd in range(3):  # 실패분 순차 재시도 (일시 차단 대비)
        miss = [i for i, (s, d) in enumerate(results) if s.get("naver_id") and not d]
        if not miss: break
        print(f"retry round {rnd + 1}: {len(miss)}곳"); time.sleep(30 + 30 * rnd)
        for i in miss:
            results[i] = work(results[i][0]); time.sleep(5)
    fails = sum(1 for s, d in results if s.get("naver_id") and not d)
    total = sum(1 for s, _ in results if s.get("naver_id"))
    print(f"naver ok {total - fails}/{total}")
    if total and fails > total / 2 and old:
        print("네이버 수집 실패가 절반 이상 → data.json 유지 (차단 또는 구조 변경 의심)"); sys.exit(0)

    out = []
    for s, d in results:
        r = {"name": s["name"], "cat": s["cat"], "naver_id": s.get("naver_id"), "tags": s.get("tags", []),
             "found_by": s.get("found_by", "웹 리서치 1차 목록"), "sources": []}
        prev = old.get(s["name"]) or {}
        if d:
            r.update(d); r["sources"].append(d["naver_url"]); r["map_url"] = f"https://map.naver.com/p/entry/place/{s['naver_id']}"
            if d.get("dc_url"): r["sources"].append(d["dc_url"])
            r["stale"] = False; r["updated"] = today
        elif prev and s.get("naver_id") and prev.get("reviews") is not None:
            r.update({k: v for k, v in prev.items() if k not in ("rank",)}); r["stale"] = True
        elif s.get("naver_id"):
            print("  skip (수집 실패, 이전 값 없음):", s["name"]); continue
        else:
            man = s.get("manual") or {}
            r.update({"category": man.get("category", NA), "address": man.get("address", NA), "phone": NA, "reviews": None,
                      "rating": None, "blogs": None, "menus": man.get("menus", []), "rep_menu": man.get("menus", [])[:2],
                      "menu_source": man.get("source"), "price_range": man.get("price_range", NA), "hours": man.get("hours", NA),
                      "holiday": man.get("holiday", NA), "parking": man.get("parking", NA), "facilities": [], "seats": [],
                      "keywords": [], "menu_mentions": [], "group_votes": 0, "photo_srcs": [], "updated": today, "stale": False})
            if man.get("source"): r["sources"].append(man["source"])
            r["map_url"] = "https://map.naver.com/p/search/" + urllib.parse.quote(s["name"] + " 포항")
        c = x_count(s.get("x_query", s["name"]))
        if c is not None: snap[s["name"]] = {"x_posts_7d": c, "x_query": s.get("x_query"), "measured": today}
        sn = snap.get(s["name"]) or {}
        r["sns"] = sn.get("x_posts_7d"); r["sns_measured"] = sn.get("measured")
        out.append(r)

    # 사진
    def photos_for(r):
        if no_photos or r.get("stale") or not r.get("photo_srcs"):
            return r, r.get("photos") or (old.get(r["name"]) or {}).get("photos") or []
        got = []
        for p in r["photo_srcs"]:
            f = save_photo(p["url"])
            if f: got.append({"file": f, "kind": p["kind"]})
            if len(got) >= MAXPH: break
        return r, got
    with ThreadPoolExecutor(6) as ex:
        for r, got in ex.map(photos_for, out):
            r["photos"] = [p for p in got if os.path.exists(os.path.join(HERE, p["file"]))]
            r["photo"] = r["photos"][0]["file"] if r["photos"] else None
            r.pop("photo_srcs", None)
    used = {p["file"] for r in out for p in r["photos"]}
    if not no_photos and not only:
        for f in os.listdir(os.path.join(HERE, "img")):
            if f"img/{f}" not in used: os.remove(os.path.join(HERE, "img", f))

    key = lambda r: tuple(-1 if r.get(k) is None else r[k] for k in ("reviews", "blogs", "sns"))
    for cat in ("nam", "buk", "ocheon"):
        for n, r in enumerate(sorted([r for r in out if r["cat"] == cat], key=key, reverse=True), 1): r["rank"] = n
    out.sort(key=lambda r: (r["cat"], r["rank"]))

    def is_group(r):
        return r["group_votes"] > 0 or "단체 이용 가능" in (r.get("facilities") or []) or any(s["name"] in ("단체석", "룸") for s in r.get("seats") or [])
    def sec_reason(r, sec):
        if sec == "회식":
            bits = []
            if r["group_votes"]: bits.append(f"‘단체모임 하기 좋아요’ {r['group_votes']:,}표")
            for s in r.get("seats") or []:
                if s["name"] in ("단체석", "룸", "연회석"): bits.append(s["name"] + (f"({s['desc']})" if s["desc"] else ""))
            if r.get("parking") not in (None, NA): bits.append("주차")
            return " · ".join(bits)
        if sec == "치킨": return r.get("category") or ""
        if sec == "과메기": return "메뉴/리뷰에 과메기"
    SECS = {"회식": (is_group, lambda r: (r["group_votes"], r.get("reviews") or -1, r.get("blogs") or -1)),
            "치킨": (lambda r: any(w in (r.get("category") or "") for w in ("치킨", "닭강정", "통닭")),
                    lambda r: (r.get("reviews") or -1, r.get("blogs") or -1)),
            "과메기": (lambda r: text_has(r, "과메기"), lambda r: (r.get("reviews") or -1, r.get("blogs") or -1))}
    sections = {}
    for sec, (f, k) in SECS.items():
        sections[sec] = {}
        for area in ("nam", "buk", "ocheon", "all"):
            lst = sorted([r for r in out if f(r) and (area == "all" or r["cat"] == area)], key=k, reverse=True)[:10]
            sections[sec][area] = [{"name": r["name"], "reason": sec_reason(r, sec)} for r in lst]
    json.dump(snap, open(snap_p, "w"), ensure_ascii=False, indent=1)
    now = datetime.datetime.now(KST)
    data = {"last_updated": now.strftime("%Y-%m-%d %H:%M KST"), "last_updated_iso": now.isoformat(timespec="minutes"),
            "ranking_rule": "방문자 리뷰 수 → 블로그·카페 리뷰 수 → X 최근 7일 언급 수 순서로 비교 (네이버 플레이스·X 기준)",
            "section_rules": {"회식": "‘단체모임 하기 좋아요’ 투표 수 → 방문자 리뷰 수 (단체 이용 가능·단체석·룸·투표가 있는 곳만)",
                              "치킨": "업종이 치킨·닭강정·통닭인 곳을 방문자 리뷰 수 순으로",
                              "과메기": "상호·업종·메뉴·리뷰 언급 메뉴에 ‘과메기’가 있는 곳을 방문자 리뷰 수 순으로"},
            "naver_ok": f"{total - fails}/{total}", "sections": sections, "restaurants": out}
    json.dump(data, open(dp, "w"), ensure_ascii=False, indent=1)
    print("saved", len(out), data["last_updated"])

if __name__ == "__main__":
    main()
