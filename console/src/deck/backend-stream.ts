import { answer as deterministicAnswer, type Answer } from "./answerer";
import {
  citationsForVerification,
  createBackendRequestPayload,
  snapshotCitations,
} from "./backend-context";
import { requestHeaders, streamUrl } from "./backend-endpoints";
import {
  newRequestId,
  parseConfirmedAnswerSegment,
  parseEvidenceBranch,
  parseAnswerVerification,
  parseDelegation,
  parseEvidenceFreshnessContext,
  parseInvestigationActivity,
  parseInvestigationMilestone,
  parseRetrievalSourcePreviews,
  parseResourceContext,
  parseRouter,
  parseVerificationStatus,
  tokenSuffix,
} from "./backend-normalizers";
import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
  parseIncidentCandidates,
  parseModelTrace,
  parseTurnTiming,
} from "./backend-parsers";
import type {
  AnswerVerificationStatus,
  ActionDraft,
  BackendTurn,
  ConfirmedAnswerSegment,
  ProgressiveAnswer,
  StreamCallbacks,
} from "./backend-types";
import type { ViewSnapshot } from "./context";
import { parseTrajectoryDetail } from "./trajectory-detail";
import { parseIntentGraph, parseIntentGraphEvidence } from "./intent-graph";
import { chartArtifactText } from "./rich-parse";
import { parsePresentationArtifact } from "./presentation-artifact";

export const fallbackTypewriter = { intervalMs: 12 };
export const streamBurstPacer = { intervalMs: 16 };
export const MAX_DECK_SSE_FRAME_CHARS = 256 * 1024;

let sequenceGapCount = 0;
let confirmedSegmentCount = 0;
let partialTerminalCount = 0;

export function streamProtocolMetricsSnapshot(): {
  readonly sequenceGaps: number;
  readonly confirmedSegments: number;
  readonly partialTerminals: number;
} {
  return {
    sequenceGaps: sequenceGapCount,
    confirmedSegments: confirmedSegmentCount,
    partialTerminals: partialTerminalCount,
  };
}

function chunksForTypewriter(text: string): string[] {
  const chunks: string[] = [];
  const pattern = /\s*\S{1,4}|\s+$/g;
  for (const match of text.matchAll(pattern)) chunks.push(match[0]);
  return chunks.length > 0 ? chunks : [text];
}

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

