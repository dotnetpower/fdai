# Operations Menu Deep Review

This engineering review records the July 2026 audit of the operator console's
Operations domain. It compares the registered menu, clean URL routes, read-only
page behavior, evidence contracts, localization, keyboard behavior, and tests
with the operator-console and app-shape designs.

> Scope: `Live`, `Incidents`, `Approvals`, `Provisioning`, `Onboarding`,
> `Processes`, and `Scheduler runs`. Dashboard and detection files changed by a
> concurrent session were treated as externally owned and were not overwritten.

## Design at a glance

The designed Operations domain now exposes seven first-class read-only views in
this order: Live, Incidents, Approvals, Provisioning, Onboarding, Processes, and
Scheduler runs. Scheduler runs uses `/scheduler-runs` as its canonical path;
the former `/processes/scheduler-runs` path remains a compatibility alias.

The audit accepted a finding only when source code, a design statement, or an
executable contract test could demonstrate it. Every finding below is marked
resolved and points to the implementation area that changed.

## Resolved detected issues

### Navigation and routing

| # | Critique | Resolution |
|---|----------|------------|
| 1 | Scheduler runs existed in source but was absent from the Operations submenu. | Registered `scheduler-runs` in `panels.tsx`. |
| 2 | Scheduler runs had no first-class clean URL. | Added canonical `/scheduler-runs`. |
| 3 | Existing nested Scheduler runs bookmarks had no explicit migration contract. | Added `/processes/scheduler-runs` as a canonicalizing alias. |
| 4 | The Processes shortcut still generated the old nested URL. | Switched it to `routeHref("scheduler-runs")`. |
| 5 | English navigation had no Scheduler runs label. | Added the English panel label. |
| 6 | Korean navigation had no Scheduler runs label. | Added the Korean panel label. |
| 7 | Scheduler runs had no submenu description in either locale. | Added paired English and Korean subtitles. |
| 8 | The Operations membership test locked only six pages. | Updated the exact-order test to cover all seven. |
| 9 | Route tests did not cover Scheduler runs. | Added canonical path and compatibility-alias cases. |
| 10 | Navigation-domain tests did not classify Scheduler runs. | Locked it to the Operations domain. |
| 11 | A fork panel added through `EXTRA_PANELS` silently navigated to Overview. | Registered panels now receive `/<panel-id>` when no explicit path exists. |
| 12 | Duplicate panel ids could make selection and active state ambiguous. | Added fail-fast registry validation. |
| 13 | Non-kebab-case panel ids could violate the clean URL contract. | Added lowercase kebab-case validation. |
| 14 | A blank extension-panel label could create an unnamed menu item. | Added non-empty label validation. |
| 15 | Runtime JavaScript could supply an unknown group despite TypeScript types. | Added runtime group validation. |
| 16 | Two panels could resolve to the same canonical path. | Added unique-path validation. |
| 17 | A malformed canonical path could bypass the lowercase path rule. | Added path-shape validation. |
| 18 | A dynamic panel path could collide with a legacy alias. | Added alias-collision validation. |
| 19 | Opening the navigation action menu left focus on the trigger. | Focus now moves to the first menu item. |
| 20 | Navigation menu items did not support ArrowUp or ArrowDown. | Added wrapping directional navigation. |
| 21 | Navigation menu items did not support Home or End. | Added first/last item navigation. |
| 22 | Escape closed the menu without restoring trigger focus. | Escape now restores focus to the action button. |
| 23 | The action trigger did not expose its popup type. | Added `aria-haspopup="menu"`. |
| 24 | Keyboard behavior had no focused regression test. | Added pure index-navigation tests. |

### Scheduler runs

| # | Critique | Resolution |
|---|----------|------------|
| 25 | Form submission navigated back to the old nested path. | Submission now replaces the canonical Scheduler runs URL. |
| 26 | Submission started a request and then remounted the route, causing duplicate work. | The canonical navigation owns the next load; the direct duplicate call was removed. |
| 27 | A response for a different task id was accepted as requested evidence. | Added requested-task identity validation. |
| 28 | Claimed time existed in the contract but was absent from the table. | Added a Claimed column. |
| 29 | Machine status values were shown as raw lowercase English. | Added localized status labels. |
| 30 | Korean status labels were missing. | Added claimed, published, failed, and lost translations. |
| 31 | Timestamps omitted an explicit timezone. | Routed all Scheduler timestamps through the shared formatter. |
| 32 | Invalid timestamps could be mistaken for missing values. | Invalid recorded evidence remains visible verbatim. |
| 33 | The screen did not publish narrator view context. | Added a self-describing Scheduler runs snapshot. |
| 34 | The screen had no glossary definition for a scheduler run. | Added a scoped glossary term. |
| 35 | Ledger source and durability were absent from conversational facts. | Published both provenance fields. |
| 36 | Pagination availability was absent from conversational facts. | Published `has_more`. |
| 37 | Loaded run rows were absent from conversational records. | Published bounded run records. |
| 38 | Response-task mismatch had no regression coverage. | Added positive and negative identity tests. |

