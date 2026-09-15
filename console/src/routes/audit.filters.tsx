import { useEffect, useState } from "preact/hooks";
import { currentRoute, navigate, routeHref } from "../router";
import { presentationLabel, t } from "./i18n/evidence";

const FILTER_KEYS = [
  "correlation", "mode", "tier", "action", "outcome", "vertical",
  "window", "from_seq", "through_seq", "entry", "q",
] as const;

/** Query controls preserve deep-link bounds and filters not edited by the operator. */
export function AuditQueryControls({ search }: { readonly search: string }) {
  const [draft, setDraft] = useState(() => new URLSearchParams(search));
  useEffect(() => setDraft(new URLSearchParams(search)), [search]);
  const set = (key: string, value: string) => setDraft((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    return next;
  });
  const choices = (key: string, values: readonly [string, string][]) => {
    const value = draft.get(key) ?? "";
    return (
      <select value={value} onChange={(event) => set(key, event.currentTarget.value)}>
        {values.some(([option]) => option === value) ? null : <option value={value}>{value}</option>}
        {values.map(([option, label]) => <option key={option} value={option}>{label}</option>)}
      </select>
    );
  };
  const active = new URLSearchParams(search);
  return (
    <form class="audit-query" aria-label={t("evidence.audit.activeFilters")} onSubmit={(event) => {
      event.preventDefault();
      navigate(routeHref("audit", { params: Object.fromEntries(draft) }));
    }}>
      <div class="audit-query-main">
        <label>
          <span>{t("evidence.audit.workspace.searchLedger")}</span>
          <input type="search" maxLength={200} value={draft.get("q") ?? ""}
            placeholder={t("evidence.audit.workspace.searchPlaceholder")}
            aria-describedby="audit-search-scope"
            onInput={(event) => set("q", event.currentTarget.value)} />
        </label>
        <label>
          <span>{t("evidence.audit.workspace.decisionFilter")}</span>
          {choices("outcome", [
            ["", t("evidence.audit.workspace.allDecisions")],
            ...["auto", "hil", "abstain", "deny"].map(
              (value): [string, string] => [value, presentationLabel("status", value)],
            ),
          ])}
        </label>
        <label>
          <span>{t("evidence.audit.filter.window")}</span>
          {choices("window", [
            ["", t("evidence.audit.workspace.allTime")],
            ["1d", t("evidence.audit.workspace.day")],
            ["7d", t("evidence.audit.workspace.week")],
            ["30d", t("evidence.audit.workspace.month")],
          ])}
        </label>
        <button type="submit" class="primary">{t("evidence.audit.workspace.apply")}</button>
      </div>
      <p id="audit-search-scope" class="audit-query-hint">{t("evidence.audit.workspace.searchScope")}</p>
      <details class="audit-query-more">
        <summary>{t("evidence.audit.workspace.moreFilters")}</summary>
        <div>
          <label>
            <span>{t("evidence.audit.workspace.correlation")}</span>
            <input value={draft.get("correlation") ?? ""} maxLength={256}
              placeholder={t("evidence.audit.workspace.queryPlaceholder")}
              onInput={(event) => set("correlation", event.currentTarget.value)} />
          </label>
          <label>
            <span>{t("evidence.audit.filter.mode")}</span>
            {choices("mode", [
              ["", t("evidence.audit.workspace.allModes")],
              ["shadow", presentationLabel("status", "shadow")],
              ["enforce", presentationLabel("status", "enforce")],
            ])}
          </label>
          <button type="button" onClick={() => {
            const params = new URLSearchParams(currentRoute().search);
            for (const key of FILTER_KEYS) params.delete(key);
            navigate(routeHref("audit", { params: Object.fromEntries(params) }));
          }}>{t("evidence.audit.workspace.clear")}</button>
        </div>
      </details>
      {FILTER_KEYS.some((key) => active.has(key)) ? (
        <div class="audit-active-filters">
          {FILTER_KEYS.filter((key) => active.has(key)).map((key) => (
            <span key={key}>
              {key === "correlation" ? t("evidence.audit.workspace.correlation")
                : key === "q" ? t("evidence.audit.workspace.searchLedger")
                : key === "entry" ? "#"
                : t(`evidence.audit.filter.${key === "from_seq" ? "fromSeq" : key === "through_seq" ? "throughSeq" : key}`)}
              : <strong>{active.get(key)}</strong>
            </span>
          ))}
        </div>
      ) : null}
    </form>
  );
}
