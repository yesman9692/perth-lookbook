# -*- coding: utf-8 -*-
# perth_lookbook.py — 퍼스 렌트 룩북 단일 오케스트레이터 (2026-06-16).
# 7개 빌딩블록 스크립트를 순서대로 호출해 search→download→commute→render→judge→merge→deploy
# 전 과정을 사람 개입 0으로 처리한다.
#
# cross-PC sync: Drive 폐기 → git(_deploy repo) 단일화.
#   시작 시 _sync_pull() → _deploy/data/ → tools/ 복사(verdicts+detail).
#   배포 후 _sync_push() → tools/ → _deploy/data/ → git commit+push.
#   --no-sync 으로 끌 수 있음.
#
# usage: python perth_lookbook.py <group> [옵션들...]
# 예:    python perth_lookbook.py cat --max 700 --beds 2,3 --deploy
#        python perth_lookbook.py "South Perth, WA 6151" --max 700 --beds 2,3 --skip-judge
import sys, os, re, json, shutil, subprocess, argparse, time, glob
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ── 경로 (머신 독립: __file__ 기준) ─────────────────────────────────────────
TOOLS  = Path(__file__).parent.resolve()       # D:\my\cowork\tools
DEPLOY = TOOLS / "_deploy"

# ── 도서관 허브(대문) 자동갱신 + Pages 리빌드 (같은 폴더 perth_hub.py) ──────────
# deploy() 가 라운드를 slug 폴더에 배포한 뒤 허브(_deploy/index.html)를 재생성해
# 새 라운드가 도서관 목록에 자동으로 올라가게 하고, push 후 Pages 빌드를 강제 요청해
# "building 멈춤 → 옛 화면 서빙" 문제를 회피한다. best-effort(import 실패해도 계속).
try:
    from perth_hub import build_hub as _build_hub, trigger_pages_build as _trigger_pages_build
except Exception as _hub_e:  # pragma: no cover
    _build_hub = _trigger_pages_build = None
    print("  [deploy] WARN: perth_hub import 실패 — 허브 자동갱신/리빌드 비활성:",
          _hub_e, file=sys.stderr)

# ── 존별 검색 캡 (원래캡 +$50 넉넉히) ────────────────────────────────────────
# all 그룹은 cat+inner 각각 이 캡으로 검색 후 id 기준 dedup 병합
ZONE_SEARCH = {"cat": 750, "inner": 700, "river": 650}

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def _slug(group: str) -> str:
    """group을 URL-안전 슬러그로 변환.
    예: 'South Perth, WA 6151' → 'south-perth'  /  'cat' → 'cat'"""
    s = group.lower()
    s = re.sub(r",?\s*wa\s*\d{4}", "", s)   # ', WA 60xx' 제거
    s = re.sub(r"[^\w\s-]", "", s)           # 특수문자 제거
    s = re.sub(r"[\s,]+", "-", s.strip())    # 공백·콤마 → 하이픈
    s = re.sub(r"-+", "-", s).strip("-")     # 중복 하이픈 정리
    return s or "lookbook"

def _elapsed(t0: float) -> str:
    return "%.0fs" % (time.time() - t0)

def _run(label: str, cmd: list, t0_global: float, fatal: bool = True) -> int:
    """subprocess.run 래퍼. 단계 헤더 출력 + returncode 반환.
    fatal=True 이면 실패 시 exit 1, False 이면 경고만."""
    print("\n[%s] %s ... (%s)" % (label, " ".join(str(c) for c in cmd[:3]), _elapsed(t0_global)))
    sys.stdout.flush()
    r = subprocess.run([str(c) for c in cmd], cwd=str(TOOLS), check=False)
    if r.returncode != 0:
        msg = "[%s] 실패 (returncode=%d)" % (label, r.returncode)
        if fatal:
            print("FATAL:", msg, file=sys.stderr); sys.exit(1)
        else:
            print("WARN:", msg, file=sys.stderr)
    return r.returncode

