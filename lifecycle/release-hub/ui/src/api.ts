import { authenticatedFetch } from "../../../hub/ui/src/auth";

export type Release = {
  id: string; label: string; manifest: string; digest: string; signed_payload_sha256: string; signature: string | null;
  signature_status: string; state: "draft" | "published" | "recalled";
  channels: string[]; published_at: string | null; recalled_at: string | null;
};
export type Event = {
  revision: number; release_id: string; action: string; reason: string;
  channel: string | null; occurred_at: string;
  actor?: string;
};
export type Catalog = {
  revision: number; updated_at: string; expires_at: string; expired: boolean;
  key_id: string; mode: string; releases: Release[];
  channels: Record<string, string[]>; events: Event[]; export_sha256?: string;
};
export type Action = "register" | "publish" | "contribute" | "recall" | "renew";
export type Change = {
  revision: number; confirmation: string; reason: string; channel?: string; channel_confirmation?: string;
  label?: string; manifest?: string;
};

export async function requestCatalog(path = "/v1/catalog", body?: Change): Promise<Catalog> {
  const response = await authenticatedFetch(path, {
    signal: AbortSignal.timeout(10_000),
    ...(body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : {}),
  });
  if (!response.ok) {
    const result: unknown = await response.json();
    const message = typeof result === "object" && result !== null && "error" in result
      && typeof result.error === "string" ? result.error : `Request failed (${response.status}).`;
    throw new Error(message);
  }
  return response.json() as Promise<Catalog>;
}

export function actionsFor(release: Release): Action[] {
  if (release.state === "recalled") return [];
  return release.state === "draft" ? ["publish"] : ["contribute", "recall"];
}

export function isCustomChannel(value: string): boolean {
  return value.length <= 64 && value === value.trim() && /^custom-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
}

export function artifacts(manifest: string): { component: string; digest: string; sbom: string }[] {
  const parsed: unknown = JSON.parse(manifest);
  if (typeof parsed !== "object" || parsed === null) throw new Error("Invalid manifest.");
  const root = parsed as Record<string, unknown>;
  const result: { component: string; digest: string; sbom: string }[] = [];
  for (const section of ["services", "sidecars", "installation_agents", "console", "deployment_support"]) {
    const group = root[section];
    if (typeof group !== "object" || group === null) continue;
    const entries = section === "console" || section === "deployment_support"
      ? [[section, group] as const] : Object.entries(group);
    for (const [component, value] of entries) {
      if (typeof value !== "object" || value === null) continue;
      const record = value as Record<string, unknown>;
      result.push({
        component,
        digest: typeof record.image_digest === "string" ? record.image_digest : String(record.archive_sha256),
        sbom: String(record.sbom_sha256),
      });
    }
  }
  return result;
}
