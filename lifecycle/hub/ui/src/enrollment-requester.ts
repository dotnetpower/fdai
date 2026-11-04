import type { PendingEnrollment } from "./api";
import { tr, type HubLocale } from "./locale";

const SHORT_ID_LENGTH = 8;

export interface EnrollmentRequester {
  label: string;
  // True only for a request the installation Agent proposed; approval still belongs to a human.
  fromAgent: boolean;
}

export function enrollmentRequester(
  request: Pick<PendingEnrollment, "requested_by" | "requested_via">,
  locale: HubLocale = "en",
): EnrollmentRequester {
  const via = request.requested_via ?? null;
  const by = request.requested_by ?? null;
  if (via === "agent" && by) {
    const shortId = by.slice(0, SHORT_ID_LENGTH);
    return {
      label: tr(
        locale,
        `Requested by installation Agent ${shortId}`,
        `설치 에이전트(${shortId})가 요청함`,
      ),
      fromAgent: true,
    };
  }
  if (via === "operator" && by) {
    return {
      label: tr(locale, "Requested by operator", "운영자가 요청함"),
      fromAgent: false,
    };
  }
  return {
    label: tr(locale, "Requested from a signed file", "서명된 파일로 요청됨"),
    fromAgent: false,
  };
}
