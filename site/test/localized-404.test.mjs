import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Korean 404 locale fallback redirects within the configured base", async () => {
  const source = await readFile(
    new URL("../src/pages/ko/404.astro", import.meta.url),
    "utf8",
  );

  assert.match(source, /import\.meta\.env\.BASE_URL/);
  assert.match(source, /const target = `\$\{base\}ko\/`/);
  assert.match(source, /window\.location\.replace\(target\)/);
  assert.match(source, /name="robots" content="noindex"/);
});
