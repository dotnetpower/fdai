import { build } from "esbuild";
import { fileURLToPath } from "node:url";

import type { DiagramArtifact } from "../compiler.js";

export async function buildViewerArtifact(): Promise<DiagramArtifact> {
  const result = await build({
    entryPoints: [fileURLToPath(new URL("./architecture-diagram.ts", import.meta.url))],
    bundle: true,
    format: "esm",
    minify: true,
    target: "es2022",
    write: false,
    legalComments: "none",
  });
  const output = result.outputFiles[0];
  if (!output) throw new Error("esbuild did not produce the diagram viewer bundle");
  return {
    path: "architecture-diagram.js",
    content: Buffer.from(output.contents),
  };
}
