/** Small additive navigation catalog: the page's full catalogs stay behind its lazy import. */
import { getLocale } from "../../i18n";

const en = {
  title: "Alert quality",
  subtitle: "Review alert noise evidence and prepare a bounded proposal without changing managed resources.",
};
const ko: typeof en = {
  title: "알림 품질",
  subtitle: "알림 과다 발생의 근거를 검토하고 관리 리소스를 변경하지 않는 제한된 제안을 준비합니다.",
};

/** Resolve navigation on access, with English fallback and no eager route dependency. */
export function alertQualityNavText(key: keyof typeof en): string {
  return (getLocale() === "ko" ? ko[key] : undefined) || en[key];
}
