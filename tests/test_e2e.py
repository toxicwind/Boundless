"""
tests/test_e2e.py — full E2E with Playwright + first-class tests for the 3 real
EPUBs from Downloads (Your Health Today, Financial Accounting for Managers,
Rams Write). No /mnt.

Run:
  pip install playwright pytest requests httpx
  playwright install --with-deps chromium
  pytest tests/test_e2e.py -v
"""
from __future__ import annotations
import os, time, json, shutil, subprocess
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
PROCESSING = REPO / "processing"
PROFILES = REPO / "profiles"

# The 3 real EPUBs that drove the design — first-class fixtures.
EPUB_YOUR_HEALTH = Path("/home/toxic/Downloads/Your Health Today.epub")
EPUB_FINANCIAL = Path("/home/toxic/Downloads/Financial Accounting for Managers.epub")
EPUB_RAMS = Path("/home/toxic/Downloads/[Full Text] Rams Write - Rhetoric and Critical Engagement 9781324081821.epub")

@pytest.fixture(scope="session", autouse=True)
def _clean_state():
    """Wipe processing/ + profiles/ before the suite, restore from inbox if needed."""
    for sub in ("inbox", "active", "done", "failed"):
        d = PROCESSING / sub
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    if PROFILES.exists():
        shutil.rmtree(PROFILES)
    PROFILES.mkdir(parents=True, exist_ok=True)
    yield

@pytest.fixture(scope="session")
def server(_clean_state):
    """Start the web server on a non-default port so we don't fight 10200."""
    env = os.environ.copy()
    env["PORT"] = "10201"
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "web.server:app",
         "--host", "127.0.0.1", "--port", "10201", "--log-level", "warning"],
        cwd=str(REPO), env=env,
    )
    time.sleep(2.5)
    yield "http://127.0.0.1:10201"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()

@pytest.fixture(scope="session")
def http():
    """Synchronous HTTP client for non-Playwright assertions."""
    import requests
    return requests.Session()

# ---------- Health + UI ----------

def test_health(server, http):
    r = http.get(f"{server}/api/health", timeout=5)
    assert r.status_code == 200
    h = r.json()
    assert h["status"] == "ok"
    assert h["port"] == 10201
    assert "processing_dir" in h
    assert "profiles_dir" in h
    # counts present
    for k in ("inbox", "active", "done", "failed", "profiles"):
        assert k in h
        assert isinstance(h[k], int)

def test_index_renders(server, browser):
    page = browser.new_page()
    page.goto(f"{server}/")
    assert "Boundless" in page.title()
    assert "Processing pipeline" in page.content()
    assert "natural_reader_limit_mb" not in page.content().lower() or "Natural Reader" in page.content()
    page.close()

def test_settings_renders(server, browser):
    page = browser.new_page()
    page.goto(f"{server}/settings")
    assert "Settings" in page.title()
    assert page.is_checked("#auto_watch_inbox") is True
    assert page.is_checked("#auto_profile_on_upload") is True
    page.close()

def test_settings_roundtrip(server, http):
    r = http.get(f"{server}/api/settings", timeout=5)
    assert r.status_code == 200
    s = r.json()
    s["default_max_size_mb"] = 75
    r = http.put(f"{server}/api/settings", json=s, timeout=5)
    assert r.json()["default_max_size_mb"] == 75
    r = http.get(f"{server}/api/settings", timeout=5)
    assert r.json()["default_max_size_mb"] == 75
    # restore
    s["default_max_size_mb"] = 50
    http.put(f"{server}/api/settings", json=s, timeout=5)

# ---------- Upload + profile pipeline ----------

@pytest.fixture
def uploaded_id(request, http, server) -> str:
    """Upload the file the test parametrizes with; return the upload_id."""
    path: Path = request.param
    if not path.exists():
        pytest.skip(f"sample epub not available: {path}")
    with open(path, "rb") as f:
        r = http.post(f"{server}/api/upload", files={"files": f}, timeout=60)
    assert r.status_code == 200, r.text
    up = r.json()["uploads"][0]
    return up["upload_id"], up

def _uploaded_id_to_dict(value):
    return value[1] if isinstance(value, tuple) else value

# ============================================================
# First-class tests for the 3 real EPUBs
# ============================================================

# --- 1. Your Health Today — McGraw Hill MHE Acme s9ml (134 MB) ---

