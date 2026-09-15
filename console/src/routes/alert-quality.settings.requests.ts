/** Current-principal, scope and revision fences for Settings only; never a runtime authority. */
import { isOptionalOperatorApiUnavailable, OperatorApiError, type OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import type { AsyncState } from "../components/ui";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import { isAlertQualityRef } from "./alert-quality.model";
import type { AlertClient } from "./alert-quality.requests";
import { ALERT_MAX_SCOPES } from "./alert-quality.scopes";
import {
  alertQualitySettingsOwner, buildAlertQualitySettingsUpdate, decodeAlertQualitySettings, type AlertQualitySettings,
} from "./alert-quality.settings.model";
import { alertQualityText as text } from "./i18n/alert-quality";

export type AlertQualitySettingsClient = AlertClient & Pick<OperatorApiClient, "iamOverview">;
export type AlertQualitySettingsAuthority = "loading" | "owner" | "read-only" | "unavailable" | "denied";
export type AlertQualitySettingsCommand = "idle" | "pending" | "saved" | "conflict" | "denied" | "rejected" | "blocked" | "unknown";
export interface AlertQualitySettingsState {
  readonly read: AsyncState<AlertQualitySettings>;
  readonly authority: AlertQualitySettingsAuthority;
  readonly command: AlertQualitySettingsCommand;
  readonly editable: boolean;
}

/** Denial and ambiguous writes stay locked across scoped remounts for this principal and origin. */
export function createAlertQualitySettingsMemory() {
  const holds = new Map<string, "denied" | "unknown">();
  let overflow = false;
  return {
    held: (scope: string): "denied" | "unknown" | null => holds.get(scope) ?? (overflow ? "unknown" : null),
    hold: (scope: string, reason: "denied" | "unknown"): void => {
      if (holds.size >= ALERT_MAX_SCOPES && !holds.has(scope)) overflow = true;
      else if (holds.get(scope) !== "denied") holds.set(scope, reason);
    },
  };
}
export type AlertQualitySettingsMemory = ReturnType<typeof createAlertQualitySettingsMemory>;

export interface AlertQualitySettingsSession {
  readonly load: () => Promise<void>;
  readonly save: (enabled: boolean, expectedRevision: number) => Promise<void>;
  /** A veto only. The report's independent requestable and authority fields still apply. */
  readonly requestsAllowed: () => boolean;
  readonly dispose: () => void;
}

class SettingsRequestNotSent extends Error {
  constructor() { super("Alert-quality settings request was not sent; current context is required"); }
}

async function bounded<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([work, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("Alert-quality settings deadline exceeded")), 15_000);
    })]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

function status(error: unknown): number | null {
  return error instanceof GovernedCommandError || error instanceof OperatorApiError ? error.status : null;
}

/**
 * Read Settings and the existing /iam projection independently, once per explicit load.
 * A PUT rechecks server-reported Owner and the captured context after token acquisition.
 * Conflicts require explicit refresh; no failure or timeout automatically retries a write.
 */
