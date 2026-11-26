import { describe, expect, test, vi } from "vitest";
import {
  RuleFacetToolbar,
  buildFacetSelectOptions,
  countActiveRuleFacets,
} from "./rule-facet-toolbar";

describe("RuleFacetToolbar", () => {
  test("buildFacetSelectOptions prepends an all-count option and formats facet labels", () => {
    const options = buildFacetSelectOptions(
      { active: 12, collected: 38 },
      "All",
      (key) => key.toUpperCase(),
    );

    expect(options).toEqual([
      { value: "", label: "All (50)" },
      { value: "active", label: "ACTIVE (12)" },
      { value: "collected", label: "COLLECTED (38)" },
    ]);
  });

  test("countActiveRuleFacets counts non-empty search and facet selections", () => {
    expect(countActiveRuleFacets("", [{ value: "" }, { value: "" }])).toBe(0);
    expect(countActiveRuleFacets("  aks  ", [{ value: "active" }, { value: "" }])).toBe(2);
    expect(countActiveRuleFacets(undefined, [{ value: "high" }, { value: "waf" }])).toBe(2);
  });

  test("renders Wave 0 FilterToolbar with SearchInput, SelectField facets, and reset action", () => {
    const onInput = vi.fn();
    const onOrigin = vi.fn();
    const onReset = vi.fn();

    const vnode = RuleFacetToolbar({
      ariaLabel: "Rule filters",
      search: {
        label: "Search rules",
        value: "storage",
        placeholder: "Search rule id or title",
        onInput,
      },
      facets: [
        {
          label: "Origin",
          value: "active",
          options: buildFacetSelectOptions({ active: 5, collected: 2 }, "All"),
          onChange: onOrigin,
        },
      ],
      onReset,
      resetLabel: "Clear filters",
    });

    const rendered = JSON.stringify(vnode);
    expect(rendered).toContain("rule-facet-toolbar");
    expect(rendered).toContain("Search rules");
    expect(rendered).toContain("Origin");
    expect(rendered).toContain("Clear filters");
    expect(vnode.props.activeFilterCount).toBe(2);
  });
});
