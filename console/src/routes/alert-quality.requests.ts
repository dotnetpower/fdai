/** Bounded read/request lifecycles; no polling, provider calls or approval authority. */
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import type { AsyncState } from "../components/ui";
import { GovernedCommandError, postGovernedJson } from "../governed-command";
import { alertQualityRequestable, decodeAlertQuality, isAlertQualityRef, type AlertQualityPayload } from "./alert-quality.model";
import { validateAlertProposal, type AlertProposalDraft } from "./alert-quality.proposal";
import { ALERT_MAX_SCOPES, decodeAlertQualityScopes, type AlertQualityScopes } from "./alert-quality.scopes";
import { alertQualityText as text } from "./i18n/alert-quality";

export type AlertClient = Pick<OperatorApiClient, "panel" | "authorizationHeader" | "operatorApiBaseUrl">;
export type AlertQualityCommandState = "idle" | "pending" | "submitted" | "rejected" | "unknown" | "blocked";

/** Unknown writes stay held across scope refresh/switch; overflow fails closed, never evicts a hold. */
export function createAlertQualityRequestMemory() {
  const uncertain = new Set<string>();
  const lastKeys = new Map<string, string>();
  let allHeld = false;
  return {
    isUnknown: (scope: string): boolean => allHeld || uncertain.has(scope),
    remember: (scope: string, key: string): void => {
      if (lastKeys.size >= ALERT_MAX_SCOPES && !lastKeys.has(scope)) allHeld = true;
      else lastKeys.set(scope, key);
    },
    uncertainKey: (scope: string): string | null => uncertain.has(scope) ? lastKeys.get(scope) ?? null : null,
    reconcile: (scope: string, key: string): boolean => {
      if (allHeld || !uncertain.has(scope) || lastKeys.get(scope) !== key) return false;
      uncertain.delete(scope);
      return true;
    },
    markUnknown: (scope: string): void => {
      if (uncertain.size >= ALERT_MAX_SCOPES && !uncertain.has(scope)) allHeld = true;
      else uncertain.add(scope);
    },
  };
}
export type AlertQualityRequestMemory = ReturnType<typeof createAlertQualityRequestMemory>;

/** One mounted, authorized scope owns these requests. Disposal never claims server cancellation. */
export interface AlertQualitySession {
  readonly load: () => Promise<void>;
  readonly assess: () => Promise<void>;
  readonly propose: (draft: AlertProposalDraft) => Promise<void>;
  readonly proposeRouting: (rule: string, remove: string, replacement: string) => Promise<void>;
  readonly stopWaiting: () => void;
  readonly dispose: () => void;
}
export interface AlertQualityScopesSession {
  readonly load: () => Promise<void>;
  readonly dispose: () => void;
}

class RequestNotSent extends Error {
  constructor() { super("Alert-quality request was not sent; authentication or context changed"); }
}

async function bounded<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("Alert-quality request deadline exceeded")), 15_000);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

/** Discover once per explicit load, only while the captured authenticated Live principal is current. */
export function createAlertQualityScopesSession(
  client: AlertClient,
  isCurrent: () => boolean,
  onRead: (state: AsyncState<AlertQualityScopes>) => void,
): AlertQualityScopesSession {
  let active = true;
  let generation = 0;
  return {
    load: async () => {
      if (!active || !isCurrent()) return;
      const request = ++generation;
      const current = () => active && request === generation && isCurrent();
      onRead({ status: "loading" });
      try {
        const raw = await bounded((async () => {
          const header = await client.authorizationHeader();
          if (!current() || header === null || header.trim().length === 0) throw new RequestNotSent();
          return client.panel<unknown>("/alert-quality/scopes");
        })());
        if (current()) onRead({ status: "ready", data: decodeAlertQualityScopes(raw) });
      } catch (error) {
        if (!current()) return;
        onRead(isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: text("scopesUnavailable") }
          : { status: "error", message: text("scopesFailed") });
      } finally {
        // A deadline also invalidates late authentication before it can start the GET.
        if (request === generation) generation += 1;
      }
    },
    dispose: () => { active = false; generation += 1; },
  };
}

/**
 * A caller-supplied fence must cover principal, client, selection and the latest scope discovery.
 * Revalidate after delayed authentication. An ambiguous POST is never resent or cleared by a GET.
 * canRequest is a separate current Settings veto; it cannot override report requestability.
 */
