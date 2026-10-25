// Pure selection logic for the enrollment request form's installation dropdown.
import type { BindableInstallation, BindableStatus } from "./api";

const LABELS: Record<BindableStatus, string> = {
  unrequested: "not requested yet",
  pending: "request pending",
  enrolled: "enrolled",
};

export function isSelectable(item: BindableInstallation): boolean {
  return item.status === "unrequested";
}

export function optionLabel(item: BindableInstallation): string {
  return `${item.installation_id} (${LABELS[item.status] ?? item.status})`;
}

/** The chosen installation if it can still take a new request, else the first unrequested one. */
export function effectiveSelection(
  items: readonly BindableInstallation[], chosen: string,
): string {
  const kept = items.find(item => item.installation_id === chosen && isSelectable(item));
  return (kept ?? items.find(isSelectable))?.installation_id ?? "";
}
