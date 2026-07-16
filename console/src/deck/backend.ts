/**
 * Chat backend client - POST /chat with graceful fallback.
 *
 * Single responsibility: turn a (prompt, snapshot, history) call into
 * an HTTP round-trip and normalise the reply / failure so the deck UI
 * can render either a real LLM answer or the deterministic answerer's
 * fallback without branching on transport details.
 *
 * The client also exposes a lightweight preflight (``probeBackend``)
 * that hits ``GET /chat/health`` once. The deck header renders the
 * returned descriptor as a status badge (``LLM ready · gpt-4o-mini``
 * or ``deterministic fallback``) so the operator sees the mode BEFORE
 * asking the first question - matching the "LLM by default" contract.
 */

import { loadConfig } from "../config";
import type { AuthContext } from "../auth";
import { getLocale } from "../i18n";
import { readConsolePreferences } from "../preferences";
import { answer as deterministicAnswer, ROUTE_ACTION_HINTS, type Answer } from "./answerer";
import type { ViewSnapshot } from "./context";
import { getDeckUser } from "./deck-user";

let chatAuth: AuthContext | null = null;

export function setChatAuth(auth: AuthContext | null): void {
  chatAuth = auth;
}

async function requestHeaders(contentType: boolean = false): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = "application/json";
  const authorization = await chatAuth?.getAuthorizationHeader() ?? null;
  if (authorization) headers.authorization = authorization;
  return headers;
}

/** Build the `view_context` sent to the chat backend: the screen snapshot plus
 *  the signed-in operator's identity/roles (`_user`) so the narrator can answer
 *  capability questions, plus the per-route action hint (`_route_actions`) so
 *  'what can I do here?' from the LLM matches the deterministic fallback and
 *  is grounded (never invented), plus the operator's active locale (`_locale`)
 *  so the L3 narrator renders the final answer in that language (the pipeline
 *  itself stays English - see language.instructions.md L3). Read-only,
 *  informational - see deck-user.ts. */
function viewContextWithUser(snapshot: ViewSnapshot | null): Record<string, unknown> {
  const base: Record<string, unknown> = snapshot ? { ...snapshot } : {};
  const user = getDeckUser();
  if (user) base._user = user;
  if (snapshot?.routeId) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    if (hint) base._route_actions = hint;
  }
  // Locale propagation: the backend prepends a locale directive only when
  // the tag is non-empty and not English (byte-identical default for
  // English operators), so passing `en` here is a safe no-op.
  base._locale = getLocale();
  return base;
}

export interface BackendTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
}

/** One candidate's rolling stat from the latency-routed backend. */
export interface RouterCandidate {
  readonly deployment: string;
  readonly p50_ms: number | null;
  readonly p95_ms: number | null;
  readonly samples: number;
  /** Raw rolling window (most-recent last) - drives the sparkline strip. */
  readonly history_ms: readonly number[];
}

/** Router snapshot attached to a chat reply / health descriptor. */
export interface RouterSnapshot {
  readonly chose: string;
  readonly reason: string;
  readonly candidates: readonly RouterCandidate[];
}

export interface BackendReply {
  readonly text: string;
  /** ``"llm:<model> · <N>ms"`` when the reply came from the server, else ``"deterministic"``. */
  readonly source: string;
  /** Present when the server wired the latency-routed backend. */
  readonly router?: RouterSnapshot;
}

export type AnswerVerificationStatus =
  | "verified"
  | "consistent"
  | "corrected"
  | "unverified";

export type AtomicClaimStatus = "supported" | "unsupported" | "ambiguous";

export interface AtomicAnswerClaim {
  readonly claim_id: string;
  readonly kind: "id" | "number" | "percentage" | "timestamp" | "causal" | "scope";
  readonly text: string;
  readonly span: { readonly start: number; readonly end: number };
  readonly raw_value: string;
  readonly normalized_value: string;
  readonly unit: string | null;
  readonly anchors: readonly string[];
  readonly status: AtomicClaimStatus;
  readonly evidence_refs: readonly string[];
  readonly reason_code: string | null;
}

export interface EvidenceManifestEntry {
  readonly ref: string;
  readonly path: string;
  readonly field: string;
  readonly kind: string;
  readonly raw_value: string;
  readonly normalized_value: string;
  readonly anchors: readonly string[];
}

export interface AnswerEvidenceManifest {
  readonly schema_version: number;
  readonly manifest_id: string;
  readonly authority: string;
  readonly route_id: string | null;
  readonly captured_at: string | null;
  readonly complete: boolean;
  readonly source_entry_count: number;
  readonly entries: readonly EvidenceManifestEntry[];
}

export interface SemanticVerification {
  readonly verdict: "entailed" | "contradicted" | "unknown" | "unavailable";
  readonly provider: string;
  readonly model_id: string | null;
  readonly latency_ms: number;
  readonly entailment_score: number | null;
  readonly contradiction_score: number | null;
  readonly reason_code: string | null;
}

export interface AnswerVerification {
  readonly status: AnswerVerificationStatus;
  readonly authority: string;
  readonly checks_completed: number;
  readonly checks_total: number;
  readonly evidence_refs: readonly string[];
  readonly reason_code: string | null;
  readonly claims?: readonly AtomicAnswerClaim[];
  readonly evidence_manifest?: AnswerEvidenceManifest;
  readonly failed_claim_ids?: readonly string[];
  readonly semantic?: SemanticVerification;
}

export interface DelegationMetadata {
  readonly primary_agent: string;
  readonly contributors: readonly string[];
  readonly trace_ref?: string;
}

export interface AnswerPlanMetadata {
  readonly intent: "definition" | "why" | "procedure" | "comparison" | "diagnosis" | "status" | "list" | "summary" | "proposal" | "open_question";
  readonly detail_level: "brief" | "standard" | "deep";
  readonly format: "prose" | "bullets" | "numbered_steps" | "table" | "checklist" | "mixed";
  readonly sections: readonly string[];
  readonly evidence_requirement: "none" | "screen" | "catalog" | "server_read_model" | "agent_owned";
  readonly max_words: number;
  readonly discuss: "skip" | "shadow" | "selective";
  readonly explicit_overrides: readonly string[];
}

