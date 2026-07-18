# Email Template Hardening Review

This review records the visual critique and ten-round hardening pass applied to the FDAI Calm Slate email templates. The goal is restrained elegance under real email constraints: evidence-first hierarchy, conservative HTML, clear trust boundaries, and graceful mobile behavior.

## Baseline Critique

The baseline was coherent and usable, but it still read as a polished mock rather than a finished notification system. The following 28 findings drove the hardening work.

| # | Finding | Why it reduced elegance | Resolution |
|---|---------|-------------------------|------------|
| 1 | The brand was a generic `F` square followed by a single FDAI label. | It looked like a component placeholder rather than a deliberate sender signature. | Added a two-line FDAI / Autonomous operations wordmark. |
| 2 | Messages had no hidden inbox preheader. | Inbox previews would repeat body text or expose layout noise. | Added a concise, scenario-specific preheader to every template. |
| 3 | Light color behavior was not declared. | Automatic dark-mode transformations could damage the muted palette. | Declared light `color-scheme` and `supported-color-schemes`. |
| 4 | Headline sizes varied between 31px, 32px, and 33px. | The six templates did not feel like one authored series. | Standardized desktop headlines at 30px. |
| 5 | Headline colors were inconsistent. | Some headlines lacked the calm slate editorial voice. | Standardized headlines on slate navy. |
| 6 | Headline line-height varied. | Vertical rhythm changed between message types without meaning. | Standardized to 1.22 desktop and 1.25 mobile. |
| 7 | Numeric columns used proportional figures. | Comparisons looked slightly unstable when values changed. | Enabled tabular numeric figures on the email body. |
| 8 | The 34px desktop gutter felt incidental. | It landed between compact operations UI and an editorial letter. | Raised the progressive desktop gutter to 40px. |
| 9 | The paper surface was visually flat. | The white message did not separate gently from the warm canvas. | Added a low-opacity, whole-surface shadow. |
| 10 | A2 alerts omitted detection time near the headline. | Urgency was asserted by color rather than grounded in chronology. | Added detected/window timestamps. |
| 11 | A2 alerts omitted signal provenance. | Operators could not scan which detector generated the alert. | Added probe or detector source. |
| 12 | A2 alerts omitted routing context. | T0 and retry information was buried or absent. | Added tier or retry facts beside provenance. |
| 13 | Critical metrics were merely adjacent. | The row lacked comparison rhythm. | Added desktop hairline metric dividers. |
| 14 | Cost observed and baseline values lacked a visual relationship. | They read as two unrelated numbers. | Added the same comparison divider rhythm. |
| 15 | Digest metric groups lacked internal cadence. | Centered numbers floated without a ledger structure. | Added progressive dividers with mobile reset. |
| 16 | Mobile metric dividers could become decorative rails. | Left borders on stacked blocks would violate the visual boundary and feel accidental. | Explicitly removed borders and inset on mobile. |
| 17 | The 94.5% shadow KPI was too celebratory. | It resembled marketing rather than governance evidence. | Reduced its scale and paired it with `121 of 128`. |
| 18 | Shadow accuracy did not name its evidence basis. | The percentage lacked measurement context. | Added frozen-scenario and operator-confirmed language. |
| 19 | Promotion copy said candidates deserved a "closer look." | The phrase did not state the threshold they cleared. | Changed it to evidence-floor language. |
| 20 | Promotion copy could imply that review already promoted an action. | Governance and execution boundaries were too implicit. | Stated that the digest neither promotes nor approves. |
| 21 | The monthly T2 segment hid its numeric value. | The smallest and most expensive tier was least inspectable. | Rendered `T2 7.5%` directly. |
| 22 | CTA buttons looked like generic commands. | Their read-only nature was not visible at the interaction point. | Added explicit read-only, authentication, and no-action text. |
| 23 | CTA links lacked descriptive accessibility labels. | Screen-reader context depended on surrounding prose. | Added scenario-specific `aria-label` values. |
| 24 | Mobile CTAs retained compact desktop width. | They felt visually timid and offered a smaller touch target. | Made CTAs full-width and centered on mobile. |
| 25 | Mobile titles could become visually top-heavy. | Editorial scale consumed too much of a narrow viewport. | Set a 27px mobile headline scale. |
| 26 | Outlook had no explicit table fallback. | CSS shadow, radius, and responsive behavior can be ignored by Outlook desktop. | Added MSO width, gutter, and collapse fallbacks. |
| 27 | Footers only said the data was synthetic. | They did not explain why the recipient received the message. | Added message-class-specific provenance. |
| 28 | The gallery did not expose its design process. | The result looked arbitrary rather than reviewed. | Added ten-round framing and linked this ledger. |

