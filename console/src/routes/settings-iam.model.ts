export type IamRole = "Reader" | "Contributor" | "Approver" | "Owner" | "BreakGlass";
export type AccessOperation = "grant" | "revoke" | "set";

export interface IamPrincipal {
  readonly oid: string;
  readonly roles: readonly IamRole[];
  readonly capabilities: readonly string[];
}

export interface IamRoleDefinition {
  readonly value: IamRole;
  readonly capabilities: readonly string[];
  readonly routineAssignment: boolean;
}

export interface IamOverview {
  readonly principal: IamPrincipal;
  readonly roles: readonly IamRoleDefinition[];
  readonly assignmentBoundary: "identity-provider-group";
  readonly authority: {
    readonly source: "server-verified";
    readonly isOwner: boolean;
    readonly canManageGroupMembership: boolean;
  };
  readonly directory: {
    readonly source: string;
    readonly availability: "available" | "unavailable" | "not_configured" | "unknown";
    readonly observedAt: string | null;
    readonly detail: string | null;
  };
  readonly workflow: {
    readonly accessRequestAuthority: "proposal_only";
    readonly assignmentAuthority: "observation_only";
    readonly providerMutation: "promotion_required";
  };
}

export interface IamAccessRequest {
  readonly requestId: string;
  readonly idempotencyKey: string;
  readonly requesterOid: string;
  readonly identityProvider: string;
  readonly targetSubjectId: string;
  readonly targetUsername: string;
  readonly operation: AccessOperation;
  readonly role: IamRole;
  readonly justification: string;
  readonly requestedAt: string;
  readonly status: "pending" | "approved" | "rejected";
  readonly reviewedBy: string | null;
  readonly reviewedAt: string | null;
  readonly reviewJustification: string | null;
}

export interface IamAccessRequestInput {
  readonly idempotencyKey: string;
  readonly identityProvider: string;
  readonly targetSubjectId: string;
  readonly targetUsername: string;
  readonly operation: AccessOperation;
  readonly role: Exclude<IamRole, "BreakGlass">;
  readonly justification: string;
}

export interface IamAccessRequestPage {
  readonly items: readonly IamAccessRequest[];
  readonly total: number;
  readonly nextCursor: number | null;
}

export interface IamSelfStatus {
  readonly principal: {
    readonly subjectId: string;
    readonly username: string | null;
    readonly roles: readonly IamRole[];
  };
  readonly request: IamAccessRequest | null;
  readonly canAccessConsole: boolean;
}

export interface HumanIdentityResult {
  readonly provider: string;
  readonly subjectId: string;
  readonly username: string;
  readonly displayName: string;
  readonly userType: string;
  readonly active: boolean;
}

export interface IdentityRosterItem {
  readonly provider: string;
  readonly subjectId: string;
  readonly displayName: string;
  readonly principalType: "person" | "group";
  readonly roles: readonly IamRole[];
  readonly username: string | null;
  readonly active: boolean;
}

