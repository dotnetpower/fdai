# Deployment Fork Overrides

This reference describes the supported fork-owned deployment inputs. FDAI remains
customer-agnostic, and a fork customizes deployment without changing `core/`.

## Override points

A fork can:

- Provide its own `llm-registry.yaml` with region and compliance overrides.
- Supply `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID` environment values that point to the fork's
  subscription. The upstream repository never stores those values.
- Register an additional LLM provider by binding a fork-owned `CrossCheckModel` implementation in
  its composition root. Use the `azure-foundry`, `external`, or `hil-only` strategy described in
  [Mixed-Model Family Strategies](../roadmap/architecture/llm-strategy.md#mixed-model-family-strategies).

## Related docs

| To learn about | Read |
|----------------|------|
| Local and deployed parity | [Development and deployment parity](../roadmap/deployment/dev-and-deploy-parity.md) |