## Ten Hardening Rounds

| Round | Focus | Change | Focused check |
|-------|-------|--------|---------------|
| 1 | Brand signature | Added inbox preheaders, light color-scheme declarations, and a two-line sender mark. | Six preheaders, six signatures, six scheme declarations found. |
| 2 | Typography | Unified headline size, color, line-height, and numeric figure rhythm. | All six templates carry the same headline contract and tabular numbers. |
| 3 | Space | Established a 40px desktop gutter and subtle whole-paper depth. | Gutter and shadow tokens present in all templates; diff clean. |
| 4 | A2 provenance | Added time, detector, tier, and retry context near alert headlines. | Three A2 templates expose all expected provenance facts. |
| 5 | Data composition | Added metric dividers on desktop and removed them on mobile. | Four metric-dense templates carry divider and reset rules. |
| 6 | A4 restraint | Reduced KPI spectacle, sharpened promotion language, and exposed complete tier values. | Evidence count, evidence-floor language, and T2 percentage verified. |
| 7 | Trust boundary | Normalized CTAs and stated read-only, authentication, and no-action behavior. | One labeled CTA and one boundary statement per template. |
| 8 | Mobile choreography | Reduced headline scale and expanded CTA touch targets. | Mobile title and CTA rules present in all six templates. |
| 9 | Email clients | Added Outlook-specific table width, gutter, and collapse fallbacks. | MSO conditional block present in all six templates; editor diagnostics clean. |
| 10 | Provenance | Rewrote footers around message class and receipt reason; curated the gallery. | Six receipt reasons plus gallery round provenance verified. |

## Final Verification

The final gallery and all six iframe documents were measured in Chromium at desktop and 390px mobile viewports.

- Gallery horizontal overflow: `0px` desktop and mobile.
- Template horizontal overflow: `0px` for all six templates desktop and mobile.
- Mobile headline length: three lines or fewer for all six templates.
- Mobile CTA width: stable within the content gutter for all six templates.
- HTML set: six standalone templates plus one gallery.
- Remote images, scripts, forms, and tracking pixels: none.
- Approval, reject, or execute URLs: none.
- External runtime dependency: none.
- Repository punctuation and whitespace checks: pass.
- VS Code diagnostics: zero.

## Second-Pass Critique

The first ten rounds produced a polished operational email system, but the result still relied
on familiar SaaS grammar. A second critique found 24 additional issues that separated polish
from genuine editorial elegance.

