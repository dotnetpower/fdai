---
title: FDAI L100 Deck Kit
description: The slide-by-slide source for the 30-slide FDAI introduction deck - outcome-first storyline, agent-driven architecture, and a repeatable delivery model.
---

# FDAI L100 Deck Kit

This kit is the written source for the 30-slide FDAI introduction deck (L100).
It isn't a presentation file. It's the slide-by-slide specification a presenter
or a designer turns into slides, so every delivery of the deck tells the same
story with the same evidence and the same safety claims.

The kit is built around three constraints:

- **Customer outcomes first.** The deck opens with the operational reality a
  customer already lives with, not with a component diagram. Every slide carries
  the result the customer gets.
- **An agent-driven operating shift.** FDAI is an organization of agents that
  runs the detect, decide, act, and prove loop. The deck explains what moves to
  the agents, what stays with people, and which boundaries make that safe.
- **Repeatable delivery through minimal change.** The deck states what is fixed
  in the product and what is swapped per customer, so a delivery becomes an
  onboarding procedure rather than a custom development project.

## How to use this kit

1. Read this page for the slide map, the timing plan, and the customization
   rules.
2. Open the act file that covers the slides you are building. Each slide is one
   card with a headline message, a density level, body structure, a visual
   instruction, speaker notes, and source docs.
3. Fill only the placeholder slots listed in
   [What you change per customer](#what-you-change-per-customer). Everything
   else stays as written so the deck stays reusable.

| Act | Slides | Job |
|-----|--------|-----|
| [Act 1 - Why now and what FDAI is](l100-act1-why.md) | 1-10 | Establish the pain, then define FDAI and its agent-driven architecture |
| [Act 2 - How it works and what you get](l100-act2-how.md) | 11-21 | The loop, the safety boundaries, the three verticals, and the demo |
| [Act 3 - Adopt, deliver, and measure](l100-act3-adopt.md) | 22-30 | The operating-model shift, the delivery kit, onboarding, and next steps |

## Slide density

Each slide card declares a density, so the deck mixes short and detailed slides
on purpose instead of by accident.

| Density | What it means | Time on slide |
|---------|---------------|---------------|
| `Light` | One message, minimal text, the presenter carries it | 30-45 seconds |
| `Standard` | 3-5 bullets plus one visual | 60-90 seconds |
| `Detailed` | A table or a layered diagram, meant to be read and revisited | 2-3 minutes |

A detailed slide is allowed to be dense. It doubles as a leave-behind, so it
should still make sense to a reader who wasn't in the room.

## Timing plan

| Segment | Slides | 45-minute session | 30-minute session |
|---------|--------|-------------------|-------------------|
| Open and pain | 1-5 | 8 minutes | 6 minutes |
| Definition and agent-driven architecture | 6-10 | 9 minutes | 6 minutes |
| Loop and safety boundaries | 11-16 | 9 minutes | 5 minutes |
| Verticals | 17-19 | 5 minutes | 3 minutes |
| Demo and console | 20-21 | 6 minutes | 5 minutes |
| Operating shift and delivery | 22-26 | 7 minutes | 3 minutes |
| Measure, fit, questions, next steps | 27-30 | 5 minutes | 2 minutes |

For the 30-minute cut, drop slides 9, 16, 25, and 28, and merge slides 17-19
into one outcome slide. Keep slides 13, 14, and 22 in every cut: they carry the
safety story and the role shift, which are the two questions every audience
asks.

## Audience

The deck targets a mixed room and is explicitly usable for a first sales
conversation.

| Audience | What they need from the deck | Slides that carry it |
|----------|------------------------------|----------------------|
| Operations and platform leadership | Where the toil goes, what changes for the team, what it costs to start | 3, 10, 22, 26, 30 |
| SRE and platform engineers | The loop, the tiers, the safety contract, rollback and audit | 11-16, 21 |
| Security and architecture reviewers | Separation of authority, single-writer ownership, identity boundaries | 7, 9, 15, 23 |
| Procurement and business sponsors | Measurable outcomes, guard metrics, adoption path, objections | 17-19, 27, 29, 30 |

## Asset slots

The deck reserves fixed slots for customer-specific media. The slot definition
stays in the deck. The media doesn't.

| Slot | Slide | Specification |
|------|-------|---------------|
| Demo video | 20 | 4-6 minutes, MP4, readable without sound, Korean captions burned in, autoplay off |
| Demo fallback stills | 20 | 3 images that carry the same story if the video fails |
| Console screenshots | 21 | 4 screens: decision detail, pending approval, audit history, ownership view |
| Title background | 1 | [nebula-2000x1125.png](nebula-2000x1125.png) or a customer-neutral brand background |

Screenshots and video use demo data only. Real tenant names, subscription
identifiers, resource names, endpoints, and user identities never enter the
deck.

## What you change per customer

Only these slots change between deliveries. Everything else is product-level
content that is reviewed once.

| Slot | Slide | Filled with |
|------|-------|-------------|
| Pain quote | 3 | One or two sentences from the pre-meeting interview |
| Baseline table | 3, 27 | The customer's current measured values, or blank when no baseline exists yet |
| Vertical order | 17-19 | Lead with the vertical that matches the customer's stated priority |
| Demo scenario | 20 | The scenario closest to the customer's environment |
| Pilot scope | 26 | The subscription, resource group, or workload chosen for the first observation-mode run |
| Next-step owners | 30 | Named people and dates |

## What never goes in the deck

- Customer identifiers, tenant values, endpoints, or subscription identifiers.
- Performance or savings numbers that weren't measured on a paired baseline. The
  target coverage numbers on slide 12 are stated as targets, never as results.
- Claims that FDAI acts without a safety check, an approval path, or a rollback
  path.
- Competitor comparisons by name.

## Next steps

| To learn about | Read |
|----------------|------|
| The product story the deck compresses | [Get started with FDAI](../get-started.md) |
| The agent organization behind slides 7-9 | [FDAI architecture](../architecture.md) |
| The safety story behind slides 13-16 | [Trust tiers](../concepts/risk-tiers.md) and [Observation mode](../concepts/shadow-then-enforce.md) |
| The delivery model behind slides 24-26 | [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) |
