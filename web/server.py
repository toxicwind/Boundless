"""
web/server.py — boundless boundless web UI (FastAPI, default port 10200).

Layout (boundless, never /mnt):
  boundless/
    processing/inbox/   # fresh uploads + autonomous drop-in target
    processing/active/  # currently being processed
    processing/done/    # completed splits
    processing/failed/  # failed/cancelled
    profiles/           # auto-created JSON profiles
    settings.json       # editable from /settings

Endpoints (all boundless path-bounded):
  GET  /                       — UI
  GET  /settings               — settings UI
  GET  /api/health             — health + counts
  GET  /api/settings           — read settings.json
  PUT  /api/settings           — update settings.json
  POST /api/upload             — upload + auto-profile
  GET  /api/profile/{id}       — re-profile stored upload
  POST /api/profile/ensure     — force profile creation
  POST /api/split/{id}         — size-based split
  POST /api/split-toc/{id}     — top-level TOC split (preserves assets)
  GET  /api/outputs/{sub}/{f}  — download a chunk
  POST /api/scan               — scan a boundless directory
  GET  /api/profiles           — list profiles
  DEL  /api/profiles/{file}    — delete profile
  GET  /api/processing         — list files in inbox/active/done/failed
  POST /api/process/{file}     — move inbox file → active → done/failed
  GET  /api/edge-cases         — full EdgeCaseRegistry
"""
from __future__ import annotations
import os, json, shutil, time, threading, queue
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, Response, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SRC))

from boundless import (
    profile_epub, ensure_profile, auto_create_profiles,
    EpubSplitter, PdfSplitter, DocxSplitter,
    ChunkMetadata, SplitReport, A11yLogger,
    DEFAULT_MAX_SIZE_MB, EdgeCaseRegistry,
)

# ---- .env loader (boundless, no dotenv dep) ----
def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
_load_env()

PORT = int(os.environ.get("PORT", "10200"))
HOST = os.environ.get("HOST", "0.0.0.0")
PROCESSING_DIR = Path(os.environ.get("PROCESSING_DIR", str(ROOT / "processing"))).expanduser()
PROFILES_DIR = Path(os.environ.get("PROFILES_DIR", str(ROOT / "profiles"))).expanduser()
MAX_SIZE_MB = int(os.environ.get("MAX_SIZE_MB", str(DEFAULT_MAX_SIZE_MB)))
INBOX_DIR = PROCESSING_DIR / "inbox"
ACTIVE_DIR = PROCESSING_DIR / "active"
DONE_DIR = PROCESSING_DIR / "done"
FAILED_DIR = PROCESSING_DIR / "failed"
SETTINGS_PATH = ROOT / "settings.json"
for _d in (INBOX_DIR, ACTIVE_DIR, DONE_DIR, FAILED_DIR, PROFILES_DIR, PROCESSING_DIR):
    _d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Boundless", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
WEB_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# ---- Settings (boundless JSON, editable from frontend) ----
DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_watch_inbox": True,        # process new files in inbox/ automatically
    "auto_profile_on_upload": True,  # create profile JSON on every upload
    "auto_split_on_upload": False,   # run size-based split immediately on upload
    "default_max_size_mb": MAX_SIZE_MB,
    "max_size_mb_options": [25, 50, 75, 100],
    "natural_reader_limit_mb": 50,
    "default_split_method": "size",  # "size" or "toc"
    "scan_recursive": False,
    "scan_extensions": ["epub", "pdf", "docx", "doc"],
    "tray_enabled": False,
    "auto_open_browser_on_launch": True,
    "theme": "dark",
    "log_level": "info",
    "open_browser_after_start": True,
    "host": HOST,
    "port": PORT,
}

def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))}
        except Exception:
            return dict(DEFAULT_SETTINGS)
    return dict(DEFAULT_SETTINGS)

def _save_settings(s: dict) -> dict:
    merged = {**DEFAULT_SETTINGS, **s}
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged

# ---- Autonomous inbox watcher ----
_watcher_lock = threading.Lock()
_watcher_thread: Optional[threading.Thread] = None
_watcher_event = threading.Event()

def _is_stable(p: Path) -> bool:
    """True if file size hasn't changed in 1.5s (upload finished)."""
    try:
        s1 = p.stat().st_size
        time.sleep(1.5)
        s2 = p.stat().st_size
        return s1 == s2 and s1 > 0
    except Exception:
        return False

