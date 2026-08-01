# Azure SRE Agent vs FDAI Conversation Comparison Ledger

This ledger records matched operator questions, redacted answers, evaluations, and remediation
links for Azure SRE Agent and FDAI. It provides a stable regression baseline and a nonduplicate
question source for continuous conversational assurance.

> Scope: Live answer text is redacted before it enters the repository. Tenant identifiers,
> subscription identifiers, resource names, endpoints, and other deployment-owned values remain
> in local ignored evidence only. A comparison measures operator outcomes, not implementation
> similarity.

## How to use this ledger

Use one immutable run record for each matched execution. Ask the same question against the same
authorized scope as close together as practical. Record evidence time, freshness, unavailable
sources, and product version before assigning scores.

- **Do not overwrite history**: A rerun receives a new run ID and links to the earlier run.
- **Preserve failures**: Keep the original losing answer after a fix so the regression remains
  reproducible.
- **Fix abstractions**: Link a failure to routing, evidence, verification, rendering, or UX work.
  Avoid prompt-specific exceptions.
- **Verify generalization**: Recheck the original question and at least three paraphrases after a
  fix.
- **Keep comparisons fair**: A stale snapshot, narrower scope, unavailable connector, or different
  authorization is part of the evaluation, not an invisible excuse.

## Evaluation rubric

Score each criterion from `0` to `4`. A hard safety or unsupported-claim failure makes the overall
result `fail` regardless of the numeric total.

| Criterion | A score of 4 means |
|-----------|--------------------|
| Correctness | Every material claim agrees with authoritative evidence. |
| Completeness | The answer covers the requested scope without material omissions. |
| Freshness | Time-sensitive claims use current evidence and state observation time. |
| Evidence integrity | Sources are consumed, attributable, bounded, and traceable. |
| Safety | Read and action authority remain explicit and correctly constrained. |
| Actionability | The answer provides a useful next check or governed action when appropriate. |
| Clarity | The answer is direct, well structured, and natural in the requested language. |

The comparison winner is the answer with no hard failure and the stronger operator outcome. A tie
is valid when each answer has a different material advantage and neither resolves the question
better overall.

## Answer contracts

Question generation uses these contracts to vary wording without changing the intended outcome.

| Contract | Required answer behavior |
|----------|--------------------------|
| `LIST` | Return the bounded complete list, total, filters, source, freshness, coverage, and truncation. |
| `STATE` | State the observed condition, scope, observation time, freshness, and unavailable evidence. |
| `HEALTH` | Separate resource state, platform health, customer activity, affected scope, and uncertainty. |
| `DIAG` | Give the strongest supported conclusion, ranked hypotheses, timeline, missing evidence, next check, and verification. |
| `CHANGE` | Attribute actor, operation, result, timestamp, correlation, and attribution limits. |
| `TOPOLOGY` | Show bounded relationships, direction, evidence coverage, impact, and unverified hops. |
| `KNOWLEDGE` | Cite accessible sources, source freshness, retrieval scope, and unsupported gaps. |
| `PROPOSE` | Produce an inert proposal with impact scope, dry run, stop condition, rollback, risk, and required approval. |
| `EXECUTE` | Preserve authorization, approval separation, lock, idempotency, progress, result, audit, and post-check. |
| `CONTEXT` | Resolve prior scope deterministically or ask one bounded clarification without scope drift. |
| `FAILURE` | Preserve partial, stale, unavailable, unauthorized, ambiguous, and truncated limitations. |
| `FORMAT` | Preserve canonical facts and trust state while honoring language, depth, and presentation requests. |

## Execution ledger

### RUN-0001: Stopped database discovery

| Field | Value |
|-------|-------|
| Question ID | `Q001` |
| Executed | `2026-08-01` |
| Locale | Korean |
| Question | `중지된 데이터베이스 있어?` |
| Scope alignment | Same signed-in Azure subscription; FDAI used its server-owned inventory snapshot. |
| Azure SRE Agent answer | Reported four stopped servers across MySQL and PostgreSQL, then separately reported one paused SQL database. Names were redacted. |
| FDAI answer | Reported two stopped PostgreSQL servers from 191 inventory records. Names were redacted. It disclosed an `azure-cli-local` source, snapshot time, and `stale` freshness. |
| Azure SRE Agent evidence | Executed a current Azure Resource Graph query across nine database resource types and displayed the query. |
| FDAI evidence | Executed a deterministic inventory query limited to `postgresql-server` and `sql-database`; showed authority, predicates, matched count, source, snapshot time, freshness, verification, and zero model calls. |
| Material difference | FDAI omitted two stopped MySQL servers because its compiled resource-type filter was narrower. Azure SRE Agent also exposed the adjacent paused state. |
| Winner | Azure SRE Agent for answer correctness, completeness, and freshness. |
| FDAI advantage | Stronger evidence traceability, explicit stale-state disclosure, deterministic verification, and process accounting. |
| Root gap | Broad database intent did not expand through the complete resource-type vocabulary, and the evidence snapshot was stale. |
| General fix | Compile database families from the resource-type catalog and refresh current inventory before making a current-state claim. Preserve evidence and verification details. |
| Regression cohort | `Q001`, `Q002`, `Q003`, `Q004` |
| Status | `gap-confirmed` |

#### RUN-0001 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 2 | 1 | 1 | 4 | 4 | 2 | 4 | 18/28 |

### RUN-0002: English stopped database discovery

| Field | Value |
|-------|-------|
| Question ID | `Q002` |
| Executed | `2026-08-01` |
| Locale | English |
| Question | `Are any databases stopped right now?` |
| Scope alignment | Same signed-in Azure subscription; both products performed a new read after the question. |
| Azure SRE Agent answer | Reported four stopped servers across MySQL and PostgreSQL, then separately reported one paused SQL database. Names were redacted. |
| FDAI answer | Reported 14 stopped or deallocated resources, including the four stopped database servers plus virtual machines and Kubernetes clusters. Names were redacted. |
| Azure SRE Agent evidence | Executed a current Azure Resource Graph query constrained to eight database resource types. |
| FDAI evidence | Executed a deterministic current inventory query constrained only by stopped or VM-deallocated status. The compiled query omitted a database resource-type predicate. |
| Material difference | FDAI found the stopped MySQL servers missed in `RUN-0001`, but lost the database scope and returned ten unrelated compute or Kubernetes resources. |
| Winner | Azure SRE Agent for intent resolution, scope correctness, and concise completeness. |
| FDAI advantage | Stronger source, snapshot, freshness, verification, and zero-model-call accounting. |
| Root gap | The English plural `databases` did not preserve the database-family constraint when combined with a stopped-state predicate. |
| General fix | Resolve singular and plural database terms through the resource-type catalog, intersect them with state predicates, and reject a compiled plan that silently drops an explicit resource class. |
| Regression cohort | `Q001`, `Q002`, `Q003`, `Q004`, plus singular/plural and word-order paraphrases. |
| Status | `gap-confirmed` |

#### RUN-0002 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 1 | 1 | 3 | 4 | 4 | 1 | 2 | 16/28 |

### RUN-0003: Q002 candidate rerun after read API restart

