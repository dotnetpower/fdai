import { OperatorApiError } from "../api";

export interface GuidanceText { readonly en: string; readonly ko?: string }
export interface GuidanceNode {
  readonly id: string;
  readonly label: GuidanceText;
  readonly detail: GuidanceText;
  readonly role: "subject" | "configuration" | "dependency" | "evidence" | "outcome";
}
export interface GuidanceEdge {
  readonly from: string;
  readonly to: string;
  readonly label: GuidanceText;
  readonly style: "solid" | "dashed";
}
export interface GuidanceReferenceImage {
  readonly asset_id: string;
  readonly digest: string;
  readonly source_document_url: string;
  readonly image_url: string;
  readonly source_revision: string;
  readonly attribution: string;
  readonly license: "CC-BY-4.0";
  readonly license_url: "https://creativecommons.org/licenses/by/4.0/";
  readonly alt: GuidanceText;
  readonly caption: GuidanceText;
  readonly english_in_image_notice: GuidanceText;
}
export interface GuidancePresentation {
  readonly title: GuidanceText;
  readonly summary: GuidanceText;
  readonly benefits: GuidanceText;
  readonly rationale: GuidanceText;
  readonly applicability: readonly GuidanceText[];
  readonly configuration: { readonly before: readonly GuidanceText[]; readonly after: readonly GuidanceText[] };
  readonly implementation_steps: readonly GuidanceText[];
  readonly verification_steps: readonly GuidanceText[];
  readonly cautions: readonly GuidanceText[];
  readonly reference_image?: GuidanceReferenceImage;
  readonly diagram: {
    readonly id: string;
    readonly kind: string;
    readonly title: GuidanceText;
    readonly description: GuidanceText;
    readonly nodes: readonly GuidanceNode[];
    readonly edges: readonly GuidanceEdge[];
  };
  readonly sources: readonly { readonly label: GuidanceText; readonly url: string; readonly kind: "aprl" | "learn" | "vendor" }[];
}

export interface WaraGuidance extends GuidancePresentation {
  readonly schema_version: "1.0.0";
  readonly recommendation_id: string;
  readonly source_revision: string;
  readonly source_digest: string;
  readonly lifecycle: "active" | "disabled";
  readonly content_digest: string;
}

interface GuidanceIdentity {
  readonly id: string;
  readonly source_revision: string;
  readonly source_digest: string;
  readonly lifecycle: string;
}

function invalid(reason: string): never {
  throw new OperatorApiError(502, `invalid Operator API response: WARA guidance ${reason}`);
}

function object(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid(`${label} MUST be an object`);
  const raw = value as Record<string, unknown>;
  if (Object.keys(raw).some((key) => !keys.includes(key))) invalid(`${label} contains unsupported fields`);
  return raw;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 12_000) {
    invalid(`${label} MUST be bounded non-empty text`);
  }
  return value;
}

function localized(value: unknown, label: string): GuidanceText {
  const raw = object(value, ["en", "ko"], label);
  return { en: text(raw["en"], `${label}.en`), ...(raw["ko"] === undefined ? {} : { ko: text(raw["ko"], `${label}.ko`) }) };
}

function list<T>(value: unknown, min: number, max: number, decode: (item: unknown, label: string) => T, label: string): T[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) invalid(`${label} has an invalid item count`);
  return value.map((item, index) => decode(item, `${label}[${index}]`));
}

function token(value: unknown, label: string): string {
  const result = text(value, label);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}$/.test(result)) invalid(`${label} MUST be a safe identifier`);
  return result;
}

function digest(value: unknown, label: string): string {
  const result = text(value, label);
  if (!/^sha256:[a-f0-9]{64}$/.test(result)) invalid(`${label} MUST be SHA-256`);
  return result;
}

export function guidanceText(value: GuidanceText, locale: string): string {
  return locale === "ko" && value.ko ? value.ko : value.en;
}

export function guidanceMissingKoreanFields(guidance: GuidancePresentation): number {
  const image = guidance.reference_image;
  const fields = [
    guidance.title, guidance.summary, guidance.benefits, guidance.rationale,
    ...guidance.applicability, ...guidance.configuration.before, ...guidance.configuration.after,
    ...guidance.implementation_steps, ...guidance.verification_steps, ...guidance.cautions,
    guidance.diagram.title, guidance.diagram.description,
    ...guidance.diagram.nodes.flatMap((node) => [node.label, node.detail]),
    ...guidance.diagram.edges.map((edge) => edge.label),
    ...(image ? [image.alt, image.caption, image.english_in_image_notice] : []),
  ];
  return fields.filter((field) => !field.ko?.trim()).length;
}

