# Development Console and Gateway

This Terraform root owns the FDAI development Console host and browser API edge in a separate
state. It reuses the Static Web App and authenticated browser-gateway modules while referencing
existing HTTPS Operator and document-ingestion backends.

## Boundary

- Static Web Apps hosts only the prebuilt Console artifact and receives no managed identity.
- API Management validates the Microsoft Entra tenant and API client audience, restricts CORS to
  the exact Console origin, and routes Operator at `/` and ingestion at `/ingestion`.
- Operator and ingestion retain their own JWT, App Role, idempotency, revision, and audit checks.
  API Management does not receive an executor identity and cannot bypass either backend.
- The two backend origins must use HTTPS. Deployment values, Entra ids, endpoints, and the remote
  backend configuration stay outside source control.

Use a dedicated backend key such as
`fdai-<environment>-development-console-gateway.tfstate`. This root does not own the resource
group, backend services, Entra registrations, Console publication, or live reachability checks.

## Outputs

`console_static_web_app_id`, `console_origin`, `operator_api_base_url`, and
`ingestion_api_base_url` are the publication bindings. `operator_health_url`,
`ingestion_health_url`, and the two `*_unauthenticated_probe_url` outputs are the exact URLs for
live reachability verification. The `gateway_frontend_tenant_id` and
`gateway_frontend_audience` outputs bind the authenticated token check. A healthy deployment
returns success from both health URLs and `401` from both unauthenticated probes.

## Validation

Run from the repository root:

```bash
terraform -chdir=infra/development-console-gateway init -backend=false
terraform -chdir=infra/development-console-gateway validate
terraform -chdir=infra/development-console-gateway test
```

These commands perform no Azure mutation. An exact reviewed plan and separate current approval
remain required before any apply.
