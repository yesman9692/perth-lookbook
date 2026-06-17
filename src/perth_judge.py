# -*- coding: utf-8 -*-
# perth_judge.py — 사진 판정을 **claude -p(헤드리스)**로 스크립트화.
#   2026-06-16: floor 4키(floor_photo/condition/notes/tags)만 판정 — 8항목 주관채점은 수동 서브에이전트(갭).
#   2026-06-17 v2: 갭 해소 + 비용/정확성/캐시 개선 (backlog A·B·C·D·E·F·G 반영).
#     C. 환경 격리: 매 스폰을 중립 cwd(cowork 밖) + --strict-mcp-config + --setting-sources project,local
#        + --exclude-dynamic-system-prompt-sections + --add-dir TOOLS + --permission-mode bypassPermissions 로 스폰.
#        → cowork CLAUDE.md(⛔BLOCKING)/SessionStart 훅/MCP 오염 제거. 1스폰 벤치 -32% 비용·-38% 시간(Read 정상).
#     G. 모델: 격리가 user settings의 opus 기본을 떨구므로 **--model 핀 필수**. 기본 opus.
#        (Sonnet 프로토타입: 14사진 판정에서 2/5 실패·2-3x 느림·verifiable 축 오류 → 기각, "품질부족시 Opus" 발동.)
#     A. 8항목 통합 = **adaptive**: fresh 매물 = full 1패스(floor+8) 1스폰 / 루브릭bump = subj-only 1스폰.
#        (프로토타입: 동일 모델서 1패스≈2패스 점수 → 구조는 economics 선택. fresh는 1패스, bump는 subj만.)
#     D. 캐시 무효화 = rubric_version 스탬프. SUBJ 8항목만 게이트(floor는 floor_photo presence 유지 — floor는 객관·버전무관).
#        version 불일치/누락이면 subj 강제 재판정. SCORING.md 타이틀 vN 파싱 → 바꾸면 자동 rejudge.
#     E. _rubric_v4 텍스트전용 stopgap 졸업: version 누락 구 verdict는 subj 재판정 대상 → 사진기반 storage/area 가 덮어씀.
#     F. JSON 견고화: 항목별 스키마 검증 + 허용값 coerce + 실패 모드만 retry(2회).
#     B. 배치 = 사진수 기준: 매 스폰 1매물×전수사진(cap 14, 침실·카펫은 9-14번). workers로 동시성 제한.
# usage: python perth_judge.py <manifest.json> [--cache a,b] [--out f.json] [--workers 3] [--cap 14] [--model opus]
import sys, os, json, re, argparse, subprocess, tempfile, shutil, concurrent.futures as cf
sys.stdout.reconfigure(encoding="utf-8")
CLAUDE = shutil.which("claude") or "claude.cmd"
TOOLS = os.path.dirname(os.path.abspath(__file__))

FLOOR_KEYS = ("floor_photo", "condition", "notes", "tags")
SUBJ_NUM = ("interior", "carpet", "detached", "emotion", "safety", "storage", "hood", "area")
# 허용값(coerce 기준). interior/detached는 범위, 나머지는 이산 집합.
ALLOWED = {
    "carpet": [1.5, 2.5, 3.5, 5.0],
    "emotion": [0, 1],
    "safety": [0, 1, 2],
    "storage": [1.0, 1.5, 2.0, 2.5, 3.0],
    "hood": [0, 1, 2],
    "area": [1.0, 1.5, 2.0, 2.5, 3.0],
}

def rubric_version():
    """SCORING.md 첫 헤딩의 vN 파싱 → 'v4'. 바꾸면 자동 rejudge(D)."""
    try:
        with open(os.path.join(TOOLS, "SCORING.md"), encoding="utf-8") as f:
            head = f.readline()
        m = re.search(r"\bv(\d+)\b", head)
        if m:
            return "v" + m.group(1)
    except Exception:
        pass
    return "v4"

RUBRIC_VERSION = rubric_version()