def _process_one(file: Path, settings: dict) -> Dict[str, Any]:
    """Process a single file: profile, then optionally split."""
    log = []
    try:
        if settings.get("auto_profile_on_upload", True):
            p = ensure_profile(file, PROFILES_DIR)
            log.append(f"profile → {p.name}")
        if settings.get("auto_split_on_upload", False):
            method = settings.get("default_split_method", "size")
            out = DONE_DIR / f"{file.stem}_{method}"
            if method == "toc":
                try:
                    from boundless import split_epub_by_toc
                    r = split_epub_by_toc(file, out)
                    log.append(f"toc split → {r['count']} sections in {out.name}")
                except Exception as e:
                    log.append(f"toc split skipped: {e}")
            else:
                sp = EpubSplitter(max_size_bytes=settings["default_max_size_mb"]*1024*1024, logger=A11yLogger())
                rep = sp.split(str(file), str(out))
                log.append(f"size split → {rep.chunk_count} chunks in {out.name}")
        # move to done
        dest = DONE_DIR / file.name
        if dest.exists():
            dest = DONE_DIR / f"{file.stem}_{int(time.time())}{file.suffix}"
        shutil.move(str(file), str(dest))
        return {"ok": True, "log": log, "moved_to": str(dest)}
    except Exception as e:
        try:
            shutil.move(str(file), str(FAILED_DIR / file.name))
        except Exception:
            pass
        return {"ok": False, "error": str(e), "log": log}

def _watcher_loop():
    settings = _load_settings()
    seen: Dict[str, int] = {}
    while not _watcher_event.is_set():
        try:
            if settings.get("auto_watch_inbox", True):
                for f in INBOX_DIR.iterdir():
                    if not f.is_file():
                        continue
                    key = f.name
                    if seen.get(key) == f.stat().st_size:
                        continue
                    seen[key] = f.stat().st_size
                    if _is_stable(f):
                        _process_one(f, settings)
                        seen.pop(key, None)
        except Exception:
            pass
        _watcher_event.wait(2.0)

def start_watcher():
    global _watcher_thread
    with _watcher_lock:
        if _watcher_thread and _watcher_thread.is_alive():
            return
        _watcher_event.clear()
        _watcher_thread = threading.Thread(target=_watcher_loop, name="inbox-watcher", daemon=True)
        _watcher_thread.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_watcher()
    yield
    _watcher_event.set()  # graceful shutdown signal

# ---- Path-bounded helpers ----
def _resolve_in(p: Path) -> Path:
    rp = p.resolve()
    if not str(rp).startswith(str(INBOX_DIR.resolve())):
        raise HTTPException(403, "Path traversal denied")
    return rp

def _resolve_done(p: Path) -> Path:
    rp = p.resolve()
    if not str(rp).startswith(str(DONE_DIR.resolve())):
        raise HTTPException(403, "Path traversal denied")
    return rp

def _splitter_for(path: Path, max_size_mb: int):
    logger = A11yLogger(verbose=True)
    ext = path.suffix.lower()
    if ext == ".epub":
        return EpubSplitter(max_size_bytes=max_size_mb*1024*1024, logger=logger)
    if ext == ".pdf":
        return PdfSplitter(max_size_bytes=max_size_mb*1024*1024, logger=logger)
    if ext in (".docx", ".doc"):
        return DocxSplitter(max_size_bytes=max_size_mb*1024*1024, logger=logger)
    raise HTTPException(415, f"Unsupported: {ext}")

def _check_boundless(p: Path):
    s = str(p.resolve())
    if "/mnt" in s.split("/"):
        raise HTTPException(403, "Boundary: /mnt access denied")
    return p

# ---- Routes ----
@app.get("/", response_class=HTMLResponse)
async def index():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return (WEB_DIR / "settings.html").read_text(encoding="utf-8")

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/api/health")
async def health():
    return {
        "status": "ok", "port": PORT, "host": HOST,
        "max_size_mb": MAX_SIZE_MB,
        "processing_dir": str(PROCESSING_DIR),
        "profiles_dir": str(PROFILES_DIR),
        "inbox": len(list(INBOX_DIR.iterdir())),
        "active": len(list(ACTIVE_DIR.iterdir())),
        "done": len(list(DONE_DIR.iterdir())),
        "failed": len(list(FAILED_DIR.iterdir())),
        "profiles": len(list(PROFILES_DIR.glob("*.json"))),
        "version": "2.0.0",
    }

@app.get("/api/settings")
async def get_settings():
    return _load_settings()

