# Java SQL constant-flow guard

Catalog 1.6.0 adds a bounded Java AST guard that vetoes verifier evidence only when a SQL
argument is provably constant. It preserves the original scanner occurrence and canonical
issue. Use the [frozen evidence](managed-verifiers-1.6.0.json) to inspect the precision change
and the reasons that Java SQL still remains in observation mode (`shadow`).

## Proof scope

The guard parses the acquired source with tree-sitter, without rewriting, compiling, importing,
or executing project code. It follows:

- **Local values:** Immutable strings and primitive constants, including a final unconditional
  assignment in the read's own lexical block that dominates earlier definitions. Conditional
  or uncertain final definitions retain the engine evidence.
- **Local maps (guard version 2):** Exact fully qualified `java.util.HashMap` construction,
  constant String keys, standalone `put`, and `get` of a known String value. Unknown keys,
  aliases, escapes, custom dispatch, conditional mutations, and other mutators provide no proof.
  Only a String cast of an already proven String is supported.
  Source-declared or imported `java` types and unresolved wildcard imports also provide no proof.
- **Conditions:** Literal arithmetic, Java 32-bit/64-bit integer overflow, signed division and
  remainder, shift masking, comparisons, Boolean short-circuiting, and fixed switch targets.
  Constant string `charAt` and `length` are supported when UTF-16 indexing is unambiguous.
- **Helper returns:** An unambiguous private static helper in the same class, or a method on an
  exact new nested-class receiver with no constructor, initializer, fields, or inheritance.
  The helper has supported pure operations and local writes only. Every possible return
  needs the same known value.
- **Bounds:** At most 1 MB of source, 25,000 AST nodes, 10,000 expression evaluations,
  depth 32, 32 helper arguments, and a 100 ms parser deadline. Exhaustion provides no proof.

Example: a private helper selects a literal using arithmetic on a single-assignment local.
Its request parameter appears only in the branch that is provably not selected. A query
concatenated with that return is constant, so the guard records `argument_provably_constant`.
The scanner's original issue remains available for review.

The guard does not infer a sanitizer from a helper name or from a literal argument passed to
an unknown call. Overloads, arbitrary receiver dispatch, reflection, unmodeled collections or
casts, loops, unknown calls, custom constructors, field access, and unsupported syntax retain
the engine hit.
A sink inside a loop is unsupported because a textual write after it may reach the next iteration.
Java Unicode escapes are unsupported: Java expands them before lexing, even inside comments,
whereas tree-sitter receives the unexpanded source.

This is a source-level constant slice, not a compiler, whole-program call graph, or general
path-sensitive taint analysis. Exceptions and runtime code generation are not modeled. A guard
miss is not evidence of safety, and engine `unsupported` counts do not represent guard coverage.

## Runtime integration handoff

The runtime verifier and evaluator call the same `java_sql_constant_veto` implementation.
The public runtime integration is:

```python
taint_rule_verifications(
    issues,
    occurrences,
    verifier_catalog,
    repository=acquired.path,
)
```

`repository` is the exact acquired source directory, not the project checkout or an operator-
supplied alternate file. A constant veto returns `NOT_VERIFIED` with reason
`argument_provably_constant`, the guard version, source SHA-256, and sink line in provenance.
Unknown flows use the existing engine decision. A promoted Java SQL rule without the source
binding returns `java_constant_guard_source_unavailable` and cannot raise confidence.
An absent fix-site line similarly returns `java_constant_guard_fix_site_unavailable`.

`code_security_scan_job.py` and repository-backed export in `code_security_cli.py` bind the
exact acquired directory, as does evaluation. Prepared-result acceptance reuses that same
scan pipeline. A source-bound proof removes verifier confidence only, never the base finding.

## Version 2 measurement

Catalog 1.7.0 changes no promotion threshold or promoted list. Dev-only work on the exact local
map and dominating assignments reduces Java SQL false positives from 3 to 2: 15 true positives,
precision 0.8824, recall 0.1119. Frozen holdout evaluation remains 21 true positives and 2 false
positives, precision 0.9130 and recall 0.1511. No verifier loses a true positive in either split.
Java SQL remains in shadow because dev precision is below 0.90. Reflection chosen through
classloader properties remains unknown rather than being treated as a pure local method.
The [version 2 receipt](managed-verifiers-1.7.0.json) binds the unchanged corpus and rule-pack
digests, guard version and source-code digest, promoted set, and actual offline engine process observations.

