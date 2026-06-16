# -*- coding: utf-8 -*-
# Perth rental LIST search via RapidAPI "Realty in AU" — rich filters, flag annotation.
# Pairs with perth_detail.py (single-listing detail+photos). Fast 1st-pass filter so
# Claude only eyeballs the shortlist, then runs perth_detail.py <id> --imgs on picks.
#
# usage examples:
#   python perth_search.py cat   --min 500 --max 700 --beds 2
#   python perth_search.py inner --max 700 --beds 2,3 --floor nocarpet
#   python perth_search.py "Mount Lawley, WA 6050" --max 700 --type villa,townhouse,unit
#   python perth_search.py cat   --max 700 --no-red          # hide hard red-flag listings
#
# groups: cat (free-CAT core) | inner (bike/ferry ring) | river | first3 | all
# floor:  BARE = hard/non-carpet (barefoot ok, GOOD) | mix = living hard + beds carpet | CARP = carpet | ? = ad didn't say
# flags:  RED = auto-out (communal laundry / serviced-short-stay / granny-rear)
#         YEL = soft (furnished / carpet / fifo-ish)  -> not filtered unless asked
import os, re, sys, json, argparse
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\my\cowork\tools")
import ra_client   # 키 자동 폴백 + degradation 감지

GROUPS = {
    "cat":   ["East Perth, WA 6004", "Perth, WA 6000", "West Perth, WA 6005",
              "Northbridge, WA 6003", "Highgate, WA 6003", "Leederville, WA 6007"],
    "inner": ["North Perth, WA 6006", "Mount Lawley, WA 6050", "West Leederville, WA 6007",
              "Subiaco, WA 6008", "Mount Hawthorn, WA 6016", "South Perth, WA 6151",
              "Victoria Park, WA 6100", "Como, WA 6152", "Kensington, WA 6151", "Maylands, WA 6051"],
    "river": ["South Perth, WA 6151", "Como, WA 6152", "Kensington, WA 6151"],
    "first3":["Wembley, WA 6014", "Rivervale, WA 6103", "Shenton Park, WA 6008"],
    # original perth_rentals.html gallery footprint (re-filter target)
    "gallery":["East Perth, WA 6004", "Victoria Park, WA 6100", "Maylands, WA 6051",
               "Rivervale, WA 6103", "Mount Lawley, WA 6050"],
}
GROUPS["all"] = sorted(set(GROUPS["cat"] + GROUPS["inner"]))

def num(s):
    m = re.search(r"(\d[\d,]*)", s or "")
    return int(m.group(1).replace(",", "")) if m else None

HARD   = re.compile(r"floor\s*board|timber floor|wood(en)? floor|laminate|vinyl|hybrid floor|bamboo|tiled through|polished concrete|floorboards", re.I)
CARPET = re.compile(r"carpet", re.I)
RENO   = re.compile(r"renovat|refurbish|brand new|modern|stylish|updated|newly|revamp|fully renovated", re.I)
RED = [("communal", re.compile(r"communal laundry|shared laundry|common laundry|laundry facilit", re.I)),
       ("serviced", re.compile(r"serviced apartment|short[ -]?stay|fully serviced|nightly rate", re.I)),
       ("granny",   re.compile(r"granny flat|ancillary dwelling", re.I)),
       ("over55",   re.compile(r"over[\s-]?5[05]\b|\b5[05]\s*\+|over 50s|aged 5[05]|5[05]\s*years|5[05] and over|retirement village|lifestyle village|seniors? (only|village|living)", re.I))]
YEL = [("furnished", re.compile(r"(?<!un)furnished", re.I)),
       ("fifo",      re.compile(r"\bfifo\b|lock and leave|lock & leave|mining roster", re.I))]

def analyze(x):
    blob = (x.get("description") or "") + " " + json.dumps(x.get("propertyFeatures") or "")
    addr = ((x.get("address", {}) or {}).get("streetAddress", "") or "")
    hard, carp = bool(HARD.search(blob)), bool(CARPET.search(blob))
    floor = "BARE" if hard and not carp else "mix" if hard and carp else "CARP" if carp else "?"
    reds = [n for n, p in RED if p.search(blob)]
    if addr.upper().startswith("REAR"): reds.append("rear")
    yels = [n for n, p in YEL if p.search(blob)]
    if carp: yels.append("carpet")
    return floor, reds, yels, bool(RENO.search(blob))

ap = argparse.ArgumentParser()
ap.add_argument("target", nargs="?", default="cat", help="group or 'Suburb, WA 60xx'")
ap.add_argument("--min", type=int, default=0)
ap.add_argument("--max", type=int, default=700)
ap.add_argument("--beds", default="2", help="exact comma list e.g. 2 or 2,3 or any")
ap.add_argument("--baths-min", type=int, default=0)
ap.add_argument("--car-min", type=int, default=0)
ap.add_argument("--type", default="", help="comma filter: unit,apartment,house,villa,townhouse")
ap.add_argument("--floor", default="any", choices=["any", "bare", "nocarpet"],
                help="bare=hard/non-carpet floor only; nocarpet=exclude carpet")
