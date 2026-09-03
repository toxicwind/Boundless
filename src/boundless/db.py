"""
src/boundless/db.py — Persistent SQLite storage for Boundless jobs, history, and inbox tracking.
Uses python's standard sqlite3 library (zero external dependencies).
"""
from __future__ import annotations
import sqlite3
import json
import time
import os
from pathlib import Path
from typing import List, Dict, Optional, Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    method TEXT NOT NULL,
    max_size_mb INTEGER NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER DEFAULT 0,
    stage TEXT DEFAULT 'queued',
    book_title TEXT,
    creator TEXT,
    publisher TEXT,
    origin_pipeline TEXT,
    nr_status TEXT,
    chunk_count INTEGER DEFAULT 0,
    total_output_size INTEGER DEFAULT 0,
    output_dir TEXT,
    chunks_json TEXT DEFAULT '[]',
    profile_json TEXT DEFAULT '{}',
    log_json TEXT DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    duration_seconds REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS inbox_items (
    filename TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    modified_at TEXT NOT NULL,
    title TEXT,
    creator TEXT,
    publisher TEXT,
    nr_status TEXT,
    origin_json TEXT DEFAULT '{}',
    profile_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
"""

def get_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA)

def create_job(
    db_path: Path,
    filename: str,
    file_path: str,
    file_size: int,
    method: str = "size",
    max_size_mb: int = 50,
    book_title: Optional[str] = None,
    creator: Optional[str] = None,
    publisher: Optional[str] = None,
    origin_pipeline: Optional[str] = None,
    nr_status: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    jid = job_id or f"job_{int(time.time()*1000)}_{os.urandom(3).hex()}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prof_json = json.dumps(profile or {}, ensure_ascii=False)
    
    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, filename, file_path, file_size, method, max_size_mb,
                status, progress, stage, book_title, creator, publisher,
                origin_pipeline, nr_status, profile_json, created_at, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', 10, 'starting', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                jid, filename, file_path, file_size, method, max_size_mb,
                book_title or filename, creator or "Unknown", publisher or "Unknown",
                origin_pipeline or "", nr_status or "ok", prof_json, now, now
            ),
        )
    return get_job(db_path, jid) or {}

def update_job_progress(
    db_path: Path,
    job_id: str,
    progress: int,
    stage: str,
    log_msg: Optional[str] = None,
) -> None:
    with get_db(db_path) as conn:
        row = conn.execute("SELECT log_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
        logs = json.loads(row["log_json"]) if row and row["log_json"] else []
        if log_msg:
            logs.append(f"[{time.strftime('%H:%M:%S')}] {log_msg}")
        conn.execute(
            "UPDATE jobs SET progress = ?, stage = ?, log_json = ? WHERE id = ?",
            (progress, stage, json.dumps(logs), job_id),
        )

def complete_job(
    db_path: Path,
    job_id: str,
    output_dir: str,
    chunks: List[Dict[str, Any]],
    total_output_size: int,
    log_messages: List[str],
    duration_seconds: float,
) -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with get_db(db_path) as conn:
        row = conn.execute("SELECT log_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
        existing_logs = json.loads(row["log_json"]) if row and row["log_json"] else []
        existing_logs.extend(log_messages)
        conn.execute(
            """
            UPDATE jobs SET
                status = 'completed',
                progress = 100,
                stage = 'done',
                chunk_count = ?,
                total_output_size = ?,
                output_dir = ?,
                chunks_json = ?,
                log_json = ?,
                completed_at = ?,
                duration_seconds = ?
            WHERE id = ?
            """,
            (
                len(chunks), total_output_size, output_dir,
                json.dumps(chunks, ensure_ascii=False),
                json.dumps(existing_logs, ensure_ascii=False),
                now, duration_seconds, job_id
            ),
        )
    return get_job(db_path, job_id) or {}

def fail_job(
    db_path: Path,
    job_id: str,
    error: str,
    log_messages: Optional[List[str]] = None,
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with get_db(db_path) as conn:
        row = conn.execute("SELECT log_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
        existing_logs = json.loads(row["log_json"]) if row and row["log_json"] else []
        if log_messages:
            existing_logs.extend(log_messages)
        existing_logs.append(f"[{time.strftime('%H:%M:%S')}] ERROR: {error}")
        conn.execute(
            """
            UPDATE jobs SET
                status = 'failed',
                stage = 'failed',
                error = ?,
                log_json = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (error, json.dumps(existing_logs, ensure_ascii=False), now, job_id),
        )

