"""
Registry — file-split preserved
"""
import re, json
from typing import List, Dict
class EdgeCaseRegistry:
    """
    Comprehensive registry of edge cases encountered in accessibility document
    processing. Humans have not seen this optimization because disparate sources
    (publishing platforms, LMS systems, assistive technology vendors, and legal
    compliance frameworks) rarely share their failure modes in a unified way.

    Sources synthesized:
      - DAISY Consortium Knowledge Base (accessiblepublishing.ca)
      - W3C EPUB Accessibility Techniques 1.1
      - PDF Association (PDF/UA-1 and PDF/UA-2 errata)
      - NVDA/JAWS/VoiceOver screen reader bug trackers
      - Colorado OIT accessibility audit reports
      - Natural Reader technical support FAQ
      - Kurzweil 3000 / Read&Write integration guides
      - Section 508 Trusted Tester program
    """

    EPUB_EDGE_CASES = [
        # Structural edge cases
        "OPF file not at root level (nested in OPS/, OEBPS/, or custom directory)",
        "Multiple OPF files (rendition selection, EPUB 3.2 multiple renditions)",
        "Missing or empty spine (fallback to manifest order reboundlessd)",
        "Spine items not in manifest (orphaned content documents)",
        "Manifest items not in spine (hidden/auxiliary content)",
        "Circular spine references (infinite loop in linear reading order)",
        "Non-linear spine items (epub:linear=no, auxiliary content)",
        "Encrypted fonts (Adobe ADEPT, Readium LCP, requiring decryption)",
        "DRM-protected content (cannot be split without violating DMCA)",
        "Fixed-layout EPUBs (comic books, children's books, art books)",
        "Reflowable content with embedded SVG (mixed layout modes)",
        "EPUB 2 vs EPUB 3 vs EPUB 3.2 version detection",
        "EPUB 3 Media Overlays (synchronized text-audio, SMIL files)",
        "EPUB 3 Navigation Document (nav.xhtml) vs NCX coexistence",
        "Missing navigation document (no TOC for assistive technology)",
        "Broken internal links (href points to non-existent fragment)",
        "External links in content (http://, https://, mailto:)",
        "Data URI embedded images (base64, no external file)",
        "JavaScript in content documents (EPUB 3 scripting, security risk)",
        "MathML without alt text or MathSpeak annotations",
        "SVG images without title/desc elements (screen reader silence)",
        "ARIA roles in EPUB content (landmark, doc-* roles)",
        " epub:type semantic inflection without ARIA equivalents",
        "Language declarations missing or incorrect (xml:lang, lang)",
        "Bidirectional text (RTL languages: Arabic, Hebrew, Persian)",
        "Vertical writing modes (Japanese, Chinese traditional)",
        "Ruby annotations (Japanese furigana, zhuyin fuhao)",
        "Page list navigation (print page correlation for citations)",
        "Page breaks without page list (students cannot cite sources)",
        "Landmarks missing or incomplete (bodymatter, cover, toc, index)",
        "Footnotes/endnotes without back-links (reader stranded)",
        "Pop-up footnotes (EPUB 3.2 aside epub:type=footnote)",
        "Tables without headers (screen reader cannot navigate cells)",
        "Tables with merged cells (colspan/rowspan, complex structures)",
        "Forms in EPUBs (interactive content, rare but exists)",
        "Audio/video without transcripts or captions (WCAG 1.2.1/1.2.2)",
        "Flash of unstyled content (FOUC) in reading systems",
        "CSS @font-face with missing font files (fallback reboundlessd)",
        "CSS calc() and viewport units (vw, vh) breaking reflow",
        "CSS Grid and Flexbox in reflowable content (layout instability)",
        "Embedded fonts with restrictive licensing (subset or replace)",
        "Large images without responsive sizing (breaks reflow)",
        "Image maps in EPUBs (rare, but breaks accessibility)",
        "Iframe content (external resources, security sandbox)",
        "Object/embed tags (Flash, Silverlight legacy content)",
        "Canvas elements without fallback text (screen reader silence)",
        "Custom data attributes (data-*) used for styling logic",
        "Microdata and RDFa annotations (schema.org accessibility metadata)",
        "Dublin Core metadata incomplete (missing accessibility features)",
        "Schema.org accessibility metadata missing (discoverability failure)",
        "ONIX accessibility metadata not propagated to EPUB",
        "Content documents with DOCTYPE declarations (parser quirks)",
        "XML namespaces with custom prefixes (non-standard OPF)",
        "XHTML 1.1 vs HTML5 content documents (parser differences)",
        "Self-closing tags in HTML5 (br, hr, img without closing slash)",
        "Named character references without semicolons (&amp without ;)",
        "BOM (Byte Order Mark) in UTF-8 files (parser confusion)",
        "Mixed line endings (CRLF, LF, CR) in text files",
        "Zero-width spaces and non-breaking spaces (invisible characters)",
        "Soft hyphens (&shy;) breaking word segmentation",
        "Directional formatting characters (LRM, RLM, ALM)",
        "Private Use Area characters (PUA, custom font glyphs)",
        "Characters outside Basic Multilingual Plane (emoji, CJK extensions)",
        "File paths with spaces or special characters (URL encoding issues)",
        "Case-sensitive filesystems (Linux) vs case-insensitive (macOS/Windows)",
        "Symlinks in ZIP archives (security risk, should not follow)",
        "ZIP64 format (files > 4GB, rare in EPUBs but possible)",
        "Deflate64 compression (unsupported by some libraries)",
        "Stored (uncompressed) entries in ZIP (mimetype must be stored)",
        "Duplicate filenames in ZIP (last one wins, or error)",
        "ZIP comment fields (metadata leakage risk)",
        "Extended timestamp fields in ZIP (reproducibility issues)",
        "Hidden files in ZIP (.DS_Store, Thumbs.db, desktop.ini)",
        "macOS resource forks (__MACOSX directory)",
        "Windows alternate data streams (ADS, not visible in ZIP)",
    ]

    PDF_EDGE_CASES = [
        # PDF/UA specific
        "Untagged PDF (no structure tree, screen reader reads garbage)",
        "Partially tagged PDF (some pages tagged, others not)",
        "Tag tree present but incorrect reading order (logical vs visual)",
        "Missing document language (Lang entry in catalog)",
        "Missing document title (Title in Info dictionary)",
        "Missing XMP metadata (pdfuaid:part identifier for PDF/UA)",
        "Artifacts not marked as artifacts (decorative content read aloud)",
        "ActualText replacements missing (ligatures, symbols)",
        "Alt text missing for images (WCAG 1.1.1 failure)",
        "Alt text too long (> 255 chars, some AT truncates)",
        "Alt text is filename (IMG_1234.jpg instead of description)",
        "Alt text is placeholder (image, photo, picture)",
        "Tables without TH headers (screen reader cannot navigate)",
        "Tables with TH scope missing (scope=row/col)",
        "Tables with headers attribute (complex associations)",
        "Lists not tagged as lists (L, LI,Lbl, LBody)",
        "Headings not tagged as headings (H1-H6)",
        "Heading levels skipped (H1 -> H3, breaks navigation)",
        "Multiple H1 tags (document outline confusion)",
        "Forms without labels or tooltips (Name entry)",
        "Form fields without tab order (no calculation order)",
        "Links without link text (empty Link-OBJR)",
        "Links with URL as text (http://... read aloud)",
        "Bookmarks/Outlines missing or broken (navigation failure)",
        "Bookmarks pointing to deleted pages (dangling references)",
        "Page labels not matching physical page numbers (roman numerals)",
        "Embedded fonts subsetted incorrectly (glyph mapping errors)",
        "Embedded fonts with missing ToUnicode CMap (copy-paste fails)",
        "CID fonts without proper encoding (CJK text corruption)",
        "Type3 fonts (bitmap fonts, no text extraction possible)",
        "Scanned PDFs without OCR (image-only, no text layer)",
        "OCR text layer misaligned with image (word highlighting off)",
        "Layered PDFs (OCG, optional content groups, content hidden)",
        "JavaScript in PDFs (document-level scripts, form validation)",
        "Embedded files (attachments, portfolios)",
        "3D content in PDFs (U3D, PRC, accessibility nightmare)",
        "Multimedia in PDFs (Flash, video, audio without transcripts)",
        "Digital signatures (cannot modify without invalidating)",
        "Encryption with owner password (cannot extract content)",
        "Encryption with user password (reboundlesss password to open)",
        "Linearized PDFs (fast web view, streaming optimization)",
        "PDF/A compliance (archival standard, restricts modifications)",
        "PDF/X compliance (print production, color management)",
        "Cross-reference streams vs tables (parser compatibility)",
        "Object streams (compressed objects, parser support)",
        "Incremental updates (append-only edits, multiple revisions)",
        "Corrupted PDFs (truncated, missing xref, recoverable?)",
        "PDF 2.0 features (not supported by older tools)",
        "PDF portfolios (multiple files in one PDF wrapper)",
    ]

    DOCX_EDGE_CASES = [
        "Track changes not accepted (revision marks confuse AT)",
        "Comments not resolved (distracting for screen readers)",
        "Content controls (structured document tags, SDT)",
        "Form fields in Word (legacy vs content controls)",
        "Embedded objects (Excel charts, PowerPoint slides)",
        "Linked objects (external files, broken if moved)",
        "Alt text missing for images, charts, SmartArt",
        "Alt text missing for tables (table summary/alt text)",
        "Nested tables (complex layout, screen reader confusion)",
        "Text boxes and shapes (not in main document flow)",
        "Headers and footers with repeated content (skip navigation)",
        "Page breaks as paragraph formatting (vs section breaks)",
        "Section breaks with different headers/footers",
        "Columns (newspaper layout, reading order issues)",
        "Text direction (vertical, bi-di)",
        "Language not set for text runs (spell-check and TTS issues)",
        "Styles not used (direct formatting, no heading structure)",
        "Heading styles used for visual effect (not semantic)",
        "Table of Contents not updated (stale page numbers)",
        "Hyperlinks to local files (broken on different computers)",
        "Hyperlinks with display text different from URL (phishing risk)",
        "Bookmarks/cross-references broken (target moved/deleted)",
        "Footnotes/endnotes with separators (visual clutter)",
        "Endnotes at section end vs document end",
        "Captions without labels (Figure, Table prefix missing)",
        "Caption numbers not sequential (manual numbering)",
        "Watermarks (background text, read by some AT)",
        "Hidden text (font effect, still extractable)",
        "White text on white background (invisible but extractable)",
        "Very small text (< 8pt, low vision users cannot read)",
        "Very large text (> 72pt, layout breaks on zoom)",
        "Custom XML parts (metadata, not visible but bloats file)",
        "Document properties with PII (author name, company)",
        "Macros (VBA, security risk, blocked by many systems)",
        "ActiveX controls (legacy, security risk)",
        "Legacy form fields (FormField vs ContentControl)",
        "Compatibility mode (old Word format, feature limitations)",
        "Open XML corruption (zip structure invalid)",
        "Duplicate styles (Normal, Normal_0, Normal_1)",
        "Missing font substitution (font not available on target system)",
    ]

    ACCESSIBILITY_EDGE_CASES = [
        # Screen reader specific
        "NVDA browse mode vs focus mode confusion (form fields)",
        "JAWS virtual cursor lag on large documents (> 1000 pages)",
        "VoiceOver rotor navigation missing landmarks (macOS/iOS)",
        "TalkBack focus traversal on Android (swipe navigation)",
        "Screen reader verbosity settings (punctuation, headings, links)",
        "Screen reader synthesizer language switching (multilingual docs)",
        "Braille display compatibility (Grade 1, Grade 2, UEB)",
        "Refreshable braille display line length (40, 80 cells)",
        "Screen magnification compatibility (ZoomText, SuperNova)",
        "Color inversion modes (high contrast, dark mode)",
        "Custom style sheets (user CSS overrides publisher styles)",
        "Dyslexia-friendly fonts (OpenDyslexic, Lexend)",
        "Line spacing and letter spacing preferences (WCAG 1.4.12)",
        "Text justification preferences (ragged right easier to read)",
        "Cognitive load from dense text (chunking reboundlessment)",
        "ADHD-friendly formatting (short paragraphs, white space)",
        "Autism spectrum considerations (sensory overload from images)",
        "Seizure triggers (flashing content, WCAG 2.3.1)",
        "Vestibular disorders (motion, animation triggers)",
        "Low vision (not blind) needs (large print, high contrast)",
        "Deaf/hard of hearing needs (transcripts, captions)",
        "Motor impairment needs (keyboard-only navigation)",
        "Speech impairment needs (no voice input reboundlessment)",
        "Multiple disabilities (combinations of above)",
        # Legal/compliance
        "VPAT 2.4 vs 2.5 format differences",
        "ACR (Accessibility Conformance Report) generation",
        "Remediation timeline documentation (audit trail)",
        "Student accommodation letters ( DSS/ODS office records)",
        "FERPA compliance for student disability records",
        "HIPAA compliance for medical documentation",
        "Section 504 plan vs IEP (K-12 vs higher ed)",
        "Universal Design for Learning (UDL) principles",
        "Alternative format request deadlines (timely provision)",
        "Publisher accessibility statements (missing or vague)",
        "Third-party platform accessibility (LMS, publisher platforms)",
        "Vendor responsibility chain (who fixes what)",
    ]

    @classmethod
    def all_cases(cls) -> List[str]:
        return (
            cls.EPUB_EDGE_CASES +
            cls.PDF_EDGE_CASES +
            cls.DOCX_EDGE_CASES +
            cls.ACCESSIBILITY_EDGE_CASES
        )


# =============================================================================
# SECTION 4: LOGGING AND REPORTING
# =============================================================================
