# -*- coding: utf-8 -*-
# perth_merge_verdicts.py — 채점 서브에이전트가 각자 쓴 verdicts_partial_*.json 들을
#   verdicts.json 으로 합친다(몇 초). 본체가 손으로 전사하던 단계를 제거(2026-06-16).
# 운영: 각 서브에이전트가 자기 배치를 `tools/verdicts_partial_{batch}.json`에 Write →
#       이 스크립트가 glob 머지(기존 verdicts.json의 다른 키 보존, 같은 id는 update).
# usage: python perth_merge_verdicts.py            # tools/verdicts_partial_*.json → verdicts.json
#        python perth_merge_verdicts.py --reset    # 기존 verdicts.json 무시하고 partial만으로 새로
import os, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8")
TOOLS = r"D:\my\cowork\tools"
VPATH = os.path.join(TOOLS, "verdicts.json")

base = {}
if "--reset" not in sys.argv and os.path.exists(VPATH):
    base = json.load(open(VPATH, encoding="utf-8"))

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
