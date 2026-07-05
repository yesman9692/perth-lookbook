# -*- coding: utf-8 -*-
# perth_hub.py — 퍼스 룩북 "라운드 아카이브" 대문(허브) index.html 생성기.
#
# 왜 있나: _deploy/index.html(레포 루트)은 개별 룩북이 아니라 라운드 목록을 보여주는
#   허브다. perth_lookbook.py 의 deploy() 가 새 라운드를 slug 폴더에 배포한 뒤 이 모듈의
#   build_hub() 를 호출해 허브를 재생성하므로, 새 라운드가 자동으로 도서관 목록에 올라간다.
#   또 trigger_pages_build() 로 GitHub Pages 빌드를 강제 요청해 "building 멈춤 → 새 화면이
#   안 뜸" 문제를 회피한다. (2026-07-05 세션: push 후 Pages 빌드가 정체돼 옛 화면이 계속
#   서빙되던 현상 반복 관측 → 수동 리빌드가 유일한 확실 해법.)
#
# 단독 실행:
#   python perth_hub.py [--deploy-dir PATH] [--push] [--rebuild]
#     --deploy-dir : _deploy 경로 (기본: 이 파일 기준 ../ = 레포 루트, 또는 ../_deploy)
#     --push       : 재생성 후 index.html 만 git add/commit/push
#     --rebuild    : push 후(또는 단독) GitHub Pages 리빌드 요청
import os, re, sys, html, subprocess, argparse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = "yesman9692/perth-lookbook"

# 라운드가 아닌(스캔 제외) 폴더
_EXCLUDE = {"imgs", "imgs_detail", "data", "src", "__pycache__", "node_modules", "assets"}

# 알려진 slug → (표시 이름). 없으면 slug 를 보기 좋게 정리해서 사용.
_SLUG_LABELS = {
    "cat-inner-0623": "도심권",
    "cat-inner":      "도심권",
    "main-0616":      "종합",
    "cat700":         "cat700",
    "south-perth":    "South Perth",
}
# 카드 책등 색 팔레트 (최신순으로 순환)
_PALETTE = ["#1a73e8", "#7c4dff", "#0f9d58", "#e8710a", "#d93025", "#00897b", "#5e35b1", "#f4511e"]

_HDR_RE = re.compile(r"퍼스 매물 룩북\s*<span[^>]*>(.*?)</span>", re.S)

