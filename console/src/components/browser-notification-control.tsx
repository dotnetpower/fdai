import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  acknowledgeBrowserAlertDeliveryForClaim,
  BROWSER_NOTIFICATION_DELIVERY_CHANGED_EVENT,
  BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
  browserAlertNotificationData,
  isBrowserNotificationDeliveryChange,
  browserAlertDeliveryStatusForStorageKey,
  browserAlertForLiveEvent,
  decodeBrowserAlertAcknowledgementFragment,
  isBrowserNotificationPreferenceStorageKey,
  isBrowserNotificationPreferenceChange,
  browserNotificationsSupported,
  claimBrowserAlertDelivery,
  readBrowserAlertAcknowledgementToken,
  readBrowserAlertDeliveryStatus,
  readBrowserNotificationPreference,
  recordBrowserAlertDelivered,
  releaseBrowserAlertDelivery,
  requireBrowserNotificationPreferenceWrite,
  writeBrowserNotificationPreference,
  type BrowserAlertKind,
  type BrowserAlert,
  type BrowserAlertDeliveryStatus,
} from "../browser-notifications";
import {
  prepareBrowserNotificationTransport,
  type BrowserNotificationTransport,
} from "../browser-notification-transport";
import { useExclusiveBrowserStreamLeader } from "../hooks/browser-stream-leader";
import { useLiveStream } from "../hooks/use-live-stream";
import {
  browserNotificationText,
  type BrowserNotificationTextKey,
} from "./i18n/browser-notifications";
import { NotificationBellIcon } from "./notification-bell-icon";
import { findingNotificationText } from "./i18n/finding-notifications";
import {
  findingBrowserAlert, findingNeedsAttention, markFindingPending, rememberFinding,
  type CurrentFinding,
} from "../findings";

interface Props {
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
  readonly presentation?: "header" | "settings";
  readonly findings?: readonly CurrentFinding[];
}

type ControlState = "off" | "enabling" | "on" | "blocked" | "unsupported" | "error";
const COMPACT_STATUS_QUERY = "(max-width: 640px)";
const EMPTY_FINDINGS: readonly CurrentFinding[] = [];

const CONTROL_LABEL_KEYS: Readonly<Record<ControlState, BrowserNotificationTextKey>> = {
  off: "off",
  enabling: "enabling",
  on: "on",
  blocked: "blocked",
  unsupported: "unsupported",
  error: "error",
};

const CONTROL_STATE_KEYS: Readonly<Record<ControlState, BrowserNotificationTextKey>> = {
  off: "stateOff",
  enabling: "stateEnabling",
  on: "stateOn",
  blocked: "stateBlocked",
  unsupported: "stateUnsupported",
  error: "stateError",
};

const DELIVERY_STATE_KEYS: Readonly<Record<BrowserAlertDeliveryStatus, BrowserNotificationTextKey>> = {
  ready: "stateOn",
  delivered: "stateDelivered",
  acknowledged: "stateAcknowledged",
};

const ALERT_TITLE_KEYS: Readonly<Record<Exclude<BrowserAlertKind, "finding">, BrowserNotificationTextKey>> = {
  approval: "approvalTitle",
  denied: "deniedTitle",
  failed: "failedTitle",
};

const ALERT_BODY_KEYS: Readonly<Record<Exclude<BrowserAlertKind, "finding">, BrowserNotificationTextKey>> = {
  approval: "approvalBody",
  denied: "deniedBody",
  failed: "failedBody",
};

