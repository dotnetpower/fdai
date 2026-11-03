import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { ErrorState, KpiCard, KpiGrid, LoadingState, PageHeader, StatusPill } from "../components/ui";
import { useSettingsDirtyState } from "../components/settings-dirty-state";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import {
  RuntimeSettingsCommandError,
  saveRuntimeSettings,
} from "./settings-runtime.command";
import {
  decodeRuntimeSettings,
  initialRuntimeDraft,
  normalizeRuntimeSettingChanges,
  runtimeDraftError,
  runtimeNetChange,
  filterRuntimePolicies,
  type RuntimeSettingsView,
  type RuntimeSettingValue,
  type RuntimeSettingView,
} from "./settings-runtime.model";
import { CostGovernanceSettingsSection } from "./cost-governance-settings";
import { settingsIntegrationsText } from "./settings-integrations.i18n";
import { runtimeUxText } from "./settings-runtime.i18n";

export { parseRuntimeNumericInput } from "./settings-runtime.model";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function SettingsRuntimeRoute({ client, auth }: Props) {
  const [view, setView] = useState<RuntimeSettingsView | null>(null);
  const [draft, setDraft] = useState<Readonly<Record<string, RuntimeSettingValue>>>({});
  const [changes, setChanges] = useState<
    Readonly<Record<string, RuntimeSettingValue | null>>
  >({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [changedOnly, setChangedOnly] = useState(false);
  const [conflictView, setConflictView] = useState<RuntimeSettingsView | null>(null);
  const [needsConflictReview, setNeedsConflictReview] = useState(false);
  const generation = useRef(0);
  useSettingsDirtyState("settings-runtime", Object.keys(changes).length > 0);

  const applyView = (next: RuntimeSettingsView) => {
    setView(next);
    setDraft(initialRuntimeDraft(next));
    setChanges({});
    setConflictView(null);
    setNeedsConflictReview(false);
  };

  const fetchView = async (): Promise<RuntimeSettingsView> => {
    return decodeRuntimeSettings(await client.panel<unknown>("/runtime/settings"));
  };

  const load = async (preserveDraft = false) => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchView();
      if (generation.current === current) {
        if (preserveDraft) {
          setConflictView(next);
          setNeedsConflictReview(true);
        } else applyView(next);
      }
    } catch (reason) {
      if (generation.current === current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (generation.current === current) setLoading(false);
    }
  };

  useEffect(() => {
    setView(null);
    setDraft({});
    setChanges({});
    setSaving(false);
    setNotice(null);
    void load();
    return () => {
      generation.current += 1;
    };
  }, [client]);

  const updateDraft = (setting: RuntimeSettingView, value: RuntimeSettingValue) => {
    setNotice(null);
    setDraft((current) => ({ ...current, [setting.key]: value }));
    setChanges((current) => {
      const next = { ...current };
      const change = runtimeNetChange(setting, value);
      if (change === undefined) delete next[setting.key];
      else next[setting.key] = change;
      return next;
    });
  };

  const resetOverride = (setting: RuntimeSettingView) => {
    setNotice(null);
    setDraft((current) => ({ ...current, [setting.key]: setting.environmentValue }));
    setChanges((current) => {
      const next = { ...current };
      const change = runtimeNetChange(setting, null);
      if (change === undefined) delete next[setting.key];
      else next[setting.key] = change;
      return next;
    });
  };

  const save = async () => {
    if (view === null || !view.canManage || saving || needsConflictReview
      || Object.keys(changes).length === 0
      || view.settings.some((setting) => runtimeDraftError(setting, draft[setting.key] ?? setting.effectiveValue))) return;
    const current = ++generation.current;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await saveRuntimeSettings(
        auth,
        client.operatorApiBaseUrl,
        normalizeRuntimeSettingChanges(view, changes),
        view.revision,
      );
      if (generation.current === current) {
        applyView(next);
        setNotice(t("settings.runtimePolicies.saved"));
      }
    } catch (reason) {
      if (reason instanceof RuntimeSettingsCommandError && reason.status === 409) {
        if (generation.current !== current) return;
        setNeedsConflictReview(true);
        try {
          const latest = await fetchView();
          if (generation.current === current) {
            setConflictView(latest);
            setError(t("settings.runtimePolicies.conflict"));
          }
        } catch {
          if (generation.current === current) {
            setError(t("settings.runtimePolicies.conflictReloadFailed"));
          }
        }
      } else if (generation.current === current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (generation.current === current) setSaving(false);
    }
  };

  usePublishViewContext(
    () => ({
      routeId: "settings-runtime",
      routeLabel: t("route.settingsRuntime"),
      purpose: "Sanitized runtime policy values, durable overrides, and application timing.",
      glossary: composeGlossary([TERMS.mode, TERMS.humanRbac]),
      headline: view
        ? `${view.settings.length} allowlisted runtime policies at revision ${view.revision}`
        : "Runtime policies loading",
      capturedAt: new Date().toISOString(),
      facts: view?.settings.map((setting) => ({
        key: setting.key,
        value: typeof setting.effectiveValue === "object"
          ? "Structured policy; inspect the Settings editor for complete values."
          : setting.effectiveValue,
        group: setting.group,
      })) ?? [],
      records: {},
    }),
    [view],
  );

  const visibleSettings = filterRuntimePolicies(
    view?.settings ?? [], search, changedOnly, changes, (key) => runtimeSettingText(key, "label"),
  );
  const groups = view === null
    ? []
    : [...new Set(visibleSettings.map((setting) => setting.group))];
  const dirty = Object.keys(changes).length > 0;
  const invalid = view?.settings.some((setting) => runtimeDraftError(setting, draft[setting.key] ?? setting.effectiveValue)) ?? false;
  const canReapply = conflictView?.canManage && Object.keys(changes).every((key) =>
    conflictView.settings.some((setting) => setting.key === key && setting.available));
  const reapplyDraft = () => {
    if (!conflictView || !canReapply) return;
    const nextDraft = { ...initialRuntimeDraft(conflictView) };
    const nextChanges: Record<string, RuntimeSettingValue | null> = {};
    for (const setting of conflictView.settings) {
      if (!Object.hasOwn(changes, setting.key)) continue;
      const value = changes[setting.key] === null ? null : draft[setting.key]!;
      nextDraft[setting.key] = value === null ? setting.environmentValue : value;
      const change = runtimeNetChange(setting, value);
      if (change !== undefined) nextChanges[setting.key] = change;
    }
    setView(conflictView);
    setDraft(nextDraft);
    setChanges(nextChanges);
    setConflictView(null);
    setNeedsConflictReview(false);
    setError(null);
  };

  return (
    <div class="stack settings-route settings-runtime-route">
      <PageHeader
        title={t("route.settingsRuntime")}
        subtitle={t("settings.runtimePolicies.subtitle")}
        actions={view ? (
          <StatusPill
            kind="neutral"
            label={t("settings.runtimePolicies.revision", { revision: view.revision })}
          />
        ) : null}
      />
      {loading ? <LoadingState label={t("settings.runtimePolicies.loading")} /> : null}
      {error ? (
        <ErrorState
          message={error}
          onRetry={() => { void (needsConflictReview ? load(true) : view ? save() : load()); }}
          retryLabel={view && !needsConflictReview ? runtimeUxText("retrySave") : t("settings.retry")}
        />
      ) : null}
      {notice ? <div class="state-block state-success" role="status">{notice}</div> : null}
      {!loading && view ? (
        <>
          <section class="settings-runtime-boundary" aria-label={t("settings.runtimePolicies.boundaryLabel")}>
            <p>{t("settings.runtimePolicies.boundary")}</p>
            <small class="muted">
              {view.updatedAt && view.updatedBy
                ? t("settings.runtimePolicies.lastUpdated", {
                    actor: view.updatedBy,
                    time: formatConsoleTimestamp(view.updatedAt),
                  })
                : t("settings.runtimePolicies.neverUpdated")}
            </small>
          </section>
          <KpiGrid>
            <KpiCard evidenceState="measured" href="#settings-runtime-policies-list" label={t("route.settingsRuntime")} value={view.settings.length} />
            <KpiCard evidenceState="measured" href="#settings-runtime-policies-list" label="Overridden" value={view.settings.filter((item) => Boolean(item.overrideValue)).length} />
            <KpiCard evidenceState="measured" href="#settings-runtime-policies-list" label="Restart required" value={view.settings.filter((item) => item.restartRequired).length} />
            <KpiCard evidenceState="measured" href="#settings-runtime-policies-list" label="Unavailable" value={view.settings.filter((item) => !item.available).length} />
          </KpiGrid>
          {!view.canManage ? (
            <div class="state-block" role="note">{t("settings.runtimePolicies.readOnly")}</div>
          ) : null}
          <CostGovernanceSettingsSection client={client} auth={auth} />
          {conflictView ? <section class="state-block" aria-label={t("settings.runtimePolicies.conflict")}>
            <p>{runtimeUxText("conflictReview", { revision: conflictView.revision })}</p>
            <dl>{Object.keys(changes).map((key) => <div key={key}>
              <dt>{runtimeSettingText(key, "label")}</dt>
              <dd>{runtimeUxText("latest")}: {formatValue(conflictView.settings.find((setting) => setting.key === key)?.effectiveValue ?? "-")}</dd>
              <dd>{runtimeUxText("proposed")}: {changes[key] === null
                ? runtimeUxText("pendingReset", { value: formatValue(conflictView.settings.find((setting) => setting.key === key)?.environmentValue ?? "-") })
                : formatValue(draft[key]!)}</dd>
            </div>)}</dl>
            {!canReapply ? <p>{runtimeUxText("cannotReapply")}</p> : null}
            <button type="button" class="btn secondary" disabled={!canReapply || saving} onClick={reapplyDraft}>
              {runtimeUxText("reapply")}
            </button>
          </section> : null}
          <div id="settings-runtime-policies-list" class="settings-filter-bar">
            <label><span>{runtimeUxText("search")}</span><input type="search" class="form-input" value={search}
              onInput={(event) => setSearch(event.currentTarget.value)} /></label>
            <label><input type="checkbox" checked={changedOnly}
              onChange={(event) => setChangedOnly(event.currentTarget.checked)} /> {runtimeUxText("changedOnly")}</label>
            <button type="button" class="btn secondary" disabled={!search && !changedOnly}
              onClick={() => { setSearch(""); setChangedOnly(false); }}>{runtimeUxText("clearFilters")}</button>
          </div>
          <p role="status">{runtimeUxText("count", { shown: visibleSettings.length, total: view.settings.length })}</p>
          {invalid ? <p class="error-text" role="alert">{runtimeUxText("invalidBatch")}</p> : null}
          {visibleSettings.length === 0 ? <p class="state-block">
            {runtimeUxText(view.settings.length === 0 ? "empty" : "noMatches")}
          </p> : null}
          {groups.map((group) => (
            <section class="settings-section settings-runtime-section" key={group}>
              <h3>{group === "forecast"
                ? settingsIntegrationsText("forecastHistory.group")
                : t(`settings.runtimePolicies.groups.${group}`)}</h3>
              <div class="settings-list">
                {visibleSettings
                  .filter((setting) => setting.group === group)
                  .map((setting) => (
                    <RuntimeSettingRow
                      key={setting.key}
                      setting={setting}
                      value={draft[setting.key] ?? setting.effectiveValue}
                      changed={Object.hasOwn(changes, setting.key)}
                      resetPending={Object.hasOwn(changes, setting.key) && changes[setting.key] === null}
                      canManage={view.canManage}
                      saving={saving}
                      onChange={(value) => updateDraft(setting, value)}
                      onReset={() => resetOverride(setting)}
                    />
                  ))}
              </div>
            </section>
          ))}
          <div class="settings-actions settings-runtime-actions">
            <button type="button" class="btn secondary" disabled={saving || (!dirty && !needsConflictReview)}
              onClick={() => {
                if (needsConflictReview && conflictView === null) {
                  setDraft(initialRuntimeDraft(view));
                  setChanges({});
                  void load();
                } else applyView(conflictView ?? view);
                setError(null);
                setNotice(null);
              }}>
              {runtimeUxText("discard")}
            </button>
            <button
              type="button"
              class="btn primary"
              disabled={!view.canManage || !dirty || saving || invalid || needsConflictReview}
              onClick={() => { void save(); }}
            >
              {saving ? t("settings.runtimePolicies.saving") : t("settings.runtimePolicies.save")}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

function runtimeSettingText(key: string, part: "label" | "hint"): string {
  if (key === "detection.resource_availability") {
    const text = {
      en: {
        label: "Resource availability policy",
        hint: "Declare enabled, resource_types, and resources keyed by logical Resource identity. Each resource can declare expected_state and planned_stops with evidence references. Unknown expectations never imply an outage. This is observation-only and never authorizes a restart.",
      },
      ko: {
        label: "리소스 가용성 정책",
        hint: "enabled, resource_types와 논리 Resource 식별자를 키로 하는 resources를 선언합니다. 각 리소스에 expected_state와 근거 참조가 있는 planned_stops를 지정할 수 있습니다. 기대 상태를 모르면 장애로 판단하지 않습니다. 이 설정은 관측 전용이며 재시작 권한을 부여하지 않습니다.",
      },
    };
    return (getLocale() === "ko" ? text.ko[part] : text.en[part]) || text.en[part];
  }
  if (key === "forecast.history_collection.enabled") {
    return settingsIntegrationsText(part === "label"
      ? "forecastHistory.collectionLabel" : "forecastHistory.collectionHint");
  }
  if (key === "conversation.result_handles.enabled") {
    return settingsIntegrationsText(part === "label"
      ? "resultHandles.label" : "resultHandles.hint");
  }
  return t(`settings.runtimePolicies.fields.${key}.${part}`);
}

function RuntimeSettingRow({
  setting,
  value,
  changed,
  resetPending,
  canManage,
  saving,
  onChange,
  onReset,
}: {
  readonly setting: RuntimeSettingView;
  readonly value: RuntimeSettingValue;
  readonly changed: boolean;
  readonly resetPending: boolean;
  readonly canManage: boolean;
  readonly saving: boolean;
  readonly onChange: (value: RuntimeSettingValue) => void;
  readonly onReset: () => void;
}) {
  const disabled = !canManage || !setting.available || saving;
  const hasOverride = setting.overrideValue !== null || changed;
  const fieldError = runtimeDraftError(setting, value);
  const errorId = `runtime-error-${encodeURIComponent(setting.key)}`;
  const reasonId = `${errorId}-reason`;
  return (
    <div class="settings-row settings-runtime-row" data-value-type={setting.valueType}>
      <div class="settings-runtime-copy">
        <strong>{runtimeSettingText(setting.key, "label")}</strong>
        <small class="muted">{runtimeSettingText(setting.key, "hint")}</small>
        <span class="settings-runtime-meta">
          <span>
            {t("settings.runtimePolicies.environment")}: {formatValue(setting.environmentValue)}
          </span>
          {changed ? <p class="settings-runtime-pending">{runtimeUxText(resetPending ? "pendingReset" : "pending", {
            value: formatValue(resetPending ? setting.environmentValue : value),
          })}</p> : null}
          {!setting.available ? <p id={reasonId}>{setting.unavailableReason ?? runtimeUxText("unavailableReason")}</p> : null}
          <span>
            {t("settings.runtimePolicies.effective")}: {formatValue(setting.effectiveValue)}
          </span>
          <span>
            {t("settings.runtimePolicies.source")}: {setting.overrideValue === null
              ? t("settings.runtimePolicies.sourceEnvironment")
              : t("settings.runtimePolicies.sourceOverride")}
          </span>
        </span>
      </div>
      <div class="settings-runtime-control">
        <span class="settings-runtime-flags">
          {setting.restartRequired ? (
            <StatusPill kind="neutral" label={t("settings.runtimePolicies.restartRequired")} />
          ) : null}
          {!setting.available ? (
            <StatusPill kind="warning" label={t("settings.runtimePolicies.unavailable")} />
          ) : null}
        </span>
        <SettingControl
          setting={setting}
          value={value}
          disabled={disabled}
          invalid={fieldError !== null}
          describedBy={fieldError ? errorId : !setting.available ? reasonId : undefined}
          onChange={onChange}
        />
        {fieldError ? <p class="error-text" id={errorId} role="alert">
          {fieldError === "object" ? runtimeUxText("objectError") : runtimeUxText("numericError", {
            type: runtimeUxText(setting.valueType === "integer" ? "integer" : "number"),
            min: setting.minimum ?? runtimeUxText("unbounded"), max: setting.maximum ?? runtimeUxText("unbounded"),
          })}
        </p> : null}
        <button
          type="button"
          class="btn subtle settings-runtime-reset"
          disabled={disabled || !hasOverride}
          onClick={onReset}
        >
          {t("settings.runtimePolicies.reset")}
        </button>
      </div>
    </div>
  );
}

function SettingControl({
  setting,
  value,
  disabled,
  onChange,
  invalid,
  describedBy,
}: {
  readonly setting: RuntimeSettingView;
  readonly value: RuntimeSettingValue;
  readonly disabled: boolean;
  readonly onChange: (value: RuntimeSettingValue) => void;
  readonly invalid: boolean;
  readonly describedBy: string | undefined;
}) {
  const label = runtimeSettingText(setting.key, "label");
  if (setting.valueType === "object") {
    return (
      <textarea
        aria-label={label}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        rows={10}
        value={typeof value === "string" ? value : JSON.stringify(value, null, 2)}
        disabled={disabled}
        spellcheck={false}
        onInput={(event) => onChange(event.currentTarget.value)}
      />
    );
  }
  if (setting.valueType === "boolean") {
    return (
      <label class="settings-toggle-control" aria-label={label}>
        <input
          type="checkbox"
          aria-label={label}
          aria-describedby={describedBy}
          checked={value === true}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.checked)}
        />
        <span aria-hidden="true" />
      </label>
    );
  }
  if (setting.valueType === "enum") {
    return (
      <select
        aria-label={label}
        aria-describedby={describedBy}
        value={String(value)}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        {setting.options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    );
  }
  return (
    <input
      type="number"
      aria-label={label}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      value={String(value)}
      min={setting.minimum ?? undefined}
      max={setting.maximum ?? undefined}
      step={setting.valueType === "integer" ? 1 : "any"}
      disabled={disabled}
      onInput={(event) => onChange(event.currentTarget.value)}
    />
  );
}

function formatValue(value: RuntimeSettingValue): string {
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") {
    return value ? t("settings.enabled") : t("settings.disabled");
  }
  return String(value);
}