function referenceImage(value: unknown): GuidanceReferenceImage {
  const raw = object(value, [
    "asset_id", "digest", "source_document_url", "image_url", "source_revision",
    "attribution", "license", "license_url", "alt", "caption", "english_in_image_notice",
  ], "reference_image");
  const hash = digest(raw["digest"], "reference_image.digest");
  const asset = text(raw["asset_id"], "reference_image.asset_id");
  if (asset !== hash.replace("sha256:", "sha256-")) invalid("reference_image asset identifier does not match its digest");
  const revision = text(raw["source_revision"], "reference_image.source_revision");
  if (!/^[a-f0-9]{40}$/.test(revision)) invalid("reference_image.source_revision MUST be a pinned commit");
  const sourceUrl = (key: string): string => {
    const url = text(raw[key], `reference_image.${key}`);
    let parsed: URL;
    let decoded: string;
    try { parsed = new URL(url); decoded = decodeURIComponent(url); }
    catch { invalid(`reference_image.${key} MUST be a public Learn URL`); }
    if (parsed.protocol !== "https:" || parsed.hostname !== "learn.microsoft.com"
      || parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash
      || !url.startsWith("https://learn.microsoft.com/en-us/") || url.length > 2_048 || /[^\x21-\x7e]/.test(url)
      || decoded.includes("\\") || decoded.split("/").some((part) => part === "." || part === "..")
      || /[\x00-\x20]/.test(decoded)) invalid(`reference_image.${key} MUST be a public Learn URL`);
    return url;
  };
  if (raw["license"] !== "CC-BY-4.0" || raw["license_url"] !== "https://creativecommons.org/licenses/by/4.0/") {
    invalid("reference_image license is not reviewed");
  }
  const imageText = (key: string): GuidanceText => {
    const result = localized(raw[key], `reference_image.${key}`);
    if (/[<>]/.test(result.en) || /[<>]/.test(result.ko ?? "") || result.en.length > 4_000 || (result.ko?.length ?? 0) > 4_000) invalid("reference_image text MUST be bounded and MUST NOT contain markup");
    return result;
  };
  const attribution = text(raw["attribution"], "reference_image.attribution");
  if (attribution.length > 512) invalid("reference_image.attribution is too long");
  return {
    asset_id: asset, digest: hash, source_document_url: sourceUrl("source_document_url"), image_url: sourceUrl("image_url"),
    source_revision: revision, attribution,
    license: "CC-BY-4.0", license_url: "https://creativecommons.org/licenses/by/4.0/",
    alt: imageText("alt"), caption: imageText("caption"), english_in_image_notice: imageText("english_in_image_notice"),
  };
}

export function decodeWaraGuidance(value: unknown, control: GuidanceIdentity): WaraGuidance | null {
  if (value === undefined || value === null) return null;
  const raw = object(value, [
    "schema_version", "recommendation_id", "source_revision", "source_digest", "lifecycle",
    "title", "summary", "benefits", "rationale", "applicability", "configuration",
    "implementation_steps", "verification_steps", "cautions", "diagram", "sources", "content_digest", "reference_image",
  ], "entry");
  if (raw["schema_version"] !== "1.0.0") invalid("schema_version MUST be 1.0.0");
  for (const [field, expected] of [
    ["recommendation_id", control.id], ["source_revision", control.source_revision],
    ["source_digest", control.source_digest], ["lifecycle", control.lifecycle],
  ] as const) {
    if (raw[field] !== expected) invalid(`${field} does not match the selected recommendation`);
  }
  if (!["active", "disabled"].includes(control.lifecycle)) invalid("lifecycle is unsupported");
  digest(raw["source_digest"], "source_digest");
  return {
    schema_version: "1.0.0", recommendation_id: control.id, source_revision: control.source_revision,
    source_digest: control.source_digest, lifecycle: control.lifecycle as WaraGuidance["lifecycle"],
    ...decodeGuidancePresentation(raw, control.source_revision),
    content_digest: digest(raw["content_digest"], "content_digest"),
  };
}