export async function askBackendStream(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  callbacks: StreamCallbacks,
): Promise<ProgressiveAnswer> {
  let emittedText = "";
  const emitToken = (delta: string): void => {
    emittedText += delta;
    callbacks.onToken(delta);
  };
  const visibleDelay = (intervalMs: number): number => {
    if (typeof document === "undefined") return intervalMs;
    const unfocused = typeof document.hasFocus === "function" && !document.hasFocus();
    return document.visibilityState === "hidden" || unfocused ? 0 : intervalMs;
  };
  const emitTypewriter = async (text: string): Promise<void> => {
    for (const chunk of chunksForTypewriter(text)) {
      if (callbacks.signal?.aborted) return;
      emitToken(chunk);
      const interval = visibleDelay(fallbackTypewriter.intervalMs);
      if (interval > 0) await new Promise((resolve) => setTimeout(resolve, interval));
    }
  };
  const fallback = async (why: string): Promise<Answer & { readonly source: string }> => {
    const local = deterministicAnswer(prompt, snapshot, history);
    await emitTypewriter(local.text);
    if (callbacks.signal?.aborted) return stopped(emittedText);
    return { ...local, source: `deterministic (${why})` };
  };
  const stopped = (partial: string): Answer & { readonly source: string } => ({
    text: partial.length > 0 ? partial : "Stopped before any answer arrived.",
    citations: snapshotCitations(snapshot),
    followUps: [],
    source: "stopped",
  });

  const tokenQueue: string[] = [];
  let queueDone = false;
  let pumpError: unknown = null;
  let queueWake: (() => void) | null = null;
  let pumpPromise: Promise<void> | null = null;
  const startPump = (): void => {
    if (pumpPromise) return;
    pumpPromise = (async () => {
      try {
        while (true) {
          if (callbacks.signal?.aborted) return;
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
          const burstMode = queuedBurst || delta.length > 48;
          const parts = burstMode ? chunksForBurst(delta) : [delta];
          for (const part of parts) {
            if (callbacks.signal?.aborted) return;
            emitToken(part);
            const delay = burstMode ? visibleDelay(streamBurstPacer.intervalMs) : 0;
            if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }
      } catch (error) {
        pumpError = error;
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
    if (pumpError) throw pumpError;
  };

  let response: Response;
  const requestId = newRequestId();
  try {
    response = await fetch(streamUrl(), {
      method: "POST",
      headers: await requestHeaders(true),
      body: JSON.stringify(
        createBackendRequestPayload(
          prompt,
          snapshot,
          history,
          callbacks.sessionId,
          requestId,
          callbacks.conversationBinding,
          callbacks.attachments,
          callbacks.targetAgent,
        ),
      ),
      signal: callbacks.signal ?? null,
      credentials: "omit",
    });
  } catch {
    if (callbacks.signal?.aborted) return stopped("");
    return fallback("offline");
  }
  if (response.status === 404 || response.status === 501) return fallback("LLM not configured");
  if (response.status === 422) return fallback("blocked by content policy");
  if (!response.ok || response.body === null) return fallback(`backend ${response.status}`);
  startPump();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answerText = "";
  let doneData: Record<string, unknown> | null = null;
  let errored = false;
  let errorCode: string | null = null;
  let interrupted = false;
  let turnInterrupted = false;
  let lastSequence = 0;
  let lastRevision = 0;
  let sequenceGap = false;
  let terminalSeen = false;
  let confirmedSegment: ConfirmedAnswerSegment | undefined;
  const pendingRevisions: Array<{
    readonly answer: string;
    readonly revision: number;
    readonly status: AnswerVerificationStatus;
  }> = [];

  const handleFrame = (frame: string): void => {
    if (terminalSeen) return;
    if (frame.length > MAX_DECK_SSE_FRAME_CHARS) {
      throw new Error("backend stream frame exceeds the size limit");
    }
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
    const object = typeof parsed === "object" && parsed !== null
      ? parsed as Record<string, unknown>
      : {};
    const sequence = typeof object.seq === "number" && Number.isInteger(object.seq)
      ? object.seq
      : null;
    if (
      object.v === 1 &&
      (object.request_id !== requestId || sequence === null)
    ) {
      tokenQueue.length = 0;
      answerText = "";
      doneData = null;
      pendingRevisions.length = 0;
      confirmedSegment = undefined;
      sequenceGap = true;
      terminalSeen = true;
      return;
    }
    if (sequence !== null) {
      if (sequence <= lastSequence) return;
      if (sequence !== lastSequence + 1) sequenceGap = true;
      lastSequence = sequence;
    }
    const revision = typeof object.revision === "number" && Number.isInteger(object.revision)
      ? object.revision
      : lastRevision;
    if (event === "token") {
      const delta = typeof object.delta === "string" ? object.delta : "";
      if (delta && revision === lastRevision) {
        answerText += delta;
        enqueueDelta(delta);
      }
    } else if (event === "status" || event === "verification") {
      callbacks.onProgress?.({
        phase: typeof object.phase === "string" ? object.phase : event,
        label: typeof object.label === "string" ? object.label : "Checking answer",
        completed: typeof object.completed === "number" && Number.isFinite(object.completed)
          ? object.completed
          : null,
        total: typeof object.total === "number" && Number.isFinite(object.total)
          ? object.total
          : null,
        sources: parseRetrievalSourcePreviews(object.sources),
      });
    } else if (event === "activity") {
      const activity = parseInvestigationActivity(object);
      if (activity !== null) callbacks.onActivity?.(activity);
    } else if (event === "milestone") {
      const milestone = parseInvestigationMilestone(object);
      if (milestone !== null) callbacks.onMilestone?.(milestone);
    } else if (event === "branch") {
      const branch = parseEvidenceBranch(object);
      if (branch !== null) callbacks.onBranch?.(branch);
    } else if (event === "revision") {
      const replacement = typeof object.answer === "string" ? object.answer : null;
      const status = parseVerificationStatus(object.status);
      if (replacement !== null && status !== null && revision > lastRevision) {
        lastRevision = revision;
        answerText = replacement;
        pendingRevisions.push({ answer: replacement, revision, status });
      }
    } else if (event === "confirmed") {
      const confirmed = parseConfirmedAnswerSegment(object, revision);
      if (
        confirmed !== null &&
        confirmed.revision === lastRevision &&
        confirmed.revision > (confirmedSegment?.revision ?? -1)
      ) {
        confirmedSegment = confirmed;
        confirmedSegmentCount += 1;
      }
    } else if (event === "done") {
      doneData = object;
      terminalSeen = true;
    } else if (event === "interrupted") {
      turnInterrupted = true;
      terminalSeen = true;
    } else if (event === "error") {
      errored = true;
      errorCode = typeof object.code === "string" ? object.code : null;
      if (errorCode === "content_policy_block") {
        answerText = "";
        terminalSeen = true;
      }
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary: RegExpMatchArray | null;
      while ((boundary = buffer.match(/\r?\n\r?\n/)) !== null) {
        const index = boundary.index ?? 0;
        handleFrame(buffer.slice(0, index));
        buffer = buffer.slice(index + boundary[0].length);
        if (terminalSeen) break;
      }
      if (terminalSeen) {
        void reader.cancel().catch(() => undefined);
        break;
      }
      if (buffer.length > MAX_DECK_SSE_FRAME_CHARS) {
        throw new Error("backend stream frame exceeds the size limit");
      }
    }
  } catch {
    if (callbacks.signal?.aborted) {
      await flushPump();
      return stopped(answerText);
    }
    if (answerText === "") {
      await flushPump();
      return fallback("stream interrupted");
    }
    interrupted = true;
  }
  buffer += decoder.decode();
  if (buffer.trim().length > 0) handleFrame(buffer);
  await flushPump();
  if (callbacks.signal?.aborted) return stopped(emittedText);
  if (turnInterrupted) return stopped(answerText);

  if (errorCode === "content_policy_block") return fallback("blocked by content policy");
  if (errored && answerText === "") return fallback("stream error");
  if (errored || interrupted) {
    partialTerminalCount += 1;
    const why = errored ? "stream error" : "stream interrupted";
    return {
      text: answerText,
      citations: snapshotCitations(snapshot),
      followUps: [],
      source: `partial (${why})`,
    };
  }
  if (sequenceGap) {
    sequenceGapCount += 1;
    partialTerminalCount += 1;
    const gapDone: Record<string, unknown> = doneData ?? {};
    const terminalAnswer = typeof gapDone.answer === "string" ? gapDone.answer : "";
    return {
      text: terminalAnswer || answerText,
      citations: snapshotCitations(snapshot),
      followUps: [],
      source: "partial (sequence gap)",
    };
  }
  if (!terminalSeen && answerText !== "") {
    partialTerminalCount += 1;
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
    callbacks.onRevision?.(
      pendingRevision.answer,
      pendingRevision.revision,
      pendingRevision.status,
    );
  }
  if (confirmedSegment !== undefined) callbacks.onConfirmed?.(confirmedSegment);

  const done: Record<string, unknown> = doneData ?? {};
  const model = typeof done.model === "string" ? done.model : "llm";
  const latencyMs = typeof done.latency_ms === "number" && Number.isFinite(done.latency_ms)
    ? done.latency_ms
    : null;
  const router = parseRouter(done.router);
  const verification = parseAnswerVerification(done.verification);
  const presentationArtifact = parsePresentationArtifact(done.presentation_artifact, verification);
  const canonicalAnswer = typeof done.answer === "string" && done.answer ? done.answer : answerText;
  const finalText = presentationArtifact
    ? canonicalAnswer
    : chartArtifactText(done.chart_artifact) ?? canonicalAnswer;
  if (finalText === "") return fallback("upstream returned empty completion");
  const delegation = parseDelegation(done.delegation);
  const answerPlan = parseAnswerPlan(done.answer_plan);
  const answerPlanning = parseAnswerPlanning(done.answer_planning);
  const actionDraft = parseActionDraft(done.action_draft);
  const codeArtifacts = parseGroundedCodeArtifacts(done.code_artifacts);
  const incidentCandidates = parseIncidentCandidates(done.incident_candidates);
  const resourceContext = parseResourceContext(done.resource_context);
  const evidenceFreshnessContext = parseEvidenceFreshnessContext(
    done.evidence_freshness_context,
  );
  const modelTrace = parseModelTrace(done.model_trace);
  const turnTiming = parseTurnTiming(done.turn_timing);
  const trajectoryDetail = parseTrajectoryDetail(done.trajectory_detail);
  const intentGraph = parseIntentGraph(done.intent_graph);
  const intentGraphEvidence = parseIntentGraphEvidence(done.intent_graph_evidence);
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
    ...(answerPlanning ? { answerPlanning } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
    ...(incidentCandidates.length > 0 ? { incidentCandidates } : {}),
    ...(presentationArtifact ? { presentationArtifact } : {}),
    ...(confirmedSegment ? { confirmed: confirmedSegment } : {}),
    ...(actionDraft ? { actionDraft } : {}),
    ...(resourceContext ? { resourceContext } : {}),
    ...(evidenceFreshnessContext ? { evidenceFreshnessContext } : {}),
    ...(modelTrace ? { modelTrace } : {}),
    ...(turnTiming ? { turnTiming } : {}),
    ...(trajectoryDetail ? { trajectoryDetail } : {}),
    ...(intentGraph ? { intentGraph } : {}),
    ...(intentGraphEvidence ? {
      intentGraphEvidence,
      evidenceMode: intentGraphEvidence.evidence_mode,
    } : {}),
  };
}

function parseActionDraft(value: unknown): ActionDraft | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (
    typeof record.action_type !== "string" ||
    record.action_type.length === 0 ||
    record.action_type.length > 200 ||
    typeof record.arguments !== "object" ||
    record.arguments === null ||
    Array.isArray(record.arguments) ||
    (record.session_id !== null && typeof record.session_id !== "string") ||
    typeof record.idempotency_key !== "string" ||
    record.idempotency_key.length === 0 ||
    record.idempotency_key.length > 200
  ) return undefined;
  return {
    actionType: record.action_type,
    arguments: record.arguments as Record<string, unknown>,
    sessionId: record.session_id as string | null,
    idempotencyKey: record.idempotency_key,
  };
}
