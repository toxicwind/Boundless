"""
epub — file-split preserved EpubSplitter + lossless asset tracing
Uses ZIP entry preservation (not from-scratch regeneration).
"""
import os, re, json, zipfile, shutil, argparse, hashlib, tempfile, posixpath
from copy import deepcopy
from urllib.parse import unquote, urlparse
from collections import defaultdict, OrderedDict
from pathlib import Path
from typing import List, Set, Dict, Tuple, Optional, Any
try:
    from lxml import etree
    HAS_LXML=True

except ImportError:
    HAS_LXML=False
    import xml.etree.ElementTree as etree
from .models import DEFAULT_MAX_SIZE_BYTES, EPUB_NS, SHARED_ASSET_PATTERNS, ChunkMetadata, SplitReport, A11yLogger
from .utils import discover_chunk_assets, compute_shared_assets, _rewrite_opf, _strip_external_links, get_path_part, resolve_href
class EpubSplitter:
    """
    Split EPUBs by table of contents while preserving accessibility metadata.
    Designed for Natural Reader 50MB constraint and screen reader compatibility.
    """

    def __init__(self, max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES, logger: Optional[A11yLogger] = None):
        self.max_size = max_size_bytes
        self.logger = logger or A11yLogger()
        self.report = SplitReport()

    def split(self, src_path: str, out_dir: str) -> SplitReport:
        self.report.source_path = src_path
        self.report.source_size_bytes = os.path.getsize(src_path)
        self.report.source_format = "epub"

        if not os.path.isfile(src_path):
            self.logger.error("Source file not found: " + src_path)
            return self.report

        # Extract to temp directory for fast file access
        extract_dir = tempfile.mkdtemp(prefix="epub_extract_")
        try:
            with zipfile.ZipFile(src_path, "r") as z:
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            self.logger.error("Invalid ZIP/EPUB file: " + src_path)
            return self.report

        # Find OPF
        opf_path = self._find_opf(extract_dir)
        if not opf_path:
            self.logger.error("OPF file not found in EPUB")
            shutil.rmtree(extract_dir)
            return self.report

        opf_rel = os.path.relpath(opf_path, extract_dir).replace("\\", "/")
        opf_dir = posixpath.dirname(opf_rel)

        # Parse OPF
        opf_tree = etree.parse(opf_path)
        ns = {"opf": EPUB_NS["opf"]}

        manifest = {}
        manifest_by_href = {}
        for item in opf_tree.xpath("//opf:manifest/opf:item", namespaces=ns):
            iid = item.get("id")
            href = item.get("href")
            if iid and href:
                full = posixpath.normpath(posixpath.join(opf_dir, href))
                manifest[iid] = full
                manifest_by_href[full] = iid

        spine = []
        for itemref in opf_tree.xpath("//opf:spine/opf:itemref", namespaces=ns):
            spine.append(itemref.get("idref"))

        spine_full = [manifest[iid] for iid in spine if iid in manifest]

        # Build TOC mapping
        toc_map = self._build_toc_map(extract_dir, opf_tree, opf_dir, ns)

        # Group spine by directory (chapter-level grouping)
        dir_groups = defaultdict(list)
        for href in spine_full:
            dir_part = href.rsplit("/", 1)[0] if "/" in href else ""
            dir_groups[dir_part].append(href)

        # Scan assets
        asset_map = self._scan_assets(extract_dir, spine_full)

        # Discover shared assets
        shared_assets = self._discover_shared_assets(extract_dir)

        # Build chunks
        os.makedirs(out_dir, exist_ok=True)
        chunk_idx = 0

        for dir_name, files in sorted(dir_groups.items()):
            chunk_idx += 1
            name = self._dir_to_name(dir_name, toc_map)

            # Collect assets for this chunk
            chunk_assets = set()
            for f in files:
                chunk_assets.update(asset_map.get(f, set()))

            # Add shared assets
            chunk_assets.update(shared_assets)

            # Add non-HTML files from chunk directories
            chunk_dirs = {posixpath.dirname(f) for f in files if posixpath.dirname(f)}
            for d in chunk_dirs:
                abs_d = os.path.join(extract_dir, d)
                if os.path.exists(abs_d):
                    for root2, dirs2, files2 in os.walk(abs_d):
                        rel_root = os.path.relpath(root2, extract_dir).replace("\\", "/")
                        for f2 in files2:
                            rel_path = posixpath.join(rel_root, f2) if rel_root else f2
                            if not rel_path.lower().endswith((".xhtml", ".html", ".htm", ".opf")):
                                chunk_assets.add(rel_path)

            keep_hrefs = set(files) | chunk_assets
            keep_ids = set()
            new_spine = []
            for iid in spine:
                href = manifest.get(iid, "")
                if href in keep_hrefs:
                    keep_ids.add(iid)
                    if href in files:
                        new_spine.append(iid)

            # Rewrite OPF
            chunk_opf = deepcopy(opf_tree)
            chunk_manifest = chunk_opf.xpath("//opf:manifest", namespaces=ns)[0]
            for item in list(chunk_manifest):
                if item.get("id") not in keep_ids:
                    chunk_manifest.remove(item)

            chunk_spine = chunk_opf.xpath("//opf:spine", namespaces=ns)[0]
            for itemref in list(chunk_spine):
                if itemref.get("idref") not in new_spine:
                    chunk_spine.remove(itemref)

            guide = chunk_opf.xpath("//opf:guide", namespaces=ns)
            if guide:
                guide[0].getparent().remove(guide[0])

            # Write output EPUB
            out_path = os.path.join(out_dir, name + ".epub")
            with zipfile.ZipFile(out_path, "w") as zout:
                mimetype_path = os.path.join(extract_dir, "mimetype")
                if os.path.exists(mimetype_path):
                    zout.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)

                meta_dir = os.path.join(extract_dir, "META-INF")
                if os.path.exists(meta_dir):
                    for mf in os.listdir(meta_dir):
                        zout.write(os.path.join(meta_dir, mf), "META-INF/" + mf)

                zout.writestr(opf_rel, etree.tostring(chunk_opf, encoding="utf-8", xml_declaration=True))

                for href in keep_hrefs:
                    fp = os.path.join(extract_dir, href)
                    if os.path.exists(fp):
                        zout.write(fp, href)

            size = os.path.getsize(out_path)
            meta = ChunkMetadata(
                title=name,
                slug=name,
                source_file=src_path,
                page_count=len(files),
                byte_size=size,
                spine_files=files,
                asset_files=sorted(chunk_assets),
            )
            self.report.chunks.append(meta)
            self.report.total_output_size += size

            if size > self.max_size:
                self.logger.warn("Chunk exceeds max size: %s (%d MB > %d MB)" % (name, size // (1024*1024), self.max_size // (1024*1024)))

        self.report.chunk_count = len(self.report.chunks)
        shutil.rmtree(extract_dir)
        return self.report

    def _find_opf(self, extract_dir: str) -> Optional[str]:
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f.endswith(".opf"):
                    return os.path.join(root, f)
        return None

    def _build_toc_map(self, extract_dir: str, opf_tree, opf_dir: str, ns: Dict) -> Dict[str, str]:
        """Build mapping from file basename to TOC title."""
        toc_map = {}

        # Try NCX first
        ncx = None
        for item in opf_tree.xpath("//opf:manifest/opf:item", namespaces=ns):
            if item.get("media-type") == "application/x-dtbncx+xml":
                ncx = posixpath.normpath(posixpath.join(opf_dir, item.get("href")))
                break

        if ncx and os.path.exists(os.path.join(extract_dir, ncx)):
            try:
                ncx_data = open(os.path.join(extract_dir, ncx), "rb").read()
                ncx_data = re.sub(b' xmlns="[^"]+"', b'', ncx_data)
                ncx_root = etree.fromstring(ncx_data)
                for np in ncx_root.findall(".//navPoint"):
                    t = np.find(".//text")
                    c = np.find(".//content")
                    if t is not None and t.text and c is not None:
                        href = c.get("src", "")
                        base = href.split("/")[-1].split("#")[0].split("?")[0]
                        dir_part = href.rsplit("/", 1)[0] if "/" in href else ""
                        if dir_part:
                            toc_map[dir_part] = t.text.strip()
                        if base:
                            toc_map[base] = t.text.strip()
            except Exception:
                pass

        # Fallback to nav document
        if not toc_map:
            for item in opf_tree.xpath("//opf:manifest/opf:item", namespaces=ns):
                if "nav" in (item.get("properties") or "").lower():
                    nav_file = posixpath.normpath(posixpath.join(opf_dir, item.get("href")))
                    if os.path.exists(os.path.join(extract_dir, nav_file)):
                        try:
                            nd = open(os.path.join(extract_dir, nav_file), "rb").read()
                            nd = re.sub(b' xmlns="[^"]+"', b'', nd)
                            nr = etree.fromstring(nd)
                            for a in nr.findall(".//a"):
                                href = a.get("href", "")
                                title = "".join(a.itertext()).strip()
                                if href and title:
                                    base = href.split("/")[-1].split("#")[0].split("?")[0]
                                    dir_part = href.rsplit("/", 1)[0] if "/" in href else ""
                                    if dir_part:
                                        toc_map[dir_part] = title
                                    if base:
                                        toc_map[base] = title
                        except Exception:
                            pass

        return toc_map

    def _scan_assets(self, extract_dir: str, spine_files: List[str]) -> Dict[str, Set[str]]:
        """Scan HTML files for referenced assets."""
        asset_map = {}
        for href in spine_files:
            if not href.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            html_path = os.path.join(extract_dir, href)
            if not os.path.exists(html_path):
                continue
            try:
                tree = etree.parse(html_path)
                assets = set()
                for elem in tree.iter():
                    for attr in ("src", "href"):
                        val = elem.get(attr)
                        if val and not val.startswith(("http://", "https://", "mailto:", "data:", "#", "//")):
                            resolved = posixpath.normpath(unquote(posixpath.join(
                                posixpath.dirname(href) + "/" if posixpath.dirname(href) else "",
                                val.split("#")[0].split("?")[0]
                            )))
                            assets.add(resolved)
                asset_map[href] = assets
            except Exception:
                asset_map[href] = set()
        return asset_map

    def _discover_shared_assets(self, extract_dir: str) -> Set[str]:
        """Discover shared assets (CSS, images, fonts, etc.)."""
        shared = set()
        for root, dirs, files in os.walk(extract_dir):
            rel_root = os.path.relpath(root, extract_dir).replace("\\", "/")
            for f in files:
                rel_path = posixpath.join(rel_root, f) if rel_root else f
                rel_lower = rel_path.lower()
                if any(pat in rel_lower for pat in SHARED_ASSET_PATTERNS):
                    shared.add(rel_path)
        return shared

    def _dir_to_name(self, dir_name: str, toc_map: Dict[str, str]) -> str:
        """Convert directory name to human-readable chunk name."""
        clean = dir_name
        if clean.startswith("OPS/"):
            clean = clean[4:]
        if clean.startswith("OEBPS/"):
            clean = clean[6:]

        if not clean:
            return "Root"
        if clean == "s9ml/fm":
            return "Front_Matter"
        if clean.startswith("s9ml/chapter"):
            return clean.replace("s9ml/", "").replace("/", "_").title()

        # Try TOC mapping
        if clean in toc_map:
            title = toc_map[clean]
            clean_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:80]
            return clean_title or "Section"

        return clean.replace("/", "_").replace("s9ml_", "").title() or "Section"


# =============================================================================
# SECTION 6: PDF SPLITTER
# =============================================================================