| # | Finding | Why it still felt ordinary | Resolution |
|---|---------|----------------------------|------------|
| 29 | The entire message floated as a shadowed card. | It resembled an application panel placed on a background. | Removed the shadow and treated the message as a sheet of correspondence. |
| 30 | The paper used an 8px product-card radius. | Rounded corners signaled reusable UI more than a formal dispatch. | Reduced the paper edge to a nearly square 2px fallback. |
| 31 | The canvas and paper colors were neutral gray and white. | The pair was clean but lacked material warmth. | Moved to warm stone canvas and ivory paper. |
| 32 | The square `F` mark imitated an app icon. | It looked generic and decorative rather than authored. | Replaced it with a typographic FDAI / Field dispatch wordmark. |
| 33 | Segoe UI plus Georgia felt like a default Microsoft document. | The combination was familiar but not distinctive. | Introduced an Aptos-first body and Iowan/Palatino old-style headline stack. |
| 34 | Thirty-pixel desktop headlines were cautious. | They did not create the generous editorial pause expected from a letter. | Raised desktop headlines to 34px while retaining a restrained mobile scale. |
| 35 | A2 state lived in rounded colored pills. | The strongest SaaS artifact remained at the top of every alert. | Replaced pills with thin ruled typographic rubrics. |
| 36 | A2 headlines used mechanical threshold language. | They sounded generated rather than composed. | Rewrote them as concise operating statements. |
| 37 | Evidence links still looked like filled primary buttons. | The messages invited an app command rather than further reading. | Converted CTAs into restrained underlined evidence links. |
| 38 | Mobile CTAs were centered like conversion buttons. | Centered controls reinforced marketing-email rhythm. | Left-aligned evidence links on mobile. |
| 39 | Critical disposition sat in a pink card. | The container carried more alarm than the words. | Changed it to an unboxed ruled section with text-local status color. |
| 40 | Cost observed/baseline values sat in a pale card. | The comparison looked like a dashboard widget. | Changed it to an open ruled comparison ledger. |
| 41 | Channel health used three boxes and arrows. | It read as an architecture diagram, not correspondence. | Rebuilt it as a numbered delivery trail. |
| 42 | Shadow accuracy used a centered green KPI card. | It remained celebratory despite the first-pass reduction. | Left-aligned the number in an unboxed evidence section. |
| 43 | Promotion candidates were side-by-side cards. | The pattern resembled product comparison. | Rebuilt them as a vertically ordered review docket. |
| 44 | Promotion rule identifiers were 10px. | Technical provenance was visually demoted too far. | Raised rule identifiers to 11px and gave them a full line. |
| 45 | Promotion cards implied equal readiness. | A side-by-side layout flattened the held-candidate distinction. | Numbered and ordered candidates by review readiness. |
| 46 | The monthly tier mix was a three-color dashboard bar. | It imported chart grammar into a letter. | Replaced it with a three-column typographic ledger. |
| 47 | Monthly inference cost sat in its own tinted box. | It competed with reliability as a detachable widget. | Integrated it as a ruled column in the operating ledger. |
| 48 | Trust captions read like compliance boilerplate. | Long slash-separated text interrupted the ending cadence. | Shortened the caption to one authenticated-evidence sentence. |
| 49 | Audit identifiers looked like ordinary body metadata. | They lacked the quiet, archival quality of a reference folio. | Styled one monospace folio per message. |
| 50 | Footers retained a tinted surface. | The footer became another card-like band. | Removed the tint and kept a single hairline rule. |
| 51 | Footer prose explained receipt in full sentences. | The compliance tone weakened the editorial finish. | Replaced prose with a concise message-class colophon. |
| 52 | The gallery remained a rounded card wall. | It contradicted the correspondence language of the templates. | Rebuilt the gallery as a ruled, shadow-free specimen folio. |

## Second-Pass Rounds

| Round | Focus | Change | Focused check |
|-------|-------|--------|---------------|
| 11 | Paper architecture | Warmed canvas and paper, removed shadows, reduced radius, widened the reading gutter. | Six templates carry ivory paper, no shadow, and 44px desktop gutters. |
| 12 | Typographic brand | Removed the square icon and introduced the FDAI / Field dispatch wordmark. | No template contains the old icon; six contain the new signature. |
| 13 | Editorial type | Added Aptos-first body text and Iowan/Palatino headline typography at 34px. | All six templates expose the new font stacks and headline scale. |
| 14 | Status rubric | Removed A2 pills and rewrote alert headlines. | Three A2 templates contain ruled rubric labels and no hero pill. |
| 15 | Evidence links | Converted filled CTAs into transparent underlined references. | Six CTAs compute to transparent backgrounds and 0px radius. |
| 16 | De-cardification | Rebuilt disposition, comparison, KPI, and candidate surfaces as ruled sections. | Primary semantic blocks carry no tint, radius, or nested card border. |
| 17 | Monthly letter | Replaced the tier bar and inference card with typographic ledgers. | Colored bar and boxed KPI signatures are absent. |
| 18 | Review docket | Replaced side-by-side promotion cards with an ordered vertical docket. | Candidate card classes are absent from the message body. |
| 19 | Delivery trail | Replaced channel boxes and arrows with a numbered correspondence trail. | Flow-card classes are absent; three numbered stages are present. |
| 20 | Folio system | Shortened trust captions and separated audit references typographically. | Exactly one `.audit-ref` exists in every template. |
| 21 | Colophon | Replaced tinted explanatory footers with concise unboxed colophons. | Receipt prose and tinted footer bands are absent. |
| 22 | Specimen folio | Rebuilt the gallery and exposed cumulative critique provenance. | Gallery reports 52 findings / 22 rounds and has no card shadow. |

