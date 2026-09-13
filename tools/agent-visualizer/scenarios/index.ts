import { copy, type Activity, type AgentId, type Scenario } from "../src/model";

function event(
  at: number, agent: AgentId, from: AgentId | undefined, stage: Activity["stage"],
  title: [string, string], detail: [string, string], duration = 5,
): Activity {
  return { at, agent, from, stage, duration, title: copy(...title), detail: copy(...detail) };
}

/** Authored illustrations, not recordings, observed calls, approvals, or resource actions. */
export const scenarios: readonly Scenario[] = [
  {
    id: "safe-change", source: "synthetic-demo", duration: 72,
    title: copy("The anatomy of a safe change", "안전한 변경의 흐름"),
    description: copy("From the first signal to independent verification.", "첫 신호부터 독립적인 검증까지."),
    events: [
      event(0, "Huginn", undefined, "observe", ["A signal enters", "신호 수신"], ["Illustrated change event enters the collection boundary.", "예시 변경 이벤트가 수집 경계에 도착합니다."]),
      event(5, "Heimdall", "Huginn", "observe", ["Context takes shape", "맥락 형성"], ["The observer correlates signals without assuming causation.", "관측자가 인과관계를 단정하지 않고 신호를 연관 짓습니다."]),
      event(10, "Njord", undefined, "observe", ["Cost context arrives", "비용 맥락 도착"], ["A parallel cost signal contributes domain context.", "병렬 비용 신호가 도메인 맥락을 제공합니다."]),
      event(13, "Freyr", undefined, "observe", ["Capacity is considered", "용량 검토"], ["Capacity evidence adds another view of the proposed change.", "용량 근거가 제안된 변경에 대한 관점을 더합니다."]),
      event(17, "Forseti", "Heimdall", "reason", ["Evidence before judgment", "판정보다 근거가 먼저"], ["Deterministic rules evaluate the illustrated evidence. No model is invoked.", "결정론적 규칙으로 예시 근거를 평가합니다. 모델을 호출하지 않습니다."], 7),
      event(21, "Odin", "Forseti", "reason", ["Priorities are reconciled", "우선순위 조정"], ["Portfolio arbitration resolves an illustrated priority conflict, not approval.", "포트폴리오 중재로 예시 우선순위 충돌을 조정합니다. 승인은 아닙니다."]),
      event(26, "Forseti", "Odin", "reason", ["A bounded decision", "범위가 제한된 결정"], ["The decision remains separate from approval and execution.", "결정은 승인 및 실행과 분리됩니다."]),
      event(31, "Var", "Forseti", "review", ["A human decision boundary", "사람의 결정 경계"], ["This scripted approval illustration is not a real authorization.", "각본에 따른 승인 예시이며 실제 실행 권한을 부여하지 않습니다."], 7),
      event(34, "Saga", undefined, "remember", ["Intent is recorded", "의도 기록"], ["Audit intent precedes any illustrated execution.", "예시 실행에 앞서 감사 의도를 기록합니다."]),
      event(37, "Vidar", undefined, "review", ["Recovery is prepared", "복구 준비"], ["A tested rollback path is a prerequisite, not an optional afterthought.", "검증된 롤백 경로는 선택 사항이 아닌 전제 조건입니다."]),
      event(42, "Thor", "Var", "review", ["Dispatch is not success", "전달은 성공이 아닙니다"], ["Illustrated preflight and dispatch only. No managed resources are changed.", "실행 전 검사와 전달을 예시로 보여 줍니다. 관리 리소스를 변경하지 않습니다."], 6),
      event(48, "Heimdall", "Thor", "verify", ["Observe the actual effect", "실제 효과 관측"], ["An independent observer, not the executor receipt, verifies the expected effect in this story.", "이 시나리오에서는 실행 접수 기록이 아닌 독립 관측자가 예상 효과를 검증합니다."], 6),
      event(54, "Saga", "Heimdall", "remember", ["Close the evidence trail", "근거 이력 마무리"], ["The illustrative verification outcome joins the audit trail.", "예시 검증 결과를 감사 이력에 연결합니다."]),
      event(59, "Muninn", "Saga", "remember", ["Experience becomes memory", "경험이 기억으로"], ["State snapshots and case context preserve the evidence.", "상태 스냅샷과 사례 맥락으로 근거를 보존합니다."]),
      event(64, "Bragi", "Saga", "remember", ["Make the outcome legible", "결과를 이해할 수 있게"], ["A plain-language explanation closes the loop. This entire scene is synthetic.", "이해하기 쉬운 설명으로 흐름을 마칩니다. 화면 전체가 합성 예시입니다."]),
    ],
  },
  {
    id: "recovery", source: "synthetic-demo", duration: 56,
    title: copy("When the safer path is back", "더 안전한 길이 복구일 때"),
    description: copy("A recovery story, with every boundary intact.", "모든 안전 경계를 지키는 복구 이야기."),
    events: [
      event(0, "Loki", undefined, "observe", ["Test resilience, deliberately", "의도적인 복원력 점검"], ["A synthetic experiment proposal introduces the story. No experiment runs.", "합성 실험 제안으로 이야기를 시작합니다. 실제 실험은 실행하지 않습니다."]),
      event(6, "Heimdall", "Loki", "observe", ["An unexpected signal", "예상 밖의 신호"], ["The observer detects an illustrated deviation.", "관측자가 예시 편차를 탐지합니다."]),
      event(12, "Forseti", "Heimdall", "reason", ["Hold at the safety boundary", "안전 경계에서 보류"], ["The illustrated judgment requires a human-reviewed recovery path.", "예시 판정은 사람이 검토한 복구 경로를 요구합니다."]),
      event(18, "Var", "Forseti", "review", ["Human review", "사람 검토"], ["Scripted review is visibly synthetic and grants no authority.", "각본에 따른 합성 검토이며 실행 권한을 부여하지 않습니다."]),
      event(23, "Saga", undefined, "remember", ["Preserve the intent", "의도 보존"], ["The recovery intent is illustrated before dispatch.", "전달에 앞서 복구 의도 기록을 보여 줍니다."]),
      event(28, "Vidar", undefined, "review", ["Prepare the rollback", "롤백 준비"], ["Vidar coordinates recovery; Thor remains the sole executor.", "Vidar는 복구를 조정하며 Thor가 유일한 실행자로 유지됩니다."]),
      event(34, "Thor", "Vidar", "review", ["A bounded recovery dispatch", "범위가 제한된 복구 전달"], ["A visual handoff through the event bus, not a direct agent call.", "이벤트 버스를 통한 전달을 시각화합니다. 에이전트 직접 호출이 아닙니다."]),
      event(40, "Heimdall", "Thor", "verify", ["Verify independently", "독립적으로 검증"], ["Independent effect evidence is required to close recovery.", "복구를 마무리하려면 독립적인 효과 근거가 필요합니다."]),
      event(46, "Saga", "Heimdall", "remember", ["An attributable outcome", "추적 가능한 결과"], ["The scenario ends with an illustrative audit record, not a live success claim.", "실제 성공을 주장하지 않고 예시 감사 기록으로 마칩니다."]),
    ],
  },
  {
    id: "knowledge", source: "synthetic-demo", duration: 60,
    title: copy("Signals become understanding", "신호가 이해로 이어지는 과정"),
    description: copy("Observation, domain context, and governed memory.", "관측과 도메인 맥락, 통제된 기억."),
    events: [
      event(0, "Bragi", undefined, "observe", ["Start with intent", "의도에서 시작"], ["Natural language becomes typed intent, never authority.", "자연어를 타입화된 의도로 변환합니다. 권한은 부여하지 않습니다."]),
      event(6, "Huginn", undefined, "observe", ["Collect the evidence", "근거 수집"], ["Illustrated intake preserves the source of each signal.", "예시 수집 과정에서 각 신호의 출처를 보존합니다."]),
      event(12, "Heimdall", "Huginn", "observe", ["Connect the observations", "관측 연결"], ["Relationships add context without proving causation.", "관계는 맥락을 더하지만 인과관계를 증명하지는 않습니다."]),
      event(17, "Njord", undefined, "observe", ["Understand cost", "비용 이해"], ["Cost-domain signals remain distinct from operational health.", "비용 도메인 신호를 운영 상태와 구분합니다."]),
      event(22, "Freyr", undefined, "observe", ["Understand capacity", "용량 이해"], ["Forecasts are contextual evidence, not guaranteed outcomes.", "예측은 맥락 근거이며 보장된 결과가 아닙니다."]),
      event(28, "Forseti", "Heimdall", "reason", ["Evaluate, deterministically", "결정론적 평가"], ["Rules resolve a repeatable illustrated case without a model call.", "모델 호출 없이 규칙으로 반복 가능한 예시 사례를 처리합니다."]),
      event(34, "Mimir", undefined, "remember", ["Govern the rule lifecycle", "규칙 수명 주기 관리"], ["Rule knowledge remains versioned and governed.", "규칙 지식은 버전과 거버넌스에 따라 관리됩니다."]),
      event(40, "Muninn", undefined, "remember", ["Retain experience", "경험 보존"], ["State snapshots and context indexes preserve case history.", "상태 스냅샷과 맥락 인덱스로 사례 이력을 보존합니다."]),
      event(46, "Norns", undefined, "remember", ["Learn without self-approval", "자체 승인 없는 학습"], ["Recurring patterns produce inert candidates, never automatic execution authority.", "반복 패턴에서 비활성 후보를 만듭니다. 실행 권한을 자동으로 부여하지 않습니다."]),
      event(52, "Bragi", undefined, "remember", ["Explain what is known", "확인된 내용 설명"], ["The explanation preserves uncertainty and the synthetic source.", "설명에 불확실성과 합성 출처를 그대로 드러냅니다."]),
    ],
  },
];
