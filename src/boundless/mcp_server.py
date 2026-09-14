"""boundless.mcp_server — Model Context Protocol server for document splitting.

Uses the official `mcp` SDK (v2 API). Exposes the boundless splitters,
accessibility validation, VPAT generation, and the edge-case registry as
MCP tools, plus legal-framework and edge-case docs as MCP resources.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer

from .deps import HAS_PYMUPDF, HAS_PYTHON_DOCX, Document, fitz
from .models import A11Y_STANDARDS
from .registry import EdgeCaseRegistry
from .universal import UniversalSplitter

mcp = MCPServer("boundless-splitter")


def _validate_epub(path: str) -> list[str]:
    issues = []
    try:
        with zipfile.ZipFile(path, "r") as z:
            namelist = z.namelist()
            if "mimetype" not in namelist:
                issues.append("Missing mimetype file")
            if not [f for f in namelist if f.endswith(".opf")]:
                issues.append("No OPF file found")
            if not any(f.endswith(".ncx") or "nav" in f for f in namelist):
                issues.append("No navigation document (NCX or nav) found")
    except Exception as e:
        issues.append("Cannot read EPUB: " + str(e))
    return issues


def _validate_pdf(path: str) -> list[str]:
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
    else:
        issues.append("PyMuPDF not installed; PDF validation skipped")
    return issues


def _validate_docx(path: str) -> list[str]:
    issues = []
    if HAS_PYTHON_DOCX:
        try:
            doc = Document(path)
            if not any(p.style.name.startswith("Heading") for p in doc.paragraphs):
                issues.append("No heading structure found")
        except Exception as e:
            issues.append("Cannot read DOCX: " + str(e))
    else:
        issues.append("python-docx not installed; DOCX validation skipped")
    return issues


@mcp.tool()
def split_document(source_path: str, output_dir: str, max_size_mb: int = 50) -> str:
    """Split a document by table of contents while preserving accessibility."""
    splitter = UniversalSplitter(max_size_mb=max_size_mb)
    report = splitter.split(source_path, output_dir)
    return json.dumps(asdict(report), indent=2)


@mcp.tool()
def validate_accessibility(document_path: str, standard: str = "wcag21_aa") -> str:
    """Check a document for accessibility issues against WCAG/EPUB-A11Y/PDF-UA."""
    issues: list[str] = []
    if not os.path.exists(document_path):
        issues.append("File not found")
    else:
        ext = os.path.splitext(document_path)[1].lower()
        if ext == ".epub":
            issues.extend(_validate_epub(document_path))
        elif ext == ".pdf":
            issues.extend(_validate_pdf(document_path))
        elif ext == ".docx":
            issues.extend(_validate_docx(document_path))
        else:
            issues.append(f"Unsupported format: {ext}")
    return json.dumps({"standard": standard, "issues": issues}, indent=2)


@mcp.tool()
def generate_vpat(report: dict[str, Any]) -> str:
    """Generate a Voluntary Product Accessibility Template (VPAT) summary."""
    vpat = {
        "product_name": "BOUNDLESS Document Splitter",
        "standards": ["WCAG 2.1 AA", "Section 508", "EPUB Accessibility 1.1"],
        "conformance_summary": "Supports",
        "remarks": "Splits documents by TOC while preserving accessibility metadata.",
        "split_report": report,
    }
    return json.dumps(vpat, indent=2)


@mcp.tool()
def list_edge_cases() -> str:
    """List all known edge cases for document accessibility processing."""
    return "\n".join(EdgeCaseRegistry.all_cases())


@mcp.resource("docs://legal-framework")
def legal_framework() -> str:
    """ADA, IDEA, Section 508, and state accessibility law summary."""
    lines = ["# Accessibility Legal Framework", ""]
    for key, desc in A11Y_STANDARDS.items():
        lines.append(f"## {key}")
        lines.append(str(desc))
        lines.append("")
    return "\n".join(lines)


@mcp.resource("docs://edge-cases")
def edge_cases_resource() -> str:
    """Comprehensive edge case list for EPUB, PDF, DOCX processing."""
    return "\n".join(EdgeCaseRegistry.all_cases())


def main(argv=None) -> int:
    """boundless-mcp — run the MCP server over stdio."""
    ap = argparse.ArgumentParser(prog="boundless-mcp", description="Boundless MCP server (stdio)")
    ap.parse_args(argv)
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
