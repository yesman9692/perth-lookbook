# -*- coding: utf-8 -*-
# perth_drive_cache.py — 렌트 룩북 judge 단계 전, 구글 드라이브에서 verdicts 캐시를 내려받아
# 다른 PC에서 판정된 매물을 재사용한다(토큰·시간 절약). best-effort: 드라이브 실패 시
# 로컬 캐시만으로 진행, 절대 non-zero exit 안 함.
#
# stdout 마지막 줄 = perth_judge.py --cache 에 넘길 콤마 결합 경로 문자열
# stderr = 진행 로그 (stdout 최종 라인과 섞이지 않음)
#
# usage: python perth_drive_cache.py [--tools-dir PATH]
#   출력 예: .drive_cache/combined_verdicts.json,.drive_cache/verdicts.json,verdicts.json
import os, sys, json, argparse
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── 인증 (perth_upload.py 동일 패턴 재사용) ────────────────────────────────
HOME = Path(os.path.expanduser("~"))
CRED_DIR = HOME / ".claude" / "projects" / "D--my-cowork" / ".gcreds"
CRED_PATH, TOKEN_PATH = CRED_DIR / "credentials.json", CRED_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

DRIVE_FOLDER_ID = "1Uae6hsarR8PyhNrrX21MvDs92yfobqkH"  # CLAUDE/perth-tools/

# 드라이브에서 받을 파일 목록 (완전한 것 우선 순서)
DRIVE_TARGETS = [
    "combined_verdicts.json",
    "verdicts.json",
    "existing_verdicts.json",
    "cat700_verdicts.json",
]

# judge가 쓰는 로컬 캐시 파일들 (TOOLS 기준 상대경로)
LOCAL_CACHE_FILES = [
    "verdicts.json",
    "verdicts_batch1.json",
    "verdicts_batch2.json",
    "verdicts_batch3.json",
]


def _log(msg: str):
    """진행 로그는 stderr 로 — stdout 최종 라인과 분리."""
    print(msg, file=sys.stderr, flush=True)


