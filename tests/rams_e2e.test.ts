import { test, expect, describe } from "bun:test";
import { profileEpub } from "../web/profile.ts";
import { splitBySize, splitByToc } from "../web/splitter.ts";
import { existsSync, statSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { unzipSync } from "fflate";

const EPUB_RAMS = "/home/toxic/Downloads/[Full Text] Rams Write - Rhetoric and Critical Engagement 9781324081821.epub";
const ROOT = "/home/toxic/projects/boundless";
const PROCESSING = join(ROOT, "processing");
const DONE = join(PROCESSING, "e2e_rams");

describe("Rams Write E2E", () => {
  test("Profile Rams Write", async () => {
    if (!existsSync(EPUB_RAMS)) return;
    const p = await profileEpub(EPUB_RAMS);
    expect(p.origin.publisher).toMatch(/Norton/);
    expect(p.origin.imprint).toMatch(/CSU/);
    expect(p.creator).toMatch(/Colorado/);
    expect(p.fonts).toBeGreaterThan(50);
  }, { timeout: 30_000 });

  test("Split Rams Write by Size (50MB)", async () => {
    if (!existsSync(EPUB_RAMS)) return;
    const out = join(DONE, "size");
    mkdirSync(out, { recursive: true });
    const r = splitBySize(EPUB_RAMS, out, 50 * 1024 * 1024);
    for (const s of r.sections) {
      expect(statSync(join(out, s)).size).toBeLessThanOrEqual(50 * 1024 * 1024 + 1024);
    }
  }, { timeout: 30_000 });

  test("Split Rams Write by TOC", async () => {
    if (!existsSync(EPUB_RAMS)) return;
    const out = join(DONE, "toc");
    mkdirSync(out, { recursive: true });
    const r = splitByToc(EPUB_RAMS, out);
    expect(r.count).toBeGreaterThanOrEqual(2);
    for (const s of r.sections) {
      const entries = unzipSync(readFileSync(join(out, s)));
      expect(Object.keys(entries).some((n: string) => n.startsWith("EPUB/"))).toBe(true);
    }
  }, { timeout: 60_000 });
});
