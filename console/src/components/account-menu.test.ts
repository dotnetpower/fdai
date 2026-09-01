import { beforeEach, describe, expect, it } from "vitest";
import type { AuthContext } from "../auth";
import { setLocale } from "../i18n";
import type { IamSelfStatus } from "../routes/settings-iam.model";
import {
  accountInitials,
  accountSessionLabel,
  verifiedAccountRoles,
} from "./account-menu";

function auth(overrides: Partial<AuthContext> = {}): AuthContext {
  return {
    devMode: false,
    account: null,
    async getAuthorizationHeader() { return null; },
    async signIn() {},
    async signOut() {},
    ...overrides,
  };
}

describe("account menu presentation", () => {
  beforeEach(() => setLocale("en"));

  it("uses the display-name edges and falls back to the username", () => {
    expect(accountInitials("Ada Lovelace", "ada@example.com")).toBe("AL");
    expect(accountInitials("문 초이", "moon@example.com")).toBe("문초");
    expect(accountInitials(undefined, "moon.choi@example.com")).toBe("MC");
    expect(accountInitials(undefined, "@example.com")).toBe("?");
  });

  it("shows roles only from the server-verified self projection", () => {
    const iamSelf: IamSelfStatus = {
      principal: {
        subjectId: "user-1",
        username: "operator@example.com",
        roles: ["Reader", "Approver"],
      },
      request: null,
      canAccessConsole: true,
    };

    expect(verifiedAccountRoles(iamSelf)).toEqual(["Reader", "Approver"]);
    expect(verifiedAccountRoles(undefined)).toBeNull();
  });

  it("distinguishes production, local Entra, and Azure CLI sessions", () => {
    expect(accountSessionLabel(auth())).toBe("Microsoft Entra ID");
    expect(accountSessionLabel(auth({ devMode: true }))).toBe("Local Microsoft Entra ID");
    expect(accountSessionLabel(auth({ devMode: true, localAzureCli: true })))
      .toBe("Azure CLI session");
  });

  it("localizes session labels without changing their auth classification", () => {
    setLocale("ko");

    expect(accountSessionLabel(auth())).toBe("Microsoft Entra ID");
    expect(accountSessionLabel(auth({ devMode: true }))).toBe("로컬 Microsoft Entra ID");
    expect(accountSessionLabel(auth({ devMode: true, localAzureCli: true })))
      .toBe("Azure CLI 세션");
  });
});
