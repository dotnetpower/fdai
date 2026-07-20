import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { buildViewerArtifact } from "./build.js";

const artifact = await buildViewerArtifact();
const outputDirectory = path.resolve(import.meta.dirname, "../../dist");
await mkdir(outputDirectory, { recursive: true });
await writeFile(path.join(outputDirectory, artifact.path), artifact.content);
console.log(`Built ${artifact.path}.`);
