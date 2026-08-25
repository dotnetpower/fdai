import { describe, expect, it } from "vitest";

import { PREACT_PLUGIN_OPTIONS, resolveViteCacheDir } from "../vite.config";

describe("Vite dependency cache", () => {
  it("keeps the default cache for ordinary Console starts", () => {
    expect(resolveViteCacheDir({})).toBe("node_modules/.vite");
  });

  it("uses the runner-owned cache when configured", () => {
    expect(resolveViteCacheDir({ VITE_CACHE_DIR: "/tmp/assurance-vite-cache" }))
      .toBe("/tmp/assurance-vite-cache");
  });

  it("uses full reloads instead of duplicating lazy route subtrees during Fast Refresh", () => {
    expect(PREACT_PLUGIN_OPTIONS).toEqual({ prefreshEnabled: false });
  });
});
