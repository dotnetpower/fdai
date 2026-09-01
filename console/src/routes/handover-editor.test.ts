import { describe, expect, test } from "vitest";
import type { AuthContext } from "../auth";
import { PANTHEON } from "./agents.model";
import {
  buildHandoverDocument,
  canProposeHandover,
  resolveHandoverAuthority,
  safeProposalUrl,
  type HandoverAssignmentInput,
} from "./handover-editor";
import type { IamOverview } from "./settings-iam.model";

function overview(capabilities: readonly string[]): IamOverview {
  return {
    principal: { oid: "oid-1", roles: [], capabilities: [...capabilities] },
    roles: [],
    assignmentBoundary: "identity-provider-group",
    authority: {
      source: "server-verified",
      isOwner: false,
      canManageGroupMembership: false,
    },
    directory: {
      source: "configured",
      availability: "unknown",
      observedAt: null,
      detail: null,
    },
    workflow: {
      accessRequestAuthority: "proposal_only",
      assignmentAuthority: "observation_only",
      providerMutation: "promotion_required",
    },
  };
}

function auth(roles: readonly string[], options: { devMode?: boolean; account?: boolean } = {}): AuthContext {
  const hasAccount = options.account ?? true;
  return {
    devMode: options.devMode ?? false,
    account: hasAccount ? {
      homeAccountId: "home",
      localAccountId: "local",
      username: "operator@example.com",
      idTokenClaims: { roles: [...roles] },
    } : null,
    async getAuthorizationHeader() { return null; },
    async signIn() {},
    async signOut() {},
  };
}

describe("Handover registration proposal", () => {
  test("renders deterministic structured lines for users and groups", () => {
    const assignments: readonly HandoverAssignmentInput[] = [
      { agent: "Njord", kind: "user", responsibility: "accountable", identity: "Jane Kim" },
      { agent: "Heimdall", kind: "group", responsibility: "informed", identity: "Cloud Operations" },
    ];

    expect(buildHandoverDocument(assignments)).toBe([
      "FDAI agent ownership handover proposal",
      "Agent: Njord; responsibility: accountable; subject: user; identity: Jane Kim",
      "Agent: Heimdall; responsibility: informed; subject: group; identity: Cloud Operations",
      "",
    ].join("\n"));
  });

  test("accepts every fixed pantheon agent and rejects unsafe identities", () => {
    const assignments = PANTHEON.map(({ name }) => ({
      agent: name,
      kind: "user" as const,
      responsibility: "accountable" as const,
      identity: `${name} Owner`,
    }));
    expect(buildHandoverDocument(assignments).split("\n")).toHaveLength(17);
    expect(() => buildHandoverDocument([{ ...assignments[0]!, identity: "Bad; Identity" }]))
      .toThrow(/semicolons/);
    expect(() => buildHandoverDocument([{ ...assignments[0]!, agent: "Unknown" }]))
      .toThrow(/Unknown pantheon agent/);
  });

  test("allows proposal roles and keeps Reader locked", () => {
    expect(canProposeHandover(auth(["Contributor"]))).toBe(true);
    expect(canProposeHandover(auth(["Approver"]))).toBe(true);
    expect(canProposeHandover(auth(["Owner"]))).toBe(true);
    expect(canProposeHandover(auth(["Reader"]))).toBe(false);
    expect(canProposeHandover(auth([], { devMode: true, account: false }))).toBe(true);
  });

  test("resolves authority from the server IAM projection, not the SPA id token", () => {
    // FDAI App Roles live on the API application, so a fully authorized browser
    // session normally has no id-token roles claim.
    const claimless = auth([]);
    expect(resolveHandoverAuthority(claimless, null, false)).toBe("resolving");
    expect(resolveHandoverAuthority(claimless, overview(["view-console", "author-draft-pr"]), false))
      .toBe("granted");
    expect(resolveHandoverAuthority(claimless, overview(["view-console"]), false)).toBe("denied");
    expect(resolveHandoverAuthority(claimless, null, true)).toBe("denied");
    expect(resolveHandoverAuthority(auth(["Contributor"]), null, false)).toBe("granted");
    expect(resolveHandoverAuthority(auth([], { devMode: true, account: false }), null, false))
      .toBe("granted");
  });

  test("renders only absolute HTTPS proposal links without credentials", () => {
    expect(safeProposalUrl("https://example.com/pull/42"))
      .toBe("https://example.com/pull/42");
    expect(safeProposalUrl("javascript:alert(1)")) .toBeNull();
    expect(safeProposalUrl("data:text/html,unsafe")).toBeNull();
    expect(safeProposalUrl("/pull/42")).toBeNull();
    expect(safeProposalUrl("https://user:password@example.com/pull/42")).toBeNull();
  });
});
