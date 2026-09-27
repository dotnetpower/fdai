import { useEffect, useId, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { type TestContextDraft } from "./test-context";
import {
  readTestContextStatus,
  validProposalId,
  type StatusReadResult,
} from "./test-context-status";

export function TestContextReview({ draft }: { readonly draft: TestContextDraft }) {
  const [proposalId, setProposalId] = useState("");
  const [result, setResult] = useState<StatusReadResult | null>(null);
  const [loading, setLoading] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const inputId = useId();
  useEffect(() => () => {
    pending.current?.abort();
    pending.current = null;
  }, []);
  const lookup = async () => {
    if (loading || !validProposalId(proposalId)) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setResult(null);
    try {
      const response = await readTestContextStatus(proposalId, controller.signal);
      if (pending.current === controller) setResult(response);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        if (pending.current === controller) setResult({ kind: "error" });
      }
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        setLoading(false);
      }
    }
  };
  const status = result?.kind === "ready" ? result.status : null;
  return (
    <section class="deck-test-context" aria-label={t("deck.testContext.title")}>
      <h4>{t("deck.testContext.title")}</h4>
      <p>{t("deck.testContext.candidate")}</p>
      <dl class="deck-test-context-facts">
        <div><dt>{t("deck.testContext.target")}</dt><dd><code>{draft.target_ref}</code></dd></div>
        <div><dt>{t("deck.testContext.signal")}</dt><dd><code>{draft.signal_code}</code></dd></div>
        <div><dt>{t("deck.testContext.range")}</dt><dd>{draft.window.expected_min} - {draft.window.expected_max}</dd></div>
        <div><dt>{t("deck.testContext.interval")}</dt><dd><time dateTime={draft.window.effective_from}>{draft.window.effective_from}</time> - <time dateTime={draft.window.effective_to}>{draft.window.effective_to}</time></dd></div>
        <div><dt>{t("deck.testContext.source")}</dt><dd><code>{draft.source_ref}</code></dd></div>
        <div><dt>{t("deck.testContext.receipt")}</dt><dd><code>{draft.semantic_receipt}</code></dd></div>
      </dl>
      <p role="note">{t("deck.testContext.selectionUnavailable")}</p>
      <p>{t("deck.testContext.lookupBoundary")}</p>
      <form class="deck-test-context-lookup" onSubmit={(event) => {
        event.preventDefault();
        void lookup();
      }}>
        <label for={inputId}>{t("deck.testContext.commandId")}</label>
        <div>
          <input id={inputId} value={proposalId} maxLength={256}
            onInput={(event) => {
              pending.current?.abort();
              pending.current = null;
              setLoading(false);
              setProposalId(event.currentTarget.value);
              setResult(null);
            }} />
          <button type="submit" disabled={loading || !validProposalId(proposalId)}>
            {t("deck.testContext.lookup")}
          </button>
        </div>
      </form>
      {loading ? <p role="status">{t("deck.testContext.loading")}</p> : null}
      {result && result.kind !== "ready" ? (
        <p role="status">{t(`deck.testContext.${result.kind}`)}</p>
      ) : null}
      {status ? (
        <div role="status" class="deck-test-context-result">
          <p>{t("deck.testContext.command", { operation: t(`deck.testContext.operations.${status.operation}`) })} <code>{status.proposalId}</code></p>
          <dl class="deck-test-context-facts">
            <div><dt>{t("deck.testContext.delivery")}</dt><dd>{t(`deck.testContext.deliveryStates.${status.delivery}`)}</dd></div>
            <div><dt>{t("deck.testContext.application")}</dt><dd>{t(`deck.testContext.applicationStates.${status.policyApplication}`)}{status.application ? ` (${t(`deck.testContext.applicationStates.${status.application.state}`)}, ${t("deck.testContext.revision")} ${status.application.revision})` : ""}</dd></div>
            <div><dt>{t("deck.testContext.authorization")}</dt><dd>{t(`deck.testContext.authorizationStates.${status.currentAuthorization}`)}</dd></div>
          </dl>
        </div>
      ) : null}
    </section>
  );
}
