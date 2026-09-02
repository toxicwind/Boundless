import { readFileSync } from "node:fs";
import { unzipSync, strFromU8 } from "fflate";
import { parseToc } from "./splitter.ts";
import { basename, dirname, join } from "node:path";

const sourcePath = "/tmp/test_rams/Rams Write Rhetoric and Critical Engagement.epub";
const data = readFileSync(sourcePath);
const unzipped = unzipSync(data);

const fileNames = Object.keys(unzipped);
const opfFile = fileNames.find((f) => f.endsWith(".opf"));
if (!opfFile) throw new Error("No OPF");
const opfRaw = strFromU8(unzipped[opfFile]);
const opfDir = dirname(opfFile);

let navPath: string | null = null;
const navRe = /<item\s+([^>]+)\/?>/g;
let m;
while ((m = navRe.exec(opfRaw))) {
    const props = m[1];
    const hrefM = props.match(/href=["']([^"']+)["']/);
    if (hrefM && /properties=["'][^"']*\bnav\b/.test(props)) {
        navPath = join(opfDir, hrefM[1]);
    }
}

if (navPath && unzipped[navPath]) {
    const toc = parseToc(strFromU8(unzipped[navPath]), navPath);
    console.log(JSON.stringify(toc, null, 2));
} else {
    console.log("No nav found");
}
