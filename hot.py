#!/usr/bin/env python3
"""🔥 실시간 핫플 (인기 급상승) 계산 — GitHub Actions에서 3시간마다 실행.

신호 (모두 로그인 없는 공개 페이지, 실제로 수집되는 것만 사용):
  1) 네이버 블로그 글 수 (section.blog.naver.com 검색 API의 totalCount, 날짜 범위 지정)
     - 최근 7일 vs 직전 7일(8~14일 전) vs 직전 30일(8~37일 전)의 주 평균
  2) 네이버 방문자 리뷰: 최근순 리뷰 첫 페이지에서 최근 7일 작성 리뷰 수(페이지 한도 내) +
     일별 스냅샷(history/YYYY-MM-DD.json)의 방문자 리뷰 총수 증가분(1일·7일)
  3) X 최근 7일 언급 수: X_BEARER_TOKEN 있을 때만
  인스타그램·페이스북·틱톡·구글 검색 수는 비로그인으로 신뢰성 있게 받을 수 없어 수집하지 않음 (social_probe 결과 기록).
점수 = 최근7일 블로그 × (1 + 성장률[−100%~+500%로 제한]) + 최근7일 리뷰 × 2 + X언급
  (블로그 최근 7일 2건 이상 또는 최근 7일 리뷰 3건 이상인 곳만 후보)
신규 탐지: 지역별 네이버 플레이스 목록 중 앱에 없는 곳의 최근 7일 블로그 수를 재서 3건 이상이면 핫플 후보로 추가하고 seeds.json에도 등록(다음 일일 갱신 때 전체 정보 수집).
결과: hot.json, history/YYYY-MM-DD.json(일별 스냅샷), history/blogwin.json(직전 기간 블로그 수 캐시)
"""
import json, os, re, sys, time, datetime, subprocess, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from naverlist import place_list, area_of
HERE = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
now = datetime.datetime.now(KST); today = now.date()
D = lambda n: (today - datetime.timedelta(days=n)).isoformat()

def curl(url, headers=()):
    cmd = ["curl", "-sL", "--compressed", "--max-time", "25", "-A", UA]
    for h in headers: cmd += ["-H", h]
    return subprocess.run(cmd + [url], capture_output=True).stdout.decode("utf-8", "ignore")

CAP = 30
def blog_count(keyword, start, end):
    """네이버 모바일 블로그 검색(정확한 구문 "..." + 기간 지정)의 첫 페이지에 나온 서로 다른 글 수. 한 페이지 한도(약 30) 이상이면 CAP으로 표기."""
    s, e = start.replace("-", ""), end.replace("-", "")
    u = ("https://m.search.naver.com/search.naver?where=m_blog&query=" + urllib.parse.quote(keyword)
         + f"&nso=so%3Add%2Cp%3Afrom{s}to{e}")
    for _ in range(2):
        h = curl(u)
        if len(h) > 20000:
            return min(CAP, len(set(re.findall(r"https://m\.blog\.naver\.com/([\w-]+/\d+)", h))))
        time.sleep(2)
    return None

def keyword_for(name):
    """체인점은 지점 동네명까지 넣어 다른 지점 글이 섞이지 않게 함. 예) '명륜진사갈비 문덕점' → "명륜진사갈비" 문덕"""
    toks = name.split(); loc = ""
    if len(toks) > 1 and toks[-1].endswith("점"):
        loc = re.sub(r"(본점|점)$", "", toks[-1]); loc = re.sub(r"^포항", "", loc); toks = toks[:-1]
    core = " ".join(toks)
    return f'"{core}" {loc}' if loc and loc not in ("남구", "북구", "") else f'"{core}" 포항'

def recent_reviews(pid):
    h = curl(f"https://m.place.naver.com/restaurant/{pid}/review/visitor?reviewSort=recent")
    ds = re.findall(r'"created":"(\d{1,2})\.(\d{1,2})\.', h)
    if not ds: return None
    n = 0
    for m, d in ds:
        try:
            dt = datetime.date(today.year, int(m), int(d))
            if dt > today: dt = dt.replace(year=today.year - 1)
            if (today - dt).days <= 6: n += 1
        except ValueError: pass
    return {"count": n, "capped": n == len(ds)}

def x_count(q):
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok: return None
    t = curl("https://api.x.com/2/tweets/counts/recent?granularity=day&query=" + urllib.parse.quote(q), [f"Authorization: Bearer {tok}"])
    try: return json.loads(t)["meta"]["total_tweet_count"]
    except Exception: return None

def growth(b7, base):
    if b7 is None: return None
    if not base: return None if not b7 else float("inf")
    return (b7 - base) / base

