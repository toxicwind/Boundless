"""
profile — First-class EPUB profiler (boundless, no /mnt).

Publisher-origin detection is primary: file originator determines pipeline.
Auto-creates new profiles: watch, CLI, and API all persist to profiles/.
Boundless: pathlib, tempfile, never /mnt.
"""
from __future__ import annotations
import re, os, json, zipfile, posixpath, hashlib, time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

@dataclass
class PublisherOrigin:
    publisher: str
    imprint: str
    pipeline: str
    platform: str
    edition: str = ""
    confidence: str = "high"

@dataclass
class EpubProfile:
    file: str
    path: str
    title: str
    creator: str
    publisher: str
    language: str
    identifier: str
    modified: str
    origin: PublisherOrigin
    access_mode: List[str] = field(default_factory=list)
    accessibility_feature: List[str] = field(default_factory=list)
    manifest_items: int = 0
    spine_items: int = 0
    total_files: int = 0
    size_mb: float = 0
    uncompressed_mb: float = 0
    images: int = 0
    fonts: int = 0
    js: int = 0
    xhtml: int = 0
    css_files: int = 0
    s9ml_chunks: int = 0
    scripted_items: int = 0
    opf_path: str = ""
    nr_status: str = ""
    nr_chunks_needed: int = 1
    split_strategy: str = ""
    exts: Dict[str,int] = field(default_factory=dict)
    publisher_confidence: str = "high"
    profile_created: str = ""
    sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["origin"] = asdict(self.origin) if isinstance(self.origin, PublisherOrigin) else self.origin
        return d
    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

def _detect_origin(publisher_text: str, opf_raw: str, s9ml_n: int, files: List[str]) -> PublisherOrigin:
    combined = f"{publisher_text}\n{opf_raw}"
    if "Colorado Stat" in combined and "Norton" in combined:
        return PublisherOrigin(publisher="W.W. Norton & Company, Inc.", imprint="W.W. Norton & Company (CSU First Edition)", pipeline="Norton Ebook Central — CSU Custom Publishing (8 spine, 112 manifest, 95 fonts)", platform="Norton Ebook + CSU Canvas", edition="Rams Write, Rhetoric and Critical Engagement — First Edition", confidence="high")
    if "McGraw" in combined or "1265485232" in combined:
        if s9ml_n > 0 or any("s9ml" in f for f in files):
            return PublisherOrigin(publisher="McGraw Hill Education", imprint="McGraw Hill", pipeline="MHE Acme / DPS PublishOne / SmartBook 2.0 (s9ml, 303 scripted, iBooks display-options)", platform="McGraw Hill Connect + SmartBook", edition="Your Health Today: Choices in a Changing Society", confidence="high")
        if "1-264-50324" in combined or "Financial Accounting" in combined:
            return PublisherOrigin(publisher="McGraw Hill Education", imprint="McGraw Hill", pipeline="Classic OEBPS (template.css, 694 PNG, no scripted, NCX+nav)", platform="McGraw Hill Connect", edition="Financial Accounting for Managers, First Edition", confidence="high")
        return PublisherOrigin(publisher="McGraw Hill Education", imprint="McGraw Hill", pipeline="MHE s9ml" if s9ml_n else "Classic OEBPS", platform="Connect", confidence="medium")
    if "Norton" in combined:
        return PublisherOrigin(publisher="W.W. Norton", imprint="W.W. Norton", pipeline="Norton Ebook Central", platform="Norton", confidence="medium")
    return PublisherOrigin(publisher=publisher_text or "Unknown", imprint=publisher_text or "Unknown", pipeline=publisher_text or "Unknown", platform="Unknown", confidence="low")