@app.put("/api/settings")
async def update_settings(s: dict):
    merged = _save_settings(s)
    if merged.get("auto_watch_inbox", True):
        start_watcher()
    return merged

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...)):
    settings = _load_settings()
    out = []
    for f in files:
        safe = f.filename.replace("/", "_").replace("\\", "_")
        ts = int(time.time()*1000)
        dest = INBOX_DIR / f"{Path(safe).stem}_{ts}{Path(safe).suffix}"
        with open(dest, "wb") as fp:
            shutil.copyfileobj(f.file, fp)
        prof_path = None
        prof = None
        if settings.get("auto_profile_on_upload", True):
            prof_path = ensure_profile(dest, PROFILES_DIR)
            prof = json.loads(prof_path.read_text(encoding="utf-8"))
        out.append({
            "upload_id": dest.name,
            "filename": f.filename,
            "size": dest.stat().st_size,
            "size_mb": prof["size_mb"] if prof else round(dest.stat().st_size/1024/1024, 1),
            "profile_path": str(prof_path) if prof_path else None,
            "profile": prof,
        })
    return {"uploads": out, "count": len(out)}

@app.get("/api/profile/{upload_id}")
async def get_profile(upload_id: str):
    p = _resolve_in(INBOX_DIR / upload_id)
    if not p.exists():
        raise HTTPException(404)
    return profile_epub(p, compute_hash=True).to_dict()

@app.post("/api/profile/ensure")
async def profile_ensure(upload_id: str):
    p = _resolve_in(INBOX_DIR / upload_id)
    if not p.exists():
        raise HTTPException(404)
    out = ensure_profile(p, PROFILES_DIR)
    return {"profile_path": str(out), "profile": json.loads(out.read_text(encoding="utf-8"))}

@app.post("/api/process/{upload_id}")
async def process_upload(upload_id: str, method: str = "size", max_size_mb: Optional[int] = None):
    """Move inbox → active → run split → done. Returns log + result."""
    src = _resolve_in(INBOX_DIR / upload_id)
    if not src.exists():
        raise HTTPException(404)
    settings = _load_settings()
    max_mb = max_size_mb or settings.get("default_max_size_mb", MAX_SIZE_MB)
    log = []
    try:
        # profile
        prof = ensure_profile(src, PROFILES_DIR)
        log.append(f"profile → {prof.name}")
        # move to active
        active = ACTIVE_DIR / src.name
        if active.exists():
            active = ACTIVE_DIR / f"{src.stem}_{int(time.time())}{src.suffix}"
        shutil.move(str(src), str(active))
        log.append(f"active → {active.name}")
        # split
        out = DONE_DIR / f"{active.stem}_{method}"
        if method == "toc":
            from boundless import split_epub_by_toc
            r = split_epub_by_toc(active, out)
            log.append(f"toc split → {r['count']} sections in {out.name}")
            result = r
        else:
            sp = _splitter_for(active, max_mb)
            rep = sp.split(str(active), str(out))
            log.append(f"size split → {rep.chunk_count} chunks in {out.name}")
            result = {
                "source": rep.source_path, "chunk_count": rep.chunk_count,
                "total_output_size": rep.total_output_size,
                "warnings": rep.warnings, "errors": rep.errors,
                "chunks": [{"title": c.title, "size": c.byte_size, "spine": c.spine_files, "asset_count": len(c.asset_files)} for c in rep.chunks],
                "output_dir": str(out),
            }
        # move to done
        dest = DONE_DIR / active.name
        if dest.exists():
            dest = DONE_DIR / f"{active.stem}_{int(time.time())}{active.suffix}"
        shutil.move(str(active), str(dest))
        log.append(f"done → {dest.name}")
        return {"ok": True, "log": log, "result": result}
    except Exception as e:
        try:
            shutil.move(str(active) if active.exists() else str(src), str(FAILED_DIR / (active.name if active.exists() else src.name)))
        except Exception:
            pass
        log.append(f"FAILED: {e}")
        raise HTTPException(500, detail={"error": str(e), "log": log})

@app.post("/api/split-toc/{upload_id}")
async def split_toc(upload_id: str, output_subdir: Optional[str] = None):
    try:
        from boundless import split_epub_by_toc
    except Exception as e:
        raise HTTPException(503, f"toc_split unavailable (need lxml): {e}")
    src = _resolve_in(INBOX_DIR / upload_id)
    if not src.exists():
        raise HTTPException(404)
    out_dir = DONE_DIR / (output_subdir or f"{src.stem}_toc")
    return split_epub_by_toc(src, out_dir)