| Field | Value |
|-------|-------|
| Question ID | `Q002` |
| Executed | `2026-08-01` |
| Locale | English |
| Question | `Are any databases stopped right now?` |
| Prior run | `RUN-0002` |
| Candidate state | Uncommitted catalog-driven resource-type resolver loaded by a restarted local read API. |
| Azure SRE Agent answer | Reused the matched `RUN-0002` baseline: four stopped MySQL or PostgreSQL servers and one separately identified paused SQL database. |
| FDAI answer | Reported exactly four stopped MySQL or PostgreSQL servers and excluded unrelated compute and Kubernetes resources. Names were redacted. |
| FDAI evidence | Compiled a database-category resource-type predicate intersected with stopped status, returned four matches, and exposed source, snapshot time, stale freshness, verification, and zero model calls. |
| Material difference | The candidate closed the resource-scope defect from `RUN-0002`. FDAI still used a snapshot about 12 minutes old for a `right now` question, while Azure SRE Agent performed a current query. |
| Winner | Azure SRE Agent because current evidence is material to the explicit `right now` request. |
| FDAI advantage | Equal stopped-database coverage with stronger typed-query, source, freshness, verification, and process disclosure. |
| Root gap | Current-state questions can return an honestly labeled but stale server inventory snapshot instead of refreshing or holding the current claim. |
| General fix | Refresh the server-owned inventory within the current-state freshness budget, or hold the current claim and return the last observation as stale evidence with a refresh action. |
| Regression cohort | `Q001-Q004`, `Q035`, `Q036`, and current-state paraphrases. |
| Status | `scope-fixed-freshness-open` |

#### RUN-0003 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI candidate | 3 | 4 | 1 | 4 | 4 | 2 | 4 | 22/28 |

### RUN-0004: Q002 fresh-cache candidate rerun

| Field | Value |
|-------|-------|
| Question ID | `Q002` |
| Executed | `2026-08-01` |
| Locale | English |
| Question | `Are any databases stopped right now?` |
| Prior run | `RUN-0003` |
| Candidate state | Same uncommitted catalog-driven resolver after the local inventory background refresh completed. |
| Azure SRE Agent answer | Reused the matched `RUN-0002` baseline: four stopped MySQL or PostgreSQL servers and one separately identified paused SQL database. |
| FDAI answer | Reported exactly four stopped MySQL or PostgreSQL servers from a newly refreshed inventory and excluded unrelated resource types. Names were redacted. |
| FDAI evidence | Compiled the database-category and stopped-state intersection, returned four matches from a fresh snapshot, and exposed source, exact observation time, verification, and zero model calls. |
| Material difference | Both products found the four stopped servers. FDAI answered only the requested stopped condition and exposed stronger evidence and process accounting; Azure SRE Agent added one adjacent paused database and a running-list offer. |
| Winner | FDAI for equal factual coverage, more precise scope, stronger evidence integrity, and explicit freshness. |
| FDAI advantage | Typed query, exact snapshot timestamp, fresh-state label, consumed evidence reference, deterministic verification, and zero model calls in 2.1 seconds. |
| Residual risk | After a long idle period, the local stale-while-revalidate provider can return one honestly stale answer before its background refresh completes. |
| General fix | Preserve the current candidate and add a bounded fresh-read contract for explicit current-state intent so the first post-idle answer refreshes or holds instead of claiming `right now` from stale evidence. |
| Regression cohort | `Q001-Q004`, `Q035`, `Q036`, and first-request-after-idle scenarios. |
| Status | `candidate-win-residual-open` |

#### RUN-0004 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI candidate | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0005: Korean database grouping

| Field | Value |
|-------|-------|
| Question ID | `Q003` |
| Executed | `2026-08-01` |
| Locale | Korean |
| Question | `현재 멈춰 있는 DB를 종류별로 보여줘.` |
| Scope alignment | Same signed-in Azure subscription and near-adjacent execution time. |
| Azure SRE Agent answer | Grouped two stopped MySQL servers, two stopped PostgreSQL servers, and one paused SQL database by service type. Names were redacted. |
| FDAI answer | Reported zero matching resources and then listed the type counts for the complete 192-resource inventory. |
| Azure SRE Agent evidence | Executed a current Azure Resource Graph query constrained to database types and stopped or paused state. |
| FDAI evidence | The deterministic inventory branch had evidence, but local intent resolution did not accept the object particle in `DB를`. Public-web planning then ran, and terminal verification accepted an incorrect broad inventory projection. |
| Material difference | FDAI failed both the requested database scope and the type-grouped answer shape. Its source and freshness disclosure did not compensate for the incorrect result. |
| Winner | Azure SRE Agent for correctness, completeness, intent resolution, and presentation. |
| FDAI advantage | Explicit branch availability, evidence references, snapshot provenance, and terminal verification state. |
| Root gap | Korean object particles after a catalog term were not accepted by deterministic phrase matching, allowing a routine local inventory question to escape into broader planning. |
| General fix | Accept Korean object particles at catalog and facet boundaries, preserve local inventory authority, and regression-test the exact question before evaluating grouped presentation. |
| Regression cohort | `Q001-Q004` plus Korean topic, subject, object, and additive particle variants. |
| Status | `gap-confirmed` |

#### RUN-0005 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 0 | 0 | 1 | 3 | 4 | 0 | 1 | 9/28 |

### RUN-0006: Q003 object-particle candidate rerun

| Field | Value |
|-------|-------|
| Question ID | `Q003` |
| Executed | `2026-08-01` |
| Locale | Korean |
| Question | `현재 멈춰 있는 DB를 종류별로 보여줘.` |
| Prior run | `RUN-0005` |
| Candidate state | Korean object particles accepted by catalog and inventory facet phrase matching. |
| Azure SRE Agent answer | Reused the matched `RUN-0005` baseline: stopped MySQL and PostgreSQL servers plus one paused SQL database grouped by service type. |
| FDAI answer | Correctly listed four stopped MySQL or PostgreSQL servers and excluded unrelated resources. It did not group the result by type or include the paused SQL database. |
| FDAI evidence | Executed only the server-owned inventory branch with a database-category and stopped-state intersection; public-web and agent branches did not run. |
| Material difference | The candidate closed the routing and zero-result defects but still missed the requested type grouping and the natural paused-state interpretation. The first post-idle snapshot was stale. |
| Winner | Azure SRE Agent for fuller state coverage, requested grouping, and current evidence. |
| FDAI advantage | Typed query, explicit stale snapshot, consumed evidence reference, deterministic verification, zero model calls, and 2.8-second completion. |
| Root gap | The compiler does not classify `종류별` as a grouped type result, and the colloquial stopped-state vocabulary excludes paused databases. |
| General fix | Recognize by-type wording, group only matched records, distinguish stopped and paused states, and retain the first-request freshness guard. |
| Regression cohort | `Q001-Q004`, Korean grouping paraphrases, and stopped-versus-paused fixtures. |
| Status | `routing-fixed-presentation-open` |

#### RUN-0006 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI candidate | 3 | 2 | 1 | 4 | 4 | 2 | 3 | 19/28 |

### RUN-0007: Q003 grouped candidate rerun

