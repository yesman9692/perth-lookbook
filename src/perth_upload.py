# -*- coding: utf-8 -*-
# perth_upload.py — archive analysed listings to Google Drive (standalone, backgroundable).
# Structure (per feedback_perth_realestate_session_rule): 호주/부동산/{date}/{id}_{region}_{price}/
#   uploads detail_{id}.json + imgs_detail/{id}_*.jpg ; idempotent (skips existing names).
# Reuses cowork .gcreds (same auth as scripts/sync_memory.py).
# usage: python perth_upload.py lookbook_manifest.json --date 20260608
import os, sys, json, glob, argparse, mimetypes
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

HOME = Path(os.path.expanduser("~"))
CRED_DIR = HOME / ".claude" / "projects" / "D--my-cowork" / ".gcreds"
CRED_PATH, TOKEN_PATH = CRED_DIR / "credentials.json", CRED_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
PROPERTY_FOLDER_ID = "1Gp6mnA1CnDWvxWqQadxDtWTGXrdQtgCz"          # 호주/부동산/
TOOLS = Path(r"D:\my\cowork\tools"); IMGDIR = TOOLS / "imgs_detail"

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

def service():
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

def _esc(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")

def find_child(svc, parent, name, folder=False):
    q = "name='%s' and '%s' in parents and trashed=false" % (_esc(name), parent)
    if folder:
        q += " and mimeType='application/vnd.google-apps.folder'"
    f = svc.files().list(q=q, fields="files(id,name)", pageSize=1,
                         supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
    return f[0]["id"] if f else None

def ensure_folder(svc, parent, name):
    fid = find_child(svc, parent, name, folder=True)
    if fid:
        return fid, False
    body = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]}
    return svc.files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"], True

def upload(svc, parent, path):
    from googleapiclient.http import MediaFileUpload
    name = os.path.basename(path)
    if find_child(svc, parent, name):
        return "skip"
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    media = MediaFileUpload(path, mimetype=mime, resumable=False)
    svc.files().create(body={"name": name, "parents": [parent]}, media_body=media,
                       fields="id", supportsAllDrives=True).execute()
    return "up"

def upload_or_replace(svc, parent, path, name):
    """Upload a single file, overwriting content if a file with the same name exists."""
    from googleapiclient.http import MediaFileUpload
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    media = MediaFileUpload(path, mimetype=mime, resumable=False)
    fid = find_child(svc, parent, name)
    if fid:
        svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
        return "update", fid
    f = svc.files().create(body={"name": name, "parents": [parent]}, media_body=media,
                           fields="id", supportsAllDrives=True).execute()
    return "create", f["id"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--maximg", type=int, default=14)
    ap.add_argument("--pdf", default=None, help="also upload this lookbook PDF to the date folder (overwrite by name)")
    args = ap.parse_args()
    manifest = json.load(open(args.manifest, encoding="utf-8"))
    svc = service()
    date_fid, _ = ensure_folder(svc, PROPERTY_FOLDER_ID, args.date)
    print("[upload] date folder %s = %s" % (args.date, date_fid), flush=True)
    for e in manifest:
        lid = e["id"]
        fname = "%s_%s_%s" % (lid, e.get("region", "x").replace(" ", ""), e.get("price", "x"))
        lf, created = ensure_folder(svc, date_fid, fname)
        up = sk = 0
        jp = TOOLS / ("detail_%s.json" % lid)
        if jp.exists():
            r = upload(svc, lf, str(jp)); up += r == "up"; sk += r == "skip"
        for img in sorted(glob.glob(str(IMGDIR / ("%s_*.jpg" % lid))))[:args.maximg]:
            r = upload(svc, lf, img); up += r == "up"; sk += r == "skip"
        print("[upload] %-30s up=%d skip=%d %s" % (fname, up, sk, "NEW" if created else ""), flush=True)
    if args.pdf and os.path.exists(args.pdf):
        pname = "퍼스_룩북_%s.pdf" % args.date
        act, pid = upload_or_replace(svc, date_fid, args.pdf, pname)
        print("[upload] PDF %s (%s) -> https://drive.google.com/file/d/%s/view" % (pname, act, pid), flush=True)
    print("[upload] DONE -> https://drive.google.com/drive/folders/%s" % date_fid, flush=True)

if __name__ == "__main__":
    main()
