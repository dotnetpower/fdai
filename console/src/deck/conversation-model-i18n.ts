import { getLocale } from "../i18n";

const COPY = {
  en: {
    mode: "Conversation mode",
    operatorMode: "Chat",
    discussionMode: "Agent discussion",
    position: "Position",
    critique: "Peer critique",
    consistent: "Consistent",
    conflicting: "Disagreement",
    not_comparable: "Not comparable",
    discussionEvidence: "Evidence",
    discussionConclusion: "Verified conclusion",
    discussionHeld: "Conclusion held",
    completed: "Contributed",
    abstained: "Abstained",
    not_attempted: "Not attempted",
    discussionAttachmentHold: "Remove attachments before starting an agent discussion.",
    label: "Conversation model",
    hint: "Choose the model tier for new questions in this conversation.",
    auto: "Auto",
    t1: "T1 - Fast",
    t2Unavailable: "T2 - Unavailable",
    confirmT2: "T2 responses can take longer and cost more. Use T2 for new questions in this conversation?",
    appliesNext: "The conversation model will apply to the next question.",
  },
  ko: {
    mode: "대화 모드",
    operatorMode: "일반 대화",
    discussionMode: "에이전트 토론",
    position: "기본 발언",
    critique: "동료 비평",
    consistent: "일치",
    conflicting: "의견 불일치",
    not_comparable: "비교 근거 부족",
    discussionEvidence: "근거",
    discussionConclusion: "검증된 결론",
    discussionHeld: "결론 보류",
    completed: "발언 완료",
    abstained: "기권",
    not_attempted: "미시도",
    discussionAttachmentHold: "에이전트 토론을 시작하기 전에 첨부를 제거해 주세요.",
    label: "대화 모델",
    hint: "이 대화의 새 질문에 사용할 모델 등급을 선택합니다.",
    auto: "자동",
    t1: "T1 - 빠른 응답",
    t2Unavailable: "T2 - 사용 불가",
    confirmT2: "T2 응답은 더 오래 걸리고 비용이 증가할 수 있습니다. 이 대화의 새 질문에 T2를 사용하시겠습니까?",
    appliesNext: "선택한 대화 모델은 다음 질문부터 적용됩니다.",
  },
} as const;

export type ConversationModelCopyKey = keyof typeof COPY.en;

export function conversationModelText(key: ConversationModelCopyKey): string {
  return COPY[getLocale()][key];
}

export function conversationT2Label(model: string): string {
  return `T2 - ${model}`;
}
