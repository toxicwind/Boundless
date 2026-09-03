"""
web/server.py — boundless web UI (FastAPI, default port 10200).
Autonomous inbox processing, persistent SQLite job engine, hot-reloading by default.

Layout (boundless, never /mnt):
  boundless/
    processing/inbox/   # fresh uploads + autonomous drop-in target
    processing/active/  # currently being processed
    processing/done/    # completed splits
    processing/failed/  # failed/cancelled
    processing/boundless.db # SQLite job history and inbox store
    profiles/           # auto-created JSON profiles
    settings.json       # editable from /settings

Endpoints:
  GET  /                       — UI
  GET  /settings               — settings UI
  GET  /api/health             — health + counts
  GET  /api/status             — full system status + watcher heartbeat + DB counts
  GET  /api/settings           — read settings.json
  PUT  /api/settings           — update settings.json
  POST /api/upload             — upload + auto-profile
  GET  /api/profile/{id}       — re-profile stored upload
  POST /api/profile/ensure     — force profile creation
  POST /api/split/{id}         — size-based split
  POST /api/split-toc/{id}     — top-level TOC split (preserves assets)
  GET  /api/outputs/{sub}/{f}  — download a chunk
  GET  /api/outputs/{sub}/zip  — download all chunks as ZIP
  GET  /api/outputs/{sub}      — inspect chunks in done folder
  POST /api/scan               — scan a boundless directory
  GET  /api/profiles           — list profiles
  DEL  /api/profiles/{file}    — delete profile
  GET  /api/processing         — list files in inbox/active/done/failed
  POST /api/process/{file}     — move inbox file → active → done/failed
  GET  /api/jobs               — list jobs from SQLite
  GET  /api/jobs/{id}          — get job details + chunks + logs
  DEL  /api/jobs/{id}          — delete job record
  POST /api/jobs/retry/{id}    — re-run a job
  GET  /api/inbox              — rich metadata of inbox files
  DEL  /api/inbox/{filename}   — remove file from inbox
  GET  /api/edge-cases         — full EdgeCaseRegistry
"""
from __future__ import annotations
import os, sys, json, shutil, time, threading, queue, io, zipfile
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from boundless import (
    profile_epub, ensure_profile, auto_create_profiles,
    EpubSplitter, PdfSplitter, DocxSplitter,
    ChunkMetadata, SplitReport, A11yLogger,
    DEFAULT_MAX_SIZE_MB, EdgeCaseRegistry,
)
from boundless.deps import (
    HAS_LXML, HAS_PYMUPDF, HAS_EBOOKLIB, HAS_PYTHON_DOCX,
)
from boundless.db import (
    init_db, create_job, update_job_progress, complete_job, fail_job,
    get_job, list_jobs, delete_job, record_inbox_item, remove_inbox_item,
    list_inbox_items, backfill_from_disk,
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
DB_PATH = PROCESSING_DIR / "boundless.db"
SETTINGS_PATH = ROOT / "settings.json"

for _d in (INBOX_DIR, ACTIVE_DIR, DONE_DIR, FAILED_DIR, PROFILES_DIR, PROCESSING_DIR):
    _d.mkdir(parents=True, exist_ok=True)

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
    "hot_reload": True,
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
    """Process a single file: profile, then optionally split. Records to SQLite."""
    log = []
    t0 = time.time()
    job = None
    try:
        prof_data = {}
        if settings.get("auto_profile_on_upload", True):
            p = ensure_profile(file, PROFILES_DIR)
            prof_data = json.loads(p.read_text(encoding="utf-8"))
            log.append(f"profile → {p.name}")
        
        origin = prof_data.get("origin", {})
        title = prof_data.get("title") or file.stem.replace("_", " ").title()
        creator = prof_data.get("creator") or "Unknown"
        publisher = prof_data.get("publisher") or origin.get("publisher") or "Unknown"
        nr_status = prof_data.get("nr_status") or "ok"

        # Update inbox in DB
        mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(file.stat().st_mtime))
        record_inbox_item(
            DB_PATH,
            filename=file.name,
            size=file.stat().st_size,
            modified_at=mtime,
            title=title,
            creator=creator,
            publisher=publisher,
            nr_status=nr_status,
            origin=origin,
            profile_path=str(PROFILES_DIR / f"{file.stem}.json") if (PROFILES_DIR / f"{file.stem}.json").exists() else None,
        )

        if settings.get("auto_split_on_upload", False):
            method = settings.get("default_split_method", "size")
            max_mb = settings.get("default_max_size_mb", MAX_SIZE_MB)
            job = create_job(
                DB_PATH,
                filename=file.name,
                file_path=str(file),
                file_size=file.stat().st_size,
                method=method,
                max_size_mb=max_mb,
                book_title=title,
                creator=creator,
                publisher=publisher,
                origin_pipeline=origin.get("pipeline", ""),
                nr_status=nr_status,
                profile=prof_data,
            )
            # move to active
            active = ACTIVE_DIR / file.name
            if active.exists():
                active = ACTIVE_DIR / f"{file.stem}_{int(time.time())}{file.suffix}"
            shutil.move(str(file), str(active))
            log.append(f"active → {active.name}")
            update_job_progress(DB_PATH, job["id"], 40, "splitting", f"Moved to active: {active.name}")

            out = DONE_DIR / f"{active.stem}_{method}"
            chunks = []
            if method == "toc":
                from boundless import split_epub_by_toc
                r = split_epub_by_toc(active, out)
                log.append(f"toc split → {r['count']} sections in {out.name}")
                for s in r.get("sections", []):
                    cp = out / s
                    sz = cp.stat().st_size if cp.exists() else 0
                    chunks.append({"name": s, "title": Path(s).stem, "size": sz, "size_mb": round(sz/1024/1024, 2), "url": f"/api/outputs/{out.name}/{s}"})
            else:
                sp = _splitter_for(active, max_mb)
                rep = sp.split(str(active), str(out))
                log.append(f"size split → {rep.chunk_count} chunks in {out.name}")
                for c in rep.chunks:
                    cf_name = f"{c.title}.epub"
                    chunks.append({"name": cf_name, "title": c.title, "size": c.byte_size, "size_mb": round(c.byte_size/1024/1024, 2), "url": f"/api/outputs/{out.name}/{cf_name}"})

            # move original to done
            dest = DONE_DIR / active.name
            if dest.exists():
                dest = DONE_DIR / f"{active.stem}_{int(time.time())}{active.suffix}"
            shutil.move(str(active), str(dest))
            log.append(f"done → {dest.name}")
            remove_inbox_item(DB_PATH, file.name)
            total_out = sum(c["size"] for c in chunks)
            complete_job(DB_PATH, job["id"], str(out), chunks, total_out, log, time.time() - t0)
            return {"ok": True, "log": log, "moved_to": str(dest)}
        else:
            return {"ok": True, "log": log, "profiled": True}
    except Exception as e:
        if job:
            fail_job(DB_PATH, job["id"], str(e), log)
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
            settings = _load_settings()
            if settings.get("auto_watch_inbox", True) and INBOX_DIR.exists():
                for f in list(INBOX_DIR.iterdir()):
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
    init_db(DB_PATH)
    backfill_from_disk(DB_PATH, PROCESSING_DIR, PROFILES_DIR)
    start_watcher()
    yield
    _watcher_event.set()