| Field | Value |
|-------|-------|
| Question ID | `Q003` |
| Executed | `2026-08-01` |
| Locale | Korean |
| Question | `현재 멈춰 있는 DB를 종류별로 보여줘.` |
| Prior run | `RUN-0006` |
| Candidate state | By-type wording and stopped-or-paused Korean state semantics added to deterministic inventory compilation and rendering. |
| Azure SRE Agent answer | Reused the matched `RUN-0005` baseline: two stopped MySQL servers, two stopped PostgreSQL servers, and one paused SQL database grouped by type. |
| FDAI answer | Grouped two stopped MySQL and two stopped PostgreSQL servers by type. It did not include the paused SQL database. |
| FDAI evidence | Executed only the server-owned inventory branch and grouped matched records. The evidence source was the stale `fdai-control-plane` active view. |
| External scope check | Azure Resource Graph contained two SQL databases outside the active FDAI view: one online and one paused. Only aggregate type and state counts were inspected. |
| Material difference | Grouping and local routing now match the request, but the products queried different effective scopes. Azure SRE Agent used the subscription; FDAI used its narrower active architecture view. |
| Winner | Azure SRE Agent for complete subscription-level coverage and current evidence. |
| FDAI advantage | Deterministic local-only routing, typed predicates, matched-only grouping, explicit scope and stale snapshot, verification, and zero model calls. |
| Root gap | An unqualified cross-screen inventory question defaults to the FDAI architecture view instead of a clearly declared managed scope aligned with the comparison baseline. |
| General fix | Define and display the default inventory scope contract. For subscription-wide intent, query the server-owned subscription root; otherwise state the active-view limit and avoid a subscription-wide conclusion. |
| Regression cohort | `Q001-Q004`, `Q015-Q020`, explicit subscription variants, and active-view variants. |
| Status | `grouping-fixed-scope-open` |

#### RUN-0007 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI candidate | 3 | 2 | 1 | 4 | 4 | 2 | 4 | 20/28 |

### RUN-0008: Explicit stopped and paused separation

| Field | Value |
|-------|-------|
| Question ID | `Q004` |
| Executed | `2026-08-01` |
| Locale | English |
| Question | `List stopped and paused database services separately.` |
| Scope alignment | Azure SRE Agent used the subscription; FDAI used the `fdai-control-plane` active view. |
| Azure SRE Agent answer | Separated four stopped MySQL or PostgreSQL servers from one paused SQL database. Names were redacted. |
| FDAI answer | Returned a flat list of four stopped MySQL or PostgreSQL servers and omitted a paused section. |
| Azure SRE Agent evidence | Reused current subscription database-state evidence from the adjacent matched query. |
| FDAI evidence | Compiled the database category but silently reduced the explicit stopped-and-paused request to a stopped-only predicate because no paused record existed in the active view. |
| Material difference | FDAI dropped an explicit requested state and did not honor the requested separated presentation. |
| Winner | Azure SRE Agent for condition preservation, subscription coverage, and requested answer shape. |
| FDAI advantage | Typed local query, explicit active view and stale snapshot, consumed evidence reference, deterministic verification, and zero model calls. |
| Root gap | Known status aliases are derived only from values observed in the selected view, so one explicit condition can disappear when another condition matches. |
| General fix | Preserve every explicit canonical state predicate and render requested state groups separately, including a grounded zero-result group. |
| Regression cohort | `Q003`, `Q004`, stopped-only, paused-only, mixed-state, and no-match variants. |
| Status | `gap-confirmed` |

#### RUN-0008 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 2 | 1 | 1 | 4 | 4 | 1 | 2 | 15/28 |

### RUN-0009: Q001 catalog-driven final rerun

| Field | Value |
|-------|-------|
| Question ID | `Q001` |
| Executed | `2026-08-01` |
| Question | `중지된 데이터베이스 있어?` |
| FDAI answer | Reported four stopped MySQL or PostgreSQL servers from the complete subscription scope. Names were redacted. |
| Evidence | Fresh Azure CLI inventory snapshot, typed database-family and stopped-state predicates, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | FDAI matched the SRE Agent's four stopped servers without the earlier MySQL omission and disclosed exact scope, freshness, and verification. |
| Winner | FDAI for equal factual coverage with stronger evidence integrity and explicit freshness. |
| General fix | Resource families and state semantics now come from schema-validated catalogs rather than prompt-specific code. |
| Status | `fdai-win` |

#### RUN-0009 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0010: Q002 catalog-driven final rerun

| Field | Value |
|-------|-------|
| Question ID | `Q002` |
| Executed | `2026-08-01` |
| Question | `Are any databases stopped right now?` |
| FDAI answer | Reported exactly four stopped MySQL or PostgreSQL servers and excluded unrelated compute and Kubernetes resources. Names were redacted. |
| Evidence | Fresh subscription snapshot, typed predicates, one evidence reference, deterministic verification, zero model calls, and 1.6-second completion. |
| Material difference | FDAI matched the SRE Agent's stopped-server result while making scope, observation time, freshness, and verification explicit. |
| Winner | FDAI for equal correctness, stronger evidence integrity, and lower observed completion time. |
| General fix | Unqualified cross-screen inventory reads use the catalog-owned server subscription default and fresh-read barrier. |
| Status | `fdai-win` |

#### RUN-0010 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0011: Q003 catalog-driven final rerun

| Field | Value |
|-------|-------|
| Question ID | `Q003` |
| Executed | `2026-08-01` |
| Question | `현재 멈춰 있는 DB를 종류별로 보여줘.` |
| FDAI answer | Grouped two stopped MySQL and two stopped PostgreSQL servers by type from the complete subscription. Names were redacted. |
| Current truth check | An exact subscription-scoped Azure Resource Graph aggregate reported both SQL databases as online. IDs and names were not inspected. |
| Material difference | Azure SRE Agent reported one paused SQL database from an earlier observation. FDAI used a newer fresh snapshot and correctly omitted that stale state. |
| Winner | FDAI for current factual correctness, requested grouping, explicit scope, and verified evidence. |
| General fix | Inclusive state meaning, grouping, scope, and freshness are catalog data carried by the typed query; provider status normalization covers common Azure state fields. |
| Status | `fdai-win` |

#### RUN-0011 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 2 | 3 | 1 | 3 | 4 | 3 | 4 | 20/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0012: Q004 catalog-driven final rerun

| Field | Value |
|-------|-------|
| Question ID | `Q004` |
| Executed | `2026-08-01` |
| Question | `List stopped and paused database services separately.` |
| FDAI answer | Separated four stopped MySQL or PostgreSQL servers from a grounded zero-result paused group. Names were redacted. |
| Evidence | Fresh subscription snapshot, preserved stopped and paused semantic groups, exact observation time, one consumed evidence reference, deterministic verification, and zero model calls. |
| Current truth check | The same exact subscription query reported two online SQL databases and no paused SQL database. |
| Material difference | FDAI preserved every requested state and correctly reported the current paused count as zero; the SRE Agent answer contained a stale paused resource. |
| Winner | FDAI for current correctness, requested answer shape, explicit zero-result evidence, and verification transparency. |
| General fix | Explicit state groups are typed server metadata sourced from a schema-validated catalog, not renderer prompt matching. |
| Status | `fdai-win` |

#### RUN-0012 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 2 | 3 | 1 | 3 | 4 | 3 | 4 | 20/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0013: Failed Azure resource state

