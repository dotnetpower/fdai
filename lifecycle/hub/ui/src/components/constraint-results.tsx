import type { CandidateCheck } from "../api";
import { constraintVerdict, describeConstraintReason } from "../constraint-status";

export function ConstraintResults({ checks }: { checks: readonly CandidateCheck[] }) {
  if (checks.length === 0) {
    return <p class="note">No candidate constraint checks recorded.</p>;
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
                <div class="soft">All constraints passed</div>
              ) : (
                <ul class="constraint-reasons">
                  {check.blocks.map((block, index) => (
                    <li key={`${block.reason_code}-${index}`}>
                      <div>{describeConstraintReason(block.reason_code)}</div>
                      <code class="soft">{block.reason_code}</code>
                      {block.details.length > 0 && <div class="soft">{block.details.join("; ")}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <span class={`constraint-verdict ${passed ? "ok" : waiting ? "warn" : "fail"}`}>
              {passed ? "Passed" : waiting ? "Waiting" : "Blocked"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