## Editorial Verification

The second-pass result was loaded directly, with cache-busting URLs, at 760px desktop and
390px mobile viewports.

- Paper width: `640px` desktop and `351px` mobile.
- Horizontal overflow: `0px` in all six templates at both viewports.
- Rounded elements over 4px: `0` in all six templates.
- Filled evidence links: `0`; every CTA computed to a transparent background and 0px radius.
- Desktop headline: `34px`, two lines or fewer.
- Mobile headline: `28px`, three lines or fewer.
- Old square monogram and `Autonomous operations` signature: absent.
- Typographic FDAI / Field dispatch signature: present in all six templates.
- Promotion cards, channel-flow cards, colored monthly tier bar, and tinted footer bands:
	absent.

## Third-Pass Critique

The second pass removed SaaS card grammar, but the result was still a highly restrained report.
The third pass identified 24 further gaps between minimal cleanliness and premium executive
correspondence.

| # | Finding | Why restraint was not yet elegance | Resolution |
|---|---------|------------------------------------|------------|
| 53 | The first viewport had no dark visual anchor. | Ivory-on-stone was calm but lacked a memorable opening gesture. | Added a full content-bearing ink masthead. |
| 54 | The typographic masthead was too small for a sender signature. | FDAI felt like metadata rather than the author. | Increased the wordmark and expanded its tracking. |
| 55 | Messages had no serial or issue number. | The six artifacts lacked collectible correspondence identity. | Added `NO. 001` through `NO. 006`. |
| 56 | A2 and A4 used the same masthead temperature. | Immediate alerts and reflective digests felt emotionally identical. | Kept A2 charcoal and moved A4 to muted green-black. |
| 57 | Hero decks used the full available measure. | Headline and deck formed the same rectangle. | Constrained deck copy to a 500px editorial measure. |
| 58 | Hero deck line-height remained compact. | The message opening still read like product copy. | Increased deck line-height and softened its color. |
| 59 | Metric numerals remained semibold sans. | Data still looked detached from the editorial voice. | Applied old-style serif numerals with regular weight. |
| 60 | Cost comparison lacked a single conclusion. | Readers still had to calculate the scale of variance. | Added a large `+38.0%` focal datum. |
| 61 | Critical disposition only described review state. | It did not show why execution remained safe. | Paired review state with explicitly withheld authority. |
| 62 | Shadow agreement dominated its guard result. | Accuracy could still be read as the only success measure. | Paired agreement and zero escapes at the same hierarchy. |
| 63 | The shadow lower ledger repeated policy escapes. | Repetition consumed scarce evidence space. | Replaced the duplicate with mixed-model disagreement count. |
| 64 | A4 time labels used three unrelated naming patterns. | Daily, weekly, and monthly messages lacked edition coherence. | Introduced ledger, docket, and operating-letter kickers. |
| 65 | A2 provenance floated as an unframed tiny row. | Time, source, and decision path lacked wire-service authority. | Added a thin stone dateline band. |
| 66 | Evidence links ended without directional cadence. | The eye stopped abruptly at the underline. | Added a progressive arrow cue with text-only fallback. |
| 67 | Gallery specimens had names but no issue order. | The gallery resembled a file browser more than an archive. | Numbered all six specimens. |
| 68 | Gallery classifications were generic frequency labels. | They did not echo each template's correspondence type. | Added operational, governance, ledger, docket, and letter metadata. |
| 69 | The monthly tier ledger lacked a dark contextual anchor above it. | The data structure was elegant but emotionally flat. | Bound it to the green-black A4 masthead. |
| 70 | The critical message lacked a visible fail-closed phrase. | Safety had to be inferred from "no action." | Added `Withheld / fail-closed`. |
| 71 | Cost variance color appeared in contributors but not a conclusion. | Accent use was fragmented. | Concentrated terracotta on the focal variance result. |
| 72 | Shadow mode had three equal lower metrics after a large KPI. | The hierarchy did not distinguish quality from diagnostic context. | Promoted agreement/guard pair and demoted volume diagnostics. |
| 73 | Several progressive style blocks sat after `</head>`. | Browsers repaired the markup, but conservative clients need explicit structure. | Kept the head open through every style block. |
| 74 | Outlook conditional CSS remained in body content. | The body was not purely message content. | Moved the MSO block into the head. |
| 75 | Style architecture could not be verified by simple ordering. | Client safety depended on browser tolerance. | Added one-head, head-before-body, no-body-style checks. |
| 76 | The folio still advertised an earlier critique count. | Process provenance lagged behind the actual design. | Updated the gallery to 76 findings / 34 rounds. |