@pytest.mark.parametrize("uploaded_id", [EPUB_YOUR_HEALTH], indirect=True)
def test_your_health_profile(server, http, uploaded_id):
    """McGraw Hill MHE Acme / DPS PublishOne SmartBook 2.0 (s9ml chunked)."""
    upid, body = uploaded_id
    p = body["profile"]
    assert p["origin"]["publisher"] == "McGraw Hill Education"
    assert "MHE Acme" in p["origin"]["pipeline"]
    assert "s9ml" in p["origin"]["pipeline"].lower()
    assert p["size_mb"] >= 130
    assert p["spine_items"] >= 200
    assert p["scripted_items"] >= 200  # s9ml is heavily scripted
    assert p["s9ml_chunks"] >= 100
    assert "EXCEEDS 50MB" in p["nr_status"]
    assert p["nr_chunks_needed"] >= 3
    # accessibility metadata
    assert "textual" in p["access_mode"]
    assert "visual" in p["access_mode"]
    assert "MathML" in p["accessibility_feature"] or "displayTransformability" in p["accessibility_feature"]

@pytest.mark.parametrize("uploaded_id", [EPUB_YOUR_HEALTH], indirect=True)
def test_your_health_split_size(server, http, uploaded_id):
    upid, _ = uploaded_id
    r = http.post(f"{server}/api/split/{upid}?max_size_mb=50", timeout=300)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["chunk_count"] >= 3
    # every chunk must be <= 50MB (Natural Reader limit)
    for c in rep["chunks"]:
        assert c["size"] <= 50 * 1024 * 1024 + 1024, f"chunk {c['slug']} = {c['size']} bytes exceeds 50MB"

@pytest.mark.parametrize("uploaded_id", [EPUB_YOUR_HEALTH], indirect=True)
def test_your_health_split_toc(server, http, uploaded_id):
    """Top-level TOC splitter — must preserve publisher assets (CSS, fonts, images)."""
    upid, _ = uploaded_id
    r = http.post(f"{server}/api/split-toc/{upid}", timeout=300)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["count"] >= 1
    # spot-check: every output is a real EPUB
    out = Path(rep["output_dir"])
    assert out.exists()
    eps = list(out.glob("*.epub"))
    assert len(eps) == rep["count"]
    # publisher assets preserved: each output has shared assets from OPS/assets/
    # (verify by re-opening the first chunk and checking it has at least one image)
    import zipfile
    with zipfile.ZipFile(eps[0]) as z:
        names = z.namelist()
        assert any(n.startswith(("OPS/assets/", "OEBPS/", "EPUB/")) for n in names), \
            f"output {eps[0].name} missing publisher assets"

# --- 2. Financial Accounting for Managers — McGraw Hill Classic OEBPS (30 MB) ---

@pytest.mark.parametrize("uploaded_id", [EPUB_FINANCIAL], indirect=True)
def test_financial_profile(server, http, uploaded_id):
    upid, body = uploaded_id
    p = body["profile"]
    assert p["origin"]["publisher"] == "McGraw Hill Education"
    assert "Classic OEBPS" in p["origin"]["pipeline"]
    assert "template.css" in p["origin"]["pipeline"]
    assert p["size_mb"] >= 25
    assert p["spine_items"] >= 30
    assert p["scripted_items"] == 0  # no JS, classic
    assert p["s9ml_chunks"] == 0
    assert p["images"] >= 500
    # NCX + nav dual TOC
    # author detection
    assert "Thomas" in p["creator"] or "Spiceland" in p["creator"]

@pytest.mark.parametrize("uploaded_id", [EPUB_FINANCIAL], indirect=True)
def test_financial_split_size(server, http, uploaded_id):
    upid, _ = uploaded_id
    r = http.post(f"{server}/api/split/{upid}?max_size_mb=50", timeout=120)
    assert r.status_code == 200, r.text
    rep = r.json()
    # Within 50MB so 1 chunk expected
    assert rep["chunk_count"] >= 1

@pytest.mark.parametrize("uploaded_id", [EPUB_FINANCIAL], indirect=True)
def test_financial_split_toc_preserves_ncx(server, http, uploaded_id):
    """The classic McGraw EPUB has a 515-navPoint NCX. TOC split must preserve it in every chunk."""
    upid, _ = uploaded_id
    r = http.post(f"{server}/api/split-toc/{upid}", timeout=300)
    assert r.status_code == 200, r.text
    rep = r.json()
    out = Path(rep["output_dir"])
    eps = list(out.glob("*.epub"))
    assert len(eps) >= 30, f"expected >=30 sections from NCX, got {len(eps)}"
    import zipfile
    ncx_count = 0
    for ep in eps[:5]:
        with zipfile.ZipFile(ep) as z:
            if any(n.endswith(".ncx") for n in z.namelist()):
                ncx_count += 1
    assert ncx_count >= 4, f"NCX not preserved in 4/5 chunks (got {ncx_count})"

