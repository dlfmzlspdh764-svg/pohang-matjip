#!/usr/bin/env python3
"""랭킹 섹션(회식/치킨/과메기) 후보를 네이버 플레이스 목록에서 찾아 seeds.json에 추가 (태그 없이 후보만).
실제 섹션 포함 여부·순위는 update.py가 상세 데이터(업종·메뉴·단체석·키워드 투표)로 판정."""
import json, os, sys
from naverlist import place_list, area_of
HERE = os.path.dirname(os.path.abspath(__file__))
SPOTS = {"ocheon": [("오천", 129.405, 35.965), ("문덕", 129.405, 35.962)],
         "nam": [("효자동", 129.329, 36.008), ("이동", 129.338, 36.030), ("상도동", 129.360, 36.025), ("구룡포", 129.555, 35.990), ("호미곶", 129.566, 36.076), ("연일", 129.345, 35.995)],
         "buk": [("죽도동", 129.366, 36.036), ("양학동", 129.354, 36.040), ("장성동", 129.375, 36.067), ("두호동", 129.385, 36.060), ("영일대", 129.380, 36.056), ("흥해", 129.351, 36.110), ("청하", 129.340, 36.197), ("송라", 129.375, 36.230), ("기계", 129.215, 36.060)]}
SEC = {"치킨": (["치킨", "통닭", "닭강정"], ("치킨", "닭강정", "통닭")),
       "과메기": (["과메기"], None),
       "회식": (["회식", "단체 회식 장소", "룸 식당"], None)}
seeds = json.load(open(os.path.join(HERE, "seeds.json")))
have = {s.get("naver_id") for s in seeds}
added = 0
for area, spots in (SPOTS.items() if len(sys.argv) < 2 else [(a, SPOTS[a]) for a in sys.argv[1:]]):
    for sec, (words, catok) in SEC.items():
        cand = {}
        for an, x, y in spots:
            for w in words:
                for p in place_list(f"{an} {w}", x, y):
                    if p["isAd"] or area_of(p["addr"]) != area: continue
                    if catok and not any(c in (p["category"] or "") for c in catok): continue
                    if any(b in (p["category"] or "") for b in ("카페", "베이커리", "디저트")): continue
                    cand[p["id"]] = p
        top = sorted(cand.values(), key=lambda p: (p["reviews"], p["blogs"]), reverse=True)[:14]
        print(area, sec, [(p["name"], p["reviews"]) for p in top])
        for p in top:
            if p["id"] in have: continue
            seeds.append({"cat": area, "name": p["name"], "naver_id": p["id"], "tags": [],
                          "x_query": f'"{p["name"].split()[0]}" 포항', "found_by": f"네이버 플레이스 검색 '{sec}'"})
            have.add(p["id"]); added += 1
json.dump(seeds, open(os.path.join(HERE, "seeds.json"), "w"), ensure_ascii=False, indent=1)
print("added", added, "total", len(seeds))
