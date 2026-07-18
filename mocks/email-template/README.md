# FDAI Email Template Gallery

This folder contains standalone, dependency-free HTML email concepts based on the FDAI Calm Slate visual language. Each template uses synthetic data and a table-first layout suitable for Outlook, Microsoft 365, Gmail, and Apple Mail.

The collection has completed three critique-and-hardening passes: 76 findings across 34
rounds. See [hardening-review.md](hardening-review.md) for all finding sets, the round
ledgers, verification evidence, and residual email-client constraints.

## Templates

| File | Message class | Purpose |
|------|---------------|---------|
| [critical-incident.html](critical-incident.html) | A2 | Critical service degradation alert with evidence and runbook handoff |
| [cost-anomaly.html](cost-anomaly.html) | A2 | Cost anomaly notice with baseline comparison and contributing services |
| [channel-health.html](channel-health.html) | A2 | Primary notification-channel degradation and fallback status |
| [shadow-digest.html](shadow-digest.html) | A4 | Daily shadow-mode accuracy and guardrail digest |
| [promotion-candidates.html](promotion-candidates.html) | A4 | Weekly enforcement-promotion candidate review |
| [monthly-operations.html](monthly-operations.html) | A4 | Monthly tier, outcome, reliability, and inference-cost summary |
| [index.html](index.html) | Gallery | Browser preview and template comparison |

## Email Rules

- Email is send-only. Templates never include approval, reject, or execution actions.
- Links lead to read-only evidence, dashboards, runbooks, or authenticated review surfaces.
- All identifiers and values are synthetic and customer-agnostic.
- Important meaning is expressed in text, not color alone.
- Layout uses nested presentation tables and inline styles. The small responsive style block is progressive enhancement.
- Every message includes an inbox preheader, read-only evidence boundary, audit folio,
  concise colophon, and Outlook table fallback.
- External fonts, JavaScript, SVG, forms, video, and remote tracking pixels are intentionally absent.

## Preview

Open [index.html](index.html) directly in a browser. Open an individual file to inspect the 640px email rendering without the gallery shell.
