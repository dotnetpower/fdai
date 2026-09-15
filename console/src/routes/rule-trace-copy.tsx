import { useEffect, useRef, useState } from "preact/hooks";
import { t } from "./i18n/evidence";

type CopyState = "idle" | "copied" | "failed";

export async function copyTraceValue(
  clipboard: Pick<Clipboard, "writeText"> | undefined,
  value: string,
): Promise<Exclude<CopyState, "idle">> {
  if (clipboard === undefined) return "failed";
  try {
    await clipboard.writeText(value);
    return "copied";
  } catch {
    return "failed";
  }
}

export function TraceCopyButton({
  label,
  text,
}: {
  readonly label: string;
  readonly text: string;
}) {
  const [state, setState] = useState<CopyState>("idle");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (resetTimer.current !== null) clearTimeout(resetTimer.current);
  }, []);

  async function copy(): Promise<void> {
    const result = await copyTraceValue(navigator.clipboard, text);
    setState(result);
    if (resetTimer.current !== null) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => setState("idle"), 2_000);
  }

  return (
    <button
      type="button"
      class={`btn btn-small copy-btn trace-copy-button is-${state}`}
      onClick={() => void copy()}
      aria-live="polite"
    >
      {state === "copied"
        ? t("evidence.trace.copied")
        : state === "failed"
          ? t("evidence.trace.copyFailed")
          : label}
    </button>
  );
}
