# -*- coding: utf-8 -*-
# perth_score.py — 매물 61점 종합 채점 + 순위 (2026-06-16 v3).
# 자동 6항목(가격·통근·자전거·편의·소음·주차)은 여기서 계산, 판정 8항목(인테리어·카펫·detached·
# 감성·안전·수납·동네·면적)은 사진판정 서브에이전트가 verdicts.json에 미리 채워둔 값을 읽어 합산한다.
# 루브릭 명세 = SCORING.md. 서브에이전트 프롬프트 템플릿도 SCORING.md에 있음.
#
# 선행: perth_search→detail→commute(통근+amenity)→micro 서브에이전트(noise)→채점 서브에이전트
#       (interior/carpet/detached/emotion/safety/storage/hood/area + disqualify를 verdicts에 기록)
# usage: python perth_score.py manifest_full.json verdicts.json micro.json
#   → verdicts.json에 score_total/score_breakdown/score_dq/rank/rank_reason 기록 + 순위표 출력
import sys, json, re, os
sys.stdout.reconfigure(encoding="utf-8")
TOOLS = r"D:\my\cowork\tools"

def _parking(lid):
    fp = os.path.join(TOOLS, "detail_%s.json" % lid)
    if not os.path.exists(fp):
        return 0
    d = json.load(open(fp, encoding="utf-8"))
    return (d.get("features", {}) or {}).get("general", {}).get("parkingSpaces", 0) or 0

SAFETY_CORRIDOR = {"Armadale", "Maddington", "Gosnells"}   # WA Police 고범죄 corridor (베이스 감점, micro로 보정)

def parse_commute(s):
    mins = re.search(r"🚆\s*(\d+)분", s or "")
    walk = re.search(r"🚆\s*\d+분\(도보\s*(\d+)m\)", s or "")
    xm = re.search(r"·환승(\d+)회", s or "")
    is_train = "Line]" in (s or "")          # 기차 노선 포함 여부
    bm = re.search(r"자전거\s+(?:(\d+)\s+hours?\s+)?(\d+)\s+mins?", s or "")   # "11 mins" 또는 "2 hours 6 mins"
    bike_min = ((int(bm.group(1)) if bm.group(1) else 0) * 60 + int(bm.group(2))) if bm else None
    return (int(mins.group(1)) if mins else 999,
            int(walk.group(1)) if walk else 0,
            int(xm.group(1)) if xm else 0,
            not is_train, bike_min)

def score_price(price):
    # $700=3 / $500=8 선형. 절대가격(통근↔가격 상쇄로 A존 이중우대 차단)
    return round(max(0, min(10, 3 + (700 - price) / 40)), 2)

def score_commute(commute_str):
    mins, walk, xfer, is_bus, bike = parse_commute(commute_str)
    s = 10 - mins / 10 - xfer - (1 if is_bus else 0) - walk / 300
    return round(max(0, min(10, s)), 2)    # 0~10 cap (자전거는 별도 항목)

def score_bike(commute_str):
    # 자전거 5점 만점, 독립 항목. 10분 이하 5 / 10분 초과 1분당 −0.1 / 30분 초과 0.
    _, _, _, _, bike = parse_commute(commute_str)
    if bike is None or bike > 30:
        return 0
    if bike <= 10:
        return 5.0
    return round(5 - (bike - 10) * 0.1, 2)

def score_noise(noise_grade):
    # 2점 만점 (v3). 낮음/보통 2 / 약간 1 / 높음 1 / 심함 0.
    return {"낮음": 2, "보통": 2, "약간": 1, "높음": 1, "심함": 0}.get(noise_grade, 2)