export function decodeIamOverview(value: unknown): IamOverview {
  const root = record(value, "IAM overview");
  const principal = record(root["principal"], "IAM principal");
  const roles = array(root["roles"], "IAM roles").map((item) => {
    const role = record(item, "IAM role");
    return {
      value: iamRole(role["value"], "IAM role.value"),
      capabilities: stringArray(role["capabilities"], "IAM role.capabilities"),
      routineAssignment: boolean(role["routine_assignment"], "IAM role.routine_assignment"),
    };
  });
  const boundary = string(root["assignment_boundary"], "IAM assignment_boundary");
  if (boundary !== "identity-provider-group") {
    throw new Error("IAM assignment_boundary MUST be identity-provider-group");
  }
  const principalRoles = stringArray(principal["roles"], "IAM principal.roles").map((role) =>
    iamRole(role, "IAM principal.roles[]")
  );
  const principalCapabilities = stringArray(
    principal["capabilities"],
    "IAM principal.capabilities",
  );
  const authority = root["access_authority"] === undefined
    ? null
    : record(root["access_authority"], "IAM access_authority");
  const directory = root["directory"] === undefined
    ? null
    : record(root["directory"], "IAM directory");
  const workflow = root["workflow"] === undefined
    ? null
    : record(root["workflow"], "IAM workflow");
  const availability = directory === null
    ? "unknown"
    : string(directory["availability"], "IAM directory.availability");
  if (!["available", "unavailable", "not_configured", "unknown"].includes(availability)) {
    throw new Error("IAM directory.availability is invalid");
  }
  const accessRequestAuthority = workflow === null
    ? "proposal_only"
    : string(workflow["access_request_authority"], "IAM workflow.access_request_authority");
  const assignmentAuthority = workflow === null
    ? "observation_only"
    : string(workflow["assignment_authority"], "IAM workflow.assignment_authority");
  const providerMutation = workflow === null
    ? "promotion_required"
    : string(workflow["provider_mutation"], "IAM workflow.provider_mutation");
  if (
    accessRequestAuthority !== "proposal_only"
    || assignmentAuthority !== "observation_only"
    || providerMutation !== "promotion_required"
  ) {
    throw new Error("IAM workflow authority is invalid");
  }
  return {
    principal: {
      oid: string(principal["oid"], "IAM principal.oid"),
      roles: principalRoles,
      capabilities: principalCapabilities,
    },
    roles,
    assignmentBoundary: "identity-provider-group",
    authority: {
      source: authority === null ? "server-verified" : serverVerifiedSource(authority["source"]),
      isOwner: authority === null
        ? principalRoles.includes("Owner")
        : boolean(authority["is_owner"], "IAM access_authority.is_owner"),
      canManageGroupMembership: authority === null
        ? principalCapabilities.includes("manage-group-membership")
        : boolean(
            authority["can_manage_group_membership"],
            "IAM access_authority.can_manage_group_membership",
          ),
    },
    directory: {
      source: directory === null ? "legacy-api" : string(directory["source"], "IAM directory.source"),
      availability: availability as IamOverview["directory"]["availability"],
      observedAt: directory === null
        ? null
        : nullableDateString(directory["observed_at"] ?? null, "IAM directory.observed_at"),
      detail: directory === null
        ? null
        : nullableString(directory["detail"] ?? null, "IAM directory.detail"),
    },
    workflow: {
      accessRequestAuthority: "proposal_only",
      assignmentAuthority: "observation_only",
      providerMutation: "promotion_required",
    },
  };
}

function serverVerifiedSource(value: unknown): "server-verified" {
  if (value !== "server-verified") throw new Error("IAM access_authority.source is invalid");
  return value;
}

export function decodeIamAccessRequests(value: unknown): readonly IamAccessRequest[] {
  return decodeIamAccessRequestPage(value).items;
}

export function decodeIamAccessRequestPage(value: unknown): IamAccessRequestPage {
  const root = record(value, "IAM access request page");
  const items = array(root["items"], "IAM access request page.items").map(decodeIamAccessRequest);
  const total = root["total"] === undefined
    ? items.length
    : nonNegativeInteger(root["total"], "IAM access request page.total");
  const nextCursor = root["next_cursor"] === null || root["next_cursor"] === undefined
    ? null
    : nonNegativeInteger(root["next_cursor"], "IAM access request page.next_cursor");
  if (total < items.length) throw new Error("IAM access request page.total is invalid");
  return { items, total, nextCursor };
}

export function decodeIamAccessRequest(value: unknown): IamAccessRequest {
  const item = record(value, "IAM access request");
  const operation = string(item["operation"], "IAM access request.operation");
  if (operation !== "grant" && operation !== "revoke" && operation !== "set") {
    throw new Error("IAM access request.operation MUST be grant, revoke, or set");
  }
  const status = string(item["status"], "IAM access request.status");
  if (!["pending", "approved", "rejected"].includes(status)) {
    throw new Error("IAM access request.status is invalid");
  }
  return {
    requestId: string(item["request_id"], "IAM access request.request_id"),
    idempotencyKey: string(item["idempotency_key"], "IAM access request.idempotency_key"),
    requesterOid: string(item["requester_oid"], "IAM access request.requester_oid"),
    identityProvider: string(item["identity_provider"], "IAM access request.identity_provider"),
    targetSubjectId: string(
      item["target_subject_id"] ?? item["target_oid"],
      "IAM access request.target_subject_id",
    ),
    targetUsername: string(item["target_username"], "IAM access request.target_username"),
    operation,
    role: iamRole(item["role"], "IAM access request.role"),
    justification: string(item["justification"], "IAM access request.justification"),
    requestedAt: dateString(item["requested_at"], "IAM access request.requested_at"),
    status: status as IamAccessRequest["status"],
    reviewedBy: nullableString(item["reviewed_by"] ?? null, "IAM reviewed_by"),
    reviewedAt: nullableDateString(item["reviewed_at"] ?? null, "IAM reviewed_at"),
    reviewJustification: nullableString(
      item["review_justification"] ?? null,
      "IAM review_justification",
    ),
  };
}