export interface VerificationProgress {
  readonly phase: string;
  readonly label: string;
  readonly completed: number | null;
  readonly total: number | null;
  readonly sources?: readonly RetrievalSourcePreview[];
}

export interface RetrievalSourcePreview {
  readonly kind: string;
  readonly label: string;
  readonly detail: string;
  readonly side_effect_class: "read" | "route" | "simulate" | "ground";
}

export type CodeValidationStatus = "valid" | "invalid" | "not_checked";

export interface GroundedCodeArtifact {
  readonly artifact_ref: string;
  readonly language: string;
  readonly content: string;
  readonly sha256: string;
  readonly validation_status: CodeValidationStatus;
  readonly validation_detail: string | null;
}

export type ProgressiveAnswer = Answer & {
  readonly source: string;
  readonly router?: RouterSnapshot;
  readonly verification?: AnswerVerification;
  readonly delegation?: DelegationMetadata;
  readonly answerPlan?: AnswerPlanMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
};

/** Health-check descriptor returned by ``GET /chat/health``. */
export interface BackendHealth {
  readonly available: boolean;
  readonly mode: string;
  readonly model: string | null;
  readonly endpoint: string | null;
  readonly router?: RouterSnapshot;
}

const OFFLINE_HEALTH: BackendHealth = {
  available: false,
  mode: "offline",
  model: null,
  endpoint: null,
};

const HEALTH_CACHE_MS = 30_000;
let healthCache: { readonly value: BackendHealth; readonly at: number } | null = null;
let healthInFlight: Promise<BackendHealth> | null = null;

function chatUrl(): string {
  const cfg = loadConfig();
  const base = cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  return `${base.replace(/\/$/, "")}/chat`;
}

function healthUrl(): string {
  return `${chatUrl()}/health`;
}

function streamUrl(): string {
  return `${chatUrl()}/stream`;
}

function toBackendHistory(history: readonly BackendTurn[]): BackendTurn[] {
  // Only user/assistant pairs, most recent 8 turns.
  return history.slice(-8).map((t) => ({ role: t.role, content: t.content }));
}

function verificationPreferences(): { readonly semantic_enabled: boolean } {
  return {
    semantic_enabled: readConsolePreferences().semanticVerification === "shadow",
  };
}

/**
 * Ping the chat backend's health endpoint. Returns a descriptor even
 * on failure - callers can render "offline" without a try/catch.
 */
async function fetchBackendHealth(): Promise<BackendHealth> {
  let response: Response;
  try {
    response = await fetch(healthUrl(), {
      method: "GET",
      headers: await requestHeaders(),
      credentials: "omit",
    });
  } catch {
    return OFFLINE_HEALTH;
  }
  if (!response.ok) {
    return {
      available: false,
      mode: `unreachable (${response.status})`,
      model: null,
      endpoint: null,
    };
  }
  try {
    const payload = (await response.json()) as Partial<BackendHealth> & {
      router?: unknown;
    };
    const router = parseRouter(payload.router);
    const base: BackendHealth = {
      available: payload.available === true,
      mode: typeof payload.mode === "string" ? payload.mode : "unknown",
      model: typeof payload.model === "string" ? payload.model : null,
      endpoint: typeof payload.endpoint === "string" ? payload.endpoint : null,
    };
    return router ? { ...base, router } : base;
  } catch {
    return OFFLINE_HEALTH;
  }
}

export function probeBackend(): Promise<BackendHealth> {
  const now = Date.now();
  if (healthCache && now - healthCache.at < HEALTH_CACHE_MS) {
    return Promise.resolve(healthCache.value);
  }
  if (healthInFlight) return healthInFlight;

  const request = fetchBackendHealth().then((value) => {
    healthCache = { value, at: Date.now() };
    return value;
  });
  healthInFlight = request;
  void request.then(
    () => {
      if (healthInFlight === request) healthInFlight = null;
    },
    () => {
      if (healthInFlight === request) healthInFlight = null;
    },
  );
  return request;
}

/**
 * Ask the chat backend. Always tries the backend first; falls back to
 * the deterministic answerer per-turn when the request fails. Never
 * caches failures permanently - transient outages self-heal on the
 * next attempt.
 */
export async function askBackend(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  sessionId?: string,
): Promise<ProgressiveAnswer> {
  let response: Response;
  try {
    response = await fetch(chatUrl(), {
      method: "POST",
      headers: await requestHeaders(true),
      body: JSON.stringify({
        prompt,
        session_id: sessionId,
        view_context: viewContextWithUser(snapshot),
        history: toBackendHistory(history),
        verification_preferences: verificationPreferences(),
      }),
      credentials: "omit",
    });
  } catch {
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (offline)" };
  }

  if (response.status === 404 || response.status === 501) {
    // Endpoint not wired on this deployment (no upstream configured).
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (LLM not configured)" };
  }

  if (response.status === 422) {
    // Prompt refused by the upstream content/jailbreak filter - a safe,
    // expected block (not an outage). Label it distinctly.
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (blocked by content policy)" };
  }

  if (!response.ok) {
    // Upstream error - deterministic fallback for this turn only. We do
    // NOT cache: transient upstream hiccups must self-heal.
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: `deterministic (backend ${response.status})` };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (bad JSON)" };
  }

  const answerText = extractString(payload, "answer");
  const model = extractString(payload, "model") ?? "llm";
  const explicitSource = extractString(payload, "source");
  const latencyMs = extractNumber(payload, "latency_ms");
  const verification = parseAnswerVerification(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).verification
      : undefined,
  );
  const router = parseRouter(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).router
      : undefined,
  );
  const delegation = parseDelegation(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).delegation
      : undefined,
  );
  const answerPlan = parseAnswerPlan(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).answer_plan
      : undefined,
  );
  const codeArtifacts = parseGroundedCodeArtifacts(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).code_artifacts
      : undefined,
  );
  if (answerText === null) {
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (no answer field)" };
  }
  // Compose the source badge. Router pick wins over the plain ``model``
  // field so the operator always sees the deployment that actually served
  // the turn (they can differ if the backend echoes a canonical name).
  const chosen = router?.chose ?? model;
  const source = explicitSource ?? (
    (latencyMs !== null && latencyMs >= 0
      ? `llm:${chosen} · ${latencyMs}ms`
      : `llm:${chosen}`) +
    tokenSuffix(
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>).usage
        : undefined,
    )
  );
  const base = {
    text: answerText,
    // LLM replies do not carry structured citations; the deck grounds the
    // reply on the snapshot the model was given (see snapshotCitations).
    citations: citationsForVerification(snapshot, verification),
    followUps: [],
    source,
    ...(verification ? { verification } : {}),
  };
  return {
    ...base,
    ...(router ? { router } : {}),
    ...(delegation ? { delegation } : {}),
    ...(answerPlan ? { answerPlan } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
  };
}

