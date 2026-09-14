"""
universal — file-split preserved
"""
import os

from .docx import DocxSplitter
from .epub import EpubSplitter
from .models import (
    DEFAULT_MAX_SIZE_MB,
    A11yLogger,
    SplitReport,
)
from .pdf import PdfSplitter

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
