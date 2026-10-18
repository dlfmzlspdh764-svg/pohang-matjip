#!/usr/bin/env python3
"""포항 맛집 앱 데이터 갱신 스크립트 (매주 재실행용).

수집 신호 (순위 우선순위 순):
 1) reviews  : 네이버 플레이스 방문자 리뷰 수 (visitorReviewsTotal)
 2) blogs    : 네이버 플레이스 블로그·카페 리뷰 수 (cafeBlogReviewsTotal)
 3) sns      : X(트위터) 최근 7일 언급 게시물 수 (X API v2 /tweets/counts/recent)
               - 환경변수 X_BEARER_TOKEN 이 있으면 새로 측정
               - 없으면 sns_snapshot.json 의 마지막 측정값을 그대로 사용 (측정일 표시)
               - Instagram 해시태그 수는 로그인 없이 조회할 수 없어 수집하지 않음
정렬: 카테고리별로 (reviews, blogs, sns) 내림차순 사전식 정렬. 값이 없으면(정보 없음) -1로 취급해 뒤로 감.
메뉴·가격·영업시간·휴무·주소·대표사진도 네이버 플레이스 공개 페이지에서 다시 읽어옴.
사용법: python3 update.py            (사진 재다운로드 생략하려면 --no-photos)
"""
import json, re, os, sys, subprocess, urllib.parse, datetime, io
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
NA = "정보 없음"
DAYS = ["월", "화", "수", "목", "금", "토", "일"]

def get(url, binary=False, headers=()):
    cmd = ["curl", "-sL", "--max-time", "30", "-A", UA]
    for h in headers: cmd += ["-H", h]
    out = subprocess.run(cmd + [url], capture_output=True).stdout
    return out if binary else out.decode("utf-8", "ignore")

def naver_state(pid):
    h = get(f"https://m.place.naver.com/restaurant/{pid}/home")
    m = re.search(r"window.__APOLLO_STATE__\s*=\s*(\{.*?\});\s*window", h, re.S)
    return json.loads(m.group(1)) if m else None

def deref(st, x):
    return st.get(x["__ref"], {}) if isinstance(x, dict) and "__ref" in x else x

def fmt_hours(nbh):
    if not nbh: return NA, NA
    groups = {}; off = []; extra = []
    for blk in nbh:
        for d in blk.get("businessHours") or []:
            day = d.get("day"); bh = d.get("businessHours"); desc = d.get("description") or ""
            if day not in DAYS and not (bh and bh.get("start")):
                if desc: extra.append(f"{day} {desc}")
                continue
            if bh and bh.get("start"):
                t = f"{bh['start']}~{bh['end']}"
                br = d.get("breakHours") or []
                if br: t += " (브레이크 " + ", ".join(f"{b['start']}~{b['end']}" for b in br) + ")"
                groups.setdefault(t, []).append(day)
            elif "휴무" in desc or not bh:
                off.append(day)
        if blk.get("comingRegularClosedDays"): extra.append(str(blk["comingRegularClosedDays"]) + " 휴무")
        if blk.get("freeText"): extra.append(str(blk["freeText"]))
    o = lambda d: DAYS.index(d) if d in DAYS else -1
    dl = lambda v: "매일" if set(DAYS) <= set(v) else "·".join(sorted(v, key=o))
    hours = " / ".join(f"{dl(v)} {k}" for k, v in groups.items()) or NA
    hol = ", ".join(sorted(set(off), key=DAYS.index)) + " 휴무" if off else ("휴무일 표기 없음" if groups else NA)
    for e in extra:
        if "휴무" in e or "휴일" in e: hol = (hol + " · " if hol not in (NA, "휴무일 표기 없음") else "") + e
    return hours, hol

def price_num(t):
    m = re.search(r"\d[\d,]*", t or ""); return int(m.group().replace(",", "")) if m else None

def collect_naver(pid):
    st = naver_state(pid)
    if not st: return None
    base = st.get(f"PlaceDetailBase:{pid}", {})
    pd = next((v for k, v in st["ROOT_QUERY"].items() if k.startswith("placeDetail(")), {})
    menus = []
    for it in (pd.get("placeMenus") or {}).get("items") or []:
        it = deref(st, it)
        menus.append({"name": it.get("name"), "price": ((it.get("price") or {}).get("displayText") or NA),
                      "repr": "repr" in (it.get("badges") or [])})
    reprs = [m for m in menus if m["repr"]] or menus[:3]
    nums = [price_num(m["price"]) for m in reprs if price_num(m["price"])]
    if nums: pr = f"{min(nums):,}원" if min(nums) == max(nums) else f"{min(nums):,}~{max(nums):,}원"
    else: pr = NA
    hours, hol = fmt_hours(pd.get("newBusinessHours"))
    photo = None
    for it in (pd.get("topPhotos") or {}).get("items") or []:
        it = deref(st, it)
        if it.get("mediaSource") == "business" and it.get("mediaFormat") == "image":
            photo = it.get("originalUrl"); break
    co = base.get("coordinate") or {}
    if not menus and pd.get("menuImages"):
        menus = []; menu_note = "메뉴판 사진만 등록되어 있어요 (네이버 플레이스 메뉴 탭에서 확인)"
    else: menu_note = None
    return {"naver_name": base.get("name"), "category": base.get("category") or NA,
            "address": base.get("roadAddress") or base.get("address") or NA,
            "phone": (pd.get("phoneInfo") or {}).get("phone") or base.get("virtualPhone") or base.get("phone") or NA,
            "reviews": base.get("visitorReviewsTotal"), "rating": base.get("visitorReviewsScore"),
            "blogs": base.get("cafeBlogReviewsTotal"), "menus": [{"name": m["name"], "price": m["price"]} for m in menus],
            "price_range": pr, "hours": hours, "holiday": hol, "photo_src": photo,
            "lat": co.get("y"), "lng": co.get("x"), "menu_note": menu_note,
            "menu_url": f"https://m.place.naver.com/restaurant/{pid}/menu/list"}

