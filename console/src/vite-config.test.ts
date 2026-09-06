import { describe, expect, it } from "vitest";

import { offlineBuildOptions, PREACT_PLUGIN_OPTIONS, resolveViteCacheDir } from "../vite.config";

describe("Vite dependency cache", () => {
  it("keeps the default cache for ordinary Console starts", () => {
    expect(resolveViteCacheDir({})).toBe("node_modules/.vite");
  });

  describe("generic offline Console builds", () => {
    it("disables env files and exposed process variables and requires runtime bindings", () => {
      expect(offlineBuildOptions("offline")).toEqual({
        envDir: false,
        envPrefix: [],
        define: { "import.meta.env.VITE_REQUIRE_RUNTIME_CONFIG": '"1"' },
      });
    });

    it("does not change ordinary build or development environment handling", () => {
      expect(offlineBuildOptions("production")).toEqual({});
      expect(offlineBuildOptions("development")).toEqual({});
      expect(offlineBuildOptions("test")).toEqual({});
    });
  });

  it("uses the runner-owned cache when configured", () => {
    expect(resolveViteCacheDir({ VITE_CACHE_DIR: "/tmp/assurance-vite-cache" }))
      .toBe("/tmp/assurance-vite-cache");
  });

  it("uses full reloads instead of duplicating lazy route subtrees during Fast Refresh", () => {
    expect(PREACT_PLUGIN_OPTIONS).toEqual({ prefreshEnabled: false });
  });
});