/** Synthesize the client-side "grounded on" citations from the snapshot -
 *  LLM replies do not carry structured citations, so the deck grounds on what
 *  the model was told: the screen it read, the facts on it, and the record
 *  collections it could search. The deck (GroundedReply) then narrows these to
 *  the ones the answer actually references. */
function snapshotCitations(
  snapshot: ViewSnapshot | null,
): readonly { readonly label: string; readonly value?: string }[] {
  if (!snapshot) return [];
  const cites: { readonly label: string; readonly value?: string }[] = [
    // Always cite the screen the answer is grounded on (kept even when the
    // answer references none of the individual facts).
    { label: "screen", value: `${snapshot.routeLabel} - ${snapshot.headline}` },
  ];
  for (const f of snapshot.facts.slice(0, 12)) {
    cites.push({ label: f.key, value: f.value === null ? "-" : String(f.value) });
  }
  const records = snapshot.records ?? {};
  for (const [key, rows] of Object.entries(records)) {
    if (Array.isArray(rows) && rows.length > 0) {
      cites.push({ label: `records.${key}`, value: `${rows.length} row(s)` });
    }
  }
  return cites;
}

function citationsForVerification(
  snapshot: ViewSnapshot | null,
  verification: AnswerVerification | undefined,
): readonly { readonly label: string; readonly value?: string }[] {
  if (verification && verification.evidence_refs.length > 0) {
    return verification.evidence_refs.map((reference, index) => ({
      label: `evidence.${index + 1}`,
      value: reference,
    }));
  }
  return snapshotCitations(snapshot);
}

/** Callbacks for :func:`askBackendStream`. */
export interface StreamCallbacks {
  /** Fired for each streamed token delta (append to the live reply). */
  readonly onToken: (delta: string) => void;
  /** Verification lifecycle updates for the same assistant turn. */
  readonly onProgress?: (progress: VerificationProgress) => void;
  /** Atomically replace provisional text with a newer verified revision. */
  readonly onRevision?: (
    answer: string,
    revision: number,
    status: AnswerVerificationStatus,
  ) => void;
  /** Optional signal; abort to stop the stream and keep whatever streamed so far. */
  readonly signal?: AbortSignal;
  readonly sessionId?: string;
}

/** Typewriter cadence for the deterministic fallback, in ms per chunk.
 *  Small enough to feel live, large enough that Preact batches don't collapse
 *  the whole answer into one paint. Held in a mutable holder so tests can
 *  set it to 0 for hermetic runs (ES modules refuse const reassignment). */
export const fallbackTypewriter = { intervalMs: 12 };

/** Cosmetic pacing used only when SSE deltas arrive as one burst. Normal
 *  incremental model tokens bypass this delay entirely. */
export const streamBurstPacer = { intervalMs: 16 };

/** Split a string into small chunks (~one grapheme-cluster group at a time)
 *  so the deterministic fallback types in like the LLM stream does. Splits
 *  on whitespace-preserving boundaries so words never break mid-character. */
function chunksForTypewriter(text: string): string[] {
  // 3-4 char groups on average; whitespace is emitted attached to the
  // following chunk so the visible cursor "types" whole tokens.
  const out: string[] = [];
  const re = /\s*\S{1,4}|\s+$/g;
  for (const m of text.matchAll(re)) out.push(m[0]);
  return out.length > 0 ? out : [text];
}

/** Split a burst into paint-sized groups without replaying every model token
 *  through the slower deterministic fallback typewriter. */
function chunksForBurst(text: string): string[] {
  const words = text.match(/\s*\S+/g) ?? [];
  if (words.length <= 1) return text.match(/[\s\S]{1,12}/gu) ?? [text];
  const chunks: string[] = [];
  let chunk = "";
  let wordCount = 0;
  for (const word of words) {
    if (chunk && (wordCount >= 2 || chunk.length + word.length > 18)) {
      chunks.push(chunk);
      chunk = "";
      wordCount = 0;
    }
    chunk += word;
    wordCount += 1;
  }
  if (chunk) chunks.push(chunk);
  return chunks;
}

/**
 * Ask the chat backend over SSE (`POST /chat/stream`), streaming tokens as
 * they arrive. Resolves to the same shape as :func:`askBackend` once the
 * terminal `done` frame lands. Falls back to the deterministic answerer on
 * any transport error or an `error` frame; the fallback types in through
 * `onToken` chunk by chunk (cadence :data:`fallbackTypewriter.intervalMs`)
 * so the deck always LOOKS like it is streaming - even when the upstream
 * LLM is down, misconfigured, or refused the prompt. Read-only, no state
 * mutation.
 */
