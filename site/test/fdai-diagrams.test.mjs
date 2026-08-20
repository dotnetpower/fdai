import assert from "node:assert/strict";
import test from "node:test";

import { diagramEmbedForImage } from "../src/plugins/fdai-diagrams.mjs";

test("FDAI diagram embeds preserve locale and route depth", () => {
  const cases = [
    [
      "/repo/site/src/content/docs/architecture.md",
      "../diagrams/generated/fdai-system-overview.en.svg",
      '../diagrams/generated/fdai-system-overview.manifest.json',
      '../diagrams/generated/fdai-system-overview.en.svg',
    ],
    [
      "/repo/site/src/content/docs/ko/architecture.md",
      "../../diagrams/generated/fdai-system-overview.ko.svg",
      '../../diagrams/generated/fdai-system-overview.manifest.json',
      '../../diagrams/generated/fdai-system-overview.ko.svg',
    ],
    [
      "/repo/site/src/content/docs/reference/roadmap/agents/workflows.md",
      "../../../../../../diagrams/generated/fdai-workflow.en.svg",
      '../../../../diagrams/generated/fdai-workflow.manifest.json',
      '../../../../diagrams/generated/fdai-workflow.en.svg',
    ],
  ];

  for (const [filePath, url, manifest, image] of cases) {
    const embed = diagramEmbedForImage({ url, alt: 'Safe "flow"' }, filePath);
    assert.ok(embed);
    assert.match(embed, new RegExp(`manifest="${manifest.replaceAll(".", "\\.")}"`));
    assert.match(embed, new RegExp(`src="${image.replaceAll(".", "\\.")}"`));
    assert.match(embed, /alt="Safe &quot;flow&quot;"/);
  }
});

test("ordinary images are left unchanged", () => {
  assert.equal(
    diagramEmbedForImage(
      { url: "../images/screenshot.png", alt: "Screenshot" },
      "/repo/site/src/content/docs/guide.md",
    ),
    null,
  );
});
