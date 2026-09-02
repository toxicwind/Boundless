"""
mcp_server — file-split preserved
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

class MCPServer:
    """
    Model Context Protocol server for accessibility document splitting.
    Implements 2026-07-28 stateless specification.

    Protocol: Stateless HTTP, no handshake, no sessions.
    Discovery: server/discover endpoint.
    Headers: MCP-Protocol-Version, Mcp-Method, Mcp-Name.
    """

    PROTOCOL_VERSION = "2026-07-28"

    def __init__(self, splitter: UniversalSplitter):
        self.splitter = splitter

    def discover(self) -> Dict:
        """Return server capabilities for MCP discovery."""
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {
                "name": "boundless-splitter",
                "version": "2.0.0",
                "description": "Accessibility-first document splitter for higher education",
            },
            "tools": [
                {
                    "name": "split_document",
                    "description": "Split a document by table of contents while preserving accessibility",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "source_path": {"type": "string", "description": "Path to source document"},
                            "output_dir": {"type": "string", "description": "Directory for output chunks"},
                            "max_size_mb": {"type": "integer", "description": "Maximum chunk size in MB", "default": 50},
                        },
                        "reboundlessd": ["source_path", "output_dir"],
                    },
                },
                {
                    "name": "validate_accessibility",
                    "description": "Check document for accessibility issues against WCAG/EPUB-A11Y/PDF-UA",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "document_path": {"type": "string", "description": "Path to document"},
                            "standard": {"type": "string", "enum": list(A11Y_STANDARDS.keys()), "default": "wcag21_aa"},
                        },
                        "reboundlessd": ["document_path"],
                    },
                },
                {
                    "name": "generate_vpat",
                    "description": "Generate Voluntary Product Accessibility Template (VPAT) summary",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "report": {"type": "object", "description": "SplitReport JSON"},
                        },
                        "reboundlessd": ["report"],
                    },
                },
                {
                    "name": "list_edge_cases",
                    "description": "List all known edge cases for document accessibility processing",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    },
                },
            ],
            "resources": [
                {
                    "uri": "docs://legal-framework",
                    "name": "Legal Framework",
                    "description": "ADA, IDEA, Section 508, HB21-1110 summary",
                    "mimeType": "text/markdown",
                },
                {
                    "uri": "docs://edge-cases",
                    "name": "Edge Case Registry",
                    "description": "Comprehensive edge case list for EPUB, PDF, DOCX",
                    "mimeType": "text/plain",
                },
            ],
        }

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        """Execute a tool call."""
        if name == "split_document":
            src = arguments.get("source_path")
            out = arguments.get("output_dir")
            max_mb = arguments.get("max_size_mb", 50)
            splitter = UniversalSplitter(max_size_mb=max_mb)
            report = splitter.split(src, out)
            return {"content": [{"type": "text", "text": json.dumps(asdict(report), indent=2)}]}

        elif name == "validate_accessibility":
            path = arguments.get("document_path")
            standard = arguments.get("standard", "wcag21_aa")
            return self._validate(path, standard)

        elif name == "generate_vpat":
            report_data = arguments.get("report", {})
            return self._generate_vpat(report_data)

        elif name == "list_edge_cases":
            cases = EdgeCaseRegistry.all_cases()
            return {"content": [{"type": "text", "text": "\n".join(cases)}]}

        else:
            return {"error": "Unknown tool: " + name}

    def _validate(self, path: str, standard: str) -> Dict:
        """Basic accessibility validation."""
        issues = []
        if not os.path.exists(path):
            issues.append("File not found")
            return {"content": [{"type": "text", "text": json.dumps({"issues": issues}, indent=2)}]}

        ext = os.path.splitext(path)[1].lower()
        if ext == ".epub":
            issues.extend(self._validate_epub(path))
        elif ext == ".pdf":
            issues.extend(self._validate_pdf(path))
        elif ext == ".docx":
            issues.extend(self._validate_docx(path))

        return {"content": [{"type": "text", "text": json.dumps({"standard": standard, "issues": issues}, indent=2)}]}

    def _validate_epub(self, path: str) -> List[str]:
        issues = []
        try:
            with zipfile.ZipFile(path, "r") as z:
                namelist = z.namelist()
                if "mimetype" not in namelist:
                    issues.append("Missing mimetype file")
                opfs = [f for f in namelist if f.endswith(".opf")]
                if not opfs:
                    issues.append("No OPF file found")
                if not any(f.endswith(".ncx") or "nav" in f for f in namelist):
                    issues.append("No navigation document (NCX or nav) found")
        except Exception as e:
            issues.append("Cannot read EPUB: " + str(e))
        return issues

    def _validate_pdf(self, path: str) -> List[str]:
        issues = []
        if HAS_PYMUPDF:
            try:
                doc = fitz.open(path)
                if not doc.metadata.get("title"):
                    issues.append("PDF missing title metadata")
                if doc.is_encrypted:
                    issues.append("PDF is encrypted")
                if not doc.get_toc():
                    issues.append("PDF has no bookmarks/outline")
                doc.close()
            except Exception as e:
                issues.append("Cannot read PDF: " + str(e))
        return issues

    def _validate_docx(self, path: str) -> List[str]:
        issues = []
        if HAS_PYTHON_DOCX:
            try:
                doc = Document(path)
                has_headings = any(p.style.name.startswith("Heading") for p in doc.paragraphs)
                if not has_headings:
                    issues.append("No heading structure found")
            except Exception as e:
                issues.append("Cannot read DOCX: " + str(e))
        return issues

    def _generate_vpat(self, report_data: Dict) -> Dict:
        """Generate a basic VPAT-style summary."""
        vpat = {
            "product_name": "BOUNDLESS Document Splitter",
            "date": "2026-08-31",
            "standards": ["WCAG 2.1 AA", "Section 508", "EPUB Accessibility 1.1"],
            "conformance_summary": "Supports",
            "remarks": "Splits documents by TOC while preserving accessibility metadata.",
            "split_report": report_data,
        }
        return {"content": [{"type": "text", "text": json.dumps(vpat, indent=2)}]}


# =============================================================================
# SECTION 10: CLI INTERFACE
# =============================================================================