export async function askBackendStream(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  cb: StreamCallbacks,
): Promise<ProgressiveAnswer> {
  let emittedText = "";
  const emitToken = (delta: string): void => {
    emittedText += delta;
    cb.onToken(delta);
  };
  const visibleDelay = (intervalMs: number): number => {
    if (typeof document === "undefined") return intervalMs;
    const unfocused = typeof document.hasFocus === "function" && !document.hasFocus();
    return document.visibilityState === "hidden" || unfocused
      ? 0
      : intervalMs;
  };
  const emitTypewriter = async (text: string): Promise<void> => {
    const chunks = chunksForTypewriter(text);
    for (const c of chunks) {
      if (cb.signal?.aborted) return;
      emitToken(c);
      const interval = visibleDelay(fallbackTypewriter.intervalMs);
      if (interval > 0) {
        await new Promise((r) => setTimeout(r, interval));
      }
    }
  };
  const fallback = async (
    why: string,
  ): Promise<Answer & { readonly source: string }> => {
    const local = deterministicAnswer(prompt, snapshot, history);
    await emitTypewriter(local.text);
    if (cb.signal?.aborted) return stopped(emittedText);
    return { ...local, source: `deterministic (${why})` };
  };

  const stopped = (partial: string): Answer & { readonly source: string } => ({
    text: partial.length > 0 ? partial : "Stopped before any answer arrived.",
    citations: snapshotCitations(snapshot),
    followUps: [],
    source: "stopped",
  });

  // Token pacer: reasoning-family models (gpt-5, o1/o3/o4) spend ~1-2s
  // thinking then flush the whole answer as one TCP write, so the client
  // sees N tokens land in the same event-loop tick and repaints once - the
  // deck looks non-streaming even though the transport IS streaming. The
  // pacer drains the SSE token queue at a bounded cadence so a burst
  // arrival still types in visibly. When tokens arrive slower than the
  // cadence (classic chat models like gpt-4o-mini), the pacer adds no
  // delay - it only paces bursts.
  const tokenQueue: string[] = [];
  let queueDone = false;
  let pumpErr: unknown = null;
  let queueWake: (() => void) | null = null;
  let pumpPromise: Promise<void> | null = null;
  const startPump = (): void => {
    if (pumpPromise) return;
    pumpPromise = (async () => {
      try {
        while (true) {
          if (cb.signal?.aborted) return;
          if (tokenQueue.length === 0) {
            if (queueDone) return;
            await new Promise<void>((resolve) => {
              queueWake = resolve;
            });
            queueWake = null;
            continue;
          }
          let delta = tokenQueue.shift() as string;
          const queuedBurst = tokenQueue.length > 0;
          while (tokenQueue.length > 0 && delta.length < 96) {
            delta += tokenQueue.shift() as string;
          }
          // Preserve genuine model cadence. Only fan out a large frame or a
          // same-tick queue burst, and use paint-sized groups rather than the
          // slower deterministic fallback chunks.
          const burstMode = queuedBurst || delta.length > 48;
          const parts = burstMode ? chunksForBurst(delta) : [delta];
          for (const p of parts) {
            if (cb.signal?.aborted) return;
            emitToken(p);
            const delay = burstMode ? visibleDelay(streamBurstPacer.intervalMs) : 0;
            if (delay > 0) await new Promise((r) => setTimeout(r, delay));
          }
        }
      } catch (e) {
        pumpErr = e;
      }
    })();
  };
  const enqueueDelta = (delta: string): void => {
    tokenQueue.push(delta);
    queueWake?.();
  };
  const flushPump = async (): Promise<void> => {
    queueDone = true;
    queueWake?.();
    if (pumpPromise) await pumpPromise;
    if (pumpErr) throw pumpErr;
  };

  let response: Response;
  const requestId = newRequestId();
  try {
    response = await fetch(streamUrl(), {
      method: "POST",
      headers: await requestHeaders(true),
      body: JSON.stringify({
        request_id: requestId,
        prompt,
        session_id: cb.sessionId,
        view_context: viewContextWithUser(snapshot),
        history: toBackendHistory(history),
        verification_preferences: verificationPreferences(),
      }),
      signal: cb.signal ?? null,
      credentials: "omit",
    });
  } catch {
    if (cb.signal?.aborted) return stopped("");
    return fallback("offline");
  }
  if (response.status === 404 || response.status === 501) {
    return fallback("LLM not configured");
  }
  if (response.status === 422) {
    // The upstream content/jailbreak filter refused the prompt. This is a safe,
    // expected block (not an outage); label it distinctly so the operator sees
    // why rather than a generic transient error.
    return fallback("blocked by content policy");
  }
  if (!response.ok || response.body === null) {
    return fallback(`backend ${response.status}`);
  }
  startPump();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answerText = "";
  let doneData: Record<string, unknown> | null = null;
  let errored = false;
  let interrupted = false;
  let lastSequence = 0;
  let lastRevision = 0;
  let terminalSeen = false;
  const pendingRevisions: Array<{
    readonly answer: string;
    readonly revision: number;
    readonly status: AnswerVerificationStatus;
  }> = [];

  const handleFrame = (frame: string): void => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    const obj =
      typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
    const sequence =
      typeof obj.seq === "number" && Number.isInteger(obj.seq) ? obj.seq : null;
    if (sequence !== null) {
      if (sequence <= lastSequence) return;
      lastSequence = sequence;
    }
    const revision =
      typeof obj.revision === "number" && Number.isInteger(obj.revision)
        ? obj.revision
        : lastRevision;
    if (event === "token") {
      const delta = typeof obj.delta === "string" ? obj.delta : "";
      if (delta) {
        answerText += delta;
        enqueueDelta(delta);
      }
    } else if (event === "status" || event === "verification") {
      cb.onProgress?.({
        phase: typeof obj.phase === "string" ? obj.phase : event,
        label: typeof obj.label === "string" ? obj.label : "Checking answer",
        completed:
          typeof obj.completed === "number" && Number.isFinite(obj.completed)
            ? obj.completed
            : null,
        total:
          typeof obj.total === "number" && Number.isFinite(obj.total) ? obj.total : null,
        sources: parseRetrievalSourcePreviews(obj.sources),
      });
    } else if (event === "revision") {
      const replacement = typeof obj.answer === "string" ? obj.answer : null;
      const status = parseVerificationStatus(obj.status);
      if (replacement !== null && status !== null && revision > lastRevision) {
        lastRevision = revision;
        answerText = replacement;
        pendingRevisions.push({ answer: replacement, revision, status });
      }
    } else if (event === "done") {
      doneData = obj;
      terminalSeen = true;
    } else if (event === "error") {
      errored = true;
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary: RegExpMatchArray | null;
      while ((boundary = buffer.match(/\r?\n\r?\n/)) !== null) {
        const idx = boundary.index ?? 0;
        handleFrame(buffer.slice(0, idx));
        buffer = buffer.slice(idx + boundary[0].length);
      }
    }
  } catch {
    if (cb.signal?.aborted) {
      await flushPump();
      return stopped(answerText);
    }
    if (answerText === "") {
      await flushPump();
      return fallback("stream interrupted");
    }
    interrupted = true;
  }
  // Flush any multi-byte code point buffered by TextDecoder when the final
  // network chunk ended in the middle of UTF-8, then process a trailing frame
  // even when the server closed without a blank-line delimiter.
  buffer += decoder.decode();
  if (buffer.trim().length > 0) handleFrame(buffer);
  // Wait for the pacer to drain any tokens still queued from the burst
  // arrival before we hand the deck the final `done` payload.
  await flushPump();
  if (cb.signal?.aborted) return stopped(emittedText);

  if (errored && answerText === "") return fallback("stream error");
  if (errored || interrupted) {
    const why = errored ? "stream error" : "stream interrupted";
    return {
      text: answerText,
      citations: snapshotCitations(snapshot),
      followUps: [],
      source: `partial (${why})`,
    };
  }
  if (!terminalSeen && answerText !== "") {
    return {
      text: answerText,
      citations: snapshotCitations(snapshot),
      followUps: [],
      source: "partial (missing terminal verification)",
    };
  }
  if (answerText === "" && doneData === null) return fallback("empty stream");
  const pendingRevision = pendingRevisions.at(-1);
  if (pendingRevision !== undefined) {
    cb.onRevision?.(
      pendingRevision.answer,
      pendingRevision.revision,
      pendingRevision.status,
    );
  }

  const done: Record<string, unknown> = doneData ?? {};
  const finalText = typeof done.answer === "string" && done.answer ? done.answer : answerText;
  // Edge case: connection closed normally with a `done` frame but no answer
  // AND no streamed tokens (upstream returned an empty completion). Rather
  // than render an LLM-badged blank bubble, degrade to the deterministic
  // answer with a distinct label so the operator sees WHY.
  if (finalText === "") return fallback("upstream returned empty completion");
  const model = typeof done.model === "string" ? done.model : "llm";
  const latencyMs =
    typeof done.latency_ms === "number" && Number.isFinite(done.latency_ms)
      ? done.latency_ms
      : null;
  const router = parseRouter(done.router);
  const verification = parseAnswerVerification(done.verification);
  const delegation = parseDelegation(done.delegation);
  const answerPlan = parseAnswerPlan(done.answer_plan);
  const codeArtifacts = parseGroundedCodeArtifacts(done.code_artifacts);
  const chosen = router?.chose ?? model;
  const explicitSource = typeof done.source === "string" ? done.source : null;
  const source = explicitSource ?? (
    (latencyMs !== null && latencyMs >= 0 ? `llm:${chosen} · ${latencyMs}ms` : `llm:${chosen}`) +
    tokenSuffix(done.usage)
  );
  const base: Answer & { readonly source: string } = {
    text: finalText,
    citations: citationsForVerification(snapshot, verification),
    followUps: [],
    source,
    ...(verification ? { verification } : {}),
  };
  return {
    ...base,
    ...(router ? { router } : {}),
    ...(delegation ? { delegation } : {}),
    ...(answerPlan ? { answerPlan } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
  };
}

