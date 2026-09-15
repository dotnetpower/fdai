/** Operations alert quality: authorized scope selection and inert, single-axis proposals only. */
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
  AlertQualityPlans, AlertQualityRequestControls, alertQualityReason,
} from "./alert-quality.presentation";
import { selectAlertQualityScope, type AlertQualityScopes } from "./alert-quality.scopes";
import { AlertQualitySettingsPanel } from "./alert-quality.settings";
import { alertQualityText as text } from "./i18n/alert-quality";

// Keep existing route-local import surfaces compatible while separating responsibilities.
export { createAlertQualitySession, type AlertQualitySession, type AlertQualityCommandState } from "./alert-quality.requests";
export { AlertQualityEvidence, AlertQualityFindingTable, AlertQualityPlans, CommandFeedback, alertQualityCount, alertQualityReason } from "./alert-quality.presentation";

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
  return <div class="stack" style={{ minWidth: 0, overflowWrap: "anywhere", gap: 40 }}>
    <PageHeader title={text("title")} subtitle={text("subtitle")} />
    <section class="stack-section" aria-label={text("posture")}>
      <strong>{text("shadow")}</strong><p class="muted">{text("postureBody")}</p>
    </section>
    {dataMode !== "live" ? <UnavailableState message={text("liveOnly")} />
      : identity.principal === null ? <UnavailableState message={text("signInRequired")} />
        : <section class="stack" style={{ minWidth: 0, gap: 40 }}>
          <div class="toolbar">
            <button class="btn" type="button" style={{ minHeight: 44 }} disabled={discovery.state.status === "loading"}
              aria-describedby="alert-quality-scope-refresh-help" onClick={discovery.refresh}>{text("refreshScopes")}</button>
            <span id="alert-quality-scope-refresh-help" class="muted">{text("scopeRefreshHelp")}</span>
          </div>
          <AsyncBoundary state={discovery.state} resourceLabel={text("authorizedScopes")}>
            {(scopes) => {
              const selected = selectAlertQualityScope(search, scopes);
              return <>
                <AlertQualityScopePicker scopes={scopes} selected={selected.status === "selected" ? selected.scope : null}
                  onSelect={(scope) => {
                    if (identity.current() && identity.scopeCurrent(scopes) && scopes.scope_refs.includes(scope)) {
                      navigate(routeHref("alert-quality", { params: { scope_ref: scope } }));
                    }
                  }} />
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
  return <section class="stack-section" aria-label={text("authorizedScopes")}>
    <label style={{ minWidth: 0, display: "grid", gap: 8 }}>
      <span>{text("scope")}</span>
      <select class="cs-control-select" name="scope_ref" value={selected ?? ""} disabled={scopes.scope_refs.length === 0}
        style={{ minWidth: 0, minHeight: 44, width: "100%" }} aria-describedby="alert-quality-scope-help"
        onChange={(event) => { if (scopes.scope_refs.includes(event.currentTarget.value)) onSelect(event.currentTarget.value); }}>
        <option value="" disabled={selected !== null}>{text("chooseScope")}</option>
        {scopes.scope_refs.map((scope) => <option key={scope} value={scope}>{scope}</option>)}
      </select>
    </label>
    <p id="alert-quality-scope-help" class="muted">{text("scopeHelp")}</p>
  </section>;
}

function ScopedAlertQuality({ identity, scopes, scope, rule, invalidRule }: {
  readonly identity: AlertQualityIdentity; readonly scopes: AlertQualityScopes;
  readonly scope: string; readonly rule: string | null; readonly invalidRule: boolean;
}) {
  const settings = useAlertQualitySettings(identity, scopes, scope);
  const report = useAlertQualityReport(identity, scopes, scope, settings.requestsAllowed);
  const { state, command, now } = report;
  const waiting = command === "pending";
  const preferenceHeld = !settings.requestsAllowed();
  const held = preferenceHeld || waiting || command === "unknown" || command === "rejected" || command === "blocked";
  return <>
    <AlertQualitySettingsPanel state={settings.state} isCurrent={settings.isCurrent} onRefresh={settings.refresh} onSave={settings.save} />
    <AlertQualityRequestControls state={state} command={command} onRefresh={report.refresh}
      onAssess={report.assess} onStop={report.stop} preferenceHeld={preferenceHeld} />
    <AsyncBoundary state={state} resourceLabel={text("title")}>
      {(data) => <div class="stack" style={{ minWidth: 0, gap: 40 }}>
        <section class="stack-section" aria-label={text("runtime")}>
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
        {data.assessment === null ? <UnavailableState message={text("notPublished")} /> : <>
          <AlertQualityEvidence report={data.assessment} now={now} />
          <AlertQualityFindings key={`${data.assessment.evidence_digest}:${rule}:${invalidRule}`}
            report={data.assessment} rule={rule} invalidRule={invalidRule} />
        </>}
        <AlertQualityProposalForm key={data.assessment?.evidence_digest ?? "no-assessment"}
          data={data} scope={scope} held={held || invalidRule} now={now} onSubmit={report.propose} />
        <AlertQualityPlans plans={data.plans} now={now} />
      </div>}
    </AsyncBoundary>
    <AlertQualityHistory identity={identity} scopes={scopes} scope={scope} onReconciled={report.refresh} />
  </>;
}
