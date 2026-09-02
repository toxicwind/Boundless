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
from .deps import (
    etree, HAS_LXML,
    epub, HAS_EBOOKLIB,
    PdfReader, PdfWriter, HAS_PYPDF2,
    fitz, HAS_PYMUPDF,
    Document, HAS_PYTHON_DOCX
)


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
