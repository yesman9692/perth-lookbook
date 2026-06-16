# -*- coding: utf-8 -*-
# perth_pdf.py v3 — interactive HTML lookbook (data-driven, no hardcoded verdicts)
# v3 changes: ① 판정항목도 parts 있으면 자동항목과 동일 렌더 + 만점 정정 ② ZONE_HARDCAP(A750/B700/C650) 초과 시 제외표로
# usage: python perth_pdf.py <manifest.json> [verdicts.json] [out.html]
#   manifest : id/region/price/type/bd/floor/flag/commute  (perth_search --emit → perth_commute)
#   verdicts : {id:{floor_photo,condition,notes,tags}}  (사진판정 서브에이전트 산출, optional)
#   reads also: detail_{id}.json (주소·좌표·입주일) + imgs_detail/{id}_NN.jpg (상대경로)
#   제외 = commute/flag 규칙 자동 (communal·over55·통근>COMMUTE_CUT·도보>WALK_CUT)
#   writes: interactive HTML (sort 가격/통근/도보 · floor 필터 · 사진 가로스크롤·라이트박스 · 구글맵 링크)
import os, sys, json, re, html as esc
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
DATESTR = datetime.now().strftime("%Y%m%d")

TOOLS   = r"D:\my\cowork\tools"
IMGDIR  = "imgs_detail"          # relative from HTML file location
ECU_LAT, ECU_LNG = -31.9502, 115.8640   # 500 Wellington St, Perth City Campus

# 제외 컷 (사용자 조정 가능) — 2026-06-09: 도보는 1km 하드컷 아님(경계선 1000~1150 포함)
COMMUTE_CUT = 60      # 분 초과 시 제외 (2026-06-15: C존 외곽 도어투도어 60분 정책 반영, 40→60)
WALK_CUT    = 1300    # m 초과 시 제외 (2026-06-15: C존 역세권 도보 포함 위해 1150→1300)

