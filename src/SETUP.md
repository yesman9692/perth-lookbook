# 퍼스 렌트 파이프라인 — 새 PC 셋업 가이드 (머신 독립)

이 폴더(Drive `CLAUDE/perth-tools/`)는 퍼스 매물 5종 파이프라인 + 채점 시스템의 **백업본**이다.
집↔사무실 어디서든 복원해서 쓴다. ⚠️ **API 키는 시크릿이라 Drive에 안 올린다** — 각 PC 로컬 생성.
스크립트는 경로를 하드코딩하지 않고 `__file__` 기준으로 자동 감지하므로 **어느 경로의 `tools/`에 둬도 동작**한다.

## 복원 절차

1. **스크립트·문서·데이터 배치**: 이 폴더의 `perth_*.py` + `build_combined.py` + `merge_irj.py` + `backup_tools.py` + `*.md` + 재사용 데이터(`verdicts.json`·`micro.json`·`suburb_vibe.json`·`scores_auto.json`·`combined_*`·`cat700_*`)를 로컬 프로젝트의 `tools/` 폴더에 복사. (Claude가 `google-docs` MCP `downloadFile`로 받아도 됨.)

2. **의존성**:
   ```
   pip install curl_cffi google-api-python-client google-auth-oauthlib google-auth requests
   ```
   + 룩북 렌더 확인용 Chrome/Edge. + 배포용 `gh` CLI(`winget install GitHub.cli` → `gh auth login`).

3. **API 키 로컬 생성** (Drive에 없음 — `tools/`에 텍스트 파일로):
   - `rapidapi_key.txt` — RapidAPI "Realty in AU" 키 (무료 500콜/월). 매물 검색·상세.
   - `gmaps_key.txt` — Google Maps 키. **Directions API + Places API 둘 다 사용설정 + 결제 ON** 필요. (통근=Directions, 마트·편의 밀집도=Places Nearby).

4. **Drive 인증** (업로드·백업용): `~/.claude/projects/<encoded-cowork-path>/.gcreds/` (credentials.json + token.json). sync 스킬과 공유. `perth_upload.py`/`backup_tools.py`가 `D--cowork`/`D--my-cowork` 자동 탐지. 없으면 sync-pull 계열로 복원.

5. **launch.json** (룩북 렌더 확인용, 선택): `.claude/launch.json` 에 python http.server 설정.

## 파이프라인 흐름
```
perth_search → perth_detail(+사진) → perth_commute(통근+편의 amenity) → [사진판정·micro 서브에이전트] → perth_score(61점) → perth_pdf(룩북 --nocap) → perth_upload/배포
```
- 통합 재채점(기존+신규 한 순위): `build_combined.py` → commute → perth_score → perth_pdf --nocap.
- 채점 루브릭 전문 = `SCORING.md` (61점 v3). 워크플로 = `README.md`.
- 자산 백업: `python tools/backup_tools.py` (이 폴더로 update/create, 멱등).

## 재사용 데이터 자산 (같이 백업, 재생성 수십만 토큰)
- `verdicts.json`·`combined_verdicts.json` — 사진판정·점수+근거+parts
- `micro.json`·`combined_micro.json` — 소음·골목
- `suburb_vibe.json` — 동네별 분위기 누적
