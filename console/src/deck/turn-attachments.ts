export const MAX_TURN_ATTACHMENTS = 4;
const MEDIA_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const ATTACHMENT_ID = /^att-[A-Za-z0-9-]{1,124}$/;

export interface TurnAttachment {
  readonly id: string;
  readonly name: string;
  readonly mediaType: string;
  readonly conversationId: string;
  readonly src?: string;
}

export function parseTurnAttachmentMetadata(
  raw: string | undefined,
  conversationId: string,
): TurnAttachment[] {
  if (!raw || raw.length > 4096) return [];
  try {
    return parseTurnAttachments(JSON.parse(raw), conversationId);
  } catch {
    return [];
  }
}

export function parseTurnAttachments(
  value: unknown,
  fallbackConversationId = "",
): TurnAttachment[] {
  if (!Array.isArray(value) || value.length > MAX_TURN_ATTACHMENTS) return [];
  const attachments: TurnAttachment[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const id = record.id;
    const name = record.name;
    const mediaType = record.mediaType ?? record.media_type;
    const conversationId = record.conversationId ?? fallbackConversationId;
    if (
      typeof id !== "string" || !ATTACHMENT_ID.test(id) ||
      typeof name !== "string" || name.length < 1 || name.length > 128 ||
      typeof mediaType !== "string" || !MEDIA_TYPES.has(mediaType) ||
      typeof conversationId !== "string" || conversationId.length < 1 || conversationId.length > 200
    ) return [];
    attachments.push({ id, name, mediaType, conversationId });
  }
  return attachments;
}
