# Document Ingestion Gateway

This module runs the production document-ingestion API, internal worker, and migration job as
independent Azure Container Apps roles from one image. The API streams uploads to private ADLS
Gen2. The worker consumes durable lifecycle records, runs ClamAV, extracts content, and indexes
pgvector. The migration job remains the single schema authority.

## Role boundaries

- **API:** External HTTPS ingress, `/healthz`, Event Hubs send, upload/search/deletion database
	grants, and no background worker loops.
- **Worker:** No ingress, internal `/live` and `/ready` probes, Event Hubs send/receive, worker
	database grants, optional OCR, and replica-local ClamAV on port `3310`.
- **Migration:** No runtime traffic. It alone reads the administrator DSN and runs
	`alembic upgrade head` before either runtime revision is accepted.

Each role uses a distinct user-assigned managed identity and Key Vault DSN reference. API and
worker readiness verifies the effective PostgreSQL session role. Their CPU, memory, and replica
settings are independent. Defaults keep one worker replica until
restart, broker redelivery, DLQ, and durable-claim scale-out smoke checks are recorded.

## Rollback

Set `cohost_worker = true` to remove the worker app and return its loops and ClamAV sidecar to the
API app. This rollback preserves the existing image, topics, consumer groups, offsets, storage
layout, public routes, and migration authority.
