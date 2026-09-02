"""boundless — ADA maximal (file-split preserved, modular)"""
from .models import ChunkMetadata, SplitReport, A11yLogger, DEFAULT_MAX_SIZE_MB
from .registry import EdgeCaseRegistry
from .epub import EpubSplitter
from .pdf import PdfSplitter
from .docx import DocxSplitter
from .profile import (
    EpubProfile, PublisherOrigin,
    profile_epub, profile_many, profile_dir,
    ensure_profile, auto_create_profiles,
)
try:
    from .toc_split import split_epub_by_toc, load_book, locate_top_levels
    from .toc_parse import TocNode, unique_names, parse_epub3_toc, parse_ncx_toc, sanitize_filename
    from .toc_build import build_one, crop_xhtml
except Exception:  # lxml missing on minimal installs
    split_epub_by_toc = None
    load_book = None
    locate_top_levels = None
    TocNode = None
    unique_names = None
    parse_epub3_toc = None
    parse_ncx_toc = None
    sanitize_filename = None
    build_one = None
    crop_xhtml = None
try:
    from .mcp_server import UniversalSplitter, MCPServer
except Exception:
    UniversalSplitter = None
    MCPServer = None

__version__ = "2.0.0"
__all__ = [
    "EpubSplitter", "PdfSplitter", "DocxSplitter",
    "UniversalSplitter", "MCPServer",
    "EdgeCaseRegistry", "A11yLogger", "ChunkMetadata", "SplitReport",
    "EpubProfile", "PublisherOrigin", "profile_epub", "profile_many", "profile_dir",
    "ensure_profile", "auto_create_profiles",
    "split_epub_by_toc", "load_book", "locate_top_levels",
    "TocNode", "unique_names", "parse_epub3_toc", "parse_ncx_toc", "sanitize_filename",
    "build_one", "crop_xhtml",
]