export function decodeIamSelfStatus(value: unknown): IamSelfStatus {
  const root = record(value, "IAM self status");
  const principal = record(root["principal"], "IAM self principal");
  return {
    principal: {
      subjectId: string(principal["subject_id"], "IAM self principal.subject_id"),
      username: nullableString(principal["username"], "IAM self principal.username"),
      roles: stringArray(principal["roles"], "IAM self principal.roles").map((role) =>
        iamRole(role, "IAM self principal.roles[]")
      ),
    },
    request: root["request"] === null ? null : decodeIamAccessRequest(root["request"]),
    canAccessConsole: boolean(root["can_access_console"], "IAM self can_access_console"),
  };
}

export function decodeHumanIdentityResults(value: unknown): readonly HumanIdentityResult[] {
  const root = record(value, "human identity search result");
  return array(root["items"], "human identity search result.items").map((value) => {
    const item = record(value, "human identity");
    return {
      provider: string(item["provider"], "human identity.provider"),
      subjectId: string(item["subject_id"], "human identity.subject_id"),
      username: string(item["username"], "human identity.username"),
      displayName: string(item["display_name"], "human identity.display_name"),
      userType: string(item["user_type"], "human identity.user_type"),
      active: boolean(item["active"], "human identity.active"),
    };
  });
}

export function decodeIdentityRoster(value: unknown): readonly IdentityRosterItem[] {
  const root = record(value, "identity roster");
  return array(root["items"], "identity roster.items").map((value) => {
    const item = record(value, "identity roster item");
    const principalType = string(item["principal_type"], "identity roster.principal_type");
    if (principalType !== "person" && principalType !== "group") {
      throw new Error("identity roster.principal_type MUST be person or group");
    }
    return {
      provider: string(item["provider"], "identity roster.provider"),
      subjectId: string(item["subject_id"], "identity roster.subject_id"),
      displayName: string(item["display_name"], "identity roster.display_name"),
      principalType,
      roles: stringArray(item["roles"], "identity roster.roles").map((role) =>
        iamRole(role, "identity roster.roles[]")
      ),
      username: nullableString(item["username"] ?? null, "identity roster.username"),
      active: boolean(item["active"], "identity roster.active"),
    };
  });
}

function iamRole(value: unknown, name: string): IamRole {
  const role = string(value, name);
  if (!["Reader", "Contributor", "Approver", "Owner", "BreakGlass"].includes(role)) {
    throw new Error(`${name} is not a known IAM role`);
  }
  return role as IamRole;
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${name} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, name: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${name} MUST be an array`);
  return value;
}

function string(value: unknown, name: string): string {
  if (typeof value !== "string" || !value) throw new Error(`${name} MUST be a non-empty string`);
  return value;
}

function nullableString(value: unknown, name: string): string | null {
  if (value === null) return null;
  return string(value, name);
}

function dateString(value: unknown, name: string): string {
  const parsed = string(value, name);
  if (!Number.isFinite(Date.parse(parsed))) throw new Error(`${name} MUST be ISO 8601`);
  return parsed;
}

function nullableDateString(value: unknown, name: string): string | null {
  if (value === null) return null;
  return dateString(value, name);
}

function stringArray(value: unknown, name: string): readonly string[] {
  return array(value, name).map((item) => string(item, `${name}[]`));
}

function boolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${name} MUST be a boolean`);
  return value;
}

function nonNegativeInteger(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${name} MUST be a non-negative integer`);
  }
  return value;
}
