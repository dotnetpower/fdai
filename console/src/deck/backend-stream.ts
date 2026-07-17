import { answer as deterministicAnswer, type Answer } from "./answerer";
import {
  citationsForVerification,
  createBackendRequestPayload,
  snapshotCitations,
} from "./backend-context";
import { requestHeaders, streamUrl } from "./backend-endpoints";
import {
  newRequestId,
  parseAnswerVerification,
  parseDelegation,
  parseRetrievalSourcePreviews,
  parseRouter,
  parseVerificationStatus,
  tokenSuffix,
} from "./backend-normalizers";
import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
} from "./backend-parsers";
import type {
  AnswerVerificationStatus,
  BackendTurn,
  ProgressiveAnswer,
  StreamCallbacks,
} from "./backend-types";
import type { ViewSnapshot } from "./context";

export const fallbackTypewriter = { intervalMs: 12 };
export const streamBurstPacer = { intervalMs: 16 };

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
    const object = typeof parsed === "object" && parsed !== null
      ? parsed as Record<string, unknown>
      : {};
    const sequence = typeof object.seq === "number" && Number.isInteger(object.seq)
      ? object.seq
      : null;
    if (sequence !== null) {
      if (sequence <= lastSequence) return;
      lastSequence = sequence;
    }
    const revision = typeof object.revision === "number" && Number.isInteger(object.revision)
      ? object.revision
      : lastRevision;
    if (event === "token") {
      const delta = typeof object.delta === "string" ? object.delta : "";
      if (delta) {
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
    } else if (event === "revision") {
      const replacement = typeof object.answer === "string" ? object.answer : null;
      const status = parseVerificationStatus(object.status);
      if (replacement !== null && status !== null && revision > lastRevision) {
        lastRevision = revision;
        answerText = replacement;
        pendingRevisions.push({ answer: replacement, revision, status });
      }
    } else if (event === "done") {
      doneData = object;
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
        const index = boundary.index ?? 0;
        handleFrame(buffer.slice(0, index));
        buffer = buffer.slice(index + boundary[0].length);
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
    callbacks.onRevision?.(
      pendingRevision.answer,
      pendingRevision.revision,
      pendingRevision.status,
    );
  }

  const done: Record<string, unknown> = doneData ?? {};
  const finalText = typeof done.answer === "string" && done.answer ? done.answer : answerText;
  if (finalText === "") return fallback("upstream returned empty completion");
  const model = typeof done.model === "string" ? done.model : "llm";
  const latencyMs = typeof done.latency_ms === "number" && Number.isFinite(done.latency_ms)
    ? done.latency_ms
    : null;
  const router = parseRouter(done.router);
  const verification = parseAnswerVerification(done.verification);
  const delegation = parseDelegation(done.delegation);
  const answerPlan = parseAnswerPlan(done.answer_plan);
  const answerPlanning = parseAnswerPlanning(done.answer_planning);
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
    ...(answerPlanning ? { answerPlanning } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
  };
}