### Live

| # | Critique | Resolution |
|---|----------|------------|
| 39 | Freezing the view discarded every incoming frame. | Pause now retains frames in a bounded backlog. |
| 40 | Resume could not catch up to events observed while frozen. | Resume drains the retained backlog in arrival order. |
| 41 | More than 200 frames in one flush interval silently lost older frames. | Draining now takes the oldest 200 and retains the remainder. |
| 42 | The pending queue had no memory bound after retaining paused frames. | Added a 1,000-frame cap. |
| 43 | Buffer overflow was invisible to the operator. | Added an explicit dropped-frame counter. |
| 44 | Overflow was absent from narrator context. | Published `stream.frames_dropped`. |
| 45 | The frozen label claimed observation but not queued replay. | Reworded it as queued frames in both locales. |
| 46 | Frame continuity had no health signal. | Added a continuity row with complete/overflow states. |
| 47 | Backlog drain ordering had no regression test. | Added ordered drain coverage. |
| 48 | Bounded overflow selection had no regression test. | Added newest-retention and drop-count coverage. |

### Incidents

| # | Critique | Resolution |
|---|----------|------------|
| 49 | Arbitrary `vertical` query values reached the API. | Added a four-value boundary parser. |
| 50 | Human-facing hyphenated vertical links did not normalize to machine values. | Normalized hyphens to underscores. |
| 51 | Selecting an incident reloaded the complete roster. | Split roster dependencies from selected-detail lookup. |
| 52 | Every deep link fetched both roster and exact incident before showing either. | Roster loads first; exact lookup runs only when needed. |
| 53 | Re-delivered pagination rows could duplicate incidents. | Merge now deduplicates by correlation id. |
| 54 | Exact deep-link prepending could duplicate a roster item. | The same merge helper handles exact results. |
| 55 | Roster timestamps were raw server strings. | Applied the shared timestamp formatter. |
| 56 | Incident opened and updated facts lacked timezone context. | Applied the shared formatter to detail facts. |
| 57 | Timeline timestamps lacked timezone context. | Applied the shared formatter to audit rows. |
| 58 | Filter normalization and rejection were untested. | Added valid, normalized, empty, and malicious cases. |
| 59 | Pagination deduplication was untested. | Added roster and exact-result merge cases. |

### Approvals

| # | Critique | Resolution |
|---|----------|------------|
| 60 | A page could claim fewer total approvals than returned items. | Decoder now rejects contradictory totals. |
| 61 | A count-only response could leak full item details. | Decoder now rejects details at `count_only`. |
| 62 | Duplicate idempotency keys could render one approval twice. | Decoder now requires unique keys. |
| 63 | Unknown approval modes were rendered as if authoritative. | Decoder now accepts only shadow, enforce, or omission. |
| 64 | Malformed requested timestamps were accepted. | Decoder now requires RFC 3339. |
| 65 | Malformed expiry timestamps were accepted. | Decoder now requires RFC 3339 or null. |
| 66 | Search case folding depended on the browser locale for machine ids. | Search now uses stable lowercase folding. |
| 67 | Repeated reasons could produce duplicate render keys. | Reasons are deduplicated and index-keyed. |
| 68 | Repeated rule ids could produce duplicate links and keys. | Rule links are deduplicated. |
| 69 | Requested time was shown as raw ISO text. | Applied the shared timestamp formatter. |
| 70 | Expiry time was shown as raw ISO text. | Applied the shared timestamp formatter. |
| 71 | Loaded expired items were mixed into the summary without disclosure. | Added an expired-details status count. |
| 72 | Search coverage omitted action, resource, event, correlation, reason, and rule composition. | Added a complete search-index test. |
| 73 | Malformed TTL timer behavior was untested. | Added an invalid-time no-schedule test. |

### Provisioning and onboarding

