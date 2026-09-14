"""boundless — ADA maximal (file-split preserved, modular)"""
from .models import ChunkMetadata, SplitReport, A11yLogger, DEFAULT_MAX_SIZE_MB
from .registry import EdgeCaseRegistry
from .epub import EpubSplitter
from .pdf import PdfSplitter
from .docx import DocxSplitter
from .universal import UniversalSplitter
from .profile import (
    EpubProfile, PublisherOrigin,
    profile_epub, profile_many, profile_dir,
    ensure_profile, auto_create_profiles,
)
from .db import (
    init_db, create_job, update_job_progress, complete_job, fail_job,
    get_job, list_jobs, delete_job, record_inbox_item, remove_inbox_item,
    list_inbox_items, backfill_from_disk,
)
from .deps import HAS_LXML

if HAS_LXML:
    from .toc_split import split_epub_by_toc, load_book, locate_top_levels
    from .toc_parse import TocNode, unique_names, parse_epub3_toc, parse_ncx_toc, sanitize_filename
    from .toc_build import build_one, crop_xhtml
else:  # lxml missing on minimal installs — TOC splitting unavailable
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

from .mcp_server import (
    mcp as mcp_server,
    split_document, validate_accessibility, generate_vpat, list_edge_cases,
)

__version__ = "2.0.0"
__all__ = [
    "EpubSplitter", "PdfSplitter", "DocxSplitter",
    "UniversalSplitter", "mcp_server",
    "split_document", "validate_accessibility", "generate_vpat", "list_edge_cases",
    "EdgeCaseRegistry", "A11yLogger", "ChunkMetadata", "SplitReport",
    "EpubProfile", "PublisherOrigin", "profile_epub", "profile_many", "profile_dir",
    "ensure_profile", "auto_create_profiles",
    "split_epub_by_toc", "load_book", "locate_top_levels",
    "TocNode", "unique_names", "parse_epub3_toc", "parse_ncx_toc", "sanitize_filename",
    "build_one", "crop_xhtml",
    "init_db", "create_job", "update_job_progress", "complete_job", "fail_job",
    "get_job", "list_jobs", "delete_job", "record_inbox_item", "remove_inbox_item",
    "list_inbox_items", "backfill_from_disk",
]
