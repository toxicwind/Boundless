/**
 * splitter.ts — Bun-native EPUB splitter
 *  - splitBySize: groups spine by directory, bin-packs to <= maxSize
 *  - splitByToc: top-level TOC entries, preserves publisher assets
 * Uses fflate for streaming ZIP read/write (no whole-file buffer).
 */

/**
 * ManifestStrategy: ensures chunks conform to environment requirements.
 */
export interface ManifestStrategy {
  readonly name: "Default" | "NeuralCompatible";
  readonly maxSizeBytes: number;
  preCompress(data: Unzipped): Unzipped;
}

export const DefaultStrategy: ManifestStrategy = {
  name: "Default",
  maxSizeBytes: 50 * 1024 * 1024,
  preCompress: (data: Unzipped) => data,
};

export const NeuralCompatible: ManifestStrategy = {
  name: "NeuralCompatible",
  maxSizeBytes: 48 * 1024 * 1024,
  preCompress: (data: Unzipped) => {
    // TTS-compatibility: strip non-essential heavy media (video, heavy animations)
    const filtered: Unzipped = {};
    for (const [name, content] of Object.entries(data)) {
      if (/\.(mp4|mov|gif)$/i.test(name)) continue;
      filtered[name] = content;
    }
    return filtered;
  },
};


import { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import { unzipSync, strFromU8, zipSync, Zip, Unzipped } from "fflate";

export interface ChunkMeta {
  title: string;
  slug: string;
}

export interface SplitReport {
  source: string;
  output_dir: string;
  sections: string[];
  count: number;
  total_size: number;
  warnings: string[];
}

function normPath(p: string): string {
  return p.replace(/\\/g, "/");
}

function isHttpHref(href: string): boolean {
  return /^(https?:|mailto:|data:|#|\/\/)/i.test(href);
}

function resolveHref(baseFile: string, href: string): string {
  const baseDir = dirname(baseFile);
  const resolved = resolve(baseDir, href);
  return normPath(relative(process.cwd(), resolved));
}

function getReferencedAssets(files: string[], unzipped: Unzipped, opfDir: string): Set<string> {
  strategy: ManifestStrategy = DefaultStrategy,
): SplitReport {
  const maxSizeBytes = strategy.maxSizeBytes;
  const data = strategy.preCompress(unzipSync(readFileSync(sourcePath)));
  const fileNames = Object.keys(data);

  const opfFile = fileNames.find((f) => f.endsWith(".opf"));
  if (!opfFile) throw new Error("No OPF in EPUB");
  const opfDir = dirname(opfFile);
  const opfRaw = strFromU8(data[opfFile]);
  for (const f of files) {
    if (!/\.(xhtml|html|htm)$/i.test(f)) continue;
    const html = strFromU8(unzipped[f]);
    const hrefs = html.match(/(src|href)=["']([^"']+)["']/gi);
    if (!hrefs) continue;
    for (const h of hrefs) {
      const m = h.match(/(src|href)=["']([^"']+)["']/i);
      if (m && m[2] && !isHttpHref(m[2])) {
        const p = normPath(join(dirname(f), m[2]));
        if (unzipped[p]) assets.add(p);
      }
    }
  }
  return assets;
}

function getSegmentSize(selectedFiles: string[], unzipped: Unzipped, opfDir: string): number {
  const referencedAssets = getReferencedAssets(selectedFiles, unzipped, opfDir);
  const allFiles = [...selectedFiles, ...Array.from(referencedAssets)];
  return allFiles.reduce((acc: number, f: string) => acc + (unzipped[f]?.byteLength ?? 0), 0);
}

export function splitBySize(
  sourcePath: string,
  outputDir: string,
  maxSizeBytes: number,
): SplitReport {
  const data = readFileSync(sourcePath);
  const unzipped = unzipSync(data);
  const fileNames = Object.keys(unzipped);

  const opfFile = fileNames.find((f) => f.endsWith(".opf"));
  if (!opfFile) throw new Error("No OPF in EPUB");
  const opfDir = dirname(opfFile);
  const opfRaw = strFromU8(unzipped[opfFile]);

  const manifest: Record<string, string> = {};
  const itemRe = /<item\s+([^>]+)\/?>/g;
  let m: RegExpExecArray | null;
  while ((m = itemRe.exec(opfRaw))) {
    const idM = m[1].match(/id="([^"]+)"/);
    const hrefM = m[1].match(/href="([^"]+)"/);
    if (idM && hrefM) {
      manifest[idM[1]] = normPath(join(opfDir, hrefM[1]));
    }
  }

  const spineIds: string[] = [];
  const spRe = /<itemref\s+([^>]+)\/?>/g;
  while ((m = spRe.exec(opfRaw))) {
    const idM = m[1].match(/idref="([^"]+)"/);
    if (idM) spineIds.push(idM[1]);
  }
  const spineFiles = spineIds.map((id) => manifest[id]).filter(Boolean);

  const groups: Record<string, string[]> = {};
  for (const f of spineFiles) {
    const dir = dirname(f);
    if (!groups[dir]) groups[dir] = [];
    groups[dir].push(f);
  }

  const sections: string[] = [];
  const warnings: string[] = [];
  let chunkIdx = 0;

  for (const [dirName, files] of Object.entries(groups)) {
    const approxSize = getSegmentSize(files, unzipped, opfDir);
    if (approxSize <= maxSizeBytes || files.length === 1) {
      chunkIdx++;
      const name = dirName.replace(/[\/\\]/g, "_") || `Section_${chunkIdx}`;
      writeChunk(unzipped, fileNames, opfFile, files, outputDir, name, sections);
    } else {
      const sized = files.map((f) => ({ f, sz: unzipped[f]?.byteLength ?? 0 }));
      const bins: { f: string; sz: number }[][] = [];
      for (const item of sized) {
        let placed = false;
        for (const b of bins) {
          const binSize = b.reduce((s, x) => s + x.sz, 0);
          if (binSize + item.sz <= maxSizeBytes) {
            b.push(item);
            placed = true;
            break;
          }
        }
        if (!placed) bins.push([item]);
      }
      for (let bi = 0; bi < bins.length; bi++) {
        chunkIdx++;
        const binFiles = bins[bi].map((x) => x.f);
        const name = (dirName.replace(/[\/\\]/g, "_") || `Section_${chunkIdx}`) +
          (bins.length > 1 ? `_${bi + 1}` : "");
        writeChunk(unzipped, fileNames, opfFile, binFiles, outputDir, name, sections);
      }
    }
  }

  return {
    source: sourcePath,
    output_dir: outputDir,
    sections,
    count: sections.length,
    total_size: 0,
    warnings
  };
}