def get_job(db_path: Path, job_id: str) -> Optional[Dict[str, Any]]:
    with get_db(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["chunks"] = json.loads(d.get("chunks_json") or "[]")
        d["profile"] = json.loads(d.get("profile_json") or "{}")
        d["log"] = json.loads(d.get("log_json") or "[]")
        return d

def list_jobs(
    db_path: Path,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with get_db(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["chunks"] = json.loads(d.get("chunks_json") or "[]")
            d["profile"] = json.loads(d.get("profile_json") or "{}")
            d["log"] = json.loads(d.get("log_json") or "[]")
            out.append(d)
        return out

def delete_job(db_path: Path, job_id: str) -> bool:
    with get_db(db_path) as conn:
        res = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return res.rowcount > 0

def record_inbox_item(
    db_path: Path,
    filename: str,
    size: int,
    modified_at: str,
    title: Optional[str] = None,
    creator: Optional[str] = None,
    publisher: Optional[str] = None,
    nr_status: Optional[str] = None,
    origin: Optional[Dict[str, Any]] = None,
    profile_path: Optional[str] = None,
) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO inbox_items (
                filename, size, modified_at, title, creator, publisher, nr_status, origin_json, profile_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                size=excluded.size,
                modified_at=excluded.modified_at,
                title=coalesce(excluded.title, inbox_items.title),
                creator=coalesce(excluded.creator, inbox_items.creator),
                publisher=coalesce(excluded.publisher, inbox_items.publisher),
                nr_status=coalesce(excluded.nr_status, inbox_items.nr_status),
                origin_json=coalesce(excluded.origin_json, inbox_items.origin_json),
                profile_path=coalesce(excluded.profile_path, inbox_items.profile_path)
            """,
            (
                filename, size, modified_at, title, creator, publisher, nr_status,
                json.dumps(origin or {}, ensure_ascii=False), profile_path
            ),
        )

def remove_inbox_item(db_path: Path, filename: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM inbox_items WHERE filename = ?", (filename,))

def list_inbox_items(db_path: Path) -> List[Dict[str, Any]]:
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM inbox_items ORDER BY modified_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["origin"] = json.loads(d.get("origin_json") or "{}")
            out.append(d)
        return out

def backfill_from_disk(db_path: Path, processing_dir: Path, profiles_dir: Path) -> int:
    """Scan processing/done and processing/inbox, backfilling SQLite so existing runs show up in UI."""
    init_db(db_path)
    done_dir = processing_dir / "done"
    inbox_dir = processing_dir / "inbox"
    backfilled = 0

    # Load profiles to cross-reference metadata
    profiles_by_stem = {}
    if profiles_dir.exists():
        for p in profiles_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                # strip hashes or suffix
                stem = p.stem.split("__")[0]
                profiles_by_stem[stem] = data
                profiles_by_stem[p.stem] = data
                if data.get("file"):
                    profiles_by_stem[Path(data["file"]).stem] = data
            except Exception:
                pass

    if done_dir.exists():
        for item in sorted(done_dir.iterdir()):
            if item.is_dir():
                job_id = f"job_done_{item.name}"
                # check if already exists
                with get_db(db_path) as conn:
                    exists = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    if exists:
                        continue

                # find chunks inside
                chunks = []
                total_size = 0
                for cf in sorted(item.glob("*.epub")):
                    sz = cf.stat().st_size
                    total_size += sz
                    chunks.append({
                        "name": cf.name,
                        "title": cf.stem.replace("_", " ").title(),
                        "size": sz,
                        "size_mb": round(sz / 1024 / 1024, 2),
                        "url": f"/api/outputs/{item.name}/{cf.name}",
                    })

                # look up profile metadata
                stem_lookup = item.name.rsplit("_", 1)[0] if "_" in item.name else item.name
                prof = profiles_by_stem.get(item.name) or profiles_by_stem.get(stem_lookup) or {}
                origin = prof.get("origin", {})

                title = prof.get("title") or item.name.replace("_", " ").title()
                creator = prof.get("creator") or "Unknown"
                publisher = prof.get("publisher") or origin.get("publisher") or "Unknown"
                pipeline = origin.get("pipeline") or "Auto-split"
                nr_status = prof.get("nr_status") or ("ok" if all(c["size"] <= 50*1024*1024 for c in chunks) else "EXCEEDS_50MB")

                mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(item.stat().st_mtime))

                with get_db(db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            id, filename, file_path, file_size, method, max_size_mb,
                            status, progress, stage, book_title, creator, publisher,
                            origin_pipeline, nr_status, chunk_count, total_output_size,
                            output_dir, chunks_json, profile_json, log_json,
                            created_at, started_at, completed_at, duration_seconds
                        ) VALUES (?, ?, ?, ?, 'size', 50, 'completed', 100, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0)
                        """,
                        (
                            job_id, f"{item.name}.epub", str(item), total_size,
                            title, creator, publisher, pipeline, nr_status,
                            len(chunks), total_size, str(item),
                            json.dumps(chunks, ensure_ascii=False),
                            json.dumps(prof, ensure_ascii=False),
                            json.dumps([f"Imported from {item.name} ({len(chunks)} chunks)"], ensure_ascii=False),
                            mtime, mtime, mtime
                        ),
                    )
                backfilled += 1

    # Backfill inbox items
    if inbox_dir.exists():
        for f in inbox_dir.iterdir():
            if f.is_file():
                stem = f.stem
                stem_lookup = stem.split("__")[0] if "__" in stem else stem
                prof = profiles_by_stem.get(stem) or profiles_by_stem.get(stem_lookup) or {}
                origin = prof.get("origin", {})
                mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.stat().st_mtime))
                record_inbox_item(
                    db_path,
                    filename=f.name,
                    size=f.stat().st_size,
                    modified_at=mtime,
                    title=prof.get("title") or f.stem.replace("_", " ").title(),
                    creator=prof.get("creator") or "Unknown",
                    publisher=prof.get("publisher") or origin.get("publisher") or "Unknown",
                    nr_status=prof.get("nr_status") or "ok",
                    origin=origin,
                    profile_path=str(profiles_dir / f"{stem}.json") if (profiles_dir / f"{stem}.json").exists() else None,
                )
    return backfilled