# ── A/B/C 존 분류 + 가격 캡 (2026-06-15) ──
# 예산 주 $700 기준. A=CBD 통근 교통비 $0(상한 700). B=자전거권·우천만 교통비(상한 650).
# C=기차 필수·2인 통근비 차감(상한 600). 하한 = 상한 - 100 (극단 저가 이상치 컷).
# 존 판정: commute 첫 탑승수단이 CAT이면 A(궂은날에도 교통비 0) / 검색을 외곽으로 한 매물(_src=outer)은 C / 나머지(realestate inner)는 B.
ZONE_CAPS     = {'A': (600, 700), 'B': (550, 650), 'C': (500, 600)}   # overbudget 배지 기준 (lo, hi)
ZONE_HARDCAP  = {'A': 750, 'B': 700, 'C': 650}                        # 이 가격 초과 시 카드 제외
ZONE_BADGE = {'A': ('z-a', 'Ⓐ CAT존'), 'B': ('z-b', 'Ⓑ 자전거존'), 'C': ('z-c', 'Ⓒ 기차외곽')}
def classify_zone(commute, src):
    first = re.search(r'\[([^\]]+)\]', commute or "")   # 첫 탑승수단 라벨
    if first and 'CAT' in first.group(1):
        return 'A'
    if src == 'outer':
        return 'C'
    return 'B'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_commute(s):
    """Extract (mins, walk_m) from commute string. (999,9999) on failure."""
    m = re.search(r'🚆\s*(\d+)분\(도보\s*(\d+)m\)', s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (999, 9999)

def parse_bike(s):
    m = re.search(r'🚲\s*자전거\s*(\d+)\s*mins?\(([^)]+)\)', s or "")
    return "🚲 %smin(%s)" % (m.group(1), m.group(2)) if m else ""

def exclusion_reason(flag, mins, walk):
    """제외 사유(문자열) 또는 None. manifest의 flag + 통근수치만으로 자동 판정."""
    fl = (flag or "").lower()
    if "communal" in fl:                    return "공용 세탁실"
    if "over55" in fl or "over-55" in fl:   return "over-55 제한 단지"
    if mins > COMMUTE_CUT:                   return "통근 %d분" % mins
    if walk > WALK_CUT:                      return "도보 %dm" % walk
    return None

def gmaps_url_coord(lat, lng):
    return ("https://www.google.com/maps/dir/?api=1&origin=%.6f,%.6f"
            "&destination=%.6f,%.6f&travelmode=transit") % (lat, lng, ECU_LAT, ECU_LNG)

def gmaps_url_addr(addr, region):
    return ("https://www.google.com/maps/dir/?api=1&origin=%s+%s+WA+Australia"
            "&destination=%.6f,%.6f&travelmode=transit") % (
            "+".join(addr.split()), "+".join(region.split()), ECU_LAT, ECU_LNG)

FLOOR_BADGE = {
    "BARE": ('b-bare', '🟢 BARE'),
    "MIX":  ('b-mix',  '🟡 MIX'),
    "CARP": ('b-carp', '🔴 CARP'),
    "?":    ('b-unk',  '❓ ?'),
}
COND_COLOR = {
    "신축급":"#1565c0","모던":"#0288d1","보통":"#607d8b","낡음":"#8d6e63","?":"#9e9e9e"
}
TAG_BADGE = {
    "6개월단기":  ('b-short',  '⚠️ 6개월단기'),
    "5개월단기":  ('b-short',  '⚠️ 5개월단기'),
    "경계선walk": ('b-border', '🔶 경계선 walk'),
    "가구포함":   ('b-furn',   '🛋 가구포함'),
    "사진없음":   ('b-nophoto','📷 사진없음'),
}

def badge(cls, lbl):
    return '<span class="badge %s">%s</span>' % (cls, esc.escape(lbl))

# ---------------------------------------------------------------------------
# Args: manifest(필수) + verdicts.json(opt) + out.html(opt) — 확장자로 판별
# ---------------------------------------------------------------------------
if len(sys.argv) < 2:
    print("usage: python perth_pdf.py <manifest.json> [verdicts.json] [out.html]"); sys.exit(1)
manifest_path = sys.argv[1]
extra = sys.argv[2:]
verdicts_path = next((a for a in extra if a.endswith(".json")), None)
out_path = next((a for a in extra if a.endswith(".html")), os.path.join(TOOLS, "perth_lookbook_%s.html" % DATESTR))
# --no-cap: 가격무제한 탐색 모드 — overbudget 배지/data속성 자체를 안 달고 토글도 무의미(하위호환)
NO_CAP = "--no-cap" in extra

manifest = json.load(open(manifest_path, encoding="utf-8"))
VERDICTS = json.load(open(verdicts_path, encoding="utf-8")) if verdicts_path else {}

# ---------------------------------------------------------------------------
# Build card data
# ---------------------------------------------------------------------------
included = []         # cards for main section
excluded_rows = []    # rows for excluded table

for e in manifest:
    lid = e["id"]
    jp = os.path.join(TOOLS, "detail_%s.json" % lid)
    d = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {}
    g = (d.get("features", {}) or {}).get("general", {}) or {}
    ad = d.get("address", {}) or {}
    loc = (ad.get("location") or {})
    lat, lng = loc.get("latitude"), loc.get("longitude")

    commute_str = e.get("commute", "")
    mins, walk = parse_commute(commute_str)
    bike = parse_bike(commute_str)
    commute_display = re.sub(r'\s*·\s*🚲.*', '', commute_str).replace(" (Maps)", "").strip()
    xfer = "·환승" in commute_str   # ·환승N회 vs ·무환승

    v = VERDICTS.get(lid, {})
    floor = v.get("floor_photo") or e.get("floor", "?")
    condition = v.get("condition", "")
    notes = v.get("notes", "")
    tags = v.get("tags", [])
    rank = v.get("rank", 999)
    score_detail = v.get("score_detail", {})
    score_total = v.get("score_total", 0)
    score_dq = v.get("score_dq", False)

    price_raw = e.get("price", "0")
    price_int = int(re.sub(r'[^\d]', '', str(price_raw)) or 0)
    avail = (d.get("dateAvailable", {}) or {}).get("dateDisplay", "") or "미정"
    ba    = g.get("bathrooms") or 1
    car   = g.get("parkingSpaces") or 0
    bd    = g.get("bedrooms") or e.get("bd", "?")
    ptype = (d.get("propertyType") or e.get("type", "")).lower()
    addr  = ad.get("streetAddress", "") or ""
    region = e.get("region", "")
    rea_url = "https://www.realestate.com.au/" + (d.get("prettyUrl", "") or "")

    # ── 존 분류 + 제외 판정 (규칙 자동) ──
    zone = classify_zone(commute_str, e.get("_src", ""))
    zlo, zhi = ZONE_CAPS[zone]
    reason = exclusion_reason(e.get("flag", ""), mins, walk)

    # 하드캡 제외 — --no-cap이면 무효
    if (not reason) and (not NO_CAP) and (price_int > ZONE_HARDCAP[zone]):
        reason = "존 하드캡 초과 ($%d > %s존 $%d)" % (price_int, zone, ZONE_HARDCAP[zone])

    if reason:
        excluded_rows.append(
            '<tr><td>%s</td><td>$%d</td><td>%s</td><td>%s</td>'
            '<td class="reason">%s</td><td class="note-gray">%s</td></tr>'
            % (zone, price_int, esc.escape(region), esc.escape(addr),
               esc.escape(reason), esc.escape(e.get("flag", ""))))
        continue

    # 예산 초과 판정 — flag/통근 제외 통과 후에만. --no-cap이면 overbudget=False(배지 안 달기)
    overbudget = (not NO_CAP) and (price_int > zhi)

    zc, zl = ZONE_BADGE[zone]
    zone_badge_html = badge(zc, zl)
    # 예산초과 배지: 원래 존캡(hi) 초과분 표시
    over_amt = price_int - zhi
    overbudget_badge_html = (badge('b-overbudget', '💸 예산초과 $%d over' % over_amt)
                             if overbudget else "")
    rank_badge_html = ('<span class="rank-badge">#%d</span>' % rank) if rank != 999 else ""
    _ORDER = ["가격", "통근", "자전거", "편의", "소음", "주차", "동네", "안전", "면적", "인테리어", "카펫", "detached", "감성", "수납"]
    # 만점: score_detail의 max_score 기반이 가장 정확하나, 없을 때 폴백으로 사용
    # v3: 편의5·소음2·주차1·안전2·동네2·감성1·면적5 (perth_score score_detail 키 "편의"와 일치)
    _MAXP = {"가격": 10, "통근": 10, "자전거": 5, "편의": 5, "소음": 2, "주차": 1, "동네": 2, "안전": 2,
             "면적": 5, "인테리어": 5, "카펫": 5, "detached": 5, "감성": 1, "수납": 3}
    # score_detail에 max_score 있으면 그걸 우선 사용, 없으면 _MAXP 폴백
    def _maxp(k):
        sd = score_detail.get(k, {})
        return sd.get("max_score", _MAXP.get(k, "?"))
    # 총점 만점: score_detail의 max_score 합 (없으면 _MAXP 합 = 61)
    _MAXT = sum(_maxp(k) for k in _MAXP if isinstance(_maxp(k), int))
    def _pph(parts):
        return "".join('<div class="pp"><span class="ppl">%s</span><span class="ppv %s">%s%s</span></div>'
            % (esc.escape(str(l)), "pos" if val >= 0 else "neg", "+" if val > 0 else "", val) for l, val in parts)
    _items = ""
    for _k in _ORDER:
        if _k not in score_detail: continue
        sdk = score_detail[_k]; inner = ""
        # parts 있으면 자동항목과 동일 렌더, 없으면 why 폴백
        if sdk.get("parts"): inner += '<div class="bd">%s</div>' % _pph(sdk["parts"])
        if sdk.get("route"): inner += '<div class="route">%s</div>' % esc.escape(sdk["route"])
        if sdk.get("why"):   inner += '<div class="why">%s</div>' % esc.escape(sdk["why"])
        _items += ('<div class="item"><div class="ihead"><b>%s</b><span class="iscore">%s<i>/%s</i></span></div>%s</div>'
                   % (_k, sdk["s"], _maxp(_k), inner))
    _dq = '<span class="sd-dq">❌ 단기계약 탈락</span>' if score_dq else ""
    if score_dq:
        oneliner_html = ('<div class="oneliner dq-line">❌ %s</div>'
                         % esc.escape(v.get("disqualify_reason", "탈락 (단기계약/공용세탁/펫+카펫)")))
    else:
        oneliner_html = ('<div class="oneliner">%s</div>' % esc.escape(v.get("oneliner", ""))) if v.get("oneliner") else ""
    _A = v.get("analysis", "") or ""
    _ci = _A.find("🆚")
    _compare = ('<div class="sectit">■ 비교</div><div class="compare">%s</div>'
                % esc.escape(_A[_ci:].strip()).replace("\n", "<br>")) if _ci >= 0 else ""
    detail_html = ('<details><summary>▼ 상세 보기 (점수 분해 + 비교)</summary><div class="dbody">'
                   '<div class="sectit">■ 점수 상세</div>%s%s</div></details>' % (_items, _compare))
    fc, fl = FLOOR_BADGE.get(floor, FLOOR_BADGE["?"])
    floor_badge_html = badge(fc, fl)
    grocery_str = e.get("grocery", "") or ""
    cond_badge_html  = ('<span class="badge b-cond" style="background:%s20;color:%s">%s</span>'
                        % (COND_COLOR.get(condition, "#9e9e9e"),
                           COND_COLOR.get(condition, "#9e9e9e"),
                           esc.escape(condition))) if condition else ""
    tag_badges_html  = "".join(badge(*TAG_BADGE[t]) for t in tags if t in TAG_BADGE)

    walk_cls = "walk-warn" if walk >= 1000 else ""
    xfer_html = ' <span class="xfer">환승</span>' if xfer else ""
    _gmap = gmaps_url_coord(lat, lng) if (lat and lng) else gmaps_url_addr(addr, region)
    gmaps_html = '<a class="maps-link" href="%s" target="_blank">🗺 구글맵 길찾기 (ECU City)</a>' % esc.escape(_gmap)
    rea_html   = '<a class="rea-link" href="%s" target="_blank">↗ realestate.com.au/%s</a>' % (esc.escape(rea_url), lid)

    # photo img tags — try 01-40, remove on error (캡 없음; 40은 안전 상한)
    photo_tags = "".join(
        '<img src="%s/%s_%02d.jpg" onerror="this.remove()" alt="">' % (IMGDIR, lid, i)
        for i in range(1, 41))

    included.append({
        "html": (
            '<div class="card" id="card-{lid}" data-price="{price}" data-mins="{mins}" data-walk="{walk}" data-floor="{floor}" data-zone="{zone}" data-rank="{rank}" data-interior="{interior}" data-detached="{detached}" data-id="{lid}" data-overbudget="{overbudget}">'
            '<div class="chead">'
            '  <button class="fav-btn" data-fav="{lid}" title="즐겨찾기">★</button>'
            '  <div class="top">{rank_badge}<span class="price">${price}</span></div>'
            '  <div class="addr">{addr}</div>'
            '  <div class="suburb-line">{region} · {ptype} · {bd}bd/{ba}ba/{car}car · 입주 {avail}</div>'
            '  <div class="badges">{zone_badge}{floor_badge}{cond_badge}{tag_badges}{overbudget_badge}</div>'
            '  <div class="tot">종합 <b>{score_total}</b> / {maxt}{dq}</div>'
            '  {oneliner}'
            '</div>'
            '{detail}'
            '<div class="photos">{photos}</div>'
            '<div class="card-footer">{gmaps} &nbsp; {rea}</div>'
            '</div>'
        ).format(
            price=price_int, mins=mins, walk=walk, floor=floor, zone=zone, rank=rank,
            addr=esc.escape(addr), region=esc.escape(region), ptype=ptype,
            bd=bd, ba=ba, car=car, avail=esc.escape(avail),
            zone_badge=zone_badge_html, rank_badge=rank_badge_html,
            floor_badge=floor_badge_html, cond_badge=cond_badge_html, tag_badges=tag_badges_html,
            overbudget_badge=overbudget_badge_html,
            overbudget="1" if overbudget else "0",
            score_total=score_total, maxt=_MAXT, dq=(' <span class="sd-dq">❌탈락</span>' if score_dq else ''),
            interior=v.get("interior", 0), detached=v.get("detached", 0),
            oneliner=oneliner_html, detail=detail_html,
            gmaps=gmaps_html, photos=photo_tags, lid=lid, rea=rea_html,
        ),
        "price": price_int, "mins": mins, "walk": walk, "rank": rank,
    })

included.sort(key=lambda x: x["rank"])
cards_html = "\n".join(c["html"] for c in included)
excl_html  = "\n".join(excluded_rows)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Malgun Gothic','Segoe UI',system-ui,sans-serif;background:#f0f2f5;padding:12px;font-size:14px}
h1{font-size:1.3rem;margin-bottom:10px;color:#1a1a1a}
.controls{background:#fff;padding:10px 14px;border-radius:10px;margin-bottom:12px;
  display:flex;gap:10px;flex-wrap:wrap;align-items:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.btn{padding:5px 12px;border:1.5px solid #ccc;border-radius:20px;cursor:pointer;font-size:.8rem;background:#fff;transition:all .15s}
.btn:hover{border-color:#888}.btn.active{background:#1a73e8;color:#fff;border-color:#1a73e8}
.filter-lbl{font-size:.8rem;cursor:pointer;display:flex;align-items:center;gap:3px;white-space:nowrap}
#search{padding:5px 10px;border:1.5px solid #ccc;border-radius:20px;font-size:.82rem;width:200px;outline:none}
#search:focus{border-color:#1a73e8}
#count{font-size:.8rem;color:#888;margin-left:auto;white-space:nowrap}
.divider{width:1px;background:#e0e0e0;height:22px}

.cards{display:grid;grid-template-columns:1fr;gap:12px}
.card{background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.card-header{padding:10px 14px 8px;display:flex;gap:10px;align-items:flex-start;border-bottom:1px solid #f0f0f0}
.price{font-size:1.4rem;font-weight:800;color:#1a1a1a;min-width:56px;padding-top:2px}
.rank-badge{font-size:.95rem;font-weight:800;color:#fff;background:#1a1a1a;border-radius:8px;
  padding:3px 9px;align-self:flex-start;margin-top:2px;white-space:nowrap}
.rank-reason{font-size:.78rem;color:#555;margin-top:6px;line-height:1.5;font-weight:600;
  background:#f6f8fa;border-left:3px solid #1a73e8;padding:5px 9px;border-radius:0 6px 6px 0}
.chead{padding:12px 15px 11px;position:relative}
.top{display:flex;gap:10px;align-items:baseline}
.tot{margin-top:9px;font-size:.98rem;font-weight:800}.tot b{color:#1a73e8;font-size:1.2rem}
.oneliner{margin-top:8px;font-size:.86rem;line-height:1.55;background:#f6f8fa;border-left:3px solid #34a853;padding:7px 10px;border-radius:0 7px 7px 0;font-weight:600;color:#333}
.dq-line{border-left-color:#c0392b!important;background:#fdecea!important;color:#c0392b!important}
.sd-dq{color:#c0392b;font-size:.74rem;font-weight:700;margin-left:6px}
details{margin:0 15px 11px;border:1px solid #e8ebf0;border-radius:9px;overflow:hidden}
summary{padding:10px 13px;font-weight:700;font-size:.84rem;cursor:pointer;background:#f8f9fb;color:#1a73e8;user-select:none;list-style:none}
summary::-webkit-details-marker{display:none}
summary:hover{background:#eef1f6}
.dbody{padding:5px 13px 12px}
.sectit{font-size:.78rem;font-weight:800;color:#999;margin:12px 0 6px;letter-spacing:.5px}
.item{padding:7px 0;border-bottom:1px solid #f2f4f7}
.ihead{display:flex;justify-content:space-between;align-items:baseline}.ihead b{font-size:.84rem}
.iscore{font-weight:800;color:#1a73e8;font-size:.92rem}.iscore i{font-size:.66rem;color:#bbb;font-style:normal;font-weight:400}
.bd{margin-top:5px;background:#fafbfc;border-radius:6px;padding:5px 9px}
.pp{display:flex;justify-content:space-between;font-size:.77rem;padding:1.5px 0}
.ppl{color:#555}.ppv{font-weight:700;font-variant-numeric:tabular-nums}.ppv.neg{color:#c0392b}.ppv.pos{color:#2e7d32}
.route{margin-top:5px;font-size:.72rem;color:#999;line-height:1.5}
.why{margin-top:4px;font-size:.79rem;color:#444;line-height:1.5}
.compare{font-size:.83rem;line-height:1.65;color:#333}
.meta{flex:1;min-width:0}
.addr{font-size:.95rem;font-weight:700;color:#1a1a1a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.suburb-line{font-size:.75rem;color:#777;margin-top:2px}
.badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}
.badge{padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:700;white-space:nowrap}
.b-bare{background:#d4edda;color:#155724}
.b-mix{background:#fff3cd;color:#856404}
.b-carp{background:#fde8e8;color:#c0392b}
.b-unk{background:#e9ecef;color:#555}
.z-a{background:#1a73e8;color:#fff}
.z-b{background:#34a853;color:#fff}
.z-c{background:#9334e8;color:#fff}
.b-short{background:#fff8e1;color:#7d5800;border:1px solid #ffc107}
.b-border{background:#fde9b4;color:#7d5800;border:1px solid #f0c040}
.b-furn{background:#e8eaf6;color:#3949ab}
.b-nophoto{background:#f8f8f8;color:#aaa;border:1px solid #ddd}
.b-overbudget{background:#fff3cd;color:#856404;border:1px solid #ffc107;font-weight:700}
.card[data-overbudget="1"]{border-left:3px solid #ffc107}

.commute-row{padding:7px 14px 4px;display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:.8rem;color:#333}
.c-main{font-weight:700;color:#1a1a1a}
.xfer{font-size:.7rem;color:#e67e22;font-weight:600;margin-left:2px}
.c-bike{color:#666}
.walk-warn{color:#c0392b;font-weight:700}
.maps-link{font-size:.8rem;color:#1a73e8;text-decoration:none;white-space:nowrap;
  background:#e8f0fe;padding:4px 10px;border-radius:12px;font-weight:600}
.maps-link:hover{background:#d2e3fc}
.commute-detail{padding:2px 14px 6px;font-size:.73rem;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.grocery-row{padding:2px 14px 7px;font-size:.78rem;color:#2e7d32;font-weight:600}
.notes-row{padding:9px 14px 11px;font-size:.84rem;color:#2a2a2a;line-height:1.62;border-top:1px solid #f5f5f5;white-space:pre-wrap}
.fav-btn{position:absolute;top:9px;right:11px;z-index:2;cursor:pointer;font-size:1.4rem;line-height:1;background:none;border:none;color:#dcdcdc;padding:0;transition:color .15s}
.addr{font-size:.95rem;font-weight:700;color:#1a1a1a;margin-top:6px}
.fav-btn.on{color:#ffc107}
.fav-btn:hover{color:#ffd966}
.card.is-fav{box-shadow:0 0 0 2px #ffc107, 0 1px 6px rgba(0,0,0,.12)}
.photos{display:flex;gap:8px;padding:10px 14px 12px;overflow-x:auto;overflow-y:hidden;
  scrollbar-width:thin;scrollbar-color:#ccc transparent}
.photos::-webkit-scrollbar{height:4px}.photos::-webkit-scrollbar-thumb{background:#ccc;border-radius:2px}
.photos img{height:370px;width:auto;min-width:200px;border-radius:7px;cursor:zoom-in;
  flex-shrink:0;object-fit:cover;transition:opacity .15s}
.photos img:hover{opacity:.85}
.card-footer{padding:8px 14px 10px;font-size:.78rem;border-top:1px solid #f0f0f0;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.rea-link{color:#1a73e8;text-decoration:none}.rea-link:hover{text-decoration:underline}

.section-title{font-size:.95rem;font-weight:700;margin:22px 0 10px;color:#555;
  border-bottom:2px solid #e0e0e0;padding-bottom:6px}
.excl-table{width:100%;border-collapse:collapse;font-size:.8rem;background:#fff;
  border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.excl-table th{background:#f5f5f5;padding:8px 12px;text-align:left;font-weight:700;color:#555;border-bottom:1px solid #e0e0e0}
.excl-table td{padding:7px 12px;border-bottom:1px solid #f5f5f5;color:#555}
.excl-table tr:last-child td{border-bottom:none}
.reason{color:#c0392b;font-weight:700}.note-gray{color:#999}

#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:9999;
  justify-content:center;align-items:center}
#lb.open{display:flex}
#lb-img{max-width:94vw;max-height:92vh;border-radius:6px;object-fit:contain}
#lb-close{position:fixed;top:14px;right:18px;color:#fff;font-size:2rem;cursor:pointer;
  user-select:none;line-height:1}
#lb-nav{position:fixed;top:50%;transform:translateY(-50%);width:100%;
  display:flex;justify-content:space-between;padding:0 6px;pointer-events:none}
#lb-nav button{pointer-events:all;background:rgba(255,255,255,.18);border:none;color:#fff;
  font-size:2.2rem;padding:8px 14px;cursor:pointer;border-radius:5px;line-height:1}
#lb-nav button:hover{background:rgba(255,255,255,.3)}
#lb-cnt{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);
  color:#eee;font-size:.8rem;background:rgba(0,0,0,.4);padding:3px 10px;border-radius:10px}
"""

# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------
JS = r"""
const FAV_KEY = "perth_favs";
let FAVS = new Set(JSON.parse(localStorage.getItem(FAV_KEY) || "[]"));
function saveFavs() { localStorage.setItem(FAV_KEY, JSON.stringify([...FAVS])); }
function initFavs() {
  document.querySelectorAll(".fav-btn").forEach(b => {
    const id = b.dataset.fav;
    if (FAVS.has(id)) { b.classList.add("on"); b.closest(".card").classList.add("is-fav"); }
    b.onclick = e => {
      e.stopPropagation();
      if (FAVS.has(id)) { FAVS.delete(id); b.classList.remove("on"); b.closest(".card").classList.remove("is-fav"); }
      else { FAVS.add(id); b.classList.add("on"); b.closest(".card").classList.add("is-fav"); }
      saveFavs(); applyFilter();
    };
  });
}

let sortField = 'rank', sortDir = 1;

function setSort(f) {
  const desc = (f === 'interior' || f === 'detached');   // 점수 높을수록 좋은 항목
  if (sortField === f) sortDir *= -1; else { sortField = f; sortDir = desc ? -1 : 1; }
  document.querySelectorAll('#sort-btns .btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-sort="${f}"]`).classList.add('active');
  applySort();
}

function applySort() {
  const container = document.getElementById('cards');
  const cards = [...container.querySelectorAll('.card')];
  cards.sort((a, b) => (parseFloat(a.dataset[sortField]) - parseFloat(b.dataset[sortField])) * sortDir);
  cards.forEach(c => container.appendChild(c));
  updateCount();
}

function applyFilter() {
  const q = document.getElementById('search').value.toLowerCase();
  const floorSet = new Set([...document.querySelectorAll('.floor-cb:checked')].map(i => i.value));
  const zoneSet = new Set([...document.querySelectorAll('.zone-cb:checked')].map(i => i.value));
  const favOnly = document.getElementById('fav-only').checked;
  const hideOverbudget = document.getElementById('hide-overbudget') && document.getElementById('hide-overbudget').checked;
  document.querySelectorAll('.card').forEach(c => {
    const floorOk = floorSet.has(c.dataset.floor);
    const zoneOk = zoneSet.has(c.dataset.zone);
    const searchOk = !q || c.textContent.toLowerCase().includes(q);
    const favOk = !favOnly || FAVS.has(c.dataset.id);
    const budgetOk = !hideOverbudget || c.dataset.overbudget !== '1';
    c.style.display = floorOk && zoneOk && searchOk && favOk && budgetOk ? '' : 'none';
  });
  updateCount();
}

function updateCount() {
  const total = document.querySelectorAll('.card').length;
  const vis   = document.querySelectorAll('.card:not([style*="none"])').length;
  document.getElementById('count').textContent = vis + ' / ' + total + '건';
}

// Lightbox
let lbPhotos = [], lbIdx = 0;
function openLb(photos, idx) {
  lbPhotos = photos; lbIdx = idx; updLb();
  document.getElementById('lb').classList.add('open');
}
function closeLb() { document.getElementById('lb').classList.remove('open'); }
function updLb() {
  document.getElementById('lb-img').src = lbPhotos[lbIdx];
  document.getElementById('lb-cnt').textContent = (lbIdx + 1) + ' / ' + lbPhotos.length;
}
function lbPrev(e) { e.stopPropagation(); lbIdx = (lbIdx - 1 + lbPhotos.length) % lbPhotos.length; updLb(); }
function lbNext(e) { e.stopPropagation(); lbIdx = (lbIdx + 1) % lbPhotos.length; updLb(); }
document.addEventListener('keydown', e => {
  if (!document.getElementById('lb').classList.contains('open')) return;
  if (e.key === 'Escape') closeLb();
  if (e.key === 'ArrowLeft')  lbPrev({ stopPropagation: () => {} });
  if (e.key === 'ArrowRight') lbNext({ stopPropagation: () => {} });
});

// Photo click — collect visible loaded images in this card
document.querySelectorAll('.photos').forEach(pDiv => {
  pDiv.addEventListener('click', e => {
    const img = e.target.closest('img');
    if (!img) return;
    const imgs = [...pDiv.querySelectorAll('img')].filter(i => i.naturalWidth > 0);
    openLb(imgs.map(i => i.src), imgs.indexOf(img));
  });
});

initFavs();
updateCount();
"""

# ---------------------------------------------------------------------------
# Assemble HTML
# ---------------------------------------------------------------------------
N_INCLUDED = len(included)
N_EXCLUDED = len(excluded_rows)
N_OVERBUDGET = sum(1 for c in included if 'data-overbudget="1"' in c["html"])

# 예산초과 체크박스: overbudget 매물이 하나라도 있고 --no-cap 아닐 때만 노출
if N_OVERBUDGET > 0 and not NO_CAP:
    overbudget_toggle_html = (
        '<div class="divider"></div>'
        '<label class="filter-lbl" style="color:#856404;font-weight:700">'
        '<input type="checkbox" id="hide-overbudget" onchange="applyFilter()">'
        '💸 예산초과 제외 (%d건)</label>' % N_OVERBUDGET
    )
else:
    overbudget_toggle_html = ""

doc = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>퍼스 매물 룩북</title>
<style>{css}</style>
</head>
<body>
<h1>퍼스 매물 룩북 <span style="font-size:.8rem;font-weight:400;color:#888">{date} · A/B/C존 · {n_inc}건 포함 · {n_exc}건 제외</span></h1>

<div class="controls">
  <span style="font-size:.78rem;color:#888;font-weight:600">정렬:</span>
  <div style="display:flex;gap:5px" id="sort-btns">
    <button class="btn active" data-sort="rank" onclick="setSort('rank')">🏆 종합순위</button>
    <button class="btn" data-sort="price" onclick="setSort('price')">💰 가격</button>
    <button class="btn" data-sort="mins"  onclick="setSort('mins')">🚆 통근</button>
    <button class="btn" data-sort="interior" onclick="setSort('interior')">🏠 인테리어</button>
    <button class="btn" data-sort="detached" onclick="setSort('detached')">🏡 detached</button>
  </div>
  <div class="divider"></div>
  <span style="font-size:.78rem;color:#888;font-weight:600">존:</span>
  <label class="filter-lbl"><input class="zone-cb" type="checkbox" value="A" checked onchange="applyFilter()">Ⓐ CAT존</label>
  <label class="filter-lbl"><input class="zone-cb" type="checkbox" value="B" checked onchange="applyFilter()">Ⓑ 자전거존</label>
  <label class="filter-lbl"><input class="zone-cb" type="checkbox" value="C" checked onchange="applyFilter()">Ⓒ 기차외곽</label>
  <div class="divider"></div>
  <span style="font-size:.78rem;color:#888;font-weight:600">바닥:</span>
  <label class="filter-lbl"><input class="floor-cb" type="checkbox" value="BARE" checked onchange="applyFilter()">🟢 BARE</label>
  <label class="filter-lbl"><input class="floor-cb" type="checkbox" value="MIX"  checked onchange="applyFilter()">🟡 MIX</label>
  <label class="filter-lbl"><input class="floor-cb" type="checkbox" value="CARP" checked onchange="applyFilter()">🔴 CARP</label>
  <label class="filter-lbl"><input class="floor-cb" type="checkbox" value="?"    checked onchange="applyFilter()">❓ ?</label>
  <div class="divider"></div>
  <label class="filter-lbl"><input type="checkbox" id="fav-only" onchange="applyFilter()">⭐ 즐겨찾기만</label>
  {overbudget_toggle}
  <input type="text" id="search" placeholder="검색 (동네, 주소, 메모…)" oninput="applyFilter()">
  <span id="count"></span>
</div>

<div class="cards" id="cards">
{cards}
</div>

<p class="section-title">❌ 제외 매물 {n_exc}건 — 공용세탁·over55·통근 &gt;{cc}분·도보 &gt;{wc}m</p>
<table class="excl-table">
  <thead><tr><th>존</th><th>$</th><th>동네</th><th>주소</th><th>제외 사유</th><th>비고</th></tr></thead>
  <tbody>{excl}</tbody>
</table>

<div id="lb" onclick="closeLb()">
  <span id="lb-close" onclick="closeLb()">✕</span>
  <div id="lb-nav">
    <button onclick="lbPrev(event)">‹</button>
    <button onclick="lbNext(event)">›</button>
  </div>
  <img id="lb-img" src="" alt="">
  <div id="lb-cnt"></div>
</div>

<script>{js}</script>
</body>
</html>
""".format(css=CSS, js=JS, n_inc=N_INCLUDED, n_exc=N_EXCLUDED,
           cards=cards_html, excl=excl_html, cc=COMMUTE_CUT, wc=WALK_CUT, date=DATESTR,
           overbudget_toggle=overbudget_toggle_html)

open(out_path, "w", encoding="utf-8").write(doc)
print("wrote", out_path, "|", N_INCLUDED, "cards |", N_EXCLUDED, "excluded |",
      round(len(doc) / 1024), "KB")
