import assert from "node:assert/strict";
import test from "node:test";

import {
  convertMermaidPair,
  extractMermaidBlocks,
  parseFlowchart,
  parseSequence,
  replaceMermaidBlocks,
} from "../src/migrate/mermaid.js";

test("flowchart migration preserves groups, decisions, and localized edges", () => {
  const en = {
    heading: "Approval flow",
    source: `flowchart LR
subgraph CORE[Core]
  A[Request] -->|approval required| B{Approved?}
end
B -. evidence .-> C[(Audit)]`,
  };
  const ko = {
    heading: "승인 흐름",
    source: `flowchart LR
subgraph CORE[코어]
  A[요청] -->|사람 승인 필요| B{승인됨?}
end
B -. 근거 .-> C[(감사)]`,
  };
  const parsed = parseFlowchart(en.source);
  assert.equal(parsed.groups.length, 1);
  assert.equal(parsed.nodes.find((node) => node.id === "B")?.kind, "decision");
  const spec = convertMermaidPair("approval-flow", en, ko);
  assert.equal(spec.nodes.find((node) => node.id === "a")?.label.ko, "요청");
  assert.equal(spec.edges[0]?.kind, "approval");
  assert.equal(spec.edges[1]?.kind, "dependency");
});

test("flowchart migration expands simple chained edges", () => {
  const parsed = parseFlowchart(`flowchart LR
A[Authorize] --> B[Plan] --> C[Execute] --> D[Audit]`);
  assert.deepEqual(
    parsed.edges.map((edge) => `${edge.from}->${edge.to}`),
    ["A->B", "B->C", "C->D"],
  );
});

test("flowchart migration emits repeated fan-out labels once", () => {
  const en = {
    heading: "Tools",
    source: `flowchart LR
A[Narrator] -. tool call .-> B[Rules]
A -. tool call .-> C[Inventory]`,
  };
  const ko = {
    heading: "도구",
    source: `flowchart LR
A[내레이터] -. 도구 호출 .-> B[규칙]
A -. 도구 호출 .-> C[인벤토리]`,
  };
  const spec = convertMermaidPair("tool-fan-out", en, ko);
  assert.equal(spec.edges.filter((edge) => edge.label).length, 1);
  assert.equal(spec.edges[0]?.label?.ko, "도구 호출");
});

test("flowchart migration moves dense decision conditions into targets", () => {
  const en = {
    heading: "Decision",
    source: `flowchart LR
D{Eligible?}
D -->|yes| A[Execute]
D -->|review| B[Hold]
D -->|no| C[Deny]`,
  };
  const ko = {
    heading: "결정",
    source: `flowchart LR
D{적격?}
D -->|예| A[실행]
D -->|검토| B[보류]
D -->|아니요| C[차단]`,
  };
  const spec = convertMermaidPair("decision-fan-out", en, ko);
  assert.equal(spec.edges.filter((edge) => edge.label).length, 0);
  assert.deepEqual(spec.nodes.find((node) => node.id === "b")?.description, {
    en: "When: review",
    ko: "조건: 검토",
  });
});

test("flowchart migration keeps subgraph endpoints as groups", () => {
  const parsed = parseFlowchart(`flowchart LR
subgraph OBSERVE[Observe]
A[Signal]
end
subgraph DECIDE[Decide]
B[Decision]
end
OBSERVE --> DECIDE`);
  assert.deepEqual(parsed.groups.map((group) => group.id), ["OBSERVE", "DECIDE"]);
  assert.deepEqual(parsed.nodes.map((node) => node.id), ["A", "B"]);
  assert.deepEqual(parsed.edges.map((edge) => `${edge.from}->${edge.to}`), [
    "OBSERVE->DECIDE",
  ]);
});

test("sequence migration turns ordered messages and controls into typed steps", () => {
  const enSource = `sequenceDiagram
participant H as Heimdall
participant F as Forseti
H->>F: finding
alt review required
F-->>H: hold
end`;
  const koSource = `sequenceDiagram
participant H as Heimdall
participant F as Forseti
H->>F: 발견
alt 검토 필요
F-->>H: 보류
end`;
  assert.equal(parseSequence(enSource).steps.length, 2);
  const spec = convertMermaidPair(
    "sequence-flow",
    { heading: "Sequence", source: enSource },
    { heading: "순서", source: koSource },
  );
  assert.equal(spec.kind, "sequence");
  assert.equal(spec.nodes[1]?.description?.ko, "alt: 검토 필요 / 보류");
  assert.equal(spec.edges[0]?.kind, "sequence");
});

test("Markdown extraction and replacement are count checked", () => {
  const markdown = `# Guide
## Flow
\`\`\`mermaid
flowchart LR
A --> B
\`\`\`
`;
  assert.equal(extractMermaidBlocks(markdown)[0]?.heading, "Flow");
  assert.match(replaceMermaidBlocks(markdown, ["![Flow](diagram.svg)"]), /diagram\.svg/);
  assert.throws(() => replaceMermaidBlocks(markdown, []), /Missing Mermaid replacement/);
});
