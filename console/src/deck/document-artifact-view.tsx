import { useState } from "preact/hooks";
import type { ConversationDocumentArtifact } from "./backend-types";
import { chatUrl, requestHeaders } from "./backend-endpoints";
import { t } from "./i18n/conversation-layer";
import { RichContent } from "./rich-content";
import "./structured-reply.css";

export function DocumentArtifactView({
  artifact,
}: {
  readonly artifact: ConversationDocumentArtifact;
}) {
  const [downloading, setDownloading] = useState<"markdown" | "pdf" | null>(null);
  const [error, setError] = useState(false);

  const download = async (format: "markdown" | "pdf") => {
    if (downloading) return;
    setDownloading(format);
    setError(false);
    try {
      const path = format === "pdf" ? artifact.pdfUrl : artifact.markdownUrl;
      if (!path) throw new Error("document format is unavailable");
      const response = await fetch(new URL(path, chatUrl()), {
        headers: await requestHeaders(),
        credentials: "omit",
      });
      if (!response.ok) throw new Error(`document download failed: ${response.status}`);
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = format === "pdf"
        ? "fdai-conversation-document.pdf"
        : "fdai-conversation-document.md";
      anchor.click();
      URL.revokeObjectURL(href);
    } catch {
      setError(true);
    } finally {
      setDownloading(null);
    }
  };

  // The conversation layer's document card: title, quiet provenance, the preview in place, and the
  // downloads as affordances.
  return (
    <article class="deck-document-artifact cs-deck-document" aria-label={t("deck.documentArtifact.title")}>
      <h4 class="cs-deck-document-title">{t("deck.documentArtifact.title")}</h4>
      <dl class="cs-deck-document-meta">
        <div>
          <dt>{t("deck.documentArtifact.rows")}</dt>
          <dd>{artifact.includedRows}</dd>
        </div>
        <div>
          <dt>{t("deck.documentArtifact.digest")}</dt>
          <dd><code>sha256:{artifact.sha256.slice(0, 12)}</code></dd>
        </div>
      </dl>
      <details class="cs-deck-disclosure">
        <summary class="cs-deck-disclosure-summary">
          <span class="cs-deck-disclosure-title">{t("deck.documentArtifact.preview")}</span>
          <span class="cs-run-chevron" aria-hidden="true" />
        </summary>
        <div class="deck-document-artifact-preview cs-deck-disclosure-body">
          <RichContent text={artifact.previewMarkdown} />
        </div>
      </details>
      <div class="cs-deck-document-actions">
        <button
          type="button"
          class="cs-deck-affordance"
          disabled={downloading !== null}
          onClick={() => void download("markdown")}
        >
          {t("deck.documentArtifact.downloadMarkdown")}
        </button>
        {artifact.pdfUrl ? (
          <button
            type="button"
            class="cs-deck-affordance"
            disabled={downloading !== null}
            onClick={() => void download("pdf")}
          >
            {t("reports.downloadPdf")}
          </button>
        ) : null}
        {error ? (
          <span class="cs-deck-status is-failure" role="alert">{t("deck.documentArtifact.downloadFailed")}</span>
        ) : null}
      </div>
    </article>
  );
}
