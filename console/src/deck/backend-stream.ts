import type { Answer } from "./answerer";
import { hasAdvisoryResponse, parseActionDraftExplanation, parseAdvisoryResponse } from "./adaptive-answer";
import {
  citationsForVerification,
  createBackendRequestPayload,
  snapshotCitations,
} from "./backend-context";
import { requestHeaders, streamUrl } from "./backend-endpoints";
import { semanticUnavailable } from "./backend-unavailable";
import {
  newRequestId,
  parseConfirmedAnswerSegment,
  parseEvidenceBranch,
  parseAnswerVerification,
  parseDelegation,
  parseEvidenceFreshnessContext,
  parseInvestigationActivity,
  parseInvestigationMilestone,
  parseModelUsage,
  parseRetrievalSourcePreviews,
  parseResourceContext,
  parseRouter,
  isSemanticDirectResponseSource,
  parseSemanticProjectionReceipt,
  parseVerificationStatus,
  semanticDirectResponseSource,
  tokenSuffix,
} from "./backend-normalizers";
import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseConversationDocumentArtifact,
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
import { normalizeIncidentBinding } from "./conversation-sessions";

export const fallbackTypewriter = { intervalMs: 12 };
export const streamBurstPacer = { intervalMs: 16 };
export const MAX_DECK_SSE_FRAME_CHARS = 256 * 1024;
const MAX_PROGRESS_TEXT_CHARS = 512;

let sequenceGapCount = 0;
let protocolErrorCount = 0;
let confirmedSegmentCount = 0;
let partialTerminalCount = 0;

