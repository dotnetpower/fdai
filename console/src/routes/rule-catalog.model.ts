export function isRuleListUpdating(
  searchInput: string,
  appliedSearch: string,
  requestLoading: boolean,
): boolean {
  return requestLoading || searchInput !== appliedSearch;
}