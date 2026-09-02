#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB Splitter - Standalone Monolith (Batch & Multi-EPUB Supported)
Zero dependencies, no Calibre reboundlessd.

Behavior:
- Supports multiple files, directories, globs, or interactive picker:
  - CLI args: python3 Epubsplit-Corrected.py file1.epub file2.epub ~/Downloads/
  - No args: macOS native picker (multi-select) -> Tkinter (multi-select) -> CLI prompt
- Auto-creates <bookname>_split folder next to each book
- Content-aware: traces HTML->CSS->assets, plus subfolder + shared assets
- Strips cross-chapter links that would break
"""

import os
import sys
import glob
import shlex
import zipfile
import subprocess
import re
import xml.etree.ElementTree as ET
import posixpath
from urllib.parse import unquote
from collections import defaultdict

# ---------------------------------------------------------------------------
# Helpers borrowed & adapted from JimmXinu/EpubSplit
# ---------------------------------------------------------------------------
def get_path_part(n):
    relpath = posixpath.dirname(n)
    if len(relpath) > 0:
        relpath = relpath + "/"
    return relpath

def resolve_href(base, href):
    """Resolve a relative href against a base path (posix)."""
    # strip fragment and query for filesystem resolution, but keep original for later checks
    clean_href = href.split("#")[0].split("?")[0]
    return posixpath.normpath(unquote(posixpath.join(get_path_part(base), clean_href)))

def scan_html_for_refs(html_bytes, base_href):
    """Return a set of referenced asset paths found in HTML bytes."""
    refs = set()
    text = html_bytes.decode("utf-8", errors="ignore")
    for match in re.finditer(r'(?:src|href|xlink:href)=([\'"])(.*?)\1', text, re.IGNORECASE):
        raw = match.group(2)
        if not raw:
            continue
        if raw.startswith(("http://", "https://", "mailto:", "data:", "#")):
            continue
        if raw.startswith("//"):
            continue
        resolved = resolve_href(base_href, raw)
        refs.add(resolved)
    return refs

def scan_css_for_refs(css_bytes, base_href):
    """Return a set of asset paths referenced inside CSS via url() and @import."""
    refs = set()
    text = css_bytes.decode("utf-8", errors="ignore")
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    for match in re.finditer(r'@import\s+(?:url\()?["\']?([^"\'\);]+)', text, re.IGNORECASE):
        raw = match.group(1)
        if raw:
            refs.add(resolve_href(base_href, raw))
    for match in re.finditer(r'url\(["\']?(.*?)["\']?\)', text, re.IGNORECASE):
        raw = match.group(1)
        if raw and not raw.startswith(("http://", "https://", "data:", "#")):
            refs.add(resolve_href(base_href, raw))
    return refs

def _cascade_css(src_zip, css_path, assets, visited_css, all_files, spine_files_set):
    """Recursively scan CSS for url() and @import references."""
    try:
        css_bytes = src_zip.read(css_path)
    except Exception:
        return
    css_refs = scan_css_for_refs(css_bytes, css_path)
    for cr in css_refs:
        if cr in all_files and cr not in spine_files_set:
            assets.add(cr)
            if cr.lower().endswith(".css") and cr not in visited_css:
                visited_css.add(cr)
                _cascade_css(src_zip, cr, assets, visited_css, all_files, spine_files_set)

def discover_chunk_assets(src_zip, chunk_files, all_files, spine_files_set):
    assets = set()
    visited_css = set()
    for full_path in chunk_files:
        try:
            html_bytes = src_zip.read(full_path)
        except Exception:
            continue
        refs = scan_html_for_refs(html_bytes, full_path)
        for ref in refs:
            if ref in all_files and ref not in spine_files_set:
                assets.add(ref)
                if ref.lower().endswith(".css") and ref not in visited_css:
                    visited_css.add(ref)
                    _cascade_css(src_zip, ref, assets, visited_css, all_files, spine_files_set)
    spine_dirs = set()
    for full_path in chunk_files:
        d = get_path_part(full_path)
        if d:
            spine_dirs.add(d)
    for candidate in all_files:
        if candidate in spine_files_set:
            continue
        for d in spine_dirs:
            if candidate.startswith(d):
                # keep images/css/fonts under same folder, but not other xhtml that is spine
                if not candidate.lower().endswith((".xhtml", ".html", ".htm", ".opf")):
                    assets.add(candidate)
                break
    return assets

def compute_shared_assets(src_zip, spine_files, all_files, spine_files_set):
    shared = set()
    common_prefixes = ("css/", "images/", "fonts/", "styles/", "img/", "image/", "pics/")
    global_refs = set()
    for sp in spine_files:
        try:
            refs = scan_html_for_refs(src_zip.read(sp), sp)
            global_refs.update(refs)
            for r in refs:
                if r.lower().endswith(".css"):
                    try:
                        global_refs.update(scan_css_for_refs(src_zip.read(r), r))
                    except Exception:
                        pass
        except Exception:
            pass
    for ref in global_refs:
        if ref in all_files and ref not in spine_files_set:
            low = ref.lower()
            if any(low.startswith(p) or ("/" + p) in low for p in common_prefixes):
                shared.add(ref)
    return shared

def _rewrite_opf(opf_root, keep_manifest_ids, new_spine_idrefs):
    xml_str = ET.tostring(opf_root, encoding="utf-8")
    tree = ET.fromstring(xml_str)
    manifest_elem = tree.find(".//manifest")
    if manifest_elem is not None:
        for child in list(manifest_elem):
            if child.get("id") not in keep_manifest_ids:
                manifest_elem.remove(child)
    spine_elem = tree.find(".//spine")
    if spine_elem is not None:
        for child in list(spine_elem):
            if child.get("idref") not in new_spine_idrefs:
                spine_elem.remove(child)
    guide_elem = tree.find(".//guide")
    if guide_elem is not None:
        for child in list(guide_elem):
            guide_elem.remove(child)
    ET.register_namespace("", "http://www.idpf.org/2007/opf")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    out = ET.tostring(tree, encoding="utf-8")
    if b'xmlns="http://www.idpf.org/2007/opf"' not in out:
        out = out.replace(b'<package', b'<package xmlns="http://www.idpf.org/2007/opf"', 1)
    return out

def _strip_external_links(html_bytes, chunk_set, current_path):
    text = html_bytes.decode("utf-8", errors="ignore")
    def replacer(m):
        tag_open = m.group(1)
        inner = m.group(2)
        href_match = re.search(r'href=["\'](.*?)["\']', tag_open, re.IGNORECASE)
        if not href_match:
            return m.group(0)
        href = href_match.group(1)
        if href.startswith("#"):
            return m.group(0)
        if href.startswith(("http://", "https://", "mailto:", "data:")):
            return m.group(0)
        resolved = resolve_href(current_path, href)
        # resolved is already fragment-stripped, compare to chunk_set (which has no fragments)
        if resolved in chunk_set:
            return m.group(0)
        return inner
    return re.sub(r'<a\b([^>]*?)>(.*?)</a>', replacer, text, flags=re.IGNORECASE | re.DOTALL).encode("utf-8")

# ---------------------------------------------------------------------------
# File Target Resolution & Discovery
# ---------------------------------------------------------------------------
def expand_epub_targets(targets):
    """Given a list of strings (paths, globs, or directories), return a list of unique valid EPUB file paths."""
    resolved = []
    for target in targets:
        if isinstance(target, (list, tuple)):
            resolved.extend(expand_epub_targets(target))
            continue
        target = str(target).strip().strip('"').strip("'")
        if not target:
            continue
        expanded_target = os.path.abspath(os.path.expanduser(target))
        if os.path.isdir(expanded_target):
            # Scan directory for .epub files (ignoring output directories)
            for root, dirs, files in os.walk(expanded_target):
                # Don't recurse into *_split directories
                dirs[:] = [d for d in dirs if not d.endswith("_split")]
                for f in files:
                    if f.lower().endswith(".epub") and not f.startswith("."):
                        resolved.append(os.path.join(root, f))
        elif os.path.isfile(expanded_target) and expanded_target.lower().endswith(".epub"):
            resolved.append(expanded_target)
        else:
            # Try glob
            glob_matches = glob.glob(os.path.expanduser(target))
            for m in glob_matches:
                m_abs = os.path.abspath(m)
                if os.path.isfile(m_abs) and m_abs.lower().endswith(".epub"):
                    resolved.append(m_abs)
                elif os.path.isdir(m_abs):
                    for f in os.listdir(m_abs):
                        if f.lower().endswith(".epub") and not f.startswith("."):
                            resolved.append(os.path.join(m_abs, f))

    # Deduplicate while preserving discovery order
    seen = set()
    deduped = []
    for r in resolved:
        norm = os.path.normpath(r)
        if norm not in seen and os.path.isfile(norm):
            seen.add(norm)
            deduped.append(norm)
    return deduped

def get_source_files(cli_args=None):
    """Find source EPUB files from CLI args, GUI pickers (multi-select), or CLI prompt."""
    if cli_args:
        files = expand_epub_targets(cli_args)
        if files:
            return files

    # macOS GUI file dialog (multi-select enabled)
    if sys.platform == "darwin":
        script = (
            'tell application "System Events"\n'
            '    activate\n'
            '    set theFiles to choose file with prompt "Select EPUB file(s) to split:" with multiple selections allowed\n'
            '    set posixPaths to ""\n'
            '    repeat with aFile in theFiles\n'
            '        set posixPaths to posixPaths & (POSIX path of aFile) & "\\n"\n'
            '    end repeat\n'
            '    return posixPaths\n'
            'end tell\n'
        )
        try:
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            files = expand_epub_targets(lines)
            if files:
                return files
        except Exception:
            pass

    # Tkinter GUI file dialog (multi-select enabled)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        root.update()
        selected = filedialog.askopenfilenames(
            title="Select EPUB file(s) to split:",
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")]
        )
        root.destroy()
        if selected:
            files = expand_epub_targets(list(selected))
            if files:
                return files
    except Exception:
        pass

    # CLI prompt fallback
    try:
        raw = input("Enter path(s) to EPUB file(s), folder (e.g. ~/Downloads), or wildcard pattern: ").strip()
    except (EOFError, KeyboardInterrupt):
        return []

    if raw:
        try:
            parts = shlex.split(raw)
        except Exception:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
        files = expand_epub_targets(parts)
        if files:
            return files

    return []

# ---------------------------------------------------------------------------
# Core Splitting Engine
# ---------------------------------------------------------------------------
def split_epub(source_epub):
    """Splits a single EPUB file into structured chapter/section parts."""
    base_dir = os.path.dirname(source_epub)
    book_name = os.path.splitext(os.path.basename(source_epub))[0]
    output_dir = os.path.join(base_dir, book_name + "_split")
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(source_epub, "r") as src:
        all_files = src.namelist()
        opf_file = next((f for f in all_files if f.endswith(".opf")), None)
        if not opf_file:
            raise RuntimeError("Could not find OPF manifest in EPUB.")
        opf_dir = os.path.dirname(opf_file)
        opf_content = src.read(opf_file)
        opf_content_clean = re.sub(b' xmlns="[^"]+"', b'', opf_content)
        try:
            root = ET.fromstring(opf_content_clean)
        except Exception as e:
            raise RuntimeError(f"Error parsing OPF XML: {e}")

        manifest = {}
        manifest_items = {}
        manifest_by_href = {}
        for item in root.findall(".//item"):
            item_id = item.get("id")
            href = item.get("href")
            if item_id and href:
                full = posixpath.normpath(posixpath.join(opf_dir, href))
                manifest[item_id] = href
                manifest_items[item_id] = item
                manifest_by_href[full] = item

        spine_files = []
        spine_idrefs = []
        for itemref in root.findall(".//itemref"):
            idref = itemref.get("idref")
            if idref in manifest:
                href = manifest[idref]
                full_path = posixpath.normpath(posixpath.join(opf_dir, href))
                spine_files.append(full_path)
                spine_idrefs.append(idref)

        spine_xhtml = [f for f in spine_files if f.endswith((".xhtml", ".html", ".htm"))]
        if not spine_xhtml:
            raise RuntimeError("Could not determine reading order from spine.")

        spine_files_set = set(spine_files)
        toc_breakpoints = {}
        ncx_file = next((f for f in all_files if f.endswith(".ncx")), None)
        if ncx_file:
            ncx_content = src.read(ncx_file)
            ncx_content = re.sub(b' xmlns="[^"]+"', b'', ncx_content)
            try:
                ncx_root = ET.fromstring(ncx_content)
                for navpoint in ncx_root.findall(".//navPoint"):
                    text_node = navpoint.find(".//text")
                    content_node = navpoint.find(".//content")
                    if text_node is not None and text_node.text and content_node is not None:
                        src_href = content_node.get("src")
                        if src_href:
                            basename = src_href.split("/")[-1].split("#")[0].split("?")[0]
                            if basename not in toc_breakpoints:
                                toc_breakpoints[basename] = text_node.text.strip()
            except Exception:
                pass

        if not toc_breakpoints:
            for item in root.findall(".//item"):
                props = item.get("properties", "")
                if "nav" in props.lower():
                    nav_href = item.get("href")
                    nav_file = posixpath.normpath(posixpath.join(opf_dir, nav_href))
                    if nav_file in all_files:
                        nav_content = src.read(nav_file)
                        nav_content = re.sub(b' xmlns="[^"]+"', b'', nav_content)
                        try:
                            nav_root = ET.fromstring(nav_content)
                            for a_tag in nav_root.findall(".//a"):
                                href = a_tag.get("href")
                                title = "".join(a_tag.itertext()).strip()
                                if href and title:
                                    basename = href.split("/")[-1].split("#")[0].split("?")[0]
                                    if basename not in toc_breakpoints:
                                        toc_breakpoints[basename] = title
                        except Exception:
                            pass

        chunks = []
        current_chunk_name = "Front_Matter"
        current_chunk_files = []
        for full_path in spine_xhtml:
            basename = full_path.split("/")[-1]
            new_name = None
            if basename in toc_breakpoints:
                new_name = toc_breakpoints[basename]
            else:
                try:
                    html_content = src.read(full_path).decode("utf-8", errors="ignore")
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE)
                    if title_match:
                        page_title = title_match.group(1).strip()
                        if re.match(r"^(chapter|appendix|glossary|index|preface|part|module|unit)\b", page_title, re.IGNORECASE):
                            new_name = page_title
                except Exception:
                    pass
            if not new_name:
                fn_match = re.match(r"^(ch(?:apter)?\s*[_0-9]+|app(?:endix)?\s*[_a-z0-9]+|fm|index|glossary|preface)", basename, re.IGNORECASE)
                if fn_match:
                    new_name = fn_match.group(1).capitalize()
            if new_name:
                clean_new = re.sub(r"[^\w]", "", new_name).lower()
                clean_curr = re.sub(r"[^\w]", "", current_chunk_name).lower()
                if clean_new != clean_curr and current_chunk_files:
                    chunks.append((current_chunk_name, current_chunk_files))
                    current_chunk_files = []
                current_chunk_name = new_name
            current_chunk_files.append(full_path)
        if current_chunk_files:
            chunks.append((current_chunk_name, current_chunk_files))

        final_chunks = []
        seen_names = {}
        def sanitize_filename(name):
            clean = re.sub(r"[^\w\s-]", "", name)
            return clean.strip().replace(" ", "_")[:80]
        for name, files in chunks:
            clean_name = sanitize_filename(name)
            if not clean_name:
                clean_name = "Section"
            if clean_name in seen_names:
                seen_names[clean_name] += 1
                final_name = clean_name + "_" + str(seen_names[clean_name])
            else:
                seen_names[clean_name] = 1
                final_name = clean_name
            final_chunks.append((final_name, files))

        shared_assets = compute_shared_assets(src, spine_files, all_files, spine_files_set)

        for ch_name, chunk_files in final_chunks:
            final_epub_path = os.path.join(output_dir, ch_name + ".epub")
            chunk_set = set(chunk_files)
            chunk_assets = discover_chunk_assets(src, chunk_files, all_files, spine_files_set)
            chunk_assets.update(shared_assets)
            keep_manifest_ids = set()
            new_spine_idrefs = []
            for idx, idref in enumerate(spine_idrefs):
                if spine_files[idx] in chunk_set:
                    keep_manifest_ids.add(idref)
                    new_spine_idrefs.append(idref)
            for item_id, href in manifest.items():
                full = posixpath.normpath(posixpath.join(opf_dir, href))
                if full in chunk_assets:
                    keep_manifest_ids.add(item_id)

            with zipfile.ZipFile(final_epub_path, "w") as dst:
                if "mimetype" in all_files:
                    dst.writestr("mimetype", src.read("mimetype"), compress_type=zipfile.ZIP_STORED)
                for item in all_files:
                    if item == "mimetype":
                        continue
                    if item == opf_file:
                        new_opf = _rewrite_opf(root, keep_manifest_ids, new_spine_idrefs)
                        dst.writestr(item, new_opf, compress_type=zipfile.ZIP_DEFLATED)
                        continue
                    if item in spine_files:
                        if item in chunk_set:
                            data = src.read(item)
                            data = _strip_external_links(data, chunk_set, item)
                            dst.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)
                        continue
                    if item in chunk_assets:
                        try:
                            dst.writestr(item, src.read(item), compress_type=zipfile.ZIP_DEFLATED)
                        except Exception:
                            pass
                        continue
                    if item.startswith("META-INF/"):
                        try:
                            dst.writestr(item, src.read(item), compress_type=zipfile.ZIP_DEFLATED)
                        except Exception:
                            pass

    return {
        "success": True,
        "epub": source_epub,
        "book_name": book_name,
        "output_dir": output_dir,
        "sections": len(final_chunks),
        "shared_assets": len(shared_assets)
    }

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Content-Aware EPUB Splitter (Batch & Monolith)")
    print("=" * 60)

    source_files = get_source_files(sys.argv[1:])
    if not source_files:
        print("No valid EPUB files selected or found. Exiting.")
        sys.exit(1)

    print(f"Found {len(source_files)} EPUB file(s) to process.")
    results = []
    output_dirs = []

    for idx, epub_path in enumerate(source_files, 1):
        print(f"\n[{idx}/{len(source_files)}] Splitting: {os.path.basename(epub_path)}")
        try:
            res = split_epub(epub_path)
            results.append(res)
            if res.get("output_dir"):
                output_dirs.append(res["output_dir"])
            print(f"  -> Success: {res['sections']} sections created in:")
            print(f"     {res['output_dir']}")
        except Exception as e:
            print(f"  -> Error processing {os.path.basename(epub_path)}: {e}")
            results.append({"success": False, "epub": epub_path, "error": str(e)})

    # Print summary
    success_count = sum(1 for r in results if r.get("success"))
    print("\n" + "=" * 60)
    print(f"Summary: {success_count}/{len(source_files)} EPUBs successfully split.")
    for r in results:
        base = os.path.basename(r["epub"])
        if r.get("success"):
            print(f"  [OK]   {base} -> {r['sections']} sections ({r['output_dir']})")
        else:
            print(f"  [FAIL] {base} -> {r.get('error')}")
    print("=" * 60)

    # Auto-open output folder if running interactively with a display
    if output_dirs and sys.stdout.isatty():
        try:
            target_open = output_dirs[0] if len(output_dirs) == 1 else os.path.dirname(output_dirs[0])
            if sys.platform == "darwin":
                subprocess.run(["open", target_open], check=False)
            elif sys.platform.startswith("win"):
                os.startfile(target_open)
            elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
                subprocess.run(["xdg-open", target_open], check=False)
        except Exception:
            pass

if __name__ == "__main__":
    main()