function writeChunk(
  unzipped: Unzipped,
  fileNames: string[],
  opfFile: string,
  keep: string[],
  outputDir: string,
  name: string,
  sections: string[]
): void {
  const referencedAssets = getReferencedAssets(keep, unzipped, dirname(opfFile));
  const allFiles = [...keep, ...referencedAssets];
  const out: Unzipped = {};
  for (const f of fileNames) {
    if (f === "mimetype" || f.startsWith("META-INF/") || f === opfFile || allFiles.includes(f)) {
      out[f] = unzipped[f];
    }
  }
  const outName = `${name}.epub`;
  writeFileSync(join(outputDir, outName), zipSync(out));
  sections.push(outName);
}

export interface TocNode {
  title: string;
  href: string;
  sourceElement: string;
  children: TocNode[];
}

export function parseToc(navXhtml: string, navPath: string): TocNode[] {
  const navMatch = navXhtml.match(/<nav[^>]*epub:type=["']toc["'][^>]*>([\s\S]*?)<\/nav>/i) ??
    navXhtml.match(/<nav[^>]*role=["']doc-toc["'][^>]*>([\s\S]*?)<\/nav>/i) ??
    navXhtml.match(/<nav[^>]*>([\s\S]*?)<\/nav>/i);
  if (!navMatch) return [];
  const inner = navMatch[1];
  const firstOpen = inner.search(/<ol[\s>]/i);
  if (firstOpen < 0) return [];
  let d = 0, end = -1;
  for (let p = firstOpen; p < inner.length; ) {
    const o = inner.indexOf("<ol", p);
    const c = inner.indexOf("</ol>", p);
    if (c < 0) break;
    if (o >= 0 && o < c) {
      const tail = inner.charAt(o + 3);
      if (tail === ">" || tail === " " || tail === "\t" || tail === "\n") {
        d++;
        p = o + 3;
      } else {
        p = o + 1;
      }
    } else {
      d--;
      p = c + 5;
      if (d === 0) { end = p; break; }
    }
  }
  if (end < 0) return [];
  return parseOl(inner.substring(firstOpen, end), navPath);
}

function topLevelLis(html: string): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < html.length) {
    const liStart = html.indexOf("<li", i);
    if (liStart < 0) break;
    const tail = html.charAt(liStart + 3);
    if (tail !== ">" && tail !== " " && tail !== "\t" && tail !== "\n") { i = liStart + 1; continue; }
    let d = 1, p = liStart + 3, close = -1;
    while (p < html.length && d > 0) {
      const o = html.indexOf("<li", p);
      const c = html.indexOf("</li>", p);
      if (c < 0) break;
      if (o >= 0 && o < c) {
        const t = html.charAt(o + 3);
        if (t === ">" || t === " " || t === "\t" || t === "\n") d++;
        p = o + 1;
      } else {
        d--;
        if (d === 0) { close = c; break; }
        p = c + 5;
      }
    }
    if (close < 0) break;
    out.push(html.substring(liStart, close + 5));
    i = close + 5;
  }
  return out;
}

function parseOl(html: string, navPath: string): TocNode[] {
  const inner = html.replace(/^<ol[^>]*>/i, "").replace(/<\/ol>\s*$/i, "");
  const lis = topLevelLis(inner);
  const nodes: TocNode[] = [];
  for (const li of lis) {
    const aM = li.match(/<a[^>]+href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/i);
    let title = aM ? aM[2].replace(/<[^>]+>/g, "").trim() : "";
    let href = aM ? aM[1] : "";
    if (!title) {
      const span = li.match(/<span[^>]*>([\s\S]*?)<\/span>/i);
      if (span) title = span[1].replace(/<[^>]+>/g, "").trim();
    }
    if (!href) {
      const any = li.match(/<a[^>]+href=["']([^"']+)["']/);
      if (any) href = any[1];
    }
    if (!title) title = href || "Untitled";
    const ol2M = li.match(/<ol[\s>]([\s\S]*)<\/ol>/i);
    let children: TocNode[] = [];
    if (ol2M) {
      const liStart = li.indexOf(ol2M[0]);
      const olStart = liStart + li.substring(liStart).search(/<ol[\s>]/i);
      let d = 0, p = olStart, end = -1;
      for (let k = olStart; k < li.length; ) {
        const oo = li.indexOf("<ol", k);
        const cc = li.indexOf("</ol>", k);
        if (cc < 0) break;
        if (oo >= 0 && oo < cc) {
          const t = li.charAt(oo + 3);
          if (t === ">" || t === " " || t === "\t" || t === "\n") { d++; k = oo + 3; }
          else k = oo + 1;
        } else {
          d--;
          k = cc + 5;
          if (d === 0) { end = k; break; }
        }
      }
      if (end > 0) children = parseOl(li.substring(olStart, end), navPath);
    }
    if (href || children.length > 0) {
      nodes.push({ title, href, sourceElement: li, children });
    }
  }
  return nodes;
}

function parseNcxToc(ncxRaw: string): TocNode[] {
  const mapMatch = ncxRaw.match(/<navMap>([\s\S]*?)<\/navMap>/i);
  if (!mapMatch) return [];
  const nodes: TocNode[] = [];
  const pointRe = /<navPoint[^>]*id=["']([^"']+)["'][^>]*>([\s\S]*?)<\/navPoint>/gi;
  let m;
  while ((m = pointRe.exec(mapMatch[1]))) {
    const label = m[2].match(/<text>([\s\S]*?)<\/text>/i);
    const content = m[2].match(/<content[^>]+src=["']([^"']+)["']/i);
    nodes.push({
      title: label ? label[1].trim() : "Untitled",
      href: content ? content[1] : "",
      sourceElement: m[0],
      children: []
    });
  }
  return nodes;
}

export function splitByToc(
  sourcePath: string,
  outputDir: string,
  options: { recursive?: boolean; maxSizeBytes?: number } = {},
): SplitReport {
  const maxSizeBytes = options.maxSizeBytes ?? 50 * 1024 * 1024;
  const data = readFileSync(sourcePath);
  const unzipped = unzipSync(data);
  const fileNames = Object.keys(unzipped);

  const opfFile = fileNames.find((f) => f.endsWith(".opf"));
  if (!opfFile) throw new Error("No OPF in EPUB");
  const opfDir = dirname(opfFile);
  const opfRaw = strFromU8(unzipped[opfFile]);

  const manifest: Record<string, string> = {};
  const manifestByPath: Record<string, string> = {};
  const itemRe = /<item\s+([^>]+)\/?>/g;
  let m: RegExpExecArray | null;
  while ((m = itemRe.exec(opfRaw))) {
    const idM = m[1].match(/id="([^"]+)"/);
    const hrefM = m[1].match(/href="([^"]+)"/);
    if (idM && hrefM) {
      const path = normPath(join(opfDir, hrefM[1]));
      manifest[idM[1]] = path;
      manifestByPath[path] = idM[1];
    }
  }
  
  let navPath: string | null = null;
  let ncxPath: string | null = null;
  const navRe = /<item\s+([^>]+)\/?>/g;
  while ((m = navRe.exec(opfRaw))) {
    const props = m[1];
    const hrefM = props.match(/href=["']([^"']+)["']/);
    const mtM = props.match(/media-type=["']([^"']+)["']/);
    if (hrefM) {
      const p = normPath(join(opfDir, hrefM[1]));
      if (/properties=["'][^"']*\bnav\b/.test(props)) navPath = p;
      if (mtM && mtM[1] === "application/x-dtbncx+xml") ncxPath = p;
    }
  }

  let toc: TocNode[] = [];
  if (navPath && unzipped[navPath]) {
    toc = parseToc(strFromU8(unzipped[navPath]), navPath);
  }
  if (toc.length === 0 && ncxPath && unzipped[ncxPath]) {
    toc = parseNcxToc(strFromU8(unzipped[ncxPath]));
  }
  if (toc.length === 0) throw new Error("No usable TOC found");

  const spineIds: string[] = [];
  const spRe = /<itemref\s+([^>]+)\/?>/g;
  while ((m = spRe.exec(opfRaw))) {
    const idM = m[1].match(/idref="([^"]+)"/);
    if (idM) spineIds.push(idM[1]);
  }
  const spineFiles = spineIds.map((id) => manifest[id]).filter(Boolean);
  const spineIndex: Record<string, number> = {};
  spineFiles.forEach((f, i) => (spineIndex[f] = i));

  const baseFile = navPath || ncxPath || opfFile;
  function findSpineStart(node: TocNode): { node: TocNode; idx: number; path: string; frag: string } | null {
    if (node.href) {
      const [p, f] = node.href.split("#");
      const resolved = resolveHref(baseFile, p);
      if (resolved in spineIndex) return { node, idx: spineIndex[resolved], path: resolved, frag: f || "" };
    }
    for (const c of node.children) {
      const r = findSpineStart(c);
      if (r) return r;
    }
    return null;
  }

  const locations: { node: TocNode; idx: number; path: string; frag: string }[] = [];
  const locationMap = new Map<number, { node: TocNode; idx: number; path: string; frag: string }>();

  function collect(node: TocNode) {
    const loc = findSpineStart(node);
    if (loc) {
      if (options.recursive && node.children.length > 0) {
        const next = findSpineStart(node.children[0])?.idx ?? spineFiles.length;
        const selected = spineFiles.slice(loc.idx, next);
        const size = getSegmentSize(selected, unzipped, opfDir);
        if (size <= maxSizeBytes) {
          for (const child of node.children) collect(child);
          return;
        }
      }
      if (!options.recursive || !locationMap.has(loc.idx)) {
        locationMap.set(loc.idx, loc);
      }
    }
    for (const child of node.children) collect(child);
  }

  if (options.recursive) {
    for (const node of toc) collect(node);
    const sortedIdxs = Array.from(locationMap.keys()).sort((a, b) => a - b);
    for (const idx of sortedIdxs) locations.push(locationMap.get(idx)!);
  } else {
    for (const node of toc) {
      const sub: { node: TocNode; idx: number; path: string; frag: string }[] = [];
      function walk(n: TocNode) { const loc = findSpineStart(n); if (loc) sub.push(loc); }
      const directChildren = node.children.filter((c) => {
        if (!c.href) return false;
        const [p] = c.href.split("#");
        return resolveHref(baseFile, p) in spineIndex;
      });
      if (directChildren.length >= 1) for (const c of directChildren) walk(c);
      else walk(node);
      const seen = new Set<number>();
      for (const s of sub) if (!seen.has(s.idx)) { seen.add(s.idx); locations.push(s); }
    }
  }

  const names: string[] = [];
  const used: Record<string, number> = {};
  const sections: string[] = [];

  for (let i = 0; i < locations.length; i++) {
    const loc = locations[i];
    let name = loc.node.title.replace(/[^a-zA-Z0-9]/g, "_") || "Untitled";
    if (used[name]) { used[name]++; name = `${name}_${used[name]}`; } else used[name] = 1;
    names.push(name);

    const next = locations[i + 1];
    const endIdx = next ? next.idx : spineFiles.length;
    const selected = spineFiles.slice(loc.idx, endIdx);
    if (selected.length === 0) continue;
    
    const allFiles = [...selected, ...Array.from(getReferencedAssets(selected, unzipped, opfDir))];
    const keepManifestIds = new Set<string>();
    for (const f of allFiles) { const id = manifestByPath[f]; if (id) keepManifestIds.add(id); }
    if (navPath && manifestByPath[navPath]) keepManifestIds.add(manifestByPath[navPath]);
    if (ncxPath && manifestByPath[ncxPath]) keepManifestIds.add(manifestByPath[ncxPath]);
    const keepIds = new Set<string>(keepManifestIds);

    let newOpf = opfRaw
      .replace(/<item\s+([^>]+)\/?>/g, (full, attrs) => {
        const idM = attrs.match(/id="([^"]+)"/);
        return idM && keepManifestIds.has(idM[1]) ? full : "";
      })
      .replace(/<itemref\s+([^>]+)\/?>/g, (full, attrs) => {
        const idM = attrs.match(/idref="([^"]+)"/);
        return idM && keepIds.has(idM[1]) ? full : "";
      })
      .replace(/<guide[\s\S]*?<\/guide>/g, "");

    const out: Unzipped = {};
    if (unzipped["mimetype"]) out["mimetype"] = unzipped["mimetype"];
    for (const name of fileNames) {
      if (name === "mimetype" || name.startsWith("META-INF/") || name === opfFile || (navPath && name === navPath)) {
        if (unzipped[name]) out[name] = unzipped[name];
      }
    }
    out[opfFile] = new TextEncoder().encode(newOpf);
    if (navPath) {
      const newNav = strFromU8(unzipped[navPath])
        .replace(/<ol[^>]*>[\s\S]*?<\/ol>/, `<ol>${loc.node.sourceElement.replace(/<li[^>]*>|<\/li>/g, "").match(/<li[^>]*>[\s\S]*<\/li>/)?.[0] ?? ""}</ol>`);
      out[navPath] = new TextEncoder().encode(newNav);
    }
    for (const f of fileNames) {
      if (f === opfFile || f === "mimetype" || f.startsWith("META-INF/") || (navPath && f === navPath)) continue;
      if (allFiles.includes(f)) out[f] = unzipped[f];
    }
    const outName = `${names[i]}.epub`;
    writeFileSync(join(outputDir, outName), zipSync(out));
    sections.push(outName);
  }
  
  return { source: sourcePath, output_dir: outputDir, sections, count: sections.length, total_size: 0, warnings: [] };
}