def x_count(q):
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok: return None
    u = "https://api.x.com/2/tweets/counts/recent?granularity=day&query=" + urllib.parse.quote(q)
    try: return json.loads(get(u, headers=[f"Authorization: Bearer {tok}"]))["meta"]["total_tweet_count"]
    except Exception: return None

def save_photo(url, slug):
    try:
        from PIL import Image
        raw = get(url, binary=True)
        im = Image.open(io.BytesIO(raw)).convert("RGB"); im.thumbnail((480, 480))
        p = f"img/{slug}.jpg"; im.save(os.path.join(HERE, p), "JPEG", quality=78); return p
    except Exception as e:
        print("  photo fail", e); return None

def main():
    no_photos = "--no-photos" in sys.argv
    seeds = json.load(open(os.path.join(HERE, "seeds.json")))
    snap_p = os.path.join(HERE, "sns_snapshot.json")
    snap = json.load(open(snap_p)) if os.path.exists(snap_p) else {}
    old = {}
    if os.path.exists(os.path.join(HERE, "data.json")):
        for r in json.load(open(os.path.join(HERE, "data.json")))["restaurants"]: old[r["name"]] = r
    today = datetime.date.today().isoformat()
    os.makedirs(os.path.join(HERE, "img"), exist_ok=True)
    out = []
    for i, s in enumerate(seeds):
        slug = f"r{i:02d}"; print(s["name"])
        r = {"name": s["name"], "cat": s["cat"], "naver_id": s.get("naver_id"), "tags": s.get("tags", []), "found_by": s.get("found_by", "웹 리서치 1차 목록"), "sources": []}
        d = collect_naver(s["naver_id"]) if s.get("naver_id") else None
        if d:
            r.update(d); r["sources"].append(f"https://m.place.naver.com/restaurant/{s['naver_id']}/home")
            r["map_url"] = f"https://map.naver.com/p/entry/place/{s['naver_id']}"
        else:
            man = s.get("manual") or {}
            r.update({"category": NA, "address": man.get("address", NA), "phone": NA, "reviews": None, "rating": None,
                      "blogs": None, "menus": man.get("menus", []), "price_range": man.get("price_range", NA),
                      "hours": man.get("hours", NA), "holiday": man.get("holiday", NA), "photo_src": None})
            if man.get("source"): r["sources"].append(man["source"])
            r["map_url"] = "https://map.naver.com/p/search/" + urllib.parse.quote(s["name"] + " 포항")
        # SNS
        c = x_count(s["x_query"])
        if c is not None: snap[s["name"]] = {"x_posts_7d": c, "x_query": s["x_query"], "measured": today}
        sn = snap.get(s["name"]) or {}
        r["sns"] = sn.get("x_posts_7d"); r["sns_measured"] = sn.get("measured"); r["x_query"] = s["x_query"]
        # photo
        prev = (old.get(s["name"]) or {}).get("photo")
        if r.get("photo_src") and not no_photos: r["photo"] = save_photo(r["photo_src"], slug) or prev
        else: r["photo"] = prev if prev and os.path.exists(os.path.join(HERE, prev)) else None
        r["updated"] = today
        out.append(r)
    key = lambda r: tuple(-1 if r.get(k) is None else r[k] for k in ("reviews", "blogs", "sns"))
    for cat in ("nam", "ocheon"):
        lst = sorted([r for r in out if r["cat"] == cat], key=key, reverse=True)
        for n, r in enumerate(lst, 1): r["rank"] = n
    out.sort(key=lambda r: (r["cat"], r["rank"]))
    json.dump(snap, open(snap_p, "w"), ensure_ascii=False, indent=1)
    data = {"last_updated": today,
            "ranking_rule": "방문자 리뷰 수 → 블로그·카페 리뷰 수 → X 최근 7일 언급 수 순서로 비교 (네이버 플레이스·X 기준)",
            "restaurants": out}
    json.dump(data, open(os.path.join(HERE, "data.json"), "w"), ensure_ascii=False, indent=1)
    print("saved", len(out), today)

if __name__ == "__main__":
    main()
