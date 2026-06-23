# 퍼스 룩북 조사 — 오케스트레이터 지침 (tools/)

> 이 디렉토리(`D:/my/cowork/tools`)에서 퍼스 렌트 매물 조사·룩북 작업을 할 때 **먼저 읽는 문서.**
> 목적: 오케스트레이터(`perth_lookbook.py`)의 **전체 로직과 단계간 상태 전이**를 숙지해, 한 단계의 단일 신호를 잘못 일반화하는 오판을 막는다.
> 상세는 아래 "📚 상세 문서 참조 맵" 의 각 문서로.

---

## ⭐ 진입점 — `perth_lookbook.py` (단일 명령, 권장)

```
python perth_lookbook.py <group> [--beds 2,3] [--max N] [--type ...] [--floor any|bare|nocarpet]
    [--no-red] [--no-cap] [--deploy] [--slug NAME] [--skip-judge] [--no-sync]
    [--workers 6] [--cap 14] [--judge-workers 3] [--judge-cap 14] [--judge-model opus]
```
- `group`: `cat`(코어 $750) / `inner`($700) / `river`($650) / `all`(cat+inner 병합) / `first3` / `gallery` / `"Suburb, WA 60xx"`.
- 대표 풀런: `python perth_lookbook.py all --beds 2,3 --deploy --slug cat-inner-0623`
- 7개 빌딩블록을 **사람 개입 0**으로 릴레이. 내가 스크립트를 하나씩 부르는 게 아니라 **이 한 줄이 1→7 자동 진행**.

---

## 🔁 7단계 전체 흐름 (perth_lookbook.py 기준)

| 단계 | 호출 | 핵심 동작 | 상태 부작용 |
|---|---|---|---|
| `[0] sync-pull` | `_sync_pull()` (git) | `_deploy` git pull → `data/detail/*` 중 **tools에 없는 것만 복사**, verdicts/micro는 pull성공+더 최신일 때만 | detail 파일 **birth=오늘** 될 수 있음(복사라서). `--no-sync`로 끔 |
| `[1] search` | `perth_search.py` | RapidAPI 라이브 검색(존별 캡). `all`=cat+inner 각각 검색 후 **id dedup 병합** → `auto_<slug>_manifest.json` | **라이브 호출**(캐시층 없음). 0건이면 조기종료 |
| `[2] download` | `perth_download.py` | manifest의 id별 detail+사진(≤14장) 병렬. **`detail_{id}.json` 있으면 RapidAPI skip(dedup)** | `RapidAPI신규 N` = **이번 run에서 캐시에 없어 새로 받은 수** |
| `[3] commute` | `perth_commute.py` | Google Maps 도보가중 통근 + amenity_profile → manifest에 기록 | Directions/Places API 사용 |
| `[4] pdf(1차)+배포` | `perth_pdf.py` → `deploy()` | **점수 없이** 자동항목+사진만으로 룩북 즉시 렌더·배포(빠른 확인) | `--deploy`시 GitHub Pages **1차 push** |
| `[5] verdicts 캐시 확인` | (로컬) | `verdicts.json` 등 캐시 경로 확인(judge `--cache`로 전달) | Drive 캐시 폐기, git sync로 대체 |
| `[6] judge` | `perth_judge.py` (claude -p) | 사진 직접 보고 floor 4키 **+ 주관 8항목** 채점 → `verdicts_partial_<slug>.json`. **`--cache`로 기존 verdict 재사용** | `--skip-judge`로 끔. 격리 스폰 + `--model opus` 핀 |
| `[7] merge+score+pdf(2차)+배포+push` | merge_verdicts → score → pdf → deploy → `_sync_push()` | partial 머지(slug 한정) → 59점 합산·순위 → **점수 포함 2차 렌더·배포** → data/ git commit+push | GitHub Pages **2차 push** + `_deploy/data/` 자산 커밋 |

---

## ⚠️ 단계간 상태 gotcha (오판 방지 — 2026-06-23 실수의 교훈)

1. **`RapidAPI신규 0`을 "데이터 없음/stale"로 읽지 말 것.** download dedup 때문에, **직전 run(또는 sync-pull)이 이미 캐시를 채웠으면 재실행은 당연히 0.** 신선도는 **per-run 로그의 `RapidAPI신규 N`**으로 본다. 같은 세션 2회차의 0은 1회차가 받았다는 뜻.
2. **detail 파일 birth=오늘 ≠ 신규 페치.** `[0] sync-pull`이 git `data/`에서 복사해도 birth가 오늘이 된다. 신규 여부는 로그의 신규 카운트로 판정.
3. **search는 항상 라이브.** `perth_search.py`엔 캐시층이 없고 `ra_client.ra_get`을 직접 호출. 결과가 반환됐으면(에러 안 났으면) **살아있는 키로 라이브 호출 성공한 것.**
4. **churn(주간 변동) 측정**: **다른 날** manifest와 ID diff. 같은 세션/같은 날 두 run을 비교하면 당연히 동일 → 무의미.
5. **commute(3)에서 멈추면 GitHub 무변경.** 배포는 `[4]`와 `[7]`에서만. 중간 stop은 배포·채점 안 됨.
6. **judge는 adaptive·캐시 게이트.** verdict 있고 `rubric_version`(SCORING.md 첫줄 vN) 일치하면 재채점 skip. SCORING.md 버전 올리면 다음 judge가 8항목 전건 자동 재판정. 토큰은 **신규/버전불일치 건수만큼만**.

