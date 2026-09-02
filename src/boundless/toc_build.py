"""
toc_build — EPUB package mutation + chunk ZIP building for the maximal splitter.

Pure functions, file-split preserved. No /mnt. Reuses toc_parse primitives.
"""
from __future__ import annotations
import copy
import uuid
import zipfile
from pathlib import Path
from typing import Optional
from lxml import etree

from .toc_parse import (
    TocNode,
    local_name,
    xml_parse,
    PARSER,
    XHTML_TYPES,
    NCX_TYPE,
)


# ---------- OPF mutation ----------
def set_package_title(opf_root, section_title: str):
    titles = opf_root.xpath(".//*[local-name()='metadata']/*[local-name()='title']")
    if titles:
        original = " ".join("".join(titles[0].itertext()).split())
        titles[0].text = f"{original}: {section_title}" if original else section_title


def set_new_identifier(opf_root):
    uid_name = opf_root.get("unique-identifier")
    if not uid_name:
        return
    ids = opf_root.xpath(
        ".//*[local-name()='metadata']/*[local-name()='identifier' and @id=$uid]", uid=uid_name
    )
    if ids:
        ids[0].text = f"urn:uuid:{uuid.uuid4()}"


def restrict_spine(opf_root, allowed_ids: set[str]):
    spines = opf_root.xpath(".//*[local-name()='spine']")
    if not spines:
        return
    spine = spines[0]
    for itemref in list(spine):
        if local_name(itemref) == "itemref" and itemref.get("idref") not in allowed_ids:
            spine.remove(itemref)


def restrict_epub3_nav(nav_root, toc_nav, selected_li):
    if nav_root is None or toc_nav is None:
        return
    ols = toc_nav.xpath("./*[local-name()='ol']") or toc_nav.xpath(".//*[local-name()='ol']")
    if not ols:
        return
    top_ol = ols[0]
    for child in list(top_ol):
        top_ol.remove(child)
    top_ol.append(copy.deepcopy(selected_li))


def restrict_ncx(ncx_root, selected_point):
    if ncx_root is None:
        return
    maps = ncx_root.xpath(".//*[local-name()='navMap']")
    if not maps:
        return
    navmap = maps[0]
    for child in list(navmap):
        if local_name(child) == "navpoint":
            navmap.remove(child)
    if selected_point is not None:
        navmap.append(copy.deepcopy(selected_point))


# ---------- XHTML body cropping ----------
def top_body_child_for_id(root, fragment: str):
    if not fragment:
        return None
    matches = root.xpath("//*[@id=$id or @*[local-name()='id']=$id]", id=fragment)
    if not matches:
        matches = root.xpath("//*[@name=$id]", id=fragment)
    if not matches:
        return None
    node = matches[0]
    bodies = root.xpath(".//*[local-name()='body']")
    if not bodies:
        return None
    body = bodies[0]
    while node.getparent() is not None and node.getparent() is not body:
        node = node.getparent()
    return node if node.getparent() is body else None


def crop_xhtml(data: bytes, start_fragment: str = "", end_fragment: str = "") -> bytes:
    if not start_fragment and not end_fragment:
        return data
    root = xml_parse(data, "content document")
    bodies = root.xpath(".//*[local-name()='body']")
    if not bodies:
        return data
    body = bodies[0]
    children = list(body)
    start_node = top_body_child_for_id(root, start_fragment) if start_fragment else None
    end_node = top_body_child_for_id(root, end_fragment) if end_fragment else None
    start_index = children.index(start_node) if start_node in children else 0
    end_index = children.index(end_node) if end_node in children else len(children)
    if start_fragment and start_node is None:
        print(f"  Warning: start fragment #{start_fragment} not found; keeping the full document")
    if end_fragment and end_node is None:
        print(f"  Warning: end fragment #{end_fragment} not found; keeping through document end")
    if end_index <= start_index:
        print("  Warning: fragment boundaries share or reverse a body block; keeping the block")
        end_index = min(start_index + 1, len(children))
    keep = set(children[start_index:end_index])
    for child in children:
        if child not in keep:
            body.remove(child)
    return etree.tostring(
        root, xml_declaration=True, encoding="utf-8",
        doctype=root.getroottree().docinfo.doctype or None,
    )


# ---------- per-chunk writer ----------
def build_one(book, zf: zipfile.ZipFile, node: TocNode, start_i: int,
              start_path: str, start_fragment: str, end_i: int,
              end_path: Optional[str], end_fragment: str, output: Path):
    """File-splitting preservation: rewrites only OPF + nav + cropped XHTML spine,
    copies the rest of the EPUB ZIP entries verbatim (publisher's CSS, images, fonts)."""
    selected_paths = book.spine_paths[start_i:end_i + (1 if end_fragment else 0)]
    if not selected_paths:
        selected_paths = [start_path]
    selected_set = set(selected_paths)
    allowed_ids = {book.manifest_id_by_path[p] for p in selected_paths if p in book.manifest_id_by_path}

    opf_root = copy.deepcopy(book.opf_root)
    restrict_spine(opf_root, allowed_ids)
    set_package_title(opf_root, node.title)
    set_new_identifier(opf_root)
    opf_bytes = etree.tostring(opf_root, xml_declaration=True, encoding="utf-8", pretty_print=False)

    nav_bytes = None
    if book.nav_root is not None and book.nav_path:
        nav_root = copy.deepcopy(book.nav_root)
        if local_name(node.source_element) == "li":
            toc_nav = _find_epub3_toc_nav(nav_root)
            restrict_epub3_nav(nav_root, toc_nav, node.source_element)
        nav_bytes = etree.tostring(
            nav_root, xml_declaration=True, encoding="utf-8",
            doctype=nav_root.getroottree().docinfo.doctype or None,
        )

    ncx_bytes = None
    if book.ncx_root is not None and book.ncx_path:
        ncx_root = copy.deepcopy(book.ncx_root)
        if local_name(node.source_element) == "navpoint":
            restrict_ncx(ncx_root, node.source_element)
        ncx_bytes = etree.tostring(ncx_root, xml_declaration=True, encoding="utf-8")

    with zipfile.ZipFile(output, "w") as out:
        out.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name in zf.namelist():
            if name == "mimetype":
                continue
            data = zf.read(name)
            if name == book.opf_path:
                data = opf_bytes
            elif nav_bytes is not None and name == book.nav_path:
                data = nav_bytes
            elif ncx_bytes is not None and name == book.ncx_path:
                data = ncx_bytes
            elif name in selected_set:
                first_fragment = start_fragment if name == start_path else ""
                last_fragment = end_fragment if end_path == name else ""
                media_id = book.manifest_id_by_path.get(name)
                media = book.manifest_by_id.get(media_id).get("media-type") if media_id else ""
                if media in {"application/xhtml+xml", "text/html"}:
                    data = crop_xhtml(data, first_fragment, last_fragment)
            elif name in book.spine_paths:
                continue
            out.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


def _find_epub3_toc_nav(root):
    """Local re-export of toc_parse.find_epub3_toc_nav for runtime symmetry."""
    from .toc_parse import find_epub3_toc_nav
    return find_epub3_toc_nav(root)
