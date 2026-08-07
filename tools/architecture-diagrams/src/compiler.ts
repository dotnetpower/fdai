import { Resvg } from "@resvg/resvg-js";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { layoutDiagram } from "./layout/elk.js";
import { assertLayoutIntegrity } from "./layout/integrity.js";
import type { DiagramSpec, Locale } from "./model/types.js";
import { renderSvg } from "./render/svg.js";

const diagramFontPath = fileURLToPath(
  new URL("../assets/fonts/noto-sans-kr-diagrams.ttf", import.meta.url),
);

export function resolveCssFallbacks(source: string): string {
  return source.replace(
    /var\(--[a-z0-9-]+,\s*([^)]+)\)/gi,
    (_match, fallback: string) => fallback.trim(),
  );
}

export function canonicalTextArtifact(source: string): Buffer {
  return Buffer.from(`${source.replace(/\n+$/u, "")}\n`);
}

export interface DiagramArtifact {
  path: string;
  content: Buffer;
}

export async function compileDiagram(spec: DiagramSpec): Promise<DiagramArtifact[]> {
  const layout = await layoutDiagram(spec);
  assertLayoutIntegrity(spec, layout);
  const artifacts: DiagramArtifact[] = [];
  const formats = new Set(spec.formats ?? ["svg", "png"]);
  for (const locale of ["en", "ko"] satisfies Locale[]) {
    const svg = await renderSvg(spec, layout, locale);
    if (formats.has("svg")) {
      artifacts.push({
        path: `${spec.id}.${locale}.svg`,
        content: canonicalTextArtifact(svg),
      });
    }
    if (formats.has("png")) {
      artifacts.push({
        path: `${spec.id}.${locale}.png`,
        content: Buffer.from(
          new Resvg(resolveCssFallbacks(svg), {
            background: "#f7f9fc",
            fitTo: { mode: "width", value: 1800 },
            font: {
              fontFiles: [diagramFontPath],
              loadSystemFonts: false,
              defaultFontFamily: "Noto Sans KR",
            },
            languages: [locale],
            shapeRendering: 2,
            textRendering: 1,
          })
            .render()
            .asPng(),
        ),
      });
    }
  }
  const manifest = {
    id: spec.id,
    version: spec.version,
    updated: spec.updated ?? null,
    locales: spec.locales,
    assets: {
      en: {
        svg: `${spec.id}.en.svg`,
        ...(formats.has("png") ? { png: `${spec.id}.en.png` } : {}),
      },
      ko: {
        svg: `${spec.id}.ko.svg`,
        ...(formats.has("png") ? { png: `${spec.id}.ko.png` } : {}),
      },
    },
    nodes: spec.nodes.map((node) => ({
      id: node.id,
      kind: node.kind,
      ...(node.shape ? { shape: node.shape } : {}),
      ...(node.tone ? { tone: node.tone } : {}),
      ...(node.badge ? { badge: node.badge } : {}),
      label: node.label,
      description: node.description ?? node.label,
      ...(node.content ? { content: node.content } : {}),
    })),
    edges: spec.edges.map((edge) => ({
      id: edge.id,
      from: edge.from.split(":", 1)[0],
      to: edge.to.split(":", 1)[0],
      kind: edge.kind,
      label: edge.label ?? null,
      ...(edge.step ? { step: edge.step } : {}),
    })),
  };
  artifacts.push({
    path: `${spec.id}.manifest.json`,
    content: Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`),
  });
  return artifacts;
}

export async function writeArtifacts(
  outputDirectory: string,
  artifacts: DiagramArtifact[],
): Promise<void> {
  await mkdir(outputDirectory, { recursive: true });
  await Promise.all(
    artifacts.map((artifact) =>
      writeFile(path.join(outputDirectory, artifact.path), artifact.content),
    ),
  );
}

export async function checkArtifacts(
  outputDirectory: string,
  artifacts: DiagramArtifact[],
): Promise<string[]> {
  const stale: string[] = [];
  for (const artifact of artifacts) {
    try {
      const existing = await readFile(path.join(outputDirectory, artifact.path));
      if (!existing.equals(artifact.content)) stale.push(artifact.path);
    } catch {
      stale.push(artifact.path);
    }
  }
  return stale;
}
