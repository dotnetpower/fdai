// gen-og-image.mjs - render the social share (Open Graph) cover image.
//
// Link-preview cards (KakaoTalk, Slack, Discord, iMessage, Facebook, X)
// read `og:image` plus its declared `og:image:width` / `og:image:height`.
// FDAI ships a 4:3 cover (1200x900) so the preview renders as a 4:3 card
// instead of the default 1.91:1 letterbox. The meta tags are wired in
// astro.config.mjs; this script only rasterizes the committed PNG.
//
// The background is our procedural WebGL nebula (see
// src/components/NebulaBackground.astro). WebGL cannot be rendered
// headless here, so a single captured frame is committed as the source
// asset scripts/og-nebula-bg.png (1200x900) and this script composites
// the FDAI wordmark over it. Re-capture the background by serving
// site/public/nebula-demo.html, screenshotting the canvas, and
// cover-resizing to 1200x900 -> scripts/og-nebula-bg.png.
//
// The output is a static asset committed at site/public/og-cover.png.
// Run `npm run gen-og` to regenerate it after editing the design below.
// sharp (an Astro transitive dependency) does the SVG -> PNG raster and
// the composite over the nebula.

import { fileURLToPath } from "node:url";
import path from "node:path";
import sharp from "sharp";

const WIDTH = 1200;
const HEIGHT = 900; // 4:3

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const NEBULA_BG = path.resolve(scriptDir, "og-nebula-bg.png");
const OUT = path.resolve(scriptDir, "..", "public", "og-cover.png");

// Brand palette mirrors site/src/styles/custom.css and CustomHero.astro:
//   deep-space bg  #05070f, Azure accent #0078D4, cyan #50E6FF.
// The nebula carries the colour, so the overlay only adds a dark scrim
// (for text legibility over the bright cloud) plus the text.
const overlay = `<svg width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}"
     xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="scrim" cx="50%" cy="50%" r="60%">
      <stop offset="0%" stop-color="#05070f" stop-opacity="0.74"/>
      <stop offset="52%" stop-color="#05070f" stop-opacity="0.52"/>
      <stop offset="100%" stop-color="#05070f" stop-opacity="0.14"/>
    </radialGradient>
    <linearGradient id="vign" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#05070f" stop-opacity="0.4"/>
      <stop offset="28%" stop-color="#05070f" stop-opacity="0"/>
      <stop offset="72%" stop-color="#05070f" stop-opacity="0"/>
      <stop offset="100%" stop-color="#05070f" stop-opacity="0.6"/>
    </linearGradient>
    <linearGradient id="wordmark" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="55%" stop-color="#50E6FF"/>
      <stop offset="100%" stop-color="#4aa8ff"/>
    </linearGradient>
  </defs>

  <rect width="${WIDTH}" height="${HEIGHT}" fill="url(#scrim)"/>
  <rect width="${WIDTH}" height="${HEIGHT}" fill="url(#vign)"/>

  <g font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" text-anchor="middle">
    <!-- wordmark -->
    <text x="600" y="418" font-size="224" font-weight="700"
          letter-spacing="8" fill="url(#wordmark)">FDAI</text>
    <!-- full name, small caps -->
    <text x="600" y="500" font-size="42" font-weight="600" letter-spacing="14"
          fill="#dbe6f7">FORWARD DEPLOYED AGENTS</text>
    <!-- tagline -->
    <text x="600" y="602" font-size="34" font-weight="400" fill="#aec0dd">
      Deterministic-first, event-driven, risk-gated cloud operations.
    </text>
  </g>

  <!-- footer url -->
  <text x="600" y="822" text-anchor="middle"
        font-family="'DejaVu Sans Mono', 'Courier New', monospace"
        font-size="26" letter-spacing="2" fill="#7f92b0">dotnetpower.github.io/fdai</text>
</svg>`;

await sharp(NEBULA_BG)
  .composite([{ input: Buffer.from(overlay) }])
  .png()
  .toFile(OUT);

// eslint-disable-next-line no-console
console.log(
  `[gen-og-image] wrote ${path.relative(process.cwd(), OUT)} (${WIDTH}x${HEIGHT}) over nebula background`,
);
