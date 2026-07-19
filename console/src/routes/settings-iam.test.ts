import { afterEach, describe, expect, test, vi } from "vitest";
import type { AuthContext } from "../auth";
import {
  iamIdentityPresentation,
  isIamTabRestricted,
  iamTabFromSegment,
  isCurrentIamLoad,
  referencedUsers,
} from "./settings-iam";
import {
  isRoleAssigned,
  pendingAccessRequestCountKey,
  rosterIdentity,
} from "./settings-iam-requests";
import { isCurrentDirectorySearch } from "./settings-iam-users";
import {
  reviewIamAccessRequest,
  submitIamAccessRequest,
  submitSelfAccessRequest,
} from "./settings-iam.command";
import {
  decodeIamAccessRequests,
  decodeIamAccessRequestPage,
  decodeIamOverview,
  decodeIamSelfStatus,
  decodeHumanIdentityResults,
  decodeIdentityRoster,
} from "./settings-iam.model";

const overview = {
  principal: {
    oid: "principal-1",
    roles: ["Contributor"],
    capabilities: ["view-console", "author-draft-pr"],
  },
  roles: [
    {
      value: "Reader",
      capabilities: ["view-console"],
      routine_assignment: true,
    },
    {
      value: "BreakGlass",
      capabilities: ["view-console", "trigger-kill-switch"],
      routine_assignment: false,
    },
  ],
  assignment_boundary: "identity-provider-group",
};

