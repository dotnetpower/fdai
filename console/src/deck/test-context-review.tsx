import { useEffect, useId, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { type TestContextDraft } from "./test-context";
import {
  readTestContextChoices,
  readTestContextStatus,
  submitTestContextCommand,
  targetMatchesChoice,
  type ChoiceReadResult,
  type CommandSubmitResult,
  type StatusReadResult,
  type TestContextChoice,
  type TestContextStatusRequest,
} from "./test-context-status";

export function TestContextReview({ draft }: { readonly draft: TestContextDraft }) {
  const [choices, setChoices] = useState<ChoiceReadResult | null>(null);
  const [selected, setSelected] = useState("");
  const [proposalId, setProposalId] = useState("");
  const [result, setResult] = useState<StatusReadResult | null>(null);
  const [submission, setSubmission] = useState<CommandSubmitResult | null>(null);
  const [loading, setLoading] = useState(false);
  const choicesPending = useRef<AbortController | null>(null);
  const lookupPending = useRef<AbortController | null>(null);
  const submitPending = useRef<AbortController | null>(null);
  const choiceId = useId();
  const statusId = useId();
  useEffect(() => {
    const controller = new AbortController();
    choicesPending.current = controller;
    void readTestContextChoices(controller.signal).then((response) => {
      if (choicesPending.current === controller) {
        setChoices(response);
        const first = response.kind === "ready"
          ? response.choices.choices.find((choice) => targetMatchesChoice(draft, choice))
          : null;
        if (first) setSelected(choiceKey(first));
      }
    });
    return () => {
      controller.abort();
      choicesPending.current = null;
      lookupPending.current?.abort();
      submitPending.current?.abort();
    };
  }, [draft]);
  const allChoices = choices?.kind === "ready" ? choices.choices.choices : [];
  const availableChoices = allChoices.filter((choice) => targetMatchesChoice(draft, choice));
  const selectedChoice = availableChoices.find((choice) => choiceKey(choice) === selected) ?? null;
  const status = result?.kind === "ready" ? result.status : null;
  const statusChoice = status ? allChoices.find((choice) => choice.accessScopeDigest === status.request.accessScopeDigest) ?? null : null;
  const reviewed = status?.request ?? null;
  const lookupSubmitted = async (id: string) => {
    const controller = new AbortController();
    lookupPending.current = controller;
    setLoading(true);
    setResult(null);
    const response = await readTestContextStatus(id, controller.signal);
    if (lookupPending.current === controller) setResult(response);
    if (lookupPending.current === controller) {
      lookupPending.current = null;
      setLoading(false);
    }
  };
  const submit = async (operation: "propose" | "review" | "revoke") => {
    const choice = operation === "propose" ? selectedChoice : statusChoice;
    if (!choice || loading) return;
    const revision = operation === "propose" ? 0 : status?.application?.revision ?? 0;
    if (operation !== "propose" && (revision < 1 || !status?.reviewerTransitionAllowed)) return;
    const controller = new AbortController();
    submitPending.current = controller;
    setLoading(true);
    setSubmission(null);
    const response = await submitTestContextCommand(
      operation,
      draft,
      choice,
      revision,
      operation === "propose" ? undefined : status?.request,
      controller.signal,
    );
    if (submitPending.current === controller) setSubmission(response);
    if (response.kind === "accepted") {
      setProposalId(response.proposalId);
      await lookupSubmitted(response.proposalId);
    } else if (submitPending.current === controller) {
      submitPending.current = null;
      setLoading(false);
    }
  };
  return (
    <section class="deck-test-context" aria-label={t("deck.testContext.title")}>
      <h4>{t("deck.testContext.title")}</h4>
      <p>{t("deck.testContext.candidate")}</p>
      <ContextFacts draft={draft} />
      <form class="deck-test-context-lookup" onSubmit={(event) => {
        event.preventDefault();
        void submit("propose");
      }}>
        <label for={choiceId}>{t("deck.testContext.choice")}</label>
        <select id={choiceId} value={selected} disabled={loading || !availableChoices.length}
          onChange={(event) => setSelected(event.currentTarget.value)}>
          {availableChoices.map((choice) => <option value={choiceKey(choice)}>
            {choice.caseScopeId} - {choice.policyRevision}
          </option>)}
        </select>
        {choices?.kind === "ready" && choices.choices.sourceRevision
          ? <p>{t("deck.testContext.sourceRevision")} <code>{choices.choices.sourceRevision}</code></p> : null}
        {choices?.kind === "ready" && !availableChoices.length
          ? <p role="status">{t("deck.testContext.noChoices")}</p> : null}
        {choices && choices.kind !== "ready" ? <p role="status">{t("deck.testContext.choicesUnavailable")}</p> : null}
        <button type="submit" disabled={loading || !selectedChoice || !selectedChoice.allowedOperations.includes("propose")}>
          {t("deck.testContext.submitProposal")}
        </button>
      </form>
      {proposalId ? <p>{t("deck.testContext.boundStatus")} <code>{proposalId}</code></p> : null}
      <form class="deck-test-context-lookup" onSubmit={(event) => {
        event.preventDefault();
        if (proposalId) void lookupSubmitted(proposalId);
      }}>
        <label for={statusId}>{t("deck.testContext.commandId")}</label>
        <p>{t("deck.testContext.manualLookupBoundary")}</p>
        <div>
          <input id={statusId} value={proposalId} maxLength={256}
            onInput={(event) => {
              lookupPending.current?.abort();
              setLoading(false);
              setProposalId(event.currentTarget.value);
              setResult(null);
            }} />
          <button type="submit" disabled={loading || !proposalId}>{t("deck.testContext.lookup")}</button>
        </div>
      </form>
      {loading ? <p role="status">{t("deck.testContext.loading")}</p> : null}
      {submission && submission.kind !== "accepted" ? <p role="status">{t(`deck.testContext.submitStates.${submission.kind}`)}</p> : null}
      {result && result.kind !== "ready" ? <p role="status">{t(`deck.testContext.${result.kind}`)}</p> : null}
      {status ? (
        <div role="status" class="deck-test-context-result">
          <p>{t("deck.testContext.command", { operation: t(`deck.testContext.operations.${status.operation}`) })} <code>{status.proposalId}</code></p>
          {reviewed ? <ReviewedFacts request={reviewed} /> : null}
          <dl class="deck-test-context-facts">
            <div><dt>{t("deck.testContext.delivery")}</dt><dd>{t(`deck.testContext.deliveryStates.${status.delivery}`)}</dd></div>
            <div><dt>{t("deck.testContext.application")}</dt><dd>{t(`deck.testContext.applicationStates.${status.policyApplication}`)}{status.application ? ` (${t(`deck.testContext.applicationStates.${status.application.state}`)}, ${t("deck.testContext.revision")} ${status.application.revision})` : ""}</dd></div>
            <div><dt>{t("deck.testContext.authorization")}</dt><dd>{t(`deck.testContext.authorizationStates.${status.currentAuthorization}`)}</dd></div>
          </dl>
          {status.requesterIsCurrentPrincipal ? <p role="note">{t("deck.testContext.selfReviewBlocked")}</p> : null}
          <div class="deck-test-context-actions" aria-label={t("deck.testContext.lifecycleControls")}>
            <button type="button" disabled={loading || !status.application || !statusChoice?.allowedOperations.includes("review") || !status.reviewerTransitionAllowed} onClick={() => void submit("review")}>{t("deck.testContext.review")}</button>
            <button type="button" disabled={loading || !status.application || !statusChoice?.allowedOperations.includes("revoke") || !status.reviewerTransitionAllowed} onClick={() => void submit("revoke")}>{t("deck.testContext.revoke")}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ContextFacts({ draft }: { readonly draft: TestContextDraft }) {
  return <dl class="deck-test-context-facts">
    <div><dt>{t("deck.testContext.target")}</dt><dd><code>{draft.target_ref}</code></dd></div>
    <div><dt>{t("deck.testContext.signal")}</dt><dd><code>{draft.signal_code}</code></dd></div>
    <div><dt>{t("deck.testContext.range")}</dt><dd>{draft.window.expected_min} - {draft.window.expected_max}</dd></div>
    <div><dt>{t("deck.testContext.interval")}</dt><dd><time dateTime={draft.window.effective_from}>{draft.window.effective_from}</time> - <time dateTime={draft.window.effective_to}>{draft.window.effective_to}</time></dd></div>
    <div><dt>{t("deck.testContext.source")}</dt><dd><code>{draft.source_ref}</code></dd></div>
    <div><dt>{t("deck.testContext.receipt")}</dt><dd><code>{draft.semantic_receipt}</code></dd></div>
  </dl>;
}

function ReviewedFacts({ request }: { readonly request: TestContextStatusRequest }) {
  return <dl class="deck-test-context-facts" aria-label={t("deck.testContext.reviewing")}>
    <div><dt>{t("deck.testContext.reviewing")}</dt><dd><code>{request.contextId}</code></dd></div>
    <div><dt>{t("deck.testContext.target")}</dt><dd><code>{request.targetRef}</code></dd></div>
    <div><dt>{t("deck.testContext.signal")}</dt><dd><code>{request.signalCode}</code></dd></div>
    {request.expectedMin !== undefined && request.expectedMax !== undefined
      ? <div><dt>{t("deck.testContext.range")}</dt><dd>{request.expectedMin} - {request.expectedMax}</dd></div> : null}
    {request.effectiveFrom && request.effectiveTo
      ? <div><dt>{t("deck.testContext.interval")}</dt><dd><time dateTime={request.effectiveFrom}>{request.effectiveFrom}</time> - <time dateTime={request.effectiveTo}>{request.effectiveTo}</time></dd></div> : null}
    <div><dt>{t("deck.testContext.source")}</dt><dd><code>{request.sourceRef}</code></dd></div>
  </dl>;
}

function choiceKey(choice: TestContextChoice): string {
  return `${choice.accessScopeDigest}:${choice.policyRevision}:${choice.sourceRevision}`;
}
