export interface EmailTemplatePreview {
  readonly key: "incident-opened";
  readonly subject: string;
  readonly plainText: string;
  readonly html: string;
}

export function decodeEmailTemplatePreview(value: unknown): EmailTemplatePreview {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("email template preview MUST be an object");
  }
  const item = value as Record<string, unknown>;
  if (item["key"] !== "incident-opened") {
    throw new Error("email template preview.key is invalid");
  }
  return {
    key: "incident-opened",
    subject: nonEmptyString(item["subject"], "email template preview.subject"),
    plainText: nonEmptyString(item["plain_text"], "email template preview.plain_text"),
    html: nonEmptyString(item["html"], "email template preview.html"),
  };
}

function nonEmptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${path} MUST be a non-empty string`);
  }
  return value;
}
