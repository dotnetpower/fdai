import { getLocale } from "../i18n";
import en from "./i18n/evidence-refresh.en.json";
import ko from "./i18n/evidence-refresh.ko.json";

/** Refresh only the owning read projection without submitting operational work. */
export function EvidenceRefresh({
  loading,
  onRefresh,
}: {
  readonly loading: boolean;
  readonly onRefresh: () => void;
}) {
  return (
    <button
      type="button"
      class="btn"
      aria-disabled={loading}
      onClick={loading ? undefined : onRefresh}
    >
      {(getLocale() === "ko" ? ko.refresh : undefined) || en.refresh}
    </button>
  );
}
