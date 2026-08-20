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
  koreanSource?: string;
  idPrefix?: string;
  blocks: number;
  reused: Record<number, string>;
}

export const PUBLIC_MIGRATION: PublicMigrationEntry[] = [
  { source: "docs/user-guide/get-started.md", blocks: 1, reused: {} },
  { source: "docs/roadmap/README.md", blocks: 1, reused: { 1: "fdai-delivery-roadmap" } },
  {
    source: "docs/user-guide/architecture.md",
    blocks: 3,
    reused: {
      1: "fdai-system-overview",
      2: "fdai-agent-driven-runtime",
      3: "fdai-reference-architecture",
    },
  },
  { source: "docs/user-guide/concepts/deterministic-first.md", blocks: 1, reused: {} },
  { source: "docs/user-guide/concepts/risk-tiers.md", blocks: 1, reused: {} },
  { source: "docs/user-guide/concepts/shadow-then-enforce.md", blocks: 1, reused: {} },
  { source: "docs/user-guide/concepts/ontology-driven-automation.md", blocks: 2, reused: {} },
  { source: "docs/roadmap/agents/agent-workflows.md", blocks: 12, reused: {} },
  {
    source: "docs/user-guide/concepts/agents-and-self-healing.md",
    blocks: 2,
    reused: { 1: "fdai-agent-driven-runtime" },
  },
  { source: "docs/user-guide/concepts/ownership-and-handover.md", blocks: 1, reused: {} },
  { source: "docs/roadmap/deployment/deploy-and-onboard.md", blocks: 1, reused: {} },
  { source: "docs/roadmap/interfaces/operator-console.md", blocks: 1, reused: {} },
  { source: "docs/user-guide/concepts/approvals-and-channels.md", blocks: 1, reused: {} },
  { source: "docs/roadmap/interfaces/channels-and-notifications.md", blocks: 1, reused: {} },
  { source: "docs/roadmap/operations/operating-and-verification.md", blocks: 1, reused: {} },
  {
    source: "docs/roadmap/decisioning/escalation-and-standing-authority.md",
    blocks: 2,
    reused: {},
  },
  {
    source: "docs/roadmap/agents/README.md",
    idPrefix: "agent-waves",
    blocks: 1,
    reused: {},
  },
  {
    source: "docs/user-guide/deck/ref-ontology-context-vs-rag.md",
    koreanSource: "docs/user-guide/deck/ref-ontology-context-vs-rag-ko.md",
    idPrefix: "ontology-context-rag",
    blocks: 2,
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

function koreanPathFor(entry: PublicMigrationEntry): string {
  return entry.koreanSource ?? entry.source.replace(/\.md$/u, "-ko.md");
}

function generatedId(source: string, blockIndex: number, idPrefix?: string): string {
  const basename = (idPrefix ?? path.posix.basename(source, ".md"))
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
  return `fdai-${basename}-${String(blockIndex).padStart(2, "0")}`;
}

function diagramId(entry: PublicMigrationEntry, blockIndex: number): string {
  return entry.reused[blockIndex] ?? generatedId(entry.source, blockIndex, entry.idPrefix);
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

function fallbackAssetPath(sourcePath: string, id: string, locale: Locale): string {
  return path.posix.relative(
    path.posix.dirname(sourcePath),
    `docs/diagrams/generated/${id}.${locale}.svg`,
  );
}

async function migrationPlan(root: string): Promise<MigrationPlan> {
  const pairs: MigrationPair[] = [];
  const specs: DiagramSpec[] = [];
  const replacements = new Map<string, string[]>();
  let totalBlocks = 0;
  let reusedBlocks = 0;

  for (const entry of PUBLIC_MIGRATION) {
    const englishPath = entry.source;
    const koreanPath = koreanPathFor(entry);
    const [english, korean] = await Promise.all([
      readFile(path.join(root, englishPath), "utf8"),
      readFile(path.join(root, koreanPath), "utf8"),
    ]);
    const englishBlocks = extractMermaidBlocks(english);
    const koreanBlocks = extractMermaidBlocks(korean);
    if (englishBlocks.length !== koreanBlocks.length) {
      throw new Error(`${englishPath} has ${englishBlocks.length} English and ${koreanBlocks.length} Korean Mermaid blocks`);
    }
    if (englishBlocks.length !== entry.blocks) {
      throw new Error(`${englishPath} has ${englishBlocks.length} Mermaid blocks; expected ${entry.blocks}`);
    }
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
            generatedId(englishPath, blockIndex, entry.idPrefix),
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

async function validateCompiledSpecs(specs: DiagramSpec[]): Promise<void> {
  await Promise.all(
    specs.map(async (spec) => {
      try {
        await compileDiagram(spec);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`${spec.id} (${spec.locales.en.title}): ${message}`);
      }
    }),
  );
}

export async function validatePublicMigration(root: string): Promise<MigrationPlan> {
  const plan = await migrationPlan(root);
  await validateCompiledSpecs(plan.specs);
  if (plan.totalBlocks !== 35 || plan.reusedBlocks !== 5 || plan.specs.length !== 30) {
    throw new Error(
      `Public migration inventory drifted: total=${plan.totalBlocks} reused=${plan.reusedBlocks} generated=${plan.specs.length}`,
    );
  }
  return plan;
}

export async function validatePublishedMigration(root: string): Promise<MigrationPlan> {
  const specs: DiagramSpec[] = [];
  const seenGenerated = new Set<string>();
  let totalBlocks = 0;
  let reusedBlocks = 0;
  for (const entry of PUBLIC_MIGRATION) {
    const englishPath = entry.source;
    const koreanPath = koreanPathFor(entry);
    const [english, korean] = await Promise.all([
      readFile(path.join(root, englishPath), "utf8"),
      readFile(path.join(root, koreanPath), "utf8"),
    ]);
    if (extractMermaidBlocks(english).length || extractMermaidBlocks(korean).length) {
      throw new Error(`${englishPath} is partially migrated`);
    }
    for (let blockIndex = 1; blockIndex <= entry.blocks; blockIndex += 1) {
      const id = diagramId(entry, blockIndex);
      const englishAsset = fallbackAssetPath(englishPath, id, "en");
      const koreanAsset = fallbackAssetPath(koreanPath, id, "ko");
      if (!english.includes(`](${englishAsset})`) || !korean.includes(`](${koreanAsset})`)) {
        throw new Error(`${englishPath} is missing the localized fallback for ${id}`);
      }
      if (entry.reused[blockIndex]) reusedBlocks += 1;
      else if (!seenGenerated.has(id)) {
        specs.push(await loadDiagram(root, id));
        seenGenerated.add(id);
      }
      totalBlocks += 1;
    }
  }
  await validateCompiledSpecs(specs);
  if (totalBlocks !== 35 || reusedBlocks !== 5 || specs.length !== 30) {
    throw new Error(
      `Published migration inventory drifted: total=${totalBlocks} reused=${reusedBlocks} generated=${specs.length}`,
    );
  }
  return { pairs: [], specs, replacements: new Map(), totalBlocks, reusedBlocks };
}

export async function checkPublicMigration(root: string): Promise<MigrationPlan> {
  let mermaidCount = 0;
  for (const entry of PUBLIC_MIGRATION) {
    const [english, korean] = await Promise.all([
      readFile(path.join(root, entry.source), "utf8"),
      readFile(path.join(root, koreanPathFor(entry)), "utf8"),
    ]);
    mermaidCount += extractMermaidBlocks(english).length + extractMermaidBlocks(korean).length;
  }
  if (mermaidCount === 70) return validatePublicMigration(root);
  if (mermaidCount === 0) return validatePublishedMigration(root);
  throw new Error(`Public diagram migration is incomplete: ${mermaidCount} Mermaid blocks remain`);
}

export async function writePublicMigration(root: string): Promise<MigrationPlan> {
  for (const entry of PUBLIC_MIGRATION) {
    const englishPath = entry.source;
    const koreanPath = koreanPathFor(entry);
    const [english, korean] = await Promise.all([
      readFile(path.join(root, englishPath), "utf8"),
      readFile(path.join(root, koreanPath), "utf8"),
    ]);
    const englishBlocks = extractMermaidBlocks(english);
    const koreanBlocks = extractMermaidBlocks(korean);
    if (!englishBlocks.length && !koreanBlocks.length) continue;
    if (englishBlocks.length !== entry.blocks || koreanBlocks.length !== entry.blocks) {
      throw new Error(
        `${englishPath} is partially migrated: en=${englishBlocks.length} ko=${koreanBlocks.length} expected=${entry.blocks}`,
      );
    }
    const specs: DiagramSpec[] = [];
    const englishReplacements: string[] = [];
    const koreanReplacements: string[] = [];
    for (let offset = 0; offset < entry.blocks; offset += 1) {
      const blockIndex = offset + 1;
      const reusedId = entry.reused[blockIndex];
      const spec = reusedId
        ? await loadDiagram(root, reusedId)
        : convertMermaidPair(
            generatedId(englishPath, blockIndex, entry.idPrefix),
            englishBlocks[offset]!,
            koreanBlocks[offset]!,
          );
      if (!reusedId) specs.push(spec);
      englishReplacements.push(
        fallbackMarkdown(englishPath, spec.id, "en", spec.locales.en.alt),
      );
      koreanReplacements.push(
        fallbackMarkdown(koreanPath, spec.id, "ko", spec.locales.ko.alt),
      );
    }
    await validateCompiledSpecs(specs);
    await Promise.all(
      specs.map((spec) =>
        writeFile(diagramSourcePath(root, spec.id), stringify(spec, { lineWidth: 120 })),
      ),
    );
    await Promise.all([
      writeFile(path.join(root, englishPath), replaceMermaidBlocks(english, englishReplacements)),
      writeFile(path.join(root, koreanPath), replaceMermaidBlocks(korean, koreanReplacements)),
    ]);
  }
  return checkPublicMigration(root);
}
