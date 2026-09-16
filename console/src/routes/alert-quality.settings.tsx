/** Scope-owned Settings presentation. An enabled preference cannot grant request or execution authority. */
import { useState } from "preact/hooks";
import { AsyncBoundary, LoadingState } from "../components/ui";
import { AlertQualityFact as Fact, AlertQualityFacts as Facts, AlertQualityTime as Time, alertQualityReason } from "./alert-quality.presentation";
import { buildAlertQualitySettingsUpdate, type AlertQualitySettings } from "./alert-quality.settings.model";
import type { AlertQualitySettingsState } from "./alert-quality.settings.requests";
import { alertQualityText as text } from "./i18n/alert-quality";

interface SettingsProps {
  readonly state: AlertQualitySettingsState;
  readonly isCurrent: () => boolean;
  readonly onRefresh: () => void;
  readonly onSave: (enabled: boolean, expectedRevision: number) => void;
}

/** Only the same exact read snapshot retains a draft; refresh, scope and identity changes retire it. */
export function AlertQualitySettingsPanel(props: SettingsProps) {
  const [draft, setDraft] = useState<{ snapshot: AlertQualitySettings; enabled: boolean } | null>(null);
  const snapshot = props.state.read.status === "ready" ? props.state.read.data : null;
  return <AlertQualitySettingsEditor {...props}
    value={snapshot !== null && draft?.snapshot === snapshot ? draft.enabled : snapshot?.enabled ?? null}
    onValue={(enabled) => { if (snapshot !== null && props.isCurrent()) setDraft({ snapshot, enabled }); }} />;
}

/** Pure controls expose source, prerequisites, preference revision and shadow authority separately. */
export function AlertQualitySettingsEditor({ state, isCurrent, onRefresh, onSave, value, onValue }: SettingsProps & {
  readonly value: boolean | null;
  readonly onValue: (enabled: boolean) => void;
}) {
  const data = state.read.status === "ready" ? state.read.data : null;
  const editable = state.editable && state.authority === "owner" && data !== null && isCurrent()
    && !["pending", "conflict", "denied", "rejected", "unknown"].includes(state.command);
  const body = data === null ? null : buildAlertQualitySettingsUpdate(data, data.scope_ref, value, data.revision);
  const read = state.read.status === "error" ? { ...state.read, message: text("settings.loadFailed") }
    : state.read.status === "unavailable" ? { ...state.read, message: text("settings.loadUnavailable") } : state.read;
  return <section class="alert-quality-section alert-quality-settings" aria-labelledby="alert-quality-settings-title">
    <div class="stack-section">
      <h3 id="alert-quality-settings-title">{text("settings.title")}</h3>
      <p id="alert-quality-settings-help" class="muted">{text("settings.help")}</p>
      <strong>{text("shadow")}</strong>
    </div>
    <div class="toolbar">
      <button type="button" class="btn" style={{ minHeight: 44 }} disabled={!isCurrent() || state.command === "pending" || state.read.status === "loading"}
        aria-describedby="alert-quality-settings-refresh-help" onClick={() => { if (isCurrent() && state.command !== "pending") onRefresh(); }}>{text("settings.refresh")}</button>
      <span id="alert-quality-settings-refresh-help" class="muted">{text("settings.refreshHelp")}</span>
    </div>
    <AsyncBoundary state={read} resourceLabel={text("settings.title")}>
      {(settings) => <div class="stack-section">
        <Facts>
          <Fact label={text("scope")}>{settings.scope_ref}</Fact>
          <Fact label={text("settings.available")}>{text(settings.available ? "available" : "unavailable")}</Fact>
          <Fact label={text("preference")}>{text(settings.enabled === null ? "unknown" : settings.enabled ? "enabled" : "disabled")}</Fact>
          <Fact label={text("posture")}>{text("shadow")}</Fact>
          <Fact label={text("settings.preferenceState")}>{text(`settings.state.${settings.preference_state}`)}</Fact>
          <Fact label={text("settings.revision")}>{settings.revision === null ? text("unknown") : String(settings.revision)}</Fact>
          <Fact label={text("settings.recordedAt")}>{settings.recorded_at === null ? text(settings.preference_state === "default" ? "settings.unsaved" : "settings.notRecorded") : <Time value={settings.recorded_at} />}</Fact>
        </Facts>
        <Facts>
          {(["source_bound", "writer_bound", "producer_ready", "preference_store_available"] as const).map((key) =>
            <Fact key={key} label={text(`settings.prerequisite.${key}`)}>{text(settings.prerequisites[key] ? "available" : "unavailable")}</Fact>)}
        </Facts>
        {settings.unavailable_reason !== null ? <p role="status">{alertQualityReason(settings.unavailable_reason)}</p> : null}
      </div>}
    </AsyncBoundary>
    {state.authority === "loading" ? <LoadingState label={text("settings.authority.loading")} />
      : <p id="alert-quality-settings-authority" class="muted">{text(`settings.authority.${state.authority}`)}</p>}
    <form class="stack-section" aria-label={text("settings.preferenceForm")} onSubmit={(event) => {
      event.preventDefault();
      if (editable && isCurrent() && body !== null) onSave(body.enabled, body.expected_revision);
    }}>
      <label style={{ minWidth: 0, maxWidth: 480, display: "grid", gap: 8 }} htmlFor="alert-quality-enabled">
        <span>{text("settings.preferenceForm")}</span>
        <select id="alert-quality-enabled" class="cs-control-select" name="enabled" required disabled={!editable}
          style={{ minHeight: 44, minWidth: 0, width: "100%" }} value={value === null ? "" : String(value)}
          aria-describedby="alert-quality-settings-help" onChange={(event) => {
            const selected = event.currentTarget.value;
            if (editable && isCurrent() && (selected === "true" || selected === "false")) onValue(selected === "true");
          }}>
          <option value="" disabled>{text("settings.preferenceUnknown")}</option>
          <option value="true">{text("enabled")}</option>
          <option value="false">{text("disabled")}</option>
        </select>
      </label>
      <button class="btn" type="submit" style={{ minHeight: 44, alignSelf: "start" }} disabled={!editable || body === null}
        aria-describedby="alert-quality-settings-help">{text("settings.save")}</button>
    </form>
    {state.command === "pending" ? <LoadingState label={text("settings.command.pending")} />
      : state.command !== "idle" ? <p role="status" aria-live="polite">{text(`settings.command.${state.command}`)}</p> : null}
  </section>;
}
