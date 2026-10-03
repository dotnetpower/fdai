/**
 * Navigation consent for Command Deck links.
 *
 * A deck link to another screen closes the docked or full-workspace conversation, so the deck asks
 * first and navigates only after the operator agrees. In-page anchors, new-tab or modified clicks,
 * and downloads are never intercepted. The floating layout keeps the conversation open across
 * routes, so its links navigate directly.
 */

import { useEffect, useRef } from "preact/hooks";
import { t } from "./i18n/conversation-layer";
import { panelForId } from "../panels";
import { navigate, parseConsoleRoute } from "../router";

export interface LeaveTarget {
  readonly href: string;
  readonly screen: string;
}

/** The parts of a primary click on a link that decide whether it leaves the conversation. */
export interface LeaveClick {
  readonly button: number;
  readonly modified: boolean;
  readonly href: string | null;
  readonly target: string;
  readonly download: boolean;
}

/** Return the absolute URL a click would open in place of the conversation, or null when it stays. */
export function leaveHref(click: LeaveClick, base: string): string | null {
  if (click.button !== 0 || click.modified || click.download || click.target) return null;
  const href = click.href?.trim() ?? "";
  if (!href || href.startsWith("#")) return null;
  try {
    const url = new URL(href, base);
    if (!/^https?:$/.test(url.protocol)) return null;
    const current = new URL(base);
    const samePage = url.origin === current.origin && url.pathname === current.pathname &&
      url.search === current.search;
    return samePage && url.hash ? null : url.href;
  } catch {
    return null;
  }
}

/** Name the screen a link opens: the Console panel label, or the host for another site. */
export function leaveScreenLabel(
  href: string,
  origin: string,
  panelLabel: (panelId: string) => string,
): string {
  const url = new URL(href, origin);
  if (url.origin !== origin) return url.host;
  const route = parseConsoleRoute(url.pathname, url.search);
  return route.matched ? panelLabel(route.panelId) : url.pathname;
}

/** Resolve a click inside the deck to the screen it would open, or null when it stays in place. */
export function leaveTargetFromClick(event: MouseEvent): LeaveTarget | null {
  const element = event.target instanceof Element ? event.target : null;
  const anchor = element?.closest<HTMLAnchorElement>("a[href]") ?? null;
  if (!anchor) return null;
  const href = leaveHref({
    button: event.button,
    modified: event.metaKey || event.ctrlKey || event.shiftKey || event.altKey,
    href: anchor.getAttribute("href"),
    target: anchor.target,
    download: anchor.hasAttribute("download"),
  }, window.location.href);
  if (href === null) return null;
  return {
    href,
    screen: leaveScreenLabel(href, window.location.origin, (panelId) => panelForId(panelId).label),
  };
}

/** Open the consented screen through the Console router, or the browser for another site. */
export function followLeaveTarget(target: LeaveTarget): void {
  const url = new URL(target.href);
  if (url.origin === window.location.origin) navigate(`${url.pathname}${url.search}${url.hash}`);
  else window.location.assign(url.href);
}

export function DeckLeaveConsent({
  target,
  onClose,
}: {
  readonly target: LeaveTarget | null;
  readonly onClose: (open: boolean) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !target || dialog.open) return;
    dialog.returnValue = "";
    dialog.showModal();
  }, [target]);
  if (!target) return null;
  return (
    <dialog
      ref={dialogRef}
      class="cs-deck-leave"
      aria-labelledby="deck-leave-title"
      aria-describedby="deck-leave-body"
      onClose={(event) => onClose(event.currentTarget.returnValue === "open")}
      // The dialog owns Escape and Tab while it is open; the deck's close key and focus loop must
      // not act behind it.
      onKeyDown={(event) => {
        if (event.key === "Escape" || event.key === "Tab") event.stopPropagation();
      }}
    >
      <form class="cs-deck-leave-form" method="dialog">
        <h2 class="cs-deck-leave-title" id="deck-leave-title">
          {t("deck.leave.title", { screen: target.screen })}
        </h2>
        <p class="cs-deck-leave-body" id="deck-leave-body">
          {t("deck.leave.body", { screen: target.screen })}
        </p>
        <div class="cs-deck-leave-actions">
          <button type="submit" class="cs-deck-leave-stay" value="stay" autoFocus>
            {t("deck.leave.stay")}
          </button>
          <button type="submit" class="cs-deck-leave-open" value="open">
            {t("deck.leave.open", { screen: target.screen })}
          </button>
        </div>
      </form>
    </dialog>
  );
}
