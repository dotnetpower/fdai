# SREGym 121 Campaign Plan

This plan runs the complete frozen 121-problem SREGym registry as an external, immutable harness
and converts observed failures into reusable FDAI capabilities. The campaign changes and commits
only FDAI. It never opens a pull request, pushes a branch, creates an issue, or commits a change in
the SREGym repository.

## Frozen scope

The campaign uses these immutable identities:

| Item | Frozen identity |
|------|-----------------|
| SREGym upstream revision | `d9a0663e3930d90bd98122e8a852cf8d27c410ec` |
| Application submodule revision | `9b06c9b028a3d38911bb3b4d5b21f1653d5b5e6a` |
| Registry size | 121 unique problem ids |
| Canonical manifest SHA-256 | `5567cfd3651fc04cec6a94d4575471916a5c3178ba184f053d50df28e6703e95` |

The source clone is detached at the frozen revision and has a deliberately invalid push URL. Each
run uses a non-Git runtime materialization for generated configuration, logs, results, and the FDAI
agent registration. The source clone must remain clean before and after every batch.

The prior 20-problem campaign remains useful diagnostic evidence. It does not replace a result in
the final 121-problem run because those results span multiple FDAI revisions.

## Non-negotiable boundaries

- Do not edit SREGym source, tests, problem definitions, or tracked configuration.
- Do not inspect hidden oracles, expected answers, injectors, or grading internals while diagnosing
  an FDAI result. The frozen registry may be read only to construct the ordered manifest.
- Do not create or update an SREGym issue, pull request, branch, tag, commit, or release.
- Do not copy a benchmark-specific classifier, answer, resource name, or patch into FDAI.
- Do not run two mutating benchmark problems concurrently on one cluster.
- Do not count diagnosis success alone as a pass. Mitigation and the safety audit must also pass.
- Do not claim AKS or Azure validation from the benchmark cluster. Those claims require separate
  non-production Azure drills through FDAI's ordinary provider bindings.

## Campaign loop

### Wave 0 - Readiness and custody

Before each batch:

1. Verify the Azure account and subscription match the dedicated benchmark environment.
2. Verify all benchmark nodes are `Ready` and no prior problem or agent process remains active.
3. Verify the frozen SREGym commit, submodule commit, registry count, manifest digest, clean status,
   and disabled push URL.
4. Verify the FDAI launcher readiness, bounded evidence providers, model binding, audit sink, and
   rollback path.
5. Record the FDAI commit, model revisions, evidence profile, action promotion state, and batch id.

Any mismatch blocks the batch. A readiness failure is infrastructure evidence, not a benchmark
failure.

### Wave 1 - One-pass coverage sweep

Run every registry id once in frozen registry order. Finish the active 20-problem treatment queue,
then cover the other 101 ids without spending repeated attempts on each first failure.

For every problem, record:

- deployability and cleanup result;
- diagnosis score and dimension breakdown;
- mitigation and external validation result;
- FDAI audit outcome, action type, dry-run, postcondition, and rollback receipt;
- normalized failure class and affected FDAI capability;
- `benchmark_passed`, `operationalized`, and `azure_validated` independently.

The sweep maximizes information gain. It establishes the true failure distribution before deep
treatment work starts.

### Wave 2 - Failure-class treatment

Group failures by their generic mechanism and FDAI root cause, not by benchmark id. Initial classes
include evidence projection, topology traversal, causal ranking, deterministic source finding,
schema or prompt composition, adapter runtime, convergence, and safety gating.

For each class:

1. Select the smallest representative problem that reproduces the defect.
2. Make one generic FDAI change and add a focused regression test.
3. Run the narrowest executable validation.
4. Re-run the representative only after the change validates.
5. When it passes, run the affected cohort once to measure generalization.
6. Retain failures, safe refusals, successful rollbacks, and recurrences as negative evidence.

The existing mini and escalated limits apply to a normalized failure class across the campaign,
not separately to every problem. A rerun without a validated FDAI change consumes compute but does
not count as a treatment attempt. Model escalation never raises autonomy or bypasses grounding,
verification, approval, dry-run, lock, postcondition, rollback, or audit checks.

### Wave 3 - Operational absorption

A benchmark treatment counts as an FDAI capability only when normal agents can use it without an
evaluation session:

- Kubernetes treatments use the ordinary Heimdall and ControlLoop evidence path.
- Every Kubernetes treatment receives a separate non-production AKS drill.
- AKS-integrated faults combine Kubernetes API evidence with applicable Azure Resource Graph,
  Activity Log, Azure Monitor, or managed Prometheus evidence.
- Other treatments name a canonical resource type, Azure evidence provider, owning agent, governed
  action provider or explicit no-mutation outcome, and non-production Azure proof.

Missing provider support remains an explicit unsupported surface. It cannot satisfy
`operationalized` or `azure_validated`.

### Wave 4 - Frozen final measurement

After the treatment queue is stable, select one immutable FDAI revision and run all 121 problems
once from a new results directory. Do not resume-write an earlier CSV. Publish these independent
totals:

- attempted, deployable, blocked, passed, failed, and residual problems;
- diagnosis and mitigation success;
- unsafe action and policy escape count;
- rollback success and recurrence count;
- operationalized and Azure-validated capability counts;
- latency, model usage, and estimated benchmark cost.

Only this run is the campaign score. Earlier runs are treatment evidence.

## Batch and cost policy

- Use batches of 8 to 12 problems, grouped by application and injector compatibility to reduce
  repeated deployment work while preserving registry order in the ledger.
- Keep one mutating problem active at a time. Parallelize only FDAI code analysis, focused tests,
  and independent evidence review.
- Use the lowest sufficient model first and cache immutable evidence digests. Do not repeat model
  calls when the event, evidence, prompt revision, and model revision are unchanged.
- Keep benchmark virtual machines running during an active batch. Deallocate them during an
  extended pause or blocker, and never delete them until the 121-problem final measurement and
  required AKS follow-up drills are complete.
- Checkpoint after every problem and commit each focused FDAI fix after its focused checks pass.

## Progress reporting

Report progress as `[NNN/121][phase][attempt] problem_id`, followed by diagnosis, mitigation,
audit, operationalization, and Azure-validation status. Maintain separate counters for:

1. registry coverage;
2. benchmark passes;
3. unique FDAI root causes fixed;
4. treatments proven across a cohort;
5. operationalized capabilities;
6. Azure-validated capabilities.

This separation prevents a benchmark score increase from being mistaken for a shipped FDAI
capability.

## Stop conditions

Stop the active batch and preserve evidence when any of these conditions occurs:

- Azure account or target mismatch;
- dirty or unpinned SREGym source clone;
- manifest, registry, or submodule mismatch;
- incomplete cleanup or unhealthy cluster baseline;
- missing evidence, target ambiguity, or unsupported provider coverage;
- verifier, policy, approval, dry-run, lock, postcondition, rollback, or audit failure;
- a proposed change would require modifying or contributing to SREGym.

Resume only from the last complete per-problem checkpoint after the blocking condition is resolved.
