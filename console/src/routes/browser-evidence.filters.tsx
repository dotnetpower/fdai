import { useState } from "preact/hooks";
import { navigate, routeHref } from "../router";
import type { BrowserEvidenceHostScope } from "./browser-evidence.model";
import { t } from "./i18n/browser-evidence";

export function BrowserEvidenceFilters({ search }: { readonly search: URLSearchParams }) {
  const [host, setHost] = useState(search.get("host") ?? "");
  const [hostScope, setHostScope] = useState<BrowserEvidenceHostScope>(
    filterEnum<BrowserEvidenceHostScope>(
      search.get("host_scope"),
      ["requested", "final", "either"],
      "either",
    ),
  );
  const [artifact, setArtifact] = useState(search.get("artifact") ?? "");
  const [policy, setPolicy] = useState(search.get("policy") ?? "");
  const [policyVersion, setPolicyVersion] = useState(search.get("policy_version") ?? "");
  const [retention, setRetention] = useState(search.get("retention") ?? "");
  const [finding, setFinding] = useState(search.get("finding") ?? "");
  const [custody, setCustody] = useState(search.get("custody") ?? "");
  const [sort, setSort] = useState(search.get("sort") ?? "attention");
  const [capturedFrom, setCapturedFrom] = useState(
    isoToLocalInput(search.get("from")),
  );
  const [capturedBefore, setCapturedBefore] = useState(
    isoToLocalInput(search.get("before")),
  );
  const advancedOpen = Boolean(
    artifact || policy || policyVersion || custody || capturedFrom || capturedBefore,
  );
  return (
    <form
      class="browser-evidence-filters"
      aria-label={t("browserEvidence.filters.label")}
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault();
        navigate(routeHref("browser-evidence", {
          params: {
            locale: search.get("locale"),
            host,
            host_scope: host ? hostScope : null,
            artifact,
            policy,
            policy_version: policyVersion,
            retention,
            finding,
            custody,
            sort: sort === "attention" ? null : sort,
            from: localInputToIso(capturedFrom),
            before: localInputToIso(capturedBefore),
          },
        }));
      }}
    >
      <label class="browser-evidence-host-filter">
        <span>{t("browserEvidence.filters.host")}</span>
        <input
          type="search"
          name="browser-evidence-host"
          value={host}
          placeholder={t("browserEvidence.filters.hostPlaceholder")}
          onInput={(event) => setHost(event.currentTarget.value)}
        />
      </label>
      <label>
        <span>{t("browserEvidence.filters.retention")}</span>
        <select
          value={retention}
          onChange={(event) => setRetention(event.currentTarget.value)}
        >
          <option value="">{t("browserEvidence.filters.allRetention")}</option>
          {(["retained", "expiring", "expired_pending_purge", "held"] as const)
            .map((value) => (
              <option key={value} value={value}>
                {t(`browserEvidence.retention.${value}`)}
              </option>
            ))}
        </select>
      </label>
      <label>
        <span>{t("browserEvidence.filters.finding")}</span>
        <select
          value={finding}
          onChange={(event) => setFinding(event.currentTarget.value)}
        >
          <option value="">{t("browserEvidence.filters.allFindings")}</option>
          <option value="present">{t("browserEvidence.filters.findingsPresent")}</option>
          <option value="clear">{t("browserEvidence.filters.findingsClear")}</option>
        </select>
      </label>
      <label>
        <span>{t("browserEvidence.filters.sort")}</span>
        <select value={sort} onChange={(event) => setSort(event.currentTarget.value)}>
          <option value="attention">{t("browserEvidence.filters.attentionFirst")}</option>
          <option value="newest">{t("browserEvidence.filters.newestFirst")}</option>
        </select>
      </label>
      <button type="submit" class="btn primary browser-evidence-apply">
        {t("browserEvidence.filters.apply")}
      </button>
      <details class="browser-evidence-advanced" open={advancedOpen}>
        <summary>{t("browserEvidence.filters.more")}</summary>
        <div>
          <label>
            <span>{t("browserEvidence.filters.hostScope")}</span>
            <select
              value={hostScope}
              disabled={!host}
              onChange={(event) => setHostScope(
                event.currentTarget.value as BrowserEvidenceHostScope,
              )}
            >
              <option value="either">{t("browserEvidence.filters.hostEither")}</option>
              <option value="requested">{t("browserEvidence.filters.hostRequested")}</option>
              <option value="final">{t("browserEvidence.filters.hostFinal")}</option>
            </select>
          </label>
          <label>
            <span>{t("browserEvidence.filters.artifact")}</span>
            <input
              type="search"
              class="mono"
              name="browser-evidence-artifact"
              value={artifact}
              placeholder="sha256:"
              onInput={(event) => setArtifact(event.currentTarget.value)}
            />
          </label>
          <label>
            <span>{t("browserEvidence.filters.policy")}</span>
            <input
              value={policy}
              onInput={(event) => setPolicy(event.currentTarget.value)}
            />
          </label>
          <label>
            <span>{t("browserEvidence.filters.policyVersion")}</span>
            <input
              type="number"
              min="1"
              max="2147483647"
              value={policyVersion}
              disabled={!policy}
              onInput={(event) => setPolicyVersion(event.currentTarget.value)}
            />
          </label>
          <label>
            <span>{t("browserEvidence.filters.custody")}</span>
            <input
              class="mono"
              name="browser-evidence-custody"
              value={custody}
              onInput={(event) => setCustody(event.currentTarget.value)}
            />
          </label>
          <fieldset>
            <legend>{t("browserEvidence.filters.captureWindow")}</legend>
            <label>
              <span>{t("browserEvidence.filters.from")}</span>
              <input
                type="datetime-local"
                value={capturedFrom}
                onInput={(event) => setCapturedFrom(event.currentTarget.value)}
              />
            </label>
            <label>
              <span>{t("browserEvidence.filters.before")}</span>
              <input
                type="datetime-local"
                value={capturedBefore}
                onInput={(event) => setCapturedBefore(event.currentTarget.value)}
              />
            </label>
          </fieldset>
          <a href={routeHref("browser-evidence", {
            params: { locale: search.get("locale") },
          })}>
            {t("browserEvidence.filters.clear")}
          </a>
        </div>
      </details>
    </form>
  );
}

function isoToLocalInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function localInputToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function filterEnum<T extends string>(
  value: string | null,
  allowed: readonly T[],
  fallback: T,
): T {
  return value !== null && allowed.includes(value as T) ? value as T : fallback;
}
