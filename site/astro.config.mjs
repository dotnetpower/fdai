// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import { remarkStripFirstH1 } from "./src/plugins/strip-first-h1.mjs";
import { remarkMermaid } from "./src/plugins/mermaid.mjs";

// GitHub Pages project page: https://dotnetpower.github.io/aiopspilot/
// Overridable at build time via SITE_URL / BASE_PATH env vars so a fork can
// deploy under a different owner or path without editing this file.
//
// Base path defaults by environment:
//   - astro dev  (NODE_ENV=development) -> "/"          so localhost:4321/roadmap/ works
//   - astro build (NODE_ENV=production) -> "/aiopspilot" (GitHub Pages project page)
// An explicit BASE_PATH env always wins, so CI can override either way.
const SITE_URL = process.env.SITE_URL ?? "https://dotnetpower.github.io";
const IS_PROD = process.env.NODE_ENV === "production";
const BASE_PATH = process.env.BASE_PATH ?? (IS_PROD ? "/aiopspilot" : "/");

export default defineConfig({
  site: SITE_URL,
  base: BASE_PATH,
  trailingSlash: "ignore",
  // Starlight auto-renders `frontmatter.title` as the page H1. The source
  // Markdown under docs/roadmap/**/*.md keeps its own `# Title` line so it
  // reads naturally on GitHub, so left alone the site would show two H1s
  // back-to-back. remarkStripFirstH1 drops the first H1 iff it duplicates
  // the front-matter title; anything else is preserved.
  // remarkMermaid rewrites ```mermaid fenced blocks into a bare
  // <pre class="mermaid"> so the head-level mermaid loader can render
  // them on the client (Expressive Code otherwise turns them into a
  // syntax-highlighted code sample).
  markdown: {
    remarkPlugins: [remarkStripFirstH1, remarkMermaid],
  },
  integrations: [
    starlight({
      title: "AIOpsPilot",
      description:
        "Autonomous cloud operations control plane — deterministic-first, event-driven, risk-gated.",
      // Browser language detection is Starlight's default behaviour when
      // multiple locales are configured. Users land on the closest match to
      // their Accept-Language header and can flip via the language switcher.
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        ko: { label: "\ud55c\uad6d\uc5b4", lang: "ko" },
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/dotnetpower/aiopspilot",
        },
      ],
      customCss: ["./src/styles/custom.css"],
      // Client-side Mermaid renderer. Loaded from jsDelivr as an ES module
      // so it stays out of the site's build graph (build-time SVG via
      // Playwright/rehype-mermaid would be heavier and, importantly,
      // would not react to the reader's theme toggle). The script:
      //   1. imports mermaid.esm.min.mjs from a CDN,
      //   2. initialises it with the current theme (data-theme on <html>),
      //   3. calls mermaid.run() once the DOM is ready,
      //   4. observes data-theme changes and re-renders every diagram so
      //      switching to dark mode isn't visually jarring.
      // Content lives in an inline module script because Starlight's head
      // slot inserts raw HTML — Astro's script pipeline is out of scope.
      head: [
        {
          tag: "script",
          attrs: { type: "module" },
          content: `
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
            const currentTheme = () =>
              document.documentElement.dataset.theme === 'dark' ? 'dark' : 'default';
            const configure = () =>
              mermaid.initialize({
                startOnLoad: false,
                theme: currentTheme(),
                securityLevel: 'strict',
                fontFamily: 'inherit',
              });
            const renderAll = async () => {
              const nodes = document.querySelectorAll('pre.mermaid');
              nodes.forEach((el) => {
                if (!el.dataset.mermaidSrc) el.dataset.mermaidSrc = el.textContent ?? '';
                el.textContent = el.dataset.mermaidSrc;
                el.removeAttribute('data-processed');
              });
              await mermaid.run({ nodes: [...nodes] });
            };
            configure();
            if (document.readyState === 'loading') {
              document.addEventListener('DOMContentLoaded', renderAll);
            } else {
              renderAll();
            }
            new MutationObserver(() => {
              configure();
              renderAll();
            }).observe(document.documentElement, {
              attributes: true,
              attributeFilter: ['data-theme'],
            });
          `,
        },
      ],
      sidebar: [
        {
          label: "Roadmap",
          autogenerate: { directory: "roadmap" },
        },
      ],
      editLink: {
        // "Edit this page" points at the canonical Markdown under
        // docs/roadmap/, not at the mounted symlink. Contributors land on
        // the source of truth.
        baseUrl: "https://github.com/dotnetpower/aiopspilot/edit/main/",
      },
    }),
  ],
});