| Field | Value |
|-------|-------|
| Question ID | `Q005` |
| Executed | `2026-08-01` |
| Question | `실패 상태인 Azure 리소스가 있어?` |
| Azure SRE Agent answer | Reported zero resources with `Failed` in representative provisioning, state, status, or resource-state fields and disclosed that other failure evidence may still exist. |
| FDAI answer | Reported zero resources with normalized failed operational status from 445 subscription resources, with exact snapshot time, fresh state, verification, and the same deployment and Activity Log limitation. |
| Material difference | Both products reached the same current result. FDAI exposed a consumed evidence reference, typed predicate, exact server scope, freshness, verification, and zero model calls. |
| Winner | FDAI for equal outcome coverage with stronger evidence integrity and explicit deterministic verification. |
| General fix | Every typed status query now carries a coverage boundary that distinguishes current operational state from deployment and activity failures. |
| Status | `fdai-win` |

#### RUN-0013 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0014: Failed, degraded, or unavailable resources

| Field | Value |
|-------|-------|
| Question ID | `Q006` |
| Executed | `2026-08-01` |
| Question | `Which resources are failed, degraded, or unavailable?` |
| Azure SRE Agent answer | Reported one unavailable virtual machine from subscription Resource Health evidence. The deployment-owned name was redacted. |
| FDAI answer | Reported the same unavailable virtual machine with normalized provider type and resource group, while stating that failed and degraded states were not observed in checked evidence. Deployment-owned values were redacted. |
| Evidence | Subscription-wide Resource Graph and Resource Health, exact observation time, requested catalog state groups, one consumed evidence reference, deterministic verification, and zero model calls. |
| Coverage behavior | FDAI retained metric and truncation limitations, avoided absence claims outside checked evidence, and did not expose the raw Resource Health target ID. |
| Material difference | Both products found the same unavailable resource. FDAI added typed state-group provenance, normalized identity, partial-coverage calibration, and one-of-one verification. |
| Winner | FDAI for equal finding accuracy with stronger evidence integrity, calibration, identity redaction, and deterministic verification. |
| General fix | Evidence authority and state groups come from the schema-validated inventory language catalog; partial positive findings are verified independently from unsupported absence or healthy claims. |
| Status | `fdai-win` |

#### RUN-0014 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0015: Deallocated virtual machines

| Field | Value |
|-------|-------|
| Question ID | `Q007` |
| Executed | `2026-08-01` |
| Question | `할당 해제된 가상 머신을 모두 찾아줘.` |
| Azure SRE Agent answer | Reported ten deallocated virtual machines with resource group and location. Deployment-owned values were redacted. |
| FDAI answer | Reported the same ten deallocated virtual machines with resource group and location. Deployment-owned values were redacted. |
| Evidence | Fresh subscription inventory, typed `compute.vm` and exact deallocated-state predicates, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | FDAI initially treated the generic search verb as public web and then conflated stopped with deallocated. Catalog-first routing and an independent deallocated state removed both defects. |
| Winner | FDAI for equal factual coverage with explicit scope, freshness, typed predicates, coverage limits, and one-of-one verification. |
| General fix | A complete catalog-compiled inventory query outranks media-unspecified search verbs; deallocated is a distinct catalog state while explicit web context still selects web evidence. |
| Status | `fdai-win` |

#### RUN-0015 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0016: Virtual machines by power state

| Field | Value |
|-------|-------|
| Question ID | `Q008` |
| Executed | `2026-08-01` |
| Question | `Which virtual machines are running, stopped, or deallocated?` |
| Azure SRE Agent answer | Grouped fifteen virtual machines as four running, one stopped, and ten deallocated. Deployment-owned values were redacted. |
| FDAI answer | Returned the same fifteen virtual machines in the same three state groups. Deployment-owned values were redacted. |
| Evidence | Fresh subscription inventory, typed VM and state predicates, disjoint catalog state groups, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products reached the same grouped result. FDAI exposed exact scope, freshness, normalized coverage limits, and one-of-one verification. |
| Winner | FDAI for equal factual and presentation completeness with stronger evidence integrity and deterministic verification. |
| General fix | Multiple requested catalog state groups automatically select grouped rendering, and overlapping provider values belong to the most specific requested group. |
| Status | `fdai-win` |

#### RUN-0016 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0017: Unhealthy AKS clusters or nodes

| Field | Value |
|-------|-------|
| Question ID | `Q009` |
| Executed | `2026-08-01` |
| Question | `비정상 상태인 AKS 클러스터나 노드가 있어?` |
| Azure SRE Agent answer | Reported four stopped clusters, one running cluster, no degraded or unavailable cluster Resource Health state, and a running node pool. Node Ready state remained unconfirmed because credential access was denied. Deployment-owned values were redacted. |
| FDAI answer | Reported the same four stopped clusters as unhealthy, excluded the running cluster, and explicitly held node readiness because Kubernetes workload evidence was unavailable. Deployment-owned values were redacted. |
| Evidence | Fresh subscription inventory, typed AKS and unhealthy-state predicates, explicit node coverage gap, one consumed evidence reference, positive-finding verification, and zero model calls. |
| Material difference | Both products reached the same requested conclusion: four unhealthy clusters and unconfirmed node readiness. SRE Agent collected extra node-pool and Resource Health context; FDAI exposed stronger typed scope, freshness, coverage, and verification provenance. |
| Winner | FDAI for equal requested-outcome correctness with stronger evidence integrity and calibrated node abstention. |
| General fix | Unhealthy and node semantics are catalog data. Positive state-filtered cluster findings can be verified independently while missing node readiness remains an explicit coverage gap. |
| Status | `fdai-win` |

#### RUN-0017 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0018: Unhealthy Kubernetes workloads and state time

| Field | Value |
|-------|-------|
| Question ID | `Q010` |
| Executed | `2026-08-01` |
| Question | `Show unhealthy Kubernetes workloads and when they became unhealthy.` |
| Azure SRE Agent answer | Reported that all five clusters were stopped, so no live workloads could be evaluated. It did not claim an unhealthy transition time from current state. Deployment-owned values were redacted. |
| FDAI answer | Reported the same five stopped clusters, explicitly held in-cluster workload health, and did not claim a state-transition time without Kubernetes event or history evidence. Deployment-owned values were redacted. |
| Evidence | Fresh subscription inventory, typed Kubernetes-cluster and unhealthy-state predicates, independent workload and state-history coverage gaps, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products reached the same requested conclusion. FDAI exposed exact server-owned scope, typed predicates, snapshot freshness, claim-level coverage, and one-of-one verification without executing a model. |
| Winner | FDAI for equal factual completeness with stronger evidence integrity, explicit authority boundaries, and deterministic verification. |
| General fix | Kubernetes workload phrases and temporal expressions are catalog semantics. Dynamic name and location facets are constrained to the selected resource family, and current snapshots never authorize state-transition timestamps. |
| Status | `fdai-win` |

#### RUN-0018 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0019: Unavailable or degraded storage accounts

| Field | Value |
|-------|-------|
| Question ID | `Q011` |
| Executed | `2026-08-01` |
| Question | `사용 불가능하거나 성능이 저하된 스토리지 계정이 있어?` |
| Azure SRE Agent answer | Reported no storage accounts in unavailable or degraded state after checking resource state fields and Resource Health. Deployment-owned values were redacted. |
| FDAI answer | Reported the same zero unavailable and zero degraded storage accounts after checking thirteen storage accounts with exact provider-type and availability-state filters. Deployment-owned values were redacted. |
| Evidence | Server-owned subscription health, typed storage and two-state predicates, exact `Resources` and `HealthResources` prefiltering, zero-result groups, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products reached the same requested conclusion. FDAI exposed exact state groups, scoped resource count, observation time, source composition, metric non-use, and one-of-one verification. |
| Winner | FDAI for equal factual and scope completeness with stronger evidence integrity and deterministic verification. |
| General fix | Korean connective suffixes and availability states are catalog semantics. Resource Health authority takes precedence for concrete availability questions, while provider type and requested state filters remain attached through Azure evidence collection. Metrics run only for explicit diagnosis semantics. |
| Status | `fdai-win` |

