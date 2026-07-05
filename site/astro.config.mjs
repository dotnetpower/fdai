// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// GitHub Pages project page: https://dotnetpower.github.io/aiopspilot/
// Overridable at build time via SITE_URL / BASE_PATH env vars so a fork can
// deploy under a different owner or path without editing this file.
const SITE_URL = process.env.SITE_URL ?? "https://dotnetpower.github.io";
const BASE_PATH = process.env.BASE_PATH ?? "/aiopspilot";

export default defineConfig({
  site: SITE_URL,
  base: BASE_PATH,
  trailingSlash: "ignore",
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
      sidebar: [
        {
          label: "Roadmap",
          autogenerate: { directory: "roadmap" },
        },
        {
          label: "Phases",
          autogenerate: { directory: "roadmap/phases" },
        },
      ],
      // "Edit this page" is wired later once the roadmap docs are mounted;
      // it will point at the canonical .md under docs/roadmap so contributors
      // land on the source of truth, not the built page.
    }),
  ],
});