export function BrowserNotificationControl({
  client,
  principalId,
  presentation = "header",
  findings = EMPTY_FINDINGS,
}: Props) {
  const activePrincipal = useRef(principalId);
  activePrincipal.current = principalId;
  const supported = browserNotificationsSupported();
  const [selected, setSelected] = useState(
    () => readBrowserNotificationPreference(principalId),
  );
  const [state, setState] = useState<ControlState>(() => initialState(supported, principalId));
  const [deliveryState, setDeliveryState] = useState<BrowserAlertDeliveryStatus>(
    () => readBrowserAlertDeliveryStatus(principalId),
  );
  const [compactStatus, setCompactStatus] = useState(isCompactNotificationStatus);
  const [workerReady, setWorkerReady] = useState(false);
  const [receiverKind, setReceiverKind] = useState<BrowserNotificationTransport["kind"] | null>(null);

  useEffect(() => {
    const media = window.matchMedia(COMPACT_STATUS_QUERY);
    const sync = () => setCompactStatus(media.matches);
    media.addEventListener("change", sync);
    sync();
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    setWorkerReady(false);
    setSelected(readBrowserNotificationPreference(principalId));
    setState(initialState(supported, principalId));
    setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
  }, [supported, principalId]);

  useEffect(() => {
    const syncStoredState = (event: StorageEvent) => {
      if (isBrowserNotificationPreferenceStorageKey(event.key, principalId)) {
        const nextSelected = readBrowserNotificationPreference(principalId);
        const nextControlState = initialState(supported, principalId);
        if (nextControlState !== "on") setWorkerReady(false);
        setSelected(nextSelected);
        setState(nextControlState);
      }
      const nextDeliveryState = browserAlertDeliveryStatusForStorageKey(
        event.key,
        principalId,
      );
      if (nextDeliveryState !== null) setDeliveryState(nextDeliveryState);
    };
    window.addEventListener("storage", syncStoredState);
    const syncCurrentDocument = (event: Event) => {
      const detail = event instanceof CustomEvent ? event.detail : null;
      if (!isBrowserNotificationPreferenceChange(detail, principalId)) return;
      const nextSelected = readBrowserNotificationPreference(principalId);
      const nextControlState = initialState(supported, principalId);
      if (nextControlState !== "on") setWorkerReady(false);
      setSelected(nextSelected);
      setState(nextControlState);
    };
    const syncCurrentDelivery = (event: Event) => {
      const detail = event instanceof CustomEvent ? event.detail : null;
      if (!isBrowserNotificationDeliveryChange(detail, principalId)) return;
      setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
    };
    window.addEventListener(
      BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
      syncCurrentDocument,
    );
    window.addEventListener(
      BROWSER_NOTIFICATION_DELIVERY_CHANGED_EVENT,
      syncCurrentDelivery,
    );
    return () => {
      window.removeEventListener("storage", syncStoredState);
      window.removeEventListener(
        BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
        syncCurrentDocument,
      );
      window.removeEventListener(
        BROWSER_NOTIFICATION_DELIVERY_CHANGED_EVENT,
        syncCurrentDelivery,
      );
    };
  }, [principalId, supported]);

  useEffect(() => {
    if (state !== "on") {
      setWorkerReady(false);
      setReceiverKind(null);
      return undefined;
    }
    let cancelled = false;
    void prepareBrowserNotificationTransport(import.meta.env.BASE_URL)
      .then((receiver) => {
        if (!cancelled) {
          setReceiverKind(receiver.kind);
          setWorkerReady(true);
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => { cancelled = true; };
  }, [state]);

  useEffect(() => {
    if (!supported || !("permissions" in navigator)) return undefined;
    let cancelled = false;
    let permissionStatus: PermissionStatus | null = null;
    const syncPermission = () => {
      if (cancelled) return;
      if (Notification.permission !== "granted") {
        writeBrowserNotificationPreference(false, principalId);
        setWorkerReady(false);
      }
      setState((current) => Notification.permission === "granted" &&
        (current === "error" || current === "enabling")
        ? current
        : initialState(supported, principalId));
    };
    window.addEventListener("focus", syncPermission);
    void navigator.permissions
      .query({ name: "notifications" as PermissionName })
      .then((status) => {
        if (cancelled) return;
        permissionStatus = status;
        status.addEventListener("change", syncPermission);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", syncPermission);
      permissionStatus?.removeEventListener("change", syncPermission);
    };
  }, [supported, principalId]);

  useEffect(() => {
    let cancelled = false;
    const consumeAcknowledgementFragment = () => {
      const location = new URL(window.location.href);
      const acknowledgement = decodeBrowserAlertAcknowledgementFragment(location.hash);
      if (acknowledgement === null) return;
      window.history.replaceState(
        window.history.state,
        "",
        `${location.pathname}${location.search}`,
      );
      void acknowledgeBrowserAlertDeliveryForClaim(
        acknowledgement.tag,
        acknowledgement.acknowledgementToken,
        Date.now(),
      ).then((receipt) => {
        if (!cancelled && receipt !== null) {
          setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
        }
      });
    };
    consumeAcknowledgementFragment();
    window.addEventListener("hashchange", consumeAcknowledgementFragment);
    return () => {
      cancelled = true;
      window.removeEventListener("hashchange", consumeAcknowledgementFragment);
    };
  }, [principalId]);

  const streamEnabled = state === "on" && workerReady;
  const streamLeader = useExclusiveBrowserStreamLeader(
    streamEnabled,
    "browser-notifications",
    principalId,
    () => {
      setWorkerReady(false);
      setState("error");
    },
  );

  const deliverAlert = async (alert: BrowserAlert): Promise<"delivered" | "deferred"> => {
    const claim = await claimBrowserAlertDelivery(alert.tag, principalId);
    if (claim === "duplicate" || claim === "rate-limited") return "deferred";
    if (claim === "unavailable") throw new Error("Browser notification claim is unavailable");
    const acknowledgementToken = readBrowserAlertAcknowledgementToken(alert.tag, principalId);
    if (acknowledgementToken === null) throw new Error("Browser notification claim has no token");
    try {
      const receiver = await prepareBrowserNotificationTransport(import.meta.env.BASE_URL);
      if (activePrincipal.current !== principalId || !document.hidden
          || Notification.permission !== "granted" || !readBrowserNotificationPreference(principalId)) {
        await releaseBrowserAlertDelivery(alert.tag, acknowledgementToken, principalId);
        return "deferred";
      }
      const title = alert.kind === "finding" ? findingNotificationText("title")
        : browserNotificationText(ALERT_TITLE_KEYS[alert.kind]);
      const body = alert.kind === "finding" ? findingNotificationText("body")
        : browserNotificationText(ALERT_BODY_KEYS[alert.kind]);
      await receiver.show(title, {
        body,
        tag: alert.tag,
        data: browserAlertNotificationData(alert, import.meta.env.BASE_URL, acknowledgementToken),
      });
      const receipt = await recordBrowserAlertDelivered(alert.tag, acknowledgementToken, principalId);
      if (receipt === null) throw new Error("Browser notification display receipt could not be recorded");
      setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
      return "delivered";
    } catch (error) {
      await releaseBrowserAlertDelivery(alert.tag, acknowledgementToken, principalId);
      throw error;
    }
  };

  useEffect(() => {
    if (!streamEnabled || !streamLeader || !document.hidden) return;
    let cancelled = false;
    const deliver = async () => {
      try {
        for (const finding of findings) {
          if (cancelled || activePrincipal.current !== principalId || !document.hidden) return;
          if (!findingNeedsAttention(finding, principalId)) continue;
          markFindingPending(finding, principalId);
          const result = await deliverAlert(findingBrowserAlert(finding));
          if (result === "delivered") rememberFinding(finding, principalId);
        }
      } catch {
        if (!cancelled) setState("error");
      }
    };
    void deliver();
    return () => { cancelled = true; };
  }, [findings, streamEnabled, streamLeader, principalId]);

  useLiveStream({
    url: `${client.operatorApiBaseUrl.replace(/\/$/, "")}/live/stream`,
    enabled: streamEnabled && streamLeader,
    pauseWhenHidden: false,
    retryAuthenticationFailures: true,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => {
      if (typeof document !== "undefined" && !document.hidden) return;
      if (Notification.permission !== "granted") {
        writeBrowserNotificationPreference(false, principalId);
        setWorkerReady(false);
        setState(Notification.permission === "denied" ? "blocked" : "off");
        return;
      }
      const alert = browserAlertForLiveEvent(event);
      if (alert === null) return;
      void deliverAlert(alert).catch(() => setState("error"));
    },
  });

  const setSelection = async (enabled: boolean): Promise<void> => {
    if (!supported) return;
    try {
      if (!enabled) {
        requireBrowserNotificationPreferenceWrite(false, principalId);
        setSelected(false);
        setWorkerReady(false);
        setState("off");
        return;
      }
      setState("enabling");
      const permission = Notification.permission === "granted"
        ? "granted"
        : await Notification.requestPermission();
      if (permission !== "granted") {
        writeBrowserNotificationPreference(false, principalId);
        setState(permission === "denied" ? "blocked" : "off");
        return;
      }
      const receiver = await prepareBrowserNotificationTransport(import.meta.env.BASE_URL, true);
      if (Notification.permission !== "granted") {
        writeBrowserNotificationPreference(false, principalId);
        setSelected(false);
        setWorkerReady(false);
        setState(Notification.permission === "denied" ? "blocked" : "off");
        return;
      }
      requireBrowserNotificationPreferenceWrite(true, principalId);
      setReceiverKind(receiver.kind);
      setSelected(true);
      setWorkerReady(true);
      setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
      setState("on");
    } catch {
      setWorkerReady(false);
      setState(Notification.permission === "denied" ? "blocked" : "error");
    }
  };

  const preparing = state === "enabling" || (state === "on" && !workerReady);
  const disabled = state === "unsupported" || state === "blocked" || preparing;
  const label = selected && state === "error" && presentation === "settings"
    ? browserNotificationText("on")
    : browserNotificationText(CONTROL_LABEL_KEYS[state]);
  const stateLabel = browserNotificationText(
    preparing ? "stateEnabling" : state === "on"
      ? deliveryState === "ready" && receiverKind === "session"
        ? "stateOnSession"
        : DELIVERY_STATE_KEYS[deliveryState]
      : CONTROL_STATE_KEYS[state],
  );
  const visibleStateLabel = compactStatus
    && state === "on"
    && deliveryState === "acknowledged"
    ? browserNotificationText("stateAcknowledgedCompact")
    : stateLabel;
  if (presentation === "settings") {
    return (
      <label class="settings-toggle-control" title={receiverKind === "session" ? browserNotificationText("sessionDetail") : undefined}>
        <input
          type="checkbox"
          checked={selected}
          aria-label={`${label}: ${stateLabel}`}
          title={receiverKind === "session" ? browserNotificationText("sessionDetail") : undefined}
          disabled={disabled}
          onChange={(event) => { void setSelection(event.currentTarget.checked); }}
        />
        <span aria-hidden="true" />
        <strong role="status" aria-live="polite">{stateLabel}</strong>
      </label>
    );
  }
  return (
    <button
      type="button"
      class={`topbar-control browser-notification-control ${selected ? "is-active" : ""}`}
      aria-pressed={selected}
      aria-label={`${label}: ${stateLabel}`}
      title={receiverKind === "session" ? browserNotificationText("sessionDetail") : undefined}
      disabled={disabled}
      onClick={() => { void setSelection(state === "error" ? true : !selected); }}
    >
      <span class="browser-notification-indicator" aria-hidden="true" />
      <NotificationBellIcon />
      <span class="topbar-control-label">{browserNotificationText("label")}</span>
      <span class="browser-notification-state" role="status" aria-live="polite">
        {visibleStateLabel}
      </span>
    </button>
  );
}

function isCompactNotificationStatus(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia(COMPACT_STATUS_QUERY).matches;
}

function initialState(supported: boolean, principalId?: string | null): ControlState {
  if (!supported) return "unsupported";
  if (Notification.permission === "denied") return "blocked";
  return Notification.permission === "granted"
    && readBrowserNotificationPreference(principalId)
    ? "on"
    : "off";
}