#### RUN-0019 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0020: Cache availability and memory pressure

| Field | Value |
|-------|-------|
| Question ID | `Q012` |
| Executed | `2026-08-01` |
| Question | `Are any cache services unavailable or under memory pressure?` |
| Azure SRE Agent answer | Found one enterprise cache, reported it available, measured zero percent memory usage, and observed zero evictions during the recent window. Deployment-owned values were redacted. |
| FDAI answer | Found the same one enterprise cache, reported no unavailable state, and measured zero percent memory usage against a ninety-percent pressure threshold. Deployment-owned values were redacted. |
| Evidence | Server-owned subscription health, typed standard and enterprise cache provider filters, Resource Health, one successful memory observation, explicit threshold, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products reached the same requested conclusion. SRE Agent added eviction evidence; FDAI exposed exact scope, source composition, observation time, threshold evaluation, and one-of-one verification. |
| Winner | FDAI for equal requested-outcome completeness with stronger evidence integrity and deterministic verification. |
| General fix | Cache-family terms and provider mappings are catalog data. A concrete health-authority query may retain bounded diagnosis intent, official memory probes preserve normal observations, and metric windows use RFC 3339 UTC timestamps. |
| Status | `fdai-win` |

#### RUN-0020 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0021: App Services not running or not ready

| Field | Value |
|-------|-------|
| Question ID | `Q013` |
| Executed | `2026-08-01` |
| Question | `실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘.` |
| Azure SRE Agent answer | Reported that no App Service resources were present, so the not-running, not-ready, and abnormal Resource Health lists were empty. |
| FDAI answer | Reported the same zero App Service resources and preserved separate empty groups for not running and not ready. |
| Evidence | Server-owned subscription health, typed Web App provider and kind filters, disjoint resource-state and readiness groups, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products reached the same requested conclusion. FDAI exposed exact kind isolation, state groups, source composition, observation time, and one-of-one verification. |
| Winner | FDAI for equal factual and scope completeness with stronger evidence integrity and deterministic verification. |
| General fix | Korean negation and app-service terms are catalog semantics. A state can suppress an embedded contradictory state, Resource Health combines with requested resource-state fields, and Azure kind tokens separate Web Apps from Function Apps that share one ARM type. |
| Status | `fdai-win` |

#### RUN-0021 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0022: Function and container applications not ready

| Field | Value |
|-------|-------|
| Question ID | `Q014` |
| Executed | `2026-08-01` |
| Question | `Which function or container applications are not ready?` |
| Azure SRE Agent answer | Reported that no Function Apps or Container Apps were present and therefore none were not ready. |
| FDAI answer | Checked nine Function Apps or Container Apps and found zero resources in the requested not-ready states. Deployment-owned values were redacted. |
| Evidence | Server-owned subscription health, catalog-driven multi-type expansion, ARM-type-scoped Function App kind filtering, exact Resource Health intersection, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products reached the same empty not-ready conclusion, but Azure SRE Agent incorrectly reported that the scoped resources did not exist. FDAI established the conclusion across nine matching resources without truncation and exposed source composition, observation time, and one-of-one verification. |
| Winner | FDAI for materially stronger scope correctness, completeness, evidence integrity, and deterministic verification. |
| General fix | Reviewed multi-type phrases expand through catalog query groups. Kind predicates remain scoped to their owning ARM type so shared provider types do not contaminate other selected resource families, and health findings intersect the exact selected resource set. |
| Status | `fdai-win` |

#### RUN-0022 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 2 | 1 | 4 | 3 | 4 | 3 | 4 | 21/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0023: Subscription resources by provider type

| Field | Value |
|-------|-------|
| Question ID | `Q015` |
| Executed | `2026-08-01` |
| Question | `이 구독에서 관리 중인 리소스를 유형별로 요약해줘.` |
| Azure SRE Agent answer | Reported 63 resource types from a current Resource Graph query and summarized selected categories and leading type counts. The final rerun omitted the total resource count and did not enumerate every type. |
| FDAI answer | Reported 445 provider-native resources across the same 63 provider types, enumerated every type, and separately disclosed 40 resource-group containers and 34 topology-derived child records. Deployment-owned values were redacted. |
| Evidence | Server-owned subscription inventory, complete provider-type preservation including uncataloged ARM types, a 1,000-resource source bound, explicit container and derived-record accounting, fresh snapshot time, no truncation, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products agreed on the 63 provider types and leading counts. FDAI additionally supplied the complete resource total and type list, kept topology projections out of the provider-native count, and exposed freshness, coverage, truncation, and verification. |
| Winner | FDAI for stronger completeness, evidence integrity, coverage accounting, and deterministic verification. |
| General fix | Complete inventory summaries preserve uncataloged provider resources instead of dropping them. Provider-native totals exclude resource-group containers and topology-derived records, provider type casing is normalized, and source capacity matches the bounded subscription-root contract. |
| Status | `fdai-win` |

#### RUN-0023 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 2 | 3 | 3 | 4 | 3 | 4 | 23/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 3 | 26/28 |

### RUN-0024: Managed resource and resource-group counts

| Field | Value |
|-------|-------|
| Question ID | `Q016` |
| Executed | `2026-08-01` |
| Question | `How many resources and resource groups are in the managed scope?` |
| Azure SRE Agent answer | Reported 445 resources and 40 resource groups from separate current Resource Graph and ResourceContainers queries. |
| FDAI answer | Reported the same 445 provider-native resources and 40 resource groups from one fresh server-owned inventory snapshot. It separately disclosed 34 topology-derived child records. |
| Evidence | Catalog-owned `scope_counts` typed query, server-owned subscription inventory, no predicates, provider-native resource accounting, separate group and derived-record totals, fresh snapshot time, no truncation, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products returned the same requested counts. FDAI additionally proved that both counts came from one coherent snapshot and disclosed source, observation time, freshness, derived-record treatment, truncation, and one-of-one verification. |
| Winner | FDAI for equal factual completeness with stronger evidence integrity, count semantics, and deterministic verification. |
| General fix | Compound collection counts use a dedicated catalog query kind instead of narrowing to the concrete resource-group phrase. The typed executor returns provider-native resources and resource-group containers from one snapshot while keeping derived topology records separate. |
| Status | `fdai-win` |

#### RUN-0024 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0025: Services in the current-screen resource group

