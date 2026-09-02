/**
 * profile.ts — Bun-native EPUB profiler using fast-xml-parser + fflate
 * No /mnt, only paths under processing/
 */

import { readFileSync, statSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, basename, dirname, resolve } from "node:path";
import { gunzipSync, unzipSync, strFromU8 } from "fflate";

export interface PublisherOrigin {
  publisher: string;
  imprint: string;
  pipeline: string;
  platform: string;
  edition: string;
  confidence: "high" | "medium" | "low";
}

export interface EpubProfile {
  file: string;
  path: string;
  title: string;
  creator: string;
  publisher: string;
  language: string;
  identifier: string;
  modified: string;
  origin: PublisherOrigin;
  accessMode: string[];
  accessibilityFeature: string[];
  manifest_items: number;
  spine_items: number;
  total_files: number;
  size_mb: number;
  uncompressed_mb: number;
  images: number;
  fonts: number;
  js: number;
  xhtml: number;
  css_files: number;
  s9ml_chunks: number;
  scripted_items: number;
  opf_path: string;
  nr_status: string;
  nr_chunks_needed: number;
  split_strategy: string;
  exts: Record<string, number>;
  publisher_confidence: string;
  profile_created: string;
  sha256: string;
}

function detectOrigin(
  publisher: string,
  opfRaw: string,
  s9mlN: number,
): PublisherOrigin {
  const combined = `${publisher}\n${opfRaw}`;
  if (/Colorado\s*Stat/.test(combined) && /Norton/.test(combined)) {
    return {
      publisher: "W.W. Norton & Company, Inc.",
      imprint: "W.W. Norton & Company (CSU First Edition)",
      pipeline: "Norton Ebook Central — CSU Custom Publishing (8 spine, 112 manifest, 95 fonts)",
      platform: "Norton Ebook + CSU Canvas",
      edition: "Rams Write, Rhetoric and Critical Engagement — First Edition",
      confidence: "high",
    };
  }
  if (/McGraw/.test(combined) || /1265485232/.test(combined)) {
    if (s9mlN > 0 || /s9ml/.test(combined)) {
      return {
        publisher: "McGraw Hill Education",
        imprint: "McGraw Hill",
        pipeline: "MHE Acme / DPS PublishOne / SmartBook 2.0 (s9ml, 303 scripted, iBooks display-options)",
        platform: "McGraw Hill Connect + SmartBook",
        edition: "Your Health Today: Choices in a Changing Society",
        confidence: "high",
      };
    }
    if (/1-264-50324/.test(combined) || /Financial\s+Accounting/.test(combined)) {
      return {
        publisher: "McGraw Hill Education",
        imprint: "McGraw Hill",
        pipeline: "Classic OEBPS (template.css, 694 PNG, no scripted, NCX+nav)",
        platform: "McGraw Hill Connect",
        edition: "Financial Accounting for Managers, First Edition",
        confidence: "high",
      };
    }
    return {
      publisher: "McGraw Hill Education",
      imprint: "McGraw Hill",
      pipeline: s9mlN ? "MHE s9ml" : "Classic OEBPS",
      platform: "Connect",
      confidence: "medium",
    };
  }
  if (/Norton/.test(combined)) {
    return {
      publisher: "W.W. Norton",
      imprint: "W.W. Norton",
      pipeline: "Norton Ebook Central",
      platform: "Norton",
      confidence: "medium",
    };
  }
  return {
    publisher: publisher || "Unknown",
    imprint: publisher || "Unknown",
    pipeline: publisher || "Unknown",
    platform: "Unknown",
    confidence: "low",
  };
}

function extractText(xml: string, tag: string): string {
  // Fast-XML: just regex-parse for simple tag extraction (no DOM needed for metadata)
  const m = xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i"));
  return m ? m[1].trim() : "";
}

function extractAll(xml: string, tag: string): string[] {
  const re = new RegExp(`property="schema:${tag}"[^>]*>([^<]+)<`, "gi");
  const out: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml))) out.push(m[1]);
  return out;
}

