# 퍼스 렌트 매물 자동화 도구 (perth_*)

> **성격**: 정착집(2027.2 입주) 탐색 보조. **2027년 전까지는 진지한 순위 결정이 아니라 그냥 재미로 흐름 파악.** 가볍게.
> **판단 기준**: 퍼스 부동산 분석 가이드(Google Doc `1CRged5w23Jh-ljhHBNKMJNLfYV8gwZFjhq1pEXOo7LI`) §A-H + 메모리 `user-perth-rental-preferences` / `perth-rental-workflow-rules`.
> **핵심 원리**: Claude는 **스크립트를 돌려 결과(데이터+사진)만 보고 판단**한다. 데이터 수집·문서화(PDF)·Drive 업로드는 전부 스크립트가 한다. 무거운 건 백그라운드로 돌리고 그 시간에 대화한다.

## ⭐ 단일 명령 자동화 — `perth_lookbook.py` (2026-06-16, 권장 진입점)

7개 빌딩블록(search→download→commute→pdf→judge→merge→score)을 **사람 개입 0**으로 묶은 오케스트레이터. 사용자가 요구사항만 주면 search부터 GitHub Pages 배포까지 단일 명령으로 끝난다. 모델은 검증된 `claude -p`(헤드리스 비전)로만 사용 — 대화 세션이 손으로 사진 판정할 필요 없음.

```
python perth_lookbook.py <group> [--beds 2,3] [--type ...] [--floor ...] [--no-red]
    [--no-cap] [--deploy] [--slug NAME] [--no-sync]
    [--workers 6] [--cap 14] [--judge-workers 3] [--judge-cap 14] [--judge-model opus] [--skip-judge]
```
예: `python perth_lookbook.py all --beds 2,3 --deploy --slug cat-inner`

**단계** (각 단계 헤더+경과시간 출력): ⓪**git sync-pull**(`_deploy` pull → `data/`를 tools/로 복원, **pull 실패 시 verdicts 복사 skip**해 로컬 자산 보호) → ①**존별 search**(`all`=cat$750+inner$700 각각 검색 후 병합, `ZONE_SEARCH` +$50캡) `--emit` → ②**병렬** download(`detail_{id}.json` 로컬 있으면 RapidAPI skip=신규만, `--refresh` 강제) → ③commute(통근+마트) → ④**1차 배포**(점수 없이 `perth_pdf`→`_deploy/<slug>/`→git push) → ⑤**judge**(`perth_judge` claude -p, 로컬 verdicts.json 캐시로 dedup·신규만) → ⑥merge→score(**manifest 한정 순위**)→**2차 배포** + **git sync-push**(`data/verdicts.json`·manifest·detail 커밋).

- **배포·백업 = GitHub 단일(Drive 폐기)**: 서브페이지 `_deploy/<slug>/index.html`(+자체 `imgs_detail/`) + 데이터 자산 `_deploy/data/`(verdicts·detail·manifest·micro)를 **공개 repo에 커밋**. cross-PC = git pull/push. **메인 `_deploy/index.html`(마당 룩북) 무영향** — git add는 슬러그+data/ 한정. (`perth_drive_cache.py`/`perth_upload.py`는 레거시, 호출 안 함.)
- **예산초과 토글**: 존캡(A700/B650/C600) 초과 매물은 제외표가 아니라 **카드+💸배지**로 노출, "예산 초과 제외" 체크박스로 숨김(기본 표시). RED·단기·통근초과만 제외표.
- **judge가 8항목까지 자동 (2026-06-17 통합, 갭 해소)**: `perth_judge`(claude -p)가 floor 4키 **+ 주관 8항목**(인테리어·카펫·detached·감성·안전·수납·동네·면적)을 사진 직접 보고 verdicts에 기록. **수동 채점 서브에이전트 폐지** — 단일 명령으로 채점까지 끝남.
  - **격리 스폰**: 매 spawn을 중립 cwd(cowork 밖) + `--strict-mcp-config`(MCP 0) + `--setting-sources project,local`(user 훅 제외) + `--exclude-dynamic-system-prompt-sections` + `--add-dir tools`(Read용) + `--permission-mode bypassPermissions`로. cowork `CLAUDE.md`(⛔BLOCKING)·SessionStart 훅·MCP 오염 제거 → **-32% 비용·-38% 시간**(1스폰 벤치, Read 정상).
  - **모델 핀 필수(`--judge-model`, 기본 opus)**: 격리가 user settings의 모델 기본을 떨구므로 명시 핀. (Sonnet은 14사진 판정서 2/5 실패·2-3x 느림·verifiable 축 오류로 기각 — 프로토타입 측정. 품질 부족시에만 격하.)
  - **adaptive 패스(비용 최적)**: 신규 매물 = floor+8 **full 1스폰**, 루브릭 bump = **subj-only 1스폰**(floor 캐시 유지). `rubric_version`(SCORING.md 첫줄 vN) 불일치/누락이면 8항목 강제 재판정.
  - **JSON 견고화**: 항목별 스키마 검증 + 허용값 coerce + 실패 모드만 retry(2회). 출력 listingId 키잉.
  - partial 머지는 여전히 **controlled merge**(slug 한정 경로 명시; `perth_merge_verdicts` 인자 없는 blind glob은 stale 오염 주의).
  - ⚠️ **`perth_rubric_v4.py` 졸업(레거시)**: 면적 remap·텍스트전용 수납은 judge가 사진 기반으로 직접 처리 → 더 이상 호출 안 함. v3→v4 같은 과거 일회성 마이그레이션 기록용으로만 보존.
