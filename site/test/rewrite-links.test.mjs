import assert from "node:assert/strict";
import test from "node:test";

import { repositorySourceUrl } from "../src/plugins/rewrite-links.mjs";

test("repository source URLs follow existing file and directory targets", () => {
  const cases = [
    [
      "rule-catalog/workflows",
      "https://github.com/dotnetpower/fdai/tree/main/rule-catalog/workflows",
    ],
    [
      "services/core-control-plane/src/fdai/core/readiness",
      "https://github.com/dotnetpower/fdai/tree/main/services/core-control-plane/src/fdai/core/readiness",
    ],
    [
      "infra/envs/staging.tfvars.example",
      "https://github.com/dotnetpower/fdai/blob/main/infra/envs/staging.tfvars.example",
    ],
    [
      ".github/CODEOWNERS",
      "https://github.com/dotnetpower/fdai/blob/main/.github/CODEOWNERS",
    ],
  ];

  for (const [target, expected] of cases) {
    assert.equal(repositorySourceUrl(target), expected, target);
  }
});

test("repository source URLs preserve anchors and reject missing targets", () => {
  assert.equal(
    repositorySourceUrl(".github/CODEOWNERS", "approval-boundary"),
    "https://github.com/dotnetpower/fdai/blob/main/.github/CODEOWNERS#approval-boundary",
  );
  assert.equal(repositorySourceUrl("missing/source-without-extension"), null);
  assert.equal(repositorySourceUrl("../outside-repository"), null);
});