app = FastAPI(title="Boundless", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
WEB_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

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

def _system_status_payload() -> Dict[str, Any]:
    inbox_files = [f for f in INBOX_DIR.iterdir() if f.is_file()] if INBOX_DIR.exists() else []
    active_files = list(ACTIVE_DIR.iterdir()) if ACTIVE_DIR.exists() else []
    done_items = list(DONE_DIR.iterdir()) if DONE_DIR.exists() else []
    failed_items = list(FAILED_DIR.iterdir()) if FAILED_DIR.exists() else []
    profiles = list(PROFILES_DIR.glob("*.json")) if PROFILES_DIR.exists() else []
    all_jobs = list_jobs(DB_PATH) if DB_PATH.exists() else []
    
    settings = _load_settings()
    is_watcher_running = _watcher_thread is not None and _watcher_thread.is_alive()

    return {
        "status": "ok",
        "healthy": True,
        "port": PORT,
        "host": HOST,
        "max_size_mb": MAX_SIZE_MB,
        "processing_dir": str(PROCESSING_DIR),
        "profiles_dir": str(PROFILES_DIR),
        "inbox": len(inbox_files),
        "active": len(active_files),
        "done": len(done_items),
        "failed": len(failed_items),
        "profiles": len(profiles),
        "jobs_total": len(all_jobs),
        "jobs_completed": sum(1 for j in all_jobs if j.get("status") == "completed"),
        "version": "2.0.0",
        "watcher": {
            "running": is_watcher_running,
            "auto_watch": settings.get("auto_watch_inbox", True),
            "auto_split": settings.get("auto_split_on_upload", False),
        },
        "system": {
            "has_lxml": HAS_LXML,
            "has_pymupdf": HAS_PYMUPDF,
            "has_ebooklib": HAS_EBOOKLIB,
            "has_docx": HAS_PYTHON_DOCX,
            "hot_reload": settings.get("hot_reload", True),
        },
    }

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
    return _system_status_payload()

@app.get("/api/status")
async def status():
    return _system_status_payload()
@app.put("/api/settings")
async def update_settings(s: dict):
    merged = _save_settings(s)
    if merged.get("auto_watch_inbox", True):
        start_watcher()
    return merged

@app.get("/api/jobs")
async def get_jobs_route(limit: int = 50, offset: int = 0, status: Optional[str] = None):
    jobs = list_jobs(DB_PATH, limit=limit, offset=offset, status=status)
    return {"jobs": jobs, "count": len(jobs)}

@app.get("/api/jobs/{job_id}")
async def get_job_route(job_id: str):
    j = get_job(DB_PATH, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j

@app.delete("/api/jobs/{job_id}")
async def delete_job_route(job_id: str):
    ok = delete_job(DB_PATH, job_id)
    if not ok:
        raise HTTPException(404, "Job not found")
    return {"deleted": job_id}

@app.get("/api/inbox")
async def get_inbox():
    items = list_inbox_items(DB_PATH)
    # Also verify with physical files
    filenames_in_db = {it["filename"] for it in items}
    if INBOX_DIR.exists():
        for f in INBOX_DIR.iterdir():
            if f.is_file() and f.name not in filenames_in_db:
                mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.stat().st_mtime))
                record_inbox_item(
                    DB_PATH,
                    filename=f.name,
                    size=f.stat().st_size,
                    modified_at=mtime,
                    title=f.stem.replace("_", " ").title(),
                )
        items = list_inbox_items(DB_PATH)
    return {"items": items, "count": len(items)}

