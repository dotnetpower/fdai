import { describe, expect, test } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * Self-describing screen contract (Phase 2 enforcement).
 *
 * Every route that publishes a view snapshot MUST declare `purpose` and
 * `glossary`, composed from the shared catalog (`../deck/glossary`). This is
 * what makes the console deck screen-agnostic: a new screen becomes explainable
 * by declaring its vocabulary, and this test fails the build if a screen ships
 * a snapshot without it - so an under-described screen can never land silently
 * (the root cause the narrator used to trip on).
 *
 * The check is deliberately a source scan, not a render test: it needs no DOM,
 * no API client, and no per-route wiring, so it keeps working as screens change.
 */

const ROUTES_DIR = fileURLToPath(new URL("./", import.meta.url));

function routeFiles(): readonly string[] {
  return readdirSync(ROUTES_DIR).filter(
    (f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx"),
  );
}

/** Files that call the publish hook - i.e. contribute a screen the deck reads. */
function publishingRoutes(): readonly { file: string; source: string }[] {
  const out: { file: string; source: string }[] = [];
  for (const file of routeFiles()) {
    const source = readFileSync(ROUTES_DIR + file, "utf8");
    if (source.includes("usePublishViewContext(")) out.push({ file, source });
  }
  return out;
}

describe("self-describing screen contract", () => {
  test("there is at least one publishing route (sanity)", () => {
    expect(publishingRoutes().length).toBeGreaterThan(5);
  });

  for (const { file, source } of publishingRoutes()) {
    test(`${file} declares purpose + glossary from the shared catalog`, () => {
      expect(source, `${file}: snapshot must declare a purpose`).toMatch(/\bpurpose:/);
      expect(source, `${file}: snapshot must declare a glossary`).toMatch(/\bglossary:/);
      expect(
        source,
        `${file}: glossary must compose from the shared ../deck/glossary catalog`,
      ).toMatch(/from "\.\.\/deck\/glossary"/);
    });
  }
});