function parseRetrievalSourcePreviews(raw: unknown): readonly RetrievalSourcePreview[] {
  if (!Array.isArray(raw)) return [];
  const sources: RetrievalSourcePreview[] = [];
  for (const item of raw.slice(0, 8)) {
    if (typeof item !== "object" || item === null) continue;
    const record = item as Record<string, unknown>;
    const side = record.side_effect_class;
    if (
      typeof record.kind !== "string" ||
      typeof record.label !== "string" ||
      typeof record.detail !== "string" ||
      (side !== "read" && side !== "route" && side !== "simulate" && side !== "ground")
    ) continue;
    sources.push({
      kind: record.kind,
      label: record.label,
      detail: record.detail,
      side_effect_class: side,
    });
  }
  return sources;
}

const CODE_SHA256 = /^[0-9a-f]{64}$/;
const CODE_LANGUAGE = /^[A-Za-z0-9_+#.-]{1,32}$/;
const MAX_CODE_ARTIFACTS = 8;
const MAX_CODE_CHARS = 64 * 1024;

export function parseGroundedCodeArtifacts(raw: unknown): GroundedCodeArtifact[] {
  if (!Array.isArray(raw)) return [];
  const artifacts: GroundedCodeArtifact[] = [];
  for (const item of raw.slice(0, MAX_CODE_ARTIFACTS)) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    const sha256 = record.sha256;
    const artifactRef = record.artifact_ref;
    const language = record.language;
    const content = record.content;
    const status = record.validation_status;
    const detail = record.validation_detail;
    if (typeof sha256 !== "string" || !CODE_SHA256.test(sha256)) continue;
    if (artifactRef !== `code:sha256:${sha256}`) continue;
    if (typeof language !== "string" || !CODE_LANGUAGE.test(language)) continue;
    if (typeof content !== "string" || content.length > MAX_CODE_CHARS) continue;
    if (status !== "valid" && status !== "invalid" && status !== "not_checked") continue;
    if (detail !== null && typeof detail !== "string") continue;
    artifacts.push({
      artifact_ref: artifactRef,
      language,
      content,
      sha256,
      validation_status: status,
      validation_detail: detail,
    });
  }
  return artifacts;
}

