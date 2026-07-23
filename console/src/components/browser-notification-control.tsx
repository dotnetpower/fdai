import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  browserAlertForLiveEvent,
  browserNotificationsSupported,
  browserNotificationTargetPath,
  browserNotificationWorkerPaths,
  claimBrowserAlertDelivery,
  readBrowserNotificationPreference,
  releaseBrowserAlertDelivery,
  writeBrowserNotificationPreference,
  type BrowserAlertKind,
} from "../browser-notifications";
import { useLiveStream } from "../hooks/use-live-stream";
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
  readonly principalId?: string | null;
}

type ControlState = "off" | "enabling" | "on" | "blocked" | "unsupported" | "error";

const CONTROL_LABEL_KEYS: Readonly<Record<ControlState, string>> = {
  off: "browserNotifications.off",
  enabling: "browserNotifications.enabling",
  on: "browserNotifications.on",
  blocked: "browserNotifications.blocked",
  unsupported: "browserNotifications.unsupported",
  error: "browserNotifications.error",
};

const ALERT_TITLE_KEYS: Readonly<Record<BrowserAlertKind, string>> = {
  approval: "browserNotifications.approvalTitle",
  denied: "browserNotifications.deniedTitle",
  failed: "browserNotifications.failedTitle",
};

const ALERT_BODY_KEYS: Readonly<Record<BrowserAlertKind, string>> = {
  approval: "browserNotifications.approvalBody",
  denied: "browserNotifications.deniedBody",
  failed: "browserNotifications.failedBody",
};

export function BrowserNotificationControl({ client, principalId }: Props) {
  const supported = browserNotificationsSupported();
  const [state, setState] = useState<ControlState>(() => initialState(supported, principalId));
  const [workerReady, setWorkerReady] = useState(false);

  useEffect(() => {
    setWorkerReady(false);
    setState(initialState(supported, principalId));
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

  useLiveStream({
    url: `${client.readApiBaseUrl.replace(/\/$/, "")}/live/stream`,
    enabled: state === "on" && workerReady,
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
            data: {
              path: browserNotificationTargetPath(alert.path, import.meta.env.BASE_URL),
            },
          },
        ))
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
      setState("on");
    } catch {
      writeBrowserNotificationPreference(false, principalId);
      setState("error");
    }
  };

  const disabled = state === "unsupported" || state === "blocked" || state === "enabling";
  const label = t(CONTROL_LABEL_KEYS[state]);
  return (
    <button
      type="button"
      class={`browser-notification-control ${state === "on" ? "is-active" : ""}`}
      aria-pressed={state === "on"}
      disabled={disabled}
      onClick={() => { void toggle(); }}
    >
      {label}
    </button>
  );
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