## Third-Pass Rounds

| Round | Focus | Change | Focused check |
|-------|-------|--------|---------------|
| 23 | Ink masthead | Added full charcoal headers, ivory branding, and serial numbers. | Six mastheads contain dark surfaces and `NO. 00x`. |
| 24 | Narrative measure | Constrained and softened the hero deck. | Six templates expose the 500px deck contract. |
| 25 | Temperature split | Differentiated A4 with a muted green-black masthead. | Exactly three templates carry the semantic `a4` treatment. |
| 26 | Signal dateline | Framed A2 time, source, and decision path in a stone band. | Three A2 templates carry `.dateline`. |
| 27 | Editorial numerals | Applied old-style serif treatment to primary metrics. | Six templates expose the progressive numeral rule. |
| 28 | Cost focal datum | Added the explicit `+38.0%` variance conclusion. | Cost template contains the focal result and its context. |
| 29 | Response posture | Paired critical review state with withheld authority. | Both posture dimensions are present. |
| 30 | Guard pairing | Paired shadow agreement with zero policy escapes. | Outcome and guard labels coexist in the focal section. |
| 31 | Edition system | Added Daily ledger, Governance docket, and Operating letter kickers. | All three A4 edition labels are present. |
| 32 | Link cadence | Added progressive directional cues to evidence links. | Six templates expose the arrow fallback rule. |
| 33 | Specimen archive | Numbered and classified the gallery specimens. | `01` through `06` and six `Open specimen` links exist. |
| 34 | Style architecture | Moved all progressive and Outlook CSS into a single ordered head. | One head, one head close, no body style elements in every template. |

## Premium Correspondence Verification

The third-pass result was cache-busted and measured directly at 760px desktop and 390px
mobile viewports.

- A2 masthead: computed charcoal `rgb(39, 50, 58)` in all three operational templates.
- A4 masthead: computed green-black `rgb(52, 65, 61)` in all three governance templates.
- Masthead height: stable at `95px` across all six templates and both viewports.
- Paper width: `640px` desktop and `351px` mobile.
- Horizontal overflow: `0px` across all templates and viewports.
- Rounded elements over 4px: `0`.
- Filled evidence links: `0`.
- Desktop headline: `34px`, two lines or fewer.
- Mobile headline: `28px`, three lines or fewer.
- Style elements in body: `0`; Outlook conditional CSS is head-scoped.
- Every template carries one message serial, one audit folio, one evidence link, and one
	content-class colophon.

## Residual Constraints

Email clients are not browsers. Outlook desktop can ignore border radius and shadows, while dark-mode clients can still transform colors despite a light scheme declaration. The templates therefore preserve meaning through words, table structure, complete borders, and whole-surface tints even when progressive styling disappears.

Production rendering should inline any future shared CSS and run screenshot comparison in the supported mail-client matrix before release. The current files are standalone concepts, not a claim of pixel identity across every client.
