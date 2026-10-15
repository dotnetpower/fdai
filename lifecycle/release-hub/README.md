# FDAI Release Hub

The Release Hub is the vendor's independent local application for registering manifests,
publishing development signatures, contributing releases to channels, and recalling releases.
It does not deploy FDAI, build images, publish to a registry, or grant installation authority.

## Layout

| Path | Responsibility |
|------|----------------|
| `src/fdai_release_hub` | Loopback API, development signing and transactional local metadata |
| `ui` | Independent Preact UI using shared Calm Slate tokens and primitives |
| `tests` | API, persistence and Lifecycle Hub consumer regression tests |
| `../hub/src/fdai_lifecycle_hub/catalog_import.py` | Opt-in pinned export admission into the existing catalog |

## Local design, critique, and revised boundary

Initial design: expose vendor publication and channel mutation using the existing runtime
manifest parser and the installation agent's detached Ed25519 signature convention.

Critique: a valid manifest signature does not authenticate its version label, channel membership,
or recall state. It does not prove artifact availability, production trust, or catalog freshness.
An unauthenticated development service cannot safely listen on a public interface.

Revised boundary: this is a local-only, shadow development tool, not a production catalog
protocol. Registration retains exact manifest bytes, and publication signs those bytes with a
development key generated outside the checkout. SQLite transactions bind revision, metadata,
and audit events. Every mutation requires an exact current revision, target confirmation and
reason. Retry after an ambiguous result starts with a read, not an automatic repeated write.
Release ids cannot be reused, recalled releases cannot be republished or added to a channel,
and channel additions are manual curation, not an automatic promotion pipeline.

The export is a local JSON projection of releases, channels and recalls, not signed TUF
metadata. A Lifecycle Hub consumer requires a separately obtained exact SHA-256 pin and a
trusted development public key, verifies each release signature and parses existing manifest
and recall contracts. Changing membership or recalls changes the pin. Consumers reject expired
exports, a lower revision, and a changed export at the same revision. Pins and revision floors
must be retained by the caller; automatic remote sync and durable consumer trust state are not
implemented. Production root, snapshot, timestamp roles and key rotation remain future work.
The default unsigned `load_catalog` development path stays unchanged.
The canonical manifest digest identifies the parsed release, while the signed payload digest
hashes its exact original bytes, including whitespace. The UI shows both; neither establishes
registry availability or production trust.

## Running locally

From the repository root, use Python 3.12 or newer:

```bash
uv run --project lifecycle/release-hub fdai-release-hub dev-init /private/release-hub
uv run --project lifecycle/release-hub fdai-release-hub serve /private/release-hub --port 8091
npm --prefix lifecycle/release-hub/ui ci
npm --prefix lifecycle/release-hub/ui run dev
```

The API and UI bind only to `127.0.0.1`. The UI uses port `5291`, proxies the API on `8091`,
and rejects cross-origin mutation requests. No production authentication or key management is
implemented. The key is never returned by an API or accepted through a browser form.
Register an existing `fdai.runtime-release.v3` manifest; registration validates metadata only.
Artifact archives, SBOM contents, provenance semantics and registry presence remain unverified.
The optional local label may contain Korean; machine release ids remain canonical SemVer.

Build the UI with `npm --prefix lifecycle/release-hub/ui run build`; the API serves the built
application from the same loopback origin when the build exists. The `serve` command never
creates a missing key implicitly. Keep the state directory outside source control.

## Testing

```bash
uv run --project lifecycle/release-hub --with pytest --with pytest-cov --with httpx \
  python -m pytest -q --no-cov -p no:cacheprovider -c /dev/null \
  lifecycle/release-hub/tests lifecycle/hub/tests/test_release_hub_consumer.py \
  lifecycle/hub/tests/test_planning.py lifecycle/hub/tests/test_cli.py
npm --prefix lifecycle/release-hub/ui run typecheck
npm --prefix lifecycle/release-hub/ui test
npm --prefix lifecycle/release-hub/ui run build
```

## Consume a local export

Save `/v1/catalog/export` from the loopback API outside the checkout. Obtain its exact SHA-256
pin separately through the trusted local operator session; do not trust a digest delivered
alongside an untrusted download. Retain the last admitted revision and pin outside the checkout.
For an already enrolled development installation, use the existing Hub signing key and database:

```bash
uv run --project lifecycle/release-hub fdai-lifecycle-hub recompute-pinned \
  installation-alpha --export /private/catalog.json --sha256 "$TRUSTED_CATALOG_SHA256" \
  --release-public-key /private/release-hub/development.pub.pem \
  --minimum-revision "$LAST_ADMITTED_REVISION" --previous-sha256 "$LAST_ADMITTED_SHA256" \
  --key /private/lifecycle-hub.pem
```

On the first admission only, use a revision floor of `0` and omit `--previous-sha256`.
Choose the database with the existing `FDAI_LIFECYCLE_HUB_DATABASE_URL` setting. Tests use SQLite;
no runtime or remote PostgreSQL database is needed. Recall changes the pin and revision. Import
the newly approved export before recomputing; existing issued Plans are not revoked by this tool.

## Remaining production work

Production signing and root ceremony, authenticated contributor roles, signed catalog freshness
and anti-rollback state, automated promotion gates, custom channels, capability recall delivery,
registry mirroring, upgrade bundles and real FDAI workload deployment remain unsupported.
The Recall action records local eligibility withdrawal; it does not cancel issued Plans or
roll off running installations. An operator must refresh the pinned export before recomputing.

## Related docs

| To learn about | Read |
|----------------|------|
| Release design | [Lifecycle Releases and Channels](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md) |
| Installation planning | [Lifecycle Hub](../hub/README.md) |
| Current delivery scope | [Implementation ledger](../../docs/roadmap-implementation/deployment/lifecycle-releases-and-channels.md) |
