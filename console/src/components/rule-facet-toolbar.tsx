import type { ComponentChildren } from "preact";
import {
  FilterToolbar,
  SearchInput,
  SelectField,
  type SelectOption,
} from "./form-controls";

export type FacetCountMap = Readonly<Record<string, number>>;

export interface RuleFacetFilter {
  readonly id?: string;
  readonly label: string;
  readonly value: string;
  readonly options: readonly SelectOption[];
  readonly disabled?: boolean;
  readonly className?: string;
  readonly onChange: (value: string) => void;
}

export interface RuleFacetSearchConfig {
  readonly id?: string;
  readonly label: string;
  readonly hideLabel?: boolean;
  readonly value: string;
  readonly placeholder?: string;
  readonly maxLength?: number;
  readonly clearLabel?: string;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly onInput: (value: string) => void;
  readonly onClear?: () => void;
}

export interface RuleFacetToolbarProps {
  readonly ariaLabel?: string;
  readonly search?: RuleFacetSearchConfig;
  readonly facets: readonly RuleFacetFilter[];
  readonly leading?: ComponentChildren;
  readonly actions?: ComponentChildren;
  readonly activeFilterCount?: number;
  readonly onReset?: () => void;
  readonly resetLabel?: string;
  readonly className?: string;
}

/** Builds standardized SelectField options with total/per-value counts. */
export function buildFacetSelectOptions(
  counts: FacetCountMap,
  allLabel: string,
  formatLabel?: (key: string) => string,
): readonly SelectOption[] {
  const entries = Object.entries(counts);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  return [
    { value: "", label: `${allLabel} (${total})` },
    ...entries.map(([key, count]) => ({
      value: key,
      label: `${formatLabel ? formatLabel(key) : key} (${count})`,
    })),
  ];
}

/** Computes how many search/facet filters are currently active. */
export function countActiveRuleFacets(
  searchValue: string | undefined,
  facets: readonly Pick<RuleFacetFilter, "value">[],
): number {
  const searchCount = searchValue && searchValue.trim().length > 0 ? 1 : 0;
  const facetCount = facets.reduce(
    (sum, facet) => sum + (facet.value.length > 0 ? 1 : 0),
    0,
  );
  return searchCount + facetCount;
}

/**
 * Shared facet filter bar for rule, control, and action catalog routes.
 * Composes Wave 0 FilterToolbar, SearchInput, and SelectField primitives
 * without raw native select/input styling drift.
 */
export function RuleFacetToolbar({
  ariaLabel,
  search,
  facets,
  leading,
  actions,
  activeFilterCount,
  onReset,
  resetLabel,
  className,
}: RuleFacetToolbarProps) {
  const resolvedActiveCount = activeFilterCount ?? countActiveRuleFacets(search?.value, facets);
  const mergedClassName = className
    ? `rule-facet-toolbar ${className}`
    : "rule-facet-toolbar";

  return (
    <FilterToolbar
      {...(ariaLabel !== undefined ? { ariaLabel } : {})}
      activeFilterCount={resolvedActiveCount}
      {...(onReset !== undefined ? { onReset } : {})}
      {...(resetLabel !== undefined ? { resetLabel } : {})}
      {...(actions !== undefined ? { actions } : {})}
      className={mergedClassName}
    >
      {leading}
      {search ? (
        <SearchInput
          {...(search.id !== undefined ? { id: search.id } : {})}
          label={search.label}
          {...(search.hideLabel !== undefined ? { hideLabel: search.hideLabel } : {})}
          value={search.value}
          {...(search.placeholder !== undefined ? { placeholder: search.placeholder } : {})}
          {...(search.maxLength !== undefined ? { maxLength: search.maxLength } : {})}
          {...(search.clearLabel !== undefined ? { clearLabel: search.clearLabel } : {})}
          {...(search.disabled !== undefined ? { disabled: search.disabled } : {})}
          className={search.className ? `rule-facet-search ${search.className}` : "rule-facet-search"}
          onInput={search.onInput}
          {...(search.onClear !== undefined ? { onClear: search.onClear } : {})}
        />
      ) : null}
      {facets.map((facet) => (
        <SelectField
          key={facet.id ?? facet.label}
          {...(facet.id !== undefined ? { id: facet.id } : {})}
          label={facet.label}
          value={facet.value}
          options={facet.options}
          {...(facet.disabled !== undefined ? { disabled: facet.disabled } : {})}
          className={facet.className ? `rule-facet-select ${facet.className}` : "rule-facet-select"}
          onChange={facet.onChange}
        />
      ))}
    </FilterToolbar>
  );
}
