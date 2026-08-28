# -*- coding: utf-8 -*-
# perth_commute.py — fill manifest 'commute' via Google Maps Directions API.
# transit: alternatives=true 로 후보경로 다 받아 comfort_cost(도보 가중)로 best 선택.
#   comfort_cost = 탑승·대기분 + 도보분 * WALK_PENALTY  (도보 1분 = 탑승 WALK_PENALTY분 체감)
#   시간최단 경로가 best와 다르면 "⚡최단" 으로 병기. 도보 총거리(m) 항상 표기.
#   departure_time = 다음 평일 08:00 AWST (통학 시나리오 고정 — 실행 요일/시각 의존 제거).
# + bicycling. Reads detail_{id}.json for coords. usage:
#   python perth_commute.py lookbook_manifest.json   (manifest 전체 갱신)
#   python perth_commute.py 441562152                (단일 listingId, 출력만)
import sys, os, json
from datetime import datetime, timedelta, timezone
sys.stdout.reconfigure(encoding="utf-8")
from curl_cffi import requests

TOOLS = r"D:\my\cowork\tools"
KEY = open(os.path.join(TOOLS, "gmaps_key.txt"), encoding="utf-8").read().strip()
B = "https://maps.googleapis.com/maps/api/directions/json"
# Places API (New) Nearby Search — 필드마스크로 Basic(id·location·types·name)만 요청 →
# "Nearby Search Pro" SKU(월 5,000콜 무료). 레거시 nearbysearch 는 Atmosphere/Contact
# 데이터를 강제 번들해 과금(2026-06 실결제 ₩21,656)됐어서 폐기. 상세: 메모리 project_perth_maps_api_cost.
PLACES_NEW = "https://places.googleapis.com/v1/places:searchNearby"
CACHE_FILE = os.path.join(TOOLS, "places_cache.json")   # amenity/grocery listingId별 캐시(재실행 무과금)
USAGE_FILE = os.path.join(TOOLS, "_deploy", "data", "places_usage.json")   # New API 월 호출 카운터(git 동기화 대상)
MONTHLY_LIMIT = 4500    # Pro 무료 5,000 아래 안전마진. 도달 시 호출 skip→폴백, 월 바뀌면 자동 리셋
FALLBACK_AMENITY = "🏪 amenity:D(클러스터0·최근접9999m)"   # New API 미활성/오류 시. 이 값은 캐싱 안 함.
DEST = "500 Wellington Street, Perth WA 6000"   # ECU City Campus
WALK_PENALTY = 2.0   # 도보 1분 체감 = 탑승 2분. ↑ 도보 더 회피 / ↓ 시간 우선

AWST = timezone(timedelta(hours=8))
def _next_weekday_8am():
    now = datetime.now(AWST)
    d = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if d <= now:
        d += timedelta(days=1)
    while d.weekday() >= 5:        # 토(5)/일(6) 건너뜀 → 평일 통학
        d += timedelta(days=1)
    return int(d.timestamp())
DEP = _next_weekday_8am()

def _routes(origin, mode, alt):
    p = {"origin": origin, "destination": DEST, "mode": mode, "key": KEY}
    if alt:
        p["alternatives"] = "true"
        p["departure_time"] = str(DEP)
    try:
        r = requests.get(B, params=p, timeout=30).json()
    except Exception as e:
        print("  !! dir error", e); return []
    return r.get("routes", []) if r.get("status") == "OK" else []

def _parse(route):
    leg = route["legs"][0]
    total = leg["duration"]["value"] / 60.0
    walk_s = walk_m = 0.0; segs = []; ntransit = 0
    for s in leg["steps"]:
        if s["travel_mode"] == "WALKING":
            walk_s += s["duration"]["value"]; walk_m += s["distance"]["value"]
            segs.append("도보 %s" % s["distance"]["text"])
        else:
            td = s.get("transit_details", {}) or {}
            ln = td.get("line", {}) or {}
            dep = (td.get("departure_stop", {}) or {}).get("name", "정류장")
            segs.append("%s[%s] %s정거장/%s" % (
                dep, ln.get("short_name") or ln.get("name") or "?",
                td.get("num_stops"), s["duration"]["text"]))
            ntransit += 1
    walk_min = walk_s / 60.0
    cost = (total - walk_min) + walk_min * WALK_PENALTY
    xfer = "·환승%d회" % (ntransit - 1) if ntransit > 1 else "·무환승"
    return {"total": total, "walk_min": walk_min, "walk_m": walk_m, "cost": cost,
            "desc": " → ".join(segs) + " " + xfer}

