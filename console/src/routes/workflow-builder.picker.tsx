/**
 * Workflow-builder ActionType picker - the explicit, searchable choice over the
 * full reviewed palette shown while the designer asks for an action. Search
 * and category filters are presentation only; nothing is selected until the
 * operator clicks an entry.
 */

import { useMemo, useState } from "preact/hooks";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import { humanizeActionName } from "./workflow-builder.helpers";
import { filterActionTypes, paletteCategories } from "./workflow-builder.palette";
import { formatNumber, t } from "./i18n/workflow";

const PICKER_LIMIT = 8;

export function ActionTypePicker({
  palette,
  exclude,
  onPick,
}: {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly exclude: ReadonlySet<string>;
  readonly onPick: (name: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const categories = useMemo(() => paletteCategories(palette), [palette]);
  const matches = useMemo(
    () => filterActionTypes(palette, query, category, exclude),
    [palette, query, category, exclude],
  );
  const shown = matches.slice(0, PICKER_LIMIT);
  return (
    <section class="wf-action-picker" aria-labelledby="wf-action-picker-title">
      <div class="wf-action-picker-head">
        <h4 id="wf-action-picker-title">{t("workflow.chat.picker.title")}</h4>
        <p role="status">
          {t("workflow.chat.picker.summary", {
            shown: formatNumber(shown.length),
            total: formatNumber(matches.length),
          })}
        </p>
      </div>
      <div class="wf-action-picker-controls">
        <input
          class="form-input"
          type="search"
          value={query}
          placeholder={t("workflow.chat.picker.placeholder")}
          aria-label={t("workflow.chat.picker.searchAria")}
          onInput={(event) => setQuery((event.target as HTMLInputElement).value)}
        />
        <select
          class="form-input"
          value={category}
          aria-label={t("workflow.chat.picker.categoryAria")}
          onChange={(event) => setCategory((event.target as HTMLSelectElement).value)}
        >
          <option value="">{t("workflow.chat.picker.allCategories")}</option>
          {categories.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </div>
      {shown.length === 0 ? (
        <p class="wf-action-picker-empty">{t("workflow.chat.picker.empty")}</p>
      ) : (
        <ul class="wf-action-picker-list">
          {shown.map((entry) => (
            <li key={entry.name}>
              <button type="button" onClick={() => onPick(entry.name)}>
                <span class="wf-action-picker-name">
                  <strong>{humanizeActionName(entry.name)}</strong>
                  <code>{entry.name}</code>
                </span>
                <span class="wf-action-picker-facts">
                  {[
                    entry.category ?? "other",
                    t("workflow.chat.picker.rollback", { value: entry.rollback_contract }),
                    entry.hil_tiers.length > 0
                      ? t("workflow.chat.picker.hil", { tiers: entry.hil_tiers.join(", ") })
                      : null,
                    entry.irreversible ? t("workflow.chat.picker.irreversible") : null,
                  ].filter((value): value is string => value !== null).join(" - ")}
                </span>
                {entry.description ? (
                  <span class="wf-action-picker-description">{entry.description}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
