/**
 * server.ts — Bun-native web server (port 10200 default).
 * - Bun.serve() with native streaming
 * - Bun.file() for /api/outputs (64KB chunks, no full-file buffer)
 * - Autonomous inbox watcher via setInterval
 * - Settings in settings.json
 * - Sovereign: never /mnt
 */

import { mkdirSync, existsSync, statSync, readFileSync, writeFileSync, readdirSync, unlinkSync, renameSync, copyFileSync, createReadStream, statSync as fsStat } from "node:fs";
import { join, basename, dirname, resolve, extname, relative } from "node:path";
import { createHash } from "node:crypto";
import { profileEpub, type EpubProfile } from "./profile.ts";
import { splitBySize, splitByToc, DefaultStrategy, type SplitReport } from "./splitter.ts";

const ROOT = resolve(dirname(import.meta.path.replace("file://", "")), "..");
const PROCESSING_DIR = process.env.PROCESSING_DIR
  ? resolve(process.env.PROCESSING_DIR)
  : join(ROOT, "processing");
const PROFILES_DIR = process.env.PROFILES_DIR
  ? resolve(process.env.PROFILES_DIR)
  : join(ROOT, "profiles");
const SETTINGS_PATH = join(ROOT, "settings.json");

// Load .env
function loadEnv() {
  const env = join(ROOT, ".env");
  if (!existsSync(env)) return;
  for (const line of readFileSync(env, "utf-8").split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) continue;
    const [k, ...v] = t.split("=");
    process.env[k.trim()] ??= v.join("=").trim();
  }
}
loadEnv();

const PORT = parseInt(process.env.PORT || "10200", 10);
const HOST = process.env.HOST || "0.0.0.0";
const MAX_SIZE_MB = parseInt(process.env.MAX_SIZE_MB || "50", 10);
const INBOX = join(PROCESSING_DIR, "inbox");
const ACTIVE = join(PROCESSING_DIR, "active");
const DONE = join(PROCESSING_DIR, "done");
const FAILED = join(PROCESSING_DIR, "failed");
for (const d of [INBOX, ACTIVE, DONE, FAILED, PROFILES_DIR, PROCESSING_DIR]) {
  mkdirSync(d, { recursive: true });
}

const WEB_DIR = dirname(import.meta.path.replace("file://", ""));

