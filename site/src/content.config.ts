// Astro 5+ content collections config for Starlight.
// The `docs` collection is Starlight's convention. Additional loaders that
// mount `../docs/roadmap` will be wired in the next commit.
import { defineCollection } from "astro:content";
import { docsLoader } from "@astrojs/starlight/loaders";
import { docsSchema } from "@astrojs/starlight/schema";

export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