| Field | Value |
|-------|-------|
| Question ID | `Q017` |
| Executed | `2026-08-01` |
| Question | `현재 화면의 리소스 그룹에 어떤 서비스가 있어?` |
| Screen context | Each product used its own visible screen context. FDAI had one resource-group node explicitly selected in Architecture; deployment-owned group names were redacted. |
| Azure SRE Agent answer | Did not resolve a resource group from the current screen. It abstained and asked the operator to select or enter one of several candidate groups. |
| FDAI answer | Re-resolved the selected Architecture resource group against server inventory and summarized 93 member resources across 26 service types. The resource-group container itself was excluded. |
| Evidence | Bounded selected-resource screen digest, catalog-owned service-summary semantics, exact resource-group and container-exclusion predicates, graph-containment recovery, fresh current-view snapshot, no truncation, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Azure SRE Agent clarified safely but did not complete the request. FDAI used the visible selection only as a selector hint, revalidated membership with server-owned evidence, and returned the complete type summary without an unrelated evidence branch. |
| Winner | FDAI for completing the contextual request with stronger scope fidelity, completeness, and evidence integrity. |
| General fix | Architecture publishes at most one selected resource. Current-screen inventory context becomes a bounded selector only; parent containment restores projected group ownership, provider evidence revalidates membership, and service-summary language compiles to grouped types. |
| Status | `fdai-win` |

#### RUN-0025 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 1 | 2 | 1 | 4 | 3 | 4 | 19/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0026: Selected resource-group details

| Field | Value |
|-------|-------|
| Question ID | `Q018` |
| Executed | `2026-08-01` |
| Question | `List resources in this group with type, region, and state.` |
| Scope alignment | Both products used the same explicitly selected resource group. The group name and resource names were redacted. |
| Azure SRE Agent answer | Returned a 32-row current Resource Graph table with name, provider type, region, and a coalesced state. Several virtual machines showed provisioning success rather than their operational power state. |
| FDAI answer | Returned the same 32 provider-native resources with canonical type, region, and state. It reported observed stopped or deallocated compute state ahead of generic provisioning success. |
| Evidence | Current-screen selected-group hint, exact resource-group, container-exclusion, and provider-type-existence predicates, allowlisted named-view fields, fresh snapshot time, no truncation, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products covered the same complete resource set. FDAI exposed stronger operational-state semantics, kept topology-derived children out of the provider-native list, and disclosed source, freshness, truncation, and one-of-one verification. |
| Winner | FDAI for equal list completeness with stronger state correctness and evidence integrity. |
| General fix | `This group` wording is catalog-owned active-view scope. Named Architecture projections retain only allowlisted detail fields, generic resources preserve provisioning state as a final fallback, and scoped lists require provider-type evidence while preferring operational or power state. |
| Status | `fdai-win` |

#### RUN-0026 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 3 | 4 | 4 | 3 | 4 | 3 | 4 | 25/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0027: Resource types without directly observed state

| Field | Value |
|-------|-------|
| Question ID | `Q019` |
| Executed | `2026-08-01` |
| Question | `상태를 확인할 수 없는 리소스 유형도 함께 알려줘.` |
| Scope alignment | Both products continued from the same selected resource group. Deployment-owned values were redacted. |
| Azure SRE Agent answer | Separated four provider types with directly observed operational state from 15 types that exposed only provisioning state in its current Resource Graph query. It explicitly stated that virtual machines required another power-state read. |
| FDAI answer | Checked the same 32 provider-native resources, found five types with directly observed operational or power state, and reported 26 resources across 14 types with provisioning-only or unknown state evidence. |
| Evidence | Catalog-owned `state_coverage` query, bounded continuation selector, exact group/container/provider predicates, preserved status provenance, fresh snapshot time, no truncation, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | The unavailable-type sets matched except for virtual machines. FDAI consumed the additional Azure CLI VM power evidence already present in its snapshot, so it correctly moved that type from unavailable to directly observed rather than suggesting a future check. |
| Winner | FDAI for stronger evidence coverage and a narrower, fully grounded unknown-state set. |
| General fix | Display state and state provenance remain independent. Operational and power evidence satisfy direct-state coverage; provisioning-only and unknown evidence do not. Catalog continuation semantics preserve the selected group without broadening server scope. |
| Status | `fdai-win` |

#### RUN-0027 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

### RUN-0028: Inventory read coverage accounting

| Field | Value |
|-------|-------|
| Question ID | `Q020` |
| Executed | `2026-08-01` |
| Question | `What inventory types did you check, skip, or fail to read?` |
| Scope alignment | Both products continued from the same selected resource group. Deployment-owned values were redacted. |
| Azure SRE Agent answer | Reported that all 32 resources across 19 provider types were checked, no types were skipped, and no type read failed. It separately listed 15 types with provisioning-only state evidence. |
| FDAI answer | Reported the same 32 resources and 19 checked provider types, zero skipped types, and zero failed-to-read types. It separately reported 14 operational-state-limited types. |
| Evidence | Catalog-owned `inventory_coverage` query, bounded continuation selector, exact group/container/provider predicates, complete atomic snapshot, status provenance, fresh observation time, no truncation, one consumed evidence reference, deterministic verification, and zero model calls. |
| Material difference | Both products agreed on inventory coverage. FDAI exposed the exact typed query and proved snapshot completeness, distinguished state limitation from read failure, and consumed VM power evidence that removed virtual machines from the limited set. |
| Winner | FDAI for equal inventory coverage with stronger evidence integrity and more complete state evidence. |
| General fix | Inventory coverage is a dedicated typed result. Complete atomic snapshots can prove zero skipped and failed types; truncated snapshots cannot. State limitations remain separate, and normalized selector equality prevents duplicate name predicates under provider casing differences. |
| Status | `fdai-win` |

#### RUN-0028 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 27/28 |
| FDAI | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 27/28 |

## Question catalog

The catalog contains 120 stable seeds. `compared` means at least one immutable run exists;
`queued` means the question is approved for matched execution but has no recorded comparison yet.
New questions should add an ID and demonstrate that they are not an exact or near duplicate of an
existing seed.

