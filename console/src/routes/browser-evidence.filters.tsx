import { useState } from "preact/hooks";
import { DisclosurePanel } from "../components/disclosure-panel";
import { SearchInput, SelectField, TextInput } from "../components/form-controls";
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
      <SearchInput
        label={t("browserEvidence.filters.host")}
        value={host}
        placeholder={t("browserEvidence.filters.hostPlaceholder")}
        clearLabel={t("browserEvidence.filters.clear")}
        className="browser-evidence-host-filter"
        onInput={setHost}
      />
      <SelectField
        label={t("browserEvidence.filters.retention")}
        value={retention}
        options={[
          { value: "", label: t("browserEvidence.filters.allRetention") },
          ...(["retained", "expiring", "expired_pending_purge", "held"] as const).map((value) => ({
            value,
            label: t(`browserEvidence.retention.${value}`),
          })),
        ]}
        onChange={setRetention}
      />
      <SelectField
        label={t("browserEvidence.filters.finding")}
        value={finding}
        options={[
          { value: "", label: t("browserEvidence.filters.allFindings") },
          { value: "present", label: t("browserEvidence.filters.findingsPresent") },
          { value: "clear", label: t("browserEvidence.filters.findingsClear") },
        ]}
        onChange={setFinding}
      />
      <SelectField
        label={t("browserEvidence.filters.sort")}
        value={sort}
        options={[
          { value: "attention", label: t("browserEvidence.filters.attentionFirst") },
          { value: "newest", label: t("browserEvidence.filters.newestFirst") },
        ]}
        onChange={setSort}
      />
      <button type="submit" class="btn primary browser-evidence-apply">
        {t("browserEvidence.filters.apply")}
      </button>
      <DisclosurePanel
        {...{ title: t("browserEvidence.filters.more") }}
        className="browser-evidence-advanced"
        open={advancedOpen}
        tone="subtle"
      >
        <div class="browser-evidence-advanced-grid">
          <SelectField
            label={t("browserEvidence.filters.hostScope")}
            value={hostScope}
            disabled={!host}
            options={[
              { value: "either", label: t("browserEvidence.filters.hostEither") },
              { value: "requested", label: t("browserEvidence.filters.hostRequested") },
              { value: "final", label: t("browserEvidence.filters.hostFinal") },
            ]}
            onChange={(value) => setHostScope(value as BrowserEvidenceHostScope)}
          />
          <SearchInput
            label={t("browserEvidence.filters.artifact")}
            value={artifact}
            mono
            placeholder="sha256:"
            clearLabel={t("browserEvidence.filters.clear")}
            className="browser-evidence-wide-field"
            onInput={setArtifact}
          />
          <TextInput
            label={t("browserEvidence.filters.policy")}
            value={policy}
            onInput={setPolicy}
          />
          <TextInput
            type="number"
            label={t("browserEvidence.filters.policyVersion")}
            min={1}
            max={2147483647}
            value={policyVersion}
            disabled={!policy}
            onInput={setPolicyVersion}
          />
          <TextInput
            label={t("browserEvidence.filters.custody")}
            name="browser-evidence-custody"
            mono
            value={custody}
            className="browser-evidence-wide-field"
            onInput={setCustody}
          />
          <fieldset>
            <legend>{t("browserEvidence.filters.captureWindow")}</legend>
            <TextInput
              type="datetime-local"
              label={t("browserEvidence.filters.from")}
              value={capturedFrom}
              onInput={setCapturedFrom}
            />
            <TextInput
              type="datetime-local"
              label={t("browserEvidence.filters.before")}
              value={capturedBefore}
              onInput={setCapturedBefore}
            />
          </fieldset>
          <a href={routeHref("browser-evidence", {
            params: { locale: search.get("locale") },
          })}>
            {t("browserEvidence.filters.clear")}
          </a>
        </div>
      </DisclosurePanel>
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