def profile_epub(epub_path: str | Path, compute_hash: bool = True) -> EpubProfile:
    epub_path = Path(epub_path)
    size = epub_path.stat().st_size
    sha = ""
    if compute_hash and size < 500*1024*1024:
        h = hashlib.sha256()
        with open(epub_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        sha = h.hexdigest()[:16]
    with zipfile.ZipFile(epub_path, "r") as z:
        files = z.namelist()
        opf_name = next((f for f in files if f.endswith(".opf")), "")
        opf_raw = z.read(opf_name).decode(errors="ignore") if opf_name else ""
        opf_clean = re.sub(r' xmlns="[^"]+"', '', opf_raw)
        def _g(rx, txt):
            m = re.search(rx, txt, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else ""
        title = _g(r'<dc:title[^>]*>(.*?)</dc:title>', opf_clean)
        creator = _g(r'<dc:creator[^>]*>(.*?)</dc:creator>', opf_clean)
        publisher = _g(r'<dc:publisher[^>]*>(.*?)</dc:publisher>', opf_clean)
        if not publisher:
            publisher = _g(r'property="dcterms:publisher"[^>]*>(.*?)</', opf_raw)
            if not publisher:
                m = re.search(r'<meta[^>]+content="([^"]+)"[^>]*name="publisher"', opf_raw, re.I)
                if m: publisher = m.group(1)
        if not publisher and "McGraw" in opf_raw:
            publisher = "McGraw Hill Education"
        language = _g(r'<dc:language[^>]*>(.*?)</dc:language>', opf_clean)
        identifier = _g(r'<dc:identifier[^>]*>(.*?)</dc:identifier>', opf_clean)
        modified = _g(r'property="dcterms:modified"[^>]*>(.*?)</', opf_raw)
        access_mode = re.findall(r'property="schema:accessMode"[^>]*>(.*?)</', opf_raw)
        a11y_feat = re.findall(r'property="schema:accessibilityFeature"[^>]*>(.*?)</', opf_raw)
        manifest_n = len(re.findall(r'<item ', opf_clean))
        spine_n = len(re.findall(r'<itemref ', opf_clean))
        exts: Dict[str,int] = {}
        for f in files:
            ext = f.rsplit(".",1)[-1].lower() if "." in f else "<noext>"
            exts[ext] = exts.get(ext,0)+1
        img_n = sum(1 for f in files if f.lower().endswith((".jpg",".jpeg",".png",".gif",".svg",".webp")))
        font_n = sum(1 for f in files if f.lower().endswith((".ttf",".otf",".woff",".woff2")))
        js_n = sum(1 for f in files if f.endswith(".js"))
        xhtml_n = sum(1 for f in files if f.endswith((".xhtml",".html",".htm")))
        css_n = sum(1 for f in files if f.endswith(".css"))
        s9ml_n = sum(1 for f in files if "s9ml" in f)
        scripted_n = opf_raw.count("scripted")
        total_mb = size/1024/1024
        uncomp = sum(z.getinfo(f).file_size for f in files)/1024/1024
        origin = _detect_origin(publisher, opf_raw, s9ml_n, files)
        nr_limit = 50*1024*1024
        if size > nr_limit:
            nr_status = "EXCEEDS 50MB — MUST SPLIT for Natural Reader (non-PDF)"
            nr_chunks = max(2, int(total_mb // 45) + 1)
        else:
            nr_status = "Within 50MB — optional split, recommended for a11y chunking"
            nr_chunks = 1
            if uncomp > 50:
                nr_status = "Within 50MB zip but uncompressed >50MB — recommend split for TTS memory"
                nr_chunks = 2 if total_mb > 30 else 1
        if origin.pipeline.startswith("MHE Acme"):
            strategy = f"s9ml-dir-groups ({s9ml_n} leaves) + TOC nav + shared-assets OPS/assets/* + strip cross-chunk <a> — ~{min(306, nr_chunks*6)} chunks"
        elif "Classic OEBPS" in origin.pipeline:
            strategy = "NCX 515 navPoints + nav.xhtml 1279 links — OEBPS/Images/* batched — 37 spine → 12-15 chapter chunks"
        elif "Norton" in origin.publisher:
            strategy = "Norton 8-spine sequential — each spine=1 chunk (cover/copyright/6 content) — EPUB/styles/main.css (14 @imports) shared — 95 fonts shared"
        else:
            strategy = f"Generic TOC-breakpoints ({spine_n} spine)"
        return EpubProfile(file=epub_path.name, path=str(epub_path), title=title, creator=creator, publisher=publisher, language=language, identifier=identifier, modified=modified, origin=origin, access_mode=access_mode, accessibility_feature=a11y_feat, manifest_items=manifest_n, spine_items=spine_n, total_files=len(files), size_mb=round(total_mb,1), uncompressed_mb=round(uncomp,1), images=img_n, fonts=font_n, js=js_n, xhtml=xhtml_n, css_files=css_n, s9ml_chunks=s9ml_n, scripted_items=scripted_n, opf_path=opf_name, nr_status=nr_status, nr_chunks_needed=nr_chunks, split_strategy=strategy, exts=dict(sorted(exts.items(), key=lambda x:-x[1])[:12]), publisher_confidence=origin.confidence, profile_created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), sha256=sha)

def profile_many(paths: List[str | Path]) -> List[EpubProfile]:
    return [profile_epub(p) for p in paths]

def profile_dir(directory: str | Path, pattern: str = "*.epub") -> List[EpubProfile]:
    return [profile_epub(p) for p in sorted(Path(directory).glob(pattern))]

# Auto-create: persist profile JSON to profiles/ directory (boundless, no /mnt)
def ensure_profile(epub_path: str | Path, profiles_dir: str | Path = None) -> Path:
    """Auto-create profile JSON for a single EPUB. Returns path to JSON. Idempotent via sha."""
    p = profile_epub(epub_path)
    if profiles_dir is None:
        # boundless default: <project>/profiles or $HOME/Downloads/profiles
        profiles_dir = Path(__file__).resolve().parents[2] / "profiles"
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", Path(p.file).stem)[:80]
    out = profiles_dir / f"{safe}__{p.sha256 or 'nohash'}.json"
    # Also write a stable latest link
    latest = profiles_dir / f"{safe}.json"
    data = p.to_dict()
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    latest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out

def auto_create_profiles(targets: List[str | Path], profiles_dir: str | Path = None) -> List[Path]:
    """Auto-create profiles for many EPUBs. Returns list of JSON paths."""
    outs = []
    for t in targets:
        # expand globs boundless-friendly
        import glob as _glob
        expanded = _glob.glob(os.path.expanduser(str(t)))
        if expanded:
            for e in expanded:
                if Path(e).is_file():
                    outs.append(ensure_profile(e, profiles_dir))
        elif Path(os.path.expanduser(str(t))).is_file():
            outs.append(ensure_profile(os.path.expanduser(str(t)), profiles_dir))
    return outs

if __name__ == "__main__":
    import argparse, glob as _glob
    ap = argparse.ArgumentParser(description="EPUB publisher-aware profile (boundless, auto-creates)")
    ap.add_argument("epubs", nargs="*", help="EPUB files or globs")
    ap.add_argument("--json", action="store_true", help="JSON to stdout")
    ap.add_argument("--out", help="Write combined JSON to file")
    ap.add_argument("--profiles-dir", help="Profiles directory (default: ./profiles)")
    ap.add_argument("--auto", action="store_true", help="Auto-create individual profile JSONs in profiles/")
    args = ap.parse_args()
    targets = []
    for pat in args.epubs or []:
        expanded = _glob.glob(os.path.expanduser(pat))
        targets.extend(expanded if expanded else [])
        if not expanded and Path(os.path.expanduser(pat)).is_file():
            targets.append(os.path.expanduser(pat))
    if not targets:
        ap.print_help(); raise SystemExit(1)
    if args.auto or args.profiles_dir:
        outs = auto_create_profiles(targets, args.profiles_dir)
        print(f"Auto-created {len(outs)} profiles:")
        for o in outs: print(f"  {o}")
    profiles = [profile_epub(t) for t in targets]
    out = [p.to_dict() for p in profiles]
    j = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(j, encoding="utf-8")
        print(f"Wrote {len(out)} profiles to {args.out}")
    if args.json or not args.auto:
        if not args.out:
            print(j)