const accessRequest = {
  request_id: "request-1",
  idempotency_key: "key-1",
  requester_oid: "principal-1",
  identity_provider: "entra",
  target_subject_id: "target-1",
  target_username: "user@example.com",
  operation: "grant",
  role: "Reader",
  justification: "Required for the support rotation.",
  requested_at: "2026-07-16T00:00:00+00:00",
  status: "pending",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("IAM settings contracts", () => {
  test("qualifies pending counts until every request page is loaded", () => {
    expect(pendingAccessRequestCountKey(true)).toBe("settings.iam.pendingLoadedCount");
    expect(pendingAccessRequestCountKey(false)).toBe("settings.iam.pendingCount");
  });

  test("rejects directory results from before the query changed", () => {
    expect(isCurrentDirectorySearch(3, 2)).toBe(false);
    expect(isCurrentDirectorySearch(3, 3)).toBe(true);
  });

  test("rejects a pagination response from before a full reload", () => {
    expect(isCurrentIamLoad(4, 3)).toBe(false);
    expect(isCurrentIamLoad(4, 4)).toBe(true);
  });

  test("distinguishes the default IAM tab from an invalid explicit segment", () => {
    expect(iamTabFromSegment(undefined)).toBe("my-access");
    expect(iamTabFromSegment("roles")).toBe("roles");
    expect(iamTabFromSegment("not-a-tab")).toBeNull();
  });

  test("marks Owner-only tabs as restricted without removing navigation", () => {
    expect(isIamTabRestricted("users", null)).toBe(false);
    expect(isIamTabRestricted("users", false)).toBe(true);
    expect(isIamTabRestricted("requests", false)).toBe(true);
    expect(isIamTabRestricted("roles", false)).toBe(false);
    expect(isIamTabRestricted("users", true)).toBe(false);
  });

  test("separates local Entra identity from the dev authorization principal", () => {
    const auth: AuthContext = {
      devMode: true,
      interactiveSignIn: true,
      account: {
        homeAccountId: "home-account",
        localAccountId: "entra-subject",
        username: "operator@example.com",
      },
      getAuthorizationHeader: async () => null,
      signIn: async () => undefined,
      signOut: async () => undefined,
    };
    const decoded = decodeIamOverview({
      ...overview,
      principal: { ...overview.principal, oid: "dev-anon" },
    });

    expect(iamIdentityPresentation(auth, decoded)).toEqual({
      source: "local-entra",
      subjectId: "entra-subject",
      authorization: "local-ceiling",
    });
  });

  test("does not turn a missing account name into a roster username", () => {
    const decoded = decodeIamOverview(overview);

    expect(referencedUsers(decoded, null, [])[0]).toMatchObject({
      subjectId: "principal-1",
      displayName: "principal-1",
      username: null,
    });
  });

  test("decodes the server-verified principal and role definitions", () => {
    const decoded = decodeIamOverview(overview);

    expect(decoded.principal.roles).toEqual(["Contributor"]);
    expect(decoded.principal.capabilities).toContain("author-draft-pr");
    expect(decoded.roles[1]).toEqual({
      value: "BreakGlass",
      capabilities: ["view-console", "trigger-kill-switch"],
      routineAssignment: false,
    });
  });

  test("rejects an unknown assignment boundary and invalid request state", () => {
    expect(() => decodeIamOverview({ ...overview, assignment_boundary: "direct-user" }))
      .toThrow("identity-provider-group");
    expect(() => decodeIamAccessRequests({
      items: [{ ...accessRequest, status: "applied" }],
    })).toThrow("status is invalid");
    expect(() => decodeIamAccessRequests({
      items: [{ ...accessRequest, identity_provider: undefined }],
    })).toThrow("identity_provider");
    expect(() => decodeIamAccessRequests({
      items: [{ ...accessRequest, requested_at: "not-a-date" }],
    })).toThrow("ISO 8601");
  });

  test("decodes server request totals independently of page length", () => {
    const page = decodeIamAccessRequestPage({
      items: [accessRequest],
      total: 51,
      next_cursor: 50,
    });
    expect(page.items).toHaveLength(1);
    expect(page.total).toBe(51);
    expect(page.nextCursor).toBe(50);
  });

  test("submits the governed command with the bearer token", async () => {
    const fetchMock = vi.fn(async (_url: URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect((init?.headers as Record<string, string>)["authorization"]).toBe("Bearer token");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        idempotency_key: "key-1",
        identity_provider: "entra",
        target_subject_id: "target-1",
        role: "Reader",
      });
      return new Response(JSON.stringify(accessRequest), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    const result = await submitIamAccessRequest(auth, "http://127.0.0.1:8000", {
      idempotencyKey: "key-1",
      identityProvider: "entra",
      targetSubjectId: "target-1",
      targetUsername: "user@example.com",
      operation: "grant",
      role: "Reader",
      justification: "Required for the support rotation.",
    });

    expect(result.requestId).toBe("request-1");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  test("decodes role-optional self status and directory users", () => {
    const self = decodeIamSelfStatus({
      principal: { subject_id: "new-user", username: "new@example.com", roles: [] },
      request: accessRequest,
      can_access_console: false,
    });
    const users = decodeHumanIdentityResults({
      items: [{
        provider: "entra",
        subject_id: "target-1",
        username: "user@example.com",
        display_name: "Example User",
        user_type: "member",
        active: true,
      }],
    });

    expect(self.canAccessConsole).toBe(false);
    expect(self.request?.targetSubjectId).toBe("target-1");
    expect(users[0]?.displayName).toBe("Example User");

    const roster = decodeIdentityRoster({
      items: [
        {
          provider: "entra",
          subject_id: "group-reader",
          display_name: "fdai-readers",
          principal_type: "group",
          roles: ["Reader"],
          username: null,
          active: true,
        },
        {
          provider: "entra",
          subject_id: "user-1",
          display_name: "Alex Kim",
          principal_type: "person",
          roles: ["Reader", "Contributor"],
          username: "alex@example.com",
          active: true,
        },
      ],
    });
    expect(roster.map((item) => item.principalType)).toEqual(["group", "person"]);
    expect(roster[1]?.roles).toEqual(["Reader", "Contributor"]);
  });

  test("submits an optional first-login message", async () => {
    const fetchMock = vi.fn(async (url: URL, init?: RequestInit) => {
      expect(url.pathname).toBe("/iam/access-requests/self");
      expect(JSON.parse(String(init?.body))).toEqual({
        idempotency_key: "self-key",
        message: "Please add me to the support readers.",
      });
      return new Response(JSON.stringify(accessRequest), { status: 201 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    const result = await submitSelfAccessRequest(auth, "http://127.0.0.1:8000", {
      idempotencyKey: "self-key",
      message: "Please add me to the support readers.",
    });

    expect(result.identityProvider).toBe("entra");
  });

  test("submits an Owner review decision", async () => {
    const fetchMock = vi.fn(async (url: URL, init?: RequestInit) => {
      expect(url.pathname).toBe("/iam/access-requests/request-1/decision");
      expect(JSON.parse(String(init?.body))).toEqual({
        decision: "approve",
        justification: "Reviewed against the operator access policy.",
      });
      return new Response(JSON.stringify({
        ...accessRequest,
        status: "approved",
        reviewed_by: "owner-1",
        reviewed_at: "2026-07-16T01:00:00+00:00",
        review_justification: "Reviewed against the operator access policy.",
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    const result = await reviewIamAccessRequest(
      auth,
      "http://127.0.0.1:8000",
      "request-1",
      {
        decision: "approve",
        justification: "Reviewed against the operator access policy.",
      },
    );

    expect(result.status).toBe("approved");
    expect(result.reviewedBy).toBe("owner-1");
  });

  test("resolves request identities from person roster entries only", () => {
    const roster = decodeIdentityRoster({
      items: [
        {
          provider: "entra",
          subject_id: "reader-group",
          display_name: "Readers",
          principal_type: "group",
          roles: ["Reader"],
          username: null,
          active: true,
        },
        {
          provider: "entra",
          subject_id: "user-1",
          display_name: "Example User",
          principal_type: "person",
          roles: ["Reader"],
          username: "user@example.com",
          active: true,
        },
      ],
    });

    expect(rosterIdentity(roster, "user-1")?.username).toBe("user@example.com");
    expect(rosterIdentity(roster, "reader-group")).toBeUndefined();
    expect(isRoleAssigned({
      ...decodeIamAccessRequests({ items: [{
        ...accessRequest,
        status: "approved",
        reviewed_by: "owner-1",
        reviewed_at: "2026-07-16T01:00:00+00:00",
        review_justification: "Reviewed against the operator access policy.",
      }] })[0]!,
      targetSubjectId: "user-1",
    }, roster)).toBe(true);
  });
});