def main():
    data = json.load(open(os.path.join(HERE, "data.json")))
    R = data["restaurants"]
    hist_dir = os.path.join(HERE, "history"); os.makedirs(hist_dir, exist_ok=True)
    cache_p = os.path.join(hist_dir, "blogwin.json")
    cache = json.load(open(cache_p)) if os.path.exists(cache_p) else {}
    cache = {k: v for k, v in cache.items() if v.get("date") == today.isoformat()}  # 날짜 바뀌면 직전기간 재계산
    def snap(n):
        p = os.path.join(hist_dir, f"{D(n)}.json")
        return json.load(open(p)) if os.path.exists(p) else None
    s1, s7 = snap(1), snap(7)

    def work(r):
        kw = keyword_for(r.get("naver_name") or r["name"])
        b7 = blog_count(kw, D(6), D(0))
        c = cache.get(r["name"])
        if not c or c.get("kw") != kw:
            c = {"date": today.isoformat(), "kw": kw, "prev7": blog_count(kw, D(13), D(7)), "prev30": blog_count(kw, D(37), D(8))}
        rv = recent_reviews(r["naver_id"]) if r.get("naver_id") else None
        return r, kw, b7, c, rv
    with ThreadPoolExecutor(3) as ex: res = list(ex.map(work, R))

    items, okb, okr = [], 0, 0
    for r, kw, b7, c, rv in res:
        cache[r["name"]] = c
        if b7 is not None: okb += 1
        if rv is not None: okr += 1
        base = None
        if c.get("prev7") is not None or c.get("prev30") is not None:
            base = max(c.get("prev7") or 0, (c.get("prev30") or 0) * 7 / 30)
        g = growth(b7, base)
        d1 = (r.get("reviews") - s1[r["name"]]["reviews"]) if s1 and r["name"] in s1 and r.get("reviews") is not None and s1[r["name"]].get("reviews") is not None else None
        d7 = (r.get("reviews") - s7[r["name"]]["reviews"]) if s7 and r["name"] in s7 and r.get("reviews") is not None and s7[r["name"]].get("reviews") is not None else None
        rv7 = rv["count"] if rv else None
        x7 = x_count(kw)
        gl = 0 if (b7 or 0) < 3 or g is None else (5 if g == float("inf") else max(-1, min(5, g)))
        score = (b7 or 0) * (1 + gl) + (rv7 or 0) * 2 + (x7 or 0)
        eligible = (b7 or 0) >= 2 or (rv7 or 0) >= 3
        badges = []
        if b7:
            if b7 >= 3 and g == float("inf"): badges.append(f"블로그 신규 {b7}건")
            elif b7 >= 3 and g is not None and g > 0: badges.append(f"블로그 +{round(g * 100)}%")
            badges.append(f"7일 블로그 {b7}{'+' if b7 >= CAP else ''}건")
        if rv7: badges.append(f"7일 리뷰 {rv7}{'+' if rv and rv['capped'] else ''}건")
        if d1: badges.append(f"하루 리뷰 +{d1}")
        if x7: badges.append(f"X {x7}건")
        items.append({"name": r["name"], "cat": r["cat"], "in_data": True, "keyword": kw, "blog7": b7, "blog_prev7": c.get("prev7"),
                      "blog_prev30": c.get("prev30"), "blog_growth_pct": None if g is None else ("new" if g == float("inf") else round(g * 100)),
                      "review7": rv7, "review7_capped": bool(rv and rv["capped"]), "review_delta_1d": d1, "review_delta_7d": d7,
                      "x7": x7, "score": round(score, 1), "eligible": eligible, "badges": badges})

    # 신규 탐지
    known = {r.get("naver_id") for r in R}; known_names = {r["name"] for r in R}
    SPOTS = {"ocheon": [("오천", 129.405, 35.965), ("문덕", 129.405, 35.962)],
             "nam": [("효자동", 129.329, 36.008), ("이동", 129.338, 36.030), ("상도동", 129.360, 36.025), ("구룡포", 129.555, 35.990), ("대이동", 129.335, 36.028)],
             "buk": [("죽도동", 129.366, 36.036), ("양학동", 129.354, 36.040), ("장성동", 129.375, 36.067), ("두호동", 129.385, 36.060), ("영일대", 129.380, 36.056), ("흥해", 129.351, 36.110), ("청하", 129.340, 36.197), ("송라", 129.375, 36.230), ("기계", 129.215, 36.060)]}
    seeds_p = os.path.join(HERE, "seeds.json"); seeds = json.load(open(seeds_p)); seed_ids = {s.get("naver_id") for s in seeds}
    discovered = []
    for area, spots in SPOTS.items():
        cand = {}
        for an, x, y in spots:
            for w in ("맛집", "신상 맛집", "핫플"):
                for p in place_list(f"{an} {w}", x, y):
                    if p["isAd"] or area_of(p["addr"]) != area or p["id"] in known or p["name"] in known_names: continue
                    if any(b in (p["category"] or "") for b in ("카페", "베이커리", "디저트", "제과", "절", "사찰", "명소", "공원", "관광", "숙박", "노래", "PC방", "헬스")): continue
                    cand[p["id"]] = p
        scored = []
        for p in list(cand.values())[:25]:
            kw = keyword_for(p["name"]); b7 = blog_count(kw, D(6), D(0))
            if b7 and b7 >= 3:
                pv = blog_count(kw, D(13), D(7)) or 0
                g = (b7 - pv) / pv if pv else float("inf")
                scored.append((b7 * (1 + (5 if g == float("inf") else max(-1, min(5, g)))), p, kw, b7, pv, g))
        for sc, p, kw, b7, pv, g in sorted(scored, key=lambda t: -t[0])[:3]:
            badges = [f"블로그 신규 {b7}건" if g == float("inf") else (f"블로그 +{round(g * 100)}%" if g > 0 else f"7일 블로그 {b7}건"), "새로 발견"]
            discovered.append({"name": p["name"], "cat": area, "in_data": False, "keyword": kw, "blog7": b7, "blog_prev7": pv,
                               "blog_growth_pct": "new" if g == float("inf") else round(g * 100), "score": round(sc, 1), "eligible": True,
                               "badges": badges, "category": p["category"], "address": p["addr"].strip(), "reviews": p["reviews"],
                               "map_url": f"https://map.naver.com/p/entry/place/{p['id']}", "naver_id": p["id"]})
            if p["id"] not in seed_ids:
                seeds.append({"cat": area, "name": p["name"], "naver_id": p["id"], "tags": [], "x_query": kw,
                              "found_by": f"핫플 탐지 ({today.isoformat()}, 최근 7일 블로그 {b7}건)"}); seed_ids.add(p["id"])
    json.dump(seeds, open(seeds_p, "w"), ensure_ascii=False, indent=1)

    allitems = [i for i in items + discovered if i["eligible"]]
    top = {a: sorted([i for i in allitems if a == "all" or i["cat"] == a], key=lambda i: -i["score"])[:10] for a in ("nam", "buk", "ocheon", "all")}
    probe_p = os.path.join(HERE, "social_probe.json")
    probe = json.load(open(probe_p)) if os.path.exists(probe_p) else {}
    out = {"updated": now.strftime("%Y-%m-%d %H:%M KST"),
           "rule": "최근 7일 네이버 블로그 글 수(정확한 상호 검색, 최대 30건까지 집계) × (1+성장률, 직전 7일·30일 주평균 대비) + 최근 7일 방문자 리뷰 × 2 + X 언급",
           "signals": {"naver_blog": f"수집됨 ({okb}/{len(R)})", "naver_review_recent": f"수집됨 ({okr}/{len(R)})",
                       "naver_review_snapshot_delta": "수집됨" if s1 else "기록 쌓는 중 (내일부터 하루 증가분 표시)",
                       "x": "수집됨" if os.environ.get("X_BEARER_TOKEN") else "미수집 (X_BEARER_TOKEN 없음)",
                       "instagram": probe.get("instagram", "미수집"), "facebook": probe.get("facebook", "미수집"),
                       "tiktok": probe.get("tiktok", "미수집"), "google": probe.get("google", "미수집")},
           "top": top, "discovered": discovered, "all": sorted(items, key=lambda i: -i["score"])}
    json.dump(out, open(os.path.join(HERE, "hot.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(cache, open(cache_p, "w"), ensure_ascii=False, indent=0)
    sp = os.path.join(hist_dir, f"{today.isoformat()}.json")
    json.dump({r["name"]: {"reviews": r.get("reviews"), "blogs": r.get("blogs"),
                           "blog7": next((i["blog7"] for i in items if i["name"] == r["name"]), None),
                           "review7": next((i["review7"] for i in items if i["name"] == r["name"]), None)} for r in R},
              open(sp, "w"), ensure_ascii=False, indent=0)
    print(out["updated"], out["signals"])
    for a in ("nam", "buk", "ocheon"):
        print(a, [(i["name"], i["score"], i["badges"][:2]) for i in top[a]])

if __name__ == "__main__":
    main()
