"""
toc_split — Driver for the maximal EPUB 3 splitter.

Top-level: one EPUB per top-level TOC entry, with publisher files preserved
(MathML, CSS, images, fonts, metadata, navigation). Modular split:

  toc_parse — data models + EPUB3 NAV/NCX parsers
  toc_build — OPF mutation + chunk writer (file-preserving)
  toc_split — this driver (Book load, locations, run)

No /mnt. Pure pathlib + zipfile.
"""
from __future__ import annotations
import os
import sys
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from lxml import etree
except ImportError:
    print("Missing dependency: lxml")
    print("Run: python3 -m pip install --user lxml")
    raise SystemExit(1)

from .toc_parse import (
    TocNode,
    NCX_TYPE,
    PARSER,
    local_name,
    attr_local,
    xml_parse,
    clean_archive_path,
    resolve_href,
    parse_epub3_toc,
    parse_ncx_toc,
    sanitize_filename,
    unique_names,
)
from .toc_build import (
    set_package_title,
    set_new_identifier,
    restrict_spine,
    restrict_epub3_nav,
    restrict_ncx,
    build_one,
)


# ---------- data model: book ----------
@dataclass
class Book:
    source: Path
    names: set
    opf_path: str
    opf_dir: str
    opf_root: object
    manifest_by_id: dict
    manifest_path_by_id: dict
    manifest_id_by_path: dict
    spine_paths: list
    nav_path: Optional[str]
    nav_root: Optional[object]
    nav_toc: Optional[object]
    ncx_path: Optional[str]
    ncx_root: Optional[object]
    toc: list


# ---------- loader ----------
def load_book(source: Path) -> Book:
    """File-splitting preserves every ZIP entry except those rewritten by toc_build.
    Reads OPF + nav + NCX in one pass; never opens the same archive twice."""
    with zipfile.ZipFile(source, "r") as zf:
        names = set(zf.namelist())
        if "META-INF/container.xml" not in names:
            raise RuntimeError("META-INF/container.xml is missing")
        container = xml_parse(zf.read("META-INF/container.xml"), "container.xml")
        roots = container.xpath(".//*[local-name()='rootfile' and @full-path]")
        if not roots:
            raise RuntimeError("container.xml does not identify a package document")
        opf_path = clean_archive_path(roots[0].get("full-path"))
        if opf_path not in names:
            raise RuntimeError(f"Package document not found: {opf_path}")
        opf_root = xml_parse(zf.read(opf_path), opf_path)
        opf_dir = os.path.dirname(opf_path)

        manifest_by_id, manifest_path_by_id, manifest_id_by_path = {}, {}, {}
        nav_path = ncx_path = None
        for item in opf_root.xpath(".//*[local-name()='manifest']/*[local-name()='item']"):
            item_id = item.get("id")
            href = item.get("href")
            if not item_id or not href:
                continue
            item_path, _ = resolve_href(opf_path, href)
            manifest_by_id[item_id] = item
            manifest_path_by_id[item_id] = item_path
            manifest_id_by_path[item_path] = item_id
            props = set((item.get("properties") or "").lower().split())
            media_type = (item.get("media-type") or "").lower()
            if "nav" in props:
                nav_path = item_path
            if media_type == NCX_TYPE:
                ncx_path = item_path

        spine_paths = []
        for itemref in opf_root.xpath(".//*[local-name()='spine']/*[local-name()='itemref']"):
            path = manifest_path_by_id.get(itemref.get("idref"))
            if path:
                spine_paths.append(path)

        nav_root = xml_parse(zf.read(nav_path), nav_path) if nav_path in names else None
        nav_toc, toc = parse_epub3_toc(nav_root, nav_path) if nav_root is not None else (None, [])

        ncx_root = xml_parse(zf.read(ncx_path), ncx_path) if ncx_path in names else None
        if not toc and ncx_root is not None:
            toc = parse_ncx_toc(ncx_root)

    if not spine_paths:
        raise RuntimeError("The EPUB spine is empty or could not be parsed")
    if not toc:
        raise RuntimeError("No usable top-level TOC entries were found in EPUB navigation or NCX")
    return Book(source, names, opf_path, opf_dir, opf_root, manifest_by_id,
                manifest_path_by_id, manifest_id_by_path, spine_paths,
                nav_path, nav_root, nav_toc, ncx_path, ncx_root, toc)


