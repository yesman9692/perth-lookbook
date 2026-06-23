# -*- coding: utf-8 -*-
# ra_client.py — RapidAPI "Realty in AU" 키 자동 폴백 + 월한도 park (2026-06-16).
# 동작:
#   1) 키 파일 여러 줄 → 최신(맨 아래)→과거 순으로 시도. 줄 추가하면 폴백 풀에 자동 합류(개수 무관).
#   2) RPM(분당/버스트) vs 월 한도(500/월) 구분:
#        - 월 한도 소진(remaining<=0, 또는 429+"monthly/quota") → reset 초(x-ratelimit-requests-reset,
#          보통 수 주)만큼 `.ra_key_state.json`에 **park**. 이후 실행은 그 키를 리셋 시각까지 건너뜀
#          (만료 키 매번 재낭비 방지 — 사용자 요구 2026-06-16).
#        - RPM 429(짧은 리셋) → 이번 실행만 회피, park 안 함.
#   3) degraded(검증 실패=전국 디폴트, 단 remaining>0) → 업스트림 일시장애로 보고 이번 실행만 회피.
#   4) 성공하면 그 키의 묵은 park 상태 해제.
# 헤더: x-ratelimit-requests-remaining(월 잔여), x-ratelimit-requests-reset(리셋까지 초).
import os, json, time
from curl_cffi import requests

KEY_FILE   = r"D:\my\cowork\tools\rapidapi_key.txt"
STATE_FILE = r"D:\my\cowork\tools\.ra_key_state.json"
HOST = "realty-in-au.p.rapidapi.com"
BASE = "https://realty-in-au.p.rapidapi.com"
RPM_RESET_MAX = 3600          # reset가 이 값(초) 이하면 RPM(짧음), 초과면 월 한도로 간주
TRANSIENT = (500, 502, 503, 504)  # 공급자측 일시 오류 → 키 죽이지 말고 재시도(2026-06-23 502 폭풍 대응)
TRANSIENT_RETRIES = 3             # 키당 5xx/예외 재시도 횟수
TRANSIENT_BACKOFF = 1.5           # 백오프 기준초(시도마다 ×n: 1.5/3.0/4.5s)
_DEAD = set()                 # 이번 실행에서만 회피할 키(RPM·degraded 일시)

def load_keys():
    lines = [l.strip() for l in open(KEY_FILE, encoding="utf-8") if l.strip()]
    if not lines:
        raise RuntimeError("rapidapi_key.txt 비어있음")
    return list(reversed(lines))      # 최신(맨 아래 줄) 먼저

def _mask(k):
    return (k[:6] + "…" + k[-4:]) if len(k) > 12 else "key"

def _load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}

def _save_state(s):
    json.dump(s, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def _park(state, mask, reset_sec, reason, now):
    state[mask] = {"park_until": now + reset_sec, "reason": reason,
                   "parked_at": int(now), "reset_sec": reset_sec}

def ra_get(path, params, validate=None, timeout=40, verbose=True):
    now = time.time()
    state = _load_state()
    state_dirty = False
    avail = []
    for k in load_keys():
        m = _mask(k)
        pu = state.get(m, {}).get("park_until", 0)
        if pu and pu > now:
            if verbose:
                print("  ⏸ 키 %s 월한도 소진 — 복구까지 %.1f일, 건너뜀" % (m, (pu - now) / 86400))
            continue
        if k in _DEAD:
            continue
        avail.append(k)
    if not avail:                      # 전부 park/dead면 park 무시하고 1회 더 시도(리셋 됐을 수도)
        avail = [k for k in load_keys() if k not in _DEAD] or load_keys()

    last = None
    for k in avail:
        m = _mask(k)
        h = {"x-rapidapi-key": k, "x-rapidapi-host": HOST}
        r = None
        for attempt in range(TRANSIENT_RETRIES + 1):
            try:
                r = requests.get(BASE + path, headers=h, params=params, timeout=timeout)
            except Exception as e:
                last = ("ERR", m, str(e)[:60]); r = None
            # 공급자측 일시 5xx 또는 요청 예외 → 키를 죽이지 말고 짧은 백오프로 재시도
            if (r is None or r.status_code in TRANSIENT) and attempt < TRANSIENT_RETRIES:
                wait = TRANSIENT_BACKOFF * (attempt + 1)
                if verbose:
                    code = "EXC" if r is None else r.status_code
                    print("  ↻ 키 %s 일시오류(%s) → %.1fs 후 재시도(%d/%d)" % (m, code, wait, attempt + 1, TRANSIENT_RETRIES))
                time.sleep(wait); continue
            break
        if r is None:
            continue   # 재시도 후에도 요청 자체 실패 → 다음 키
        rem = r.headers.get("x-ratelimit-requests-remaining")
        rst = r.headers.get("x-ratelimit-requests-reset")
        remn = int(rem) if (rem and rem.lstrip("-").isdigit()) else None
        rsec = int(rst) if (rst and rst.isdigit()) else None

        if r.status_code == 429:
            body = (r.text or "").lower()
            monthly = ("month" in body or "quota" in body) or (rsec and rsec > RPM_RESET_MAX)
            if monthly:
                _park(state, m, rsec or 23 * 86400, "monthly", now); state_dirty = True
                if verbose: print("  ⛔ 키 %s 429 월한도 → %.1f일 park" % (m, (rsec or 23*86400)/86400))
            else:
                _DEAD.add(k)
                if verbose: print("  ⏳ 키 %s 429 RPM(짧음) → 이번만 회피" % m)
            last = ("429", m, rst); continue
        if r.status_code != 200:
            # 5xx(공급자측 일시장애)는 키 문제 아님 → _DEAD 안 함(다음 콜에서 재시도). 그 외(403 등)만 이번 실행 제외
            if r.status_code not in TRANSIENT:
                _DEAD.add(k)
            last = (r.status_code, m, rem); continue

        # 월 한도 소진(잔여 0 이하) → 이번 응답이 valid여도 다음 실행 위해 park
        if remn is not None and remn <= 0 and rsec:
            _park(state, m, rsec, "monthly", now); state_dirty = True
            if verbose: print("  ⛔ 키 %s 월한도 소진(remaining %s) → %.1f일 park" % (m, rem, rsec / 86400))

        j = r.json()
        if validate is None or validate(j):
            if m in state:                       # 성공 → 묵은 park 해제
                state.pop(m, None); state_dirty = True
            if state_dirty: _save_state(state)
            return j, m, rem
        _DEAD.add(k); last = ("degraded", m, rem)   # 전국 디폴트 등 일시장애, park 안 함
        if verbose: print("  ↻ 키 %s degraded(remaining=%s) → 다음 키" % (m, rem))

    if state_dirty: _save_state(state)
    raise RuntimeError("모든 키 사용불가: %s — 새 키 추가 또는 월한도 복구 대기(상태 %s)" % (last, STATE_FILE))
