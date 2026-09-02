import { test, expect, describe } from "bun:test";
import { profileEpub } from "../web/profile.ts";
import { splitBySize } from "../web/splitter.ts";
import { existsSync, statSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const EPUB_FINANCIAL = "/home/toxic/Downloads/Financial Accounting for Managers.epub";
const PROCESSING = "/home/toxic/projects/boundless/processing";
const DONE = join(PROCESSING, "done");

describe("Financial Accounting for Managers e2e", () => {
  test("profile and metadata verification", async () => {
    if (!existsSync(EPUB_FINANCIAL)) return;
    const p = await profileEpub(EPUB_FINANCIAL);
    expect(p.origin.publisher).toBe("McGraw Hill Education");
    expect(p.title).toMatch(/Financial Accounting/);
    expect(p.size_mb).toBeGreaterThan(25);
    expect(p.spine_items).toBeGreaterThan(30);
  });

  test("size-based splitting <=50MB", async () => {
    if (!existsSync(EPUB_FINANCIAL)) return;
    const out = join(DONE, "test_fin_e2e");
    mkdirSync(out, { recursive: true });
    const r = splitBySize(EPUB_FINANCIAL, out, 50 * 1024 * 1024);
    for (const s of r.sections) {
      expect(statSync(join(out, s)).size).toBeLessThanOrEqual(50 * 1024 * 1024 + 1024);
    }
  });
});