def commute(lat, lng):
    if lat is None:
        return "(좌표 없음)"
    o = "%s,%s" % (lat, lng)
    out = []
    routes = _routes(o, "transit", True)
    if routes:
        P = [_parse(r) for r in routes]
        best = min(P, key=lambda x: x["cost"])
        fast = min(P, key=lambda x: x["total"])
        out.append("🚆 %d분(도보 %dm): %s" % (round(best["total"]), round(best["walk_m"]), best["desc"]))
        if round(fast["total"]) < round(best["total"]):   # 더 빠른 대안이 도보 부담 때문에 밀린 경우 병기
            out.append("⚡최단 %d분(도보 %dm)" % (round(fast["total"]), round(fast["walk_m"])))
    bike = _routes(o, "bicycling", False)
    if bike:
        bl = bike[0]["legs"][0]
        out.append("🚲 자전거 %s(%s)" % (bl["duration"]["text"], bl["distance"]["text"]))
    return " · ".join(out) if out else "(통근 조회 실패)"

_cap_warned = [False]

def _usage_ok():
    """이번 달 New API 호출 수 확인. MONTHLY_LIMIT 미만이면 +1 후 True, 도달하면 False(호출 skip).
    월이 바뀌면 카운트 자동 리셋. 파일 오류 시 fail-open(호출 허용) — 콘솔 일 1,000이 비용 백스톱."""
    try:
        month = datetime.now(AWST).strftime("%Y-%m")
        try:
            u = json.load(open(USAGE_FILE, encoding="utf-8"))
        except Exception:
            u = {}
        if u.get("month") != month:
            u = {"month": month, "count": 0}
        if u["count"] >= MONTHLY_LIMIT:
            if not _cap_warned[0]:
                print("  !! Places New 월 한도 %d 도달 — 이후 amenity/grocery 폴백(D/빈값). 다음달 자동 리셋." % MONTHLY_LIMIT)
                _cap_warned[0] = True
            return False
        u["count"] += 1
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        json.dump(u, open(USAGE_FILE, "w", encoding="utf-8"))
        return True
    except Exception:
        return True

def _places_new(location, included_types, rank_distance=False, radius=600, max_results=20):
    """Places API (New) Nearby Search. Basic 필드마스크만 요청 → Nearby Search Pro SKU(월 5,000 무료).
    반환: 레거시 호환 dict 리스트 [{place_id, name, geometry.location.lat/lng, types}].
    New API 권한거부(미활성)/월한도 도달이면 None (amenity FALLBACK 트리거용), 그 외 실패/빈결과면 []."""
    if not _usage_ok():                  # 월 4,500 하드스톱 — 무료티어 초과 방지
        return None
    try:
        lat_s, lng_s = str(location).split(",")
        lat, lng = float(lat_s), float(lng_s)
    except Exception:
        return []
    body = {
        "includedTypes": included_types,
        "maxResultCount": max_results,
        "locationRestriction": {"circle": {
            "center": {"latitude": lat, "longitude": lng}, "radius": float(radius)}},
    }
    if rank_distance:
        body["rankPreference"] = "DISTANCE"
    try:
        r = requests.post(PLACES_NEW, headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": KEY,
            "X-Goog-FieldMask": "places.id,places.location,places.types,places.displayName",
        }, json=body, timeout=15)
    except Exception:
        return []
    if r.status_code in (401, 403):      # New API 미활성/키 제한 → None(FALLBACK)
        return None
    try:
        j = r.json()
    except Exception:
        return []
    if r.status_code != 200 or "error" in j:
        return []
    out = []
    for p in j.get("places", []):
        loc = p.get("location", {}) or {}
        out.append({
            "place_id": p.get("id"),
            "name": (p.get("displayName", {}) or {}).get("text", "마트"),
            "geometry": {"location": {"lat": loc.get("latitude"), "lng": loc.get("longitude")}},
            "types": p.get("types", []),
        })
    return out

