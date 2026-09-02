import { test, expect, describe } from "bun:test";
import { profileEpub } from "../web/profile.ts";
import { splitBySize, splitByToc } from "../web/splitter.ts";
import { unzipSync } from "fflate";
import { existsSync, statSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const EPUB_YOUR_HEALTH = "/home/toxic/Downloads/Your Health Today.epub";
const ROOT = "/home/toxic/projects/boundless";
const PROCESSING = join(ROOT, "processing");
const DONE = join(PROCESSING, "done");

describe("YHT E2E", () => {
  test("profile, size-splitting, and toc-splitting for Your Health Today", async () => {
    if (!existsSync(EPUB_YOUR_HEALTH)) {
      console.warn("Skipping YHT E2E: EPUB not found");
      return;
    }

    // 1. Profiling & Metadata Verification
    const p = await profileEpub(EPUB_YOUR_HEALTH);
    expect(p.origin.publisher).toBe("McGraw Hill Education");
    expect(p.origin.pipeline).toMatch(/MHE Acme/);
    expect(p.size_mb).toBeGreaterThan(130);
    expect(p.title).toMatch(/Your Health Today/);

    // 2. Size-based splitting
    const outSize = join(DONE, "test_yht_e2e_size");
    mkdirSync(outSize, { recursive: true });
    const rSize = splitBySize(EPUB_YOUR_HEALTH, outSize, 50 * 1024 * 1024);
    expect(rSize.count).toBeGreaterThanOrEqual(2);
    for (const s of rSize.sections) {
      expect(statSync(join(outSize, s)).size).toBeLessThanOrEqual(50 * 1024 * 1024 + 1024);
    }

    // 3. TOC-splitting
    const outToc = join(DONE, "test_yht_e2e_toc");
    mkdirSync(outToc, { recursive: true });
    const rToc = splitByToc(EPUB_YOUR_HEALTH, outToc);
    expect(rToc.count).toBeGreaterThanOrEqual(2);
    
    // Basic TOC verification
    for (const s of rToc.sections) {
      const entries = unzipSync(readFileSync(join(outToc, s)));
      // Verify EPUB structure
      expect(Object.keys(entries).some((n: string) => n.startsWith("EPUB/"))).toBe(true);
    }
  }, { timeout: 120_000 });
});
