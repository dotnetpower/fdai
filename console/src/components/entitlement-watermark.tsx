/**
 * Trial expiry watermark: a persistent lower-right notice on every Console view.
 *
 * It renders whenever the latest Operator entitlement stamp withholds acting work, or
 * when the stamp is missing or stale. It is semi-transparent, passes pointer input
 * through, cannot be dismissed, and is announced to assistive technology. It reads no
 * preference or setting, so nothing but a current `none` stamp hides it.
 *
 * The notice text lives in this file instead of the shared message catalog so the
 * signed framework surface covers what the watermark says as well as how it renders.
 * The watermark is an availability notice: it grants and removes no authority.
 */

import type { JSX } from "preact";
import { useCallback, useEffect, useRef, useState } from "preact/hooks";

import {
  entitlementStamps,
  FIRST_STAMP_WAIT_MS,
  PROBE_INTERVAL_MS,
  watermarkNotice,
  type EntitlementStampStore,
  type WatermarkNotice,
} from "../entitlement-state";
import { getLocale, type Locale } from "../i18n";

const MESSAGES: Record<Locale, Record<WatermarkNotice, readonly [string, string]>> = {
  en: {
    "evaluation-ended": [
      "Evaluation period ended",
      "Observation continues. Acting work is unavailable until FDAI is activated.",
    ],
    "not-activated": [
      "FDAI is not activated",
      "Observation continues. Acting work is unavailable until FDAI is activated.",
    ],
  },
  ko: {
    "evaluation-ended": [
      "평가 기간이 끝났습니다",
      "관찰은 계속되지만, FDAI를 활성화할 때까지 변경 작업을 사용할 수 없습니다.",
    ],
    "not-activated": [
      "FDAI가 활성화되지 않았습니다",
      "관찰은 계속되지만, FDAI를 활성화할 때까지 변경 작업을 사용할 수 없습니다.",
    ],
  },
};

const RECHECK_INTERVAL_MS = 15_000;

const STYLE: JSX.CSSProperties = {
  position: "fixed",
  // Sit above the Command Deck invoke bar and clear of the activity rail on narrow screens.
  inset: "auto 24px calc(var(--deck-invoke-height, 44px) + 16px) auto",
  zIndex: 2147483647,
  display: "grid",
  gap: "2px",
  width: "auto",
  height: "auto",
  maxWidth: "min(440px, calc(100vw - 96px))",
  margin: 0,
  padding: 0,
  border: 0,
  overflow: "visible",
  background: "transparent",
  color: "var(--cs-text, #2c333a)",
  fontFamily: "var(--cs-font, sans-serif)",
  opacity: 0.55,
  textAlign: "right",
  textWrap: "balance",
  wordBreak: "keep-all",
  pointerEvents: "none",
  userSelect: "none",
};

const TITLE_STYLE: JSX.CSSProperties = {
  fontSize: "var(--cs-type-section-title-size, 18px)",
  fontWeight: 600,
  lineHeight: "var(--cs-type-section-title-line-height, 1.35)",
};

const DETAIL_STYLE: JSX.CSSProperties = {
  fontSize: "var(--cs-type-compact-size, 13px)",
  lineHeight: "var(--cs-type-compact-line-height, 1.5)",
};

function monotonicNow(): number {
  return globalThis.performance.now();
}

export interface EntitlementWatermarkProps {
  /** One authenticated Operator read whose response carries a fresh stamp. */
  readonly probe: () => Promise<unknown>;
  readonly store?: EntitlementStampStore;
  readonly clock?: () => number;
}

export function EntitlementWatermark(props: EntitlementWatermarkProps) {
  const store = props.store ?? entitlementStamps;
  const clock = props.clock ?? monotonicNow;
  const startedAt = useRef(clock());
  const probeRef = useRef(props.probe);
  probeRef.current = props.probe;
  const node = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);
  const rerender = useCallback(() => setTick((tick) => tick + 1), []);

  useEffect(() => store.subscribe(rerender), [store, rerender]);

  useEffect(() => {
    // A failed probe only ages the stamp, and an aged stamp shows the watermark.
    // The probe shares the client's cached data-source read with panel source gating,
    // so the mount-time probe rarely adds a request.
    const probe = () => {
      void probeRef.current().catch(() => undefined);
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") probe();
    };
    probe();
    const first = window.setTimeout(rerender, FIRST_STAMP_WAIT_MS);
    const recheck = window.setInterval(rerender, RECHECK_INTERVAL_MS);
    const refresh = window.setInterval(probe, PROBE_INTERVAL_MS);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(recheck);
      window.clearInterval(refresh);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [rerender]);

  const notice = watermarkNotice(store.latest(), {
    startedAt: startedAt.current,
    now: clock(),
  });

  useEffect(() => {
    const element = node.current;
    if (element === null || typeof element.showPopover !== "function") return undefined;
    // The top layer keeps the notice above every z-index. Modal dialogs and fullscreen
    // views also enter the top layer, so re-showing the notice after either one keeps it
    // above them.
    const raise = () => {
      if (!element.isConnected) return;
      if (element.matches(":popover-open")) element.hidePopover();
      element.showPopover();
    };
    raise();
    const observer = new MutationObserver((records) => {
      if (records.some((record) => record.target instanceof HTMLDialogElement && record.target.open)) {
        raise();
      }
    });
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["open"] });
    document.addEventListener("fullscreenchange", raise);
    return () => {
      observer.disconnect();
      document.removeEventListener("fullscreenchange", raise);
    };
  }, [notice]);

  if (notice === null) return null;
  const [title, detail] = MESSAGES[getLocale()][notice];
  return (
    <div
      ref={node}
      popover="manual"
      class="entitlement-watermark"
      data-notice={notice}
      aria-live="polite"
      aria-atomic="true"
      style={STYLE}
    >
      <strong style={TITLE_STYLE}>{title}</strong>
      <span style={DETAIL_STYLE}>{detail}</span>
    </div>
  );
}
