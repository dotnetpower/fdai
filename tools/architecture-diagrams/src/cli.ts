import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { checkArtifacts, compileDiagram, writeArtifacts } from "./compiler.js";
import { parseDiagram } from "./model/validate.js";
import { buildViewerArtifact } from "./viewer/build.js";

const command = process.argv[2] ?? "validate";
const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const sourceDirectory = path.join(repositoryRoot, "docs/diagrams");
const siteViewerOutputDirectory = path.join(repositoryRoot, "site/public/diagrams");
const siteDiagramOutputDirectory = path.join(
  repositoryRoot,
  "site/public/diagrams/generated",
);
const docsOutputDirectory = path.join(repositoryRoot, "docs/diagrams/generated");

async function diagramPaths(): Promise<string[]> {
  return (await readdir(sourceDirectory))
    .filter((name) => name.endsWith(".diagram.yaml"))
    .sort()
    .map((name) => path.join(sourceDirectory, name));
}

async function run(): Promise<void> {
  const sources = await diagramPaths();
  if (!sources.length) throw new Error(`No diagram specifications found in ${sourceDirectory}`);
  const specs = await Promise.all(
    sources.map(async (sourcePath) => parseDiagram(await readFile(sourcePath, "utf8"))),
  );

  if (command === "validate") {
    console.log(`Validated ${specs.length} architecture diagram specification(s).`);
    return;
  }
  if (command !== "render" && command !== "check") {
    throw new Error(`Unknown command '${command}'. Use validate, render, or check.`);
  }

  const diagramArtifacts = (await Promise.all(specs.map(compileDiagram))).flat();
  const viewerArtifact = await buildViewerArtifact();
  if (command === "render") {
    await Promise.all([
      writeArtifacts(siteViewerOutputDirectory, [viewerArtifact]),
      writeArtifacts(siteDiagramOutputDirectory, diagramArtifacts),
      writeArtifacts(docsOutputDirectory, diagramArtifacts),
    ]);
    console.log(
      `Rendered 1 viewer artifact and ${diagramArtifacts.length} mirrored diagram artifact(s).`,
    );
    return;
  }

  const [staleViewer, staleSite, staleDocs] = await Promise.all([
    checkArtifacts(siteViewerOutputDirectory, [viewerArtifact]),
    checkArtifacts(siteDiagramOutputDirectory, diagramArtifacts),
    checkArtifacts(docsOutputDirectory, diagramArtifacts),
  ]);
  const stale = [
    ...staleViewer.map((name) => `site/public/diagrams/${name}`),
    ...staleSite.map((name) => `site/public/diagrams/generated/${name}`),
    ...staleDocs.map((name) => `docs/diagrams/generated/${name}`),
  ];
  if (stale.length) {
    throw new Error(`Generated diagram artifacts are stale: ${stale.join(", ")}`);
  }
  console.log(
    `Checked 1 viewer artifact and ${diagramArtifacts.length} mirrored diagram artifact(s).`,
  );
}

run().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