---

## 🔑 ra_client 폴백 모델 (`ra_client.py`)

- 키 파일 `rapidapi_key.txt` 여러 줄 → **역순(맨 아래=최신 먼저)** 시도. 줄 추가하면 풀 자동 합류.
- **월 한도 소진** → `.ra_key_state.json`에 reset초만큼 **park**(다음 실행도 리셋까지 skip, "건너뜀" 출력). **RPM 429** → 이번 실행만 회피, park 안 함.
- **park 키만 "건너뜀" 로그 출력. 성공 키는 침묵.** → 로그에 한 키만 보여도 폴백은 작동 중일 수 있음.
- **전 키 사망 시에만 `RuntimeError` raise.** 결과 반환 = 라이브 성공.
- 키 추가: `rapidapi_key.txt`에 새 줄. 현재 4키, 1개만 월한도 park 상태(~22일 리셋).

---

## 📋 채점·배포 핵심

- **채점 = 59점 v4** (자동6 33점 + 판정8 26점). 루브릭 전문 = `SCORING.md`. 면적 5→3, 수납=붙박이 중심, 인테리어=밝기(0~3.5)+마감(0~1.5), 안전·소음·동네 0/1/2.
- **judge 모델 = opus 핀 필수**(격리가 user settings 기본을 떨굼). Sonnet은 14사진 판정서 실패율·오류 높아 기각.
- **배포 = slug 하위폴더** `_deploy/<slug>/` → `https://yesman9692.github.io/perth-lookbook/<slug>/`. **메인 `_deploy/index.html`(마당 룩북) 불변** — slug 폴더만 staging.
- **존(zone) 2단계 설계는 의도적**: 검색은 suburb를 넓게(cat $750), 룩북 `classify_zone`은 **실제 best 통근 첫 탑승수단**으로 A/B/C 재판정. suburb 기준으로 "고치지" 말 것.
- **데이터 백업 = GitHub 단일화**(Drive 폐기). `verdicts.json`·detail·manifest·micro = `_deploy/data/`에 git 커밋. 코드 = `_deploy/src/`(수동 커밋). 새 PC = `git clone` + 키 2개 로컬 생성.

---

## 🧭 작업 태도 (상세 = 메모리 perth-rental-workflow-rules)

- **톤**: 2027.2 입주 전 탐색은 **재미로 흐름파악.** 확정·과최적화 압박 금지. 본격 수집은 2026.10-11.
- **선별 관대**: floor "?"·borderline·RED도 미리 제외 금지. **전수로 보여주고 좁히는 건 사용자.** cat 그룹도 넓게(기능, 위험 아님).
- **꼼수 금지**: `perth_detail` 요약/일괄 모드 금지, 사진 전수. 일 자체를 줄이지 말 것.
- **기존 도구 재사용**: 룩북 HTML은 `perth_pdf.py`로. 손으로 HTML 짜지 말 것. 부족하면 고쳐서 재사용.
- **산출물 렌더 확인**: 배포·완료 선언 전 브라우저로 사진·정렬 실제 확인.
- **무거운 작업 백그라운드**: 긴 run은 `run_in_background`로 띄우고 도는 동안 대화.

---

## 📚 상세 문서 참조 맵

| 문서 | 내용 |
|---|---|
| `README.md` | 5종 스크립트 사용법, 케이스①②③ 워크플로, 데이터 스키마, 변경이력 |
| `SCORING.md` | 59점 v4 루브릭 전문(14항목 단계·기준), rubric_version |
| `SETUP.md` | 새 PC 복원 절차(git clone + 키) |
| `ra_client.py` (헤더 주석) | 키 폴백·park 로직 |
| `perth_lookbook.py` (헤더 주석) | 7단계 오케스트레이션·git sync |
| 메모리 `feedback_perth_orchestrator_full_logic` | **본 CLAUDE.md의 출처가 된 2026-06-23 오판 사례 + 체크리스트** |
| 메모리 `perth-rental-workflow-rules` | 작업 태도·5종 파이프라인·케이스③ 절차 |
| 메모리 `user_perth_rental_preferences` | 카펫 🟡 등 개인 선호 |
| 메모리 `feedback_perth_realestate_session_rule` | 산출물 보존(GitHub 단일화) |
| 메모리 `reference_github_library` | GitHub Pages 도서관 패턴·PC별 인증 |

> 키 파일(`*_key.txt`)·`.gcreds`는 로컬 전용(.gitignore). 커밋 금지.
