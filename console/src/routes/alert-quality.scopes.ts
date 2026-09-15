/** Exact authorized-scope decoding and principal-bound presentation selectors. */
import type { AuthContext } from "../auth";
import type { ConsoleDataMode } from "../console-data-mode";
import { isAlertQualityRef } from "./alert-quality.model";
import { panelContractError, panelRecord } from "./panel-decode";

export const ALERT_MAX_SCOPES = 64;

/** Discovery grants no execution authority and contains no provider or audience identities. */
export interface AlertQualityScopes {
  readonly source: "alert-noise-governance";
  readonly scope_refs: readonly string[];
  readonly execution_authority: false;
}

/** Reject the whole list rather than sorting, truncating or repairing an unsafe response. */
export function decodeAlertQualityScopes(value: unknown): AlertQualityScopes {
  const row = panelRecord(value, "alert quality scopes");
  if (Object.keys(row).length !== 3
    || Object.keys(row).some((key) => !["source", "scope_refs", "execution_authority"].includes(key))
    || row.source !== "alert-noise-governance" || row.execution_authority !== false
    || !Array.isArray(row.scope_refs) || row.scope_refs.length > ALERT_MAX_SCOPES) {
    throw panelContractError("alert quality scopes: invalid discovery envelope");
  }
  const scope_refs: string[] = [];
  for (const value of row.scope_refs) {
    if (!isAlertQualityRef(value) || (scope_refs.length > 0 && value <= scope_refs[scope_refs.length - 1]!)) {
      throw panelContractError("alert quality scopes: expected sorted unique opaque references");
    }
    scope_refs.push(value);
  }
  return { source: "alert-noise-governance", scope_refs: Object.freeze(scope_refs), execution_authority: false };
}

export type AlertQualityScopeSelection =
  | { readonly status: "missing" | "invalid" | "unauthorized" }
  | { readonly status: "selected"; readonly scope: string };

/** A URL is a selector, not authority. Even a valid explicit scope must occur in discovery. */
export function selectAlertQualityScope(
  search: URLSearchParams, scopes: AlertQualityScopes,
): AlertQualityScopeSelection {
  const values = search.getAll("scope_ref");
  if (values.length === 0) return { status: "missing" };
  if (values.length !== 1 || !isAlertQualityRef(values[0])) return { status: "invalid" };
  return scopes.scope_refs.includes(values[0])
    ? { status: "selected", scope: values[0] } : { status: "unauthorized" };
}

/** Identity fingerprint for withdrawing stale UI, never a browser RBAC decision or token. */
export function alertQualityPrincipal(auth: AuthContext, mode: ConsoleDataMode): string | null {
  const account = auth.account;
  if (mode !== "live" || (auth.devMode && auth.localAzureCli !== true) || account === null
    || !account.homeAccountId || !account.localAccountId) return null;
  return JSON.stringify([account.homeAccountId, account.localAccountId, auth.localAzureCli === true]);
}
