import type { CandidateCheck } from "../api";
import { constraintVerdict, describeConstraintReason } from "../constraint-status";
import { tr, useHubLocale } from "../locale";

export function ConstraintResults({ checks }: { checks: readonly CandidateCheck[] }) {
  const [locale] = useHubLocale();
  if (checks.length === 0) {
    return (
      <p class="note">
        {tr(locale, "No candidate constraint checks recorded.", "기록된 후보 제약 조건 검사가 없습니다.")}
      </p>
    );
  }
  return (
    <ul class="list constraint-results">
      {checks.map((check) => {
        const verdict = constraintVerdict(check);
        const passed = verdict === "passed";
        const waiting = verdict === "waiting";
        return (
          <li key={check.release_id}>
            <span class={`ic ${passed ? "ok" : waiting ? "warn" : "fail"}`} aria-hidden="true">
              {passed ? "✓" : waiting ? "◷" : "✕"}
            </span>
            <div>
              <strong>{check.release_id}</strong>
              {passed ? (
                <div class="soft">{tr(locale, "All constraints passed", "모든 제약 조건 통과")}</div>
              ) : (
                <ul class="constraint-reasons">
                  {check.blocks.map((block, index) => (
                    <li key={`${block.reason_code}-${index}`}>
                      <div>{describeConstraintReason(block.reason_code, locale)}</div>
                      <code class="soft">{block.reason_code}</code>
                      {block.details.length > 0 && <div class="soft">{block.details.join("; ")}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <span class={`constraint-verdict ${passed ? "ok" : waiting ? "warn" : "fail"}`}>
              {passed
                ? tr(locale, "Passed", "통과")
                : waiting
                ? tr(locale, "Waiting", "대기 중")
                : tr(locale, "Blocked", "차단됨")}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