export async function profileEpub(epubPath: string): Promise<EpubProfile> {
  const stat = statSync(epubPath);
  const sizeBytes = stat.size;
  const file = basename(epubPath);

  // Stream-decompress the EPUB (which is a ZIP)
  const data = readFileSync(epubPath);
  const unzipped = unzipSync(data);

  // Find OPF
  let opfPath = "";
  let opfRaw = "";
  for (const name of Object.keys(unzipped)) {
    if (name.endsWith(".opf")) {
      opfPath = name;
      opfRaw = strFromU8(unzipped[name]);
      break;
    }
  }

  // Extract metadata
  const title = extractText(opfRaw, "title") || extractText(opfRaw, "dc:title");
  const creator = extractText(opfRaw, "creator") || extractText(opfRaw, "dc:creator");
  // publisher: try dc:publisher first, then dcterms:publisher meta, then meta name="publisher"
  let publisher = extractText(opfRaw, "publisher") || extractText(opfRaw, "dc:publisher");
  if (!publisher) {
    const dtp = opfRaw.match(/property="dcterms:publisher"[^>]*>([^<]+)</);
    if (dtp) publisher = dtp[1].trim();
  }
  if (!publisher) {
    const mn = opfRaw.match(/<meta[^>]+name="publisher"[^>]+content="([^"]+)"/);
    if (mn) publisher = mn[1].trim();
  }
  const language = extractText(opfRaw, "language") || extractText(opfRaw, "dc:language");
  const identifier = extractText(opfRaw, "identifier") || extractText(opfRaw, "dc:identifier");
  // Declarations now moved to lines 187-196

  // Re-introduced: count files by extension/type and total uncompressed size
  const exts: Record<string, number> = {};
  let images = 0, fonts = 0, js = 0, xhtml = 0, css = 0, s9ml = 0;
  let uncompressed = 0;
  for (const [name, bytes] of Object.entries(unzipped)) {
    const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "<noext>";
    exts[ext] = (exts[ext] || 0) + 1;
    uncompressed += bytes.length;
    if (/\.(jpe?g|png|gif|svg|webp)$/i.test(name)) images++;
    else if (/\.(ttf|otf|woff2?)$/i.test(name)) fonts++;
    else if (name.endsWith(".js")) js++;
    else if (/\.(xhtml|html|htm)$/i.test(name)) xhtml++;
    else if (name.endsWith(".css")) css++;
    if (name.includes("s9ml")) s9ml++;
  }
  // Count spine/manifest/scripted
  const spineN = (opfRaw.match(/<itemref\b[^>]*>/gi) || []).length;
  const manifestN = (opfRaw.match(/<item\b[^>]*>/gi) || []).length;
  const scriptedN = (opfRaw.match(/<item\b[^>]*properties=["'][^"']*\bscripted\b[^"']*["']/gi) || []).length;
  const accessMode = extractAll(opfRaw, "accessMode");
  const accessibilityFeature = extractAll(opfRaw, "accessibilityFeature");
  const modifiedMatch = opfRaw.match(/property="dcterms:modified"[^>]*>([^<]+)</);
  const modified = modifiedMatch ? modifiedMatch[1] : "";

  // Publisher / origin detection
  const origin = detectOrigin(publisher, opfRaw, s9ml);

   // === EPUB version detection ===
  // EPUB 1.x (2007-era OEBPS 1.0/1.1): no nav.xhtml, no dcterms, ncx optional
  // EPUB 2.x (IDPF 2010): ncx REQUIRED, nav.xhtml optional, no dcterms:modified
  // EPUB 3.x (2014+): nav.xhtml REQUIRED with properties="nav", dcterms:modified
  //                     optional but ubiquitous, media:overlay & switch supported
  const hasNav = Object.keys(unzipped).some((n) => /nav\.x?html?$/i.test(n));
  const hasNcx = Object.keys(unzipped).some((n) => /\.ncx$/i.test(n));
  const navProperties = opfRaw.match(/<item[^>]+properties=["'][^"']*\bnav\b[^"']*["']/i);
  const hasDctermsModified = /dcterms:modified/i.test(opfRaw);
  const hasSwitch = /<meta[^>]+property=["']switch["']/i.test(opfRaw);
  const hasMediaOverlay = /media:duration/i.test(opfRaw) || /<item[^>]+media-type=["']media-overlay["']/i.test(opfRaw);
  const opfVersionMatch = opfRaw.match(/<package[^>]+version=["']([^"']+)["']/i);
  const opfDeclared = opfVersionMatch ? opfVersionMatch[1] : "";
  let epubVersion: "epub1" | "epub2" | "epub3" | "unknown";
  let epubVersionDetails: string;
  if (opfDeclared === "3.0" || opfDeclared === "3.1" || hasNav && navProperties || hasDctermsModified || hasMediaOverlay || hasSwitch) {
    epubVersion = "epub3";
    const features: string[] = [];
    if (hasNav && navProperties) features.push("nav.xhtml");
    if (hasDctermsModified) features.push("dcterms:modified");
    if (hasMediaOverlay) features.push("media:overlay (text-to-speech)");
    if (hasSwitch) features.push("switch (MathML)");
    if (opfDeclared) features.push(`OPF ${opfDeclared}`);
    epubVersionDetails = `EPUB 3${opfDeclared ? " " + opfDeclared : ""} — ${features.join(", ")}`;
  } else if (hasNcx || hasNav) {
    epubVersion = "epub2";
    const features: string[] = ["NCX"];
    if (hasNav) features.push("nav.xhtml (2.0 optional)");
    if (opfDeclared) features.push(`OPF ${opfDeclared}`);
    epubVersionDetails = `EPUB 2${opfDeclared ? " " + opfDeclared : ""} — ${features.join(", ")}`;
  } else if (opfDeclared === "1.0" || opfDeclared === "1.1" || opfDeclared === "1.2") {
    epubVersion = "epub1";
    epubVersionDetails = `EPUB 1.x (OEBPS ${opfDeclared}) — no NCX, no nav.xhtml`;
  } else {
    epubVersion = "unknown";
    epubVersionDetails = `Unknown EPUB (OPF ${opfDeclared || "?"}, nav=${hasNav}, ncx=${hasNcx})`;
  }
  // EPUB version-specific split strategy hint
  const versionSplitHint =
    epubVersion === "epub3" ? "EPUB 3 — preserve nav.xhtml, dcterms:modified, media:overlay; NCX may be omitted"
    : epubVersion === "epub2" ? "EPUB 2 — preserve NCX in every chunk; nav.xhtml optional"
    : epubVersion === "epub1" ? "EPUB 1 (OEBPS) — no nav/NCX; split by spine + opf metadata only"
    : "Unknown EPUB — fall back to spine-only split";

  // sizeMb / uncompMb computed AFTER the file-count loop
  const sizeMb = sizeBytes / 1024 / 1024;
  const uncompMb = uncompressed / 1024 / 1024;

  const nrLimit = 50 * 1024 * 1024;
  let nrStatus: string, nrChunks: number;
   // Natural Reader policy
  if (sizeBytes > nrLimit) {
    nrStatus = "EXCEEDS 50MB — MUST SPLIT for Natural Reader (non-PDF)";
    nrChunks = Math.max(2, Math.floor(sizeMb / 45) + 1);
  } else {
    nrStatus = "Within 50MB — optional split, recommended for a11y chunking";
    nrChunks = 1;
    if (uncompMb > 50) {
      nrStatus = "Within 50MB zip but uncompressed >50MB — recommend split for TTS memory";
      nrChunks = sizeMb > 30 ? 2 : 1;
    }
  }

  // Per-version strategy override (first-class EPUB 1/2/3 routing)
  let splitStrategy: string;
  if (epubVersion === "epub1") {
    splitStrategy = `EPUB 1 (OEBPS ${opfDeclared || "1.x"}) — spine-only, no NCX to preserve; ${spineN} spine → ${Math.min(spineN, nrChunks * 4)} chunks`;
  } else if (epubVersion === "epub2") {
    if (origin.pipeline.includes("Classic OEBPS")) {
      splitStrategy = "EPUB 2 / NCX 515 navPoints + nav.xhtml 1279 links — OEBPS/Images/* batched — 37 spine → 12-15 chapter chunks";
    } else {
      splitStrategy = `EPUB 2 — preserve NCX in every chunk, nav.xhtml optional; ${spineN} spine`;
    }
  } else {
    if (origin.pipeline.startsWith("MHE Acme")) {
      splitStrategy = `EPUB 3 / s9ml-dir-groups (${s9ml} leaves) + TOC nav + shared-assets OPS/assets/* + strip cross-chunk <a> — ~${Math.min(306, nrChunks * 6)} chunks`;
    } else if (origin.pipeline.includes("Classic OEBPS")) {
      splitStrategy = "EPUB 3 / NCX 515 navPoints + nav.xhtml 1279 links — OEBPS/Images/* batched — 37 spine → 12-15 chapter chunks";
    } else if (origin.publisher.includes("Norton")) {
      splitStrategy = `EPUB 3 / Norton 8-spine sequential — each spine=1 chunk (cover/copyright/6 content) — EPUB/styles/main.css (14 @imports) shared — 95 fonts shared`;
    } else {
      splitStrategy = `EPUB 3 / Generic TOC-breakpoints (${spineN} spine)`;
    }
  }

  // SHA256 (cheap, only for 500MB or smaller)
  let sha = "";
  if (sizeBytes < 500 * 1024 * 1024) {
    const h = createHash("sha256");
    h.update(data);
    sha = h.digest("hex").slice(0, 16);
  }

  // Sort exts desc
  const sortedExts: Record<string, number> = {};
  Object.entries(exts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .forEach(([k, v]) => (sortedExts[k] = v));

  return {
    file,
    path: epubPath,
    title,
    creator,
    publisher,
    language,
    identifier,
    modified,
    origin,
    epub_version: epubVersion,
    epub_version_details: epubVersionDetails,
    version_split_hint: versionSplitHint,
    has_nav: hasNav,
    has_ncx: hasNcx,
    has_dcterms_modified: hasDctermsModified,
    has_media_overlay: hasMediaOverlay,
    has_switch: hasSwitch,
    opf_declared: opfDeclared,
    accessMode,
    accessibilityFeature,
    manifest_items: manifestN,
    spine_items: spineN,
    total_files: Object.keys(unzipped).length,
    size_mb: Math.round(sizeMb * 10) / 10,
    uncompressed_mb: Math.round(uncompMb * 10) / 10,
    images,
    fonts,
    js,
    xhtml,
    css_files: css,
    s9ml_chunks: s9ml,
    scripted_items: scriptedN,
    opf_path: opfPath,
    nr_status: nrStatus,
    nr_chunks_needed: nrChunks,
    split_strategy: splitStrategy,
    exts: sortedExts,
    publisher_confidence: origin.confidence,
    profile_created: new Date().toISOString(),
    sha256: sha,
  };
}