export function decodeGuidancePresentation(
  raw: Record<string, unknown>, sourceRevision: string, framework = false,
): GuidancePresentation {
  const config = object(raw["configuration"], ["before", "after"], "configuration");
  const diagram = object(raw["diagram"], ["id", "kind", "title", "description", "nodes", "edges"], "diagram");
  const nodes = list(diagram["nodes"], 3, 9, (item, label): GuidanceNode => {
    const node = object(item, ["id", "label", "detail", "role"], label);
    const role = text(node["role"], `${label}.role`);
    if (!["subject", "configuration", "dependency", "evidence", "outcome"].includes(role)) invalid(`${label}.role is unsupported`);
    return { id: token(node["id"], `${label}.id`), label: localized(node["label"], `${label}.label`), detail: localized(node["detail"], `${label}.detail`), role: role as GuidanceNode["role"] };
  }, "diagram.nodes");
  if (new Set(nodes.map((node) => node.id)).size !== nodes.length) invalid("diagram node identities MUST be unique");
  const edges = list(diagram["edges"], 2, 12, (item, label): GuidanceEdge => {
    const edge = object(item, ["from", "to", "label", "style"], label);
    const from = token(edge["from"], `${label}.from`);
    const to = token(edge["to"], `${label}.to`);
    if (from === to || !nodes.some((node) => node.id === from) || !nodes.some((node) => node.id === to)) invalid(`${label} has an invalid node reference`);
    if (edge["style"] !== "solid" && edge["style"] !== "dashed") invalid(`${label}.style is unsupported`);
    return { from, to, label: localized(edge["label"], `${label}.label`), style: edge["style"] };
  }, "diagram.edges");
  if (new Set(edges.map((edge) => `${edge.from}/${edge.to}`)).size !== edges.length) invalid("diagram edges MUST be unique");
  if (nodes.some((node) => !edges.some((edge) => edge.from === node.id || edge.to === node.id))) invalid("diagram contains an isolated node");
  const sources = list(raw["sources"], 1, 8, (item, label) => {
    const source = object(item, ["label", "url", "kind"], label);
    if (framework ? source["kind"] !== "learn" : source["kind"] !== "aprl" && source["kind"] !== "learn" && source["kind"] !== "vendor") invalid(`${label}.kind is unsupported`);
    const url = text(source["url"], `${label}.url`);
    let parsed: URL;
    try { parsed = new URL(url); } catch { invalid(`${label}.url MUST be an absolute source URL`); }
    const approved = source["kind"] === "vendor"
      ? url === "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html"
      : source["kind"] === "learn"
        ? parsed.hostname === "learn.microsoft.com"
        : (parsed.hostname === "github.com" && parsed.pathname.startsWith(`/Azure/Azure-Proactive-Resiliency-Library-v2/blob/${sourceRevision}/`))
          || (parsed.hostname === "raw.githubusercontent.com" && parsed.pathname.startsWith(`/Azure/Azure-Proactive-Resiliency-Library-v2/${sourceRevision}/`));
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port || parsed.search || /[\u0000-\u0020]/.test(url) || !approved) {
      invalid(`${label}.url MUST identify an approved source; APRL references MUST be revision-pinned`);
    }
    return { label: localized(source["label"], `${label}.label`), url, kind: source["kind"] as "aprl" | "learn" | "vendor" };
  }, "sources");
  if (!framework && !sources.some((source) => source.kind === "aprl")) invalid("MUST cite the revision-pinned APRL source");
  return {
    title: localized(raw["title"], "title"), summary: localized(raw["summary"], "summary"),
    benefits: localized(raw["benefits"], "benefits"), rationale: localized(raw["rationale"], "rationale"),
    applicability: list(raw["applicability"], 2, 12, localized, "applicability"),
    configuration: { before: list(config["before"], 2, 12, localized, "configuration.before"), after: list(config["after"], 2, 12, localized, "configuration.after") },
    implementation_steps: list(raw["implementation_steps"], 3, 12, localized, "implementation_steps"),
    verification_steps: list(raw["verification_steps"], 3, 12, localized, "verification_steps"),
    cautions: list(raw["cautions"], 2, 12, localized, "cautions"),
    ...(raw["reference_image"] === undefined || raw["reference_image"] === null ? {} : { reference_image: referenceImage(raw["reference_image"]) }),
    diagram: { id: token(diagram["id"], "diagram.id"), kind: token(diagram["kind"], "diagram.kind"), title: localized(diagram["title"], "diagram.title"), description: localized(diagram["description"], "diagram.description"), nodes, edges },
    sources,
  };
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, item]) => [key, canonicalValue(item)]));
  }
  return value;
}

export async function verifyWaraGuidanceDigest<T extends { readonly content_digest: string }>(guidance: T | null | undefined): Promise<void> {
  if (!guidance) return;
  const { content_digest, ...material } = guidance;
  // Match the shared catalog's ASCII canonical wire encoding, not the source-file encoding.
  const canonical = JSON.stringify(canonicalValue(material)).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  const bytes = new TextEncoder().encode(canonical);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  const actual = `sha256:${Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
  if (actual !== content_digest) invalid("content_digest does not match the illustrated material");
}
