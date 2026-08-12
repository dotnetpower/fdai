---
name: roadmap-implementation-tracking
description: |
  Maintain truthful, resumable implementation ledgers in FDAI roadmap docs.
  Use when adding or reviewing implementation scope, implementation status,
  delivery history, evidence, progress records, remaining work, roadmap TODOs,
  or when a roadmap implementation-tracking gate fails. Also use when adopting
  the ledger in an existing roadmap document without inventing historical
  commits or validation evidence.
version: 1.0.0
scope: repository
---

# Roadmap Implementation Tracking

This workflow keeps each roadmap owner document useful after design approval.
It turns delivery state into an evidence-backed ledger that another maintainer
can resume without reading the entire repository history.

The normative contract is
[../../instructions/roadmap-implementation-tracking.instructions.md](../../instructions/roadmap-implementation-tracking.instructions.md).
This skill explains how to apply it safely.

## When to Use This Skill

Use this skill when you:

- implement, validate, defer, roll back, or supersede roadmap-owned behavior;
- add the ledger to an existing roadmap owner document;
- review whether a status claim is supported by source, tests, or runtime evidence;
- convert free-form status prose or TODOs into resumable records;
- fix a roadmap implementation-tracking validation failure.

Do not use it to manufacture a historical changelog. If evidence is absent,
record that provenance was not reconstructed and start from the provable
current state.

## Workflow

### 1. Identify the owner document

Confirm that the canonical English file owns the behavior rather than merely
indexing or linking to it. Exempt README/index files, Korean translations, the
FDAI Constitution, and immutable architecture decision records from the
canonical ledger check.

If implementation spans several owner documents, update only the documents
whose declared scope changed. Do not copy the same ledger into neighboring
documents.

### 2. Establish the evidence boundary

Inspect the smallest relevant set of source, catalog, migration, tests, issues,
and governed runtime records. Separate these evidence levels:

| Evidence | Strongest usual claim |
|----------|-----------------------|
| Design text or issue only | `not-started` or `deferred` |
| Implementation path without a passing focused check | `in-progress` |
| Implementation path plus passing focused checks | `implemented` |
| Required runtime or operational receipt plus implementation checks | `validated` |

Lower the state when evidence conflicts. Do not infer production use from code
presence, a passing unit test, or an enabled-looking configuration value.

### 3. Update implementation scope

Create or revise the `Area`, `State`, `Evidence`, and `Notes` table. Use one row
per independently deliverable area. Preserve design boundaries and avoid broad
rows such as "all functionality".

### 4. Append the transition

Add one dated history row for the current material transition. Include:

- the resulting state;
- the concrete change in behavior or evidence;
- task-owned paths and focused checks;
- the meaningful residual work after this transition.

Use an existing commit, pull request, issue, or receipt when it already exists.
For the same commit, write `current change` with paths and checks. Never guess
the future SHA.

For first adoption with incomplete history, use wording such as:

```markdown
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | Current source and focused checks listed in the scope table. | Validate the open items below. |
```

Do not invent earlier rows from memory, file timestamps, blame alone, or an
unverified status paragraph.

### 5. Make remaining work resumable

Write open Markdown task-list items with observable exit conditions. Prefer:

```markdown
- [ ] Record a passing `<focused command>` result for `<bounded behavior>` and
  link the resulting validation receipt.
```

Avoid vague items such as "finish implementation", "improve tests", or "TBD".
When scope is complete, keep one checked completion item with supporting
evidence rather than leaving the section empty.

### 6. Synchronize and validate

Update the Korean sibling with equivalent content and refresh its source SHA:

```bash
python3 scripts/quality/localization/refresh-translation-sha.py
```

Run the roadmap tracking check first, then the translation and punctuation
checks for changed docs. Run the narrow implementation tests cited by the new
history row. A ledger is not evidence for itself.

## Review Checklist

- The document owns the behavior it tracks.
- Every scope state is no stronger than its evidence.
- The newest material transition has one append-only history row.
- Same-change evidence uses `current change`, paths, and focused checks.
- Historical gaps are disclosed instead of reconstructed.
- Every unchecked item has an observable exit condition.
- A completion item cites evidence and does not hide deferred scope.
- English and Korean ledgers carry the same information.
