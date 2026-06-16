# -*- coding: utf-8 -*-
# Fetch one realestate.com.au listing detail via RapidAPI "Realty in AU".
# usage: python perth_detail.py <listingId> [--imgs]
import os, re, sys, json
sys.stdout.reconfigure(encoding="utf-8")
from curl_cffi import requests          # 이미지 다운로드(reastatic CDN, 키 불필요)용
sys.path.insert(0, r"D:\my\cowork\tools")
import ra_client                        # 키 자동 폴백

PFX = "https://i2.au.reastatic.net/1000x750-format=jpeg"
LID = sys.argv[1]
DL = "--imgs" in sys.argv

def _detail_ok(jj):
    rs = jj.get("results")
    dd = rs[0] if isinstance(rs, list) and rs else (rs or jj)
    return bool(dd.get("propertyType") or dd.get("address"))   # degraded/에러 응답엔 없음
j, _km, _rem = ra_client.ra_get("/properties/detail", {"id": LID}, validate=_detail_ok)
rs = j.get("results")
d = rs[0] if isinstance(rs, list) and rs else (rs or j)
open(r"D:\my\cowork\tools\detail_%s.json" % LID, "w", encoding="utf-8").write(
    json.dumps(d, ensure_ascii=False, indent=2))

g = (d.get("features", {}) or {}).get("general", {}) or {}
ad = d.get("address", {}) or {}
print("==== ID", LID, "| status", (d.get("status") or {}).get("label"), "====")
print("ADDR:", ad.get("streetAddress"), "|", ad.get("suburb"), ad.get("postcode"), ad.get("state"))
print("LL:", ad.get("location"))
print("PRICE:", (d.get("price") or {}).get("display"), "| TYPE:", d.get("propertyType"))
print("BBP: %s bd / %s ba / %s car" % (g.get("bedrooms"), g.get("bathrooms"), g.get("parkingSpaces")))
print("BOND:", (d.get("bond") or {}).get("display"), "| AVAIL:", (d.get("dateAvailable") or {}).get("dateDisplay"))
print("TITLE:", d.get("title"))
print("PFEAT:", json.dumps(d.get("propertyFeatures"), ensure_ascii=False))
print("DESC:", re.sub("<[^>]+>", "\n - ", d.get("description") or ""))
imgs = d.get("images", [])
print("IMGS:", len(imgs))
if DL:
    OUT = r"D:\my\cowork\tools\imgs_detail"; os.makedirs(OUT, exist_ok=True)
    n = 0
    for i, im in enumerate(imgs, 1):
        u = im.get("uri")
        if not u:
            continue
        fp = os.path.join(OUT, "%s_%02d.jpg" % (LID, i))
        if os.path.exists(fp) and os.path.getsize(fp) > 12000:
            n += 1; continue
        try:
            rr = requests.get(PFX + u, timeout=30)
            if rr.status_code == 200 and len(rr.content) > 10000:
                open(fp, "wb").write(rr.content); n += 1
        except Exception as e:
            print("imgerr", i, e)
    print("downloaded", n, "->", OUT)
