import { describe, expect, it } from "vitest";

import { resolveViteCacheDir } from "../vite.config";

describe("Vite dependency cache", () => {
  it("keeps the default cache for ordinary Console starts", () => {
    expect(resolveViteCacheDir({})).toBe("node_modules/.vite");
  });

  it("uses the runner-owned cache when configured", () => {
    expect(resolveViteCacheDir({ VITE_CACHE_DIR: "/tmp/assurance-vite-cache" }))
      .toBe("/tmp/assurance-vite-cache");
  });
});