export function parseAnswerPlan(raw: unknown): AnswerPlanMetadata | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const intents = ["definition", "why", "procedure", "comparison", "diagnosis", "status", "list", "summary", "proposal", "open_question"] as const;
  const details = ["brief", "standard", "deep"] as const;
  const formats = ["prose", "bullets", "numbered_steps", "table", "checklist", "mixed"] as const;
  const evidence = ["none", "screen", "catalog", "server_read_model", "agent_owned"] as const;
  const discuss = ["skip", "shadow", "selective"] as const;
  if (!intents.includes(record.intent as typeof intents[number])) return undefined;
  if (!details.includes(record.detail_level as typeof details[number])) return undefined;
  if (!formats.includes(record.format as typeof formats[number])) return undefined;
  if (!evidence.includes(record.evidence_requirement as typeof evidence[number])) return undefined;
  if (!discuss.includes(record.discuss as typeof discuss[number])) return undefined;
  if (typeof record.max_words !== "number" || !Number.isInteger(record.max_words) || record.max_words < 1 || record.max_words > 2000) return undefined;
  if (!Array.isArray(record.sections) || !record.sections.every((item) => typeof item === "string") || record.sections.length > 12) return undefined;
  const overrides = Array.isArray(record.explicit_overrides)
    ? record.explicit_overrides.filter((item): item is string => typeof item === "string").slice(0, 8)
    : [];
  return {
    intent: record.intent as AnswerPlanMetadata["intent"],
    detail_level: record.detail_level as AnswerPlanMetadata["detail_level"],
    format: record.format as AnswerPlanMetadata["format"],
    sections: record.sections,
    evidence_requirement: record.evidence_requirement as AnswerPlanMetadata["evidence_requirement"],
    max_words: record.max_words,
    discuss: record.discuss as AnswerPlanMetadata["discuss"],
    explicit_overrides: overrides,
  };
}

function parseDelegation(raw: unknown): DelegationMetadata | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  if (typeof record.primary_agent !== "string" || record.primary_agent.length === 0) {
    return undefined;
  }
  const contributors = Array.isArray(record.contributors)
    ? record.contributors.filter((item): item is string => typeof item === "string").slice(0, 8)
    : [];
  return {
    primary_agent: record.primary_agent,
    contributors,
    ...(typeof record.trace_ref === "string" && record.trace_ref.length > 0
      ? { trace_ref: record.trace_ref }
      : {}),
  };
}

function newRequestId(): string {
  const cryptoLike = globalThis.crypto as { randomUUID?: () => string } | undefined;
  return cryptoLike?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function parseVerificationStatus(raw: unknown): AnswerVerificationStatus | null {
  return raw === "verified" ||
      raw === "consistent" ||
      raw === "corrected" ||
      raw === "unverified"
    ? raw
    : null;
}

function parseAnswerVerification(raw: unknown): AnswerVerification | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  const status = parseVerificationStatus(record.status);
  if (status === null || typeof record.authority !== "string") return undefined;
  const refs = Array.isArray(record.evidence_refs)
    ? record.evidence_refs.filter((item): item is string => typeof item === "string")
    : [];
  const failedClaimIds = Array.isArray(record.failed_claim_ids)
    ? record.failed_claim_ids.filter((item): item is string => typeof item === "string")
    : [];
  const claims = parseAtomicClaims(record.claims);
  const manifest = parseEvidenceManifest(record.evidence_manifest);
  const semantic = parseSemanticVerification(record.semantic);
  const artifactPresent = record.claims !== undefined || record.evidence_manifest !== undefined;
  const malformedArtifact = artifactPresent && (claims === null || manifest === null);
  return {
    status: malformedArtifact ? "unverified" : status,
    authority: record.authority,
    checks_completed:
      typeof record.checks_completed === "number" ? record.checks_completed : 0,
    checks_total: typeof record.checks_total === "number" ? record.checks_total : 0,
    evidence_refs: refs,
    reason_code: malformedArtifact
      ? "malformed_verification_artifact"
      : (typeof record.reason_code === "string" ? record.reason_code : null),
    claims: claims ?? [],
    ...(manifest ? { evidence_manifest: manifest } : {}),
    failed_claim_ids: failedClaimIds,
    ...(semantic ? { semantic } : {}),
  };
}

function parseSemanticVerification(raw: unknown): SemanticVerification | null | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw !== "object" || Array.isArray(raw)) return null;
  const semantic = raw as Record<string, unknown>;
  const verdict = semantic.verdict;
  if (
    !["entailed", "contradicted", "unknown", "unavailable"].includes(String(verdict)) ||
    typeof semantic.provider !== "string" ||
    (semantic.model_id !== null && typeof semantic.model_id !== "string") ||
    typeof semantic.latency_ms !== "number" ||
    (semantic.entailment_score !== null && typeof semantic.entailment_score !== "number") ||
    (semantic.contradiction_score !== null &&
      typeof semantic.contradiction_score !== "number") ||
    (semantic.reason_code !== null && typeof semantic.reason_code !== "string")
  ) return null;
  return {
    verdict: verdict as SemanticVerification["verdict"],
    provider: semantic.provider,
    model_id: semantic.model_id as string | null,
    latency_ms: semantic.latency_ms,
    entailment_score: semantic.entailment_score as number | null,
    contradiction_score: semantic.contradiction_score as number | null,
    reason_code: semantic.reason_code as string | null,
  };
}

