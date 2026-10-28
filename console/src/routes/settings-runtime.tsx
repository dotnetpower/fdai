import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { ErrorState, LoadingState, PageHeader, StatusPill } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import {
  RuntimeSettingsCommandError,
  saveRuntimeSettings,
} from "./settings-runtime.command";
import {
  decodeRuntimeSettings,
  initialRuntimeDraft,
  normalizeRuntimeSettingChanges,
  type RuntimeSettingsView,
  type RuntimeSettingValue,
  type RuntimeSettingView,
} from "./settings-runtime.model";
import { CostGovernanceSettingsSection } from "./cost-governance-settings";
import { settingsIntegrationsText } from "./settings-integrations.i18n";

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
  const generation = useRef(0);

  const applyView = (next: RuntimeSettingsView) => {
    setView(next);
    setDraft(initialRuntimeDraft(next));
    setChanges({});
  };

  const fetchView = async (): Promise<RuntimeSettingsView> => {
    return decodeRuntimeSettings(await client.panel<unknown>("/runtime/settings"));
  };

  const load = async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchView();
      if (generation.current === current) applyView(next);
    } catch (reason) {
      if (generation.current === current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (generation.current === current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
    };
  }, [client]);

  const updateDraft = (setting: RuntimeSettingView, value: RuntimeSettingValue) => {
    setNotice(null);
    setDraft((current) => ({ ...current, [setting.key]: value }));
    setChanges((current) => ({ ...current, [setting.key]: value }));
  };

  const resetOverride = (setting: RuntimeSettingView) => {
    setNotice(null);
    setDraft((current) => ({ ...current, [setting.key]: setting.environmentValue }));
    setChanges((current) => ({ ...current, [setting.key]: null }));
  };

  const save = async () => {
    if (view === null || !view.canManage || saving || Object.keys(changes).length === 0) return;
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
        try {
          const latest = await fetchView();
          if (generation.current === current) {
            applyView(latest);
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

  const groups = view === null
    ? []
    : [...new Set(view.settings.map((setting) => setting.group))];
  const dirty = Object.keys(changes).length > 0;

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
          onRetry={() => { void load(); }}
          retryLabel={t("settings.retry")}
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
                    time: new Date(view.updatedAt).toLocaleString(),
                  })
                : t("settings.runtimePolicies.neverUpdated")}
            </small>
          </section>
          {!view.canManage ? (
            <div class="state-block" role="note">{t("settings.runtimePolicies.readOnly")}</div>
          ) : null}
          <CostGovernanceSettingsSection client={client} auth={auth} />
          {groups.map((group) => (
            <section class="settings-section settings-runtime-section" key={group}>
              <h3>{group === "forecast"
                ? settingsIntegrationsText("forecastHistory.group")
                : t(`settings.runtimePolicies.groups.${group}`)}</h3>
              <div class="settings-list">
                {view.settings
                  .filter((setting) => setting.group === group)
                  .map((setting) => (
                    <RuntimeSettingRow
                      key={setting.key}
                      setting={setting}
                      value={draft[setting.key] ?? setting.effectiveValue}
                      changed={Object.hasOwn(changes, setting.key)}
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
            <button
              type="button"
              class="btn primary"
              disabled={!view.canManage || !dirty || saving}
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
  canManage,
  saving,
  onChange,
  onReset,
}: {
  readonly setting: RuntimeSettingView;
  readonly value: RuntimeSettingValue;
  readonly changed: boolean;
  readonly canManage: boolean;
  readonly saving: boolean;
  readonly onChange: (value: RuntimeSettingValue) => void;
  readonly onReset: () => void;
}) {
  const disabled = !canManage || !setting.available || saving;
  const hasOverride = setting.overrideValue !== null || changed;
  return (
    <div class="settings-row settings-runtime-row" data-value-type={setting.valueType}>
      <div class="settings-runtime-copy">
        <strong>{runtimeSettingText(setting.key, "label")}</strong>
        <small class="muted">{runtimeSettingText(setting.key, "hint")}</small>
        <span class="settings-runtime-meta">
          <span>
            {t("settings.runtimePolicies.environment")}: {formatValue(setting.environmentValue)}
          </span>
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
          onChange={onChange}
        />
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
}: {
  readonly setting: RuntimeSettingView;
  readonly value: RuntimeSettingValue;
  readonly disabled: boolean;
  readonly onChange: (value: RuntimeSettingValue) => void;
}) {
  const label = runtimeSettingText(setting.key, "label");
  if (setting.valueType === "object") {
    return (
      <textarea
        aria-label={label}
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
      value={String(value)}
      min={setting.minimum ?? undefined}
      max={setting.maximum ?? undefined}
      step={setting.valueType === "integer" ? 1 : "any"}
      disabled={disabled}
      onInput={(event) => onChange(Number(event.currentTarget.value))}
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
