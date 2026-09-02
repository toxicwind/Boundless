# Sovereign Boundless — Document Splitter

[![CI](https://github.com/toxicwind/boundless/actions/workflows/ci.yml/badge.svg)](https://github.com/toxicwind/boundless/actions)
[![codeql](https://github.com/toxicwind/boundless/actions/workflows/codeql.yml/badge.svg)](https://github.com/toxicwind/boundless/security/code-scanning)
[![PyPI](https://img.shields.io/pypi/v/boundless.svg)](https://pypi.org/project/boundless/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Accessibility-first EPUB/PDF/DOCX splitter. Web UI on port 10200. Auto-creates publisher-aware profiles. Part of the Sovereign ecosystem — no `/mnt`, never container-absolute paths.

**Brand:** `boundless` = **ADA** (Title II, Section 508) + **IDEA** (K-12 IEP/504) + i18n (universal design). The name frames the product as the lawful, child-through-university accessibility stack, within the Sovereign framework.

## Pipeline

```
[drop in]  →  processing/inbox/  →  (autonomous watcher)  →  active  →  done  →  profiles/
                                                  ↓
                                                failed
```

- **`processing/inbox/`** — fresh uploads + autonomous drop-in target
- **`processing/active/`** — currently being processed
- **`processing/done/`** — completed splits
- **`processing/failed/`** — failed/cancelled
- **`profiles/`** — auto-created JSON profiles
- **`settings.json`** — editable from `/settings`

## Quick start

```bash
git clone https://github.com/toxicwind/boundless
cd boundless
pip install -e ".[full]"
python boundless.py                  # serves http://localhost:10200 + opens browser
```

## CLI

```bash
# Top-level TOC-driven split (preserves publisher's CSS, fonts, images, MathML)
python -m ada_splitter.toc_split ~/Downloads/book.epub

# Profile a single EPUB
python -m ada_splitter.profile ~/Downloads/book.epub --auto

# Batch split a directory
python -m ada_splitter.batch ~/Downloads/ -o ./out -s 50 -j 4
```

## Web API (default port 10200)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Dashboard |
| GET | `/settings` | Settings UI |
| GET | `/api/health` | status + counts |
| GET/PUT | `/api/settings` | read/update `settings.json` |
| POST | `/api/upload` | upload EPUBs (auto-profile) |
| POST | `/api/process/{id}` | inbox → active → done/failed |
| GET | `/api/profile/{id}` | re-profile a stored upload |
| POST | `/api/split/{id}` | size-based split |
| POST | `/api/split-toc/{id}` | top-level TOC split |
| GET | `/api/outputs/{sub}/{f}` | download a chunk |
| GET | `/api/processing` | list inbox/active/done/failed |
| POST | `/api/scan?directory=...` | scan dir + auto-create profiles |
| GET/DELETE | `/api/profiles[/{file}]` | manage profiles |
| GET | `/api/edge-cases` | full EdgeCaseRegistry |

## Settings (`settings.json`)

All editable from `/settings` UI or via `PUT /api/settings`:

- `auto_watch_inbox` — process new files in `inbox/` automatically
- `auto_profile_on_upload` — create profile JSON on every upload
- `auto_split_on_upload` — run split immediately on upload
- `default_max_size_mb` — Natural Reader non-PDF limit (50MB)
- `default_split_method` — `size` or `toc`
- `scan_extensions`, `scan_recursive` — scanner config
- `tray_enabled` — system tray icon (pystray)
- `auto_open_browser_on_launch` — open browser on launch
- `theme` — `dark` or `light`

## Profile-as-first-class

`profile_epub()` returns `EpubProfile` with `PublisherOrigin`:
- **McGraw Hill** — MHE Acme s9ml (303 scripted, iBooks display-options) vs Classic OEBPS
- **W.W. Norton** — CSU Custom Publishing (Rams Write, 8 spine, 95 fonts)
- **Plus** any EPUB (auto-detected) with `confidence: high/medium/low`

`ensure_profile()` and `auto_create_profiles()` persist JSONs to `profiles/`.

## Build cross-platform binary

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean boundless.spec
# Result: dist/boundless (Linux/macOS) or dist/boundless/boundless.exe (Windows)
```

CI builds for Ubuntu/macOS/Windows and uploads artifacts to Releases on `v*` tags.

## License

MIT.
