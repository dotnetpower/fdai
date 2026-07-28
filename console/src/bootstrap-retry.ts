const STARTUP_RETRY_DELAYS_MS = [
  250,
  500,
  1_000,
  2_000,
  4_000,
  5_000,
  5_000,
  5_000,
  5_000,
] as const;

interface StartupRetryOptions {
  readonly delaysMs?: readonly number[];
  readonly wait?: (delayMs: number) => Promise<void>;
}

function isFetchNetworkError(error: unknown): error is TypeError {
  if (!(error instanceof TypeError)) return false;
  const message = error.message.toLowerCase();
  return message.includes("fetch")
    || message.includes("networkerror")
    || message.includes("network error")
    || message.includes("load failed");
}

function waitFor(delayMs: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
}

export async function withStartupTransportRetry<T>(
  operation: () => Promise<T>,
  options: StartupRetryOptions = {},
): Promise<T> {
  const delaysMs = options.delaysMs ?? STARTUP_RETRY_DELAYS_MS;
  const wait = options.wait ?? waitFor;

  for (const delayMs of delaysMs) {
    try {
      return await operation();
    } catch (error) {
      if (!isFetchNetworkError(error)) throw error;
      await wait(delayMs);
    }
  }

  return operation();
}