function parseAtomicClaims(raw: unknown): AtomicAnswerClaim[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) return null;
  const claims: AtomicAnswerClaim[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) return null;
    const claim = item as Record<string, unknown>;
    const kind = claim.kind;
    const status = claim.status;
    const span = claim.span;
    const spanRecord =
      typeof span === "object" && span !== null
        ? (span as Record<string, unknown>)
        : null;
    const start = spanRecord?.start;
    const end = spanRecord?.end;
    if (
      typeof claim.claim_id !== "string" ||
      !["id", "number", "percentage", "timestamp", "causal", "scope"].includes(
        String(kind),
      ) ||
      typeof claim.text !== "string" ||
      typeof start !== "number" ||
      typeof end !== "number" ||
      typeof claim.raw_value !== "string" ||
      typeof claim.normalized_value !== "string" ||
      (claim.unit !== null && typeof claim.unit !== "string") ||
      !validStringArray(claim.anchors) ||
      !["supported", "unsupported", "ambiguous"].includes(String(status)) ||
      !validStringArray(claim.evidence_refs) ||
      (claim.reason_code !== null && typeof claim.reason_code !== "string")
    ) return null;
    claims.push({
      claim_id: claim.claim_id,
      kind: kind as AtomicAnswerClaim["kind"],
      text: claim.text,
      span: { start, end },
      raw_value: claim.raw_value,
      normalized_value: claim.normalized_value,
      unit: claim.unit as string | null,
      anchors: claim.anchors as string[],
      status: status as AtomicClaimStatus,
      evidence_refs: claim.evidence_refs as string[],
      reason_code: claim.reason_code as string | null,
    });
  }
  return claims;
}

function parseEvidenceManifest(raw: unknown): AnswerEvidenceManifest | null | undefined {
  if (raw === undefined) return undefined;
  if (typeof raw !== "object" || raw === null) return null;
  const manifest = raw as Record<string, unknown>;
  if (!Array.isArray(manifest.entries)) return null;
  const entries: EvidenceManifestEntry[] = [];
  for (const item of manifest.entries) {
    if (typeof item !== "object" || item === null) return null;
    const entry = item as Record<string, unknown>;
    if (
      typeof entry.ref !== "string" ||
      typeof entry.path !== "string" ||
      typeof entry.field !== "string" ||
      typeof entry.kind !== "string" ||
      typeof entry.raw_value !== "string" ||
      typeof entry.normalized_value !== "string" ||
      !validStringArray(entry.anchors)
    ) return null;
    entries.push({
      ref: entry.ref,
      path: entry.path,
      field: entry.field,
      kind: entry.kind,
      raw_value: entry.raw_value,
      normalized_value: entry.normalized_value,
      anchors: entry.anchors,
    });
  }
  if (
    typeof manifest.schema_version !== "number" ||
    typeof manifest.manifest_id !== "string" ||
    typeof manifest.authority !== "string" ||
    (manifest.route_id !== null && typeof manifest.route_id !== "string") ||
    (manifest.captured_at !== null && typeof manifest.captured_at !== "string") ||
    typeof manifest.complete !== "boolean" ||
    typeof manifest.source_entry_count !== "number"
  ) return null;
  return {
    schema_version: manifest.schema_version,
    manifest_id: manifest.manifest_id,
    authority: manifest.authority,
    route_id: manifest.route_id as string | null,
    captured_at: manifest.captured_at as string | null,
    complete: manifest.complete,
    source_entry_count: manifest.source_entry_count,
    entries,
  };
}

function validStringArray(raw: unknown): raw is string[] {
  return Array.isArray(raw) && raw.every((item) => typeof item === "string");
}

function extractString(payload: unknown, key: string): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const v = (payload as Record<string, unknown>)[key];
  return typeof v === "string" ? v : null;
}