def nearest_grocery(lat, lng):
    """Returns '🛒 도보 Xm Y분 (Name)' or '🛒 🚌 Y분 (Name, 현지도보 Xm)'.
    Walk if ≤15min; otherwise tries transit and shows whichever is better.
    Returns '' if Places API (New) not enabled."""
    results = _places_new("%s,%s" % (lat, lng), ["supermarket"],
                          rank_distance=True, radius=20000, max_results=1)
    if results is None:      # New API 미활성 or 월 한도 도달 → graceful 폴백(빈값). 진단은 amenity=D + 콘솔 경고로.
        return ""
    if not results:
        return ""
    place = results[0]
    name = place.get("name", "마트")
    dlat = place["geometry"]["location"]["lat"]
    dlng = place["geometry"]["location"]["lng"]
    origin = "%s,%s" % (lat, lng)
    dest   = "%s,%s" % (dlat, dlng)

    def _dir(mode):
        try:
            res = requests.get(B, params={"origin": origin, "destination": dest,
                                          "mode": mode, "key": KEY,
                                          "departure_time": str(DEP)}, timeout=15).json()
        except Exception:
            return None
        if res.get("status") != "OK" or not res.get("routes"):
            return None
        return res["routes"][0]["legs"][0]

    # 1차: 도보
    wleg = _dir("walking")
    if not wleg:
        return ""
    walk_m    = wleg["distance"]["value"]
    walk_mins = round(wleg["duration"]["value"] / 60)

    if walk_mins <= 15:
        return "🛒 도보 %dm %d분 (%s)" % (walk_m, walk_mins, name)

    # 도보 15분 초과 → 대중교통 시도
    tleg = _dir("transit")
    if tleg:
        t_mins = round(tleg["duration"]["value"] / 60)
        # 마지막 도보 구간(현지 도보) 추출 — 짐 들고 걷는 거리
        last_walk_m = 0
        for step in reversed(tleg.get("steps", [])):
            if step["travel_mode"] == "WALKING":
                last_walk_m = step["distance"]["value"]
                break
        if t_mins < walk_mins - 3:   # 대중교통이 의미있게 빠를 때만
            return "🛒 🚌 %d분 (%s, 현지도보 %dm)" % (t_mins, name, last_walk_m)

    # 대중교통도 별 이점 없으면 도보 그대로
    return "🛒 도보 %dm %d분 (%s)" % (walk_m, walk_mins, name)

