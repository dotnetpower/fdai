import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  decodeCostGovernanceSettings,
  type CostGovernanceSettings,
} from "../api-cost-governance";
import type { AuthContext } from "../auth";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import { routeHref } from "../router";
import { t } from "./i18n/cost-governance";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function CostGovernanceSettingsSection({ client, auth }: Props) {
  const [settings, setSettings] = useState<CostGovernanceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const generation = useRef(0);

  const load = async () => {
    const current = ++generation.current;
    setError(null);
    try {
      const next = await client.costGovernanceSettings();
      if (generation.current === current) setSettings(next);
    } catch (reason) {
      if (generation.current === current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
  };

  useEffect(() => {
    void load();
    return () => { generation.current += 1; };
  }, [client]);

  const update = async (enabled: boolean) => {
    if (
      settings === null
      || settings.activation_revision === null
      || !settings.available
      || !settings.can_manage
      || saving
    ) return;
    const current = ++generation.current;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await putGovernedJson(
        auth,
        client.operatorApiBaseUrl,
        "/cost-governance/settings",
        {
          enabled,
          expected_revision: settings.activation_revision,
          request_id: crypto.randomUUID(),
        },
      );
      if (generation.current === current) {
        setSettings(decodeCostGovernanceSettings(next));
        setNotice(enabled ? t("costGovernance.settings.enabled") : t("costGovernance.settings.disabled"));
      }
    } catch (reason) {
      if (reason instanceof GovernedCommandError && reason.status === 409) {
        try {
          const latest = await client.costGovernanceSettings();
          if (generation.current === current) {
            setSettings(latest);
            setError(t("costGovernance.settings.conflict"));
          }
        } catch (reloadReason) {
          if (generation.current === current) {
            setError(reloadReason instanceof Error ? reloadReason.message : String(reloadReason));
          }
        }
      } else if (generation.current === current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (generation.current === current) setSaving(false);
    }
  };

  return (
    <section class="settings-section settings-runtime-section">
      <h3>{t("costGovernance.settings.title")}</h3>
      <div class="settings-list">
        <div class="settings-row settings-runtime-row">
          <div class="settings-runtime-copy">
            <strong>{t("costGovernance.settings.activationLabel")}</strong>
            <small class="muted">{t("costGovernance.settings.activationHint")}</small>
            <span class="settings-runtime-meta">
              <span>{settings?.package_version
                ? t("costGovernance.settings.version", { version: settings.package_version })
                : t("costGovernance.settings.notInstalled")}</span>
              {settings?.availability_reasons.map((reason) => <span key={reason}>{reason}</span>)}
            </span>
          </div>
          <div class="settings-runtime-control">
            <label
              class="settings-toggle-control"
              aria-label={t("costGovernance.settings.activationLabel")}
            >
              <input
                type="checkbox"
                checked={settings?.enabled === true}
                disabled={
                  settings === null
                  || !settings.available
                  || !settings.can_manage
                  || saving
                }
                onChange={(event) => { void update(event.currentTarget.checked); }}
              />
              <span aria-hidden="true" />
            </label>
          </div>
        </div>
      </div>
      {settings && !settings.can_manage ? (
        <div class="state-block" role="note">{t("costGovernance.settings.ownerRequired")}</div>
      ) : null}
      {error ? <div class="error" role="alert">{error}</div> : null}
      {notice ? <div class="state-block state-success" role="status">{notice}</div> : null}
      <p>
        <a href={routeHref("cost-governance")}>{t("costGovernance.settings.openWorkspace")}</a>
      </p>
    </section>
  );
}
