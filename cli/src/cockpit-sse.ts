import { safeDisplayLine } from "./display-text.js";

export interface StageFrame {
  event_id: string;
  correlation_id: string;
  stage: string;
  phase: string;
  ts: string;
  detail?: Record<string, unknown>;
  error?: string;
}

export const MAX_COCKPIT_SSE_FRAME_CHARS = 256 * 1024;

export async function consumeSse(
  url: string,
  onFrame: (frame: StageFrame) => void,
  onStatus: (status: string) => void,
  signal: AbortSignal,
  authorization?: string,
): Promise<void> {
  try {
    const response = await fetch(url, {
      signal,
      headers: authorization
        ? { accept: "text/event-stream", authorization }
        : { accept: "text/event-stream" },
      redirect: "error",
    });
    if (!response.ok || !response.body) {
      onStatus(`stream ${response.status}`);
      return;
    }
    const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
    if (!contentType.startsWith("text/event-stream")) {
      onStatus("stream invalid content type");
      await response.body.cancel().catch(() => undefined);
      return;
    }
    onStatus("live");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const decoded = decoder.decode(value, { stream: true });
        buffer += decoded;
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          if (block.length > MAX_COCKPIT_SSE_FRAME_CHARS) {
            throw new Error("SSE frame exceeds the size limit");
          }
          let event = "message";
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (event === "stage" && data) {
            try {
              const frame = decodeStageFrame(JSON.parse(data) as unknown);
              if (frame) onFrame(frame);
            } catch {
              /* ignore */
            }
          }
        }
        if (buffer.length > MAX_COCKPIT_SSE_FRAME_CHARS) {
          throw new Error("SSE frame exceeds the size limit");
        }
      }
      if (!signal.aborted) onStatus("stream closed");
    } catch (error) {
      await reader.cancel(error).catch(() => undefined);
      throw error;
    } finally {
      reader.releaseLock();
    }
  } catch (error) {
    if (!signal.aborted) {
      onStatus(`stream error: ${safeDisplayLine((error as Error).message, 256)}`);
    }
  }
}

function decodeStageFrame(value: unknown): StageFrame | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const frame = value as Record<string, unknown>;
  const eventId = boundedLine(frame.event_id, 1024);
  const correlationId = boundedLine(frame.correlation_id, 1024);
  const stage = boundedLine(frame.stage, 64);
  const phase = boundedLine(frame.phase, 64);
  const ts = boundedLine(frame.ts, 128);
  if (!eventId || !correlationId || !stage || !phase || !ts) return null;
  if (frame.detail !== undefined && !isRecord(frame.detail)) return null;
  if (frame.error !== undefined && typeof frame.error !== "string") return null;
  return {
    event_id: eventId,
    correlation_id: correlationId,
    stage,
    phase,
    ts,
    ...(frame.detail === undefined ? {} : { detail: frame.detail }),
    ...(frame.error === undefined
      ? {}
      : { error: safeDisplayLine(frame.error, 4096) }),
  };
}

function boundedLine(value: unknown, maximum: number): string | null {
  if (typeof value !== "string") return null;
  const normalized = safeDisplayLine(value, maximum);
  return normalized.length > 0 ? normalized : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