# ── 루브릭 프롬프트 블록 ──────────────────────────────────────────────────────
FLOOR_DEF = (
    'floor_photo 정의: BARE=맨바닥(원목/라미네이트/타일) 전체, CARP=카펫 전체, MIX=혼합, ?=불명. '
    "floor=거실+침실 바닥. tags[0]은 '빌라'(지면접근,마당가능) 또는 '아파트'(중·고층,발코니만) 중 하나.\n"
)
RUBRIC8 = (
    "■ 8항목 판정 루브릭 (점수마다 한국어 근거 필수, 사진 전수 확인. 모든 문자열 한국어, 영어 원문 인용 금지):\n"
    "1) interior 0-5 = 톤·밝기(0-3.5)+마감(0-1.5). 밝고 개방감↑ 높음, 어둡고 낡음 낮음. "
    "가상스테이징에 속지 말고 주방·욕실 실제마감으로 판정. interior_parts는 3-tuple "
    '[["밝기·개방감",<0-3.5 점수>,"근거"],["마감 품질",<0-1.5 점수>,"근거"]] (B-full).\n'
    "2) carpet ∈{5,3.5,2.5,1.5}: BARE(전체맨바닥)5 / MIX(일부카펫)3.5 / CARP밝고깨끗2.5 / CARP짙음·오염·낡음1.5.\n"
    "3) detached 0-5 정수: 완전분리villa+전용마당5 / 전용마당+사생활우려4 / 마당+집붙음3 / 1층전용마당2 / 발코니만1 / 없음0.\n"
    "4) emotion ∈{0,1}: 외관 특출 또는 뷰(시티/리버 **명확할 때만**) 있으면 1, 흐릿한 교외전망은 0.\n"
    "5) safety ∈{0,1,2}: 기본1(일반 잠금). 보안게이트·gated·secure complex +1=2 / 두꺼운 쇠창살·burglar bars −1=0.\n"
    "6) storage ∈{1,1.5,2,2.5,3}: **붙박이 소지품 수납 중심**(런드리는 세탁유틸이라 제외). "
    "WIR(워크인로브) 또는 BIR+별도수납(팬트리·린넨·창고)다수=3 / BIR+부가1종=2.5 / BIR보유(호주표준)=2 / 부엌cupboard위주=1.5 / 빌트인 거의없음=1. "
    "**사진 우선**(침실 붙박이장·워크인로브·린넨장·팬트리·창고 실물 확인) + 광고텍스트 보조. 미언급≠없음 — 사진으로 확인.\n"
    "7) hood ∈{0,1,2}: 기본1(보통). 예쁨(leafy·강변확립 — West Leederville·Mt Lawley·South Perth·Como급)+1=2 / 우범(Armadale·Maddington·Gosnells 등)−1=0.\n"
    "8) area ∈{1,1.5,2,2.5,3}: **실내면적만**(마당·파티오 제외=detached항목, 이중계산 금지). 넓음3/표준2.5/보통2/작음1.5/협소1. 광고 m² 우선, 없으면 실내사진 추정.\n"
)
FULL_KEYS_LINE = (
    "출력 JSON 키(이것만, 코드펜스·다른키·설명·배열래퍼 금지): floor_photo, condition, notes, tags, "
    "interior, interior_parts, interior_reason, carpet, carpet_reason, detached, detached_reason, "
    "emotion, emotion_reason, safety, safety_reason, storage, storage_reason, hood, hood_reason, "
    "area, area_reason, oneliner, disqualify."
)
SUBJ_KEYS_LINE = (
    "출력 JSON 키(이것만, 코드펜스·다른키·설명·배열래퍼 금지): "
    "interior, interior_parts, interior_reason, carpet, carpet_reason, detached, detached_reason, "
    "emotion, emotion_reason, safety, safety_reason, storage, storage_reason, hood, hood_reason, "
    "area, area_reason, oneliner, disqualify."
)

def _imgs(lid, cap):
    ps = [os.path.join(TOOLS, "imgs_detail", "%s_%02d.jpg" % (lid, i)) for i in range(1, cap + 1)]
    return [p for p in ps if os.path.exists(p)]

def _prompt(lid, mode, cap):
    detail = os.path.join(TOOLS, "detail_%s.json" % lid)
    imgs = _imgs(lid, cap)
    head = ("퍼스 렌트 매물 판정. " + detail + " 와 사진 " + ", ".join(imgs) +
            " 를 Read 도구로 전부 보고 아래 JSON **한 객체만** 출력하라.\n")
    if mode == "full":
        return head + FLOOR_DEF + RUBRIC8 + FULL_KEYS_LINE
    if mode == "subj":
        return head + RUBRIC8 + SUBJ_KEYS_LINE
    # floor
    return (head + FLOOR_DEF +
            "출력 JSON 키(이것만): floor_photo(\"BARE|MIX|CARP|?\"), condition(\"모던|보통|노후\"), "
            "notes(\"빌라/아파트 판정+마당+특이점 한국어 1줄\"), tags(배열).")

