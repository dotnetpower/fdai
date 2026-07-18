// Astro 5+ content collections config for Starlight.
// The `docs` collection is Starlight's convention. The roadmap and
// user-guide Markdown trees are symlinked into src/content/docs by
// scripts/mount-docs.mjs (see site/README.md).
import { defineCollection, z } from "astro:content";
import { docsLoader } from "@astrojs/starlight/loaders";
import { docsSchema } from "@astrojs/starlight/schema";

// `derives_from` pins a user-facing doc to the roadmap reference doc(s)
// it was authored from. roadmap docs (docs/roadmap/**) are engineering
// reference material - the source of truth for the design - while
// user-facing docs (docs/user-guide/**) are authored for readers. When a
// user-facing page summarizes facts defined in a roadmap doc, it records
// that source plus the source's git hash-object so the derivation is
// explicit and drift is caught: scripts/quality/localization/check-derived-sources.py fails CI
// when a pinned sha no longer matches, and scripts/quality/localization/refresh-derived-sha.py
// re-pins after review. Extending the schema keeps Starlight's front-matter
// validation from rejecting the field.
const derivesFrom = z
  .array(
    z.object({
      source: z.string(),
      sha: z.string(),
    }),
  )
  .optional();

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        derives_from: derivesFrom,
      }),
    }),
  }),
};