# ---------- locators ----------
def locate_top_levels(book: Book):
    spine_index = {path: i for i, path in enumerate(book.spine_paths)}
    locations = []
    base_file = book.nav_path or book.ncx_path or book.opf_path
    for node in book.toc:
        path, fragment = resolve_href(base_file, node.href)
        if path not in spine_index:
            print(f"Warning: skipping TOC item not found in spine: {node.title} -> {node.href}")
            continue
        locations.append((node, spine_index[path], path, fragment))
    if not locations:
        raise RuntimeError("No top-level TOC target maps to the EPUB spine")
    return locations


# ---------- boundless file picker ----------
def choose_epub(arg: Optional[str] = None) -> Optional[Path]:
    """File picker: CLI arg → macOS native → Linux zenity/kdialog → stdin.
    No /mnt paths accepted."""
    if arg:
        p = Path(arg).expanduser().resolve()
        return p if p.is_file() and p.suffix.lower() == ".epub" else None
    # macOS native
    if sys.platform == "darwin":
        apple = '''
        tell application "System Events"
            activate
            set theFile to choose file with prompt "Select an EPUB file to split:"
            return POSIX path of theFile
        end tell
        '''
        try:
            r = subprocess.run(["osascript", "-e", apple], capture_output=True, text=True)
            selected = r.stdout.strip()
            return Path(selected).resolve() if selected else None
        except FileNotFoundError:
            pass
    # Linux: zenity / kdialog
    for tool in (
        ["zenity", "--file-selection", "--file-filter=EPUB files | *.epub", "--title=Select an EPUB file to split"],
        ["kdialog", "--getopenfilename", ".", "*.epub EPUB files"],
    ):
        try:
            r = subprocess.run(tool, capture_output=True, text=True, timeout=30)
            sel = r.stdout.strip()
            if sel:
                p = Path(sel).resolve()
                if p.is_file() and p.suffix.lower() == ".epub":
                    return p
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


# ---------- driver ----------
def split_epub_by_toc(source: Path, output_dir: Optional[Path] = None) -> dict:
    """Public API: split one EPUB by its top-level TOC.

    Returns a dict {output_dir, sections: [filenames]}. File-preserving split."""
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".epub":
        raise RuntimeError(f"Not an EPUB: {source}")
    book = load_book(source)
    locations = locate_top_levels(book)
    names = unique_names([entry[0] for entry in locations])
    output_dir = Path(output_dir) if output_dir else source.with_name(f"{source.stem}_split")
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    with zipfile.ZipFile(source, "r") as zf:
        for idx, ((node, start_i, start_path, start_fragment), filename) in enumerate(zip(locations, names)):
            if idx + 1 < len(locations):
                _, next_i, next_path, next_fragment = locations[idx + 1]
                if next_fragment:
                    end_i, end_path, end_fragment = next_i, next_path, next_fragment
                else:
                    end_i, end_path, end_fragment = next_i, None, ""
            else:
                end_i, end_path, end_fragment = len(book.spine_paths), None, ""
            output = output_dir / f"{filename}.epub"
            build_one(book, zf, node, start_i, start_path, start_fragment,
                      end_i, end_path, end_fragment, output)
            written.append(output.name)
    return {"source": str(source), "output_dir": str(output_dir), "sections": written, "count": len(written)}


def main():
    """CLI: python -m boundless.toc_split [path/to/book.epub]"""
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    src = choose_epub(arg)
    if not src:
        raise SystemExit("No valid EPUB file was selected")
    print(f"Starting adaptive TOC-driven EPUB 3 splitter on {src}")
    result = split_epub_by_toc(src)
    print(f"Built {result['count']} sections in {result['output_dir']}")
    print("Recommended validation: run EPUBCheck on the output folder.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
