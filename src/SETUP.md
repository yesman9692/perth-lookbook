# 퍼스 렌트 파이프라인 — 다른 PC 셋업 가이드

이 폴더(Drive `CLAUDE/perth-tools/`)는 퍼스 매물 탐색 5종 파이프라인의 **백업본**이다.
집↔사무실 PC 어디서든 복원해서 쓸 수 있게 한다. ⚠️ **API 키는 시크릿이라 Drive에 올리지 않는다** — 각 PC에서 로컬 생성.

## 복원 절차

1. **스크립트 배치**: 이 폴더의 `perth_*.py` + `README.md`를 로컬 `D:\my\cowork\tools\` 에 복사.

2. **의존성 설치**:
   ```
   pip install curl_cffi google-api-python-client google-auth-oauthlib google-auth requests
   ```
   + 룩북 렌더 확인용 Chrome/Edge (headless).

3. **API 키 로컬 생성** (Drive에 없음 — 직접 발급해서 `tools/`에 텍스트 파일로):
   - `rapidapi_key.txt` — RapidAPI "Realty in AU" 구독 키 (무료 500콜/월). 매물 검색·상세.
   - `gmaps_key.txt` — Google Maps API 키. **Directions API + Places API 둘 다 사용설정 + 결제 ON** 필요. (통근=Directions, 마트거리=Places Nearby). GCP 프로젝트 "Analyzing Tomcat Log".

4. **Drive 인증** (업로드용): `~/.claude/projects/D--my-cowork/.gcreds/` (credentials.json + token.json). sync 스킬과 공유. 없으면 sync-pull 계열로 복원.

5. **launch.json** (룩북 렌더 확인용): 로컬 `.claude/launch.json` 에 아래 설정:
   ```json
   {"version":"0.0.1","configurations":[{"name":"perth-lookbook","runtimeExecutable":"python","runtimeArgs":["-m","http.server","8777","--directory","tools"],"port":8777}]}
   ```

## 파이프라인 흐름

```
perth_search → perth_detail(+사진) → perth_commute(통근+마트) → [사진판정·micro 서브에이전트] → perth_pdf(룩북) → perth_upload(Drive)
```

상세 워크플로·판단기준은 `README.md` 참조. 메모리: `perth-rental-workflow-rules`, `user-perth-rental-preferences`, `feedback_listing_pocket_purpose`.

## 재사용 자산 (같이 백업)

- `suburb_vibe.json` — 동네별 분위기 누적 (12개 동네). 새 세션에서 재활용, 새 동네만 추가.
