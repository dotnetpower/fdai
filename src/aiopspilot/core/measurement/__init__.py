"""Continuous measurement + growth for the Phase 4 Azure baseline.

Phase 4 § Continuous Measurement / Pattern Library Growth / Model
Cost-Quality Tracking / Scalability. Multi-cloud items in phase-4-scale
are **TBD (deferred)** and NOT built here (see Implementation Focus in
`.github/copilot-instructions.md`).

The five modules here are:

- :mod:`.regression` — baseline-vs-treatment regression detection with
  automatic demotion to shadow on guard-metric breaches.
- :mod:`.pattern_growth` — T1 pattern-library growth guardrails
  (auto-resolved-only intake + temporal-holdout validation).
- :mod:`.model_tracking` — per-model cost/quality tracker; swaps are
  proposed only when the improvement clears a threshold **and** the
  guard metrics have not regressed.
- :mod:`.latency_budget` — per-tier latency budget monitor.
- :mod:`.runners` — scheduled runners that wire the two library-only
  measurement components (:mod:`.regression`, :mod:`.pattern_growth`)
  into Container Apps Jobs: the automated-baseline regression runner
  and the pattern-growth intake runner.
"""

from __future__ import annotations
