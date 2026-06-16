# -*- coding: utf-8 -*-
# perth_judge.py — 사진 판정을 **claude -p(헤드리스)**로 스크립트화 (2026-06-16).
#   - dedup: --cache의 verdict들(어제 것 포함)에 이미 있는 listingId는 claude -p 안 부르고 재사용.
#   - 신규만 claude -p 호출(병렬 --workers) → {floor_photo,condition,notes,tags} JSON 파싱.
#   - 출력 = verdicts_partial_auto.json → perth_merge_verdicts.py로 합침.
# 이로써 search→download→commute→render→**judge**→merge→render→deploy 전 과정이
# 사람(대화 세션) 개입 없이 스크립트 체인으로 자동화 가능(모델은 claude -p로 사용).
# usage: python perth_judge.py <manifest.json> [--cache a.json,b.json] [--out f.json] [--workers 3] [--cap 8]
import sys, os, json, re, argparse, subprocess, concurrent.futures as cf, shutil
sys.stdout.reconfigure(encoding="utf-8")
# 버그1 수정: Windows에서 "claude"는 claude.cmd라 shell=False 로 못 찾음.
# shutil.which는 PATHEXT를 고려해 claude.cmd 풀패스를 반환함.
CLAUDE = shutil.which("claude") or "claude.cmd"
# [C-2] __file__ 기준으로 이식성 확보 (하드코딩 제거)
TOOLS = os.path.dirname(os.path.abspath(__file__))
KEYS = ("floor_photo", "condition", "notes", "tags")

def load_cache(files):
    cache = {}
    for f in files:
        try:
            # [H-4] 절대경로면 그대로, 상대경로면 TOOLS 기준
            f = f.strip()
            p = f if os.path.isabs(f) else os.path.join(TOOLS, f)
            cache.update(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    return cache

def _first_json(text):
    """텍스트에서 첫 번째 완전한 JSON 객체를 추출. greedy regex 대신 raw_decode 사용.
    [H-2] 이중 블록 문자열(잡담 + JSON) 혼입 시에도 첫 JSON만 정확히 반환."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                obj, _ = dec.raw_decode(text, i)
                return obj
            except json.JSONDecodeError:
                continue
    return None

def judge_one(lid, cap):
    imgs = [os.path.join(TOOLS, "imgs_detail", "%s_%02d.jpg" % (lid, i)) for i in range(1, cap + 1)]
    imgs = [p for p in imgs if os.path.exists(p)]
    # 버그2 수정: claude가 자체 스키마(verdict/photoAnalysis/rating 등)로 응답하는 문제.
    # 출력 형식을 명시적으로 강제하고, 다른 키·설명·코드펜스를 금지함.
    # v2: claude가 listingId 래퍼나 배열 등으로 감싸는 패턴 추가 금지 명시.
    prompt = (
        "퍼스 렌트 매물 사진 판정. " + os.path.join(TOOLS, "detail_%s.json" % lid) +
        " 와 사진 " + ", ".join(imgs) + " 를 Read 도구로 보고 아래 JSON **형식 그대로만** 출력하라.\n"
        "★ 출력 규칙(반드시 준수):\n"
        "1. 아래 JSON 객체 **단 하나만** 출력. 그 외 어떤 글자도 금지.\n"
        "2. 코드펜스(```) 절대 금지.\n"
        "3. listingId·verdict·photoAnalysis·rating·pros·cons·address 같은 자체 키 추가 금지.\n"
        "4. 배열이나 중첩 객체로 감싸지 말 것 — 최상위 키는 floor_photo·condition·notes·tags 넷뿐.\n"
        "출력 형식(이 JSON 한 줄만, 다른 텍스트 없음):\n"
        '{"floor_photo":"BARE|MIX|CARP|?","condition":"모던|보통|노후",'
        '"notes":"빌라/아파트 판정+마당+특이점 한국어 1줄",'
        '"tags":["빌라 또는 아파트","마당 또는 발코니only","모던/단기/furnished 해당시"]}\n'
        "floor_photo 값 정의: BARE=맨바닥 원목/라미네이트/타일 전체, CARP=카펫 전체, MIX=혼합. "
        "빌라=지면접근(마당 가능), 아파트=중·고층(발코니만). floor=거실+침실 바닥. "
        'tags[0]에 반드시 "빌라" 또는 "아파트" 중 하나만.\n'
        "올바른 출력 예시(이 구조 그대로 복사해서 값만 채워라):\n"
        '{"floor_photo":"BARE","condition":"모던","notes":"아파트 고층, 마당없음, 원목마루 전체","tags":["아파트","발코니only","모던"]}'
    )
    try:
        # 버그1 수정: CLAUDE 변수(shutil.which로 resolve한 풀패스) 사용
        # stdin 방식: 긴 프롬프트를 -p 인수 대신 stdin으로 전달.
        # Windows에서 -p 인라인 인수로 넘길 때 claude가 JSON 템플릿 키를 인식 못 하는 문제가 있음.
        r = subprocess.run([CLAUDE, "-p", "--output-format", "text"],
                           input=prompt,
                           capture_output=True, text=True, timeout=240, encoding="utf-8")
        # [H-2] greedy regex 대신 raw_decode — 이중 JSON 블록 혼입 방어
        vd = _first_json(r.stdout or "")
        if vd is not None:
            extracted = {k: vd[k] for k in KEYS if k in vd}
            # 버그2 파싱 견고화: KEYS가 하나도 없으면 빈 dict 저장 대신 명시적 미판정 표식.
            # 빈 dict로 저장되면 dedup 게이트(cache[i].get("floor_photo")) 통과 못 해 무한 재처리.
            if not extracted:
                raw_snippet = (r.stdout or "")[:120].replace("\n", " ")
                return lid, {"floor_photo": "?", "condition": "?",
                             "notes": "스키마불일치: " + raw_snippet, "tags": []}
            return lid, extracted
        return lid, {"floor_photo": "?", "condition": "?", "notes": "JSON 파싱실패", "tags": []}
    except Exception as e:
        return lid, {"floor_photo": "?", "condition": "?", "notes": "ERR %s" % str(e)[:50], "tags": []}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--cache", default="verdicts.json,verdicts_batch1.json,verdicts_batch2.json,verdicts_batch3.json")
    ap.add_argument("--out", default="verdicts_partial_auto.json")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--cap", type=int, default=8)
    a = ap.parse_args()
    man = json.load(open(a.manifest, encoding="utf-8"))
    cache = load_cache(a.cache.split(","))
    ids = [m["id"] for m in man]
    reuse = [i for i in ids if i in cache and cache[i].get("floor_photo")]
    todo  = [i for i in ids if i not in set(reuse)]
    print("판정 %d건: 캐시 재사용 %d / claude -p 신규 %d (workers=%d)" % (len(ids), len(reuse), len(todo), a.workers))
    res = {}
    for i in reuse:
        res[i] = {k: cache[i][k] for k in KEYS if k in cache[i]}
        print("  ♻ 재사용", i)
    if todo:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            for lid, vd in ex.map(lambda x: judge_one(x, a.cap), todo):
                res[lid] = vd
                print("  🤖 claude -p", lid, vd.get("floor_photo"), vd.get("tags"))
    # [H-4] --out 절대경로면 그대로, 상대경로면 TOOLS 기준
    out = a.out if os.path.isabs(a.out) else os.path.join(TOOLS, a.out)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("저장:", a.out, "(%d건)" % len(res))

if __name__ == "__main__":
    main()
