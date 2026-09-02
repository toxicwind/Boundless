"""
utils — lossless helpers from Epubsplit-Corrected.py (verbatim preserved)
File-splitting preserves original ZIP entries: mimetype STORED, shared assets.
"""
import posixpath, re, xml.etree.ElementTree as ET
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
