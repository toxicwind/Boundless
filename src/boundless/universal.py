"""
universal — file-split preserved
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


from .models import (
    DEFAULT_MAX_SIZE_BYTES, DEFAULT_MAX_SIZE_MB, EPUB_NS, SHARED_ASSET_PATTERNS,
    NATURAL_READER_LIMITS, A11Y_STANDARDS, ChunkMetadata, SplitReport, A11yLogger,
)
from .epub import EpubSplitter
from .pdf import PdfSplitter
from .docx import DocxSplitter
from .registry import EdgeCaseRegistry
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

class UniversalSplitter:
    """
    Auto-detect format and dispatch to appropriate splitter.
    """

    def __init__(self, max_size_mb: int = DEFAULT_MAX_SIZE_MB, verbose: bool = False):
        self.max_size = max_size_mb * 1024 * 1024
        self.logger = A11yLogger(verbose=verbose)

    def split(self, src_path: str, out_dir: str) -> SplitReport:
        ext = os.path.splitext(src_path)[1].lower()

        if ext == ".epub":
            splitter = EpubSplitter(max_size_bytes=self.max_size, logger=self.logger)
        elif ext == ".pdf":
            splitter = PdfSplitter(max_size_bytes=self.max_size, logger=self.logger)
        elif ext in (".docx", ".doc"):
            splitter = DocxSplitter(max_size_bytes=self.max_size, logger=self.logger)
        else:
            self.logger.error("Unsupported format: " + ext)
            report = SplitReport()
            report.source_path = src_path
            report.source_format = ext
            return report

        report = splitter.split(src_path, out_dir)
        report.warnings = self.logger.warnings
        report.errors = self.logger.errors
        report.accessibility_notes = self.logger.notes
        return report


# =============================================================================
# SECTION 9: MCP SERVER INTERFACE (2026-07-28 Stateless Protocol)
# =============================================================================
