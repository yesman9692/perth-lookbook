# -*- coding: utf-8 -*-
# perth_merge_verdicts.py — 채점 서브에이전트가 각자 쓴 verdicts_partial_*.json 들을
#   verdicts.json 으로 합친다(몇 초). 본체가 손으로 전사하던 단계를 제거(2026-06-16).
# 운영: 각 서브에이전트가 자기 배치를 `tools/verdicts_partial_{batch}.json`에 Write →
#       이 스크립트가 glob 머지(기존 verdicts.json의 다른 키 보존, 같은 id는 update).
# usage: python perth_merge_verdicts.py                       # tools/verdicts_partial_*.json → verdicts.json (blind glob)
#        python perth_merge_verdicts.py a.json b.json          # 명시한 partial만 머지 (오케스트레이터=slug 한정, stale 오염 차단)
#        python perth_merge_verdicts.py --reset [files...]     # 기존 verdicts.json 무시하고 partial만으로 새로
# ⚠️ 인자 없는 blind glob은 다른 run/배치가 남긴 stale partial까지 슬러프함 — 자동 파이프라인은 항상 경로를 명시할 것.
import os, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8")
TOOLS = r"D:\my\cowork\tools"
VPATH = os.path.join(TOOLS, "verdicts.json")

base = {}
if "--reset" not in sys.argv and os.path.exists(VPATH):
    base = json.load(open(VPATH, encoding="utf-8"))

# 명시한 .json 경로가 있으면 그것만(stale 오염 차단), 없으면 기존 blind glob(수동 워크플로 하위호환)
explicit = [a for a in sys.argv[1:] if not a.startswith("-") and a.endswith(".json")]
if explicit:
    parts = sorted(p for p in explicit if os.path.exists(p))
    missing = [p for p in explicit if not os.path.exists(p)]
    for m in missing:
        print("skip(없음)", os.path.basename(m))
else:
    parts = sorted(glob.glob(os.path.join(TOOLS, "verdicts_partial_*.json")))
n = 0
for p in parts:
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("skip(파싱실패)", os.path.basename(p), e); continue
    for lid, vd in d.items():
        cur = base.get(lid, {})
        cur.update(vd)          # 판정 필드 병합(floor_photo/notes 등 기존값 보존)
        base[lid] = cur
        n += 1
    print("merged", os.path.basename(p), "(%d ids)" % len(d))

json.dump(base, open(VPATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("=> verdicts.json 갱신: partial %d개, 항목 %d건 병합, 총 %d 매물" % (len(parts), n, len(base)))
