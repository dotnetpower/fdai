import { describe, expect, it } from "vitest";
import { loginRouteMode } from "./login";

describe("Login route mode", () => {
  it("prioritizes access recovery over sign-in and local bypass", () => {
    const recovery = { error: "Failed to fetch", retry: async () => undefined };

    expect(loginRouteMode(false, recovery)).toBe("access-recovery");
    expect(loginRouteMode(true, recovery, true)).toBe("access-recovery");
    expect(loginRouteMode(false, undefined, true)).toBe("startup");
    expect(loginRouteMode(true, undefined)).toBe("local");
    expect(loginRouteMode(false, undefined)).toBe("sign-in");
  });
});
