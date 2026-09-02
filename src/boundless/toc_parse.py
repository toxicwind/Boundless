"""
toc_parse — EPub 3 navigation + NCX parsing primitives for the maximal splitter.

Pure functions, file-split preserved. No /mnt, no boundless-runtime concerns here.
"""
from __future__ import annotations
import re
import posixpath
import unicodedata
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urlsplit
from lxml import etree

NCX_TYPE = "application/x-dtbncx+xml"
XHTML_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "image/svg+xml",
}
PARSER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)


# ---------- generic xml helpers (file-split preserved) ----------
def local_name(node_or_tag) -> str:
    tag = node_or_tag.tag if hasattr(node_or_tag, "tag") else node_or_tag
    return etree.QName(tag).localname.lower() if isinstance(tag, str) else ""


def attr_local(el, wanted: str) -> Optional[str]:
    wanted = wanted.lower()
    for key, value in el.attrib.items():
        try:
            name = etree.QName(key).localname.lower()
        except ValueError:
            name = key.split(":")[-1].lower()
        if name == wanted:
            return value
    return None


def xml_parse(data: bytes, label: str):
    try:
        root = etree.fromstring(data, PARSER)
    except Exception as exc:
        raise RuntimeError(f"Could not parse {label}: {exc}") from exc
    if root is None:
        raise RuntimeError(f"Could not parse {label}")
    return root


def clean_archive_path(path: str) -> str:
    path = unquote(path.replace("\\", "/"))
    path = posixpath.normpath(path).lstrip("/")
    if path == ".." or path.startswith("../"):
        raise ValueError(f"Unsafe archive path: {path}")
    return path


def resolve_href(base_file: str, href: str) -> tuple[str, str]:
    parsed = urlsplit(href)
    path = unquote(parsed.path)
    if not path:
        resolved = clean_archive_path(base_file)
    else:
        resolved = clean_archive_path(posixpath.join(posixpath.dirname(base_file), path))
    return resolved, unquote(parsed.fragment)


def direct_children(el, name: str):
    return [child for child in el if isinstance(child.tag, str) and local_name(child) == name]


def first_direct(el, names: set[str]):
    for child in el:
        if isinstance(child.tag, str) and local_name(child) in names:
            return child
    return None


def text_of(el) -> str:
    return " ".join("".join(el.itertext()).split())


def epub_type_tokens(el) -> set[str]:
    value = attr_local(el, "type") or ""
    return {token.lower() for token in value.split()}


# ---------- data models ----------
@dataclass
class TocNode:
    title: str
    href: Optional[str]
    source_element: object
    children: list["TocNode"] = field(default_factory=list)


# ---------- EPUB 3 NAV parsing ----------
def find_epub3_toc_nav(root):
    navs = root.xpath(".//*[local-name()='nav']")
    for nav in navs:
        if "toc" in epub_type_tokens(nav):
            return nav
    for nav in navs:
        role = (nav.get("role") or "").lower().split()
        if "doc-toc" in role:
            return nav
    return navs[0] if len(navs) == 1 else None


def parse_nav_li(li, nav_path: str) -> Optional[TocNode]:
    label = first_direct(li, {"a", "span"})
    if label is None:
        labels = li.xpath(".//*[local-name()='a' or local-name()='span']")
        label = labels[0] if labels else None
    if label is None:
        return None
    title = text_of(label) or "Untitled Section"
    href = label.get("href") if local_name(label) == "a" else None
    child_ol = first_direct(li, {"ol"})
    children = []
    if child_ol is not None:
        for child_li in direct_children(child_ol, "li"):
            child = parse_nav_li(child_li, nav_path)
            if child:
                children.append(child)
    if not href:
        descendants = li.xpath(".//*[local-name()='a' and @href]")
        if descendants:
            href = descendants[0].get("href")
    return TocNode(title=title, href=href, source_element=li, children=children)


def parse_epub3_toc(nav_root, nav_path: str):
    toc_nav = find_epub3_toc_nav(nav_root)
    if toc_nav is None:
        return None, []
    ols = toc_nav.xpath("./*[local-name()='ol']")
    if not ols:
        ols = toc_nav.xpath(".//*[local-name()='ol']")
    if not ols:
        return toc_nav, []
    nodes = []
    for li in direct_children(ols[0], "li"):
        node = parse_nav_li(li, nav_path)
        if node and node.href:
            nodes.append(node)
    return toc_nav, nodes


# ---------- EPUB 2 NCX parsing ----------
def parse_ncx_point(point) -> Optional[TocNode]:
    labels = point.xpath("./*[local-name()='navLabel']//*[local-name()='text']")
    contents = point.xpath("./*[local-name()='content']")
    title = text_of(labels[0]) if labels else "Untitled Section"
    href = contents[0].get("src") if contents else None
    children = []
    for child in point.xpath("./*[local-name()='navPoint']"):
        parsed = parse_ncx_point(child)
        if parsed:
            children.append(parsed)
    if not href and children:
        href = children[0].href
    return TocNode(title, href, point, children) if href else None


def parse_ncx_toc(ncx_root):
    maps = ncx_root.xpath(".//*[local-name()='navMap']")
    if not maps:
        return []
    nodes = []
    for point in maps[0].xpath("./*[local-name()='navPoint']"):
        node = parse_ncx_point(point)
        if node:
            nodes.append(node)
    return nodes


# ---------- filename helpers ----------
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:140].rstrip(" .") or "Untitled Section")


def unique_names(nodes) -> list[str]:
    used = {}
    result = []
    for node in nodes:
        base = sanitize_filename(node.title)
        key = base.casefold()
        used[key] = used.get(key, 0) + 1
        result.append(base if used[key] == 1 else f"{base}_{used[key]}")
    return result