- `--skip-judge`(claude -p 없이 빠른 룩북), `--no-sync`(git sync 끄기), `--no-deploy`(로컬만): 실험·디버그용. 실 운영 judge 멀티분이면 명령 자체를 `run_in_background`로.

## 사전 준비 (이미 셋업됨, 키는 로컬 전용·동기화 X)
- `rapidapi_key.txt` — RapidAPI "Realty in AU"(realestate.com.au 우회). 무료 500콜/월. detail=1콜, 사진=0콜(reastatic CDN 직접).
  - **키 자동 폴백 + 월한도 park(`ra_client.py`, 2026-06-16)**: 한 줄에 키 하나씩, **여러 개 적으면 최신(맨 아래 줄)→과거 순으로 시도**. search/detail/market 전부 이 클라이언트 경유 → 키 막혀도 멈추지 않음. **막히면 새 키 한 줄 추가만 하면 됨**(개수 무관).
    - **월 한도(500/월) 소진**(remaining≤0 또는 429+"monthly/quota") → `x-ratelimit-requests-reset`(보통 ~22일)만큼 `.ra_key_state.json`에 **park** → 이후 실행은 리셋 시각까지 그 키를 **건너뜀**(만료 키 매번 재낭비 방지). 성공하면 park 자동 해제.
    - **RPM(분당/버스트 429, 짧은 리셋)** → 이번 실행만 회피(park 안 함). **degraded(전국 디폴트, remaining>0)** → 업스트림 일시장애로 이번 실행만 회피.
    - 전부 사용불가 시 RuntimeError로 "새 키 추가 또는 월한도 복구 대기" 명시.
- `gmaps_key.txt` — Google Maps **Directions API** 키 (GCP 프로젝트 "Analyzing Tomcat Log", Directions API 사용설정 + 결제 ON). 통근 계산. 우리 사용량은 무료 한도 내.
- `~/.claude/projects/D--my-cowork/.gcreds/` — Drive OAuth(credentials.json+token.json). sync 스크립트와 공유.
- Python + `curl_cffi`, Chrome/Edge(headless PDF 렌더).

## 스크립트 5종

| 스크립트 | 역할 | 실행 위치 | 입출력 |
|---|---|---|---|
| `perth_search.py` | 리스트 1차 필터 | **포그라운드**(빠름) | 그룹/가격/방/욕실/주차/타입/바닥/플래그 → 테이블 |
| `perth_detail.py` | 단건 상세 + 사진 | **포그라운드** | `<listingId> --imgs` → detail_{id}.json + imgs_detail/ |
| `perth_commute.py` | Maps 통근(도보가중) | **포그라운드**(빠름) | manifest 또는 단일 listingId → ECU City. `alternatives`+comfort_cost(탑승+도보×2.0) best, ⚡시간최단 병기, 평일 08:00 고정 |
| `perth_pdf.py` | 인터랙티브 룩북 HTML | **포그라운드** | manifest+detail+`VERDICTS`(코드내) → 정렬·필터·사진 가로스크롤·구글맵 링크 HTML(사진 상대경로) |
| `perth_upload.py` | Drive 업로드 | **백그라운드** | 매물 폴더 + PDF, 멱등(재실행 시 skip) |

⚠️ **백그라운드(run_in_background)**: `perth_upload.py`(Drive 업로드)만 — 매물당 새 이미지 업로드 25-35초. 돌려놓고 대화.
**포그라운드(즉시)**: search / detail / commute / **`perth_pdf`**(순수 HTML이라 즉시 생성, Chrome 렌더 불필요 — 2026-06-09 재설계).

