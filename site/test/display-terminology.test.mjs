import assert from "node:assert/strict";
import test from "node:test";

import { remarkDisplayTerminology } from "../src/plugins/display-terminology.mjs";

function transform(tree, path, frontmatter) {
  const file = {
    path,
    history: [path],
    data: frontmatter ? { astro: { frontmatter } } : {},
  };
  remarkDisplayTerminology()(tree, file);
  return tree;
}

test("English prose uses display terminology", () => {
  const tree = {
    type: "root",
    children: [
      {
        type: "paragraph",
        children: [
          {
            type: "text",
            value:
              "The risk gate returns a HIL verdict when grounding finds a remediation finding outside the blast radius.",
          },
        ],
      },
    ],
  };

  transform(tree, "/repo/site/src/content/docs/concepts/safety.md");

  assert.equal(
    tree.children[0].children[0].value,
    "The safety check returns a decision requiring human approval when evidence check finds a detected issue requiring a fix outside the impact scope.",
  );
});

test("Korean pages use Korean display terminology", () => {
  const tree = {
    type: "root",
    children: [
      {
        type: "paragraph",
        children: [
          {
            type: "text",
            value:
              "risk gate가 HIL verdict와 remediation finding을 기록하고 Shadow 모드에서 Enforce 모드로 전환합니다.",
          },
        ],
      },
    ],
  };

  transform(tree, "/repo/site/src/content/docs/ko/concepts/safety.md");

  assert.equal(
    tree.children[0].children[0].value,
    "안전성 검토가 사람 승인이 필요한 결정과 수정이 필요한 문제를 기록하고 관찰 모드에서 적용 모드로 전환합니다.",
  );
});

test("contract syntax and machine values remain unchanged", () => {
  const tree = {
    type: "root",
    children: [
      { type: "inlineCode", value: "verdict=hil" },
      { type: "code", lang: "json", value: '{"verdict":"hil"}' },
      { type: "html", value: '<span data-verdict="hil">HIL</span>' },
      {
        type: "link",
        url: "/reference/verdict?mode=hil",
        children: [{ type: "text", value: "HIL verdict" }],
      },
      { type: "text", value: "HilChannel verdict_code" },
    ],
  };

  transform(tree, "/repo/site/src/content/docs/reference/contracts.md");

  assert.equal(tree.children[0].value, "verdict=hil");
  assert.equal(tree.children[1].value, '{"verdict":"hil"}');
  assert.equal(tree.children[2].value, '<span data-verdict="hil">HIL</span>');
  assert.equal(tree.children[3].url, "/reference/verdict?mode=hil");
  assert.equal(
    tree.children[3].children[0].value,
    "decision requiring human approval",
  );
  assert.equal(tree.children[4].value, "HilChannel verdict_code");
});

test("first mentions and common mode phrases do not duplicate terms", () => {
  const tree = {
    type: "root",
    children: [
      {
        type: "paragraph",
        children: [
          {
            type: "text",
            value:
              "Human-in-the-loop (HIL) starts in shadow mode. Mimir stewards promotion to enforce.",
          },
        ],
      },
    ],
  };

  transform(tree, "/repo/site/src/content/docs/concepts/modes.md");

  assert.equal(
    tree.children[0].children[0].value,
    "Human approval starts in observation mode. Mimir owns promotion to enforcement mode.",
  );
});

test("Starlight title and description metadata use display terminology", () => {
  const frontmatter = {
    title: "Shadow, then enforce",
    description: "Review a HIL decision with shadow coverage and live enforce validation.",
  };

  transform(
    { type: "root", children: [] },
    "/repo/site/src/content/docs/concepts/modes.md",
    frontmatter,
  );

  assert.deepEqual(frontmatter, {
    title: "Observe, then enable changes",
    description:
      "Review a decision requiring human approval with observation mode coverage and live enforcement validation.",
  });
});

test("Mermaid display labels change without renaming nodes or sequence messages", () => {
  const tree = {
    type: "root",
    children: [
      {
        type: "code",
        lang: "mermaid",
        value: [
          "flowchart LR",
          "  HIL[HIL verdict]",
          "  G{Risk gate} -->|hil| HIL",
        ].join("\n"),
      },
      {
        type: "code",
        lang: "mermaid",
        value: ["sequenceDiagram", "  F->>V: verdict = hil"].join("\n"),
      },
    ],
  };

  transform(tree, "/repo/site/src/content/docs/concepts/approval.md");

  assert.equal(
    tree.children[0].value,
    [
      "flowchart LR",
      "  HIL[decision requiring human approval]",
      "  G{Safety check} -->|human approval| HIL",
    ].join("\n"),
  );
  assert.equal(
    tree.children[1].value,
    ["sequenceDiagram", "  F->>V: verdict = hil"].join("\n"),
  );
});
