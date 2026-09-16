/** Operations alert quality: authorized scope selection and inert, single-axis proposals only. */
import { useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import type { OperatorApiClient } from "../api";
import { AsyncBoundary, PageHeader, UnavailableState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { currentRoute, navigate, routeHref } from "../router";
import {
  useAlertQualityIdentity, useAlertQualityReport, useAlertQualityScopes, useAlertQualitySettings, type AlertQualityIdentity,
} from "./alert-quality.controller";
import { AlertQualityProposalForm } from "./alert-quality.forms";
import { AlertQualityHistory } from "./alert-quality.history";
import { alertQualityRequestable, isAlertQualityRef } from "./alert-quality.model";
import {
  AlertQualityEvidence, AlertQualityFact as Fact, AlertQualityFacts as Facts, AlertQualityFindings,
  AlertQualityPlans, AlertQualityProvenance, AlertQualityRequestControls, alertQualityReason,
} from "./alert-quality.presentation";
import { selectAlertQualityScope, type AlertQualityScopes } from "./alert-quality.scopes";
import { AlertQualitySettingsPanel } from "./alert-quality.settings";
import { alertQualityText as text } from "./i18n/alert-quality";
import "./alert-quality.css";

// Keep existing route-local import surfaces compatible while separating responsibilities.
export { createAlertQualitySession, type AlertQualitySession, type AlertQualityCommandState } from "./alert-quality.requests";
export {
  AlertQualityEvidence, AlertQualityFindingTable, AlertQualityPlans, AlertQualityProvenance,
  CommandFeedback, alertQualityCount, alertQualityReason,
} from "./alert-quality.presentation";

/** Authentication and scope discovery precede every report read; Sample never acquires a token. */
export function AlertQualityRoute({ client, auth, dataMode }: {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly dataMode: ConsoleDataMode;
}) {
  const identity = useAlertQualityIdentity(client, auth, dataMode);
  const discovery = useAlertQualityScopes(identity);
  const search = currentRoute().search;
  const ruleValues = search.getAll("rule_ref");
  const invalidRule = ruleValues.length > 1 || (ruleValues.length === 1 && !isAlertQualityRef(ruleValues[0]));
  const rule = !invalidRule && ruleValues.length === 1 ? ruleValues[0]! : null;
  return <div class="alert-quality-route">
    <PageHeader title={text("title")} subtitle={text("subtitle")} />
    <aside class="alert-quality-boundary" aria-label={text("posture")}>
      <strong class="status-pill status-pill-shadow">{text("shadow")}</strong>
      <p>{text("postureBody")}</p>
    </aside>
    {dataMode !== "live" ? <UnavailableState message={text("liveOnly")} />
      : identity.principal === null ? <UnavailableState message={text("signInRequired")} />
        : <section class="alert-quality-scope-shell" aria-labelledby="alert-quality-scope-title">
          <div class="alert-quality-scope-header">
            <h3 id="alert-quality-scope-title">{text("authorizedScopes")}</h3>
            <button class="btn" type="button" disabled={discovery.state.status === "loading"}
              onClick={discovery.refresh} aria-describedby="alert-quality-scope-refresh-help">{text("refreshScopes")}</button>
          </div>
          <AsyncBoundary state={discovery.state} resourceLabel={text("authorizedScopes")}>
            {(scopes) => {
              const selected = selectAlertQualityScope(search, scopes);
              return <>
                <div class="alert-quality-scope-controls">
                  <AlertQualityScopePicker scopes={scopes} selected={selected.status === "selected" ? selected.scope : null}
                    onSelect={(scope) => {
                      if (identity.current() && identity.scopeCurrent(scopes) && scopes.scope_refs.includes(scope)) {
                        navigate(routeHref("alert-quality", { params: { scope_ref: scope } }));
                      }
                    }} />
                </div>
                <p id="alert-quality-scope-help" class="alert-quality-scope-help">{text("scopeHelp")}</p>
                <span id="alert-quality-scope-refresh-help" class="sr-only">{text("scopeRefreshHelp")}</span>
                {scopes.scope_refs.length === 0 ? <UnavailableState message={text("noScopes")} />
                  : selected.status !== "selected" ? <UnavailableState message={text(selected.status === "unauthorized" ? "scopeUnauthorized" : "scopeRequired")} />
                    : <ScopedAlertQuality key={selected.scope} identity={identity} scopes={scopes} scope={selected.scope} rule={rule} invalidRule={invalidRule} />}
              </>;
            }}
          </AsyncBoundary>
        </section>}
  </div>;
}

/** Choices are the exact server allowlist, not free text or browser-created provider scope. */
export function AlertQualityScopePicker({ scopes, selected, onSelect }: {
  readonly scopes: AlertQualityScopes; readonly selected: string | null; readonly onSelect: (scope: string) => void;
}) {
  return <div class="alert-quality-scope-picker">
    <label class="cs-control-field">
      <span class="cs-control-label">{text("scope")}</span>
      <select class="cs-control-select" name="scope_ref" value={selected ?? ""} disabled={scopes.scope_refs.length === 0}
        aria-describedby="alert-quality-scope-help"
        onChange={(event) => { if (scopes.scope_refs.includes(event.currentTarget.value)) onSelect(event.currentTarget.value); }}>
        <option value="" disabled={selected !== null}>{text("chooseScope")}</option>
        {scopes.scope_refs.map((scope) => <option key={scope} value={scope}>{scope}</option>)}
      </select>
    </label>
  </div>;
}

function ScopedAlertQuality({ identity, scopes, scope, rule, invalidRule }: {
  readonly identity: AlertQualityIdentity; readonly scopes: AlertQualityScopes;
  readonly scope: string; readonly rule: string | null; readonly invalidRule: boolean;
}) {
  const [periodSeconds, setPeriodSeconds] = useState(86400);
  const settings = useAlertQualitySettings(identity, scopes, scope);
  const report = useAlertQualityReport(identity, scopes, scope, settings.requestsAllowed);
  const { state, command, now } = report;
  const waiting = command === "pending";
  const preferenceHeld = !settings.requestsAllowed();
  const held = preferenceHeld || waiting || command === "unknown" || command === "rejected" || command === "blocked";
  const requestControls = <AlertQualityRequestControls state={state} command={command} onRefresh={report.refresh}
    periodSeconds={periodSeconds} onPeriodChange={setPeriodSeconds}
    onAssess={report.assess} onStop={report.stop} preferenceHeld={preferenceHeld} />;
  return <div class="alert-quality-content">
    <AsyncBoundary state={state} resourceLabel={text("title")}>
      {(data) => <>
        {data.assessment === null ? <section class="alert-quality-empty-report">
          <UnavailableState message={text("notPublished")} />
          {requestControls}
        </section> : <>
          <AlertQualityEvidence report={data.assessment} now={now} />
          <AlertQualityFindings key={`${data.assessment.evidence_digest}:${rule}:${invalidRule}`}
            report={data.assessment} rule={rule} invalidRule={invalidRule} />
        </>}
        <section class="alert-quality-section alert-quality-source" id="alert-quality-source"
          aria-labelledby="alert-quality-source-title">
          <header class="alert-quality-section-header">
            <div>
              <h3 id="alert-quality-source-title">{text("sourceAndAuthority")}</h3>
              <p>{text("sourceAndAuthorityHelp")}</p>
            </div>
          </header>
          {data.assessment === null ? null : <AlertQualityProvenance report={data.assessment} now={now} />}
          <Facts>
            <Fact label={text("scope")}>{scope}</Fact>
            <Fact label={text("runtime")}>{text(data.available ? "available" : "unavailable")}</Fact>
            <Fact label={text("preference")}>{text(data.enabled ? "enabled" : "disabled")}</Fact>
            <Fact label={text("requestable")}>{text(data.requestable === undefined ? "requestabilityMissing" : data.requestable ? "requestableYes" : "requestableNo")}</Fact>
            <Fact label={text("posture")}>{text("shadow")}</Fact>
          </Facts>
          {!alertQualityRequestable(data) ? <UnavailableState message={text("runtimeHold")} /> : null}
          {data.unavailable_reason !== null ? <p role="status">{text("reason")}: {alertQualityReason(data.unavailable_reason)}</p> : null}
        </section>
        {data.assessment === null ? null : <section class="alert-quality-section alert-quality-workspace"
          aria-labelledby="alert-quality-workspace-title">
          <header class="alert-quality-section-header">
            <div>
              <h3 id="alert-quality-workspace-title">{text("workspace")}</h3>
              <p>{text("workspaceHelp")}</p>
            </div>
          </header>
          {requestControls}
          <AlertQualityProposalForm key={data.assessment.evidence_digest}
            data={data} scope={scope} held={held || invalidRule} now={now} onSubmit={report.propose} />
          <AlertQualityPlans plans={data.plans} now={now} />
        </section>}
      </>}
    </AsyncBoundary>
    <AlertQualitySettingsPanel state={settings.state} isCurrent={settings.isCurrent} onRefresh={settings.refresh} onSave={settings.save} />
    <AlertQualityHistory identity={identity} scopes={scopes} scope={scope} onReconciled={report.refresh} />
  </div>;
}