| # | Critique | Resolution |
|---|----------|------------|
| 74 | Provisioning used a one-off header instead of the shared page contract. | Replaced it with `PageHeader` and `StatusPill`. |
| 75 | Provisioning title and description were hardcoded English. | Added paired catalog strings. |
| 76 | Stream states were hardcoded English. | Localized all connection labels. |
| 77 | Provisioning did not publish screen context. | Added progress, terminal, and stream facts. |
| 78 | Provisioning had no contextual records. | Published bounded recent-resource records. |
| 79 | A returned console URL could embed credentials. | `safeHttpUrl` now rejects userinfo. |
| 80 | Progress accepted values above 100 percent. | Fraction input is clamped to 1. |
| 81 | Progress accepted negative values. | Fraction input is clamped to 0. |
| 82 | Progress accepted non-finite values. | Non-finite input preserves prior evidence. |
| 83 | A repeated done event could mutate terminal state. | Done is now fully terminal. |
| 84 | Stream errors were not announced as alerts. | Added `role="alert"`. |
| 85 | Onboarding allowed concurrent refresh clicks. | Added a refresh-in-flight state and disabled control. |
| 86 | Onboarding refresh and all body labels were hardcoded English. | Added paired English and Korean catalogs. |
| 87 | Last checked showed only local clock time without date or timezone. | Applied the shared timestamp formatter. |
| 88 | Role-gap tuples could omit principal, role, or target. | Decoder now requires exactly three fields. |
| 89 | Resource counts could be negative or fractional. | Decoder now requires non-negative integers. |
| 90 | Role counts could be negative or fractional. | Decoder now requires non-negative integers. |
| 91 | Readiness could be both ready and blocked. | Decoder now rejects contradictory states. |
| 92 | A configured successful probe could be neither ready nor blocked. | Decoder now requires one authoritative outcome. |

### Processes

| # | Critique | Resolution |
|---|----------|------------|
| 93 | Duplicate process ids could break active selection. | Decoder now requires unique process ids. |
| 94 | Duplicate event ids could break journal identity. | Decoder now requires unique event ids. |
| 95 | Journal count could disagree with returned events. | Decoder now requires an exact count. |
| 96 | Journal events could belong to another correlation. | Decoder now checks process correlation consistency. |
| 97 | Revision could be negative or fractional. | Decoder now requires a non-negative integer. |
| 98 | Attempt could be negative or fractional. | Decoder now requires a non-negative integer. |
| 99 | A journal for another process could render under the selected URL. | Added selected-process identity validation. |
| 100 | A ViewSpec for another process could render under the selected URL. | Added selected-view identity validation. |
| 101 | Duplicate region ids could destabilize layout keys. | Decoder now requires unique region ids. |
| 102 | Region spans outside the 12-column contract were accepted. | Decoder now enforces 1 through 12. |
| 103 | Duplicate widget ids could destabilize report keys. | Decoder now requires unique widget ids per report. |
| 104 | Process evidence timestamps used browser-default formatting without timezone. | Applied the shared timestamp formatter. |
| 105 | Console-owned Process labels and empty states were hardcoded English. | Added paired English and Korean catalogs. |
| 106 | Process provenance labels were not localized. | Localized source, evidence, and storage labels. |
| 107 | Journal metadata and details were not localized. | Localized timeline, identifiers, and attempt labels. |

## Verification

Focused Vitest runs covered panel registration, routing, navigation keyboard
behavior, Scheduler runs, Live buffering, Incidents, Approvals, Provisioning,
Onboarding, Processes, timestamp formatting, catalog usage, and the
self-describing view contract. Strict TypeScript type checking passed after
the owned changes.

Playwright verified all seven canonical routes at 1440 x 900 and 390 x 844.
Every route rendered its expected heading and active navigation item without an
alert or page-level horizontal overflow. The mobile explorer expanded from 1 px
to the remaining 338 px viewport width, and all seven links remained visible.
The action menu moved focus to its first item, ArrowDown selected the next item,
and Escape restored focus to the trigger. The legacy Scheduler runs URL kept its
query while canonicalizing, and the Korean render exposed all seven translated
menu labels and four translated statuses with `lang=ko`.

The browser verification used an isolated read-only dev API on port 8012 so it
did not change or terminate the concurrent API session on port 8010.

## Related docs

| To learn about | Read |
|----------------|------|
| Operator-console contracts | [Operator console](../docs/roadmap/interfaces/operator-console.md) |
| Read-only console boundaries | [App shape](../.github/instructions/app-shape.instructions.md) |
| Runtime process design | [Process automation](../docs/roadmap/decisioning/process-automation.md) |