def _load_token():
    data = json.load(open(TOKEN_PATH, encoding="utf-8"))
    if "client_secret" not in data and CRED_PATH.exists():
        inst = (json.load(open(CRED_PATH, encoding="utf-8")).get("installed")
                or json.load(open(CRED_PATH, encoding="utf-8")).get("web") or {})
        data.setdefault("client_id", inst.get("client_id"))
        data.setdefault("client_secret", inst.get("client_secret"))
        data.setdefault("token_uri", inst.get("token_uri", "https://oauth2.googleapis.com/token"))
        data.setdefault("refresh_token", data.get("refreshToken"))
    return data


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(_load_token(), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        try:
            open(TOKEN_PATH, "w", encoding="utf-8").write(creds.to_json())
        except Exception:
            pass
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _parse_drive_time(t: str) -> datetime:
    """Drive RFC 3339 → aware datetime."""
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def _local_mtime(path: Path) -> datetime:
    """로컬 파일 mtime → aware UTC datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def fetch_drive_verdicts(cache_dir: Path) -> list[str]:
    """드라이브 폴더를 list 해서 DRIVE_TARGETS 중 있는 파일 다운로드.
    멱등: Drive modifiedTime > 로컬 mtime 일 때만 내려받음.
    반환: cache_dir 기준 상대경로 문자열 리스트 (완전한 것 우선)."""
    try:
        svc = _service()
        _log("[drive] 서비스 연결 완료")
    except Exception as e:
        _log(f"[drive] 인증 실패 — 로컬 캐시만 사용: {e}")
        return []

    # 폴더 내 파일 목록 (name, id, modifiedTime)
    try:
        q = f"'{DRIVE_FOLDER_ID}' in parents and trashed=false"
        res = svc.files().list(
            q=q,
            fields="files(id,name,modifiedTime)",
            pageSize=50,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files_in_folder = {f["name"]: f for f in res.get("files", [])}
        _log(f"[drive] 폴더 파일 {len(files_in_folder)}개 확인: {list(files_in_folder.keys())}")
    except Exception as e:
        _log(f"[drive] 폴더 list 실패 — 로컬 캐시만 사용: {e}")
        return []

    downloaded: list[str] = []
    for target in DRIVE_TARGETS:
        if target not in files_in_folder:
            _log(f"[drive] {target} — 폴더에 없음, skip")
            continue
        meta = files_in_folder[target]
        local_path = cache_dir / target
        drive_mtime = _parse_drive_time(meta["modifiedTime"])

        # 멱등 체크: 로컬이 최신이면 skip
        if local_path.exists():
            local_mt = _local_mtime(local_path)
            if drive_mtime <= local_mt:
                _log(f"[drive] {target} — skip(최신, drive={drive_mtime.strftime('%Y-%m-%dT%H:%M')} local={local_mt.strftime('%Y-%m-%dT%H:%M')})")
                downloaded.append(str(local_path))
                continue

        # 다운로드
        try:
            from googleapiclient.http import MediaIoBaseDownload
            import io
            request = svc.files().get_media(
                fileId=meta["id"], supportsAllDrives=True
            )
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = dl.next_chunk()
            local_path.write_bytes(buf.getvalue())
            _log(f"[drive] {target} — 다운로드 완료 ({len(buf.getvalue()):,} bytes)")
            downloaded.append(str(local_path))
        except Exception as e:
            _log(f"[drive] {target} 다운로드 실패: {e}")

    return downloaded


def _relative(path: Path, base: Path) -> str:
    """base 기준 상대경로 (Path.relative_to 보장 안 되면 절대경로 fallback)."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def count_keys(path: Path) -> int | None:
    """verdicts json 파일의 최상위 키 수 (매물 id 수). 실패 시 None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return len(data)
        if isinstance(data, list):
            return len(data)
        return None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Drive verdicts 캐시 내려받기 (perth_judge 전처리)")
    ap.add_argument(
        "--tools-dir",
        default=None,
        help="TOOLS 디렉토리 경로 (기본: 스크립트 위치)",
    )
    args = ap.parse_args()

    tools_dir = Path(args.tools_dir) if args.tools_dir else Path(__file__).parent
    cache_dir = tools_dir / ".drive_cache"
    cache_dir.mkdir(exist_ok=True)
    _log(f"[cache] 캐시 디렉토리: {cache_dir}")

    # ── 드라이브 다운로드 (best-effort) ────────────────────────────────────
    drive_paths: list[str] = []
    try:
        downloaded = fetch_drive_verdicts(cache_dir)
        # 완전한 것 우선 순서(DRIVE_TARGETS 순) 유지하며 상대경로 변환
        path_set = {Path(p).name: Path(p) for p in downloaded}
        for target in DRIVE_TARGETS:
            if target in path_set:
                drive_paths.append(_relative(path_set[target], tools_dir))
    except Exception as e:
        _log(f"[cache] 드라이브 단계 예외 — 로컬 전용으로 계속: {e}")

    # ── 로컬 캐시 (TOOLS_DIR 기준) ────────────────────────────────────────
    local_paths: list[str] = []
    for name in LOCAL_CACHE_FILES:
        p = tools_dir / name
        if p.exists():
            # drive_cache 에 같은 이름이 이미 있으면 중복 추가 안 함
            rel = _relative(p, tools_dir)
            if rel not in drive_paths:
                local_paths.append(rel)

    all_paths = drive_paths + local_paths
    _log(f"[cache] 최종 캐시 경로 {len(all_paths)}개: {all_paths}")

    # ── cross-PC 가치 확인: drive verdicts vs 로컬 verdicts 키 수 비교 ────
    drive_v = cache_dir / "verdicts.json"
    local_v = tools_dir / "verdicts.json"
    if drive_v.exists() and local_v.exists() and drive_v != local_v:
        dc = count_keys(drive_v)
        lc = count_keys(local_v)
        if dc is not None and lc is not None:
            diff = dc - lc
            sign = f"+{diff}" if diff >= 0 else str(diff)
            _log(
                f"[cache] cross-PC 가치: drive verdicts={dc}개 / local verdicts={lc}개 "
                f"({sign} — drive가 {'더 많음' if diff > 0 else '같거나 적음'})"
            )
    elif drive_v.exists() and not local_v.exists():
        dc = count_keys(drive_v)
        _log(f"[cache] cross-PC: drive verdicts={dc}개 (로컬 없음 — 드라이브 전용)")

    # ── stdout: judge 에 넘길 콤마 경로 문자열 (단 한 줄) ─────────────────
    # [H-3] CACHE_PATHS: prefix — 라이브러리 stdout 혼입 방어
    print("CACHE_PATHS:" + (",".join(all_paths) if all_paths else ""))


if __name__ == "__main__":
    main()
