import assert from "node:assert/strict";
import test from "node:test";

import {
  publicationRecord,
  publicationRoute,
  SITE_OWNED_ROUTES,
} from "../scripts/publication-manifest.mjs";

test("publication routes preserve locale prefixes and collapse indexes", () => {
  assert.equal(publicationRoute([], "sre/README.md"), "/sre/");
  assert.equal(publicationRoute(["ko"], "sre/README-ko.md"), "/ko/sre/");
  assert.equal(publicationRoute(["reference", "roadmap"], "agents/workflows.md"), "/reference/roadmap/agents/workflows/");
});

test("publication records retain canonical ownership and derived facts", () => {
  const record = publicationRecord({
    sourcePath: "docs/user-guide/architecture.md",
    sourceKind: "user-guide",
    enPrefix: [],
    koPrefix: ["ko"],
    relPath: "architecture.md",
    content: `---
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: abc
---
![Flow](../diagrams/generated/fdai-system-overview.en.svg)`,
  });

  assert.equal(record.route, "/architecture/");
  assert.equal(record.source_path, "docs/user-guide/architecture.md");
  assert.deepEqual(record.derived_sources, ["docs/roadmap/architecture/goals-and-metrics.md"]);
  assert.deepEqual(record.diagram_ids, ["fdai-system-overview"]);
});

test("deck details are explicitly search-only and site fallbacks are classified", () => {
  const record = publicationRecord({
    sourcePath: "docs/user-guide/deck/reference.md",
    sourceKind: "user-guide",
    enPrefix: [],
    koPrefix: ["ko"],
    relPath: "deck/reference.md",
    content: "# Reference",
  });

  assert.equal(record.publication_state, "search-only");
  assert.equal(SITE_OWNED_ROUTES.filter((item) => item.publication_state === "fallback").length, 2);
});

test("nested roadmap indexes are explicitly search-only", () => {
  const record = publicationRecord({
    sourcePath: "docs/roadmap/agents/README.md",
    sourceKind: "roadmap",
    enPrefix: ["reference", "roadmap"],
    koPrefix: ["ko", "reference", "roadmap"],
    relPath: "agents/README.md",
    content: "# Appendices",
  });

  assert.equal(record.publication_state, "search-only");
});