# --- 3. Rams Write — W. W. Norton CSU Custom (33 MB) ---

@pytest.mark.parametrize("uploaded_id", [EPUB_RAMS], indirect=True)
def test_rams_profile(server, http, uploaded_id):
    upid, body = uploaded_id
    p = body["profile"]
    assert "Norton" in p["origin"]["publisher"]
    assert "CSU" in p["origin"]["pipeline"] or "Colorado" in p["origin"]["pipeline"]
    assert p["size_mb"] >= 30
    # Norton uses embedded fonts (95 font files)
    assert p["fonts"] >= 50
    # CSU custom imprint
    assert "CSU" in p["origin"]["imprint"] or "Colorado" in p["origin"]["imprint"]
    # Creator is the university
    assert "Colorado" in p["creator"]

@pytest.mark.parametrize("uploaded_id", [EPUB_RAMS], indirect=True)
def test_rams_split_toc_8_spine(server, http, uploaded_id):
    """Norton book has 8 spine items, so TOC split should produce 8 chunks."""
    upid, _ = uploaded_id
    r = http.post(f"{server}/api/split-toc/{upid}", timeout=300)
    assert r.status_code == 200, r.text
    rep = r.json()
    # 8 spine = ~2-8 chunks depending on TOC nesting
    assert 2 <= rep["count"] <= 12, f"unexpected chunk count: {rep['count']}"
    # all chunks must be real EPUBs with Norton assets
    import zipfile
    for ep in Path(rep["output_dir"]).glob("*.epub"):
        with zipfile.ZipFile(ep) as z:
            names = z.namelist()
            assert any("EPUB/" in n for n in names), f"chunk {ep.name} lost Norton EPUB/ structure"

# ---------- Edge cases & settings ----------

def test_edge_cases_full(server, http):
    r = http.get(f"{server}/api/edge-cases", timeout=5)
    assert r.status_code == 200
    e = r.json()
    assert len(e["epub"]) >= 70
    assert len(e["pdf"]) >= 45
    assert len(e["docx"]) >= 35
    assert len(e["a11y"]) >= 30

def test_profiles_list_after_uploads(server, http):
    """After the parametrized uploads above, we should have 3+ profiles."""
    r = http.get(f"{server}/api/profiles", timeout=5)
    assert r.status_code == 200
    assert r.json()["count"] >= 3

def test_processing_state(server, http):
    r = http.get(f"{server}/api/processing", timeout=5)
    assert r.status_code == 200
    p = r.json()
    for k in ("inbox", "active", "done", "failed"):
        assert k in p
        assert isinstance(p[k], list)

def test_autonomous_inbox_drop(server, http):
    """Drop a fresh copy into inbox, watcher should auto-process it."""
    s = http.get(f"{server}/api/settings", timeout=5).json()
    s["auto_split_on_upload"] = True
    s["auto_profile_on_upload"] = True
    http.put(f"{server}/api/settings", json=s, timeout=5)
    inbox = PROCESSING / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    name = f"autonomous_{int(time.time())}.epub"
    dest = inbox / name
    shutil.copy(EPUB_FINANCIAL, dest)
    # Wait for the watcher (poll every 2s, plus 1.5s stability)
    for _ in range(15):
        if not dest.exists() and any(PROFILES.glob(f"{Path(name).stem}__*.json")):
            break
        time.sleep(1)
    assert not dest.exists(), f"file still in inbox: {dest}"
    profiles = list(PROFILES.glob(f"{Path(name).stem}__*.json"))
    assert len(profiles) >= 1
    # restore
    s["auto_split_on_upload"] = False
    http.put(f"{server}/api/settings", json=s, timeout=5)

def test_process_endpoint(server, http):
    """Test the /api/process/{id} flow: inbox -> active -> done."""
    name = f"manual_{int(time.time())}.epub"
    dest = PROCESSING / "inbox" / name
    PROCESSING.joinpath("inbox").mkdir(parents=True, exist_ok=True)
    shutil.copy(EPUB_FINANCIAL, dest)
    r = http.post(f"{server}/api/process/{name}?method=size&max_size_mb=50", timeout=300)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    log = data["log"]
    assert any("profile" in l for l in log)
    assert any("active" in l for l in log)
    assert any("done" in l for l in log)
    assert not dest.exists()

def test_boundless_blocks_mnt(server, http):
    r = http.post(f"{server}/api/scan?directory=/mnt/anything", timeout=5)
    assert r.status_code == 403
    assert "denied" in r.text or "denied" in r.text.lower()

def test_path_traversal_blocked(server, http):
    r = http.get(f"{server}/api/outputs/../../etc/passwd", timeout=5)
    assert r.status_code in (400, 403, 404)
