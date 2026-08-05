import { describe, expect, it } from "vitest";

import { AsyncLimiter } from "./image-fetch-limiter";

describe("conversation image fetch limiter", () => {
  it("never runs more than the configured number of operations", async () => {
    const limiter = new AsyncLimiter(2);
    let active = 0;
    let maximum = 0;

    const operations = Array.from({ length: 5 }, () => limiter.run(async () => {
      active += 1;
      maximum = Math.max(maximum, active);
      await Promise.resolve();
      await Promise.resolve();
      active -= 1;
    }));

    await Promise.all(operations);
    expect(maximum).toBe(2);
  });

  it("releases a slot after a rejected operation", async () => {
    const limiter = new AsyncLimiter(1);
    await expect(limiter.run(async () => {
      throw new Error("failed");
    })).rejects.toThrow("failed");
    await expect(limiter.run(async () => "next")).resolves.toBe("next");
  });
});