def score_convenience(amenity_str):
    # 편의 5점 만점 (v3). amenity 계약: "🏪 amenity:<TIER>(클러스터<N>·최근접<M>m)"
    # TIER base: A=5, B=3.5, C=2, D=0.5. 도보 penalty −min(base, M/100*0.5).
    if not amenity_str:
        return 0.0
    tm = re.search(r"amenity:([ABCD])\(클러스터(\d+)·최근접(\d+)m\)", amenity_str or "")
    if not tm:
        return 0.0
    tier, N, M = tm.group(1), int(tm.group(2)), int(tm.group(3))
    base = {"A": 5.0, "B": 3.5, "C": 2.0, "D": 0.5}[tier]
    penalty = min(base, M / 100 * 0.5)
    return round(max(0.0, min(5.0, base - penalty)), 2)

def score_parking(park):
    # 주차 1점 만점 (v3). 1대 이상 1 / 없음 0.
    return 1 if (park or 0) >= 1 else 0

def main():
    if len(sys.argv) < 4:
        print("usage: python perth_score.py manifest_full.json verdicts.json micro.json"); return
    manifest = {e["id"]: e for e in json.load(open(sys.argv[1], encoding="utf-8"))}
    v = json.load(open(sys.argv[2], encoding="utf-8"))
    micro = json.load(open(sys.argv[3], encoding="utf-8"))

    # 자동 6항목(가격·통근·자전거·편의·소음·주차) + 판정 8항목(인테리어·카펫·detached·감성·안전·수납·동네·면적) = 61점 (v3 2026-06-16).
    JUDGE_KEYS = ["interior", "carpet", "detached", "emotion", "safety", "storage", "hood", "area"]
    LABEL = {"interior": "인테리어", "carpet": "카펫", "detached": "detached",
             "emotion": "감성", "safety": "안전", "storage": "수납", "hood": "동네", "area": "면적"}

    rows = []
    for lid, vd in v.items():
        if lid not in manifest:
            continue                              # 이번 manifest 대상 아닌 매물 skip (rank 산정 제외)
        if not all(k in vd for k in JUDGE_KEYS):
            continue                              # 채점 서브에이전트 미완료 매물 skip
        e = manifest.get(lid, {})
        price = int(re.sub(r"[^0-9]", "", str(e.get("price", "0"))) or 0)
        park = _parking(lid)      # detail_{id}.json features.general.parkingSpaces
        amenity_str = e.get("amenity", "")
        noise_grade = micro.get(lid, {}).get("noise", "보통")
        bd = {
            "가격": score_price(price),
            "통근": score_commute(e.get("commute", "")),
            "자전거": score_bike(e.get("commute", "")),
            "편의": score_convenience(amenity_str),
            "소음": score_noise(noise_grade),
            "주차": score_parking(park),
        }
        for k in JUDGE_KEYS:
            bd[LABEL[k]] = vd.get(k, 0)
        total = round(sum(bd.values()), 1)
        dq = vd.get("disqualify", False)
        vd["score_breakdown"] = bd
        vd["score_total"] = total
        vd["score_dq"] = dq

        # 항목별 점수 풀이 (카드 표시용) — 자동항목은 계산 근거, 판정항목은 서브에이전트 reason
        mins, walk, xfer, bus, bike = parse_commute(e.get("commute", ""))
        comm_parts = [("기본", 10.0), ("시간 %d분 (10분당 −1)" % mins, -round(mins/10, 2))]
        if xfer: comm_parts.append(("환승 %d회" % xfer, -float(xfer)))
        if bus: comm_parts.append(("버스 이용", -1.0))
        comm_parts.append(("역도보 %dm (300m당 −1)" % walk, -round(walk/300, 2)))
        comm_route = e.get("commute", "").replace(" (Maps)", "").strip()
        bike_why = ("자전거 %d분 — 10분 이하 5 / 10분 초과 1분당 −0.1 / 30분 초과 0" % bike) if bike is not None else "자전거 정보 없음 (0)"

        # 편의 parts
        am_tm = re.search(r"amenity:([ABCD])\(클러스터(\d+)·최근접(\d+)m\)", amenity_str or "")
        if am_tm:
            am_tier, am_N, am_M = am_tm.group(1), int(am_tm.group(2)), int(am_tm.group(3))
            am_base = {"A": 5.0, "B": 3.5, "C": 2.0, "D": 0.5}[am_tier]
            am_pen = min(am_base, am_M / 100 * 0.5)
            conv_parts = [
                ("TIER %s 기본" % am_tier, am_base),
                ("최근접 %dm 도보 페널티" % am_M, -round(am_pen, 2)),
            ]
        else:
            conv_parts = [("amenity 정보 없음", 0.0)]

        # 소음 parts
        noise_parts = [("소음등급 %s" % noise_grade, bd["소음"])]

        # 주차 parts
        park_parts = [("주차 %d대" % park, bd["주차"])]

        detail = {
            "가격": {"s": bd["가격"], "parts": [("$%d → 3 + (700−%d)/40" % (price, price), bd["가격"])]},
            "통근": {"s": bd["통근"], "parts": comm_parts, "route": comm_route},
            "자전거": {"s": bd["자전거"], "why": bike_why},
            "편의": {"s": bd["편의"], "parts": conv_parts, "route": amenity_str or "정보 없음"},
            "소음": {"s": bd["소음"], "parts": noise_parts, "why": micro.get(lid, {}).get("noise_reason", "") or ("소음 " + noise_grade)},
            "주차": {"s": bd["주차"], "parts": park_parts},
        }
        # 판정 8항목: <key>_parts 가 있으면 사용, 없으면 reason으로 폴백
        for k in JUDGE_KEYS:
            lbl = LABEL[k]
            s_val = vd.get(k, 0)
            reason = vd.get(k + "_reason", "")
            raw_parts = vd.get(k + "_parts")           # 채점 에이전트가 넣은 분해 리스트 (optional)
            # 멀티성분 분해(예 인테리어=밝기+마감)면 그대로 쓰고, 단일/trivial([["안전",2]]류)면
            # 에이전트 reason을 분해 라벨로 — "왜 이 점수인지"가 카드에 보이도록(#3).
            if raw_parts and isinstance(raw_parts, list) and len(raw_parts) >= 2:
                parts = raw_parts
            elif reason:
                parts = [[reason, s_val]]
            elif raw_parts and isinstance(raw_parts, list):
                parts = raw_parts
            else:
                parts = [[lbl, s_val]]
            detail[lbl] = {"s": s_val, "parts": parts, "why": reason}
        vd["score_detail"] = detail

        rows.append((total, dq, lid))

    # 순위: 탈락 맨뒤, 점수 내림차순
    rows.sort(key=lambda x: (x[1], -x[0]))
    for rank, (total, dq, lid) in enumerate(rows, 1):
        bd = v[lid]["score_breakdown"]
        v[lid]["rank"] = rank
        base = ("종합 %s/61 = 가격 %s · 통근 %s · 자전거 %s · 편의 %s · 소음 %s · 주차 %s · 인테리어 %s · 카펫 %s · detached %s · 감성 %s · 안전 %s · 수납 %s · 동네 %s · 면적 %s" %
                (total, bd["가격"], bd["통근"], bd["자전거"], bd["편의"], bd["소음"], bd["주차"],
                 bd["인테리어"], bd["카펫"], bd["detached"], bd["감성"], bd["안전"], bd["수납"],
                 bd["동네"], bd["면적"]))
        v[lid]["rank_reason"] = ("❌ 단기계약 탈락 — " + base) if dq else base

    json.dump(v, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("채점 완료: %d건 (verdicts.json에 score_total/breakdown/rank 기록)\n" % len(rows))
    for rank, (total, dq, lid) in enumerate(rows, 1):
        e = manifest.get(lid, {})
        tag = " ❌탈락" if dq else ""
        print("%2d. %4.1f점  %s $%s (%s)%s" % (rank, total, e.get("region", ""), e.get("price", ""),
                                              (e.get("commute", "")[:0] or lid), tag))

if __name__ == "__main__":
    main()