function extractNumber(payload: unknown, key: string): number | null {
  if (typeof payload !== "object" || payload === null) return null;
  const v = (payload as Record<string, unknown>)[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Total token count from an OpenAI/Azure `usage` block, or null. */
function totalTokensOf(raw: unknown): number | null {
  if (typeof raw !== "object" || raw === null) return null;
  const u = raw as Record<string, unknown>;
  const total = u.total_tokens;
  if (typeof total === "number" && Number.isFinite(total) && total >= 0) return Math.round(total);
  const prompt = u.prompt_tokens;
  const completion = u.completion_tokens;
  if (
    typeof prompt === "number" &&
    Number.isFinite(prompt) &&
    typeof completion === "number" &&
    Number.isFinite(completion)
  ) {
    return Math.round(prompt + completion);
  }
  return null;
}

/** `" · <N> tok"` suffix for the source badge, or `""` when usage is absent. */
function tokenSuffix(usage: unknown): string {
  const total = totalTokensOf(usage);
  if (total === null) return "";
  const label =
    total >= 1000 ? `${(total / 1000).toFixed(total >= 10000 ? 0 : 1)}k` : `${total}`;
  return ` · ${label} tok`;
}

function parseRouter(raw: unknown): RouterSnapshot | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const r = raw as Record<string, unknown>;
  const chose = typeof r.chose === "string" ? r.chose : null;
  if (chose === null) return undefined;
  const reason = typeof r.reason === "string" ? r.reason : "";
  const rawCandidates = Array.isArray(r.candidates) ? r.candidates : [];
  const candidates: RouterCandidate[] = [];
  for (const c of rawCandidates) {
    if (typeof c !== "object" || c === null) continue;
    const cr = c as Record<string, unknown>;
    const deployment = typeof cr.deployment === "string" ? cr.deployment : null;
    if (deployment === null) continue;
    const p50 =
      typeof cr.p50_ms === "number" && Number.isFinite(cr.p50_ms) ? cr.p50_ms : null;
    const p95 =
      typeof cr.p95_ms === "number" && Number.isFinite(cr.p95_ms) ? cr.p95_ms : null;
    const samples =
      typeof cr.samples === "number" && Number.isFinite(cr.samples) ? cr.samples : 0;
    const historyRaw = Array.isArray(cr.history_ms) ? cr.history_ms : [];
    const history: number[] = [];
    for (const h of historyRaw) {
      if (typeof h === "number" && Number.isFinite(h) && h >= 0) history.push(h);
    }
    candidates.push({ deployment, p50_ms: p50, p95_ms: p95, samples, history_ms: history });
  }
  return { chose, reason, candidates };
}

// ---------------------------------------------------------------------------
// Write-direction chat (POST /chat/action) - propose actions or manage incidents
// ---------------------------------------------------------------------------

function actionUrl(): string {
  return `${chatUrl()}/action`;
}

/** A stable idempotency key for one submit attempt, so a duplicated / retried
 *  request collapses server-side (Huginn dedup) instead of enqueuing a second
 *  action. Uses crypto.randomUUID when available, else a timestamp+random. */
function newIdempotencyKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return `act-${c.randomUUID()}`;
  return `act-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Result of submitting an operator command to the typed pipeline. */
export interface ActionSubmitResult {
  /** True when the proposal was accepted and published for judgment. */
  readonly submitted: boolean;
  /** HTTP status (0 on a transport error). */
  readonly status: number;
  /** The ActionType the command mapped to, when submitted. */
  readonly actionType?: string;
  /** The correlation id to track the proposal (Trace panel / audit). */
  readonly correlationId?: string;
  /** Why it was refused: `rbac_capability` | `deny_override_forbidden` |
   *  `invalid_principal` | `unmapped_action_intent` | `not_wired` | `error`. */
  readonly reason?: string;
  /** The capability the operator was missing (for `rbac_capability`). */
  readonly requiredCapability?: string;
  /** Server-authored operator communication for incident prepare/confirm. */
  readonly message?: string;
  readonly incidentId?: string;
  readonly incidentState?: string;
  readonly created?: boolean;
}

/**
 * Submit an operator command to `POST /chat/action`. Ordinary mutations publish
 * an `ActionProposal` into the typed pipeline. Incident requests use the
 * audited built-in lifecycle workflow and require same-session confirmation.
 * RBAC is enforced server-side from the validated token; a Reader gets `403`.
 *
 * Never throws: a transport error or an unwired endpoint resolves to a
 * `submitted: false` result the deck can render as a plain message.
 */
export async function submitAction(
  prompt: string,
  sessionId: string | null,
  signal?: AbortSignal,
): Promise<ActionSubmitResult> {
  let response: Response;
  try {
    response = await fetch(actionUrl(), {
      method: "POST",
      headers: await requestHeaders(true),
      body: JSON.stringify({
        prompt,
        session_id: sessionId ?? undefined,
        idempotency_key: newIdempotencyKey(),
      }),
      signal: signal ?? null,
      credentials: "omit",
    });
  } catch {
    return { submitted: false, status: 0, reason: "error" };
  }
  if (response.status === 404 || response.status === 501) {
    return { submitted: false, status: response.status, reason: "not_wired" };
  }
  let payload: Record<string, unknown> = {};
  try {
    const parsed = await response.json();
    if (typeof parsed === "object" && parsed !== null) {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    /* fall through - use the status only */
  }
  const submitted = payload.submitted === true;
  const result: ActionSubmitResult = {
    submitted,
    status: response.status,
    ...(typeof payload.action_type === "string" ? { actionType: payload.action_type } : {}),
    ...(typeof payload.correlation_id === "string"
      ? { correlationId: payload.correlation_id }
      : {}),
    ...(typeof payload.reason === "string" ? { reason: payload.reason } : {}),
    ...(typeof payload.required_capability === "string"
      ? { requiredCapability: payload.required_capability }
      : {}),
    ...(typeof payload.message === "string" ? { message: payload.message } : {}),
    ...(typeof payload.incident_id === "string" ? { incidentId: payload.incident_id } : {}),
    ...(typeof payload.incident_state === "string"
      ? { incidentState: payload.incident_state }
      : {}),
    ...(typeof payload.created === "boolean" ? { created: payload.created } : {}),
  };
  return result;
}

/** A plain-language deck message describing an action-submit result. */
export function renderActionResult(r: ActionSubmitResult): string {
  if (r.actionType?.startsWith("incident.") && r.message) return r.message;
  if (r.submitted) {
    return (
      `Submitted "${r.actionType ?? "action"}" to the pipeline for judgment. ` +
      `Nothing runs until Forseti judges it and (if high-risk) an approver signs off - ` +
      `execution is shadow-first. Track it by correlation ${r.correlationId ?? "-"} in the Trace panel.`
    );
  }
  switch (r.reason) {
    case "rbac_capability":
      return (
        "Your role can't submit actions - that needs the Contributor capability " +
        `(${r.requiredCapability ?? "author-draft-pr"}). This console stays read-only for you.`
      );
    case "deny_override_forbidden":
      return (
        "That exact action was already denied, and re-asking can't override a deny. " +
        "If the situation changed, raise it with an approver instead of re-submitting."
      );
    case "invalid_principal":
      return "I couldn't identify your account, so I did not submit that action. Try signing in again.";
    case "incident_confirmation_required":
    case "incident_details_required":
    case "incident_creation_cancelled":
    case "incident_confirmation_expired":
    case "incident_confirmation_invalid":
    case "incident_session_required":
      return r.message ?? "The incident request needs more information before it can continue.";
    case "unmapped_action_intent":
      return "I recognised that as a command, but it maps to no known action yet, so I did not submit it.";
    case "not_wired":
      return "Action submission is not enabled on this deployment (read-only console).";
    default:
      return "I could not submit that action (the action endpoint did not respond).";
  }
}