interface Settings {
  auto_watch_inbox: boolean;
  auto_profile_on_upload: boolean;
  auto_split_on_upload: boolean;
  default_max_size_mb: number;
  max_size_mb_options: number[];
  natural_reader_limit_mb: number;
  default_split_method: "size" | "toc";
  scan_recursive: boolean;
  scan_extensions: string[];
  tray_enabled: boolean;
  auto_open_browser_on_launch: boolean;
  theme: "dark" | "light";
  log_level: string;
  open_browser_after_start: boolean;
  host: string;
  port: number;
}
const DEFAULT_SETTINGS: Settings = {
  auto_watch_inbox: true,
  auto_profile_on_upload: true,
  auto_split_on_upload: false,
  default_max_size_mb: MAX_SIZE_MB,
  max_size_mb_options: [25, 50, 75, 100],
  natural_reader_limit_mb: 50,
  default_split_method: "size",
  scan_recursive: false,
  scan_extensions: ["epub", "pdf", "docx", "doc"],
  tray_enabled: false,
  auto_open_browser_on_launch: true,
  theme: "dark",
  log_level: "info",
  open_browser_after_start: true,
  host: HOST,
  port: PORT,
};
function loadSettings(): Settings {
  if (!existsSync(SETTINGS_PATH)) return { ...DEFAULT_SETTINGS };
  try {
    const s = JSON.parse(readFileSync(SETTINGS_PATH, "utf-8"));
    return { ...DEFAULT_SETTINGS, ...s };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}
function saveSettings(s: Partial<Settings>): Settings {
  const merged: Settings = { ...loadSettings(), ...s };
  writeFileSync(SETTINGS_PATH, JSON.stringify(merged, null, 2));
  return merged;
}

// ---------- helpers ----------
function ensureIn(p: string): string {
  const rp = resolve(p);
  if (!rp.startsWith(resolve(INBOX))) throw new Error("403 path traversal");
  return rp;
}
function ensureDone(p: string): string {
  const rp = resolve(p);
  if (!rp.startsWith(resolve(DONE))) throw new Error("403 path traversal");
  return rp;
}
function checkSovereign(p: string): string {
  const rp = resolve(p);
  if (rp.split("/").includes("mnt")) throw new Error("403 sovereign boundary: /mnt denied");
  return rp;
}
function safeName(n: string): string {
  return n.replace(/[^\w\-.]/g, "_");
}
async function ensureProfile(epubPath: string): Promise<string> {
  const prof = await profileEpub(epubPath);
  const safe = safeName(basename(epubPath, extname(epubPath))).slice(0, 80);
  // ONE canonical file per (book, content-hash). Re-uploading the same book
  // updates the same JSON; the timestamp suffix is dropped.
  const out = join(PROFILES_DIR, `${safe}__${prof.sha256 || "nohash"}.json`);
  writeFileSync(out, JSON.stringify(prof, null, 2));
  return out;
}

// ---------- autonomous watcher ----------
const seen = new Map<string, number>();
let watcherTimer: ReturnType<typeof setInterval> | null = null;

function isStable(p: string): Promise<boolean> {
  return new Promise((resolve) => {
    let s1 = -1;
    try { s1 = statSync(p).size } catch { return resolve(false); }
    setTimeout(() => {
      let s2 = -1;
      try { s2 = statSync(p).size } catch { return resolve(false); }
      resolve(s1 === s2 && s1 > 0);
    }, 1500);
  });
}

async function processOne(file: string, settings: Settings) {
  const log: string[] = [];
  try {
    if (settings.auto_profile_on_upload) {
      const p = await ensureProfile(file);
      log.push(`profile → ${basename(p)}`);
    }
    if (settings.auto_split_on_upload) {
      const out = join(DONE, `${basename(file, extname(file))}_${settings.default_split_method}`);
      mkdirSync(out, { recursive: true });
      const r = settings.default_split_method === "toc"
        ? splitByToc(file, out)
        : splitBySize(file, out, { ...DefaultStrategy, maxSizeBytes: settings.default_max_size_mb * 1024 * 1024 });
      log.push(`split → ${r.count} chunks in ${basename(out)}`);
    }
    const dest = join(DONE, basename(file));
    let finalDest = dest;
    if (existsSync(dest)) finalDest = join(DONE, `${basename(file, extname(file))}_${Date.now()}${extname(file)}`);
    renameSync(file, finalDest);
    log.push(`done → ${basename(finalDest)}`);
  } catch (e: any) {
    log.push(`FAILED: ${e.message}`);
    try { renameSync(file, join(FAILED, basename(file))); } catch {}
  }
  return log;
}

async function watcherTick() {
  const settings = loadSettings();
  if (!settings.auto_watch_inbox) return;
  let files: string[];
  try { files = readdirSync(INBOX); } catch { return; }
  for (const f of files) {
    const full = join(INBOX, f);
    try { if (!statSync(full).isFile()) continue; } catch { continue; }
    const sz = (() => { try { return statSync(full).size } catch { return -1 } })();
    if (seen.get(f) === sz) continue;
    seen.set(f, sz);
    if (await isStable(full)) {
      const log = await processOne(full, settings);
      console.log(`[watcher] ${f}: ${log.join(" | ")}`);
      seen.delete(f);
    }
  }
}

function startWatcher() {
  if (watcherTimer) return;
  watcherTimer = setInterval(watcherTick, 2000);
}

// ---------- HTML pages ----------
function html(filename: string): Response {
  const p = join(WEB_DIR, filename);
  if (!existsSync(p)) return new Response("Not found", { status: 404 });
  return new Response(readFileSync(p, "utf-8"), {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

// ---------- HTTP server (Bun.serve) ----------
const server = Bun.serve({
  port: PORT,
  hostname: HOST,
  // Allow up to 500MB uploads for large publisher EPUBs (McGraw s9ml books run 130-200MB)
  maxRequestBodySize: 1024 * 1024 * 500,
  async fetch(req) {
    const url = new URL(req.url);
    const method = req.method;
    const path = url.pathname;

    // ---------- Pages ----------
    if (method === "GET" && path === "/") return html("index.html");
    if (method === "GET" && path === "/settings") return html("settings.html");

    // ---------- Health ----------
    if (method === "GET" && path === "/api/health") {
      const count = (d: string) => { try { return readdirSync(d).length } catch { return 0 } };
      return Response.json({
        status: "ok",
        port: PORT, host: HOST, max_size_mb: MAX_SIZE_MB,
        processing_dir: PROCESSING_DIR, profiles_dir: PROFILES_DIR,
        inbox: count(INBOX), active: count(ACTIVE), done: count(DONE),
        failed: count(FAILED),
        profiles: count(PROFILES_DIR),
        version: "2.0.0",
      });
    }

    // ---------- Debug ----------
    if (method === "GET" && path === "/api/debug") {
      return Response.json({
        bun_version: Bun.version,
        pid: process.pid,
        cwd: process.cwd(),
        root: ROOT,
        port: PORT,
        host: HOST,
        processing: PROCESSING_DIR,
        profiles: PROFILES_DIR,
        watcher_running: !!watcherTimer,
        max_request_body_bytes: 1024 * 1024 * 500,
      });
    }

    // ---------- Settings ----------
    if (method === "GET" && path === "/api/settings") {
      return Response.json(loadSettings());
    }
    if (method === "PUT" && path === "/api/settings") {
      const body = await req.json();
      const saved = saveSettings(body);
      return Response.json(saved);
    }

    // ---------- Profile ----------
    if (method === "GET" && path.startsWith("/api/profile/")) {
      const upid = decodeURIComponent(path.replace("/api/profile/", ""));
      let p: string;
      try { p = ensureIn(join(INBOX, upid)); } catch (e: any) { return new Response(e.message, { status: 403 }); }
      if (!existsSync(p)) return new Response("Not found", { status: 404 });
      return Response.json(await profileEpub(p));
    }

    // ---------- Upload ----------
    if (method === "POST" && path === "/api/upload") {
      const form = await req.formData();
      const files = form.getAll("files") as File[];
      const settings = loadSettings();
      const out: any[] = [];
      for (const f of files) {
        const ts = Date.now();
        const safe = safeName(f.name);
        const dest = join(INBOX, `${basename(safe, extname(safe))}_${ts}${extname(safe)}`);
        // Stream upload to disk (Bun.file is faster than fs.write)
        await Bun.write(dest, f);
        let prof: EpubProfile | null = null;
        if (settings.auto_profile_on_upload) {
          try { prof = await profileEpub(dest); } catch (e) { console.error(e); }
        }
        out.push({
          upload_id: basename(dest),
          filename: f.name,
          size: statSync(dest).size,
          size_mb: prof ? prof.size_mb : Math.round(statSync(dest).size / 1024 / 1024 * 10) / 10,
          profile: prof,
        });
      }
      return Response.json({ uploads: out, count: out.length });
    }

    // ---------- Process (inbox → active → done) ----------
    const procMatch = path.match(/^\/api\/process\/(.+)$/);
    if (method === "POST" && procMatch) {
      const upid = decodeURIComponent(procMatch[1]);
      const method2 = url.searchParams.get("method") || "size";
      const maxMb = parseInt(url.searchParams.get("max_size_mb") || `${loadSettings().default_max_size_mb}`, 10);
      let src: string;
      try { src = ensureIn(join(INBOX, upid)); } catch (e: any) { return new Response(e.message, { status: 403 }); }
      if (!existsSync(src)) return new Response("Not found", { status: 404 });
      const log: string[] = [];
      try {
        const prof = await ensureProfile(src);
        log.push(`profile → ${basename(prof)}`);
        const active = join(ACTIVE, basename(src));
        renameSync(src, active);
        log.push(`active → ${basename(active)}`);
        const out = join(DONE, `${basename(active, extname(active))}_${method2}`);
        const r: SplitReport = method2 === "toc"
          ? splitByToc(active, out)
          : splitBySize(active, out, { ...DefaultStrategy, maxSizeBytes: maxMb * 1024 * 1024 });
        log.push(`split → ${r.count} chunks in ${basename(out)}`);
        const finalDest = join(DONE, basename(active));
        let finalPath = finalDest;
        if (existsSync(finalDest)) finalPath = join(DONE, `${basename(active, extname(active))}_${Date.now()}${extname(active)}`);
        renameSync(active, finalPath);
        log.push(`done → ${basename(finalPath)}`);
        return Response.json({ ok: true, log, result: r });
      } catch (e: any) {
        log.push(`FAILED: ${e.message}`);
        return Response.json({ error: e.message, log }, { status: 500 });
      }
    }

    // ---------- Split (size) ----------
    const splitMatch = path.match(/^\/api\/split\/(.+)$/);
    if (method === "POST" && splitMatch) {
      const upid = decodeURIComponent(splitMatch[1]);
      const maxMb = parseInt(url.searchParams.get("max_size_mb") || `${MAX_SIZE_MB}`, 10);
      let src: string;
      try { src = ensureIn(join(INBOX, upid)); } catch (e: any) { return new Response(e.message, { status: 403 }); }
      if (!existsSync(src)) return new Response("Not found", { status: 404 });
      const out = join(DONE, basename(src, extname(src)));
      const r = splitBySize(src, out, { ...DefaultStrategy, maxSizeBytes: maxMb * 1024 * 1024 });
      return Response.json(r);
    }

    // ---------- Split (TOC) ----------
    const tocMatch = path.match(/^\/api\/split-toc\/(.+)$/);
    if (method === "POST" && tocMatch) {
      const upid = decodeURIComponent(tocMatch[1]);
      let src: string;
      try { src = ensureIn(join(INBOX, upid)); } catch (e: any) { return new Response(e.message, { status: 403 }); }
      if (!existsSync(src)) return new Response("Not found", { status: 404 });
      const out = join(DONE, `${basename(src, extname(src))}_toc`);
      const r = splitByToc(src, out);
      return Response.json(r);
    }

    // ---------- Streaming output download (Bun.file) ----------
    const outMatch = path.match(/^\/api\/outputs\/(.+)\/(.+)$/);
    if (method === "GET" && outMatch) {
      const sub = decodeURIComponent(outMatch[1]);
      const file = decodeURIComponent(outMatch[2]);
      let p: string;
      try { p = ensureDone(join(DONE, sub, file)); } catch (e: any) { return new Response(e.message, { status: 403 }); }
      if (!existsSync(p)) return new Response("Not found", { status: 404 });
      // Bun.file returns a BunFile that streams — never loads whole file
      const bf = Bun.file(p);
      return new Response(bf, {
        headers: {
          "Content-Type": bf.type || (extname(p) === ".epub" ? "application/epub+zip" : "application/octet-stream"),
          "Content-Disposition": `attachment; filename="${file}"`,
        },
      });
    }

    // ---------- Processing state ----------
    if (method === "GET" && path === "/api/processing") {
      const list = (d: string) => {
        const out: any[] = [];
        try {
          for (const f of readdirSync(d)) {
            const full = join(d, f);
            const st = statSync(full);
            if (st.isFile()) out.push({ name: f, size: st.size, modified: st.mtimeMs });
            else if (st.isDirectory()) {
              let sz = 0;
              for (const c of readdirSync(full)) {
                try { sz += statSync(join(full, c)).size } catch {}
              }
              out.push({ name: f, type: "dir", size: sz });
            }
          }
        } catch {}
        return out;
      };
      return Response.json({ inbox: list(INBOX), active: list(ACTIVE), done: list(DONE), failed: list(FAILED) });
    }

    // ---------- Scan ----------
    if (method === "POST" && path === "/api/scan") {
      const target = checkSovereign(join(url.searchParams.get("directory") || ""));
      if (!existsSync(target) || !statSync(target).isDirectory()) {
        return new Response(`Directory not found: ${target}`, { status: 404 });
      }
      const settings = loadSettings();
      const exts = settings.scan_extensions;
      const files: string[] = [];
      for (const e of exts) {
        if (settings.scan_recursive) {
          // rglob equivalent
          const walk = (d: string) => {
            for (const f of readdirSync(d)) {
              const p = join(d, f);
              try {
                if (statSync(p).isDirectory()) walk(p);
                else if (p.toLowerCase().endsWith("." + e)) files.push(p);
              } catch {}
            }
          };
          walk(target);
        } else {
          for (const f of readdirSync(target)) {
            if (f.toLowerCase().endsWith("." + e)) files.push(join(target, f));
          }
        }
      }
      const created: string[] = [];
      for (const f of files) {
        try { created.push(await ensureProfile(f)); } catch {}
      }
      const profiles = created.map((p) => JSON.parse(readFileSync(p, "utf-8")));
      return Response.json({ scanned: files.length, profiles_created: created.length, profiles });
    }

    // ---------- Profiles list/delete ----------
    if (method === "GET" && path === "/api/profiles") {
      const files = readdirSync(PROFILES_DIR).filter((f) => f.endsWith(".json")).sort();
      const profiles = files.map((f) => {
        try {
          const d = JSON.parse(readFileSync(join(PROFILES_DIR, f), "utf-8"));
          return {
            file: f, title: d.title, creator: d.creator, publisher: d.publisher,
            origin: d.origin, nr_status: d.nr_status, size_mb: d.size_mb,
            split_strategy: d.split_strategy, nr_chunks_needed: d.nr_chunks_needed,
            sha256: d.sha256,
          };
        } catch (e: any) { return { file: f, error: e.message }; }
      });
      return Response.json({ count: profiles.length, profiles });
    }
    const profDelMatch = path.match(/^\/api\/profiles\/(.+)$/);
    if (method === "DELETE" && profDelMatch) {
      const name = decodeURIComponent(profDelMatch[1]);
      const p = resolve(join(PROFILES_DIR, name));
      if (!p.startsWith(resolve(PROFILES_DIR))) return new Response("403", { status: 403 });
      if (existsSync(p)) { unlinkSync(p); return Response.json({ deleted: name }); }
      return new Response("Not found", { status: 404 });
    }

    // ---------- Edge cases ----------
    if (method === "GET" && path === "/api/edge-cases") {
      // Lazy import to avoid loading registry on every request
      const { EdgeCaseRegistry } = await import("../src/boundless/registry.py").catch(() => ({ EdgeCaseRegistry: null }));
      if (!EdgeCaseRegistry) {
        return Response.json({ epub: [], pdf: [], docx: [], a11y: [], note: "registry not loaded" });
      }
      return Response.json({
        epub: EdgeCaseRegistry.EPUB_EDGE_CASES,
        pdf: EdgeCaseRegistry.PDF_EDGE_CASES,
        docx: EdgeCaseRegistry.DOCX_EDGE_CASES,
        a11y: EdgeCaseRegistry.ACCESSIBILITY_EDGE_CASES,
      });
    }

    return new Response("Not found", { status: 404 });
  },
});

startWatcher();
console.log(`boundless sovereign maximal web UI on http://${server.hostname}:${server.port}`);
console.log(`Drop EPUBs into ${INBOX} for autonomous processing`);
