import { chatUrl, requestHeaders } from "./backend-endpoints";

export type BusyMode = "queue" | "interrupt" | "steer";
export type BusyFailure = "unavailable" | "conflict" | "pending";

export interface BusyPending {
  readonly inputId: string;
  readonly sequence: number;
  readonly disposition: "queued" | "interrupting" | "steered";
  readonly expiresAt: string;
}

export interface BusyState {
  readonly sessionId: string;
  readonly mode: BusyMode;
  readonly active: boolean;
  readonly revision: number;
  readonly pending: readonly BusyPending[];
}

export class BusyClientError extends Error {
  constructor(readonly reason: BusyFailure) {
    super(`busy input ${reason}`);
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function boundedId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 256 &&
    value.trim() === value && !/[\x00-\x1f]/.test(value);
}

function validDate(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 &&
    /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) &&
    Number.isFinite(Date.parse(value));
}

export function decodeBusyState(value: unknown, sessionId: string): BusyState | null {
  const source = record(value);
  if (!source || source.session_id !== sessionId ||
    !["queue", "interrupt", "steer"].includes(String(source.mode)) ||
    typeof source.active !== "boolean" ||
    !Number.isSafeInteger(source.revision) || (source.revision as number) < 1 ||
    !Array.isArray(source.pending) || source.pending.length > 32) return null;

  const pending: BusyPending[] = [];
  const ids = new Set<string>();
  let previous = -1;
  for (const raw of source.pending) {
    const item = record(raw);
    const input = record(item?.input);
    if (!item || !input || !boundedId(input.input_id) ||
      !Number.isSafeInteger(item.sequence) || (item.sequence as number) <= previous ||
      !["queued", "interrupting", "steered"].includes(String(item.disposition)) ||
      item.status !== "pending" || !validDate(input.expires_at) ||
      ids.has(input.input_id)) return null;
    ids.add(input.input_id);
    previous = item.sequence as number;
    pending.push({
      inputId: input.input_id,
      sequence: previous,
      disposition: item.disposition as BusyPending["disposition"],
      expiresAt: input.expires_at,
    });
  }
  return {
    sessionId,
    mode: source.mode as BusyMode,
    active: source.active,
    revision: source.revision as number,
    pending,
  };
}

async function busyRequest(
  path: string,
  options: { method?: "GET" | "POST" | "PUT"; body?: object; signal?: AbortSignal } = {},
): Promise<Response> {
  try {
    return await fetch(`${chatUrl()}/busy-input${path}`, {
      method: options.method ?? "GET",
      headers: await requestHeaders(options.body !== undefined),
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
      ...(options.signal ? { signal: options.signal } : {}),
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new BusyClientError("unavailable");
  }
}

function requireStatus(response: Response, status: number): void {
  if (response.status === 409) throw new BusyClientError("conflict");
  if (response.status !== status) throw new BusyClientError(
    response.status === 202 ? "pending" : "unavailable",
  );
}

export async function inspectBusy(sessionId: string, signal?: AbortSignal): Promise<BusyState> {
  if (!boundedId(sessionId)) throw new BusyClientError("unavailable");
  const response = await busyRequest(
    `?session_id=${encodeURIComponent(sessionId)}`,
    signal ? { signal } : {},
  );
  requireStatus(response, 200);
  try {
    const reader = response.body?.getReader();
    if (!reader) throw new BusyClientError("unavailable");
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const frame = await reader.read();
      if (frame.done) break;
      size += frame.value.byteLength;
      if (size > 64_000) {
        await reader.cancel();
        throw new BusyClientError("unavailable");
      }
      chunks.push(frame.value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const state = decodeBusyState(JSON.parse(raw) as unknown, sessionId);
    if (state) return state;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
  }
  throw new BusyClientError("unavailable");
}

async function propose(
  path: string,
  method: "POST" | "PUT",
  body: object,
): Promise<void> {
  const response = await busyRequest(path, { method, body });
  // A proposal receipt, even HTTP 200, is not authoritative busy-session state.
  if (response.status === 409) throw new BusyClientError("conflict");
  if (response.status !== 200 && response.status !== 202) {
    throw new BusyClientError("unavailable");
  }
}

export async function submitBusy(sessionId: string, inputId: string, content: string): Promise<void> {
  if (!boundedId(sessionId) || !boundedId(inputId) ||
    !content.trim() || new TextEncoder().encode(content).length > 4_000) {
    throw new BusyClientError("unavailable");
  }
  await propose("", "POST", {
    session_id: sessionId,
    input_id: inputId,
    idempotency_key: inputId,
    content,
    kind: "prose",
  });
}

export async function setBusyMode(state: BusyState, mode: BusyMode): Promise<void> {
  await propose("/mode", "PUT", {
    session_id: state.sessionId,
    mode,
    revision: state.revision,
  });
}

export async function cancelBusyCurrent(state: BusyState): Promise<void> {
  await propose("/cancel-current", "POST", {
    session_id: state.sessionId,
    revision: state.revision,
  });
}
