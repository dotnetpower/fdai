import { GovernedCommandError } from "../governed-command";
import { t } from "./i18n/approvals";

/** Turn a failed decision request into a message the approver can act on. */
export function decisionFailureMessage(error: unknown): string {
  if (error instanceof GovernedCommandError) {
    if (error.status === 410) return t("approvals.errorExpired");
    if (error.status === 409) return t("approvals.errorAlreadyResolved");
    if (error.status >= 500) return t("approvals.errorServer");
  }
  return error instanceof Error ? error.message : String(error);
}