# ── git sync 헬퍼 ────────────────────────────────────────────────────────────
def _sync_pull() -> None:
    """시작 시 _deploy git pull → data/ 자산을 tools/ 로 복사.
    best-effort: 실패해도 파이프라인은 로컬 캐시로 계속 진행."""
    data_dir = DEPLOY / "data"

    # 1. git pull --rebase (best-effort)
    def _git(args: list) -> tuple:
        r = subprocess.run(["git"] + args, cwd=str(DEPLOY), capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    rc, out, err = _git(["pull", "--rebase"])
    pull_ok = (rc == 0)
    if not pull_ok:
        print("  [sync-pull] WARN: git pull --rebase 실패 — mid-rebase 잔재 정리 후 verdicts/micro 복사 SKIP:", err, file=sys.stderr)
        _git(["rebase", "--abort"])  # mid-rebase 잔재 방지
    else:
        print("  [sync-pull] git pull 완료:", out or "(최신)")

    # 2. data/ 없으면 생성
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "manifests").mkdir(exist_ok=True)
    (data_dir / "detail").mkdir(exist_ok=True)

    # 3. verdicts.json 복사 (_deploy/data/verdicts.json → tools/verdicts.json)
    # pull 실패 시 stale repo본으로 로컬을 덮어쓰면 수십만토큰 자산 손실 위험 — SKIP
    if pull_ok:
        src_v = data_dir / "verdicts.json"
        dst_v = TOOLS / "verdicts.json"
        if src_v.exists():
            # tools/ 에 없거나 _deploy/data/ 것이 더 최신이면 덮어쓰기
            if not dst_v.exists() or src_v.stat().st_mtime > dst_v.stat().st_mtime:
                shutil.copy2(src_v, dst_v)
                print("  [sync-pull] verdicts.json 복사 완료")
            else:
                print("  [sync-pull] verdicts.json 로컬이 최신 — 복사 skip")

        # 4. micro.json 복사
        src_m = data_dir / "micro.json"
        dst_m = TOOLS / "micro.json"
        if src_m.exists():
            if not dst_m.exists() or src_m.stat().st_mtime > dst_m.stat().st_mtime:
                shutil.copy2(src_m, dst_m)
                print("  [sync-pull] micro.json 복사 완료")
    else:
        print("  [sync-pull] verdicts.json / micro.json 복사 SKIP — pull 실패(로컬이 최신일 수 있음)")

    # 5. detail/*.json → tools/ (없는 것만 복사 — 기존 로컬 캐시 보존, pull 실패해도 안전)
    detail_dir = data_dir / "detail"
    n_copied = 0
    for src_d in detail_dir.glob("detail_*.json"):
        dst_d = TOOLS / src_d.name
        if not dst_d.exists():
            shutil.copy2(src_d, dst_d); n_copied += 1
    if n_copied:
        print("  [sync-pull] detail 복사: %d건 신규" % n_copied)
    else:
        print("  [sync-pull] detail: 신규 없음")


