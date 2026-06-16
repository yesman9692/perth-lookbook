# -*- coding: utf-8 -*-
# perth_market.py — suburb별 침실수별 '현재 호가(asking) median'을 우리 소스(RapidAPI Realty in AU)로 직접 계산.
# Domain/REIWA per-bed median은 봇차단(403)·베드수혼합이라, 같은 파이프라인 검색결과의 median이 가장 정직한 시세 앵커.
# = ACHIEVED(체결)가 아닌 ASKING(호가) snapshot, 단일 포털 기준 — analysis에 그렇게 라벨.
# 출력: 콘솔 표 + tools/market.json  ({suburb:{bed2:{n,med,lo,hi}, bed3:{...}}})
import os, re, sys, json, statistics as st
sys.stdout.reconfigure(encoding="utf-8")
TOOLS = r"D:\my\cowork\tools"
sys.path.insert(0, TOOLS)
import ra_client   # 키 자동 폴백
def num(s):
    m = re.search(r"(\d[\d,]*)", s or "")
    return int(m.group(1).replace(",", "")) if m else None
SUBS = ["Maylands, WA 6051", "Victoria Park, WA 6100", "South Perth, WA 6151",
        "Como, WA 6152", "Mount Lawley, WA 6050", "West Leederville, WA 6007",
        "Subiaco, WA 6008", "North Perth, WA 6006"]
BEDS = [2, 3]

def fetch(sub):
    p = {"channel": "rent", "searchLocation": sub, "surroundingSuburbs": "false",
         "pageSize": "50", "page": "1", "sortType": "price-asc"}
    sm = re.search(r",\s*([A-Za-z]{2,3})\b", sub); exp = (sm.group(1).upper() if sm else "WA")
    def _ok(jj, _exp=exp):
        rr = []
        for t in jj.get("tieredResults", []): rr += t.get("results", [])
        return (not rr) or any((x.get("address", {}) or {}).get("state") == _exp for x in rr)
    j, _km, _rem = ra_client.ra_get("/properties/list", p, validate=_ok)
    res = []
    for t in j.get("tieredResults", []):
        res += t.get("results", [])
    return res

out = {}
print("%-18s %-22s %-22s" % ("suburb", "2bd asking median", "3bd asking median"))
for sub in SUBS:
    name = sub.split(",")[0]
    try:
        res = fetch(sub)
    except Exception as e:
        print(name, "ERR", e); continue
    rec = {}
    cells = []
    for bd in BEDS:
        ps = []
        for x in res:
            g = (x.get("features", {}) or {}).get("general", {}) or {}
            if g.get("bedrooms") != bd:
                continue
            pn = num((x.get("price", {}) or {}).get("display"))
            if pn and 200 <= pn <= 1500:        # 주당 렌트 정상범위 (이상치 컷)
                ps.append(pn)
        if ps:
            ps.sort()
            rec["bed%d" % bd] = {"n": len(ps), "med": int(st.median(ps)), "lo": ps[0], "hi": ps[-1]}
            cells.append("$%d (n=%d, %d-%d)" % (int(st.median(ps)), len(ps), ps[0], ps[-1]))
        else:
            cells.append("-")
    out[name] = rec
    print("%-18s %-22s %-22s" % (name, cells[0], cells[1]))

json.dump(out, open(os.path.join(TOOLS, "market.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nwrote tools/market.json  (asking-rent median, 우리 RapidAPI 소스 기준 현재 snapshot)")
