import { loadConfig } from "../config";
import { chatRequestHeaders } from "./auth";

export async function requestHeaders(
  contentType: boolean = false,
): Promise<Record<string, string>> {
  return chatRequestHeaders(contentType);
}

export function chatUrl(): string {
  const config = loadConfig();
  const base = config.readApiBaseUrl || (
    typeof window !== "undefined" ? window.location.origin : ""
  );
  return `${base.replace(/\/$/, "")}/chat`;
}

export function healthUrl(): string {
  return `${chatUrl()}/health`;
}

export function streamUrl(): string {
  return `${chatUrl()}/stream`;
}
