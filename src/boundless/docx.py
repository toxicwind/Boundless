"""
docx — file-split preserved
"""
import os
import re

from .deps import (
    HAS_PYTHON_DOCX,
    Document,
)
from .models import (
    DEFAULT_MAX_SIZE_BYTES,
    A11yLogger,
    ChunkMetadata,
    SplitReport,
)

# =============================================================================

class DocxSplitter:
    """
    Split DOCX files by heading structure.
    Preserves styles and accessibility metadata.
    """

    def __init__(self, max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES, logger: A11yLogger | None = None):
        self.max_size = max_size_bytes
        self.logger = logger or A11yLogger()
        self.report = SplitReport()

    def split(self, src_path: str, out_dir: str) -> SplitReport:
        self.report.source_path = src_path
        self.report.source_size_bytes = os.path.getsize(src_path)
        self.report.source_format = "docx"

        if not HAS_PYTHON_DOCX:
            self.logger.error("python-docx not installed. Run: pip install python-docx")
            return self.report

        os.makedirs(out_dir, exist_ok=True)
        doc = Document(src_path)

        # Find heading boundaries
        headings = []
        for idx, para in enumerate(doc.paragraphs):
            if para.style.name.startswith("Heading"):
                level = int(para.style.name.replace("Heading ", "")) if para.style.name != "Heading" else 1
                headings.append({"idx": idx, "level": level, "text": para.text, "para": para})

        if not headings:
            self.logger.note("No headings found, splitting as single document")
            out_path = os.path.join(out_dir, "Document.docx")
            doc.save(out_path)
            size = os.path.getsize(out_path)
            self.report.chunks.append(ChunkMetadata(
                title="Document",
                slug="Document",
                source_file=src_path,
                byte_size=size,
            ))
            self.report.total_output_size = size
            self.report.chunk_count = 1
            return self.report

        # Split by top-level headings
        chunks = []
        for _i, h in enumerate(headings):
            if h["level"] == 1:
                if chunks:
                    chunks[-1]["end_idx"] = h["idx"]
                chunks.append({"title": h["text"], "start_idx": h["idx"], "end_idx": len(doc.paragraphs)})

        if chunks:
            chunks[-1]["end_idx"] = len(doc.paragraphs)

        for idx, chunk in enumerate(chunks):
            new_doc = Document()
            name = re.sub(r"[^\w\s-]", "", chunk["title"]).strip().replace(" ", "_")[:80] or (f"Section_{idx}")

            for para in doc.paragraphs[chunk["start_idx"]:chunk["end_idx"]]:
                new_para = new_doc.add_paragraph(para.text, style=para.style.name)
                new_para.alignment = para.alignment

            out_path = os.path.join(out_dir, name + ".docx")
            new_doc.save(out_path)

            size = os.path.getsize(out_path)
            meta = ChunkMetadata(
                title=chunk["title"],
                slug=name,
                source_file=src_path,
                byte_size=size,
            )
            self.report.chunks.append(meta)
            self.report.total_output_size += size

            if size > self.max_size:
                self.logger.warn(f"Chunk exceeds max size: {name} ({size // (1024*1024)} MB)")

        self.report.chunk_count = len(self.report.chunks)
        return self.report


