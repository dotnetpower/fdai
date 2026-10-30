import { useId, useRef, useState } from "preact/hooks";
import { getLocale } from "../i18n";
import { t } from "./i18n/governance";
import { guidanceText, type GuidanceReferenceImage } from "./wara-guidance.model";

export function WaraGuidanceReferenceImage({ image }: { readonly image: GuidanceReferenceImage }) {
  const [failed, setFailed] = useState(false);
  const previewRef = useRef<HTMLDialogElement>(null);
  const previewTitle = useId();
  const locale = getLocale();
  const assetUrl = `/wara-guidance-assets/${image.asset_id}.png`;
  return <figure class="wara-guidance-source-figure" data-reference-image={image.asset_id}>
    <header class="wara-guidance-figure-head">
      <p class="wara-guidance-eyebrow">{t("governance.rules.wara.guidance.officialImage")}</p>
      <div class="wara-guidance-image-actions">
        {!failed ? <button class="btn" type="button" onClick={() => previewRef.current?.showModal()}>{t("governance.rules.wara.guidance.enlargeImage")}</button> : null}
        <a href={image.source_document_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.guidance.originalDocument")}</a>
      </div>
    </header>
    <div class="wara-guidance-image-frame">
      {failed
        ? <>
          <p class="wara-guidance-unavailable" role="alert">{t("governance.rules.wara.guidance.imageUnavailable")}</p>
          <p>{guidanceText(image.alt, locale)}</p>
        </>
        : <img src={assetUrl} alt={guidanceText(image.alt, locale)} decoding="async" onError={() => setFailed(true)} />}
    </div>
    <figcaption>
      <div class="wara-guidance-image-scope" role="note">
        <strong>{t("governance.rules.wara.guidance.imageScope")}</strong>
        <p>{guidanceText(image.caption, locale)}</p>
      </div>
      <p class="wara-guidance-context">{guidanceText(image.english_in_image_notice, locale)}</p>
      <p class="wara-guidance-image-attribution">
        <a href={image.source_document_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.guidance.sourceDocument")}</a>
        {" · "}<a href={image.license_url} target="_blank" rel="noreferrer">{image.license}</a>
      </p>
      <details class="wara-guidance-image-rights">
        <summary>{t("governance.rules.wara.guidance.imageAttribution")}</summary>
        <p>{image.attribution}</p>
      </details>
      <p class="wara-guidance-image-print-attribution">{image.attribution}</p>
    </figcaption>
    <dialog ref={previewRef} class="wara-guidance-image-preview" aria-labelledby={previewTitle}
      onKeyDown={(event) => event.stopPropagation()} onCancel={(event) => event.stopPropagation()}>
      <header>
        <h3 id={previewTitle}>{t("governance.rules.wara.guidance.enlargeImage")}</h3>
        <button class="btn" type="button" onClick={() => previewRef.current?.close()}>{t("governance.common.close")}</button>
      </header>
      <p>{t("governance.rules.wara.guidance.imagePanHint")}</p>
      <div class="wara-guidance-image-viewport" tabIndex={0} role="region" aria-label={t("governance.rules.wara.guidance.enlargeImage")}>
        <img src={assetUrl} alt={guidanceText(image.alt, locale)} onError={() => { setFailed(true); previewRef.current?.close(); }} />
      </div>
      <p>{guidanceText(image.caption, locale)}</p>
      <p class="wara-guidance-image-attribution">{image.attribution}{" "}
        <a href={image.source_document_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.guidance.sourceDocument")}</a>
        {" · "}<a href={image.license_url} target="_blank" rel="noreferrer">{image.license}</a>
      </p>
    </dialog>
  </figure>;
}
