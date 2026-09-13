import { describe, expect, it } from "vitest";
import {
  beginAccessCheck,
  isCurrentAccessCheck,
  signedInAccountLabel,
} from "./access-required";

describe("Access Required status polling", () => {
  it("allows only the latest overlapping check to commit", () => {
    const generation = { current: 0 };
    const first = beginAccessCheck(generation);
    const second = beginAccessCheck(generation);

    expect(isCurrentAccessCheck(generation, first)).toBe(false);
    expect(isCurrentAccessCheck(generation, second)).toBe(true);
  });
});

describe("Access Required account label", () => {
  it("prefers the server-verified email over the browser session", () => {
    expect(signedInAccountLabel(
      "verified@example.com",
      "session@example.com",
      "Unavailable",
    )).toBe("verified@example.com");
  });

  it("uses the browser session username instead of exposing a subject id", () => {
    expect(signedInAccountLabel(null, "session@example.com", "Unavailable"))
      .toBe("session@example.com");
    expect(signedInAccountLabel(null, undefined, "Unavailable")).toBe("Unavailable");
  });
});
