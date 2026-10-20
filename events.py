#!/usr/bin/env python3
"""포항 행사·축제 수집 → events.json (GitHub Actions 매일 06:00 KST + 수동 실행).
출처
 1) 포항시 문화관광 '퐝퐝여행' 포항은지금: 관광축제/공연/전시/행사/체험/시립예술단 목록·상세 (pohang.go.kr/phtour)
 2) 한국관광공사 '대한민국 구석구석 축제'(kfes) 경북 목록 중 포항 주소
 3) Google 뉴스 RSS '포항 축제' 최근 기사 (날짜를 만들지 않고 기사 링크만 참고용으로 제공)
지난 행사는 빼고, 진행중/예정만 남김. 수집 실패 시 이전 events.json 항목을 유지(데이터를 지우지 않음).
포스터는 ev/<sha1>.jpg 로 저장(가로 640px)."""
import json, os, re, sys, html, hashlib, datetime, subprocess, urllib.parse, io
HERE = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST); TODAY = NOW.date().isoformat()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"
PH = "https://www.pohang.go.kr"
TYPES = [(2, 75, "축제", "&org_code=0001"), (3, 27, "공연", ""), (4, 28, "전시", ""), (5, 29, "행사", ""), (7, 77, "체험", ""), (8, 78, "시립예술단", "")]
NA = "정보 없음"
DEBUG = "--debug" in sys.argv

def get(url, data=None, ref=None, binary=False, t=30):
    cmd = ["curl", "-sL", "--max-time", str(t), "-A", UA]
    if ref: cmd += ["-e", ref]
    if data: cmd += ["-d", data]
    r = subprocess.run(cmd + [url], capture_output=True).stdout
    return r if binary else r.decode("utf-8", "ignore")