ap.add_argument("--reno", action="store_true")
ap.add_argument("--no-red", action="store_true", help="drop hard red-flag listings")
ap.add_argument("--surrounding", action="store_true")
ap.add_argument("--sort", default="price-asc")
ap.add_argument("--emit", default="", help="검색결과를 manifest JSON으로 저장(이후 perth_commute/perth_pdf 입력)")
args = ap.parse_args()

beds_set = None if args.beds.lower() == "any" else set(int(b) for b in args.beds.split(","))
types = set(t.strip().lower() for t in args.type.split(",") if t.strip())
subs = GROUPS.get(args.target, [args.target if "," in args.target else args.target + ", WA"])

print("SEARCH %s | $%s-%s | beds=%s baths>=%s car>=%s type=%s floor=%s%s%s | %d subs" % (
    args.target, args.min, args.max, args.beds, args.baths_min, args.car_min,
    args.type or "any", args.floor, " reno" if args.reno else "", " no-red" if args.no_red else "", len(subs)))
rows = []
for sub in subs:
    params = {"channel": "rent", "searchLocation": sub,
              "surroundingSuburbs": "true" if args.surrounding else "false",
              "pageSize": "50", "page": "1", "sortType": args.sort}
    sm = re.search(r",\s*([A-Za-z]{2,3})\b", sub)        # 기대 주(state) — degradation(전국 디폴트) 감지용
    exp_state = (sm.group(1).upper() if sm else "WA")
    def _ok(jj, _exp=exp_state):
        rr = []
        for t in jj.get("tieredResults", []): rr += t.get("results", [])
        if not rr: return True                            # 빈 결과는 정상(매물 없음)일 수 있음
        return any((x.get("address", {}) or {}).get("state") == _exp for x in rr)
    try:
        j, _km, _rem = ra_client.ra_get("/properties/list", params, validate=_ok)
    except Exception as e:
        print("ERR", sub, e); continue
    res = []
    for t in j.get("tieredResults", []):
        res += t.get("results", [])
    for x in res:
        g = (x.get("features", {}) or {}).get("general", {}) or {}
        bd = g.get("bedrooms"); ba = g.get("bathrooms") or 0; car = g.get("parkingSpaces") or 0
        pn = num((x.get("price", {}) or {}).get("display")); pt = (x.get("propertyType") or "").lower()
        if pn is None or pn < args.min or pn > args.max: continue
        if beds_set and bd not in beds_set: continue
        if ba < args.baths_min or car < args.car_min: continue
        if types and pt not in types: continue
        floor, reds, yels, reno = analyze(x)
        if args.floor == "bare" and floor != "BARE": continue
        if args.floor == "nocarpet" and floor == "CARP": continue
        if args.reno and not reno: continue
        if args.no_red and reds: continue
        ad = x.get("address", {}) or {}
        rows.append({"pn": pn, "bd": bd, "ba": ba, "car": car, "type": pt, "sub": ad.get("suburb") or "",
                     "addr": ad.get("streetAddress") or "", "floor": floor,
                     "flag": ("RED:" + ",".join(reds) if reds else "") + (" YEL:" + ",".join(yels) if yels else ""),
                     "reno": "reno" if reno else "", "lid": (x.get("prettyUrl") or "x-0").split("-")[-1]})

seen = set(); uniq = []
for r in sorted(rows, key=lambda x: x["pn"]):
    if r["lid"] in seen: continue
    seen.add(r["lid"]); uniq.append(r)

print("\n%-4s %-7s %-9s %-12s %-25s %-6s %-5s %-26s %s" %
      ("$", "bd/ba/c", "type", "suburb", "address", "floor", "reno", "flags", "id"))
for r in uniq:
    print("%-4s %s/%s/%s   %-9s %-12s %-25s %-6s %-5s %-26s %s" % (
        r["pn"], r["bd"], r["ba"], r["car"], r["type"][:9], r["sub"][:12], r["addr"][:25],
        r["floor"], r["reno"], r["flag"][:26], r["lid"]))
reds = sum(1 for r in uniq if r["flag"].startswith("RED"))
print("\nfloor: BARE=hard/non-carpet(barefoot ok) | mix=living hard+beds carpet | CARP=carpet | ?=not stated->check photos")
print("%d listings (%d RED-flag=auto-out). picks => python perth_detail.py <id> --imgs" % (len(uniq), reds))

if args.emit:
    # full_manifest 스키마: id/region/price/type/bd/floor/flag/commute(빈 → perth_commute가 채움)
    man = [{"id": r["lid"], "region": r["sub"], "price": str(r["pn"]), "type": r["type"],
            "bd": str(r["bd"]), "floor": (r["floor"] or "?").upper(), "flag": r["flag"], "commute": ""}
           for r in uniq]
    json.dump(man, open(args.emit, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\nemitted %d listings -> %s  (다음: python perth_commute.py %s)" % (len(man), args.emit, args.emit))
