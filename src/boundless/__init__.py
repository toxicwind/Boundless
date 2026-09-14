"""boundless — ADA maximal (file-split preserved, modular)"""
from .db import (
    backfill_from_disk,
    complete_job,
    create_job,
    delete_job,
    fail_job,
    get_job,
    init_db,
    list_inbox_items,
    list_jobs,
    record_inbox_item,
    remove_inbox_item,
    update_job_progress,
)
from .deps import HAS_LXML
from .docx import DocxSplitter
from .epub import EpubSplitter
from .models import (
    DEFAULT_MAX_SIZE_MB,  # noqa: F401
    A11yLogger,
    ChunkMetadata,
    SplitReport,
)
from .pdf import PdfSplitter
from .profile import (
    EpubProfile,
    PublisherOrigin,
    auto_create_profiles,
    ensure_profile,
    profile_dir,
    profile_epub,
    profile_many,
)
from .registry import EdgeCaseRegistry
from .universal import UniversalSplitter

if HAS_LXML:
    from .toc_build import build_one, crop_xhtml
    from .toc_parse import TocNode, parse_epub3_toc, parse_ncx_toc, sanitize_filename, unique_names
    from .toc_split import load_book, locate_top_levels, split_epub_by_toc
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
    generate_vpat,
    list_edge_cases,
    split_document,
    validate_accessibility,
)
from .mcp_server import (
    mcp as mcp_server,
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