_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perth Lookbook · 라운드 아카이브</title>
<meta name="description" content="퍼스 렌트 매물 룩북 — 검색 라운드별 아카이브.">
<style>
  :root{
    --bg:#f0f2f5; --card:#fff; --ink:#1f2733; --muted:#6b7684;
    --line:#e4e8ee; --accent:#1a73e8; --accent-soft:#e8f0fe;
    --shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.06);
    --shadow-hover:0 4px 8px rgba(16,24,40,.08),0 18px 40px rgba(26,115,232,.16);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{font-family:"Malgun Gothic","맑은 고딕",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    color:var(--ink); background:var(--bg); -webkit-font-smoothing:antialiased; line-height:1.6}
  .wrap{max-width:900px; margin:0 auto; padding:0 20px}

  .back{display:inline-flex; align-items:center; gap:6px; margin-top:26px;
    font-size:13px; font-weight:600; color:var(--muted); text-decoration:none}
  .back:hover{color:var(--accent)}

  header{padding:26px 0 34px; text-align:center;
    background:radial-gradient(1100px 360px at 50% -140px, var(--accent-soft), transparent 70%)}
  .emoji{font-size:40px; line-height:1}
  h1{font-size:clamp(26px,5vw,38px); font-weight:800; letter-spacing:-.02em; margin:12px 0 8px}
  .lede{font-size:15px; color:var(--muted); margin:0}

  main{padding:20px 0}
  .shelf-label{display:flex; align-items:center; gap:12px; font-size:13px; font-weight:700;
    letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:0 0 18px}
  .shelf-label::after{content:""; flex:1; height:1px; background:var(--line)}
  .grid{display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
  .card{position:relative; display:flex; flex-direction:column; background:var(--card);
    border:1px solid var(--line); border-radius:16px; padding:22px; text-decoration:none;
    color:inherit; box-shadow:var(--shadow); overflow:hidden;
    transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease}
  .card::before{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--spine,var(--accent)); opacity:.9}
  .card:hover{transform:translateY(-4px); box-shadow:var(--shadow-hover); border-color:#d5deec}
  .card.feat{grid-column:1/-1}
  .row{display:flex; align-items:center; gap:10px; margin-bottom:10px}
  .card h3{margin:0; font-size:18px; font-weight:750; letter-spacing:-.01em}
  .new{font-size:11px; font-weight:800; color:#fff; background:var(--accent);
    border-radius:6px; padding:2px 8px; letter-spacing:.03em}
  .card p{margin:0 0 14px; font-size:13.5px; color:var(--muted); flex:1}
  .meta{display:flex; flex-wrap:wrap; gap:6px; align-items:center}
  .chip{font-size:11.5px; font-weight:600; color:var(--muted); background:#f2f4f7; border-radius:6px; padding:3px 8px}
  .chip.count{color:var(--accent); background:var(--accent-soft)}
  .go{margin-left:auto; font-size:13px; font-weight:700; color:var(--accent);
    display:inline-flex; align-items:center; gap:4px; white-space:nowrap}
  .go svg{transition:transform .18s ease}
  .card:hover .go svg{transform:translateX(3px)}

  footer{text-align:center; color:var(--muted); font-size:13px; padding:40px 0 54px;
    margin-top:20px; border-top:1px solid var(--line)}
  .note{font-size:12px; color:#98a2b3; margin-top:6px}
</style>
</head>
<body>
<div class="wrap">

  <a class="back" href="https://yesman9692.github.io/">← 도서관으로</a>

  <header>
    <div class="emoji">\U0001f3e1</div>
    <h1>Perth Lookbook</h1>
    <p class="lede">퍼스 렌트 매물을 검색 라운드별로 정리한 룩북 아카이브. A/B/C존 기준.</p>
  </header>

  <main>
    <div class="shelf-label">Rounds · 라운드</div>
    <div class="grid">

{{CARDS}}
    </div>
  </main>

  <footer>
    퍼스 렌트 매물 룩북 · 라운드별 아카이브
    <div class="note">새 검색을 돌리면 여기에 라운드가 한 칸씩 쌓입니다.</div>
  </footer>

</div>
</body>
</html>
"""


def _pretty(slug: str) -> str:
    return _SLUG_LABELS.get(slug) or slug.replace("-", " ").replace("_", " ").strip().title()


def _parse_header(index_html: Path):
    """slug/index.html 에서 헤더 span("20260616 · A/B/C존 · 46건 포함 · 0건 제외")을 파싱.
    반환: dict(date=YYYYMMDD|"", zones=str, count=int|None). 실패 시 빈 값."""
    out = {"date": "", "zones": "", "count": None}
    try:
        txt = index_html.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    m = _HDR_RE.search(txt)
    if not m:
        return out
    parts = [p.strip() for p in m.group(1).split("·")]
    for p in parts:
        d = re.fullmatch(r"(\d{8})", p)
        if d:
            out["date"] = d.group(1); continue
        if "존" in p and not out["zones"]:
            out["zones"] = p; continue
        if "포함" in p:
            c = re.search(r"(\d+)", p)
            if c:
                out["count"] = int(c.group(1))
    return out


def _date_disp(yyyymmdd: str) -> str:
    if len(yyyymmdd) == 8:
        return "%s-%s-%s" % (yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:])
    return "날짜 미상"


def scan_rounds(deploy_dir: Path):
    """deploy_dir 하위에서 index.html 을 가진 라운드 폴더를 스캔해 정렬된 리스트 반환.
    newest first (날짜 내림차순, 미상은 뒤)."""
    rounds = []
    for child in sorted(deploy_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _EXCLUDE or child.name.startswith("."):
            continue
        idx = child / "index.html"
        if not idx.exists():
            continue
        meta = _parse_header(idx)
        rounds.append({"slug": child.name, "name": _pretty(child.name), **meta})
    rounds.sort(key=lambda r: (r["date"] or "0"), reverse=True)
    return rounds


_ARROW = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
          'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
          '<path d="M5 12h14M13 6l6 6-6 6"/></svg>')


def _card(rnd: dict, color: str, latest: bool) -> str:
    name = html.escape(rnd["name"])
    date_disp = _date_disp(rnd["date"])
    zone_chip = '<span class="chip">%s</span>' % html.escape(rnd["zones"]) if rnd["zones"] else ""
    count_chip = '<span class="chip count">%d건</span>' % rnd["count"] if rnd["count"] is not None else ""
    if latest:
        badge = '<span class="new">LATEST</span>'
        desc = "가장 최근 라운드 — 매물 수·커버리지가 가장 넓은 스냅샷입니다."
        feat = " feat"
    else:
        badge = ""
        desc = "%s 스냅샷." % date_disp
        feat = ""
    return (
        '      <a class="card%s" style="--spine:%s" href="./%s/">\n'
        '        <div class="row">%s<h3>%s</h3></div>\n'
        '        <p>%s</p>\n'
        '        <div class="meta">\n'
        '          <span class="chip">%s</span>\n'
        '          %s\n'
        '          %s\n'
        '          <span class="go">열기%s</span>\n'
        '        </div>\n'
        '      </a>\n'
    ) % (feat, color, rnd["slug"], badge, name, desc, date_disp, zone_chip, count_chip, _ARROW)


def render_hub(rounds: list) -> str:
    cards = []
    for i, rnd in enumerate(rounds):
        cards.append(_card(rnd, _PALETTE[i % len(_PALETTE)], latest=(i == 0)))
    cards_html = "\n".join(cards)
    return _TEMPLATE.replace("{{CARDS}}", cards_html)


def build_hub(deploy_dir: Path) -> int:
    """deploy_dir 를 스캔해 deploy_dir/index.html(허브)을 재생성. 라운드 수 반환."""
    deploy_dir = Path(deploy_dir)
    rounds = scan_rounds(deploy_dir)
    if not rounds:
        print("  [hub] WARN: 라운드 폴더를 못 찾음 — 허브 생성 skip", file=sys.stderr)
        return 0
    (deploy_dir / "index.html").write_text(render_hub(rounds), encoding="utf-8")
    print("  [hub] 허브 재생성 완료 — %d개 라운드: %s"
          % (len(rounds), ", ".join(r["slug"] for r in rounds)))
    return len(rounds)


def trigger_pages_build(repo: str = REPO) -> bool:
    """GitHub Pages 빌드를 강제 요청(best-effort). gh CLI → curl+token 순으로 시도."""
    # 1) gh CLI
    try:
        r = subprocess.run(["gh", "api", "-X", "POST", "repos/%s/pages/builds" % repo],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print("  [hub] Pages 리빌드 요청(gh) 완료")
            return True
    except FileNotFoundError:
        pass
    # 2) curl + 토큰(env 또는 gh auth token)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            tr = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
            if tr.returncode == 0:
                token = tr.stdout.strip()
        except FileNotFoundError:
            pass
    if token:
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", os.devnull, "-w", "%{http_code}", "-X", "POST",
                 "-H", "Authorization: Bearer %s" % token,
                 "-H", "Accept: application/vnd.github+json",
                 "https://api.github.com/repos/%s/pages/builds" % repo],
                capture_output=True, text=True)
            code = (r.stdout or "").strip()
            print("  [hub] Pages 리빌드 요청(curl) http %s" % code)
            return code.startswith("2")
        except FileNotFoundError:
            pass
    print("  [hub] WARN: Pages 리빌드 자동요청 실패 — 수동 실행: "
          "gh api -X POST repos/%s/pages/builds" % repo, file=sys.stderr)
    return False


def _git(deploy_dir: Path, args: list):
    r = subprocess.run(["git"] + args, cwd=str(deploy_dir), capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def push_hub(deploy_dir: Path) -> bool:
    """index.html(허브)만 commit/push. best-effort."""
    deploy_dir = Path(deploy_dir)
    _git(deploy_dir, ["add", "--", "index.html"])
    rc, out, _ = _git(deploy_dir, ["status", "--porcelain", "--", "index.html"])
    if not out.strip():
        print("  [hub] index.html 변경 없음 — push skip")
        return True
    rc, out, err = _git(deploy_dir, ["commit", "-m", "auto: rebuild library hub"])
    if rc != 0:
        print("  [hub] WARN: commit 실패:", err, file=sys.stderr); return False
    rc_p, _, errp = _git(deploy_dir, ["pull", "--rebase"])
    if rc_p != 0:
        print("  [hub] WARN: pull --rebase 실패 — abort:", errp, file=sys.stderr)
        _git(deploy_dir, ["rebase", "--abort"]); return False
    rc, out, err = _git(deploy_dir, ["push", "--set-upstream", "origin", "master"])
    if rc != 0:
        print("  [hub] WARN: push 실패:", err, file=sys.stderr); return False
    print("  [hub] 허브 push 완료")
    return True


def _default_deploy_dir() -> Path:
    here = Path(os.path.dirname(os.path.abspath(__file__)))
    # src/ 안에서 실행되면 레포 루트는 부모. tools/_deploy 구조면 그쪽.
    for cand in (here.parent, here.parent / "_deploy", here / "_deploy"):
        if (cand / "index.html").exists() or any(
                (cand / s).is_dir() for s in _SLUG_LABELS):
            return cand
    return here.parent


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="퍼스 룩북 대문(허브) 재생성기")
    ap.add_argument("--deploy-dir", default="", help="_deploy 경로 (기본: 자동 탐지)")
    ap.add_argument("--push", action="store_true", help="재생성 후 index.html commit+push")
    ap.add_argument("--rebuild", action="store_true", help="GitHub Pages 리빌드 요청")
    a = ap.parse_args()
    ddir = Path(a.deploy_dir) if a.deploy_dir else _default_deploy_dir()
    print("[hub] deploy-dir:", ddir)
    n = build_hub(ddir)
    if a.push and n:
        push_hub(ddir)
    if a.rebuild:
        trigger_pages_build()