# ── 격리 스폰 (C) ─────────────────────────────────────────────────────────────
def _spawn(prompt, model, timeout=300):
    """중립 cwd + 격리 플래그로 claude -p 스폰. (envelope, judged_obj, stderr) 반환."""
    neutral = tempfile.mkdtemp(prefix="judge_")
    try:
        r = subprocess.run(
            [CLAUDE, "-p", "--output-format", "json", "--model", model,
             "--strict-mcp-config",
             "--setting-sources", "project,local",
             "--exclude-dynamic-system-prompt-sections",
             "--add-dir", TOOLS,
             "--permission-mode", "bypassPermissions"],
            input=prompt, cwd=neutral, capture_output=True, text=True,
            encoding="utf-8", timeout=timeout)
    finally:
        try: shutil.rmtree(neutral)
        except Exception: pass
    env = None
    try: env = json.loads(r.stdout or "")
    except Exception: pass
    txt = (env or {}).get("result", r.stdout or "")
    return env, _first_json(txt), (r.stderr or "")

def _first_json(text):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text or ""):
        if ch == '{':
            try:
                obj, _ = dec.raw_decode(text, i); return obj
            except json.JSONDecodeError:
                continue
    return None

# ── 스키마 검증 + coerce (F) ──────────────────────────────────────────────────
def _nearest(val, allowed):
    try: f = float(val)
    except (TypeError, ValueError): return None
    return min(allowed, key=lambda a: abs(a - f))

def _validate_floor(o):
    bad = []
    if o.get("floor_photo") not in ("BARE", "MIX", "CARP", "?"):
        bad.append("floor_photo")
    for k in ("condition", "notes"):
        if not o.get(k): bad.append(k)
    if not isinstance(o.get("tags"), list): bad.append("tags")
    return bad

def _validate_coerce_subj(o):
    """8항목 검증 + 허용값 coerce. 반환 = 누락/불량 키 리스트(빈 리스트면 통과)."""
    bad = []
    # interior 0-5
    try:
        iv = float(o.get("interior"))
        o["interior"] = round(max(0.0, min(5.0, iv)), 1)
    except (TypeError, ValueError):
        bad.append("interior")
    if not (isinstance(o.get("interior_parts"), list) and len(o["interior_parts"]) >= 2):
        bad.append("interior_parts")
    # detached 0-5 정수
    try:
        o["detached"] = int(round(max(0, min(5, float(o.get("detached"))))))
    except (TypeError, ValueError):
        bad.append("detached")
    # 이산 집합 항목
    for k, allowed in ALLOWED.items():
        c = _nearest(o.get(k), allowed)
        if c is None: bad.append(k)
        else: o[k] = c
    # 근거/메타
    for k in ("interior_reason", "carpet_reason", "detached_reason", "emotion_reason",
              "safety_reason", "storage_reason", "hood_reason", "area_reason", "oneliner"):
        if not o.get(k): bad.append(k)
    if "disqualify" not in o or not isinstance(o.get("disqualify"), bool):
        o["disqualify"] = bool(o.get("disqualify", False))
    return bad

def _extract(o, keys):
    return {k: o[k] for k in keys if k in o}

# subj-only(루브릭bump) 모드에서 floor를 따로 안 판정할 때, 신선한 carpet 점수로 floor_photo 동기화
# (구 floor_photo가 새 carpet 판독과 어긋나 CARP태그·MIX점수 불일치하는 것 방지 — 신선 판독 우선).
CARPET_TO_FLOOR = {5.0: "BARE", 3.5: "MIX", 2.5: "CARP", 1.5: "CARP"}

# 전체 subj 출력 키(검증 통과시 저장)
SUBJ_OUT = (list(SUBJ_NUM) + ["interior_parts", "interior_reason", "carpet_reason",
            "detached_reason", "emotion_reason", "safety_reason", "storage_reason",
            "hood_reason", "area_reason", "oneliner", "disqualify"])

