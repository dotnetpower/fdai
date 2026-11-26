import { useEffect, useState } from "preact/hooks";
import { DisclosurePanel } from "../components/disclosure-panel";
import { SearchInput, SelectField, TextInput } from "../components/form-controls";
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
  const selectField = (
    key: string,
    label: string,
    values: readonly [string, string][],
  ) => {
    const value = draft.get(key) ?? "";
    const options = values.some(([option]) => option === value)
      ? values.map(([option, optionLabel]) => ({ value: option, label: optionLabel }))
      : [{ value, label: value }, ...values.map(([option, optionLabel]) => ({ value: option, label: optionLabel }))];
    return (
      <SelectField
        name={key}
        label={label}
        value={value}
        options={options}
        onChange={(nextValue) => set(key, nextValue)}
      />
    );
  };
  const active = new URLSearchParams(search);
  return (
    <form class="audit-query" aria-label={t("evidence.audit.activeFilters")} onSubmit={(event) => {
      event.preventDefault();
      navigate(routeHref("audit", { params: Object.fromEntries(draft) }));
    }}>
      <div class="audit-query-main">
        <SearchInput
          label={t("evidence.audit.workspace.searchLedger")}
          value={draft.get("q") ?? ""}
          maxLength={200}
          placeholder={t("evidence.audit.workspace.searchPlaceholder")}
          clearLabel={t("evidence.audit.workspace.clear")}
          onInput={(nextValue) => set("q", nextValue)}
        />
        {selectField("outcome", t("evidence.audit.workspace.decisionFilter"), [
          ["", t("evidence.audit.workspace.allDecisions")],
          ...["auto", "hil", "abstain", "deny"].map(
            (value): [string, string] => [value, presentationLabel("status", value)],
          ),
        ])}
        {selectField("window", t("evidence.audit.filter.window"), [
          ["", t("evidence.audit.workspace.allTime")],
          ["1d", t("evidence.audit.workspace.day")],
          ["7d", t("evidence.audit.workspace.week")],
          ["30d", t("evidence.audit.workspace.month")],
        ])}
        <button type="submit" class="primary">{t("evidence.audit.workspace.apply")}</button>
      </div>
      <p id="audit-search-scope" class="audit-query-hint">{t("evidence.audit.workspace.searchScope")}</p>
      <DisclosurePanel
        {...{ title: t("evidence.audit.workspace.moreFilters") }}
        className="audit-query-more"
        tone="subtle"
      >
        <div class="audit-query-more-grid">
          <TextInput
            name="correlation"
            label={t("evidence.audit.workspace.correlation")}
            value={draft.get("correlation") ?? ""}
            maxLength={256}
            mono
            placeholder={t("evidence.audit.workspace.queryPlaceholder")}
            onInput={(nextValue) => set("correlation", nextValue)}
          />
          {selectField("mode", t("evidence.audit.filter.mode"), [
            ["", t("evidence.audit.workspace.allModes")],
            ["shadow", presentationLabel("status", "shadow")],
            ["enforce", presentationLabel("status", "enforce")],
          ])}
          <button type="button" onClick={() => {
            const params = new URLSearchParams(currentRoute().search);
            for (const key of FILTER_KEYS) params.delete(key);
            navigate(routeHref("audit", { params: Object.fromEntries(params) }));
          }}>{t("evidence.audit.workspace.clear")}</button>
        </div>
      </DisclosurePanel>
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
