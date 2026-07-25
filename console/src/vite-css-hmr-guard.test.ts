import { describe, expect, test, vi } from "vitest";

import { stabilizeCssHotUpdate } from "./vite-css-hmr-guard";

describe("CSS hot-update guard", () => {
  test("waits for Vite's race-safe CSS read before continuing", async () => {
    let releaseRead: ((content: string) => void) | undefined;
    const read = vi.fn(
      () => new Promise<string>((resolve) => {
        releaseRead = resolve;
      }),
    );
    let completed = false;

    const update = stabilizeCssHotUpdate("/workspace/console/src/styles.css", read).then(() => {
      completed = true;
    });
    await Promise.resolve();

    expect(read).toHaveBeenCalledOnce();
    expect(completed).toBe(false);

    releaseRead?.("body { margin: 0; }");
    await update;

    expect(completed).toBe(true);
  });

  test("does not read non-CSS updates", async () => {
    const read = vi.fn(() => "export const value = true;");

    await stabilizeCssHotUpdate("/workspace/console/src/main.tsx", read);

    expect(read).not.toHaveBeenCalled();
  });
});
