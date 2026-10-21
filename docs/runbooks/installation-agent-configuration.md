---
title: Installation Agent configuration inputs
---
# Installation Agent configuration inputs

Use the existing installation Agent to verify a full signed v2 configuration revision and
inspect CSI reference reports without reading secret values. This guide describes local
provisioning inputs, not an enrollment ceremony, deployment approval or production trust proof.

> **Boundary:** Source and local synthetic tests are implemented. Real key onboarding,
> authenticated artifact synchronization, CSI provider binding and operational acceptance remain
> separate work. Default `poll-once` is a dry run. This guide does not authorize `--apply`.

## Prerequisites

- Independently provisioned Hub and Release verification keys and the existing local hard policy.
- The independently approved customer configuration Ed25519 public key, and a separate
  installation X25519 private key. Never supply an Ed25519 identity key as encryption input.
- An admitted signed Plan produced through the existing Hub import, independent scope/change
  approval and activation path. Its exact package digest must equal the locally retained active
  revision. A package signature or a local file does not itself prove those approvals.
- A complete signed runtime v3 Release manifest with `configuration_schema`, including its exact
  Release version and canonical schema digest. A Release Hub export, offline kit or schema file
  beside an untrusted manifest is not a substitute.

## Prepare installation-local inputs

Keep private inputs in current-user mode-`0700` directories and mode-`0600`, single-link files,
using the existing deployment private-file helpers. No key or decrypted identifier goes into
Git, a command argument value, logs, reports or public output.

Place the unchanged `fdai.lifecycle-configuration-file.v1` container produced by
`fdaictl configuration build` at `configurations/<package-digest>.json` beneath `--inputs-dir`.
This container includes the original v2 signed payload and detached signature, not a public key.
The digest names the payload, not the container. Its directory is private. The Release still
uses `releases/<manifest-digest>.json` and its existing `.sig` sibling.

The independent `--configuration-binding` JSON has exactly these fields:

```json
{
  "format": "fdai.lifecycle-agent-configuration-binding.v1",
  "installation_id": "<installation-id>",
  "active_digest": "<exact-active-package-sha256>",
  "entity_bindings": {"core": "<independently-approved-64-hex-binding>"},
  "sealed_keys": ["endpoint"],
  "history": []
}
```

`entity_bindings` covers exactly the already-managed Entity set from local policy, one-to-one.
Plan Entity IDs remain the existing local IDs, not the 64-character package bindings.
History is the complete ordered ancestor chain, at most 256 packages and 16 MiB of payloads.
Each ancestor has exactly `digest`, `configuration_key_file` (its independently retained
Ed25519 public-key PEM path), and `installation_key_digest` (its original X25519 recipient
digest). Put each original ancestor container in the same artifact store. Historical trust
authenticates accepted bytes only; it never establishes current signing permission.

Add these options to the existing `poll-once` command:

```bash
--configuration-binding /private/approved-binding.json \
--installation-encryption-key /private/installation-encryption.pem
```

Missing bindings, key input or manifest schema produce `configuration_unavailable` and no
prepare/effect. Invalid substitutions are rejected. No helper fetches a key or chooses a binding
from a package. Legacy flat `schema`/`environment`/`entity_overrides` documents and detached
signatures keep working without these options. The separate canonical single-Entity package
v1 is not a full v2 revision and is not silently converted.

## Rendering and private state

Each Entity resolves separately and all configured regions narrow the existing local maximum.
The existing demo supports 1-3 replicas for v2, while legacy demo behavior remains one replica.
The same-schema Operator profile keeps its existing schema checks, dependency references and
fixed resource limits. Of decrypted identifiers, only its supported `operator_config_map_name`
reference reaches rendering. Other identifiers are authenticated but not used to invent workload
fields. No Entity can choose a namespace, image repository or capability mode.

Before v2 preparation, the Agent requires a private state directory. Its owner-only journal may
contain rendered reference names for rollback. Decrypted endpoint/identifier values do not enter
reports, state snapshots or logs. Existing Plan admission, dry run, two-phase reports, rollback,
target lock, expiry and restart suppression remain required. Passing local tests is not evidence
of a successful installation or usable secret.

## Inspect CSI reference reports

Only explicitly bound sources are inspected. The `reference-status` command does not enroll
providers, change RBAC, create a Secret or open a mounted file:

```bash
fdai-lifecycle-agent reference-status \
  --references /private/csi-references.json \
  --kube-context <independently-selected-context> --namespace <exact-namespace>
```

The private JSON is a list of at most 32 objects, each with exactly the `CSIReference` fields:
`entity_id`, `namespace`, `pod_name`, `pod_uid`, `class_name`, `status_name`, `object_id`,
`object_version`, and `source_manager`. Supply exact retained names and the expected Key Vault
secret version, not a value. The Pod's Entity label, UID, class volume and status owner must agree,
and the SecretProviderClass provider must be `azure`.

The bounded adapter reads exactly named Pod, SecretProviderClass and
SecretProviderClassPodStatus objects through the existing Kubernetes transport. It attributes the
status resource version, expected object version, Pod UID, read time and driver manager update
time. `binding_digest` correlates the exact private namespace/Pod/class/source selection without
printing those target names. Fixed SDK read paths avoid discovery and retain the separate
ten-second SDK request timeout. A thirty-second completion-acceptance budget is checked before
and after each read. Results completing at or after that deadline are `unavailable`, and no
further read or retry starts. This does not interrupt an in-flight request or guarantee that the
whole command finishes within thirty seconds: an in-flight request may return after the
acceptance deadline under the existing SDK timeout.
Without the driver timestamp the report is `unknown`; after five minutes it is `stale`;
conflicting bindings/versions are `conflict`; missing or denied sources are `unavailable`.
`reported-mounted` and `reported-unmounted` describe driver reports only, never independently
verified secret usability. Fixtures and file existence cannot upgrade this state.

## Next steps

| To learn about | Read |
|----------------|------|
| Exact compatibility and design critique | [Lifecycle Configuration](../roadmap/deployment/lifecycle-configuration.md#installation-agent-consumer-design-and-critique) |
| Plan admission and operational boundaries | [Hub-Managed Lifecycle](../roadmap/deployment/hub-managed-lifecycle.md) |
| Existing CLI, apply safeguards and opt-in tests | [Lifecycle Agent](../../lifecycle/agent/README.md) |
