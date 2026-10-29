---
title: WARA evidence input and report exports
---
# WARA evidence input and report exports

Use the scheduled WARA assessment to combine exact Azure observations with signed manual review
receipts, then export the complete result. Source availability, successful collection and a
satisfied recommendation remain different states.

> This is a read-only shadow assessment. Running the job still requires an authorized deployment,
> its exact workload scope and its existing identity. These options grant no Azure execution rights.

## What this guide covers

The job can read an authenticated manual-evidence bundle, import bounded native WARA Collector
context, and write JSON, CSV, Excel and PowerPoint files. Missing or inadmissible evidence stays
unknown; no report is a compliance score.

## Configure a trusted manual producer

Install the producer's public-key trust file separately from its evidence file. The deployment
owner controls the trust file; never accept a public key supplied inside the evidence bundle.
Key installation, rotation and revocation are deployment administration, not evidence submission.

```json
{
  "schema_version": "1.0.0",
  "bindings": [{
    "key_id": "review-key-example",
    "producer": "workload-evidence-owner",
    "public_key_base64": "<base64-encoded-Ed25519-public-key>",
    "workload_ids": ["workload-example"],
    "valid_from": "2026-10-29T00:00:00Z",
    "valid_until": "2026-10-30T00:00:00Z",
    "revoked": false
  }]
}
```

Replace the example validity window with the approved current window. The producer keeps its
private key outside FDAI configuration, source, chat and logs.

## Produce a signed receipt bundle

The envelope contains `key_id`, `payload` and `signature_base64`. Sign the bytes returned by
`fdai.delivery.wara_manual_evidence.manual_evidence_signing_bytes(key_id, payload)` with the
registered Ed25519 key. The signature covers both the key identity and canonical payload.

| Payload field | Required meaning |
|---------------|------------------|
| `schema_version` | `1.0.0` |
| `producer` | The trusted producer slot required by each recommendation |
| `workload_id`, `scope_digest` | The exact current assessment scope |
| `framework_revision`, `crosswalk_digest` | The current pinned source and implementation |
| `ontology_release` | The exact current semantic release |
| `inventory_generation` | The current observed inventory generation |
| `receipts` | At most 393 manual `WaraEvidenceReceipt` objects, including explicit fallback review |

Each receipt supplies `recommendation_id`, `evidence_ref`, `evidence_kind`, `producer`,
`scope_digest`, `source_revision`, `inventory_generation`, `observed_at`, `recorded_at`,
`evidence_digest`, `freshness_ceiling_seconds`, `complete`, `truncated`, `conflicting`, `synthetic`,
`provider_error` and `outcome`. Its optional `applicability_approval_ref` never substitutes for
the runtime's reviewed not-applicable disposition and approval requirements.

Use the recommendation's exact evidence kind, producer and freshness ceiling. Outcome values are
`satisfied`, `failed`, `not_applicable` or `unknown`. A signature authenticates the producer's
attestation; it does not prove a recovery drill occurred or upgrade stale or synthetic material.
Unsupported fields, duplicate recommendation receipts, untrusted or expired keys, tampering and
pin substitution fail explicitly. Each input file is limited to 1 MiB.

Configure both paths together:

```text
FDAI_WARA_MANUAL_EVIDENCE_FILE=/var/run/fdai/wara/evidence.json
FDAI_WARA_MANUAL_TRUST_FILE=/var/run/fdai/wara/trust.json
```

The job reads these files before evaluation. The result retains a content-addressed attestation
reference covering the signed payload and exact trust binding, plus the independent evidence digest.
Keep the signed bundle and applicable trust revision
in the deployment's retained evidence storage for replay. No private signing key is needed by FDAI.

## Import native Collector context

Set `FDAI_WARA_COLLECTOR_CONTEXT_FILE` to an existing native WARA Collector JSON file and configure
a report directory. Its declared subscription set must exactly match the subscriptions of the
assessment's ARM targets. Wider, missing or malformed scope is rejected.

The importer connects `advisory`, `outages`, `retirements`, `supportTickets` and `serviceHealth`.
Only counts and the source digest enter the report, never private ticket text. Missing collections
are unavailable rather than an observed zero. The file is limited to 16 MiB and each collection to
10,000 records.

An unsigned Collector file is **unverified subscription context**, not fresh workload evidence.
It never changes recommendation applicability, evaluation, satisfaction or authority. This bridge
does not replace the original Collector or perform a new live Azure collection.

## Export the same assessment in four formats

Set `FDAI_WARA_REPORT_DIRECTORY` to the deployment-owned output directory before running the
existing `fdai-wara-assessment` entry point. The sink writes one content-addressed basename with
`.json`, `.csv`, `.xlsx` and `.pptx` extensions. Output files have mode `0600`.

- Every active recommendation is retained, including unknown and blocked results.
- Every format uses the same source, inventory, scope, result digest and evaluation time.
- Excel uses text-only cells and retains metadata and widget errors in separate sheets.
- PowerPoint paginates complete content instead of silently omitting rows.
- Office inputs are limited to 8 MiB of encoded report data and PowerPoint to 1,000 slides.
- Missing supplemental sources remain explicitly unavailable.
- A malformed or tampered assessment cannot be exported as a valid shadow report.

Writing files does not publish them, authorize disclosure or certify a live deployment. The
independent Operator reporting service registers its own HTTP formats separately.

## Next steps

| To learn about | Read |
|----------------|------|
| Assessment and evidence boundaries | [WARA assessment](../roadmap/rules-and-detection/wara-assessment.md) |
| Shared format encoders | [Reporting subsystem](../roadmap/interfaces/reporting-subsystem.md) |
