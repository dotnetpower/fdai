import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  acknowledgeBrowserAlertDelivery,
  BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_QUERY,
  BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
  browserAlertNotificationData,
  browserAlertForLiveEvent,
  CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
  decodeBrowserAlertAcknowledgement,
  browserNotificationsSupported,
  browserNotificationWorkerPaths,
  claimBrowserAlertDelivery,
  readLatestBrowserAlertReceipt,
  readBrowserNotificationPreference,
  recordBrowserAlertDelivered,
  releaseBrowserAlertDelivery,
  trustedBrowserAlertAcknowledgement,
  writeBrowserNotificationPreference,
  type BrowserAlertKind,
} from "../browser-notifications";
import { useExclusiveBrowserStreamLeader } from "../hooks/browser-stream-leader";
import { useLiveStream } from "../hooks/use-live-stream";
import {
  browserNotificationText as t,
  type BrowserNotificationTextKey,
} from "./i18n/browser-notifications";

interface Props {
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
}

type ControlState = "off" | "enabling" | "on" | "blocked" | "unsupported" | "error";
type DeliveryState = "ready" | "delivered" | "acknowledged";

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

const DELIVERY_STATE_KEYS: Readonly<Record<DeliveryState, BrowserNotificationTextKey>> = {
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

export function BrowserNotificationControl({ client, principalId }: Props) {
  const supported = browserNotificationsSupported();
  const [state, setState] = useState<ControlState>(() => initialState(supported, principalId));
  const [deliveryState, setDeliveryState] = useState<DeliveryState>(
    () => initialDeliveryState(principalId),
  );
  const [workerReady, setWorkerReady] = useState(false);

  useEffect(() => {
    setWorkerReady(false);
    setState(initialState(supported, principalId));
    setDeliveryState(initialDeliveryState(principalId));
  }, [supported, principalId]);

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
    const acknowledge = (tag: string, acknowledgedAt: number) => {
      const receipt = acknowledgeBrowserAlertDelivery(
        tag,
        principalId,
        acknowledgedAt,
      );
      if (receipt !== null) setDeliveryState("acknowledged");
    };
    const onWorkerMessage = (event: MessageEvent<unknown>) => {
      const acknowledgement = trustedBrowserAlertAcknowledgement(
        event.data,
        event.isTrusted,
      );
      if (acknowledgement !== null) {
        acknowledge(acknowledgement.tag, acknowledgement.acknowledgedAt);
      }
    };
    const serviceWorker = "serviceWorker" in navigator ? navigator.serviceWorker : null;
    serviceWorker?.addEventListener("message", onWorkerMessage);

    const location = new URL(window.location.href);
    const tag = location.searchParams.get(BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_QUERY);
    if (tag !== null) {
      location.searchParams.delete(BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_QUERY);
      window.history.replaceState(
        window.history.state,
        "",
        `${location.pathname}${location.search}${location.hash}`,
      );
      const acknowledgement = decodeBrowserAlertAcknowledgement({
        type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
        channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
        tag,
      });
      if (acknowledgement !== null) {
        acknowledge(acknowledgement.tag, Date.now());
      }
    }

    return () => serviceWorker?.removeEventListener("message", onWorkerMessage);
  }, [principalId]);

  const streamEnabled = state === "on" && workerReady;
  const streamLeader = useExclusiveBrowserStreamLeader(
    streamEnabled,
    "browser-notifications",
    principalId,
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
      void ensureNotificationWorker()
        .then((registration) => registration.showNotification(
          t(ALERT_TITLE_KEYS[alert.kind]),
          {
            body: t(ALERT_BODY_KEYS[alert.kind]),
            tag: alert.tag,
            data: browserAlertNotificationData(alert, import.meta.env.BASE_URL),
          },
        ))
        .then(() => {
          const receipt = recordBrowserAlertDelivered(alert.tag, principalId);
          if (receipt === null) {
            releaseBrowserAlertDelivery(alert.tag, principalId);
            setState("error");
            return;
          }
          setDeliveryState(receipt.acknowledgedAt === null ? "delivered" : "acknowledged");
        })
        .catch(() => {
          releaseBrowserAlertDelivery(alert.tag, principalId);
          setState("error");
        });
    },
  });

  const toggle = async (): Promise<void> => {
    if (!supported) return;
    if (state === "on") {
      writeBrowserNotificationPreference(false, principalId);
      setState("off");
      return;
    }
    setState("enabling");
    try {
      const permission = Notification.permission === "granted"
        ? "granted"
        : await Notification.requestPermission();
      if (permission !== "granted") {
        writeBrowserNotificationPreference(false, principalId);
        setState(permission === "denied" ? "blocked" : "off");
        return;
      }
      await ensureNotificationWorker();
      writeBrowserNotificationPreference(true, principalId);
      setWorkerReady(true);
      setDeliveryState("ready");
      setState("on");
    } catch {
      writeBrowserNotificationPreference(false, principalId);
      setState("error");
    }
  };

  const disabled = state === "unsupported" || state === "blocked" || state === "enabling";
  const label = t(CONTROL_LABEL_KEYS[state]);
  const stateLabel = t(
    state === "on" ? DELIVERY_STATE_KEYS[deliveryState] : CONTROL_STATE_KEYS[state],
  );
  return (
    <button
      type="button"
      class={`topbar-control browser-notification-control ${state === "on" ? "is-active" : ""}`}
      aria-pressed={state === "on"}
      aria-label={label}
      disabled={disabled}
      onClick={() => { void toggle(); }}
    >
      <span class="browser-notification-indicator" aria-hidden="true" />
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
        <path d="M10 21h4" />
      </svg>
      <span class="topbar-control-label">{t("label")}</span>
      <span class="browser-notification-state" role="status" aria-live="polite">
        {stateLabel}
      </span>
    </button>
  );
}

function initialDeliveryState(principalId?: string | null): DeliveryState {
  const receipt = readLatestBrowserAlertReceipt(principalId);
  if (receipt !== null && receipt.acknowledgedAt !== null) return "acknowledged";
  return receipt === null ? "ready" : "delivered";
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
  workerRegistrationPromise = navigator.serviceWorker
    .register(scriptUrl, { scope, updateViaCache: "none" })
    .then(() => navigator.serviceWorker.ready)
    .catch((error: unknown) => {
      workerRegistrationPromise = null;
      throw error;
    });
  return workerRegistrationPromise;
}

let workerRegistrationPromise: Promise<ServiceWorkerRegistration> | null = null;