## 워크플로 — 진입 2가지 케이스

### 케이스 ① 사용자가 링크를 줌
1. URL 끝 숫자 = listingId. (예: `.../property-villa-wa-victoria+park-444300692` → `444300692`)
2. `python perth_detail.py <id> --imgs` → 상세 + 사진 **전체**(14장 캡 제거 2026-06-09).
3. Claude가 사진으로 floor·컨디션·outdoor 판단. **floor "?"는 반드시 사진으로 확정**(광고가 parquet/마루를 키워드로 안 써서 "?"로 뜨는 비카펫 보석 많음).
4. 후보면 manifest에 추가.

### 케이스 ② Claude가 리스트 뽑아 추림
1. `python perth_search.py <group> --min N --max N --beds 2 [--type ...] [--floor nocarpet] [--no-red]` → 가격·bd/ba/car·바닥·reno·플래그·listingId.
   - 그룹: `cat`(무료CAT권) / `inner`(자전거·페리권) / `river` / `gallery` / `first3` / `all` / 또는 `"Suburb, WA 60xx"`.
   - **선별 원칙: 애매하면 다 본다.** floor "?"·borderline 미리 컷 금지.
2. 괜찮아 보이는 것마다 `perth_detail.py <id> --imgs`.
3. Claude 판단 → manifest 추가.

### ⚡ 서브에이전트 속도 규칙 (필수 — 사용자 1순위 = 룩북을 최대한 빨리 보기)
> 왜 여기 박았나: 백그라운드 규칙이 사이드 메모리에만 있어 발화 안 돼 한 턴이 20분 걸림(2026-06-16). **파이프라인이 매번 읽는 이 문서에 못박는다.**
1. **2단계 빠른 배포**: ① 판정 점수 *없이* 먼저 — `search→detail→commute→perth_pdf`(자동 6항목+사진만)로 **룩북 즉시 생성·배포**해서 사용자가 바로 본다(~2분). ② 채점 서브에이전트 끝나면 점수 채워 **재배포**. 룩북 먼저, 점수는 따라온다.
2. **채점/사진판정 서브에이전트는 반드시 `run_in_background:true`** — 도는 동안 사용자와 대화. 포그라운드 금지([[feedback_subagent_background]]).
3. **서브에이전트 안에서 `advisor()` 호출 금지** — 정답지 없는 루브릭 채점에 리뷰 사이클 붙으면 분 단위로 느려짐.
4. **에이전트가 결과를 `tools/verdicts_partial_{batch}.json`에 직접 Write** → 본체는 `python perth_merge_verdicts.py`로 머지(수 초). **본체가 손으로 전사 금지**(전사가 ~10분 잡아먹음).

### 케이스 ③ 대량 전수 스캔 ("inner 다 뽑아줘" 류 — 좁히지 말 것)
1. `python perth_search.py <group> --max 700 --beds 2,3 --emit tools/full_manifest.json` → 검색결과 **전부**를 manifest로 저장(RED 제외 X, floor 필터 X).
2. **RED 포함 전건** detail+사진 (출력 폭발은 10건씩 배치, 일 줄이려 요약/추리기 금지):
   `foreach ($id in @(id1,id2,...)) { python tools/perth_detail.py $id --imgs }`
3. `python perth_commute.py tools/full_manifest.json` → 통근 자동(도보가중 comfort_cost·평일 08:00).
4. **1차 배포**: `python perth_pdf.py ... --no-cap` + GitHub 배포로 룩북 먼저 보여줌(점수 없이 사진+자동항목).
5. **채점 서브에이전트 분산(백그라운드)**: 6-8건씩 N개 Agent, 각자 `verdicts_partial_{batch}.json` 직접 Write(위 속도 규칙) → `python perth_merge_verdicts.py` 머지 → `python perth_score.py` → **2차 재배포**.
6. 사용자가 정렬·필터로 직접 셀렉션. **좁히는 건 사용자, Claude는 전수 제공.**

### 공통: 후보 확정 후 (케이스 ①②)
4. `python perth_commute.py <manifest.json>` → 통근 자동(도보가중, 평일 08:00 기준, ⚡시간최단 병기). 단일 id도 가능: `perth_commute.py <listingId>`.
5. `python perth_pdf.py <manifest.json> [verdicts.json] [out.html]` (**즉시·포그라운드**) → 인터랙티브 HTML. Drive 보존 필요 시 `perth_upload.py`만 **백그라운드**.

