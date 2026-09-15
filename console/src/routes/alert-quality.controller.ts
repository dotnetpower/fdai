/** Preact ownership fences for the authenticated route, discovery and selected report. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import type { AsyncState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import type { AlertQualityPayload } from "./alert-quality.model";
import type { AlertProposalDraft } from "./alert-quality.proposal";
import {
  createAlertQualityRequestMemory, createAlertQualityScopesSession, createAlertQualitySession,
  type AlertQualityCommandState, type AlertQualityScopesSession, type AlertQualitySession,
} from "./alert-quality.requests";
import { alertQualityPrincipal, type AlertQualityScopes } from "./alert-quality.scopes";
import {
  createAlertQualitySettingsMemory, createAlertQualitySettingsSession, type AlertQualitySettingsClient,
  type AlertQualitySettingsSession, type AlertQualitySettingsState,
} from "./alert-quality.settings.requests";
import { alertQualityText as text } from "./i18n/alert-quality";

/** Re-localize existing failures without a network retry or exposing dependency prose. */
export function alertQualityReadPresentation<T>(state: AsyncState<T>, source: "scopes" | "report"): AsyncState<T> {
  if (state.status === "unavailable") return { ...state, message: text(source === "scopes" ? "scopesUnavailable" : "loadUnavailable") };
  if (state.status === "error") return { ...state, message: text(source === "scopes" ? "scopesFailed" : "loadFailed") };
  return state;
}

/** A render-time identity switch withdraws old data before effect cleanup or delayed credentials. */
export function useAlertQualityIdentity(client: AlertQualitySettingsClient, auth: AuthContext, mode: ConsoleDataMode) {
  const principal = alertQualityPrincipal(auth, mode);
  const latest = useRef<object | null>(null);
  // A new client instance, auth context or Sample presentation must not clear an
  // unknown request for the same principal and Operator origin.
  const account = alertQualityPrincipal(auth, "live");
  const memory = useMemo(() => createAlertQualityRequestMemory(), [client.operatorApiBaseUrl, account]);
  const settingsMemory = useMemo(() => createAlertQualitySettingsMemory(), [client.operatorApiBaseUrl, account]);
  const identity = useMemo(() => {
    const token = {};
    let active = true;
    let scopeSnapshot: AlertQualityScopes | null = null;
    return {
      token, client, auth, principal, memory, settingsMemory, subject: auth.account?.localAccountId ?? null,
      current: () => active && latest.current === token && principal !== null
        && alertQualityPrincipal(auth, mode) === principal,
      scopeCurrent: (scopes: AlertQualityScopes) => scopeSnapshot === scopes,
      publishScopes: (scopes: AlertQualityScopes | null) => { scopeSnapshot = scopes; },
      dispose: () => { active = false; scopeSnapshot = null; },
    };
  }, [client, auth, mode, principal, memory, settingsMemory]);
  latest.current = identity.token;
  useLayoutEffect(() => () => identity.dispose(), [identity]);
  return identity;
}
export type AlertQualityIdentity = ReturnType<typeof useAlertQualityIdentity>;

/** No effect depends on a request result, so loading and failures cannot create a fetch loop. */
export function useAlertQualityScopes(identity: AlertQualityIdentity) {
  const [read, setRead] = useState<{ owner: AlertQualityIdentity; value: AsyncState<AlertQualityScopes> }>(
    { owner: identity, value: { status: "loading" } },
  );
  const session = useRef<AlertQualityScopesSession | null>(null);
  useLayoutEffect(() => {
    const owner = createAlertQualityScopesSession(identity.client, identity.current,
      (value) => {
        // Revoke the previous read fence synchronously, before Preact paints loading.
        identity.publishScopes(value.status === "ready" ? value.data : null);
        setRead({ owner: identity, value });
      });
    session.current = owner;
    void owner.load();
    return () => { owner.dispose(); if (session.current === owner) session.current = null; };
  }, [identity]);
  const state: AsyncState<AlertQualityScopes> = read.owner === identity && identity.current()
    ? read.value : { status: "loading" };
  return { state: alertQualityReadPresentation(state, "scopes"), refresh: () => { if (identity.current()) void session.current?.load(); } };
}