@app.delete("/api/inbox/{filename}")
async def delete_inbox_file(filename: str):
    p = _resolve_in(INBOX_DIR / filename)
    if p.exists() and p.is_file():
        p.unlink()
        remove_inbox_item(DB_PATH, filename)
        return {"deleted": filename}
    raise HTTPException(404, "File not found")

@app.post("/api/inbox/process-all")
async def process_all_inbox():
    settings = _load_settings()
    results = []
    if INBOX_DIR.exists():
        for f in sorted(INBOX_DIR.iterdir()):
            if f.is_file():
                r = _process_one(f, {**settings, "auto_split_on_upload": True})
                results.append({"file": f.name, "result": r})
    return {"processed": len(results), "results": results}

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
            mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(dest.stat().st_mtime))
            record_inbox_item(
                DB_PATH,
                filename=dest.name,
                size=dest.stat().st_size,
                modified_at=mtime,
                title=prof.get("title") or dest.stem.replace("_", " ").title(),
                creator=prof.get("creator") or "Unknown",
                publisher=prof.get("publisher") or prof.get("origin", {}).get("publisher") or "Unknown",
                nr_status=prof.get("nr_status") or "ok",
                origin=prof.get("origin", {}),
                profile_path=str(prof_path),
            )
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
    """Move inbox → active → run split → done. Returns log + result and records to SQLite."""
    src = _resolve_in(INBOX_DIR / upload_id)
    if not src.exists():
        raise HTTPException(404)
    settings = _load_settings()
    max_mb = max_size_mb or settings.get("default_max_size_mb", MAX_SIZE_MB)
    log = []
    t0 = time.time()
    active = None
    job = None
    try:
        # profile
        prof = ensure_profile(src, PROFILES_DIR)
        prof_data = json.loads(prof.read_text(encoding="utf-8"))
        log.append(f"profile → {prof.name}")
        origin = prof_data.get("origin", {})
        title = prof_data.get("title") or src.stem.replace("_", " ").title()

        job = create_job(
            DB_PATH,
            filename=src.name,
            file_path=str(src),
            file_size=src.stat().st_size,
            method=method,
            max_size_mb=max_mb,
            book_title=title,
            creator=prof_data.get("creator"),
            publisher=prof_data.get("publisher") or origin.get("publisher"),
            origin_pipeline=origin.get("pipeline", ""),
            nr_status=prof_data.get("nr_status", "ok"),
            profile=prof_data,
        )

        # move to active
        active = ACTIVE_DIR / src.name
        if active.exists():
            active = ACTIVE_DIR / f"{src.stem}_{int(time.time())}{src.suffix}"
        shutil.move(str(src), str(active))
        log.append(f"active → {active.name}")
        update_job_progress(DB_PATH, job["id"], 30, "active", f"Moved to {active.name}")

        # split
        out = DONE_DIR / f"{active.stem}_{method}"
        chunks_info = []
        if method == "toc":
            from boundless import split_epub_by_toc
            r = split_epub_by_toc(active, out)
            log.append(f"toc split → {r['count']} sections in {out.name}")
            result = r
            for s in r.get("sections", []):
                cp = out / s
                sz = cp.stat().st_size if cp.exists() else 0
                chunks_info.append({"name": s, "title": Path(s).stem, "size": sz, "size_mb": round(sz/1024/1024, 2), "url": f"/api/outputs/{out.name}/{s}"})
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
            for c in rep.chunks:
                cf_name = f"{c.title}.epub"
                chunks_info.append({"name": cf_name, "title": c.title, "size": c.byte_size, "size_mb": round(c.byte_size/1024/1024, 2), "url": f"/api/outputs/{out.name}/{cf_name}"})

        # move to done
        dest = DONE_DIR / active.name
        if dest.exists():
            dest = DONE_DIR / f"{active.stem}_{int(time.time())}{active.suffix}"
        shutil.move(str(active), str(dest))
        log.append(f"done → {dest.name}")
        remove_inbox_item(DB_PATH, upload_id)
        
        total_out = sum(c["size"] for c in chunks_info)
        complete_job(DB_PATH, job["id"], str(out), chunks_info, total_out, log, time.time() - t0)
        return {"ok": True, "log": log, "result": result, "job_id": job["id"], "chunks": chunks_info}
    except Exception as e:
        if job:
            fail_job(DB_PATH, job["id"], str(e), log)
        try:
            shutil.move(str(active) if (active and active.exists()) else str(src), str(FAILED_DIR / (active.name if (active and active.exists()) else src.name)))
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
    out_dir = (DONE_DIR / (output_subdir or f"{src.stem}_toc")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return split_epub_by_toc(src, out_dir)

@app.post("/api/split/{upload_id}")
async def split_size(upload_id: str, max_size_mb: int = MAX_SIZE_MB, output_subdir: Optional[str] = None):
    src = _resolve_in(INBOX_DIR / upload_id)
    if not src.exists():
        raise HTTPException(404)
    out_dir = (DONE_DIR / (output_subdir or src.stem)).resolve()
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

@app.get("/api/outputs/{subdir}/zip")
async def fetch_output_zip(subdir: str):
    target_dir = (DONE_DIR / subdir).resolve()
    if not str(target_dir).startswith(str(DONE_DIR.resolve())):
        raise HTTPException(403, "Path traversal denied")
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(404, f"Output directory {subdir} not found")
    
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(target_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(target_dir)
                zf.write(f, str(rel))
    mem.seek(0)
    data = mem.getvalue()
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{subdir}_chunks.zip"',
            "Content-Length": str(len(data)),
        }
    )

