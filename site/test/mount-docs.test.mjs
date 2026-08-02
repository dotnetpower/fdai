import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { relative } from "node:path";
import test from "node:test";

const siteRoot = new URL("../", import.meta.url);

test("documentation mount excludes drafts and dependency trees", async () => {
  execFileSync(process.execPath, ["scripts/mount-docs.mjs"], {
    cwd: siteRoot,
    stdio: "pipe",
  });

  const manifest = JSON.parse(
    await readFile(new URL("../src/data/mount-manifest.json", import.meta.url), "utf8"),
  );
  const mounted = manifest.map((path) => relative(siteRoot.pathname, path).replaceAll("\\", "/"));

  assert(mounted.every((path) => !path.split("/").some((part) => part.startsWith("_"))));
  assert(mounted.every((path) => !path.split("/").some((part) => part.startsWith("."))));
  assert(mounted.every((path) => !path.includes("/node_modules/")));
  for (const path of [
    "src/content/docs/deck/index.md",
    "src/content/docs/deck/l100-act1-why.md",
    "src/content/docs/deck/l100-act2-how.md",
    "src/content/docs/deck/l100-act3-adopt.md",
  ]) {
    assert(mounted.includes(path), path);
  }
});
