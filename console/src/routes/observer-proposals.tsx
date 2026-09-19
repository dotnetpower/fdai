import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import { AsyncBoundary, type AsyncState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { t } from "../i18n";
import { panelArray, panelRecord, panelString, panelStringArray } from "./panel-decode";

const METHODS = ["gitops", "existing_host", "managed_host", "run_command"] as const;
const STATES = ["ready_for_review", "needs_evidence", "blocked", "not_applicable"] as const;
interface Candidate {
  readonly method: string;
  readonly egress: string;
  readonly state: string;
  readonly blockers: readonly string[];
  readonly missing: readonly string[];
}
interface ProposalItem {
  readonly target: string;
  readonly expiresAt: number;
  readonly status: string;
  readonly recommended: Candidate | null;
  readonly candidates: readonly Candidate[];
}

function candidate(value: unknown): Candidate {
  const row = panelRecord(value, "candidate");
  const method = panelString(row, "method", "candidate");
  const egress = panelString(row, "egress", "candidate");
  const state = panelString(row, "state", "candidate");
  const blockers = panelStringArray(row.blockers, "blockers");
  const missing = panelStringArray(row.missing, "missing");
  if (!(METHODS as readonly string[]).includes(method) || !["private", "public"].includes(egress)
      || !["eligible", "unknown", "blocked"].includes(state) || blockers.length > 19 || missing.length > 16) {
    throw new Error("Invalid observer deployment candidate");
  }
  return { method, egress, state, blockers, missing };
}

export function decodeObserverProposals(value: unknown): readonly ProposalItem[] {
  const root = panelRecord(value, "observer proposals");
  if (root.synthetic !== false || root.execution_authority !== false) throw new Error("Invalid observer projection authority");
  const items = panelArray(root.items, "observer proposals.items");
  if (items.length > 128) throw new Error("Observer proposal count exceeds its bound");
  const targets = new Set<string>();
  return items.map((item) => {
    const row = panelRecord(item, "observer proposal");
    const target = panelString(row, "target_ref", "observer proposal");
    const expiresAt = Date.parse(panelString(row, "expires_at", "observer proposal"));
    if (!target || target.length > 512 || targets.has(target) || !Number.isFinite(expiresAt)
        || row.execution_authority !== false || !["current", "unavailable"].includes(String(row.state))) {
      throw new Error("Invalid observer projection identity");
    }
    targets.add(target);
    if (row.state === "unavailable") {
      if (row.proposal !== null) throw new Error("Unavailable proposal contains current evidence");
      return { target, expiresAt, status: "unavailable", recommended: null, candidates: [] };
    }
    const proposal = panelRecord(row.proposal, "proposal");
    const status = panelString(proposal, "status", "proposal");
    if (proposal.execution_authority !== false || proposal.approval_required !== true
        || proposal.target_ref !== target || !(STATES as readonly string[]).includes(status)) {
      throw new Error("Invalid observer recommendation authority or target");
    }
    const candidates = panelArray(proposal.candidates, "candidates").map(candidate);
    if (candidates.length > 8) throw new Error("Observer candidates exceed their bound");
    const recommended = proposal.recommended === null ? null : candidate(proposal.recommended);
    if ((status === "ready_for_review") !== (recommended !== null)
        || recommended && (recommended.state !== "eligible" || !candidates.some((entry) => JSON.stringify(entry) === JSON.stringify(recommended)))) {
      throw new Error("Observer recommendation does not match its candidates");
    }
    return { target, expiresAt, status, recommended, candidates };
  });
}

export function ObserverProposals({ client, dataMode }: { readonly client: OperatorApiClient; readonly dataMode: ConsoleDataMode }) {
  const [state, setState] = useState<AsyncState<readonly ProposalItem[]>>({ status: "loading" });
  const [now, setNow] = useState(Date.now());
  const generation = useRef(0);
  const load = async (): Promise<void> => {
    const request = ++generation.current;
    if (dataMode !== "live") {
      setState({ status: "unavailable", message: t("observerProposals.unavailable") });
      return;
    }
    setState({ status: "loading" });
    try {
      const data = decodeObserverProposals(await client.panel<unknown>("/observer-deployment-proposals"));
      if (request === generation.current) setState({ status: "ready", data });
    } catch {
      if (request === generation.current) setState({ status: "unavailable", message: t("observerProposals.unavailable") });
    }
  };
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { generation.current += 1; window.clearInterval(timer); };
  }, [client, dataMode]);
  return <div class="stack observer-proposals">
    <header class="environment-deployment-section-header">
      <h2>{t("observerProposals.title")}</h2>
      <EvidenceRefresh loading={state.status === "loading"} onRefresh={() => { void load(); }} />
    </header>
    <AsyncBoundary state={state} resourceLabel={t("observerProposals.title")}>
      {(items) => items.length === 0 ? <p>{t("observerProposals.empty")}</p> : <>{items.map((item) => {
        const current = item.expiresAt > now && item.status !== "unavailable";
        return <details class="observer-proposal" key={item.target}>
          <summary><strong>{item.target}</strong><span>{t(`observerProposals.${current ? item.status : "unavailable"}`)}</span></summary>
          {current ? <div class="stack">
            {item.recommended && <p>{t("observerProposals.recommendation")}: {t(`observerProposals.${item.recommended.method}`)} / {t(`observerProposals.${item.recommended.egress}`)}</p>}
            <dl>{item.candidates.map((entry) => <div key={`${entry.method}-${entry.egress}`}>
              <dt>{t(`observerProposals.${entry.method}`)} / {t(`observerProposals.${entry.egress}`)}</dt>
              <dd>{t(`observerProposals.${entry.state}`)}{[...entry.blockers, ...entry.missing].map((reason) => <code key={reason}>{reason}</code>)}</dd>
            </div>)}</dl>
            <p>{t("observerProposals.expires")}: <time dateTime={new Date(item.expiresAt).toISOString()}>{new Date(item.expiresAt).toLocaleString()}</time></p>
          </div> : <p>{t("observerProposals.unavailable")}</p>}
        </details>;
      })}</>}
    </AsyncBoundary>
  </div>;
}
