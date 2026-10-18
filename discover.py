#!/usr/bin/env python3
"""필터 칩(술집/횟집/뒷고기/직장인 가성비)용 후보를 네이버 플레이스 목록에서 찾아 seeds.json에 추가.
지역별·태그별로 방문자 리뷰 수 상위 N곳(리뷰 50건 이상)을 고름. 이미 있는 곳은 태그만 붙임."""
import json, os, sys
from naverlist import place_list, area_of
HERE = os.path.dirname(os.path.abspath(__file__))
N = 5
AREAS = {"ocheon": [("오천", 129.405, 35.965), ("문덕", 129.405, 35.962)],
         "nam": [("효자동", 129.329, 36.008), ("이동", 129.338, 36.030), ("상도동", 129.360, 36.025), ("구룡포", 129.555, 35.990)]}
CATOK = {"술집": ("술집","주점","이자카야","포장마차","바(BAR)","맥주","호프","요리주점","오뎅","꼬치","막창","곱창","전,빈대떡","일본식주점"),
         "횟집": ("회","해물","물회","대게","게요리","생선","해산물","조개"),
         "뒷고기": ("돼지","고기","육류","뒷고기"),
         "직장인 가성비": ("한식","백반","국밥","찌개","칼국수","국수","분식","뷔페","덮밥","돈가스","정식","해장국","중식","중국","냉면","김밥","두루치기","곰탕","가정식","순대","식당")}
BAD = ("베이커리","카페","디저트","제과","케이크","도넛")
TAGS = {"술집": ["술집", "이자카야", "포차"], "횟집": ["횟집", "물회"], "뒷고기": ["뒷고기"],
        "직장인 가성비": ["점심 가성비", "백반", "한식뷔페"]}
seeds = json.load(open(os.path.join(HERE, "seeds.json")))
byid = {s["naver_id"]: s for s in seeds if s.get("naver_id")}
for area, spots in AREAS.items():
    for tag, words in TAGS.items():
        cand = {}
        for (aname, x, y) in spots:
            for w in words:
                for p in place_list(f"{aname} {w}", x, y):
                    if p["isAd"] or area_of(p["addr"]) != area or p["reviews"] < 50: continue
                    c = p["category"] or ""
                    if any(b in c for b in BAD) or not any(k in c for k in CATOK[tag]): continue
                    if tag == "뒷고기" and "뒷고기" not in p["name"] + c and w == "뒷고기": pass
                    cand[p["id"]] = p
        top = sorted(cand.values(), key=lambda p: (p["reviews"], p["blogs"]), reverse=True)[:N]
        print(area, tag, [(p["name"], p["reviews"]) for p in top])
        for p in top:
            if p["id"] in byid:
                byid[p["id"]].setdefault("tags", [])
                if tag not in byid[p["id"]]["tags"]: byid[p["id"]]["tags"].append(tag)
            else:
                s = {"cat": area, "name": p["name"], "naver_id": p["id"], "tags": [tag],
                     "x_query": f'"{p["name"].split()[0]}" 포항', "found_by": f"네이버 플레이스 검색 '{tag}'"}
                seeds.append(s); byid[p["id"]] = s
for s in seeds: s.setdefault("tags", [])
json.dump(seeds, open(os.path.join(HERE, "seeds.json"), "w"), ensure_ascii=False, indent=1)
print("seeds:", len(seeds))