@app.post("/api/split/{upload_id}")
async def split_size(upload_id: str, max_size_mb: int = MAX_SIZE_MB, output_subdir: Optional[str] = None):
    src = _resolve_in(INBOX_DIR / upload_id)
    if not src.exists():
        raise HTTPException(404)
    out_dir = DONE_DIR / (output_subdir or src.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    splitter = _splitter_for(src, max_size_mb)
    report = splitter.split(str(src), str(out_dir))
    return {
        "source": report.source_path, "format": report.source_format,
        "size_bytes": report.source_size_bytes, "chunk_count": report.chunk_count,
        "total_output_size": report.total_output_size,
        "warnings": report.warnings, "errors": report.errors,
        "chunks": [{"title": c.title, "slug": c.slug, "size": c.byte_size, "spine": c.spine_files, "asset_count": len(c.asset_files)} for c in report.chunks],
        "output_dir": str(out_dir),
    }

@app.get("/api/outputs/{subdir}/{file}")
async def fetch_output(subdir: str, file: str):
    p = (DONE_DIR / subdir / file).resolve()
    if not str(p).startswith(str(DONE_DIR.resolve())):
        raise HTTPException(403, "Path traversal denied")
    if not p.exists() or not p.is_file():
        raise HTTPException(404)
    total = p.stat().st_size
    mt = "application/epub+zip" if p.suffix == ".epub" else "application/octet-stream"

    def _iter():
        # Stream 64KB chunks — never loads whole file in memory
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type=mt,
        headers={
            "Content-Length": str(total),
            "Content-Disposition": f'attachment; filename="{file}"',
        },
    )

@app.get("/api/processing")
async def processing_state():
    def _list(d: Path):
        out = []
        for f in sorted(d.iterdir()):
            if f.is_file():
                out.append({"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime})
            elif f.is_dir():
                out.append({"name": f.name, "type": "dir", "size": sum(c.stat().st_size for c in f.rglob('*') if c.is_file())})
        return out
    return {
        "inbox": _list(INBOX_DIR),
        "active": _list(ACTIVE_DIR),
        "done": _list(DONE_DIR),
        "failed": _list(FAILED_DIR),
    }

@app.post("/api/scan")
async def scan(directory: str):
    target = _check_boundless(Path(directory).expanduser())
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, f"Directory not found: {target}")
    settings = _load_settings()
    exts = settings.get("scan_extensions", ["epub", "pdf", "docx", "doc"])
    if settings.get("scan_recursive", False):
        eps = []
        for e in exts:
            eps.extend(target.rglob(f"*.{e}"))
    else:
        eps = []
        for e in exts:
            eps.extend(target.glob(f"*.{e}"))
    eps = sorted(set(eps))
    created = auto_create_profiles([str(e) for e in eps], PROFILES_DIR) if eps else []
    profiles = [json.loads(p.read_text(encoding="utf-8")) for p in created]
    return {"scanned": len(eps), "profiles_created": len(created), "profiles": profiles}

@app.get("/api/profiles")
async def list_profiles():
    files = sorted(PROFILES_DIR.glob("*.json"))
    profiles = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            profiles.append({
                "file": f.name, "title": d.get("title"), "creator": d.get("creator"),
                "publisher": d.get("publisher"), "origin": d.get("origin", {}),
                "nr_status": d.get("nr_status"), "size_mb": d.get("size_mb"),
                "split_strategy": d.get("split_strategy"),
                "nr_chunks_needed": d.get("nr_chunks_needed"),
                "sha256": d.get("sha256"),
            })
        except Exception as e:
            profiles.append({"file": f.name, "error": str(e)})
    return {"count": len(profiles), "profiles": profiles}

@app.delete("/api/profiles/{name}")
async def delete_profile(name: str):
    p = (PROFILES_DIR / name).resolve()
    if not str(p).startswith(str(PROFILES_DIR.resolve())):
        raise HTTPException(403, "Path traversal denied")
    if p.exists():
        p.unlink()
        return {"deleted": name}
    raise HTTPException(404)

@app.get("/api/edge-cases")
async def edge_cases():
    return {
        "epub": EdgeCaseRegistry.EPUB_EDGE_CASES,
        "pdf": EdgeCaseRegistry.PDF_EDGE_CASES,
        "docx": EdgeCaseRegistry.DOCX_EDGE_CASES,
        "a11y": EdgeCaseRegistry.ACCESSIBILITY_EDGE_CASES,
    }

def run():
    print(f"boundless boundless web UI on http://{HOST}:{PORT}")
    print(f"Drop EPUBs into {INBOX_DIR} for autonomous processing")
    uvicorn.run("web.server:app", host=HOST, port=PORT, reload=False, log_level="info")

if __name__ == "__main__":
    run()
