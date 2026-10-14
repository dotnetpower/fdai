import { conversationModelText } from "./conversation-model-i18n";
import { RichContent } from "./rich-content";

interface Contribution {
  readonly agent: string;
  readonly answer: string;
  readonly evidence_refs: readonly string[];
  readonly peer_review?: { readonly comparison_status: string };
}

interface Discussion {
  readonly authority: "presentation_only";
  readonly status: "completed" | "held" | "partial" | "abstain";
  readonly rounds: readonly {
    readonly phase: "position" | "critique";
    readonly contributions: readonly Contribution[];
  }[];
  readonly conclusion: string | null;
  readonly participant_outcomes?: readonly {
    readonly agent: string;
    readonly status: "completed" | "abstained" | "not_attempted";
  }[];
}

const AGENTS = new Set([
  "Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi",
  "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr", "Loki",
]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function decodeAgentDiscussion(text: string): Discussion | null {
  if (text.length > 64_000) return null;
  let value: unknown;
  try { value = JSON.parse(text); } catch { return null; }
  if (
    !record(value) || value.authority !== "presentation_only"
    || !["completed", "held", "partial", "abstain"].includes(String(value.status))
    || !Array.isArray(value.rounds) || value.rounds.length > 2
    || !(value.conclusion === null || typeof value.conclusion === "string")
  ) return null;
  if (value.conclusion !== null && (
    value.status !== "completed" || value.tier !== "T2" || value.t2_status !== "completed"
    || !record(value.synthesis_verification)
    || typeof value.synthesis_verification.conclusion_sha256 !== "string"
    || !/^[a-f0-9]{64}$/.test(value.synthesis_verification.conclusion_sha256)
  )) return null;
  if (value.participant_outcomes !== undefined && (
    !Array.isArray(value.participant_outcomes) || value.participant_outcomes.length > 3
    || !value.participant_outcomes.every((item: unknown) => record(item)
      && typeof item.agent === "string" && AGENTS.has(item.agent)
      && ["completed", "abstained", "not_attempted"].includes(String(item.status)))
  )) return null;
  for (const round of value.rounds) {
    if (
      !record(round) || !["position", "critique"].includes(String(round.phase))
      || !Array.isArray(round.contributions) || round.contributions.length > 3
    ) return null;
    for (const contribution of round.contributions) {
      if (
        !record(contribution) || typeof contribution.agent !== "string"
        || !AGENTS.has(contribution.agent) || typeof contribution.answer !== "string"
        || !Array.isArray(contribution.evidence_refs) || contribution.evidence_refs.length > 20
        || !contribution.evidence_refs.every((ref: unknown) => typeof ref === "string")
        || (contribution.peer_review !== undefined && (
          !record(contribution.peer_review)
          || !["consistent", "conflicting", "not_comparable"].includes(
            String(contribution.peer_review.comparison_status),
          )
        ))
      ) return null;
    }
  }
  return value as unknown as Discussion;
}

export function AgentDiscussionReply({ discussion }: { readonly discussion: Discussion }) {
  return <section class="deck-agent-discussion" aria-label={conversationModelText("discussionMode")}>
    {discussion.participant_outcomes ? <dl class="deck-discussion-participants">
      {discussion.participant_outcomes.map((participant) => <div key={participant.agent}>
        <dt>{participant.agent}</dt><dd>{conversationModelText(participant.status)}</dd>
      </div>)}
    </dl> : null}
    {discussion.rounds.map((round) => <section key={round.phase}>
      <h4>{conversationModelText(round.phase)}</h4>
      {round.contributions.map((claim) => <article key={claim.agent}>
        <header><strong>{claim.agent}</strong>
          {claim.peer_review ? <span>{conversationModelText(
            claim.peer_review.comparison_status as "consistent" | "conflicting" | "not_comparable",
          )}</span> : null}
        </header>
        <RichContent text={claim.answer} />
        <details><summary>{conversationModelText("discussionEvidence")}</summary>
          <ul>{claim.evidence_refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul>
        </details>
      </article>)}
    </section>)}
    <section>
      <h4>{conversationModelText(discussion.conclusion ? "discussionConclusion" : "discussionHeld")}</h4>
      {discussion.conclusion ? <RichContent text={discussion.conclusion} /> : null}
    </section>
  </section>;
}
