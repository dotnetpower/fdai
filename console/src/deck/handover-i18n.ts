import { getLocale } from "../i18n";

const EN = {
  opening: "{agent} handover: answer for {minutes} minutes, upload evidence, or continue later.",
  prompt: "Start my handover with {agent}.",
  uploadDocument: "Upload document",
  remindLater: "Remind me later",
  decline: "Decline",
  snoozeDone: "Reminder postponed.",
  declineDone: "Handover declined.",
  commandFailed: "The handover status could not be updated.",
  useDocumentUpload: "use the governed document upload",
} as const;

const KO: Partial<Record<keyof typeof EN, string>> = {
  opening: "{agent} 인수인계: {minutes}분 동안 답변하거나 근거를 업로드하고 나중에 계속하세요.",
  prompt: "{agent}와 인수인계를 시작해 줘.",
  uploadDocument: "문서 업로드",
  remindLater: "나중에 알림",
  decline: "거절",
  snoozeDone: "알림을 연기했습니다.",
  declineDone: "인수인계를 거절했습니다.",
  commandFailed: "인수인계 상태를 업데이트하지 못했습니다.",
  useDocumentUpload: "관리되는 문서 업로드를 사용하세요",
};

export function handoverText(
  key: keyof typeof EN,
  params: Readonly<Record<string, string | number>> = {},
): string {
  const template = (getLocale() === "ko" ? KO[key] : undefined) ?? EN[key];
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : match);
}
