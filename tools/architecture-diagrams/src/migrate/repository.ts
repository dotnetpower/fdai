import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { stringify } from "yaml";

import { compileDiagram } from "../compiler.js";
import { parseDiagram } from "../model/validate.js";
import type { DiagramSpec } from "../model/types.js";
import {
  convertMermaidPair,
  extractMermaidBlocks,
  replaceMermaidBlocks,
  type MermaidBlock,
} from "./mermaid.js";

const EXPECTED_DIAGRAMS = 74;
const OPERATIONAL_KNOWLEDGE_PLAN = "docs/internals/operational-knowledge-query-hardening-plan.md";

interface MigrationDocument {
  englishPath: string;
  koreanPath?: string;
  english: string;
  korean?: string;
  englishBlocks: MermaidBlock[];
  koreanBlocks: MermaidBlock[];
}

export interface RepositoryMigrationPlan {
  documents: MigrationDocument[];
  specs: DiagramSpec[];
  totalBlocks: number;
  deferredBlocks: number;
}

async function markdownFiles(root: string, directory: string): Promise<string[]> {
  const absolute = path.join(root, directory);
  const entries = await readdir(absolute, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const relative = path.posix.join(directory, entry.name);
    if (entry.isDirectory()) return markdownFiles(root, relative);
    return entry.isFile() && entry.name.endsWith(".md") ? [relative] : [];
  }));
  return nested.flat().sort();
}

function koreanPathFor(englishPath: string): string {
  return englishPath.replace(/\.md$/u, "-ko.md");
}

function generatedId(source: string, blockIndex: number): string {
  const stem = source
    .replace(/^docs\//u, "")
    .replace(/\.md$/u, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
  return `fdai-${stem}-${String(blockIndex).padStart(2, "0")}`;
}

function fallbackMarkdown(source: string, spec: DiagramSpec, locale: "en" | "ko"): string {
  const target = path.posix.relative(
    path.posix.dirname(source),
    `docs/diagrams/generated/${spec.id}.${locale}.svg`,
  );
  return `![${spec.locales[locale].alt.replaceAll("]", "\\]")}](${target})`;
}

async function discoverDocuments(root: string): Promise<{
  active: MigrationDocument[];
  deferredBlocks: number;
}> {
  const files = await markdownFiles(root, "docs/roadmap");
  const fileSet = new Set(files);
  const active: MigrationDocument[] = [];
  let deferredBlocks = 0;
  for (const englishPath of files) {
    if (englishPath.endsWith("-ko.md")) continue;
    const koreanPath = koreanPathFor(englishPath);
    if (!fileSet.has(koreanPath)) continue;
    const [english, korean] = await Promise.all([
      readFile(path.join(root, englishPath), "utf8"),
      readFile(path.join(root, koreanPath), "utf8"),
    ]);
    const englishBlocks = extractMermaidBlocks(english);
    const koreanBlocks = extractMermaidBlocks(korean);
    if (!englishBlocks.length && !koreanBlocks.length) continue;
    if (englishBlocks.length !== koreanBlocks.length) {
      throw new Error(`${englishPath} has ${englishBlocks.length} English and ${koreanBlocks.length} Korean Mermaid blocks`);
    }
    active.push({ englishPath, koreanPath, english, korean, englishBlocks, koreanBlocks });
  }

  const standalonePath = OPERATIONAL_KNOWLEDGE_PLAN;
  const standalone = await readFile(path.join(root, standalonePath), "utf8");
  const standaloneBlocks = extractMermaidBlocks(standalone);
  if (standaloneBlocks.length) {
    active.push({
      englishPath: standalonePath,
      english: standalone,
      englishBlocks: standaloneBlocks,
      koreanBlocks: standaloneBlocks,
    });
  }
  return { active, deferredBlocks };
}

async function compileSpecs(specs: DiagramSpec[]): Promise<void> {
  for (const spec of specs) {
    try {
      await compileDiagram(spec);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`${spec.id} (${spec.locales.en.title}): ${message}`);
    }
  }
}

async function migrationPlan(root: string): Promise<RepositoryMigrationPlan> {
  const { active, deferredBlocks } = await discoverDocuments(root);
  const specs: DiagramSpec[] = [];
  for (const document of active) {
    for (let offset = 0; offset < document.englishBlocks.length; offset += 1) {
      specs.push(convertMermaidPair(
        generatedId(document.englishPath, offset + 1),
        document.englishBlocks[offset]!,
        document.koreanBlocks[offset]!,
      ));
    }
  }
  await compileSpecs(specs);
  return { documents: active, specs, totalBlocks: specs.length, deferredBlocks };
}

async function publishedSpecs(root: string): Promise<DiagramSpec[]> {
  const files = [
    ...await markdownFiles(root, "docs/roadmap"),
    OPERATIONAL_KNOWLEDGE_PLAN,
  ];
  const ids = new Set<string>();
  const expression = /diagrams\/generated\/(fdai-(?:roadmap|operational-knowledge-query-hardening-plan)-[^)]+?)\.(?:en|ko)\.svg/gu;
  for (const source of files) {
    const markdown = await readFile(path.join(root, source), "utf8");
    for (const match of markdown.matchAll(expression)) ids.add(match[1]!);
  }
  const specs = await Promise.all([...ids].sort().map(async (id) =>
    parseDiagram(await readFile(path.join(root, "docs/diagrams", `${id}.diagram.yaml`), "utf8")),
  ));
  await compileSpecs(specs);
  return specs;
}

export async function checkRepositoryMigration(root: string): Promise<RepositoryMigrationPlan> {
  const active = await migrationPlan(root);
  const published = await publishedSpecs(root);
  const specs = [...published, ...active.specs];
  if (specs.length !== EXPECTED_DIAGRAMS) {
    throw new Error(
      `Repository migration inventory drifted: published=${published.length} pending=${active.specs.length} expected=${EXPECTED_DIAGRAMS}`,
    );
  }
  if (active.documents.length) {
    const remaining = active.documents.reduce(
      (total, document) => total + document.englishBlocks.length + document.koreanBlocks.length,
      0,
    );
    throw new Error(`Repository diagram migration is incomplete: ${remaining} Mermaid block(s) remain`);
  }
  return { ...active, specs, totalBlocks: specs.length };
}

export async function writeRepositoryMigration(root: string): Promise<RepositoryMigrationPlan> {
  const plan = await migrationPlan(root);
  let specOffset = 0;
  for (const document of plan.documents) {
    const documentSpecs = plan.specs.slice(specOffset, specOffset + document.englishBlocks.length);
    specOffset += documentSpecs.length;
    await writeFile(
      path.join(root, document.englishPath),
      replaceMermaidBlocks(
        document.english,
        documentSpecs.map((spec) => fallbackMarkdown(document.englishPath, spec, "en")),
      ),
    );
    if (document.koreanPath && document.korean) {
      await writeFile(
        path.join(root, document.koreanPath),
        replaceMermaidBlocks(
          document.korean,
          documentSpecs.map((spec) => fallbackMarkdown(document.koreanPath!, spec, "ko")),
        ),
      );
    }
  }
  await Promise.all(plan.specs.map((spec) => writeFile(
    path.join(root, "docs/diagrams", `${spec.id}.diagram.yaml`),
    stringify(spec, { lineWidth: 120 }),
  )));
  return checkRepositoryMigration(root);
}
