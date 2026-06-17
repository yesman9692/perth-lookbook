# -*- coding: utf-8 -*-
# ⚠️ 레거시·졸업 (2026-06-17): perth_judge.py가 이제 면적(3스케일)·수납을 사진 기반으로 직접 판정한다.
#   이 일회성 remap 스크립트는 더 이상 파이프라인에서 호출하지 않음(과거 v3→v4 마이그레이션 기록용 보존).
#   루브릭 변경은 SCORING.md 첫줄 vN 올리기 → judge가 rubric_version 게이트로 8항목 자동 재판정(SCORING.md 참조).
# perth_rubric_v4.py — v3→v4 루브릭 적용 (2026-06-17, 사용자 요청).
#   ① 면적: 정수 1-5 → 3점 스케일 {5:3, 4:2.5, 3:2, 2:1.5, 1:1} 결정적 remap (재판정 불필요 — 단계 동일)
#   ② 수납: 런드리중심 폐기 → 붙박이 소지품 수납 중심. detail description의 텍스트 신호로 결정적 재채점.
#      WIR=3 / BIR+부가2종↑=3 / BIR+부가1종=2.5 / BIR=2 / 부엌장 등만=1.5 / 없음=1
#   ③ 편의·통근 등 자동항목은 perth_score.py가 재계산하므로 여기선 안 건드림.
# 멱등: vd["_rubric_v4"]=True 마킹으로 재실행 안전.
# usage: python perth_rubric_v4.py auto_<slug>_manifest.json verdicts.json
import sys, json, re, os
sys.stdout.reconfigure(encoding="utf-8")
TOOLS = os.path.dirname(os.path.abspath(__file__))

AREA_MAP = {5: 3.0, 4: 2.5, 3: 2.0, 2: 1.5, 1: 1.0}

def _desc(lid):
    fp = os.path.join(TOOLS, "detail_%s.json" % lid)
    if not os.path.exists(fp):
        return ""
    d = json.load(open(fp, encoding="utf-8"))
    return re.sub(r"<[^>]+>", " ", (d.get("description", "") or "")).lower()

def storage_v4(blob):
    """붙박이 소지품 수납 점수 + 발견 신호 리스트."""
    has_wir = any(s in blob for s in
                  ["walk-in robe", "walk in robe", "walkin robe", "walk-in wardrobe", "walk in wardrobe", "wir"])
    has_bir = has_wir or any(s in blob for s in
                  ["built-in robe", "built in robe", "builtin robe", "built-in wardrobe",
                   "built in wardrobe", "b.i.r", " bir", "robe", "wardrobe"])
    extras = []
    if "linen" in blob:                                            extras.append("린넨장")
    if "pantry" in blob:                                           extras.append("팬트리")
    if any(s in blob for s in ["store room", "storeroom", "storage room", "store-room"]):
        extras.append("창고")
    if any(s in blob for s in ["loads of cupboard", "ample cupboard", "plenty of cupboard",
                               "cupboard space", "lots of cupboard", "abundance of cupboard"]):
        extras.append("넉넉한 부엌장")
    n = len(extras)
    if has_wir:
        score, why = 3.0, "워크인 로브(WIR)" + (" + " + "·".join(extras) if extras else "")
    elif has_bir and n >= 2:
        score, why = 3.0, "붙박이장(BIR) + " + "·".join(extras)
    elif has_bir and n == 1:
        score, why = 2.5, "붙박이장(BIR) + " + extras[0]
    elif has_bir:
        score, why = 2.0, "붙박이장(BIR) 보유 (호주 표준)"
    elif extras:
        score, why = 1.5, "붙박이장 명시 없음, " + "·".join(extras) + "만"
    else:
        score, why = 1.0, "광고에 붙박이 수납 신호 없음 (사진 확인 권장)"
    return score, why

def main():
    if len(sys.argv) < 3:
        print("usage: python perth_rubric_v4.py manifest.json verdicts.json"); return
    man = json.load(open(sys.argv[1], encoding="utf-8"))
    vpath = sys.argv[2]
    v = json.load(open(vpath, encoding="utf-8"))
    ids = [e["id"] for e in man]
    n_area = n_stor = n_skip = 0
    for lid in ids:
        vd = v.get(lid)
        if not vd:
            continue
        if vd.get("_rubric_v4"):
            n_skip += 1; continue
        # ① 면적 remap
        old_area = vd.get("area")
        if old_area is not None:
            key = int(round(float(old_area)))
            new_area = AREA_MAP.get(key, max(1.0, min(3.0, float(old_area))))
            vd["area"] = new_area
            vd["area_parts"] = [["면적", new_area]]
            n_area += 1
        # ② 수납 재채점
        sc, why = storage_v4(_desc(lid))
        vd["storage"] = sc
        vd["storage_reason"] = why
        vd["storage_parts"] = [["수납", sc]]
        n_stor += 1
        vd["_rubric_v4"] = True
    json.dump(v, open(vpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("v4 적용 완료: 면적 remap %d건 · 수납 재채점 %d건 · skip(이미 v4) %d건" % (n_area, n_stor, n_skip))

if __name__ == "__main__":
    main()
