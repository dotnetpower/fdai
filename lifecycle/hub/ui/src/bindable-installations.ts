// Pure selection logic for the enrollment request form's installation dropdown.
import type { BindableInstallation, BindableStatus } from "./api";
import type { HubLocale } from "./locale";

const LABELS: Record<BindableStatus, string> = {
  unrequested: "not requested yet",
  pending: "request pending",
  enrolled: "enrolled",
};

const LABELS_KO: Record<BindableStatus, string> = {
  unrequested: "아직 요청 안 됨",
  pending: "요청 대기 중",
  enrolled: "등록됨",
};

export function isSelectable(item: BindableInstallation): boolean {
  return item.status === "unrequested";
}

export function optionLabel(item: BindableInstallation, locale: HubLocale = "en"): string {
  const map = locale === "ko" ? LABELS_KO : LABELS;
  return `${item.installation_id} (${map[item.status] ?? item.status})`;
}

/** The chosen installation if it can still take a new request, else the first unrequested one. */
export function effectiveSelection(
  items: readonly BindableInstallation[], chosen: string,
): string {
  const kept = items.find(item => item.installation_id === chosen && isSelectable(item));
  return (kept ?? items.find(isSelectable))?.installation_id ?? "";
}