## 데이터 파일 (스키마 단일화 2026-06-09)

**`full_manifest.json`** (배열) — `perth_search --emit`이 생성, `perth_commute`가 `commute` 채움:
```json
{"id":"444300692","region":"Victoria Park","price":"690","type":"villa",
 "bd":"3","floor":"?","flag":"","commute":"(perth_commute.py가 채움)"}
```
**`verdicts.json`** (객체, optional) — 사진판정 서브에이전트 산출, `perth_pdf` 3번째 인자:
```json
{"444300692": {"floor_photo":"CARP","condition":"보통","notes":"...","tags":["6개월단기"]}}
```
- `floor`(manifest)=광고 1차판정 / `floor_photo`(verdicts)=사진 확정(우선). 제외는 `perth_pdf`가 commute·flag로 **규칙 자동**(하드코딩 X) — 상수 `COMMUTE_CUT`/`WALK_CUT`로 조정.
- ⚠️ 구 `lookbook_manifest.json`(tier/imgs/verdict) 스키마 **폐기** → `_deprecated/`로 이동.

## 산출물 / 경로
- **로컬**: `detail_{id}.json`, `imgs_detail/{id}_NN.jpg`, `perth_lookbook.html/.pdf`
- **Drive**: `호주/부동산/{YYYYMMDD}/{id}_{region}_{price}/`(JSON+사진) + `퍼스_룩북_{date}.pdf`(file id 고정 = 링크 불변, 덮어쓰기). 폴더 ID `1Gp6mnA1CnDWvxWqQadxDtWTGXrdQtgCz`.
- **Doc**: 퍼스 매물 기록 로그 `1-vjcKk0XPrk4JX4Rus4S-lud1sV1duwExk03sfAV6-o` — 세션별 표(appendMarkdown, 룰 `feedback_perth_realestate_session_rule`).

## 키 재발급 / 트러블슈팅
- RapidAPI: rapidapi.com "Realty in AU" 무료 구독 → rapidapi_key.txt.
- Google Maps: console.cloud.google.com → **Directions API 사용설정 + 결제 ON** → API 키(Directions로 제한) → gmaps_key.txt. ("API key invalid"=키 오타/전파지연, "billing"=결제 OFF.)
- Drive 401/만료: .gcreds/token.json 재인증(sync 스킬).
- realestate.com.au 직접 차단 → RapidAPI 프록시로만(가이드 §8).

## 변경 이력 (트러블슈팅)

- **2026-06-09 통근 로직 개편** (`perth_commute.py`): `routes[0]`만 보던 것 → `alternatives=true` 후보 전수 + comfort_cost(탑승분 + 도보분×`WALK_PENALTY`=2.0) 최소를 best로(⚡시간최단 병기) + `departure_time`=다음 평일 08:00 AWST 고정(실행시점 의존 제거) + 단일 listingId 모드. **도보 1km train을 버스보다 잘못 우선하던 버그 해소**(Shenton 24번버스, Wembley 85번버스 전례).
- **2026-06-09 perth_pdf 재설계**: 정적 PDF용(사진 base64·Chrome 렌더·`imgs[4]`·`tier`/`verdict`) → **인터랙티브 HTML**(정렬: 가격·통근·도보 / floor 필터 / 사진 가로스크롤·라이트박스 / 매물→ECU 구글맵 링크). 입력 = `full_manifest.json`(id·price·floor·flag·commute) + **코드 내 `VERDICTS` dict**(사진판정 floor·condition·notes·tags). 구 `imgs`/`tier`/`verdict` manifest 필드 폐기. 새 매물은 `VERDICTS`에 항목 추가.
- **2026-06-09 perth_detail 사진 캡 제거**: `imgs[:14]` → `imgs` 전체(14장 초과 매물 사진 손실 버그).
- **HTML/셸 버그 재발방지**:
  - 사진 `<img>`는 `onerror="this.remove()"`로 실패 처리 — `display:none`+`loading="lazy"` 조합은 viewport 미진입 시 영구 숨김(사진 안 뜸).
  - 환승 판정은 `"·환승" in str` — `"환승"`만 쓰면 `"무환승"`도 매칭돼 무환승이 환승으로 표시됨.
  - 배치 실행은 PowerShell `foreach`(bash `for %i ...` 불가), 스크립트에 넘기는 manifest 경로는 cwd가 루트라 `tools/` 접두사 필요.
