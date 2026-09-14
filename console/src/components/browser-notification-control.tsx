import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  acknowledgeBrowserAlertDelivery,
  BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
  browserAlertNotificationData,
  browserAlertDeliveryStatusForStorageKey,
  browserAlertForLiveEvent,
  decodeBrowserAlertAcknowledgementFragment,
  isBrowserNotificationPreferenceStorageKey,
  isBrowserNotificationPreferenceChange,
  browserNotificationsSupported,
  browserNotificationWorkerPaths,
  claimBrowserAlertDelivery,
  readBrowserAlertAcknowledgementToken,
  readBrowserAlertDeliveryStatus,
  readBrowserNotificationPreference,
  recordBrowserAlertDelivered,
  releaseBrowserAlertDelivery,
  requireBrowserNotificationPreferenceWrite,
  trustedBrowserAlertAcknowledgement,
  withBrowserNotificationDeadline,
  writeBrowserNotificationPreference,
  type BrowserAlertKind,
  type BrowserAlertDeliveryStatus,
} from "../browser-notifications";
import { useExclusiveBrowserStreamLeader } from "../hooks/browser-stream-leader";
import { useLiveStream } from "../hooks/use-live-stream";
import {
  browserNotificationText as t,
  type BrowserNotificationTextKey,
} from "./i18n/browser-notifications";
import { NotificationBellIcon } from "./notification-bell-icon";

interface Props {
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
  readonly presentation?: "header" | "settings";
}

type ControlState = "off" | "enabling" | "on" | "blocked" | "unsupported" | "error";
const COMPACT_STATUS_QUERY = "(max-width: 640px)";

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

const ALERT_TITLE_KEYS: Readonly<Record<BrowserAlertKind, BrowserNotificationTextKey>> = {
  approval: "approvalTitle",
  denied: "deniedTitle",
  failed: "failedTitle",
};

const ALERT_BODY_KEYS: Readonly<Record<BrowserAlertKind, BrowserNotificationTextKey>> = {
  approval: "approvalBody",
  denied: "deniedBody",
  failed: "failedBody",
};