export function createAlertQualitySettingsSession(
  client: AlertQualitySettingsClient, auth: AuthContext, scope: string, subject: string | null,
  isCurrent: () => boolean, onState: (state: AlertQualitySettingsState) => void,
  memory: AlertQualitySettingsMemory = createAlertQualitySettingsMemory(),
): AlertQualitySettingsSession {
  let active = true;
  let readGeneration = 0;
  let saveGeneration = 0;
  let pending = false;
  let mayHaveSent = false;
  let settingsCurrent = false;
  let read: AsyncState<AlertQualitySettings> = { status: "loading" };
  let authority: AlertQualitySettingsAuthority = "loading";
  let command: AlertQualitySettingsCommand = "idle";
  const current = () => active && isCurrent() && isAlertQualityRef(scope) && subject !== null;
  const emit = () => {
    if (current()) onState({ read, authority, command, editable: settingsCurrent && !pending && authority === "owner"
      && memory.held(scope) === null && read.status === "ready" && read.data.enabled !== null
      && read.data.revision !== null && read.data.revision < Number.MAX_SAFE_INTEGER });
  };

  const authenticatedRead = async <T>(work: () => Promise<T>, valid: () => boolean): Promise<T> => {
    const header = await client.authorizationHeader();
    if (!valid() || header === null || !header.trim()) throw new SettingsRequestNotSent();
    return work();
  };

  const load = async (): Promise<void> => {
    if (!current() || pending) return;
    const generation = ++readGeneration;
    const valid = () => current() && generation === readGeneration;
    settingsCurrent = false;
    read = { status: "loading" };
    authority = memory.held(scope) === "denied" ? "denied" : "loading";
    command = memory.held(scope) ?? "idle";
    emit();
    await Promise.all([
      (async () => {
        let open = true;
        try {
          const raw = await bounded(authenticatedRead(
            () => client.panel<unknown>("/alert-quality/settings", { scope_ref: scope }), () => open && valid(),
          ));
          if (!valid()) return;
          read = { status: "ready", data: decodeAlertQualitySettings(raw, scope) };
          settingsCurrent = true;
        } catch (error) {
          if (!valid()) return;
          if (status(error) === 401 || status(error) === 403) {
            memory.hold(scope, "denied");
            command = "denied";
            authority = "denied";
          }
          read = isOptionalOperatorApiUnavailable(error)
            ? { status: "unavailable", message: text("settings.loadUnavailable") }
            : { status: "error", message: text("settings.loadFailed") };
        } finally {
          open = false;
          if (valid()) emit();
        }
      })(),
      (async () => {
        let open = true;
        try {
          const overview = await bounded(authenticatedRead(() => client.iamOverview(), () => open && valid()));
          if (!valid()) return;
          authority = alertQualitySettingsOwner(overview, subject) ? "owner" : "read-only";
        } catch {
          if (valid()) authority = "unavailable";
        } finally {
          open = false;
          if (valid()) {
            if (memory.held(scope) === "denied") authority = "denied";
            emit();
          }
        }
      })(),
    ]);
  };

  const save = async (enabled: boolean, expectedRevision: number): Promise<void> => {
    if (!current() || pending) return;
    const body = read.status === "ready" && settingsCurrent
      ? buildAlertQualitySettingsUpdate(read.data, scope, enabled, expectedRevision) : null;
    if (authority !== "owner" || memory.held(scope) !== null || body === null) {
      command = memory.held(scope) ?? "blocked";
      emit();
      return;
    }
    pending = true;
    mayHaveSent = false;
    settingsCurrent = false;
    readGeneration += 1;
    const generation = ++saveGeneration;
    const valid = () => current() && generation === saveGeneration;
    command = "pending";
    emit();
    try {
      const authorization = async (): Promise<string> => {
        if (!valid()) throw new SettingsRequestNotSent();
        const overview = await client.iamOverview();
        if (!valid()) throw new SettingsRequestNotSent();
        if (!alertQualitySettingsOwner(overview, subject)) {
          authority = "read-only";
          throw new SettingsRequestNotSent();
        }
        const header = await client.authorizationHeader();
        if (!valid() || authority !== "owner" || memory.held(scope) !== null || header === null || !header.trim()) {
          throw new SettingsRequestNotSent();
        }
        mayHaveSent = true;
        return header;
      };
      // Reuse the existing governed writer with a fenced token supplier. No identity/role enters JSON.
      const raw = await bounded(putGovernedJson({ ...auth, getAuthorizationHeader: authorization },
        client.operatorApiBaseUrl, "/alert-quality/settings", body));
      const receipt = decodeAlertQualitySettings(raw, scope);
      if (receipt.preference_state !== "recorded" || receipt.revision !== expectedRevision + 1 || receipt.enabled !== enabled) {
        throw new Error("Alert-quality preference receipt did not match the requested revision");
      }
      if (valid()) {
        read = { status: "ready", data: receipt };
        settingsCurrent = true;
        command = "saved";
      }
    } catch (error) {
      if (valid()) {
        const code = status(error);
        if (code === 401 || code === 403) {
          command = "denied";
          authority = "denied";
          memory.hold(scope, "denied");
        } else if (!mayHaveSent || error instanceof SettingsRequestNotSent) {
          command = "blocked";
          if (authority === "owner") authority = "unavailable";
        } else if (code === 409) command = "conflict";
        else if (code !== null && [400, 404, 410, 413, 415, 422, 428, 429].includes(code)) command = "rejected";
        else { command = "unknown"; memory.hold(scope, "unknown"); }
      }
    } finally {
      if (!valid() && mayHaveSent) memory.hold(scope, "unknown");
      if (generation === saveGeneration) {
        saveGeneration += 1; // A deadline must prevent a delayed token from starting the PUT.
        pending = false;
        emit();
      }
    }
  };

  return {
    load, save,
    requestsAllowed: () => current() && settingsCurrent && !pending && memory.held(scope) !== "unknown"
      && read.status === "ready" && read.data.available && read.data.enabled === true,
    dispose: () => {
      if (pending && mayHaveSent) memory.hold(scope, "unknown");
      active = false;
      settingsCurrent = false;
      readGeneration += 1;
      saveGeneration += 1;
    },
  };
}
