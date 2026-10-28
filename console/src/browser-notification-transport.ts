import {
  BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
  browserNotificationTargetPath,
  browserNotificationWorkerPaths,
  decodeBrowserAlertAcknowledgement,
  withBrowserNotificationDeadline,
} from "./browser-notifications";
import { browserNotificationText } from "./components/i18n/browser-notifications";

const SESSION_RECEIVER_KEY = "fdai:console:notification-session-receiver:v1";

export interface BrowserNotificationTransport {
  readonly kind: "service-worker" | "session";
  show(title: string, options: NotificationOptions): Promise<void>;
}

let preparation: Promise<BrowserNotificationTransport> | null = null;

export function prepareBrowserNotificationTransport(
  baseUrl: string,
  allowSessionFallback = false,
): Promise<BrowserNotificationTransport> {
  if (Notification.permission !== "granted") {
    return Promise.reject(new Error("Console web notification permission is not granted."));
  }
  if (preparation !== null) return preparation;
  preparation = prepareReceiver(baseUrl, allowSessionFallback).catch((error: unknown) => {
    preparation = null;
    throw error;
  });
  return preparation;
}

async function prepareReceiver(
  baseUrl: string,
  allowSessionFallback: boolean,
): Promise<BrowserNotificationTransport> {
  browserNotificationWorkerPaths(baseUrl);
  if (window.sessionStorage.getItem(SESSION_RECEIVER_KEY) === "verified") {
    return sessionReceiver(baseUrl);
  }
  try {
    if (!("serviceWorker" in navigator)) {
      throw new Error("Console web notification service workers are unavailable.");
    }
    const { scriptUrl, scope } = browserNotificationWorkerPaths(baseUrl);
    await withBrowserNotificationDeadline(
      navigator.serviceWorker.register(scriptUrl, { scope, updateViaCache: "none" }),
    );
    const registration = await withBrowserNotificationDeadline(navigator.serviceWorker.ready);
    return {
      kind: "service-worker",
      async show(title, options) {
        try {
          await withBrowserNotificationDeadline(registration.showNotification(title, options));
        } catch (error) {
          preparation = null;
          throw error;
        }
      },
    };
  } catch (workerError) {
    if (!allowSessionFallback) throw workerError;
    try {
      const probe = await displaySessionNotification(
        browserNotificationText("sessionTestTitle"),
        {
          body: browserNotificationText("sessionTestBody"),
          tag: "fdai-console-connection-test",
        },
        null,
      );
      window.setTimeout(() => probe.close(), 1000);
      window.sessionStorage.setItem(SESSION_RECEIVER_KEY, "verified");
      return sessionReceiver(baseUrl);
    } catch (sessionError) {
      throw new AggregateError(
        [workerError, sessionError],
        "No verified Console web notification receiver is available.",
      );
    }
  }
}

function sessionReceiver(baseUrl: string): BrowserNotificationTransport {
  return {
    kind: "session",
    async show(title, options) {
      try {
        const { target, tag } = sessionNotificationClickDetails(options.data, baseUrl);
        // Native backends can reject long tags; the canonical event tag stays in the click data.
        const digest = new Uint8Array(await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(tag),
        ));
        const displayTag = [...digest.subarray(0, 16)]
          .map((byte) => byte.toString(16).padStart(2, "0")).join("");
        await displaySessionNotification(title, { ...options, tag: displayTag }, target);
      } catch (error) {
        const knownReasons = [
          "Console web notification click data is missing.",
          "Console web notification click data is invalid.",
          "Console web notification click target is outside the allowed scope.",
          "Console web notification permission is not granted.",
          "Console web session notification display timed out.",
          "Console web session notification display failed.",
        ];
        console.warn("console_web_notification_session_failed", {
          reason: error instanceof Error && knownReasons.includes(error.message)
            ? error.message
            : "Browser notification rejected",
        });
        preparation = null;
        window.sessionStorage.removeItem(SESSION_RECEIVER_KEY);
        throw error;
      }
    },
  };
}

export function sessionNotificationClickTarget(
  data: unknown,
  baseUrl: string,
  origin: string = window.location.origin,
): string {
  return sessionNotificationClickDetails(data, baseUrl, origin).target;
}

function sessionNotificationClickDetails(
  data: unknown,
  baseUrl: string,
  origin: string = window.location.origin,
): { readonly target: string; readonly tag: string } {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error("Console web notification click data is missing.");
  }
  const record = data as Record<string, unknown>;
  const acknowledgement = decodeBrowserAlertAcknowledgement({
    ...record,
    type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
  });
  if (acknowledgement === null || typeof record.path !== "string" ||
      !record.path.startsWith("/") || record.path.startsWith("//")) {
    throw new Error("Console web notification click data is invalid.");
  }
  const target = new URL(record.path, origin);
  const allowedPaths = [
    browserNotificationTargetPath("/audit", baseUrl),
    browserNotificationTargetPath("/incidents", baseUrl),
  ];
  if (target.origin !== origin || !allowedPaths.includes(target.pathname)) {
    throw new Error("Console web notification click target is outside the allowed scope.");
  }
  target.hash = `fdai-notification-ack?${new URLSearchParams({
    tag: acknowledgement.tag,
    token: acknowledgement.acknowledgementToken,
  })}`;
  return { target: target.href, tag: acknowledgement.tag };
}

function displaySessionNotification(
  title: string,
  options: NotificationOptions,
  target: string | null,
): Promise<Notification> {
  if (Notification.permission !== "granted") {
    return Promise.reject(new Error("Console web notification permission is not granted."));
  }
  return new Promise((resolve, reject) => {
    const notification = new Notification(title, options);
    const timer = window.setTimeout(() => {
      notification.close();
      reject(new Error("Console web session notification display timed out."));
    }, 5000);
    notification.onshow = () => {
      window.clearTimeout(timer);
      resolve(notification);
    };
    notification.onerror = () => {
      window.clearTimeout(timer);
      notification.close();
      reject(new Error("Console web session notification display failed."));
    };
    notification.onclick = () => {
      notification.close();
      window.focus();
      if (target !== null) window.location.assign(target);
    };
  });
}