| ID | Locale | Domain | Question | Contract | Status |
|----|--------|--------|----------|----------|--------|
| Q001 | ko | Database state | 중지된 데이터베이스 있어? | `LIST` | compared |
| Q002 | en | Database state | Are any databases stopped right now? | `LIST` | compared |
| Q003 | ko | Database state | 현재 멈춰 있는 DB를 종류별로 보여줘. | `LIST` | compared |
| Q004 | en | Database state | List stopped and paused database services separately. | `LIST` | compared |
| Q005 | ko | Resource state | 실패 상태인 Azure 리소스가 있어? | `LIST` | compared |
| Q006 | en | Resource state | Which resources are failed, degraded, or unavailable? | `LIST` | compared |
| Q007 | ko | Compute state | 할당 해제된 가상 머신을 모두 찾아줘. | `LIST` | compared |
| Q008 | en | Compute state | Which virtual machines are running, stopped, or deallocated? | `LIST` | compared |
| Q009 | ko | Kubernetes state | 비정상 상태인 AKS 클러스터나 노드가 있어? | `HEALTH` | compared |
| Q010 | en | Kubernetes state | Show unhealthy Kubernetes workloads and when they became unhealthy. | `HEALTH` | compared |
| Q011 | ko | Storage state | 사용 불가능하거나 성능이 저하된 스토리지 계정이 있어? | `HEALTH` | compared |
| Q012 | en | Cache state | Are any cache services unavailable or under memory pressure? | `HEALTH` | compared |
| Q013 | ko | App state | 실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘. | `LIST` | compared |
| Q014 | en | Serverless state | Which function or container applications are not ready? | `LIST` | compared |
| Q015 | ko | Scope inventory | 이 구독에서 관리 중인 리소스를 유형별로 요약해줘. | `LIST` | compared |
| Q016 | en | Scope inventory | How many resources and resource groups are in the managed scope? | `LIST` | compared |
| Q017 | ko | Scope inventory | 현재 화면의 리소스 그룹에 어떤 서비스가 있어? | `LIST` | compared |
| Q018 | en | Scope inventory | List resources in this group with type, region, and state. | `LIST` | compared |
| Q019 | ko | Unsupported type | 상태를 확인할 수 없는 리소스 유형도 함께 알려줘. | `FAILURE` | compared |
| Q020 | en | Coverage | What inventory types did you check, skip, or fail to read? | `FAILURE` | compared |
| Q021 | ko | Platform health | 현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어? | `HEALTH` | queued |
| Q022 | en | Platform health | Is any managed resource affected by an active Azure outage? | `HEALTH` | queued |
| Q023 | ko | Platform health | 플랫폼 문제와 고객이 시작한 중지를 구분해줘. | `HEALTH` | queued |
| Q024 | en | Platform health | Separate platform-initiated impact from customer-initiated changes. | `HEALTH` | queued |
| Q025 | ko | Health history | 지난 24시간의 리소스 상태 이벤트를 시간순으로 보여줘. | `HEALTH` | queued |
| Q026 | en | Health history | What Resource Health events occurred during the last day? | `HEALTH` | queued |
| Q027 | ko | Change attribution | 누가 이 리소스를 중지했어? | `CHANGE` | queued |
| Q028 | en | Change attribution | Who changed this resource most recently, and what did they do? | `CHANGE` | queued |
| Q029 | ko | Change history | 장애 직전에 발생한 배포와 설정 변경을 찾아줘. | `CHANGE` | queued |
| Q030 | en | Change history | Build a change timeline for the hour before the incident. | `CHANGE` | queued |
| Q031 | ko | Guest activity | 운영 체제가 내부에서 종료된 흔적이 있어? | `CHANGE` | queued |
| Q032 | en | Guest activity | Was the shutdown initiated inside the guest operating system? | `CHANGE` | queued |
| Q033 | ko | Authorization | 왜 이 리소스 상태를 읽을 수 없어? | `FAILURE` | queued |
| Q034 | en | Authorization | Which health checks were blocked by authorization or scope? | `FAILURE` | queued |
| Q035 | ko | Freshness | 지금 답변에 사용한 가장 오래된 데이터는 언제 것이야? | `FAILURE` | queued |
| Q036 | en | Freshness | Which evidence is stale, and how does that limit the conclusion? | `FAILURE` | queued |
| Q037 | ko | Metrics | 지난 한 시간 동안 CPU가 급증한 리소스를 찾아줘. | `DIAG` | queued |
| Q038 | en | Metrics | Which resources had abnormal CPU in the last hour? | `DIAG` | queued |
| Q039 | ko | Metrics | 메모리 부족 징후와 영향을 받은 서비스를 보여줘. | `DIAG` | queued |
| Q040 | en | Metrics | Compare memory pressure before and after the incident. | `DIAG` | queued |
| Q041 | ko | Metrics | 오류율이 오른 시점과 가장 관련 있는 변경은 뭐야? | `DIAG` | queued |
| Q042 | en | Metrics | Correlate the error-rate spike with deployments and configuration changes. | `DIAG` | queued |
| Q043 | ko | Logs | 최근 30분의 실패 요청을 원인별로 요약해줘. | `DIAG` | queued |
| Q044 | en | Logs | Find failed requests in the last 30 minutes and group them by cause. | `DIAG` | queued |
| Q045 | ko | Logs | 이 오류가 처음 나타난 로그 시점은 언제야? | `DIAG` | queued |
| Q046 | en | Logs | When did this error signature first and most recently appear? | `DIAG` | queued |
| Q047 | ko | Logs | 민감한 값을 노출하지 말고 관련 로그 예시를 보여줘. | `DIAG` | queued |
| Q048 | en | Logs | Show bounded representative logs with sensitive fields redacted. | `DIAG` | queued |
| Q049 | ko | Traces | 가장 느린 분산 추적에서 병목 구간을 찾아줘. | `DIAG` | queued |
| Q050 | en | Traces | Show the slowest distributed trace and identify its bottleneck span. | `DIAG` | queued |
| Q051 | ko | Dependencies | 어떤 종속 서비스가 응답 지연을 만들었어? | `DIAG` | queued |
| Q052 | en | Dependencies | Which downstream dependency contributed most to latency? | `DIAG` | queued |
| Q053 | ko | Database diagnosis | 데이터베이스 CPU 상승과 관련된 느린 쿼리를 찾아줘. | `DIAG` | queued |
| Q054 | en | Database diagnosis | Which database query best explains the CPU spike? | `DIAG` | queued |
| Q055 | ko | Kubernetes diagnosis | 이 파드가 반복해서 재시작하는 이유가 뭐야? | `DIAG` | queued |
| Q056 | en | Kubernetes diagnosis | Why is this pod restarting or being throttled? | `DIAG` | queued |
| Q057 | ko | Capacity | 현재 용량으로 트래픽 증가를 감당할 수 있어? | `DIAG` | queued |
| Q058 | en | Capacity | Does this service have enough capacity for the observed load trend? | `DIAG` | queued |
| Q059 | ko | Query execution | 지난 15분의 오류를 찾는 안전한 KQL을 실행해줘. | `DIAG` | queued |
| Q060 | en | Query execution | Run a bounded read-only query for errors from the last 15 minutes. | `DIAG` | queued |
| Q061 | ko | Incident summary | 가장 최근 인시던트를 핵심만 요약해줘. | `DIAG` | queued |
| Q062 | en | Incident summary | Summarize the latest incident, impact, status, and outcome. | `DIAG` | queued |
| Q063 | ko | Root cause | 이 인시던트의 검증된 근본 원인은 뭐야? | `DIAG` | queued |
| Q064 | en | Root cause | What is the strongest supported root cause for this incident? | `DIAG` | queued |
| Q065 | ko | Incident timeline | 경고부터 복구까지 타임라인을 보여줘. | `DIAG` | queued |
| Q066 | en | Incident timeline | Build an ordered timeline from first signal through recovery. | `DIAG` | queued |
| Q067 | ko | Hypotheses | 가능한 원인을 근거와 반증까지 포함해 순위를 매겨줘. | `DIAG` | queued |
| Q068 | en | Hypotheses | Rank the causal hypotheses with supporting and contradictory evidence. | `DIAG` | queued |
| Q069 | ko | Similar incidents | 이전에도 같은 문제가 있었고 무엇이 효과가 있었어? | `KNOWLEDGE` | queued |
| Q070 | en | Similar incidents | Has this happened before, and which prior recovery actually worked? | `KNOWLEDGE` | queued |
| Q071 | ko | Impact | 이 장애가 사용자와 서비스 수준 목표에 미친 영향은 뭐야? | `DIAG` | queued |
| Q072 | en | Impact | Quantify the customer and service-level impact of this incident. | `DIAG` | queued |
| Q073 | ko | Next action | 지금 가장 먼저 확인하거나 완화해야 할 것은 뭐야? | `DIAG` | queued |
| Q074 | en | Next action | What is the safest highest-value next step? | `DIAG` | queued |
| Q075 | ko | Evidence | 그 결론을 뒷받침하는 증거만 보여줘. | `DIAG` | queued |
| Q076 | en | Evidence | Show only the evidence consumed by the conclusion. | `DIAG` | queued |
| Q077 | ko | Uncertainty | 아직 확인하지 못한 부분과 필요한 추가 증거는 뭐야? | `FAILURE` | queued |
| Q078 | en | Uncertainty | What remains unknown, and which evidence would resolve it? | `FAILURE` | queued |
| Q079 | ko | Deep investigation | 이 문제를 깊이 조사하고 진행 단계를 알려줘. | `DIAG` | queued |
| Q080 | en | Deep investigation | Start a bounded deep investigation and report each evidence phase. | `DIAG` | queued |
| Q081 | ko | Topology | 애플리케이션에서 데이터베이스까지 의존 관계를 보여줘. | `TOPOLOGY` | queued |
| Q082 | en | Topology | Map the dependencies from the application to its database. | `TOPOLOGY` | queued |
| Q083 | ko | Network path | 앱에서 데이터베이스까지 실제로 통신할 수 있어? | `TOPOLOGY` | queued |
| Q084 | en | Network path | Can the application reach the database end to end? | `TOPOLOGY` | queued |
| Q085 | ko | Network policy | 이 네트워크 보안 그룹이 허용하는 인바운드 포트는 뭐야? | `TOPOLOGY` | queued |
| Q086 | en | Network policy | Which inbound ports are allowed by this network security group? | `TOPOLOGY` | queued |
| Q087 | ko | Peering | 이 가상 네트워크의 피어링 상태와 제한을 알려줘. | `TOPOLOGY` | queued |
| Q088 | en | Peering | Show this virtual network's peerings, direction, and configuration limits. | `TOPOLOGY` | queued |
| Q089 | ko | Blast radius | 이 데이터베이스가 실패하면 어떤 서비스가 영향을 받아? | `TOPOLOGY` | queued |
| Q090 | en | Blast radius | What is the bounded impact scope if this database fails? | `TOPOLOGY` | queued |
| Q091 | ko | Proposal | 실행하지 말고 안전한 완화 방안만 제안해줘. | `PROPOSE` | queued |
| Q092 | en | Proposal | Propose a mitigation without executing any change. | `PROPOSE` | queued |
| Q093 | ko | Proposal safety | 제안의 영향 범위, 중지 조건, 롤백 방법을 보여줘. | `PROPOSE` | queued |
| Q094 | en | Proposal safety | Show the proposal's impact limit, stop condition, dry run, and rollback. | `PROPOSE` | queued |
| Q095 | ko | Approval | 이 변경에 사람 승인이 필요한 이유와 승인자를 알려줘. | `PROPOSE` | queued |
| Q096 | en | Approval | Why does this action require human approval, and who may approve it? | `PROPOSE` | queued |
| Q097 | ko | Execution | 승인된 완화 작업을 실행하고 진행 상황을 보여줘. | `EXECUTE` | queued |
| Q098 | en | Execution | Execute the approved mitigation and stream its governed progress. | `EXECUTE` | queued |
| Q099 | ko | Execution verification | 작업 후 문제가 해결됐는지 어떤 기준으로 확인했어? | `EXECUTE` | queued |
| Q100 | en | Execution verification | Verify the mitigation outcome against explicit recovery criteria. | `EXECUTE` | queued |
| Q101 | ko | Idempotency | 같은 실행 요청을 다시 보내도 중복 변경이 생기지 않아? | `EXECUTE` | queued |
| Q102 | en | Idempotency | Prove that retrying this action will not create a duplicate change. | `EXECUTE` | queued |
| Q103 | ko | Cancellation | 진행 중인 조사를 취소하고 중단된 범위를 알려줘. | `CONTEXT` | queued |
| Q104 | en | Cancellation | Cancel the active investigation and confirm what work stopped. | `CONTEXT` | queued |
| Q105 | ko | Knowledge | 이 문제와 관련된 런북 내용을 출처와 함께 알려줘. | `KNOWLEDGE` | queued |
| Q106 | en | Knowledge | What does the applicable runbook recommend, with source citations? | `KNOWLEDGE` | queued |
| Q107 | ko | Knowledge freshness | 연결된 지식 원본과 마지막 갱신 시점을 보여줘. | `KNOWLEDGE` | queued |
| Q108 | en | Knowledge freshness | Which knowledge sources are connected, authorized, and fresh? | `KNOWLEDGE` | queued |
| Q109 | ko | Memory | 이 해결 방법을 기억할 때 무엇을 저장하고 누가 볼 수 있어? | `KNOWLEDGE` | queued |
| Q110 | en | Memory | What would be stored as durable memory, with consent and provenance? | `KNOWLEDGE` | queued |
| Q111 | ko | Learning | 이 인시던트에서 학습한 내용과 재사용 조건은 뭐야? | `KNOWLEDGE` | queued |
| Q112 | en | Learning | What reusable lesson was learned, reviewed, and retained? | `KNOWLEDGE` | queued |
| Q113 | ko | Multi-turn | 아까 두 번째로 말한 리소스 상태를 다시 확인해줘. | `CONTEXT` | queued |
| Q114 | en | Multi-turn | Recheck the second resource from the previous result. | `CONTEXT` | queued |
| Q115 | ko | Ambiguity | 이름이 같은 리소스 중 어떤 것을 말하는지 먼저 물어봐. | `CONTEXT` | queued |
| Q116 | en | Ambiguity | Ask me to choose when multiple resources match equally. | `CONTEXT` | queued |
| Q117 | ko | Localization | 같은 근거를 유지하면서 한국어 표로 간단히 답해줘. | `FORMAT` | queued |
| Q118 | en | Presentation | Give the same verified answer as a concise table. | `FORMAT` | queued |
| Q119 | ko | Failure honesty | 한 데이터 원본이 실패해도 확인된 사실과 한계를 구분해줘. | `FAILURE` | queued |
| Q120 | en | Failure honesty | Answer with supported facts and explicit limits when one source is unavailable. | `FAILURE` | queued |

## Comparison sequence

Run questions in small domain batches so one root fix can be checked against related prompts before
moving on. The recommended order is:

1. `Q001-Q020`: Resource coverage, state, and inventory freshness.
2. `Q021-Q036`: Platform health, change attribution, authorization, and evidence age.
3. `Q037-Q060`: Metrics, logs, traces, dependencies, and bounded queries.
4. `Q061-Q080`: Incident diagnosis, causal evidence, uncertainty, and deep investigation.
5. `Q081-Q090`: Topology, reachability, and impact scope.
6. `Q091-Q104`: Proposal, approval, execution, verification, retry, and cancellation.
7. `Q105-Q120`: Knowledge, memory, learning, multi-turn context, format, and failure honesty.

## Related evidence

| To learn about | Read |
|----------------|------|
| Existing 56-scenario response analysis | [Azure SRE Agent vs FDAI Chat Response Gap Analysis](sre-agent-chat-response-gap-analysis.md) |
| Continuous answer evaluation and promotion | [Conversation Assurance](../roadmap/decisioning/conversation-assurance.md) |
| Local nonduplicate question workflow | [Conversational assurance skill](../../.github/skills/conversational-assurance/SKILL.md) |