export function BrowserNotificationControl({
  client,
  principalId,
  presentation = "header",
}: Props) {
  const supported = browserNotificationsSupported();
  const [state, setState] = useState<ControlState>(() => initialState(supported, principalId));
  const [deliveryState, setDeliveryState] = useState<BrowserAlertDeliveryStatus>(
    () => readBrowserAlertDeliveryStatus(principalId),
  );
  const [compactStatus, setCompactStatus] = useState(isCompactNotificationStatus);
  const [workerReady, setWorkerReady] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(COMPACT_STATUS_QUERY);
    const sync = () => setCompactStatus(media.matches);
    media.addEventListener("change", sync);
    sync();
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    setWorkerReady(false);
    setState(initialState(supported, principalId));
    setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
  }, [supported, principalId]);

  useEffect(() => {
    const syncStoredState = (event: StorageEvent) => {
      if (isBrowserNotificationPreferenceStorageKey(event.key, principalId)) {
        const nextControlState = initialState(supported, principalId);
        if (nextControlState !== "on") setWorkerReady(false);
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
      const nextControlState = initialState(supported, principalId);
      if (nextControlState !== "on") setWorkerReady(false);
      setState(nextControlState);
    };
    window.addEventListener(
      BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
      syncCurrentDocument,
    );
    return () => {
      window.removeEventListener("storage", syncStoredState);
      window.removeEventListener(
        BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
        syncCurrentDocument,
      );
    };
  }, [principalId, supported]);

  useEffect(() => {
    if (state !== "on") {
      setWorkerReady(false);
      return undefined;
    }
    let cancelled = false;
    void ensureNotificationWorker()
      .then(() => {
        if (!cancelled) setWorkerReady(true);
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
      setState(initialState(supported, principalId));
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
    const acknowledge = (
      tag: string,
      acknowledgementToken: string,
      acknowledgedAt: number,
    ) => {
      const receipt = acknowledgeBrowserAlertDelivery(
        tag,
        acknowledgementToken,
        principalId,
        acknowledgedAt,
      );
      if (receipt !== null) setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
    };
    const onWorkerMessage = (event: MessageEvent<unknown>) => {
      const acknowledgement = trustedBrowserAlertAcknowledgement(
        event.data,
        event.isTrusted,
      );
      if (acknowledgement !== null) {
        acknowledge(
          acknowledgement.tag,
          acknowledgement.acknowledgementToken,
          acknowledgement.acknowledgedAt,
        );
      }
    };
    const serviceWorker = "serviceWorker" in navigator ? navigator.serviceWorker : null;
    serviceWorker?.addEventListener("message", onWorkerMessage);

    const location = new URL(window.location.href);
    const acknowledgement = decodeBrowserAlertAcknowledgementFragment(location.hash);
    if (acknowledgement !== null) {
      window.history.replaceState(
        window.history.state,
        "",
        `${location.pathname}${location.search}`,
      );
      acknowledge(
        acknowledgement.tag,
        acknowledgement.acknowledgementToken,
        Date.now(),
      );
    }

    return () => serviceWorker?.removeEventListener("message", onWorkerMessage);
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
      const claim = claimBrowserAlertDelivery(alert.tag, principalId);
      if (claim === "duplicate" || claim === "rate-limited") return;
      if (claim === "unavailable") {
        setState("error");
        return;
      }
      const acknowledgementToken = readBrowserAlertAcknowledgementToken(
        alert.tag,
        principalId,
      );
      if (acknowledgementToken === null) {
        setState("error");
        return;
      }
      void ensureNotificationWorker()
        .then((registration) => registration.showNotification(
          t(ALERT_TITLE_KEYS[alert.kind]),
          {
            body: t(ALERT_BODY_KEYS[alert.kind]),
            tag: alert.tag,
            data: browserAlertNotificationData(
              alert,
              import.meta.env.BASE_URL,
              acknowledgementToken,
            ),
          },
        ))
        .then(() => {
          const receipt = recordBrowserAlertDelivered(
            alert.tag,
            acknowledgementToken,
            principalId,
          );
          if (receipt === null) {
            releaseBrowserAlertDelivery(alert.tag, acknowledgementToken, principalId);
            setState("error");
            return;
          }
          setDeliveryState(readBrowserAlertDeliveryStatus(principalId));
        })
        .catch(() => {
          releaseBrowserAlertDelivery(alert.tag, acknowledgementToken, principalId);
          setState("error");
        });
    },
  });

  const toggle = async (): Promise<void> => {
    if (!supported) return;
    try {
      if (state === "on") {
        requireBrowserNotificationPreferenceWrite(false, principalId);
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
      await ensureNotificationWorker();
      requireBrowserNotificationPreferenceWrite(true, principalId);
      setWorkerReady(true);
      setDeliveryState("ready");
      setState("on");
    } catch {
      writeBrowserNotificationPreference(false, principalId);
      setWorkerReady(false);
      setState("error");
    }
  };

  const disabled = state === "unsupported" || state === "blocked" || state === "enabling";
  const label = t(CONTROL_LABEL_KEYS[state]);
  const stateLabel = t(
    state === "on" ? DELIVERY_STATE_KEYS[deliveryState] : CONTROL_STATE_KEYS[state],
  );
  const visibleStateLabel = compactStatus
    && state === "on"
    && deliveryState === "acknowledged"
    ? t("stateAcknowledgedCompact")
    : stateLabel;
  if (presentation === "settings") {
    return (
      <label class="settings-toggle-control">
        <input
          type="checkbox"
          checked={state === "on"}
          aria-label={`${label}: ${stateLabel}`}
          disabled={disabled}
          onChange={() => { void toggle(); }}
        />
        <span aria-hidden="true" />
        <strong role="status" aria-live="polite">{stateLabel}</strong>
      </label>
    );
  }
  return (
    <button
      type="button"
      class={`topbar-control browser-notification-control ${state === "on" ? "is-active" : ""}`}
      aria-pressed={state === "on"}
      aria-label={`${label}: ${stateLabel}`}
      disabled={disabled}
      onClick={() => { void toggle(); }}
    >
      <span class="browser-notification-indicator" aria-hidden="true" />
      <NotificationBellIcon />
      <span class="topbar-control-label">{t("label")}</span>
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

async function ensureNotificationWorker(): Promise<ServiceWorkerRegistration> {
  if (workerRegistrationPromise !== null) return workerRegistrationPromise;
  const { scriptUrl, scope } = browserNotificationWorkerPaths(import.meta.env.BASE_URL);
  workerRegistrationPromise = withBrowserNotificationDeadline(
    navigator.serviceWorker.register(scriptUrl, { scope, updateViaCache: "none" }),
  )
    .then(() => withBrowserNotificationDeadline(navigator.serviceWorker.ready))
    .catch((error: unknown) => {
      workerRegistrationPromise = null;
      throw error;
    });
  return workerRegistrationPromise;
}

let workerRegistrationPromise: Promise<ServiceWorkerRegistration> | null = null;
