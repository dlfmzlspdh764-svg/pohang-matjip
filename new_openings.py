#!/usr/bin/env python3
"""포항 남구·북구·문덕·오천 신규 오픈 음식점 탐지.
1) 네이버 플레이스 목록에서 '새로 오픈(newOpening)' 표시가 붙은 음식점 수집
2) 네이버 블로그 검색 '그랜드오픈/신상 오픈' 글 제목도 참고용으로 수집
data.json 에 이미 있거나 new_openings_seen.json 에 기록된 곳은 제외하고 새 것만 출력.
결과: new_openings.json (이번 실행에서 새로 발견된 목록), new_openings_seen.json 갱신.
사용법: python3 new_openings.py"""
import json, os, re, subprocess, urllib.parse, datetime, html
from naverlist import place_list, area_of, UA
HERE = os.path.dirname(os.path.abspath(__file__))
SPOTS = [("오천", 129.405, 35.965), ("문덕", 129.405, 35.962), ("효자동", 129.329, 36.008), ("이동", 129.338, 36.030),
         ("상도동", 129.360, 36.025), ("대이동", 129.335, 36.028), ("구룡포", 129.555, 35.990), ("연일", 129.345, 35.995),
         ("죽도동", 129.366, 36.036), ("양학동", 129.354, 36.040), ("장성동", 129.375, 36.067), ("두호동", 129.385, 36.060),
         ("영일대", 129.380, 36.056), ("흥해", 129.351, 36.110), ("청하", 129.340, 36.197), ("송라", 129.375, 36.230), ("기계", 129.215, 36.060)]
WORDS = ["맛집", "음식점", "술집", "고기집", "점심", "신상 맛집", "횟집"]
BAD = ("카페", "베이커리", "디저트", "제과", "케이크", "도넛", "아이스크림", "빙수", "떡")
BLOGQ = ["포항 오천 그랜드오픈", "포항 문덕 신상 맛집 오픈", "포항 남구 신규오픈 맛집", "포항 효자동 그랜드오픈", "포항 북구 신규오픈 맛집", "포항 장성동 그랜드오픈", "영일대 신상 맛집 오픈"]

def blog_titles(q):
    u = "https://m.search.naver.com/search.naver?where=m_blog&sm=mtb_opt&nso=so%3Add%2Cp%3A1m&query=" + urllib.parse.quote(q)
    h = subprocess.run(["curl", "-sL", "--max-time", "30", "-A", UA, u], capture_output=True).stdout.decode("utf-8", "ignore")
    FOOD = ("맛집", "식당", "횟집", "고기", "돈까스", "국밥", "술집", "이자카야", "삼계탕", "피자", "버거", "라멘", "회")
    NOISE = ("카페", "베이커리", "헬멧", "스터디", "독서실", "미용", "금리", "주식", "AI", "신규 음식점", "사진전")
    texts = {}
    # 2026-10 네이버 모바일 마크업: 한 글에 앵커가 여러 개(썸네일·제목·본문 요약)라 URL별로 텍스트를 모은다
    for m in re.finditer(r'<a[^>]*href="(https://m\.blog\.naver\.com/[\w.-]+/\d+)"[^>]*>(.*?)</a>', h, re.S):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        if t: texts.setdefault(m.group(1), []).append(t)
    out = []
    for url, ts in texts.items():
        title = min(ts, key=len) if ts else ""
        full = " ".join(ts)
        if len(title) > 8 and ("오픈" in full or "신상" in full) and any(f in full for f in FOOD) and not any(n in title for n in NOISE):
            out.append({"title": title[:120], "url": url})
    return out[:10]

def main():
    known = set()
    dp = os.path.join(HERE, "data.json")
    if os.path.exists(dp):
        known = {r.get("naver_id") for r in json.load(open(dp))["restaurants"]}
    sp = os.path.join(HERE, "new_openings_seen.json")
    seen = json.load(open(sp)) if os.path.exists(sp) else {"places": {}, "blogs": []}
    today = datetime.date.today().isoformat()
    new = {}
    for (an, x, y) in SPOTS:
        for w in WORDS:
            for p in place_list(f"{an} {w}", x, y):
                if not p["newOpening"] or p["isAd"]: continue
                area = area_of(p["addr"])
                if not area or any(b in (p["category"] or "") for b in BAD): continue
                if p["id"] in known or p["id"] in seen["places"] or p["id"] in new: continue
                new[p["id"]] = {"name": p["name"], "area": {"ocheon": "문덕·오천", "buk": "포항 북구"}.get(area, "포항 남구"),
                                "category": p["category"], "address": p["addr"].strip(), "reviews": p["reviews"],
                                "blogs": p["blogs"], "map_url": f"https://map.naver.com/p/entry/place/{p['id']}",
                                "first_seen": today}
    blogs = []
    for q in BLOGQ:
        for b in blog_titles(q):
            if b["url"] not in seen["blogs"] and b["url"] not in [x["url"] for x in blogs]: blogs.append(b)
    for k, v in new.items(): seen["places"][k] = {"name": v["name"], "first_seen": today}
    seen["blogs"] += [b["url"] for b in blogs]
    json.dump(seen, open(sp, "w"), ensure_ascii=False, indent=1)
    res = {"checked": today, "new_places": list(new.values()), "new_blog_posts": blogs}
    json.dump(res, open(os.path.join(HERE, "new_openings.json"), "w"), ensure_ascii=False, indent=1)
    print(f"새로 발견된 신규 오픈 음식점 {len(new)}곳")
    for v in sorted(new.values(), key=lambda v: -v["reviews"]):
        print(f"- [{v['area']}] {v['name']} ({v['category']}) 리뷰 {v['reviews']} · {v['address']} · {v['map_url']}")
    print(f"참고 블로그 글 {len(blogs)}건")
    for b in blogs: print(f"- {b['title']} {b['url']}")

if __name__ == "__main__":
    main()
