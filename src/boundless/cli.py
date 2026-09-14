"""boundless.cli — command-line entry points for the boundless package."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    """boundless — split EPUB/PDF/DOCX documents from the command line."""
    from .universal import UniversalSplitter
    from .models import DEFAULT_MAX_SIZE_MB

    ap = argparse.ArgumentParser(prog="boundless", description="Boundless — accessible document splitter")
    ap.add_argument("input", help="Input file (.epub, .pdf, .docx)")
    ap.add_argument("-o", "--out-dir", default="./boundless-output", help="Output directory for chunks")
    ap.add_argument("--max-mb", type=int, default=DEFAULT_MAX_SIZE_MB, help="Max chunk size in MB")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        print(f"error: not a file: {src}", file=sys.stderr)
        return 2

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    splitter = UniversalSplitter(max_size_mb=args.max_mb, verbose=args.verbose)
    report = splitter.split(str(src), str(out))
    print(f"split {src.name}: {len(report.chunks)} chunks -> {out}")
    if report.errors:
        for e in report.errors:
            print(f"  error: {e}", file=sys.stderr)
        return 1
    return 0


def web(argv=None) -> int:
    """boundless-web — launch the Boundless web UI (FastAPI)."""
    # web/ is a top-level package (shipped alongside boundless).
    # When running from a source checkout, ensure repo root is importable.
    repo_root = Path(__file__).resolve().parents[2]
    web_pkg = repo_root / "web"
    if web_pkg.is_dir() and str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from web.server import run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