## Dependency justification

The existing Python AST and open-source taint engine cannot produce Java return summaries.
Two MIT-licensed packages provide parsing only: `tree-sitter` 0.25.2 and
`tree-sitter-java` 0.23.5. They are added to Core runtime dependencies and the root test extra,
with hashes and versions in `uv.lock`. No third-party source code is vendored.
No other locked package changed. Tests used an isolated parser environment with the active
Python 3.13 interpreter, leaving the parent's existing environment unchanged.

Rebuilding the runtime from the updated manifests is required to include these dependencies.
The existing scanner image was used only for its unchanged Opengrep engine observations.

## Frozen results

Development used only `dev` labels. The guard and dependencies were frozen before holdout
analysis; no holdout source was inspected to revise the algorithm. The corpus and its labels
remain byte-identical at version 1.1.0: 710 dev and 681 holdout labels.

The 12 complete offline engine observations from 1.5.0 were reused because rule bytes were
unchanged. Their stdout hashes, source tree ids, and every scanned-file input digest were
revalidated. The frozen guard and the existing Python verifier evaluation ran again on both
splits. This is explicit engine-observation reuse, not a claim that a new engine process ran.
The receipt also records parser versions, guard/lock input hashes, source-bound vetoes, and
the unchanged two unsupported JS SQL labels.

| Java SQL split | 1.5.0 TP / FP | 1.6.0 TP / FP | Precision before / after | Recall |
|---|---|---|---|---|
| Dev | 15 / 8 | 15 / 3 | 0.6522 / 0.8333 | 0.1119 |
| Holdout | 21 / 10 | 21 / 2 | 0.6774 / 0.9130 | 0.1511 |

All 36 labeled true positives were retained. Thirteen false-positive verifier hits received
explicit constant vetoes, without deleting base findings. All other per-key metrics, including
C# and Java path traversal, are unchanged from 1.5.0 and included in the receipt.
There are no new promotions: Java SQL fails the dev precision floor of 0.90, and the previously
promoted eight keys remain unchanged.

**Remaining blocker:** The three dev false positives require a mutable-map summary (one) or
unresolved reflective dispatch (two). An unknown method can return attacker-controlled state
even when called with a literal argument. Treating that argument as a sanitizer would invent
certainty. These hits are preserved; extending a closed call graph or audited heap model is
separate work. The holdout residuals were not used to design a follow-up.

## Validation

Focused tests cover constant and attacker-controlled flows, overflow, switch fallthrough,
dispatch ambiguity, constructors, mutation, loop backedges, Unicode prelexing, parser deadline
failure, source bounds, runtime/evaluation parity, and source-binding authority.
The focused Python checks passed (127 tests), along with targeted mypy/ruff checks.
The 1.5.0 engine fixture result
(10/10) remains reusable because the rules and engine inputs are unchanged.

The completed focused command is recorded below. The parser path reflects the isolated
Python 3.13 environment used for this checkpoint:

```bash
PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/.fdai/verifier-work/parser-venv/lib/python3.13/site-packages" \
  .venv/bin/python -m pytest -q --no-cov \
  --basetemp="$PWD/.fdai/verifier-work/java-pytest" \
  services/core-control-plane/tests/core/security/code_findings/test_java_constant_guard.py \
  services/core-control-plane/tests/core/security/code_findings/test_verifier.py \
  services/core-control-plane/tests/core/security/code_findings/test_managed_verifiers.py \
  services/core-control-plane/tests/core/security/code_findings/test_verifier_evaluation.py \
  services/core-control-plane/tests/delivery/test_code_security_scanning.py::test_verifier_evaluation_runs_both_verifiers_on_a_pinned_source
```

## Related evidence

| To inspect | Read |
|---|---|
| Historical managed-rule coverage changes | [1.5.0 report](managed-verifiers.md) |
| Frozen metrics and 13 source-bound vetoes | [1.6.0 evidence](managed-verifiers-1.6.0.json) |
| Original pinned labels | [Verifier corpus](verifier-corpus.yaml) |
| Unchanged promotion authority | [Verifier catalog](../verifiers.yaml) |
