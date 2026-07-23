"use strict";

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const path = event.notification.data?.path;
  const target = safeTarget(path);
  if (target === null) return;

  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const exact = windows.find((client) => client.url === target.href);
    if (exact !== undefined) {
      await exact.focus();
      return;
    }
    const sameOrigin = windows.find((client) => new URL(client.url).origin === target.origin);
    if (sameOrigin !== undefined) {
      try {
        await sameOrigin.navigate(target.href);
        await sameOrigin.focus();
      } catch {
        await self.clients.openWindow(target.href);
      }
      return;
    }
    await self.clients.openWindow(target.href);
  })());
});

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
