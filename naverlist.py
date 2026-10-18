"""네이버 플레이스 모바일 목록 페이지(검색어+좌표) 파서. discover.py / new_openings.py 공용."""
import json, re, subprocess, urllib.parse
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
def place_list(query, x, y):
    u = f"https://m.place.naver.com/restaurant/list?query={urllib.parse.quote(query)}&x={x}&y={y}"
    h = subprocess.run(["curl", "-sL", "--max-time", "30", "-A", UA, u], capture_output=True).stdout.decode("utf-8", "ignore")
    m = re.search(r"window.__APOLLO_STATE__\s*=\s*(\{.*?\});\s*window", h, re.S)
    if not m: return []
    out = []
    for k, v in json.loads(m.group(1)).items():
        if v.get("__typename") != "PlaceListBusinessesItem": continue
        n = lambda s: int(re.sub(r"[^\d]", "", s)) if s and re.sub(r"[^\d]", "", s) else 0
        out.append({"id": v["id"], "name": v["name"], "category": v.get("category"),
                    "addr": (v.get("commonAddress") or "") + " " + (v.get("roadAddress") or ""),
                    "reviews": n(v.get("visitorReviewCount")), "blogs": n(v.get("blogCafeReviewCount")),
                    "score": v.get("visitorReviewScore"), "newOpening": v.get("newOpening"), "isAd": "Ad" in k})
    return out
def area_of(addr):
    if "포항시 북구" in addr: return "buk"
    if "포항시 남구" not in addr: return None
    return "ocheon" if "오천읍" in addr else "nam"