export function createAlertQualitySession(
  client: AlertClient,
  scope: string,
  onRead: (state: AsyncState<AlertQualityPayload>) => void,
  onCommand: (state: AlertQualityCommandState) => void,
  isCurrent: () => boolean,
  memory: AlertQualityRequestMemory = createAlertQualityRequestMemory(),
  canRequest: () => boolean = () => true,
): AlertQualitySession {
  let active = true;
  let readGeneration = 0;
  let commandGeneration = 0;
  let pending = false;
  let reading = false;
  let mayHaveSent = false;
  let data: AlertQualityPayload | null = null;
  const current = (): boolean => active && isCurrent() && isAlertQualityRef(scope);
  const requestable = (): boolean => current() && canRequest() && !reading && !memory.isUnknown(scope)
    && data !== null && alertQualityRequestable(data);

  const load = async (): Promise<void> => {
    if (!current() || pending) return;
    const generation = ++readGeneration;
    reading = true;
    data = null;
    onRead({ status: "loading" });
    onCommand(memory.isUnknown(scope) ? "unknown" : "idle");
    try {
      const raw = await bounded(client.panel<unknown>("/alert-quality", { scope_ref: scope }));
      if (!current() || generation !== readGeneration) return;
      data = decodeAlertQuality(raw, scope);
      onRead({ status: "ready", data });
    } catch (error) {
      if (!current() || generation !== readGeneration) return;
      onRead(isOptionalOperatorApiUnavailable(error)
        ? { status: "unavailable", message: text("loadUnavailable") }
        : { status: "error", message: text("loadFailed") });
    } finally {
      if (generation === readGeneration) reading = false;
    }
  };

  const send = async (
    path: "/alert-quality/assess" | "/alert-quality/proposals",
    makeBody: () => Record<string, unknown> | null,
  ): Promise<void> => {
    if (!current() || pending || memory.isUnknown(scope)) return;
    const body = requestable() ? makeBody() : null;
    if (body === null) { onCommand("blocked"); return; }
    pending = true;
    mayHaveSent = false;
    const generation = ++commandGeneration;
    onCommand("pending");
    let next: AlertQualityCommandState;
    try {
      const key = globalThis.crypto.randomUUID();
      memory.remember(scope, key);
      const authorization = async (): Promise<string> => {
        const header = await client.authorizationHeader();
        if (!current() || generation !== commandGeneration || !requestable() || header === null
          || header.trim().length === 0 || JSON.stringify(makeBody()) !== JSON.stringify(body)) {
          throw new RequestNotSent();
        }
        mayHaveSent = true;
        return header;
      };
      const receipt = await bounded(postGovernedJson(authorization, client.operatorApiBaseUrl, path, body, key));
      decodeAlertQuality(receipt, scope);
      next = "submitted";
    } catch (error) {
      next = !mayHaveSent || error instanceof RequestNotSent ? "blocked"
        : error instanceof GovernedCommandError && [400, 401, 403, 404, 409, 410, 413, 415, 422, 429].includes(error.status)
          ? "rejected" : "unknown";
    }
    if (!current() || generation !== commandGeneration) {
      if (mayHaveSent) memory.markUnknown(scope);
      return;
    }
    commandGeneration += 1;
    pending = false;
    if (next === "unknown") memory.markUnknown(scope);
    if (next !== "submitted") data = null;
    onCommand(next);
    if (next === "submitted") {
      const terminalGeneration = commandGeneration;
      await load();
      if (current() && commandGeneration === terminalGeneration && !pending && !memory.isUnknown(scope)) onCommand("submitted");
    }
  };

  const propose = (draft: AlertProposalDraft) => send("/alert-quality/proposals", () => data === null
    ? null : validateAlertProposal(data, scope, draft, Date.now()).body);
  return {
    load,
    assess: () => send("/alert-quality/assess", () => ({ scope_ref: scope })),
    propose,
    proposeRouting: (rule, remove, replacement) => propose({
      kind: "routing", target_ref: rule, remove_group_ref: remove, replacement_group_ref: replacement,
    }),
    stopWaiting: () => {
      if (!current() || !pending) return;
      commandGeneration += 1;
      pending = false;
      memory.markUnknown(scope);
      data = null;
      onCommand("unknown");
    },
    dispose: () => {
      if (pending && mayHaveSent) memory.markUnknown(scope);
      active = false;
      readGeneration += 1;
      commandGeneration += 1;
      data = null;
    },
  };
}
