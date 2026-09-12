import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { renderLibraryPage } from "./share-pages.mjs";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)));
const port = Number.parseInt(process.env.PORT ?? "5474", 10);
const publicBaseUrl = process.env.MANUAL_STUDIO_PUBLIC_URL ?? `http://127.0.0.1:${port}`;
const [libraryTemplate, catalog] = await Promise.all([
  readFile(resolve(root, "library.html"), "utf8"),
  readFile(resolve(root, "catalog.json"), "utf8").then(JSON.parse),
]);
const allowedOrigins = new Set(
  (
    process.env.MANUAL_STUDIO_ALLOWED_ORIGINS ??
    "http://127.0.0.1:5273,http://localhost:5273"
  )
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);

if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
  throw new Error("PORT must be an integer between 1 and 65535.");
}

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".jpeg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
]);

function requestedManualId(requestUrl) {
  const url = new URL(requestUrl ?? "/", publicBaseUrl);
  const pathname = decodeURIComponent(url.pathname);
  if (pathname === "/library" || pathname === "/library.html") {
    const requested = url.searchParams.get("manual");
    return requested !== null && catalog.manuals.some((manual) => manual.id === requested)
      ? requested
      : null;
  }
  const match = pathname.match(/^\/([a-z0-9-]+)\.html$/);
  return match && catalog.manuals.some((manual) => manual.id === match[1]) ? match[1] : undefined;
}

function requestedFile(requestUrl) {
  const url = new URL(requestUrl ?? "/", `http://127.0.0.1:${port}`);
  const pathname = decodeURIComponent(url.pathname);
  const relativePath = pathname === "/"
    ? "index.html"
    : pathname === "/library"
      ? "library.html"
      : pathname.replace(/^\/+/, "");
  const candidate = resolve(root, relativePath);
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) return null;
  return candidate;
}

const server = createServer(async (request, response) => {
  const origin = request.headers.origin;
  const corsHeaders = origin !== undefined && allowedOrigins.has(origin)
    ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" }
    : {};
  const manualId = requestedManualId(request.url);
  if (manualId !== undefined) {
    const body = renderLibraryPage(libraryTemplate, catalog, publicBaseUrl, manualId);
    response.writeHead(200, {
      ...corsHeaders,
      "Cache-Control": "no-store",
      "Content-Length": Buffer.byteLength(body),
      "Content-Type": "text/html; charset=utf-8",
      "Cross-Origin-Resource-Policy": "cross-origin",
      "X-Content-Type-Options": "nosniff",
    });
    response.end(request.method === "HEAD" ? undefined : body);
    return;
  }
  const filePath = requestedFile(request.url);
  if (filePath === null) {
    response.writeHead(400, {
      ...corsHeaders,
      "Content-Type": "text/plain; charset=utf-8",
    });
    response.end("Invalid path.");
    return;
  }

  try {
    const file = await stat(filePath);
    if (!file.isFile()) throw Object.assign(new Error("Not a file."), { code: "ENOENT" });
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      response.writeHead(404, {
        ...corsHeaders,
        "Content-Type": "text/plain; charset=utf-8",
      });
      response.end("Not found.");
      return;
    }
    throw error;
  }

  response.writeHead(200, {
    ...corsHeaders,
    "Cache-Control": "no-store",
    "Content-Type": contentTypes.get(extname(filePath)) ?? "application/octet-stream",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "X-Content-Type-Options": "nosniff",
  });
  if (request.method === "HEAD") response.end();
  else createReadStream(filePath).pipe(response);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Manual Studio prototype ready at http://127.0.0.1:${port}`);
});