/** Settings and role reads are independent from report state; no result drives another fetch. */
export function useAlertQualitySettings(identity: AlertQualityIdentity, scopes: AlertQualityScopes, scope: string) {
  const binding = useMemo(() => ({ identity, scopes, scope }), [identity, scopes, scope]);
  const latest = useRef(binding);
  latest.current = binding;
  const empty: AlertQualitySettingsState = { read: { status: "loading" }, authority: "loading", command: "idle", editable: false };
  const [result, setResult] = useState<{ owner: typeof binding; value: AlertQualitySettingsState }>({ owner: binding, value: empty });
  const session = useRef<{ binding: typeof binding; owner: AlertQualitySettingsSession } | null>(null);
  const current = () => latest.current === binding && identity.current() && identity.scopeCurrent(scopes)
    && scopes.scope_refs.includes(scope);
  const requestsAllowed = useMemo(() => () => latest.current === binding && session.current?.binding === binding
    && session.current.owner.requestsAllowed(), [binding]);
  useLayoutEffect(() => {
    const owner = createAlertQualitySettingsSession(identity.client, identity.auth, scope, identity.subject, current,
      (value) => setResult({ owner: binding, value }), identity.settingsMemory);
    session.current = { binding, owner };
    void owner.load();
    return () => { owner.dispose(); if (session.current?.owner === owner) session.current = null; };
  }, [binding]);
  return {
    state: result.owner === binding && current() ? result.value : empty, isCurrent: current, requestsAllowed,
    refresh: () => { if (current() && session.current?.binding === binding) void session.current.owner.load(); },
    save: (enabled: boolean, revision: number) => {
      if (current() && session.current?.binding === binding) void session.current.owner.save(enabled, revision);
    },
  };
}

/** A scope-list refresh/revocation retires the selected report and every pending callback. */
export function useAlertQualityReport(identity: AlertQualityIdentity, scopes: AlertQualityScopes, scope: string, canRequest: () => boolean) {
  const binding = useMemo(() => ({ identity, scopes, scope, canRequest }), [identity, scopes, scope, canRequest]);
  const latest = useRef(binding);
  latest.current = binding;
  const [read, setRead] = useState<{ owner: typeof binding; value: AsyncState<AlertQualityPayload> }>(
    { owner: binding, value: { status: "loading" } },
  );
  const [result, setResult] = useState<{ owner: typeof binding; value: AlertQualityCommandState }>(
    { owner: binding, value: "idle" },
  );
  const [now, setNow] = useState(Date.now());
  const session = useRef<AlertQualitySession | null>(null);
  const current = () => latest.current === binding && identity.current()
    && identity.scopeCurrent(scopes) && scopes.scope_refs.includes(scope);
  useLayoutEffect(() => {
    const owner = createAlertQualitySession(identity.client, scope,
      (value) => { setNow(Date.now()); setRead({ owner: binding, value }); },
      (value) => setResult({ owner: binding, value }), current, identity.memory, canRequest);
    session.current = owner;
    void owner.load();
    return () => { owner.dispose(); if (session.current === owner) session.current = null; };
  }, [binding]);
  const state: AsyncState<AlertQualityPayload> = read.owner === binding && identity.current() && identity.scopeCurrent(scopes)
    ? read.value : { status: "loading" };
  const command = result.owner === binding && identity.current() ? result.value : "idle";
  useEffect(() => {
    // Resume updates the display clock only. It never polls or resends a request.
    const update = () => setNow(Date.now());
    globalThis.addEventListener?.("focus", update);
    return () => globalThis.removeEventListener?.("focus", update);
  }, []);
  useEffect(() => {
    if (state.status !== "ready") return;
    const report = state.data.assessment;
    const times = [
      ...(report === null ? [] : [report.observed_at, report.valid_until]),
      ...state.data.plans.flatMap((plan) => [plan.created_at, plan.expires_at]),
    ].map(Date.parse).filter((time) => time >= now);
    if (times.length === 0) return;
    const timer = setTimeout(() => setNow(Date.now()), Math.min(2_147_483_647, Math.max(1, Math.min(...times) - now + 1)));
    return () => clearTimeout(timer);
  }, [state, now]);
  return {
    state: alertQualityReadPresentation(state, "report"), command, now,
    refresh: () => { if (current()) void session.current?.load(); },
    assess: (periodSeconds?: number) => { if (current()) void session.current?.assess(periodSeconds); },
    propose: (draft: AlertProposalDraft) => { if (current()) void session.current?.propose(draft); },
    stop: () => { if (current()) session.current?.stopWaiting(); },
  };
}