@app.get("/api/outputs/{subdir}")
async def list_output_chunks(subdir: str):
    target_dir = (DONE_DIR / subdir).resolve()
    if not str(target_dir).startswith(str(DONE_DIR.resolve())):
        raise HTTPException(403, "Path traversal denied")
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(404, "Directory not found")
    chunks = []
    for f in sorted(target_dir.glob("*.epub")):
        sz = f.stat().st_size
        chunks.append({
            "name": f.name,
            "title": f.stem.replace("_", " ").title(),
            "size": sz,
            "size_mb": round(sz / 1024 / 1024, 2),
            "url": f"/api/outputs/{subdir}/{f.name}",
        })
    return {"subdir": subdir, "count": len(chunks), "chunks": chunks}

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
        if not d.exists():
            return out
        for f in sorted(d.iterdir()):
            if f.is_file():
                out.append({"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime})
            elif f.is_dir():
                sub_count = len(list(f.glob("*.epub")))
                out.append({
                    "name": f.name,
                    "type": "dir",
                    "chunk_count": sub_count,
                    "size": sum(c.stat().st_size for c in f.rglob('*') if c.is_file()),
                    "zip_url": f"/api/outputs/{f.name}/zip",
                })
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
    files = sorted(PROFILES_DIR.glob("*.json")) if PROFILES_DIR.exists() else []
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
    s = _load_settings()
    host = s.get("host", HOST)
    port = int(s.get("port", PORT))
    reload = s.get("hot_reload", True)
    print(f"Boundless Web UI on http://{host}:{port} (hot_reload={reload})")
    print(f"Drop EPUBs into {INBOX_DIR} for autonomous processing")
    uvicorn.run(
        "web.server:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(SRC), str(WEB_DIR)],
        reload_includes=["*.py", "*.html", "*.css", "*.js", "*.json"],
        log_level=s.get("log_level", "info"),
    )

if __name__ == "__main__":
    run()
