
# deps.py - Shared optional dependency handling
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

try:
    import ebooklib
    from ebooklib import epub
    HAS_EBOOKLIB = True
except ImportError:
    HAS_EBOOKLIB = False
    epub = None

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False
    PdfReader = None
    PdfWriter = None

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    fitz = None

try:
    from docx import Document
    HAS_PYTHON_DOCX = True
except ImportError:
    HAS_PYTHON_DOCX = False
    Document = None

__all__ = [
    etree, HAS_LXML, ebooklib, epub, HAS_EBOOKLIB,
    PdfReader, PdfWriter, HAS_PYPDF2, fitz, HAS_PYMUPDF,
    Document, HAS_PYTHON_DOCX,
]