def amenity_profile(lat, lng):
    """Returns '🏪 amenity:<TIER>(클러스터<N>·최근접<M>m)' — perth_score 파싱용 계약 문자열.
    Tier: A=supermarket 600m내 + 음식/카페 등 unique >=10  B=supermarket 600m내
          C=supermarket 없고 convenience_store 있음  D=600m내 없음. (Places Nearby 600m)"""
    FALLBACK = FALLBACK_AMENITY
    location = "%s,%s" % (lat, lng)

    def _nearby(place_type):
        # None(권한거부) 그대로 전파 → supermarkets is None 가드가 FALLBACK 처리.
        return _places_new(location, [place_type], radius=600, max_results=20)

    supermarkets = _nearby("supermarket")
    if supermarkets is None:
        return FALLBACK
    convenience = _nearby("convenience_store") or []
    food_results = []
    for t in ["cafe", "restaurant", "pharmacy", "bakery"]:
        results = _nearby(t)
        if results:
            food_results.extend(results)

    def _dedup(pois):
        seen = set(); out = []
        for p in pois:
            pid = p.get("place_id")
            if pid and pid not in seen:
                seen.add(pid); out.append(p)
        return out

    unique_food = _dedup(food_results)
    N = len(_dedup(list(supermarkets) + list(convenience) + unique_food))

    # 최근접 마트 거리 M — radius 결과는 prominence 순이라 [0]이 최근접이 아님.
    # rankby=distance(radius 미사용)로 진짜 최근접 슈퍼마켓(없으면 편의점) 식별 후 도보거리.
    M = 9999
    try:
        near = _places_new(location, ["supermarket"], rank_distance=True,
                           radius=20000, max_results=1) or convenience or supermarkets
        if near:
            n0 = near[0]
            dlat = n0["geometry"]["location"]["lat"]
            dlng = n0["geometry"]["location"]["lng"]
            res = requests.get(B, params={
                "origin": location, "destination": "%s,%s" % (dlat, dlng),
                "mode": "walking", "key": KEY
            }, timeout=15).json()
            if res.get("status") == "OK" and res.get("routes"):
                M = res["routes"][0]["legs"][0]["distance"]["value"]
    except Exception:
        pass

    if len(supermarkets) > 0 and len(unique_food) >= 10:
        tier = "A"
    elif len(supermarkets) > 0:
        tier = "B"
    elif len(convenience) > 0:
        tier = "C"
    else:
        tier = "D"
    return "🏪 amenity:%s(클러스터%d·최근접%dm)" % (tier, N, M)

def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cache(c):
    json.dump(c, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def _coords(lid):
    fp = os.path.join(TOOLS, "detail_%s.json" % lid)
    if not os.path.exists(fp):
        return None, None    # detail 없으면 (None,None) → main의 'lat is None' 가드가 skip 처리
    d = json.load(open(fp, encoding="utf-8"))
    loc = (d.get("address", {}) or {}).get("location", {}) or {}
    return loc.get("latitude"), loc.get("longitude")

def main():
    if len(sys.argv) < 2:
        print("usage: python perth_commute.py <manifest.json | listingId>"); return
    arg = sys.argv[1]
    print("출발기준:", datetime.fromtimestamp(DEP, AWST).strftime("%Y-%m-%d(%a) %H:%M AWST"),
          "| WALK_PENALTY=%s" % WALK_PENALTY)
    if arg.endswith(".json"):
        manifest = json.load(open(arg, encoding="utf-8"))
        refresh = "--refresh" in sys.argv     # 캐시 무시하고 amenity/grocery 강제 재조회
        cache = _load_cache()
        hits = 0
        for e in manifest:
            lat, lng = _coords(e["id"])
            if lat is None:
                print("!! no coords", e["id"]); continue
            c = commute(lat, lng)             # 통근은 항상 라이브(Directions 무료·신선도 중요)
            e["commute"] = c + " (Maps)"
            key = str(e["id"])
            cached = cache.get(key)
            if (not refresh and cached and cached.get("lat") == round(lat, 5)
                    and cached.get("lng") == round(lng, 5)
                    and cached.get("amenity") and "grocery" in cached):
                g, a = cached["grocery"], cached["amenity"]   # 캐시 적중 → Places 호출 skip
                hits += 1
            else:
                g = nearest_grocery(lat, lng)
                a = amenity_profile(lat, lng)
                if a != FALLBACK_AMENITY and not g.startswith("(Places"):   # 오류/미활성 상태는 캐싱 안 함
                    cache[key] = {"lat": round(lat, 5), "lng": round(lng, 5),
                                  "amenity": a, "grocery": g}
            e["grocery"] = g
            e["amenity"] = a
            print("%-14s $%s | %s | %s | %s" % (e.get("region", ""), e.get("price", ""), c, g, a))
        _save_cache(cache)
        json.dump(manifest, open(arg, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\nmanifest commute updated: %d (Places 캐시적중 %d, 재조회 %d)" % (
            len(manifest), hits, len(manifest) - hits))
    else:
        lat, lng = _coords(arg)
        print(commute(lat, lng))

if __name__ == "__main__":
    main()
