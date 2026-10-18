#!/usr/bin/env python3
"""인스타그램·페이스북·틱톡·구글에서 로그인 없이 공개 수치(게시물 수 등)를 받을 수 있는지 매 실행 확인 → social_probe.json.
수치를 실제로 파싱하지 못하면 '미수집 (사유)'로 기록. 지금까지 모두 로그인/캡차/JS 요구로 미수집."""
import json, os, re, subprocess
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"
T = "%ED%8F%AC%ED%95%AD%EB%A7%9B%EC%A7%91"  # 포항맛집
P = {"instagram": (f"https://www.instagram.com/explore/tags/{T}/", r'"media_count":\s*(\d+)'),
     "tiktok": (f"https://www.tiktok.com/tag/{T}", r'"videoCount":(\d+)'),
     "facebook": (f"https://www.facebook.com/hashtag/{T}", r'(\d[\d,]*)\s*(?:posts|게시물)'),
     "google": ("https://www.google.com/search?q=%22%ED%8F%AC%ED%95%AD%EB%A7%9B%EC%A7%91%22", r'검색결과 약 ([\d,]+)개')}
out = {}
for k, (u, rx) in P.items():
    r = subprocess.run(["curl", "-sL", "--max-time", "20", "-A", UA, "-o", "-", "-w", "\n%{http_code} %{url_effective}", u], capture_output=True).stdout.decode("utf-8", "ignore")
    body, _, meta = r.rpartition("\n"); m = re.search(rx, body)
    if m: out[k] = f"수집 가능 (#포항맛집 {m.group(1)})"
    else:
        why = "로그인 요구" if "login" in meta or "login" in body[:20000].lower() else ("캡차/JS 요구" if "captcha" in body.lower() or "enablejs" in body else f"수치 없음 (HTTP {meta.split()[0] if meta else '?'})")
        out[k] = f"미수집 ({why})"
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "social_probe.json"), "w"), ensure_ascii=False, indent=1)
print(out)
