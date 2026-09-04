import { useState } from "preact/hooks";
import type { ConversationDocumentArtifact } from "./backend-types";
import { chatUrl, requestHeaders } from "./backend-endpoints";
import { t } from "../i18n";
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

  return (
    <section class="deck-document-artifact" aria-label={t("deck.documentArtifact.title")}>
      <div class="deck-document-artifact-meta">
        <strong>{t("deck.documentArtifact.title")}</strong>
        <span>{t("agentActivity.log.rows", { count: artifact.includedRows })}</span>
        <code>sha256:{artifact.sha256.slice(0, 12)}</code>
      </div>
      <details>
        <summary>{t("deck.documentArtifact.title")}</summary>
        <div class="deck-document-artifact-preview">
          <RichContent text={artifact.previewMarkdown} />
        </div>
      </details>
      <div class="deck-document-artifact-actions">
        <button type="button" disabled={downloading !== null} onClick={() => void download("markdown")}>
          {t("deck.documentArtifact.downloadMarkdown")}
        </button>
        {artifact.pdfUrl ? (
          <button type="button" disabled={downloading !== null} onClick={() => void download("pdf")}>
            {t("reports.downloadPdf")}
          </button>
        ) : null}
      </div>
      {error ? <p role="alert">{t("deck.documentArtifact.downloadFailed")}</p> : null}
    </section>
  );
}
