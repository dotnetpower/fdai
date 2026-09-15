/** Read-only exact request reconciliation; never retries a POST or infers completion from a report. */
import type { AsyncState } from "../components/ui";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { AlertClient, AlertQualityRequestMemory } from "./alert-quality.requests";
import { decodeAlertRequestHistory, type AlertRequestHistory } from "./alert-quality.history.model";
import { alertQualityText as text } from "./i18n/alert-quality";

export function createAlertHistorySession(
  client: AlertClient, scope: string, memory: AlertQualityRequestMemory,
  isCurrent: () => boolean, onRead: (state: AsyncState<AlertRequestHistory>) => void,
  onReconciled: () => void,
) {
  let active = true, generation = 0;
  return {
    async load(reconcile = false): Promise<void> {
      if (!active || !isCurrent()) return;
      const request = ++generation;
      const current = () => active && generation === request && isCurrent();
      const key = reconcile ? memory.uncertainKey(scope) : null;
      let timer: ReturnType<typeof setTimeout> | undefined;
      onRead({ status: "loading" });
      try {
        const raw = await Promise.race([
          (async () => {
            const auth = await client.authorizationHeader();
            if (!current() || auth === null || auth.trim() === "") throw new Error("Request context retired");
            return client.panel<unknown>("/alert-quality/requests", {
              scope_ref: scope, ...(key === null ? {} : { request_key: key }),
            });
          })(),
          new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("History deadline")), 15_000); }),
        ]);
        if (!current()) return;
        const data = decodeAlertRequestHistory(raw, scope);
        if (key !== null && (data.truncated || data.requests.length > 1 || data.requests.some((r) => r.request_key !== key))) {
          throw new Error("History does not match selected request");
        }
        onRead({ status: "ready", data });
        const terminal = data.requests.find((r) => r.request_key === key && r.result_recorded_at !== null);
        if (reconcile && terminal !== undefined && memory.reconcile(scope, terminal.request_key)) onReconciled();
      } catch (error) {
        if (current()) onRead(isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: text("history.unavailable") }
          : { status: "error", message: text("history.failed") });
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        if (generation === request) generation += 1;
      }
    },
    dispose(): void { active = false; generation += 1; },
  };
}