export function streamProtocolMetricsSnapshot(): {
  readonly sequenceGaps: number;
  readonly protocolErrors: number;
  readonly confirmedSegments: number;
  readonly partialTerminals: number;
} {
  return {
    sequenceGaps: sequenceGapCount,
    protocolErrors: protocolErrorCount,
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

function boundedProgressText(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_PROGRESS_TEXT_CHARS
    ? value
    : fallback;
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
  let pumpGeneration = 0;
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
  const discardEmittedDraft = (): void => {
    pumpGeneration += 1;
    tokenQueue.length = 0;
    emittedText = "";
    answerText = "";
    callbacks.onRevision?.("", lastRevision + 1, "unverified");
  };
  const unavailable = async (why: string): Promise<Answer & { readonly source: string }> => {
    const result = semanticUnavailable(why);
    await emitTypewriter(result.text);
    if (callbacks.signal?.aborted) return stopped(emittedText);
    return result;
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
    const generation = pumpGeneration;
    pumpPromise = (async () => {
      try {
        while (true) {
          if (callbacks.signal?.aborted || generation !== pumpGeneration) return;
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
            if (callbacks.signal?.aborted || generation !== pumpGeneration) return;
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
          callbacks.semanticPlanningProfile,
          callbacks.handoverGoalId,
        ),
      ),
      signal: callbacks.signal ?? null,
      credentials: "omit",
    });
  } catch {
    if (callbacks.signal?.aborted) return stopped("");
    return unavailable("offline");
  }
  if (response.status === 404 || response.status === 501) {
    return unavailable("model not configured");
  }
  if (response.status === 422) return unavailable("blocked by content policy");
  if (!response.ok || response.body === null) return unavailable(`backend ${response.status}`);
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
  let protocolError: string | null = null;
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
      protocolError = "malformed stream frame";
      protocolErrorCount += 1;
      terminalSeen = true;
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
      protocolError = sequence === null
        ? "missing stream sequence"
        : "stream request mismatch";
      protocolErrorCount += 1;
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
        phase: boundedProgressText(object.phase, event),
        label: boundedProgressText(object.label, "Checking answer"),
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
      return unavailable("stream interrupted");
    }
    interrupted = true;
  }
  buffer += decoder.decode();
  if (buffer.trim().length > 0) handleFrame(buffer);
  const done: Record<string, unknown> = doneData ?? {};
  const advisoryAnswer = parseAdvisoryResponse(done, requestId);
  const adaptiveAnswer = advisoryAnswer ?? parseActionDraftExplanation(done, requestId);
  if (hasAdvisoryResponse(done) && adaptiveAnswer === undefined) {
    discardEmittedDraft();
    await flushPump();
    return unavailable("invalid advisory response");
  }
  if (advisoryAnswer && (
    protocolError !== null || errored || interrupted || sequenceGap ||
    confirmedSegment !== undefined || pendingRevisions.length > 0
  )) {
    if (sequenceGap) sequenceGapCount += 1;
    discardEmittedDraft();
    await flushPump();
    return unavailable("invalid advisory stream");
  }
  const verification = parseAnswerVerification(done.verification);
  const parsedSemanticReceipt = parseSemanticProjectionReceipt(done.semantic_receipt);
  const semanticReceipt = parsedSemanticReceipt?.request_id === requestId
    ? parsedSemanticReceipt
    : undefined;
  const terminalAnswer = typeof done.answer === "string" && done.answer.trim()
    ? done.answer
    : null;
  const typedEvidenceHoldClaim = verification?.status === "unverified" &&
    (verification.reason_code === "semantic_evidence_held" ||
      verification.reason_code === "semantic_evidence_incomplete");
  const typedEvidenceHoldReceiptValid = typedEvidenceHoldClaim &&
    semanticReceipt?.disposition === "held" &&
    semanticReceipt.reason_code === verification.reason_code;
  if (typedEvidenceHoldClaim && (!typedEvidenceHoldReceiptValid || terminalAnswer === null)) {
    discardEmittedDraft();
    await flushPump();
    return unavailable(
      terminalAnswer === null
        ? "typed evidence hold missing canonical answer"
        : "typed evidence hold receipt invalid",
    );
  }
  await flushPump();
  if (callbacks.signal?.aborted) return stopped(emittedText);
  if (turnInterrupted) return stopped(answerText);

  if (protocolError !== null) {
    if (emittedText.length === 0) return unavailable(protocolError);
    partialTerminalCount += 1;
    return {
      text: emittedText,
      citations: snapshotCitations(snapshot),
      followUps: [],
      source: `partial (${protocolError})`,
    };
  }

  if (errorCode === "content_policy_block") return unavailable("blocked by content policy");
  if (errored && answerText === "") return unavailable("stream error");
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
  if (answerText === "" && doneData === null) return unavailable("empty stream");
  const pendingRevision = pendingRevisions.at(-1);
  if (pendingRevision !== undefined) {
    callbacks.onRevision?.(
      pendingRevision.answer,
      pendingRevision.revision,
      pendingRevision.status,
    );
  }
  if (confirmedSegment !== undefined && !advisoryAnswer) callbacks.onConfirmed?.(confirmedSegment);

  const model = typeof done.model === "string" ? done.model : "llm";
  const latencyMs = typeof done.latency_ms === "number" && Number.isFinite(done.latency_ms)
    ? done.latency_ms
    : null;
  const router = parseRouter(done.router);
  const presentationArtifact = parsePresentationArtifact(done.presentation_artifact, verification);
  const documentArtifact = parseConversationDocumentArtifact(done.document_artifact);
  const canonicalAnswer = terminalAnswer ?? answerText;
  const finalText = presentationArtifact
    ? canonicalAnswer
    : chartArtifactText(done.chart_artifact) ?? canonicalAnswer;
  if (finalText === "") return unavailable("upstream returned empty completion");
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
  const modelUsage = parseModelUsage(done.usage);
  const turnTiming = parseTurnTiming(done.turn_timing);
  const trajectoryDetail = parseTrajectoryDetail(done.trajectory_detail);
  const intentGraph = parseIntentGraph(done.intent_graph);
  const intentGraphEvidence = parseIntentGraphEvidence(done.intent_graph_evidence);
  const conversationBinding = normalizeIncidentBinding(done.conversation_context);
  const chosen = router?.chose ?? model;
  const explicitSource = typeof done.source === "string" ? done.source : null;
  const directResponse = isSemanticDirectResponseSource(explicitSource);
  const source = directResponse
    ? semanticDirectResponseSource(chosen, latencyMs, done.usage)
    : explicitSource ?? (
    (latencyMs !== null && latencyMs >= 0 ? `llm:${chosen} · ${latencyMs}ms` : `llm:${chosen}`) +
    tokenSuffix(done.usage)
  );
  const base: Answer & { readonly source: string } = {
    text: finalText,
    citations: directResponse || advisoryAnswer ? [] : citationsForVerification(snapshot, verification),
    followUps: [],
    source,
    ...(verification ? { verification } : {}),
  };
  return {
    ...base,
    ...(adaptiveAnswer ? { adaptiveAnswer } : {}),
    ...(router ? { router } : {}),
    ...(delegation ? { delegation } : {}),
    ...(answerPlan ? { answerPlan } : {}),
    ...(answerPlanning ? { answerPlanning } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
    ...(incidentCandidates.length > 0 ? { incidentCandidates } : {}),
    ...(presentationArtifact ? { presentationArtifact } : {}),
    ...(documentArtifact ? { documentArtifact } : {}),
    ...(confirmedSegment && !advisoryAnswer ? { confirmed: confirmedSegment } : {}),
    ...(actionDraft ? { actionDraft } : {}),
    ...(resourceContext ? { resourceContext } : {}),
    ...(evidenceFreshnessContext ? { evidenceFreshnessContext } : {}),
    ...(modelTrace ? { modelTrace } : {}),
    ...(latencyMs !== null && latencyMs >= 0 ? { modelLatencyMs: latencyMs } : {}),
    ...(modelUsage ? { modelUsage } : {}),
    ...(turnTiming ? { turnTiming } : {}),
    ...(trajectoryDetail ? { trajectoryDetail } : {}),
    ...(intentGraph ? { intentGraph } : {}),
    ...(intentGraphEvidence ? {
      intentGraphEvidence,
      evidenceMode: intentGraphEvidence.evidence_mode,
    } : {}),
    ...(semanticReceipt ? { semanticReceipt } : {}),
    ...(conversationBinding ? { conversationBinding } : {}),
  };
}

export function parseActionDraft(value: unknown): ActionDraft | undefined {
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
