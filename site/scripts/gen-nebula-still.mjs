// gen-nebula-still.mjs - rasterize a still frame of the site nebula.
//
// The landing backdrop is a procedural WebGL shader
// (src/components/NebulaBackground.astro), so there is no image asset to
// reuse in slide decks or covers. This script extracts the VERT/FRAG
// sources straight from that component (single source of truth), renders
// one deterministic frame in headless Chromium, and writes a PNG.
//
// Default output: docs/user-guide/deck/nebula-2000x1125.png (16:9 slide
// background). Run `npm run gen-nebula` to regenerate.
//
// Overrides: --width= --height= --time= --intensity= --out=
//
// Playwright lives in the console workspace, so it is resolved from
// console/package.json rather than duplicated as a site dependency.

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import fs from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const siteDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(siteDir, "..");

const require = createRequire(path.join(repoRoot, "console", "package.json"));
const { chromium } = require("playwright");

function arg(name, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit === undefined ? fallback : hit.slice(name.length + 3);
}

const WIDTH = Number(arg("width", 2000));
const HEIGHT = Number(arg("height", 1125));
// Fixed shader clock: cloud drift and star twinkle are functions of
// u_time, so pinning it keeps the output reproducible.
const TIME = Number(arg("time", 8));
const INTENSITY = Number(arg("intensity", 1));
const OUT = path.resolve(
  repoRoot,
  arg("out", path.join("docs", "user-guide", "deck", `nebula-${WIDTH}x${HEIGHT}.png`)),
);

// ---- Pull the shader sources out of the Astro component -------------
const componentPath = path.join(siteDir, "src", "components", "NebulaBackground.astro");
const component = await fs.readFile(componentPath, "utf8");

function extractShader(name) {
  const marker = `const ${name} = \``;
  const start = component.indexOf(marker);
  if (start < 0) throw new Error(`${name} not found in ${componentPath}`);
  const from = start + marker.length;
  const end = component.indexOf("`", from);
  if (end < 0) throw new Error(`unterminated ${name} literal in ${componentPath}`);
  return component.slice(from, end);
}

const VERT = extractShader("VERT");
const FRAG = extractShader("FRAG");

// ---- Render one frame in headless Chromium (SwiftShader WebGL) ------
const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>html,body{margin:0;background:#05070f}</style></head>
<body><canvas id="c" width="${WIDTH}" height="${HEIGHT}"></canvas></body></html>`;

const browser = await chromium.launch({
  args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
});
try {
  const tab = await browser.newPage({ viewport: { width: 800, height: 600 } });
  await tab.setContent(html);

  const dataUrl = await tab.evaluate(
    ({ vert, frag, time, intensity }) => {
      const canvas = document.getElementById("c");
      const gl = canvas.getContext("webgl", {
        antialias: false,
        alpha: false,
        preserveDrawingBuffer: true,
      });
      if (!gl) throw new Error("WebGL unavailable in the headless browser");

      const compile = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
          throw new Error(`shader compile failed: ${gl.getShaderInfoLog(s)}`);
        }
        return s;
      };

      const prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, vert));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, frag));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        throw new Error(`program link failed: ${gl.getProgramInfoLog(prog)}`);
      }
      gl.useProgram(prog);

      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, "a");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(gl.getUniformLocation(prog, "u_res"), canvas.width, canvas.height);
      gl.uniform1f(gl.getUniformLocation(prog, "u_time"), time);
      gl.uniform1f(gl.getUniformLocation(prog, "u_intensity"), intensity);
      // Scroll offset 0 = the hero framing (core bloom at full strength).
      gl.uniform1f(gl.getUniformLocation(prog, "u_scroll"), 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.finish();

      return canvas.toDataURL("image/png");
    },
    { vert: VERT, frag: FRAG, time: TIME, intensity: INTENSITY },
  );

  await fs.mkdir(path.dirname(OUT), { recursive: true });
  // The canvas dump is an opaque RGBA frame at default compression
  // (~1.9 MB) and a truecolor re-encode is still ~1.3 MB, both over the
  // repository 1 MB large-file hook. Dropping the unused alpha channel
  // and quantizing to a dithered 256-colour palette lands near 0.5 MB;
  // the shader's own grain hides the banding a flat gradient would show.
  const png = await sharp(Buffer.from(dataUrl.split(",")[1], "base64"))
    .removeAlpha()
    .png({ palette: true, colours: 256, quality: 100, dither: 1, compressionLevel: 9, effort: 10 })
    .toBuffer();
  await fs.writeFile(OUT, png);
} finally {
  await browser.close();
}

// eslint-disable-next-line no-console
console.log(
  `[gen-nebula-still] wrote ${path.relative(repoRoot, OUT)} (${WIDTH}x${HEIGHT}, u_time=${TIME})`,
);
