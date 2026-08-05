import { useEffect, useRef } from "preact/hooks";
import { useTransientFlag } from "./use-transient-flag";

export const CONTENT_UPDATE_PULSE_MS = 1_350;

export type ContentUpdateKey = string | number | boolean | null | undefined;

export function didContentUpdate(
  previousKey: ContentUpdateKey,
  nextKey: ContentUpdateKey,
): boolean {
  return !Object.is(previousKey, nextKey);
}

export function shouldPulseContentUpdate({
  initialized,
  active,
  previousKey,
  nextKey,
}: {
  readonly initialized: boolean;
  readonly active: boolean;
  readonly previousKey: ContentUpdateKey;
  readonly nextKey: ContentUpdateKey;
}): boolean {
  return initialized && !active && didContentUpdate(previousKey, nextKey);
}

export function useContentUpdatePulse(updateKey: ContentUpdateKey): boolean {
  const previousRef = useRef<{ initialized: boolean; key: ContentUpdateKey }>({
    initialized: false,
    key: undefined,
  });
  const [active, activate] = useTransientFlag(CONTENT_UPDATE_PULSE_MS);

  useEffect(() => {
    const previous = previousRef.current;
    if (shouldPulseContentUpdate({
      initialized: previous.initialized,
      active,
      previousKey: previous.key,
      nextKey: updateKey,
    })) activate();
    previousRef.current = { initialized: true, key: updateKey };
  }, [activate, active, updateKey]);

  return active;
}