def _sync_push(slug: str, manifest_path: Path) -> bool:
    """배포 후 tools/ 자산을 _deploy/data/ 에 복사하고 git commit+push.
    대상: verdicts.json, micro.json, manifest, detail_{id}.json.
    best-effort: git 실패해도 파이프라인은 계속.
    반환: True=성공, False=실패(수동 push 필요)"""
    data_dir = DEPLOY / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "manifests").mkdir(exist_ok=True)
    (data_dir / "detail").mkdir(exist_ok=True)

    # 1. verdicts.json 복사
    src_v = TOOLS / "verdicts.json"
    if src_v.exists():
        shutil.copy2(src_v, data_dir / "verdicts.json")
        print("  [sync-push] verdicts.json 복사 완료")

    # 2. micro.json 복사
    src_m = TOOLS / "micro.json"
    if src_m.exists():
        shutil.copy2(src_m, data_dir / "micro.json")
        print("  [sync-push] micro.json 복사 완료")

    # 3. manifest 복사 → _deploy/data/manifests/
    if manifest_path.exists():
        dst_man = data_dir / "manifests" / manifest_path.name
        shutil.copy2(manifest_path, dst_man)
        print("  [sync-push] manifest 복사 완료: %s" % dst_man.name)

        # 4. manifest의 id별 detail_{id}.json 복사 → _deploy/data/detail/ (멱등)
        try:
            man = json.load(open(manifest_path, encoding="utf-8"))
            ids = [e["id"] for e in man]
        except Exception as e:
            print("  [sync-push] WARN: manifest 읽기 실패 — detail 복사 skip: %s" % e, file=sys.stderr)
            ids = []

        n_copied = 0
        for lid in ids:
            src_d = TOOLS / ("detail_%s.json" % lid)
            if src_d.exists():
                dst_d = data_dir / "detail" / src_d.name
                shutil.copy2(src_d, dst_d); n_copied += 1
        print("  [sync-push] detail 복사: %d건" % n_copied)

    # 5. git add data/ → commit → pull --rebase → push
    def _git(args: list) -> tuple:
        r = subprocess.run(["git"] + args, cwd=str(DEPLOY), capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    try:
        _git(["add", "--", "data/"])
        rc, out, err = _git(["status", "--porcelain"])
        if not out.strip():
            print("  [sync-push] data/ 변경사항 없음 — commit skip")
            return True

        date_str = datetime.now().strftime("%Y-%m-%d")
        commit_msg = "sync: %s data 자산 %s" % (slug, date_str)
        rc, out, err = _git(["commit", "-m", commit_msg])
        if rc != 0:
            print("  [sync-push] WARN: commit 실패:", err, file=sys.stderr); return False
        print("  [sync-push] commit:", out)

        rc, _, err = _git(["pull", "--rebase"])
        if rc != 0:
            # commit 후 pull 실패 → orphan 커밋 방지: rebase abort + commit 취소(스테이징 보존)
            print("  [sync-push] WARN: pull --rebase 실패 — rebase abort + commit 취소(스테이징 보존):", err, file=sys.stderr)
            _git(["rebase", "--abort"])
            _git(["reset", "--soft", "HEAD~1"])
            return False

        rc, _, err = _git(["push", "--set-upstream", "origin", "master"])
        if rc != 0:
            print("  [sync-push] WARN: push 실패:", err, file=sys.stderr); return False
        print("  [sync-push] push 완료 — _deploy/data/ 동기화 완료")
        return True
    except Exception as e:
        print("  [sync-push] WARN: 예외 발생 — git sync skip:", e, file=sys.stderr)
        return False


# ── deploy 함수 ──────────────────────────────────────────────────────────────
def deploy(slug: str, html_path: Path, label: str, manifest_path: Path) -> str | None:
    """cat700 패턴: _deploy/<slug>/index.html + imgs_detail/ 복사 → git push.
    메인 _deploy/index.html 은 절대 건드리지 않음. best-effort(git 실패해도 계속).
    반환값: GitHub Pages URL 또는 None"""
    slug_dir = DEPLOY / slug
    # [H-1] slug 경로 탈출 방어
    try:
        slug_dir.resolve().relative_to(DEPLOY.resolve())
    except ValueError:
        raise SystemExit("FATAL: slug가 _deploy 외부를 가리킴 — 중단")
    imgs_dst  = slug_dir / "imgs_detail"
    slug_dir.mkdir(parents=True, exist_ok=True)
    imgs_dst.mkdir(parents=True, exist_ok=True)

    # HTML 복사
    dst_html = slug_dir / "index.html"
    shutil.copy2(html_path, dst_html)
    print("  [deploy] HTML → %s" % dst_html)

    # manifest에서 id 목록 추출 → imgs_detail/<id>_*.jpg 복사
    try:
        man = json.load(open(manifest_path, encoding="utf-8"))
        ids = [e["id"] for e in man]
    except Exception as e:
        print("  [deploy] WARN: manifest 읽기 실패 — 사진 복사 skip: %s" % e, file=sys.stderr)
        ids = []

    imgs_src = TOOLS / "imgs_detail"
    copied = skipped = 0
    for lid in ids:
        for src in imgs_src.glob("%s_*.jpg" % lid):
            dst = imgs_dst / src.name
            if dst.exists() and dst.stat().st_size == src.stat().st_size:
                skipped += 1; continue
            shutil.copy2(src, dst); copied += 1
    print("  [deploy] 사진 복사: %d 신규 / %d skip(이미 있음)" % (copied, skipped))

    # 라운드를 도서관 허브(대문 _deploy/index.html)에 자동 반영 — best-effort
    if _build_hub:
        try:
            _build_hub(DEPLOY)
        except Exception as e:
            print("  [deploy] WARN: 허브 재생성 실패(계속):", e, file=sys.stderr)

    # git 배포
    date_str = datetime.now().strftime("%Y-%m-%d")
    commit_msg = "auto: %s 룩북 %s %s" % (slug, label, date_str)

    def _git(args: list) -> tuple[int, str, str]:
        r = subprocess.run(["git"] + args, cwd=str(DEPLOY), capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    try:
        # 슬러그 하위 + 허브(index.html) staging.
        # ([C-1] 원래는 메인 index.html 을 "완성된 룩북" 보호 차원에서 제외했으나,
        #  이제 루트 index.html 은 룩북이 아니라 slug 폴더 목록만 나열하는 허브다.
        #  축소/깨진 라운드여도 허브는 그 slug 를 "있는 그대로의 건수"로 나열할 뿐이라
        #  라이브 룩북을 훼손하지 않는다. 따라서 index.html 도 함께 커밋한다.)
        # resolve() 사용: symlink 환경에서 relative_to ValueError 방지
        _git(["add", "--", str(slug_dir.resolve().relative_to(DEPLOY.resolve())), "index.html"])
        rc, out, err = _git(["status", "--porcelain"])
        if not out.strip():
            print("  [deploy] 변경사항 없음 — commit skip")
        else:
            rc, out, err = _git(["commit", "-m", commit_msg])
            if rc != 0:
                print("  [deploy] WARN: commit 실패:", err, file=sys.stderr)
                return None
            print("  [deploy] commit:", out)

        # [L-2] pull --rebase 실패 시 abort하고 배포 skip
        rc_pull, _, err_pull = _git(["pull", "--rebase"])
        if rc_pull != 0:
            print("  [deploy] WARN: pull --rebase 실패 — rebase abort 후 배포 skip:", err_pull, file=sys.stderr)
            _git(["rebase", "--abort"])
            return None

        # [e2e 버그1] upstream 트래킹 보장 — 처음이면 설정, 이후도 정상
        rc, out, err = _git(["push", "--set-upstream", "origin", "master"])
        if rc != 0:
            print("  [deploy] WARN: push 실패:", err, file=sys.stderr)
            return None
        print("  [deploy] push 완료")
        # Pages 빌드 정체("building" 멈춤 → 옛 화면 서빙) 회피 — 강제 리빌드 요청(best-effort)
        if _trigger_pages_build:
            try:
                _trigger_pages_build()
            except Exception as e:
                print("  [deploy] WARN: Pages 리빌드 요청 실패:", e, file=sys.stderr)
        url = "https://yesman9692.github.io/perth-lookbook/%s/" % slug
        print("  [deploy] URL:", url)
        return url
    except Exception as e:
        print("  [deploy] WARN: 예외 발생 — git 배포 skip:", e, file=sys.stderr)
        return None

# ── argparse ─────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(
    description="퍼스 렌트 룩북 단일 오케스트레이터 — search→download→commute→render→judge→merge→deploy")
ap.add_argument("group", help="검색 그룹(cat/inner/river/first3/gallery/all) 또는 'Suburb, WA 60xx'")
# search 필터 패스스루
ap.add_argument("--max",   type=int, default=700,  help="최고 임대료 $/주")
ap.add_argument("--min",   type=int, default=0,    help="최저 임대료 $/주")
ap.add_argument("--beds",  default="2,3",          help="침실 수(쉼표 구분, any 가능)")
ap.add_argument("--type",  default="",             help="매물 유형 필터 (unit,apartment,house,villa,townhouse)")
ap.add_argument("--floor", default="any",          choices=["any", "bare", "nocarpet"])
ap.add_argument("--no-red", action="store_true",   help="RED 플래그 매물 제외")
# pdf 패스스루
ap.add_argument("--no-cap", action="store_true",   help="존 가격 캡 해제 (perth_pdf --no-cap)")
# 배포
ap.add_argument("--deploy", action="store_true",   help="GitHub Pages 배포")
ap.add_argument("--slug",   default="",            help="배포 슬러그 (미지정 시 group에서 자동 생성)")
# 병렬화
ap.add_argument("--workers",      type=int, default=6, help="perth_download workers")
ap.add_argument("--cap",          type=int, default=14, help="매물당 사진 장수 cap")
ap.add_argument("--judge-workers", type=int, default=3)
ap.add_argument("--judge-cap",    type=int, default=14)   # B: 전수 사진(침실·카펫은 9-14번 사진에 있음)
ap.add_argument("--judge-model",  default="opus")          # G: 격리가 user settings의 모델 기본을 떨구므로 핀 필수
# skip 플래그
ap.add_argument("--skip-judge",  action="store_true", help="judge 단계 스킵 (claude -p 미호출)")
ap.add_argument("--no-sync",     action="store_true", help="git sync pull/push 끄기 (오프라인/빠른 로컬 실행용)")
# 하위호환 deprecated 플래그 (무시됨 — 예전 Drive 기반 sync가 git으로 교체됨)
ap.add_argument("--no-drive-cache",   action="store_true", help=argparse.SUPPRESS)
ap.add_argument("--no-drive-push",    action="store_true", help=argparse.SUPPRESS)
ap.add_argument("--no-archive",       action="store_true", help=argparse.SUPPRESS)
ap.add_argument("--no-drive",         action="store_true", help=argparse.SUPPRESS)

args = ap.parse_args()

slug  = args.slug or _slug(args.group)
t0    = time.time()

manifest_path  = TOOLS / ("auto_%s_manifest.json" % slug)
html_path      = TOOLS / ("%s.html" % slug)
partial_path   = TOOLS / ("verdicts_partial_%s.json" % slug)
verdicts_path  = TOOLS / "verdicts.json"
empty_micro    = TOOLS / "_empty_micro.json"

print("=" * 60)
print("perth_lookbook.py — %s (slug=%s)" % (args.group, slug))
print("=" * 60)

# ── sync pull (검색 전, 다른 PC가 올린 verdicts+detail 내려받기) ───────────────
if not args.no_sync:
    print("\n[0/7] sync-pull (git → tools/) ... (%s)" % _elapsed(t0))
    sys.stdout.flush()
    _sync_pull()
else:
    print("\n[0/7] sync-pull — SKIP (--no-sync 지정) (%s)" % _elapsed(t0))

# ── 단계 1: search ────────────────────────────────────────────────────────────
def _search_passthrough_flags() -> list:
    """--type/--floor/--no-red 패스스루 플래그를 반환."""
    flags = []
    if args.type:
        flags += ["--type", args.type]
    if args.floor != "any":
        flags += ["--floor", args.floor]
    if args.no_red:
        flags.append("--no-red")
    return flags

def _make_search_cmd(target: str, max_price: int, emit_path: Path) -> list:
    """perth_search.py 호출 인자 목록을 조립해 반환."""
    cmd = [
        sys.executable, str(TOOLS / "perth_search.py"),
        target,
        "--min", str(args.min), "--max", str(max_price),
        "--beds", args.beds,
        "--emit", str(emit_path),
    ]
    cmd += _search_passthrough_flags()
    return cmd

if args.group == "all":
    # all: cat($750) + inner($700) 각각 검색 → id 기준 dedup 병합
    tmp_cat   = TOOLS / ("auto_%s_cat_tmp.json"   % slug)
    tmp_inner = TOOLS / ("auto_%s_inner_tmp.json" % slug)

    print("\n[1/7] search (all: cat+inner 존별 분리) ... (%s)" % _elapsed(t0))
    _run("[1/7] search cat($%d)"   % ZONE_SEARCH["cat"],
         _make_search_cmd("cat",   ZONE_SEARCH["cat"],   tmp_cat),   t0, fatal=True)
    _run("[1/7] search inner($%d)" % ZONE_SEARCH["inner"],
         _make_search_cmd("inner", ZONE_SEARCH["inner"], tmp_inner), t0, fatal=True)

    # dedup 병합: id 기준, cat 먼저 순서 유지
    def _load_tmp(p: Path) -> list:
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return []

    cat_rows   = _load_tmp(tmp_cat)
    inner_rows = _load_tmp(tmp_inner)
    seen_ids: set = set()
    merged: list = []
    for row in cat_rows + inner_rows:
        rid = row.get("id")
        if rid and rid not in seen_ids:
            seen_ids.add(rid); merged.append(row)

    json.dump(merged, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 임시 파일 정리
    for p in (tmp_cat, tmp_inner):
        try: p.unlink()
        except Exception: pass

    print("  [1/7] 병합 결과: cat %d건 + inner %d건 → dedup %d건" % (
        len(cat_rows), len(inner_rows), len(merged)))

elif args.group in ZONE_SEARCH:
    # 단일 존 그룹(cat/inner/river): 존 전용 캡 사용
    zone_max = ZONE_SEARCH[args.group]
    print("\n[1/7] search (%s, 존캡 $%d) ... (%s)" % (args.group, zone_max, _elapsed(t0)))
    _run("[1/7] search", _make_search_cmd(args.group, zone_max, manifest_path), t0, fatal=True)

else:
    # first3 / gallery / 단일 suburb / 기타 → 사용자 --max 그대로 사용
    _run("[1/7] search", _make_search_cmd(args.group, args.max, manifest_path), t0, fatal=True)

# manifest 로드 → 0건이면 조기 종료
try:
    manifest = json.load(open(manifest_path, encoding="utf-8"))
except Exception:
    manifest = []
if not manifest:
    print("\n매물 0건 — 파이프라인 조기 종료 (필터를 완화하거나 다른 group을 시도하세요).")
    sys.exit(0)
print("  → %d건 매물 검색됨" % len(manifest))

# ── 단계 2: download ─────────────────────────────────────────────────────────
# detail_{id}.json 로컬 캐시는 sync-pull 단계에서 이미 _deploy/data/detail/로부터 복사됨.
# Drive 아카이브 층 불필요 — 로컬 캐시 → RapidAPI 2단계만 사용.
_run("[2/7] download", [
    sys.executable, str(TOOLS / "perth_download.py"),
    str(manifest_path),
    "--workers", str(args.workers),
    "--cap", str(args.cap),
], t0, fatal=True)

# ── 단계 3: commute ──────────────────────────────────────────────────────────
_run("[3/7] commute", [
    sys.executable, str(TOOLS / "perth_commute.py"),
    str(manifest_path),
], t0, fatal=True)

# ── 단계 4: 1차 렌더+배포 (verdicts 없이) ───────────────────────────────────
pdf_cmd_1 = [
    sys.executable, str(TOOLS / "perth_pdf.py"),
    str(manifest_path),
    str(html_path),
]
if args.no_cap:
    pdf_cmd_1.append("--no-cap")
_run("[4/7] pdf(1차)", pdf_cmd_1, t0, fatal=True)

url_1 = None
if args.deploy:
    print("  [4/7] 1차 배포 중 ...")
    url_1 = deploy(slug, html_path, "1차", manifest_path)

# ── 단계 5: 로컬 verdicts 캐시 준비 ─────────────────────────────────────────
# Drive 캐시 단계 폐기 — sync-pull에서 git을 통해 verdicts.json이 이미 최신으로 동기화됨.
# perth_drive_cache.py 는 레거시 보존용으로 파일만 유지, 더 이상 호출하지 않음.
print("\n[5/7] 로컬 verdicts 캐시 확인 ... (%s)" % _elapsed(t0))
fallback_names = ["verdicts.json", "verdicts_batch1.json", "verdicts_batch2.json", "verdicts_batch3.json"]
existing_caches = [n for n in fallback_names if (TOOLS / n).exists()]
cache_paths = ",".join(existing_caches)
if cache_paths:
    print("  [5/7] 캐시 준비완료 (git sync 경유):", cache_paths)
else:
    print("  [5/7] 캐시 없음 — 신규 판정만 진행")

# ── 단계 6: judge ────────────────────────────────────────────────────────────
if not args.skip_judge:
    judge_cmd = [
        sys.executable, str(TOOLS / "perth_judge.py"),
        str(manifest_path),
        "--out", str(partial_path),
        "--workers", str(args.judge_workers),
        "--cap", str(args.judge_cap),
        "--model", args.judge_model,
    ]
    if cache_paths:
        judge_cmd += ["--cache", cache_paths]
    _run("[6/7] judge", judge_cmd, t0, fatal=True)
else:
    print("\n[6/7] judge — SKIP (--skip-judge 지정) (%s)" % _elapsed(t0))
    # partial 파일이 없으면 빈 dict로 생성해 merge가 깨지지 않게
    if not partial_path.exists():
        json.dump({}, open(partial_path, "w", encoding="utf-8"))

# ── 단계 7: merge + score + 2차 렌더 + 배포 ─────────────────────────────────
print("\n[7/7] merge+score+pdf(2차) ... (%s)" % _elapsed(t0))
sys.stdout.flush()

# 7a. merge — slug 한정 partial만 명시 머지(blind glob 금지: 다른 run/배치 stale partial 오염 차단)
_run("[7/7a] merge", [
    sys.executable, str(TOOLS / "perth_merge_verdicts.py"),
    str(partial_path),
], t0, fatal=True)

# 7b. score — 실패해도 파이프라인 계속 (판정 키 없는 매물은 score가 자동 skip)
micro_path = TOOLS / "micro.json"
if not micro_path.exists():
    json.dump({}, open(empty_micro, "w", encoding="utf-8"), ensure_ascii=False)
    micro_path = empty_micro
    print("  [7/7b] micro.json 없음 — 빈 micro 사용 (소음 점수=기본값 5)")

try:
    rc = _run("[7/7b] score", [
        sys.executable, str(TOOLS / "perth_score.py"),
        str(manifest_path),
        str(verdicts_path),
        str(micro_path),
    ], t0, fatal=False)
    if rc != 0:
        print("  [score] 경고: score 실패(판정 키 없는 매물만 있을 수 있음) — 렌더는 계속")
except Exception as e:
    print("  [score] WARN 예외:", e, file=sys.stderr)

# 7c. 2차 렌더 (verdicts.json + score 반영)
pdf_cmd_2 = [
    sys.executable, str(TOOLS / "perth_pdf.py"),
    str(manifest_path),
    str(verdicts_path),
    str(html_path),
]
if args.no_cap:
    pdf_cmd_2.append("--no-cap")
_run("[7/7c] pdf(2차)", pdf_cmd_2, t0, fatal=True)

# 7d. 배포
url_2 = None
if args.deploy:
    print("  [7/7d] 2차 배포 중 ...")
    url_2 = deploy(slug, html_path, "2차", manifest_path)

# 7e. git sync push — data/ 자산을 _deploy repo에 커밋+push (best-effort)
sync_push_ok: bool | None = None
if not args.no_sync:
    print("  [7/7e] sync-push (tools/ → _deploy/data/ → git push) ...")
    sync_push_ok = _sync_push(slug, manifest_path)
else:
    print("  [7/7e] sync-push — SKIP (--no-sync 지정)")

# ── 최종 요약 ────────────────────────────────────────────────────────────────
elapsed = time.time() - t0
print("\n" + "=" * 60)
print("완료  총 %.0f초" % elapsed)
print("  매물 수       : %d건" % len(manifest))
print("  manifest      : %s" % manifest_path)
print("  HTML          : %s" % html_path)
if verdicts_path.exists():
    try:
        v = json.load(open(verdicts_path, encoding="utf-8"))
        scored = sum(1 for vd in v.values() if "score_total" in vd)
        print("  verdicts.json : %d 매물 (채점완료 %d건)" % (len(v), scored))
    except Exception:
        pass
if args.deploy:
    final_url = url_2 or url_1
    if final_url:
        print("  GitHub Pages  : %s" % final_url)
    else:
        print("  GitHub Pages  : 배포 실패 (수동 push 필요)")
if sync_push_ok is True:
    print("  데이터 git sync: 성공")
elif sync_push_ok is False:
    print("  데이터 git sync: 실패 (수동 push 필요)")
# sync_push_ok is None → --no-sync 지정, 출력 생략
print("=" * 60)
