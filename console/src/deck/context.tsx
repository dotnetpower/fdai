/**
 * View-context provider - the "what the operator currently sees" seam.
 *
 * Every route publishes a compact structured snapshot describing the
 * data it is currently rendering. The CommandDeck reads this snapshot
 * to answer questions grounded in ONLY what is on screen right now -
 * matching the console's read-only, narrator-is-a-translator contract
 * (architecture.instructions.md § Action Ontology).
 *
 * Single responsibility: hold the snapshot + notify subscribers. It
 * does no rendering, no I/O, no LLM calls.
 */

import type { ComponentChildren } from "preact";
import { createContext } from "preact";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "preact/hooks";

/** A single fact the deck can quote back at the operator. */
export interface ViewFact {
  /** Short label used in the digest column, e.g. "eps", "tile #4". */
  readonly key: string;
  /** Human-readable value or JSON-serialisable primitive. */
  readonly value: string | number | boolean | null;
  /** Optional group heading for the digest column. */
  readonly group?: string;
}

/**
 * One term this screen renders that an operator might not know - a label,
 * abbreviation, or on-screen chip (e.g. `correlation id`, `waterfall`, a
 * `corr-*` chip). The answerer quotes `plain` when the operator asks "what is
 * X", so a screen is self-describing: it declares its own vocabulary instead
 * of relying on a hand-written per-route answerer.
 */
export interface GlossaryTerm {
  /** The word/label as the operator sees or says it, e.g. "correlation id". */
  readonly term: string;
  /** Plain-language meaning, one sentence, no jargon. */
  readonly plain: string;
  /** The precise internal token, e.g. "correlation_id" (shown dimmed). */
  readonly tech?: string;
  /** A route the operator can open to dig deeper, e.g. "trace". */
  readonly seeAlso?: string;
  /**
   * The `records` column whose VALUES this term explains, e.g.
   * "correlation_id". When the operator asks about a value that appears in
   * that column (a `corr-*` chip), the answerer recognises it as this term.
   */
  readonly match?: string;
}

/** A structured snapshot for one route. */
export interface ViewSnapshot {
  /** Panel id, matches the hash route (`live`, `dashboard`, ...). */
  readonly routeId: string;
  /** Human title shown in the deck header, e.g. "Live cockpit". */
  readonly routeLabel: string;
  /**
   * One or two lines: what this screen is FOR and what an operator does here.
   * Grounds "what is this screen / why am I looking at this" without a
   * per-route answerer. Optional during rollout; the route-contract test
   * (Phase 2) makes it required for every published route.
   */
  readonly purpose?: string;
  /** A one-line headline, e.g. "60 tiles - 4 eps - 3 failed". */
  readonly headline: string;
  /** Structured facts the answerer can pattern-match against. */
  readonly facts: readonly ViewFact[];
  /**
   * The vocabulary this screen renders. The answerer resolves "what is X"
   * and value-chip questions (e.g. "what is corr-j") from these entries, so a
   * new screen becomes explainable by declaring terms - not by adding code.
   */
  readonly glossary?: readonly GlossaryTerm[];
  /** Bulk records the answerer can search (tiles, audit rows, HIL items). */
  readonly records?: Readonly<Record<string, readonly Record<string, unknown>[]>>;
  /** ISO timestamp captured on publish. */
  readonly capturedAt: string;
}

interface ViewContextValue {
  readonly snapshot: ViewSnapshot | null;
  readonly setSnapshot: (s: ViewSnapshot | null) => void;
}

const Ctx = createContext<ViewContextValue>({
  snapshot: null,
  setSnapshot: () => {},
});

export function ViewContextProvider({ children }: { readonly children: ComponentChildren }) {
  const [snapshot, setSnapshot] = useState<ViewSnapshot | null>(null);
  const value = useMemo(() => ({ snapshot, setSnapshot }), [snapshot]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Read the current published snapshot (returns null between routes). */
export function useViewContext(): ViewSnapshot | null {
  return useContext(Ctx).snapshot;
}

/**
 * Publish a snapshot for the current route. Call from useEffect with the
 * route's own state as the dependency. The provider replaces the whole
 * snapshot; there is no partial merge.
 *
 * Throttled at :data:`PUBLISH_MIN_INTERVAL_MS` so a high-frequency
 * route (Live cockpit at rAF-batched dispatch rate) does not thrash
 * the provider: without throttling, every ~16ms dep change would call
 * ``setSnapshot`` which re-renders the entire ``ViewContextProvider``
 * subtree - i.e. the whole app - and pins CPU + GC until the tab OOMs.
 * The throttle keeps published snapshots at most twice per second,
 * with a trailing flush so the final dep value always lands.
 */
const PUBLISH_MIN_INTERVAL_MS = 500;

export function usePublishViewContext(
  build: () => ViewSnapshot | null,
  deps: readonly unknown[],
): void {
  const { setSnapshot } = useContext(Ctx);
  const stableBuild = useCallback(build, deps); // eslint-disable-line react-hooks/exhaustive-deps
  const lastPublishedAtRef = useRef(0);
  const trailingTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const publish = () => {
      lastPublishedAtRef.current = Date.now();
      setSnapshot(stableBuild());
    };
    const now = Date.now();
    const elapsed = now - lastPublishedAtRef.current;

    // Clear any pending trailing publish - the next scheduling below
    // will re-arm it if we still owe one.
    if (trailingTimerRef.current !== null) {
      window.clearTimeout(trailingTimerRef.current);
      trailingTimerRef.current = null;
    }

    if (elapsed >= PUBLISH_MIN_INTERVAL_MS) {
      publish();
    } else {
      // Trailing edge: schedule ONE publish at the end of the window
      // so the last dep value always lands even if the deps stopped
      // changing mid-throttle.
      const delay = PUBLISH_MIN_INTERVAL_MS - elapsed;
      trailingTimerRef.current = window.setTimeout(() => {
        trailingTimerRef.current = null;
        publish();
      }, delay);
    }

    return () => {
      // On unmount, cancel any pending trailing publish so it does not
      // fire after the component is gone. Do NOT clear the snapshot -
      // navigation transitions want the previous route's context to
      // survive until the next route publishes.
      if (trailingTimerRef.current !== null) {
        window.clearTimeout(trailingTimerRef.current);
        trailingTimerRef.current = null;
      }
    };
  }, [stableBuild, setSnapshot]);
}
