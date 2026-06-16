# -*- coding: utf-8 -*-
# perth_download.py — manifest의 매물들 detail+사진을 **병렬** 다운로드 (2026-06-16).
# 기존 PowerShell foreach(순차) + perth_detail(사진 1장씩) = 직렬 병목을 제거.
#   - 매물 단위: ThreadPoolExecutor(--workers, 기본 6)
#   - 사진 단위: 매물 안에서 다시 ThreadPoolExecutor(8) — reastatic CDN(키 불필요)라 안전
#   - detail API는 ra_client(키 폴백) 경유, --cap로 사진 장수 제한(판정엔 ~12장이면 충분)
#   - detail_{id}.json 캐스케이드: 로컬 캐시 → RapidAPI
#     (Drive 아카이브 층 폐기 — perth_lookbook sync-pull에서 git이 detail 동기화를 처리)
#   - --refresh: 로컬 캐시 무시하고 전건 강제 재호출
#   - --no-drive: deprecated(무시됨), 하위호환용으로만 유지
# usage: python perth_download.py <manifest.json> [--workers 6] [--cap 14] [--refresh]
import sys, os, json, argparse, concurrent.futures as cf
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
# 머신독립: __file__ 기준으로 TOOLS 경로 결정 (perth_lookbook.py와 일관)
TOOLS = str(Path(__file__).parent.resolve())
sys.path.insert(0, TOOLS)
import ra_client
from curl_cffi import requests

OUT = os.path.join(TOOLS, "imgs_detail")
PFX = "https://i2.au.reastatic.net/1000x750-format=jpeg"
os.makedirs(OUT, exist_ok=True)

def _detail_ok(jj):
    rs = jj.get("results"); dd = rs[0] if isinstance(rs, list) and rs else (rs or jj)
    return bool(dd.get("propertyType") or dd.get("address"))

def _load_cached_detail(lid):
    """detail_{id}.json 로컬 캐시가 유효하면 dict 반환, 아니면 None."""
    fp = os.path.join(TOOLS, "detail_%s.json" % lid)
    if not os.path.exists(fp):
        return None
    try:
        d = json.load(open(fp, encoding="utf-8"))
        # _detail_ok 와 동일한 유효성 기준: propertyType 또는 address 보유
        if d.get("propertyType") or d.get("address"):
            return d
    except Exception:
        pass
    return None

def _grab(lid, i, im):
    u = im.get("uri")
    if not u:
        return 0
    fp = os.path.join(OUT, "%s_%02d.jpg" % (lid, i))
    if os.path.exists(fp) and os.path.getsize(fp) > 12000:
        return 1
    try:
        rr = requests.get(PFX + u, timeout=30)
        if rr.status_code == 200 and len(rr.content) > 10000:
            with open(fp, "wb") as f:
                f.write(rr.content)
            return 1
    except Exception:
        pass
    return 0

def fetch_listing(lid, cap, refresh=False):
    """
    캐스케이드: 로컬 캐시 → RapidAPI
    (Drive 아카이브 층 폐기 — perth_lookbook sync-pull에서 git이 detail 동기화를 처리)
    반환: (lid, imgs_saved, label, source)
      source: "L"=로컬재사용, "A"=RapidAPI신규
    """
    # ① 로컬 캐시
    if not refresh:
        cached = _load_cached_detail(lid)
        if cached is not None:
            d = cached
            source = "L"
        else:
            d = None
    else:
        d = None

    # ② RapidAPI (로컬 miss이거나 --refresh)
    if d is None:
        try:
            j, _, _ = ra_client.ra_get("/properties/detail", {"id": lid}, validate=_detail_ok, verbose=False)
        except Exception as e:
            return (lid, -1, "ERR:%s" % str(e)[:40], "A")
        rs = j.get("results"); d = rs[0] if isinstance(rs, list) and rs else (rs or j)
        with open(os.path.join(TOOLS, "detail_%s.json" % lid), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        source = "A"

    imgs = d.get("images", []) or []
    if cap:
        imgs = imgs[:cap]
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        n = sum(ex.map(lambda t: _grab(lid, t[0], t[1]), enumerate(imgs, 1)))
    return (lid, n, d.get("propertyType"), source)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cap", type=int, default=14, help="매물당 사진 장수 상한(0=전체)")
    ap.add_argument("--refresh", action="store_true",
                    help="로컬 캐시 무시하고 detail 전건 강제 재호출(가격·매물상태 갱신용)")
    # deprecated: Drive 아카이브 층 폐기됨. 하위호환용으로만 수용, 동작에 영향 없음.
    ap.add_argument("--no-drive", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    man = json.load(open(a.manifest, encoding="utf-8"))
    ids = [m["id"] for m in man]

    cache_mode = "강제재호출(--refresh)" if a.refresh else "캐시재사용"
    print("병렬 다운로드: %d 매물 × (detail + 사진≤%s), workers=%d, detail=%s"
          % (len(ids), a.cap or "all", a.workers, cache_mode))
    print("  [detail] 캐스케이드: 로컬 캐시 → RapidAPI (Drive 층 폐기, git sync로 대체)")

    done = 0; n_local = 0; n_api = 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_listing, lid, a.cap, a.refresh): lid for lid in ids}
        for f in cf.as_completed(futs):
            lid, n, t, source = f.result(); done += 1
            if source == "L":
                n_local += 1
            else:
                n_api += 1
            tag = "(local)" if source == "L" else "(api)"
            print("  [%2d/%d] %s imgs=%s %s %s" % (done, len(ids), lid, n, t, tag))

    print("완료: %d 매물 — detail: 로컬재사용 %d / RapidAPI신규 %d"
          % (len(ids), n_local, n_api))

if __name__ == "__main__":
    main()
