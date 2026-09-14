"use strict";

const CONSOLE_WEB_CHANNEL_ID = "console-web";
const ACKNOWLEDGEMENT_TYPE = "fdai.console-web-notification.acknowledged";
const ACKNOWLEDGEMENT_QUERY = "fdai_notification_ack";
const SAFE_NOTIFICATION_TAG = /^fdai:[A-Za-z0-9._:-]{1,128}$/;

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const path = event.notification.data?.path;
  const tag = event.notification.data?.channel_id === CONSOLE_WEB_CHANNEL_ID
    ? safeNotificationTag(event.notification.data?.tag)
    : null;
  const target = safeTarget(path);
  if (target === null) return;

  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const exact = windows.find((client) => client.url === target.href);
    if (exact !== undefined) {
      try {
        await exact.focus();
      } catch {
        await self.clients.openWindow(acknowledgementTarget(target, tag).href);
        return;
      }
      if (!acknowledgeClient(exact, tag)) {
        try {
          const navigated = await exact.navigate(acknowledgementTarget(target, tag).href);
          await navigated?.focus();
        } catch {
          console.warn("Console web notification acknowledgement delivery failed.");
        }
      }
      return;
    }
    const sameOrigin = windows.find((client) => new URL(client.url).origin === target.origin);
    if (sameOrigin !== undefined) {
      try {
        const navigated = await sameOrigin.navigate(acknowledgementTarget(target, tag).href);
        if (navigated === null) {
          await self.clients.openWindow(acknowledgementTarget(target, tag).href);
          return;
        }
        await navigated.focus();
      } catch {
        await self.clients.openWindow(acknowledgementTarget(target, tag).href);
      }
      return;
    }
    await self.clients.openWindow(acknowledgementTarget(target, tag).href);
  })());
});

function safeNotificationTag(value) {
  return typeof value === "string" && SAFE_NOTIFICATION_TAG.test(value) ? value : null;
}

function acknowledgementTarget(target, tag) {
  const acknowledged = new URL(target.href);
  if (tag !== null) acknowledged.searchParams.set(ACKNOWLEDGEMENT_QUERY, tag);
  return acknowledged;
}

function acknowledgeClient(client, tag) {
  if (tag === null || typeof client.postMessage !== "function") return false;
  try {
    client.postMessage({
      type: ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_CHANNEL_ID,
      tag,
    });
    return true;
  } catch {
    return false;
  }
}

function safeTarget(path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) return null;
  try {
    const target = new URL(path, self.location.origin);
    const scopePath = new URL(self.registration.scope).pathname.replace(/\/$/, "");
    const incidentPath = `${scopePath}/incidents`.replace(/^\/\//, "/");
    return target.origin === self.location.origin && target.pathname === incidentPath
      ? target
      : null;
  } catch {
    return null;
  }
}
