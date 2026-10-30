import { useState } from "preact/hooks";
import { getLocale } from "../i18n";
import { t } from "./i18n/governance";
import { guidanceText, type GuidanceReferenceImage } from "./wara-guidance.model";

export function WaraGuidanceReferenceImage({ image }: { readonly image: GuidanceReferenceImage }) {
  const [failed, setFailed] = useState(false);
  const locale = getLocale();
  const assetUrl = `/wara-guidance-assets/${image.asset_id}.png`;
  return <figure class="wara-guidance-source-figure" data-reference-image={image.asset_id}>
    <header class="wara-guidance-figure-head">
      <p class="wara-guidance-eyebrow">{t("governance.rules.wara.guidance.officialImage")}</p>
      <a href={image.source_document_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.guidance.originalDocument")}</a>
    </header>
    {failed
      ? <>
        <p class="wara-guidance-unavailable" role="alert">{t("governance.rules.wara.guidance.imageUnavailable")}</p>
        <p>{guidanceText(image.alt, locale)}</p>
      </>
      : <img src={assetUrl} alt={guidanceText(image.alt, locale)} decoding="async" onError={() => setFailed(true)} />}
    <figcaption>
      <p>{guidanceText(image.caption, locale)}</p>
      <p class="wara-guidance-context">{guidanceText(image.english_in_image_notice, locale)}</p>
      <p class="wara-guidance-image-attribution">
        {image.attribution}{" "}
        <a href={image.source_document_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.guidance.sourceDocument")}</a>
        {" · "}<a href={image.license_url} target="_blank" rel="noreferrer">{image.license}</a>
      </p>
    </figcaption>
  </figure>;
}