def judge_one(lid, needs, model, cap):
    """needs ⊆ {'floor','subj'}. fresh(둘다)=full 1스폰, bump=subj 1스폰, floor만=floor 1스폰.
    실패 모드만 최대 2회 retry. 반환 = (lid, 판정 dict)."""
    out = {}
    mode = "full" if needs == {"floor", "subj"} else ("subj" if needs == {"subj"} else "floor")
    for attempt in range(1, 4):
        env, o, err = _spawn(_prompt(lid, mode, cap), model)
        if o is None:
            if attempt == 3:
                out.setdefault("notes", "JSON 파싱실패(%d회): %s" % (attempt, (err or "")[:60]))
                if "floor" in needs: out.setdefault("floor_photo", "?")
                return lid, out
            continue
        bad = []
        if mode in ("full", "floor"):
            fbad = _validate_floor(o)
            if not fbad:
                out.update(_extract(o, FLOOR_KEYS))
            bad += fbad
        if mode in ("full", "subj"):
            sbad = _validate_coerce_subj(o)
            if not sbad:
                out.update(_extract(o, SUBJ_OUT))
                out["rubric_version"] = RUBRIC_VERSION   # D: subj 판정분에 버전 스탬프
            bad += sbad
        if not bad:
            # subj-only 모드: 신선 carpet 점수로 floor_photo 동기화(구 floor와 불일치 방지).
            # full 모드는 floor 판정이 직접 floor_photo를 세팅하므로 건드리지 않음.
            if "subj" in needs and "floor" not in needs and "carpet" in out:
                out["floor_photo"] = CARPET_TO_FLOOR.get(out["carpet"], "?")
            return lid, out
        # 실패 모드만 좁혀 retry: full에서 floor만 실패하면 floor, subj만 실패하면 subj
        if mode == "full":
            floor_failed = any(b in FLOOR_KEYS for b in bad)
            subj_failed = any(b not in FLOOR_KEYS for b in bad)
            if floor_failed and not subj_failed: mode = "floor"
            elif subj_failed and not floor_failed: mode = "subj"
            # 둘 다 실패면 full 유지
        if attempt == 3:
            # 마지막: 부분 결과라도 보존 + 표식
            if "floor" in needs and "floor_photo" not in out: out["floor_photo"] = "?"
            out.setdefault("_judge_incomplete", ",".join(sorted(set(bad)))[:80])
            return lid, out
    return lid, out

def load_cache(files):
    cache = {}
    for f in files:
        f = f.strip()
        if not f: continue
        p = f if os.path.isabs(f) else os.path.join(TOOLS, f)
        try:
            cache.update(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    return cache

def _needs(vd):
    """이 매물에 어떤 판정이 필요한지. floor=floor_photo presence(버전무관), subj=8항목+현버전 일치."""
    need = set()
    if not vd.get("floor_photo"):
        need.add("floor")
    has_subj = all(k in vd for k in SUBJ_NUM)
    if not has_subj or vd.get("rubric_version") != RUBRIC_VERSION:
        need.add("subj")   # E: 구 verdict는 rubric_version 누락 → subj 재판정 → text-only storage 졸업
    return need

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--cache", default="verdicts.json")
    ap.add_argument("--out", default="verdicts_partial_auto.json")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--cap", type=int, default=14)   # B: 전수 사진(침실·카펫 9-14번)
    ap.add_argument("--model", default="opus")        # G: 격리가 기본모델 떨구므로 핀 필수
    a = ap.parse_args()

    man = json.load(open(a.manifest, encoding="utf-8"))
    cache = load_cache(a.cache.split(","))
    ids = [m["id"] for m in man]

    plan = {i: _needs(cache.get(i, {})) for i in ids}
    reuse = [i for i in ids if not plan[i]]
    todo = [i for i in ids if plan[i]]
    n_full = sum(1 for i in todo if plan[i] == {"floor", "subj"})
    n_subj = sum(1 for i in todo if plan[i] == {"subj"})
    n_floor = sum(1 for i in todo if plan[i] == {"floor"})
    print("판정 %d건 (rubric=%s, model=%s, cap=%d): 재사용 %d / full %d / subj-only %d / floor-only %d (workers=%d)"
          % (len(ids), RUBRIC_VERSION, a.model, a.cap, len(reuse), n_full, n_subj, n_floor, a.workers))

    res = {}
    for i in reuse:
        keep = _extract(cache[i], FLOOR_KEYS) | _extract(cache[i], SUBJ_OUT)
        if cache[i].get("rubric_version"): keep["rubric_version"] = cache[i]["rubric_version"]
        res[i] = keep
        print("  ♻ 재사용", i)

    if todo:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(judge_one, i, plan[i], a.model, a.cap): i for i in todo}
            for fut in cf.as_completed(futs):
                lid, vd = fut.result()
                res[lid] = vd
                tag = "·".join(sorted(plan[lid]))
                print("  🤖", lid, "[%s]" % tag, vd.get("floor_photo", "-"),
                      "int=%s carp=%s det=%s area=%s stor=%s" %
                      (vd.get("interior", "-"), vd.get("carpet", "-"), vd.get("detached", "-"),
                       vd.get("area", "-"), vd.get("storage", "-")),
                      ("⚠" + vd["_judge_incomplete"]) if "_judge_incomplete" in vd else "")

    out = a.out if os.path.isabs(a.out) else os.path.join(TOOLS, a.out)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("저장:", a.out, "(%d건)" % len(res))

if __name__ == "__main__":
    main()