def txt(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return "\n".join(l for l in (re.sub(r"[ \t\u00a0]+", " ", x).strip() for x in s.split("\n")) if l)

# 지역 분류: 주소/장소 텍스트 기준. 판단 불가 → 'all'(포항 전역)
OCHEON = r"오천|문덕|청림|제철동|구정리|원동|세계리|냉천"
NAM = r"남구|송도|효자|대잠|이동|상도|해도|구룡포|호미곶|연일|대송|동해면|장기|운하|시청|포스코|스틸야드|도구|연오랑|귀비고|문화예술회관|지곡|청송대|형산강|부조장터|호미반도|흥환"
BUK = r"북구|우창|마장지|영일대|죽도|양학|장성|두호|환호|여남|흥해|청하|송라|기계|죽장|신광|기북|양덕|장량|중앙상가|중앙아트홀|동빈|꿈틀로|시립미술관|스페이스워크|수목원|실내체육관|덕수동|대흥동|항구동|우현|창포|북부|이가리|월포|칠포|곤륜산|사방|초곡|서포중|보건고"
def area_of(*t):
    s = " ".join(x or "" for x in t)
    if "포항시 남구" in s or "포항시남구" in s: return "ocheon" if re.search(r"오천읍", s) else "nam"
    if "포항시 북구" in s or "포항시북구" in s: return "buk"
    for k, a in ((OCHEON, "ocheon"), (BUK, "buk"), (NAM, "nam")):
        if re.search(k, s): return a
    return "all"

def save_img(url):
    if not url: return None
    name = "ev/" + hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    p = os.path.join(HERE, name)
    if os.path.exists(p): return name
    try:
        from PIL import Image
        im = None
        for _ in range(3):
            b = get(url, binary=True, ref=PH + "/phtour/index.do", t=90)
            try: im = Image.open(io.BytesIO(b)); im.load(); im = im.convert("RGB"); break
            except Exception: im = None
        if im is None: raise ValueError("이미지 받기 실패")
        if im.width > 640: im = im.resize((640, int(im.height * 640 / im.width)))
        im.save(p, "JPEG", quality=74, optimize=True, progressive=True); return name
    except Exception as e:
        print("  img fail", url, e); return None

def ph_view(path):
    h = get(PH + path)
    i = h.rfind("MCbox__info"); j = h.find("<footer", i)
    body = txt(h[h.find("</dl>", i):j]) if i > 0 else ""
    body = re.split(r"\n\s*37683 |\n목록으로|\n이전글|\n다음글", "\n" + body)[0]
    links = [u for u in re.findall(r'href="(https?://[^"]+)"', h[i:j] if i > 0 else "")
             if not re.search(r"pohang\.go\.kr/phtour/(?:index|wmap)|facebook\.com/sharer|kakao|naver\.com/share|twitter", u)]
    return body.strip()[:1500], (links[0] if links else None)

def scrape_phtour():
    out = []
    for dt, mi, typ, extra in TYPES:
        for page in range(1, 6):
            u = f"{PH}/phtour/wmap/festival/index.do?menu_idx={mi}&date_type={dt}{extra}&viewPage={page}"
            h = get(u)
            items = re.findall(r'<a href="(/phtour/wmap/festival/view\.do[^"]+)" class="MCbox__item">(.*?)</a>\s*</div>', h, re.S)
            if not items: break
            old_cnt = 0
            for href, b in items:
                title = txt(re.search(r'class="MCbox__title">(.*?)</strong>', b, re.S).group(1))
                title = re.sub(r"^(진행|종료|예정|마감)\s*", "", title).strip()
                info = {}
                for k, v in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", b, re.S): info[txt(k)] = txt(v)
                dates = re.findall(r"(\d{4}-\d{2}-\d{2})", " ".join(v for k, v in info.items() if "회" in k or "일시" in v))
                if not dates: continue
                s, e = min(dates), max(dates)
                if e < TODAY: old_cnt += 1; continue
                if re.search(r"모집|공모|신청 안내$|채용", title): continue
                img = re.search(r'<img[^>]+src="([^"]+)"', b)
                fee = info.get("이용료") or NA
                if info.get("이용금액"): fee = (fee + " · " + info["이용금액"]) if fee != NA else info["이용금액"]
                cm = re.search(r"cm_idx=(\d+)", href).group(1)
                out.append({"id": f"ph{cm}", "title": title, "type": typ, "start": s, "end": e,
                            "venue": info.get("장소") or NA, "fee": fee, "org": info.get("주최/주관") or NA,
                            "age": info.get("관람연령") or NA, "tel": info.get("문의처") or NA,
                            "img_src": (PH + img.group(1)) if img and img.group(1).startswith("/") else (img.group(1) if img else None),
                            "src": "포항시 문화관광(퐝퐝여행) " + typ, "srcu": PH + href.replace("&amp;", "&"), "_view": href.replace("&amp;", "&")})
            if old_cnt == len(items): break  # 이 페이지가 전부 지난 행사 → 다음 페이지는 더 오래된 것
        print(f"phtour {typ}: 누적 {len(out)}")
    for ev in out:
        d, link = ph_view(ev.pop("_view"))
        ev["desc"] = d or NA; ev["link"] = link
    return out

def scrape_kfes():
    U = "https://korean.visitkorea.or.kr/kfes/list/selectWntyFstvlList.do"; REF = "https://korean.visitkorea.or.kr/kfes/list/wntyFstvlList.do"
    allr = {}
    for m in range(NOW.month, NOW.month + 3):
        mm = "%02d" % ((m - 1) % 12 + 1); idx = 0
        for _ in range(8):
            data = urllib.parse.urlencode(dict(startIdx=idx, searchType="A", searchDate=mm, searchArea="35", searchCate="",
                                               locationx="undefined", locationy="undefined", filterExcluded="true"))
            try: d = json.loads(get(U, data=data, ref=REF))
            except Exception as e: print("kfes fail", mm, e); break
            r = d.get("resultList") or []
            for x in r: allr[x["fstvlCntntsId"]] = x
            idx += len(r)
            if not r or idx >= int(d.get("totalCnt") or 0): break
    out = []
    for x in allr.values():
        if "포항" not in (x.get("adres") or ""): continue
        s = (x.get("fstvlBgngDe") or "").replace(".", "-"); e = (x.get("fstvlEndDe") or "").replace(".", "-") or s
        if not re.match(r"\d{4}-\d{2}-\d{2}$", s) or e < TODAY: continue
        hp = (lambda m: m.group(1) if m else "")(re.search(r'href="([^"]+)"', x.get("fstvlHmpgUrl") or "")) or (x.get("fstvlHmpgUrl") or "").strip()
        fee = re.sub(r"\s+", " ", txt(x.get("fstvlUtztFareInfo") or "")).strip()
        out.append({"id": "kf" + x["fstvlCntntsId"][:8], "title": x["cntntsNm"].strip(), "type": "축제", "start": s, "end": e,
                    "venue": " ".join(v for v in [(x.get("adres") or "").strip(), (x.get("dtadr") or "").strip()] if v) or NA,
                    "fee": fee or NA, "org": (x.get("fstvlAspcsNm") or "").strip() or NA, "age": NA,
                    "tel": (x.get("fstvlAspcsTelno") or "").strip() or NA, "img_src": x.get("dispFstvlCntntsImgRout"),
                    "desc": txt(x.get("fstvlOutlCn") or "")[:1500] or NA, "link": hp if hp.startswith("http") else None,
                    "src": "한국관광공사 대한민국 구석구석 축제",
                    "srcu": "https://korean.visitkorea.or.kr/kfes/detail/fstvlDetail.do?fstvlCntntsId=" + x["fstvlCntntsId"]})
    print("kfes 포항:", len(out))
    return out

def scrape_news():
    u = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": "포항 축제 OR 포항 행사 개최 when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    out = []
    for it in re.findall(r"<item>(.*?)</item>", get(u), re.S)[:40]:
        g = lambda t: html.unescape((re.search(fr"<{t}[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()
        t = g("title")
        if "포항" not in t or re.search(r"성료|폐막|마무리|막 내려|성황리|결산|부고|사고|사망", t): continue
        out.append({"title": t, "url": g("link"), "date": g("pubDate"), "source": g("source")})
        if len(out) >= 12: break
    print("news:", len(out))
    return out

def core_title(t):
    t = re.sub(r"\[[^\]]*\]|「|」|《|》|'|\"|‘|’|“|”|\(.*?\)", " ", t)
    t = re.sub(r"20\d\d년?도?|제\d+회|개최|안내|축제 안내", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def apply_lineups(evs):
    """lineups.json(공식 확인분만 사람이 관리)을 행사에 붙이고, 미발표·미등록 주요 행사는 매일 뉴스에서 출연진 소식을 찾아
    '확인 전 소식'으로만 붙임(자동으로 '공식 확인' 처리하지 않음)."""
    lp = os.path.join(HERE, "lineups.json")
    L = json.load(open(lp))["lineups"] if os.path.exists(lp) else []
    checks = 0
    for x in evs:
        m = next((l for l in L if re.search(l["match"], x["title"]) and (not l.get("start") or l["start"] == x["start"])), None)
        if m: x["lineup"] = {k: m.get(k) for k in ("status", "performers", "stage", "note", "sources", "checked")}
        need = (m and m["status"] != "confirmed") or (not m and x["type"] in ("축제", "행사") and x.get("origin") == "kfes")
        if not need or checks >= 12: continue
        checks += 1
        q = f'"{core_title(x["title"])[:30]}" 포항 (출연 OR 초대가수 OR 라인업 OR 축하공연) when:21d'
        try:
            rss = get("https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}))
        except Exception: continue
        news = []
        for it in re.findall(r"<item>(.*?)</item>", rss, re.S)[:15]:
            g = lambda tg: html.unescape((re.search(fr"<{tg}[^>]*>(.*?)</{tg}>", it, re.S) or [None, ""])[1]).strip()
            tt = g("title")
            if re.search(r"출연|가수|라인업|축하공연|무대", tt) and not re.search(r"성료|폐막|마무리|성황", tt):
                news.append({"title": tt, "url": g("link"), "date": g("pubDate"), "source": g("source")})
        if news:
            x["lineup_news"] = news[:5]
            print("  라인업 새 소식(확인 필요):", x["title"][:30], "→", [n["title"][:50] for n in news[:3]])

def norm(t): return re.sub(r"[\s\W_]|제\d+회|20\d\d|개최|안내|년", "", t or "")

def main():
    op = os.path.join(HERE, "events.json")
    prev = json.load(open(op)) if os.path.exists(op) else {}
    status, evs = {}, []
    for name, fn in (("phtour", scrape_phtour), ("kfes", scrape_kfes)):
        try: r = fn(); status[name] = {"ok": True, "count": len(r)}
        except Exception as e: r = []; status[name] = {"ok": False, "error": str(e)[:200]}
        if not r:  # 실패/0건 → 이전 항목 유지(아직 안 끝난 것만)
            r = [x for x in prev.get("events", []) if x.get("origin") == name and x["end"] >= TODAY]
            if r: status[name]["kept_previous"] = len(r)
        for x in r: x.setdefault("origin", name)
        evs += r
    # 중복 제거: 같은 시작일 + 제목 유사 → 시청 항목 우선, kfes의 설명/링크로 보강
    merged = []
    for x in sorted(evs, key=lambda x: x["origin"] != "phtour"):
        dup = next((m for m in merged if m["start"] == x["start"] and (norm(m["title"]) in norm(x["title"]) or norm(x["title"]) in norm(m["title"]))), None)
        if dup:
            for k in ("desc", "link", "img_src"):
                if (not dup.get(k) or dup.get(k) == NA) and x.get(k): dup[k] = x[k]
            dup.setdefault("also", []).append({"src": x["src"], "srcu": x["srcu"]})
        else: merged.append(x)
    for x in merged:
        x["area"] = area_of(x.get("venue"), x.get("title"), x.get("org"))
        x["status"] = "진행중" if x["start"] <= TODAY <= x["end"] else "예정"
        if x.get("img_src") and not x.get("img"): x["img"] = save_img(x["img_src"])
    merged.sort(key=lambda x: (x["status"] != "진행중", x["start"], x["end"]))
    apply_lineups(merged)
    try: news = scrape_news(); status["news"] = {"ok": True, "count": len(news)}
    except Exception as e: news = prev.get("news", []); status["news"] = {"ok": False, "error": str(e)[:200]}
    used = {x.get("img") for x in merged}
    for f in [f for f in os.listdir(os.path.join(HERE, "ev")) if not f.startswith(".")]:
        if f"ev/{f}" not in used: os.remove(os.path.join(HERE, "ev", f))
    res = {"updated": NOW.strftime("%Y-%m-%d %H:%M KST"), "today": TODAY, "status": status,
           "sources": {"phtour": PH + "/phtour/module/calendarManage/index.do?menu_idx=25",
                       "kfes": "https://korean.visitkorea.or.kr/kfes/list/wntyFstvlList.do", "news": "Google 뉴스 '포항 축제'"},
           "events": merged, "news": news}
    json.dump(res, open(op, "w"), ensure_ascii=False, indent=1)
    print(f"events {len(merged)} (진행중 {sum(x['status']=='진행중' for x in merged)}) ", {a: sum(x['area'] == a for x in merged) for a in ("nam", "buk", "ocheon", "all")})
    for x in merged[:60]: print(" ", x["status"], x["start"], x["end"], x["area"], x["type"], x["title"][:40], "|", x["venue"][:30], "| img", bool(x.get("img")), "| desc", len(x.get("desc") or ""))

if __name__ == "__main__":
    main()