- **운영 원칙(2026-06-09 교정)**: 산출물은 손으로 직접 만들지 말고 **기존 스크립트(`perth_pdf.py`)로 생성** 후 렌더링 직접 검증. 매물 선별은 **사전에 좁히지 말고 전수**(출력 폭발은 10건씩 배치). 상세는 `feedback_perth_rental_workflow` 메모리.

## 2026-06-15 대규모 확장 — 존 분류 · 마트 · micro-context · 64점 채점

파이프라인이 4가지 능력을 추가로 얻음. **다음 탐색(2026-10~11) 때 이 섹션부터 읽을 것.**

### ① A/B/C 존 분류 (`perth_pdf.py` 내 `classify_zone`)
- **A = CAT 도보권**(궂은날에도 교통비 $0): commute 첫 탑승수단이 `[Red/Yellow/Blue/Green CAT]` 이면 A
- **B = realestate inner**: A 아니고 검색이 inner인 것
- **C = 기차외곽**: `_src=='outer'`(외곽 suburb 직접 검색). 도어투도어 60분 이내(`COMMUTE_CUT=60`)
- **존별 가격 캡**: A $700 / B $650 / C $600 (하한 = 상한−100). 예산 주 $700 − 2인 교통비 차감 근거.
- 룩북 카드에 존 배지 + 존 필터.

### ② 마트 거리 (`perth_commute.py` 내 `nearest_grocery`)
- Google **Places API**(Nearby Search) + Directions로 가장 가까운 supermarket 거리. **GCP에서 Places API 사용설정 필수**(Directions만으론 REQUEST_DENIED).
- 도보 15분 초과 시 자동으로 대중교통 경로 재계산("🛒 🚌 N분"). manifest의 `grocery` 필드.

### ③ micro-context 서브에이전트 (골목 단위 소음·평판)
- 동네(suburb) vibe로 못 잡는 **이 주소만의** 정보: 간선/철로 인접 소음, 안쪽 골목 여부, 단지 평판.
- 입력 `micro_input.json`(주소·좌표·commute·vibe·사진) → **백그라운드** 배치 서브에이전트 → `micro.json`(noise/noise_reason/micro). 웹검색 허용, 환각 금지(모르면 UNSURE).

### ④ 64점 종합 채점 (`perth_score.py` + `SCORING.md`) — v2 (2026-06-15 개정)
- **자동 6항목**(가격10·통근10·**자전거5**·마트7·소음5·주차2 = 39): `perth_score.py` 계산. 자전거=독립 5점(10분이하 5 / 10분초과 1분당 −0.1 / 30분초과 0). 소음=보통/낮음 5(만점, 안쪽 가점 없음)·간선3·심각1.
- **판정 8항목**(동네2·안전5·면적3·인테리어5·카펫5·detached5·감성2·수납3 = 30): 채점 서브에이전트(`hood_input.json`/`score_input.json`) → verdicts.json(점수+근거+oneliner).
  - **면적=실내만**(마당은 detached 항목 — 이중계산 금지). **안전**=기본4 +게이트/−쇠창살(corridor는 동네로). **동네**=0 corridor / 1 보통 / 2 이쁜동네(분위기).
- 합산·순위·탈락(공용세탁/단기/펫+카펫) = `perth_score.py`. **루브릭 전문 = `SCORING.md`**(설계 닫힘, 사용자 요청 외 재설계 금지).
- **카드 = perth_pdf v2**: 한 줄 평 + collapsible 상세(13항목 점수 분해[통근·마트 raw 경로 하위] + 비교[#N]). 비교 매물 참조는 #순위로.

### 데이터 자산 (휘발 방지 — Drive `CLAUDE/perth-tools/` 백업)
- `verdicts.json` — 사진판정·analysis·micro·11항목 점수+근거 (**핵심, 재생성 수십만 토큰**)
- `micro.json`, `scores_auto.json`, `suburb_vibe.json`(동네 vibe 12개)

### 산출물 배포
- 룩북 HTML → `_deploy/index.html` 빌드 + 사진 동기화 → **GitHub Pages**(public) `https://yesman9692.github.io/perth-lookbook/` (모바일 확인). 상세 `feedback_html_github_autodeploy`.
- 매물 카드 앵커: `#card-{listingId}` — 대화에서 주소+가격으로 링크.

### 분석 포맷 (균일)
매물 analysis는 `🏘 동네 / ✅ 좋은 점 / ⚠️ 체크포인트 / 📐 연식·면적 / 💰 가격 / 🆚 비교` 6섹션 고정.
