import { afterEach, describe, expect, test } from "vitest";
import { isPanelRegistered } from "../router";

const previousFlags = globalThis.__FDAI_STENCIL_FEATURE_FLAGS__;

afterEach(() => {
  globalThis.__FDAI_STENCIL_FEATURE_FLAGS__ = previousFlags;
});

describe("Command Deck attachment capability", () => {
  test("hides document upload when the active Stencil omits Documents", () => {
    globalThis.__FDAI_STENCIL_FEATURE_FLAGS__ = {
      schema_version: "fdai.stencil-feature-flags.v1",
      stencil_id: "lite-observe-alert",
      enforcement_mode: "fail-closed",
      enabled_panel_ids: ["dashboard", "audit", "settings-general", "live"],
    };

    expect(isPanelRegistered("documents")).toBe(false);
  });

  test("keeps document upload available when the active Stencil includes Documents", () => {
    globalThis.__FDAI_STENCIL_FEATURE_FLAGS__ = {
      schema_version: "fdai.stencil-feature-flags.v1",
      stencil_id: "standard-sre",
      enforcement_mode: "fail-closed",
      enabled_panel_ids: [
        "dashboard",
        "audit",
        "settings-general",
        "documents",
      ],
    };

    expect(isPanelRegistered("documents")).toBe(true);
  });
});
