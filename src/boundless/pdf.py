"""
pdf — file-split preserved
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

from .deps import (
    etree, HAS_LXML,
    epub, HAS_EBOOKLIB,
    PdfReader, PdfWriter, HAS_PYPDF2,
    fitz, HAS_PYMUPDF,
    Document, HAS_PYTHON_DOCX
)

from .models import (
    DEFAULT_MAX_SIZE_BYTES, DEFAULT_MAX_SIZE_MB, EPUB_NS, SHARED_ASSET_PATTERNS,
    NATURAL_READER_LIMITS, A11Y_STANDARDS, ChunkMetadata, SplitReport, A11yLogger,
)


# =============================================================================

class PdfSplitter:
    """
    Split PDFs by bookmark/outline structure while preserving PDF/UA tags.
    Falls back to page-count splitting if no bookmarks exist.
    """

    def __init__(self, max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES, logger: Optional[A11yLogger] = None):
        self.max_size = max_size_bytes
        self.logger = logger or A11yLogger()
        self.report = SplitReport()

    def split(self, src_path: str, out_dir: str) -> SplitReport:
        self.report.source_path = src_path
        self.report.source_size_bytes = os.path.getsize(src_path)
        self.report.source_format = "pdf"

        if not HAS_PYMUPDF and not HAS_PYPDF2:
            self.logger.error("No PDF library available. Install PyMuPDF or PyPDF2.")
            return self.report

        os.makedirs(out_dir, exist_ok=True)

        if HAS_PYMUPDF:
            return self._split_with_pymupdf(src_path, out_dir)
        else:
            return self._split_with_pypdf2(src_path, out_dir)

    def _split_with_pymupdf(self, src_path: str, out_dir: str) -> SplitReport:
        doc = fitz.open(src_path)
        toc = doc.get_toc()

        if not toc:
            self.logger.note("No bookmarks found, falling back to page-count splitting")
            return self._split_by_page_count(doc, src_path, out_dir)

        # Group pages by top-level bookmark
        chunks = []
        for i, item in enumerate(toc):
            level, title, page = item
            if level == 1:
                if chunks:
                    chunks[-1]["end"] = page - 1
                chunks.append({"title": title, "start": page, "end": doc.page_count - 1})

        if chunks:
            chunks[-1]["end"] = doc.page_count - 1

        for idx, chunk in enumerate(chunks):
            name = re.sub(r"[^\w\s-]", "", chunk["title"]).strip().replace(" ", "_")[:80] or ("Section_%d" % idx)
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=chunk["start"], to_page=chunk["end"])

            out_path = os.path.join(out_dir, name + ".pdf")
            new_doc.save(out_path, garbage=4, deflate=True)
            new_doc.close()

            size = os.path.getsize(out_path)
            meta = ChunkMetadata(
                title=chunk["title"],
                slug=name,
                source_file=src_path,
                page_count=chunk["end"] - chunk["start"] + 1,
                byte_size=size,
            )
            self.report.chunks.append(meta)
            self.report.total_output_size += size

            if size > self.max_size:
                self.logger.warn("Chunk exceeds max size: %s (%d MB)" % (name, size // (1024*1024)))

        doc.close()
        self.report.chunk_count = len(self.report.chunks)
        return self.report

    def _split_by_page_count(self, doc, src_path: str, out_dir: str) -> SplitReport:
        """Fallback: split by estimated page count to stay under size limit."""
        total_pages = doc.page_count
        avg_size_per_page = self.report.source_size_bytes / total_pages
        pages_per_chunk = max(1, int(self.max_size / avg_size_per_page))

        chunk_idx = 0
        for start in range(0, total_pages, pages_per_chunk):
            end = min(start + pages_per_chunk - 1, total_pages - 1)
            chunk_idx += 1

            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start, to_page=end)

            out_path = os.path.join(out_dir, "Section_%02d.pdf" % chunk_idx)
            new_doc.save(out_path, garbage=4, deflate=True)
            new_doc.close()

            size = os.path.getsize(out_path)
            meta = ChunkMetadata(
                title="Section %d" % chunk_idx,
                slug="Section_%02d" % chunk_idx,
                source_file=src_path,
                page_count=end - start + 1,
                byte_size=size,
            )
            self.report.chunks.append(meta)
            self.report.total_output_size += size

        doc.close()
        self.report.chunk_count = len(self.report.chunks)
        return self.report

    def _split_with_pypdf2(self, src_path: str, out_dir: str) -> SplitReport:
        reader = PdfReader(src_path)
        total_pages = len(reader.pages)

        # Try to get bookmarks
        outlines = reader.outline if hasattr(reader, "outline") else []
        if not outlines:
            self.logger.note("No bookmarks found in PDF")

        # Simple page-count fallback
        avg_size = self.report.source_size_bytes / total_pages
        pages_per_chunk = max(1, int(self.max_size / avg_size))

        chunk_idx = 0
        for start in range(0, total_pages, pages_per_chunk):
            end = min(start + pages_per_chunk, total_pages)
            chunk_idx += 1

            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])

            out_path = os.path.join(out_dir, "Section_%02d.pdf" % chunk_idx)
            with open(out_path, "wb") as f:
                writer.write(f)

            size = os.path.getsize(out_path)
            meta = ChunkMetadata(
                title="Section %d" % chunk_idx,
                slug="Section_%02d" % chunk_idx,
                source_file=src_path,
                page_count=end - start,
                byte_size=size,
            )
            self.report.chunks.append(meta)
            self.report.total_output_size += size

        self.report.chunk_count = len(self.report.chunks)
        return self.report


