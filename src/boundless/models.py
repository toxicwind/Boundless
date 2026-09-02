"""
ADA maximal — models (file-split preserved, not regenerated)
Split from boundless_splitter.py to avoid loss.
"""
import sys
import os
import re
import json
import zipfile
import shutil
import argparse
import hashlib
import tempfile
import subprocess
import posixpath
from copy import deepcopy
from urllib.parse import unquote, urlparse
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field, asdict
from typing import List, Set, Dict, Tuple, Optional, Any, Callable
from pathlib import Path

# Optional dependencies with graceful degradation
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False
    import xml.etree.ElementTree as etree

try:
    import ebooklib
    from ebooklib import epub
    HAS_EBOOKLIB = True
except ImportError:
    HAS_EBOOKLIB = False

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from docx import Document
    HAS_PYTHON_DOCX = True
except ImportError:
    HAS_PYTHON_DOCX = False


# =============================================================================

DEFAULT_MAX_SIZE_MB = 50
DEFAULT_MAX_SIZE_BYTES = DEFAULT_MAX_SIZE_MB * 1024 * 1024

# Natural Reader supported formats and their size limits
NATURAL_READER_LIMITS = {
    "epub": 50 * 1024 * 1024,
    "pdf": 100 * 1024 * 1024,  # PDFs have higher limit
    "doc": 50 * 1024 * 1024,
    "docx": 50 * 1024 * 1024,
    "rtf": 50 * 1024 * 1024,
    "txt": 50 * 1024 * 1024,
    "ppt": 50 * 1024 * 1024,
    "pptx": 50 * 1024 * 1024,
}

# Accessibility metadata standards
A11Y_STANDARDS = {
    "wcag20_a": "WCAG 2.0 Level A",
    "wcag20_aa": "WCAG 2.0 Level AA",
    "wcag20_aaa": "WCAG 2.0 Level AAA",
    "wcag21_a": "WCAG 2.1 Level A",
    "wcag21_aa": "WCAG 2.1 Level AA",
    "wcag21_aaa": "WCAG 2.1 Level AAA",
    "wcag22_a": "WCAG 2.2 Level A",
    "wcag22_aa": "WCAG 2.2 Level AA",
    "wcag22_aaa": "WCAG 2.2 Level AAA",
    "section508": "Section 508",
    "pdfua1": "PDF/UA-1 (ISO 14289-1:2014)",
    "pdfua2": "PDF/UA-2 (ISO 14289-2:2024)",
}

# Shared asset directory patterns (case-insensitive)
SHARED_ASSET_PATTERNS = (
    "css", "styles", "style",
    "images", "image", "img", "pics", "pictures",
    "fonts", "font", "typefaces",
    "media", "audio", "video",
    "js", "scripts", "javascript",
    "xml", "xslt",
    "mathml", "svg",
    "metadata", "meta",
)

# EPUB namespace mappings
EPUB_NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "nav": "http://www.w3.org/1999/xhtml",
}


# =============================================================================

# SECTION 2: DATA MODELS
# =============================================================================

@dataclass
class ChunkMetadata:
    """Metadata for a single document chunk, accessibility-aware."""
    title: str = ""
    slug: str = ""
    source_file: str = ""
    page_count: int = 0
    word_count: int = 0
    byte_size: int = 0
    spine_files: List[str] = field(default_factory=list)
    asset_files: List[str] = field(default_factory=list)
    heading_structure: List[Tuple[int, str]] = field(default_factory=list)
    language: str = "en"
    accessibility_features: List[str] = field(default_factory=list)
    conformance_claim: str = ""


@dataclass
class SplitReport:
    """Comprehensive report for audit trails and VPAT documentation."""
    source_path: str = ""
    source_size_bytes: int = 0
    source_format: str = ""
    chunk_count: int = 0
    total_output_size: int = 0
    chunks: List[ChunkMetadata] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    accessibility_notes: List[str] = field(default_factory=list)
    legal_compliance: Dict[str, bool] = field(default_factory=dict)


# =============================================================================
# SECTION 3: EDGE CASE REGISTRY
# =============================================================================

class A11yLogger:
    """Structured logging for audit trails and VPAT documentation."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.notes: List[str] = []

    def warn(self, msg: str):
        self.warnings.append(msg)
        if self.verbose:
            print("[WARN] " + msg, file=sys.stderr)

    def error(self, msg: str):
        self.errors.append(msg)
        if self.verbose:
            print("[ERROR] " + msg, file=sys.stderr)

    def note(self, msg: str):
        self.notes.append(msg)
        if self.verbose:
            print("[NOTE] " + msg)

    def to_dict(self) -> Dict:
        return {
            "warnings": self.warnings,
            "errors": self.errors,
            "notes": self.notes,
            "warning_count": len(self.warnings),
            "error_count": len(self.errors),
        }


# =============================================================================
# SECTION 5: EPUB SPLITTER (Primary Format)
# =============================================================================
