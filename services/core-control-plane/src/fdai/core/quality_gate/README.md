# `src/fdai/core/quality_gate`

Guards T2. Enforces mixed-model cross-check, re-verifies against policy-as-code and
what-if, and requires grounded citations. Escalates to HIL on disagreement or low
confidence.

The optional **rubric** leg (`rubric.py`) is a subtractive hallucination filter: an
independent judge scores the candidate's `reasoning_trace` against fixed criteria and
the gate folds the minimum score into confidence via `min()` - never additive.
Shadow-first, fail-closed. `self_consistency.py` adds an `action_stability` signal by
sampling the proposer N times. Design: `docs/roadmap/decisioning/hallucination-rubric-gate.md`.
