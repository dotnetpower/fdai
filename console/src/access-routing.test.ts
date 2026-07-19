import { describe, expect, it } from "vitest";
import type { AuthContext } from "./auth";
import {
  shouldAllowLocalDevBypass,
  shouldLoadIamSelf,
  shouldShowAccessRequired,
} from "./access-routing";
import type { IamSelfStatus } from "./routes/settings-iam.model";

function auth(devMode: boolean, account: AuthContext["account"]): AuthContext {
  return {
    devMode,
    account,
    async getAuthorizationHeader() { return null; },
    async signIn() {},
    async signOut() {},
  };
}

const unassigned: IamSelfStatus = {
  principal: {
    subjectId: "user-1",
    username: "user@example.com",
    roles: [],
  },
  request: null,
  canAccessConsole: false,
};

describe("access routing", () => {
  it("loads IAM self and shows access request for local Entra accounts", () => {
    const localEntra = auth(true, {
      homeAccountId: "home-1",
      localAccountId: "user-1",
      username: "user@example.com",
    });

    expect(shouldLoadIamSelf(localEntra)).toBe(true);
    expect(shouldShowAccessRequired(localEntra, unassigned)).toBe(true);
  });

  it("does not load IAM self for anonymous dev bypass", () => {
    const anonymousDev = auth(true, null);

    expect(shouldLoadIamSelf(anonymousDev)).toBe(false);
    expect(shouldAllowLocalDevBypass(anonymousDev)).toBe(true);
    expect(shouldShowAccessRequired(anonymousDev, undefined)).toBe(false);
  });

  it("does not allow dev bypass when interactive Entra sign-in is configured", () => {
    const interactive = {
      ...auth(true, null),
      interactiveSignIn: true,
    };

    expect(shouldAllowLocalDevBypass(interactive)).toBe(false);
  });

  it("allows an assigned account into the console", () => {
    const assigned = auth(false, {
      homeAccountId: "home-1",
      localAccountId: "user-1",
      username: "user@example.com",
    });

    expect(shouldShowAccessRequired(assigned, {
      ...unassigned,
      principal: { ...unassigned.principal, roles: ["Reader"] },
      canAccessConsole: true,
    })).toBe(false);
  });
});
