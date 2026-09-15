"use strict";

const CONSOLE_WEB_CHANNEL_ID = "console-web";
const ACKNOWLEDGEMENT_FRAGMENT = "fdai-notification-ack";
const SAFE_NOTIFICATION_TAG = /^fdai:[A-Za-z0-9._:-]{1,128}$/;
const SAFE_ACKNOWLEDGEMENT_TOKEN = /^[a-f0-9]{32}$/;

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
  const acknowledgementToken = event.notification.data?.channel_id === CONSOLE_WEB_CHANNEL_ID
    ? safeAcknowledgementToken(event.notification.data?.acknowledgement_token)
    : null;
  const target = safeTarget(path);
  if (target === null) return;
  const destination = acknowledgementTarget(target, tag, acknowledgementToken);

  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window" });
    const exact = windows.find((client) => client.url === target.href);
    if (exact !== undefined) {
      await navigateAndFocus(exact, destination);
      return;
    }
    const scoped = windows.find((client) => isScopedClient(client.url));
    if (scoped !== undefined) {
      await navigateAndFocus(scoped, destination);
      return;
    }
    await self.clients.openWindow(destination.href);
  })());
});

function isScopedClient(url) {
  try {
    const candidate = new URL(url);
    const scope = new URL(self.registration.scope);
    return candidate.origin === scope.origin && candidate.pathname.startsWith(scope.pathname);
  } catch {
    return false;
  }
}

function safeNotificationTag(value) {
  return typeof value === "string" && SAFE_NOTIFICATION_TAG.test(value) ? value : null;
}

function safeAcknowledgementToken(value) {
  return typeof value === "string" && SAFE_ACKNOWLEDGEMENT_TOKEN.test(value) ? value : null;
}

function acknowledgementTarget(target, tag, acknowledgementToken) {
  const acknowledged = new URL(target.href);
  if (tag !== null && acknowledgementToken !== null) {
    acknowledged.hash = `${ACKNOWLEDGEMENT_FRAGMENT}?${new URLSearchParams({
      tag,
      token: acknowledgementToken,
    })}`;
  }
  return acknowledged;
}

async function navigateAndFocus(client, target) {
  try {
    const navigated = await client.navigate(target.href);
    if (navigated === null) {
      await self.clients.openWindow(target.href);
      return;
    }
    await navigated.focus();
  } catch {
    await self.clients.openWindow(target.href);
  }
}

function safeTarget(path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) return null;
  try {
    const target = new URL(path, self.location.origin);
    const scopePath = new URL(self.registration.scope).pathname.replace(/\/$/, "");
    const allowedPaths = [`${scopePath}/audit`, `${scopePath}/incidents`];
    return target.origin === self.location.origin && allowedPaths.includes(target.pathname)
      ? target
      : null;
  } catch {
    return null;
  }
}
