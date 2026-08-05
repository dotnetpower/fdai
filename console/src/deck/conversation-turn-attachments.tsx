import { useEffect, useState } from "preact/hooks";

import { t } from "../i18n";
import { fetchConversationImage } from "../user-context-client";
import { conversationImageFetchLimiter } from "./image-fetch-limiter";
import type { TurnAttachment } from "./turn-attachments";

export function withoutAttachmentSource(
  sources: Readonly<Record<string, string>>,
  attachmentId: string,
): Readonly<Record<string, string>> {
  return { ...sources, [attachmentId]: "" };
}

export function ConversationTurnAttachments({
  attachments,
}: {
  readonly attachments: readonly TurnAttachment[];
}) {
  const [sources, setSources] = useState<Readonly<Record<string, string>>>(() =>
    directSources(attachments));
  const [loading, setLoading] = useState(() => attachments.some((item) => !item.src));

  useEffect(() => {
    let active = true;
    const objectUrls: string[] = [];
    setSources(directSources(attachments));
    const pending = attachments.filter((attachment) => !attachment.src);
    setLoading(pending.length > 0);
    if (pending.length === 0) return () => undefined;

    void Promise.all(pending.map(async (attachment) => {
      try {
        const blob = await conversationImageFetchLimiter.run(() =>
          active
            ? fetchConversationImage(attachment.conversationId, attachment.id)
            : Promise.resolve(null));
        if (!active || blob === null) return;
        const source = URL.createObjectURL(blob);
        objectUrls.push(source);
        setSources((current) => ({ ...current, [attachment.id]: source }));
      } catch {
        if (active) setSources((current) => ({ ...current, [attachment.id]: "" }));
      }
    })).finally(() => {
      if (active) setLoading(false);
    });

    return () => {
      active = false;
      for (const source of objectUrls) URL.revokeObjectURL(source);
    };
  }, [attachments]);

  return (
    <div class="deck-turn-attachment-block">
      {loading ? (
        <span class="sr-only" role="status">{t("deck.attach.scanning")}</span>
      ) : null}
      <ul class="deck-turn-attachments" aria-label={t("deck.attach.tray")}>
        {attachments.map((attachment) => {
          const source = sources[attachment.id];
          return (
            <li key={attachment.id}>
              {source ? (
                <img
                  src={source}
                  alt={attachment.name}
                  onError={() => setSources((current) =>
                    withoutAttachmentSource(current, attachment.id))}
                />
              ) : (
                <span
                  class="deck-turn-attachment-placeholder"
                  role="img"
                  aria-label={`${attachment.name}: ${loading ? t("deck.attach.scanning") : t("deck.attach.readFailed")}`}
                />
              )}
              <span class="deck-turn-attachment-name">{attachment.name}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function directSources(
  attachments: readonly TurnAttachment[],
): Readonly<Record<string, string>> {
  return Object.fromEntries(
    attachments.flatMap((attachment) =>
      attachment.src ? [[attachment.id, attachment.src]] : []),
  );
}
