import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { stringify } from "yaml";

import { compileDiagram } from "../compiler.js";
import { parseDiagram } from "../model/validate.js";
import type { DiagramSpec, Locale } from "../model/types.js";
import {
  convertMermaidPair,
  extractMermaidBlocks,
  replaceMermaidBlocks,
  type MermaidBlock,
} from "./mermaid.js";

export interface PublicMigrationEntry {
  source: string;
  reused: Record<number, string>;
}

export const PUBLIC_MIGRATION: PublicMigrationEntry[] = [
  { source: "docs/user-guide/get-started.md", reused: {} },
  { source: "docs/roadmap/README.md", reused: { 1: "fdai-delivery-roadmap" } },
  {
    source: "docs/user-guide/architecture.md",
    reused: {
      1: "fdai-system-overview",
      2: "fdai-agent-driven-runtime",
      3: "fdai-reference-architecture",
    },
  },
  { source: "docs/user-guide/concepts/deterministic-first.md", reused: {} },
  { source: "docs/user-guide/concepts/risk-tiers.md", reused: {} },
  { source: "docs/user-guide/concepts/shadow-then-enforce.md", reused: {} },
  { source: "docs/user-guide/concepts/ontology-driven-automation.md", reused: {} },
  { source: "docs/roadmap/agents/agent-workflows.md", reused: {} },
  {
    source: "docs/user-guide/concepts/agents-and-self-healing.md",
    reused: { 1: "fdai-agent-driven-runtime" },
  },
  { source: "docs/user-guide/concepts/ownership-and-handover.md", reused: {} },
  { source: "docs/roadmap/deployment/deploy-and-onboard.md", reused: {} },
  { source: "docs/roadmap/interfaces/operator-console.md", reused: {} },
  { source: "docs/user-guide/concepts/approvals-and-channels.md", reused: {} },
  { source: "docs/roadmap/interfaces/channels-and-notifications.md", reused: {} },
  { source: "docs/roadmap/operations/operating-and-verification.md", reused: {} },
  {
    source: "docs/roadmap/decisioning/escalation-and-standing-authority.md",
    reused: {},
  },
];

interface MigrationPair {
  entry: PublicMigrationEntry;
  englishPath: string;
  koreanPath: string;
  english: string;
  korean: string;
  englishBlocks: MermaidBlock[];
  koreanBlocks: MermaidBlock[];
}

interface MigrationPlan {
  pairs: MigrationPair[];
  specs: DiagramSpec[];
  replacements: Map<string, string[]>;
  totalBlocks: number;
  reusedBlocks: number;
}

function koreanPathFor(englishPath: string): string {
  return englishPath.replace(/\.md$/u, "-ko.md");
}

function generatedId(source: string, blockIndex: number): string {
  const basename = path.posix.basename(source, ".md")
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
  return `fdai-${basename}-${String(blockIndex).padStart(2, "0")}`;
}

function diagramSourcePath(root: string, id: string): string {
  return path.join(root, "docs", "diagrams", `${id}.diagram.yaml`);
}

async function loadDiagram(root: string, id: string): Promise<DiagramSpec> {
  return parseDiagram(await readFile(diagramSourcePath(root, id), "utf8"));
}

function fallbackMarkdown(
  sourcePath: string,
  id: string,
  locale: Locale,
  alt: string,
): string {
  const target = path.posix.relative(
    path.posix.dirname(sourcePath),
    `docs/diagrams/generated/${id}.${locale}.svg`,
  );
  return `![${alt.replaceAll("]", "\\]")}](${target})`;
}

async function migrationPlan(root: string): Promise<MigrationPlan> {
  const pairs: MigrationPair[] = [];
  const specs: DiagramSpec[] = [];
  const replacements = new Map<string, string[]>();
  let totalBlocks = 0;
  let reusedBlocks = 0;

  for (const entry of PUBLIC_MIGRATION) {
    const englishPath = entry.source;
    const koreanPath = koreanPathFor(englishPath);
    const [english, korean] = await Promise.all([
      readFile(path.join(root, englishPath), "utf8"),
      readFile(path.join(root, koreanPath), "utf8"),
    ]);
    const englishBlocks = extractMermaidBlocks(english);
    const koreanBlocks = extractMermaidBlocks(korean);
    if (englishBlocks.length !== koreanBlocks.length) {
      throw new Error(`${englishPath} has ${englishBlocks.length} English and ${koreanBlocks.length} Korean Mermaid blocks`);
    }
    if (!englishBlocks.length) throw new Error(`${englishPath} has no Mermaid blocks to migrate`);
    const pair = {
      entry,
      englishPath,
      koreanPath,
      english,
      korean,
      englishBlocks,
      koreanBlocks,
    };
    pairs.push(pair);
    const englishReplacements: string[] = [];
    const koreanReplacements: string[] = [];
    for (let offset = 0; offset < englishBlocks.length; offset += 1) {
      const blockIndex = offset + 1;
      const reusedId = entry.reused[blockIndex];
      const spec = reusedId
        ? await loadDiagram(root, reusedId)
        : convertMermaidPair(
            generatedId(englishPath, blockIndex),
            englishBlocks[offset]!,
            koreanBlocks[offset]!,
          );
      if (reusedId) reusedBlocks += 1;
      else specs.push(spec);
      englishReplacements.push(
        fallbackMarkdown(englishPath, spec.id, "en", spec.locales.en.alt),
      );
      koreanReplacements.push(
        fallbackMarkdown(koreanPath, spec.id, "ko", spec.locales.ko.alt),
      );
      totalBlocks += 1;
    }
    replacements.set(englishPath, englishReplacements);
    replacements.set(koreanPath, koreanReplacements);
  }
  return { pairs, specs, replacements, totalBlocks, reusedBlocks };
}

export async function validatePublicMigration(root: string): Promise<MigrationPlan> {
  const plan = await migrationPlan(root);
  await Promise.all(
    plan.specs.map(async (spec) => {
      try {
        await compileDiagram(spec);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`${spec.id} (${spec.locales.en.title}): ${message}`);
      }
    }),
  );
  if (plan.totalBlocks !== 32 || plan.reusedBlocks !== 5 || plan.specs.length !== 27) {
    throw new Error(
      `Public migration inventory drifted: total=${plan.totalBlocks} reused=${plan.reusedBlocks} generated=${plan.specs.length}`,
    );
  }
  return plan;
}

export async function writePublicMigration(root: string): Promise<MigrationPlan> {
  const plan = await validatePublicMigration(root);
  await Promise.all(
    plan.specs.map((spec) =>
      writeFile(diagramSourcePath(root, spec.id), stringify(spec, { lineWidth: 120 })),
    ),
  );
  for (const pair of plan.pairs) {
    await Promise.all([
      writeFile(
        path.join(root, pair.englishPath),
        replaceMermaidBlocks(pair.english, plan.replacements.get(pair.englishPath)!),
      ),
      writeFile(
        path.join(root, pair.koreanPath),
        replaceMermaidBlocks(pair.korean, plan.replacements.get(pair.koreanPath)!),
      ),
    ]);
  }
  return plan;
}
