import { test, expect, describe } from "bun:test";
import { profileEpub } from "../web/profile.ts";
import { splitBySize, splitByToc } from "../web/splitter.ts";
import { existsSync, statSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const EPUB_YOUR_HEALTH = "/home/toxic/Downloads/Your Health Today.epub";
const EPUB_FINANCIAL = "/home/toxic/Downloads/Financial Accounting for Managers.epub";
const EPUB_RAMS = "/home/toxic/Downloads/[Full Text] Rams Write - Rhetoric and Critical Engagement 9781324081821.epub";

const ROOT = "/home/toxic/projects/boundless";
const PROCESSING = join(ROOT, "processing");
const DONE = join(PROCESSING, "done");

describe("profile — publisher-origin detection", () => {
  test("Your Health Today = McGraw Hill MHE Acme s9ml (134MB)", async () => {
    if (!existsSync(EPUB_YOUR_HEALTH)) return;
    const p = await profileEpub(EPUB_YOUR_HEALTH);
    expect(p.origin.publisher).toBe("McGraw Hill Education");
    expect(p.origin.pipeline).toMatch(/MHE Acme/);
    expect(p.size_mb).toBeGreaterThan(130);
    expect(p.spine_items).toBeGreaterThan(200);
    expect(p.scripted_items).toBeGreaterThan(200);
    expect(p.s9ml_chunks).toBeGreaterThan(100);
    expect(p.nr_status).toMatch(/EXCEEDS 50MB/);
  }, { timeout: 30_000 });

  test("Financial Accounting = McGraw Hill Classic OEBPS (30MB)", async () => {
    if (!existsSync(EPUB_FINANCIAL)) return;
    const p = await profileEpub(EPUB_FINANCIAL);
    expect(p.origin.publisher).toBe("McGraw Hill Education");
    expect(p.origin.pipeline).toMatch(/Classic OEBPS/);
    expect(p.title).toMatch(/Financial Accounting/);
    expect(p.publisher).toMatch(/McGraw/);
    expect(p.size_mb).toBeGreaterThan(25);
    expect(p.spine_items).toBeGreaterThan(30);
    expect(p.scripted_items).toBe(0);
    expect(p.images).toBeGreaterThan(500);
  }, { timeout: 30_000 });

  test("Rams Write = W.W. Norton CSU Custom (33MB)", async () => {
    if (!existsSync(EPUB_RAMS)) return;
    const p = await profileEpub(EPUB_RAMS);
    expect(p.origin.publisher).toMatch(/Norton/);
    expect(p.origin.imprint).toMatch(/CSU/);
    expect(p.creator).toMatch(/Colorado/);
    expect(p.fonts).toBeGreaterThan(50);
  }, { timeout: 30_000 });
});

describe("split — size-based 50MB cap", () => {
  test("Financial Accounting <=50MB chunk", async () => {
    if (!existsSync(EPUB_FINANCIAL)) return;
    const out = join(DONE, "test_fin_size");
    mkdirSync(out, { recursive: true });
    const r = splitBySize(EPUB_FINANCIAL, out, 50 * 1024 * 1024);
    for (const s of r.sections) {
      expect(statSync(join(out, s)).size).toBeLessThanOrEqual(50 * 1024 * 1024 + 1024);
    }
  }, { timeout: 30_000 });

  test("Rams Write <=50MB chunk", async () => {
    if (!existsSync(EPUB_RAMS)) return;
    const out = join(DONE, "test_rams_size");
    mkdirSync(out, { recursive: true });
    const r = splitBySize(EPUB_RAMS, out, 50 * 1024 * 1024);
    for (const s of r.sections) {
      expect(statSync(join(out, s)).size).toBeLessThanOrEqual(50 * 1024 * 1024 + 1024);
    }
  }, { timeout: 30_000 });

  test("Your Health Today (134MB) splits into multiple chunks", async () => {
    if (!existsSync(EPUB_YOUR_HEALTH)) return;
    const out = join(DONE, "test_yht_size");
    mkdirSync(out, { recursive: true });
    const r = splitBySize(EPUB_YOUR_HEALTH, out, 50 * 1024 * 1024);
    expect(r.count).toBeGreaterThanOrEqual(2);
  }, { timeout: 60_000 });
});

describe("split — TOC", () => {
  test("Rams Write produces EPUB/ structure preserved", async () => {
    if (!existsSync(EPUB_RAMS)) return;
    const out = join(DONE, "test_rams_toc");
    mkdirSync(out, { recursive: true });
    const r = splitByToc(EPUB_RAMS, out);
    expect(r.count).toBeGreaterThanOrEqual(2);
    const { unzipSync } = await import("fflate");
    for (const s of r.sections) {
      const entries = unzipSync(readFileSync(join(out, s)));
      expect(Object.keys(entries).some((n: string) => n.startsWith("EPUB/"))).toBe(true);
    }
  }, { timeout: 60_000 });
});
