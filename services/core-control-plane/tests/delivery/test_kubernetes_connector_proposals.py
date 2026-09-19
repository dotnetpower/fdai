"""Private discovery proactively creates bounded proposals, not approvals or effects."""

from datetime import timedelta

import pytest
from fdai.delivery.aks_subscription_discovery import AksPrivateClusterObservation
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.kubernetes_connector_proposals import (
    OBSERVER_PROPOSAL_PREFIX,
    ObserverDeploymentProposalService,
)
from fdai.shared.providers.testing import InMemoryStateStore

from .test_kubernetes_connector_planning import DIGEST, NOW, context

CLUSTER = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example/"
    "providers/Microsoft.ContainerService/managedClusters/aks-example"
)


class Constraints:
    def __init__(self, value=None):
        self.value = value

    async def read(self, target_ref, *, now):
        return self.value


def observation():
    return AksPrivateClusterObservation(CLUSTER, NOW, DIGEST)


async def test_fresh_observation_suppresses_setup_without_deleting_history() -> None:
    from fdai.delivery.kubernetes_connector_projection import publish_observer_proposal

    active = [False]

    async def observing(target):
        assert target == to_neutral_id(CLUSTER)
        return active[0]

    store = InMemoryStateStore()
    service = ObserverDeploymentProposalService(
        store, constraints=Constraints(), now=lambda: NOW, observing=observing
    )
    assert await service.observe((observation(),)) == 1
    history = await store.read_states(OBSERVER_PROPOSAL_PREFIX, limit=10)
    active[0] = True
    assert await service.observe((observation(),)) == 0
    assert await service.current(to_neutral_id(CLUSTER)) is None
    assert await store.read_states(OBSERVER_PROPOSAL_PREFIX, limit=10) == history
    assert len(list(store.audit_entries)) == 1
    publications = []

    class Bus:
        async def publish(self, topic, key, payload):
            publications.append(payload)

    await publish_observer_proposal(
        target_ref=to_neutral_id(CLUSTER), service=service, store=store, bus=Bus(), now=lambda: NOW
    )
    assert publications[-1]["state"] == "unavailable"
    assert publications[-1]["proposal"] is None
    active[0] = False
    assert (await service.current(to_neutral_id(CLUSTER))).status == "needs_evidence"


async def test_unknown_constraints_create_one_proactive_inspection_proposal() -> None:
    store = InMemoryStateStore()
    service = ObserverDeploymentProposalService(store, constraints=Constraints(), now=lambda: NOW)
    assert await service.observe((observation(),)) == 1
    assert await service.observe((observation(),)) == 0
    rows = await store.read_states(OBSERVER_PROPOSAL_PREFIX, limit=10)
    assert len(rows) == 1
    assert rows[0]["proposal"]["status"] == "needs_evidence"
    assert rows[0]["proposal"]["recommended"] is None
    assert rows[0]["proposal"]["execution_authority"] is False
    assert len(list(store.audit_entries)) == 1


def test_evaluate_cli_reads_private_evidence_without_install_or_network(
    tmp_path, capsys, monkeypatch
) -> None:
    import json
    from datetime import UTC, datetime

    from fdai.delivery import kubernetes_connector_proposal_cli as cli

    now = datetime.now(UTC)
    value = context(facts=(), observed_at=now, expires_at=now + timedelta(minutes=10))
    path = tmp_path / "context.json"
    path.write_text(value.model_dump_json())
    path.chmod(0o600)
    monkeypatch.setattr(
        cli,
        "PostgresStateStore",
        lambda **kwargs: pytest.fail("evaluate must not acquire a database"),
    )
    assert cli.main(["evaluate", "--context", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "needs_evidence"
    assert output["execution_authority"] is False
    path.chmod(0o644)
    assert cli.main(["evaluate", "--context", str(path)]) == 1
    assert str(path) not in capsys.readouterr().out


async def test_verified_constraints_update_existing_case_without_installing() -> None:
    store, reader = InMemoryStateStore(), Constraints()
    service = ObserverDeploymentProposalService(store, constraints=reader, now=lambda: NOW)
    await service.observe((observation(),))
    target = to_neutral_id(CLUSTER)
    valid = context()
    reader.value = context(
        target_ref=target,
        facts=tuple(fact.model_copy(update={"target_ref": target}) for fact in valid.facts),
    )
    assert await service.observe((observation(),)) == 1
    rows = await store.read_states(OBSERVER_PROPOSAL_PREFIX, limit=10)
    assert len(rows) == 1
    assert rows[0]["revision"] == 2
    assert rows[0]["proposal"]["recommended"]["method"] == "gitops"
    assert rows[0]["proposal"]["approval_required"] is True
    assert [item["entry"]["kind"] for item in store.audit_entries] == [
        "observer.deployment.proposed"
    ] * 2
    assert await store.verify_chain()


async def test_stale_discovery_and_foreign_constraints_never_persist() -> None:
    store = InMemoryStateStore()
    service = ObserverDeploymentProposalService(
        store, constraints=Constraints(context()), now=lambda: NOW
    )
    with pytest.raises(ValueError, match="target"):
        await service.observe((observation(),))
    stale = ObserverDeploymentProposalService(
        store, constraints=Constraints(), now=lambda: NOW + timedelta(minutes=10)
    )
    with pytest.raises(ValueError, match="stale"):
        await stale.observe((observation(),))
    assert list(store.audit_entries) == []


@pytest.mark.parametrize("changed", ["discovery", "private_mode"])
async def test_constraint_discovery_binding_cannot_change_on_create_or_read(changed) -> None:
    target = to_neutral_id(CLUSTER)
    valid = context(target_ref=target, facts=())
    reader, store = Constraints(valid), InMemoryStateStore()
    service = ObserverDeploymentProposalService(store, constraints=reader, now=lambda: NOW)
    await service.observe((observation(),))
    reader.value = valid.model_copy(
        update=(
            {"discovery_digest": "sha256:" + "b" * 64}
            if changed == "discovery"
            else {"private_cluster": False}
        )
    )
    with pytest.raises(ValueError, match="discovery"):
        await service.current(target)
    with pytest.raises(ValueError, match="discovery"):
        await service.observe((observation(),))
    assert len(list(store.audit_entries)) == 1


async def test_current_proposal_rejects_expiry_and_older_discovery() -> None:
    store = InMemoryStateStore()
    clock = [NOW]
    service = ObserverDeploymentProposalService(
        store, constraints=Constraints(), now=lambda: clock[0]
    )
    await service.observe((observation(),))
    target = to_neutral_id(CLUSTER)
    assert (await service.current(target)).status == "needs_evidence"
    clock[0] += timedelta(seconds=1)
    with pytest.raises(ValueError, match="backwards"):
        await service.observe(
            (AksPrivateClusterObservation(CLUSTER, NOW - timedelta(seconds=1), DIGEST),)
        )
    clock[0] = NOW + timedelta(minutes=10)
    with pytest.raises(ValueError, match="stale"):
        await service.current(target)


async def test_expired_constraint_context_preserves_last_known_owner() -> None:
    from fdai.delivery.kubernetes_connector_proposals import (
        OBSERVER_CONSTRAINT_PREFIX,
        StateStoreObserverConstraints,
    )
    from fdai_service_contracts.compatibility import canonical_digest

    store = InMemoryStateStore()
    target = to_neutral_id(CLUSTER)
    expired = context(
        target_ref=target,
        facts=(),
        existing_method="existing_host",
        expires_at=NOW + timedelta(seconds=1),
    )
    await store.write_state(
        OBSERVER_CONSTRAINT_PREFIX + canonical_digest({"target_ref": target}),
        {
            "context": expired.model_dump(mode="json"),
            "context_digest": canonical_digest(expired.model_dump(mode="json")),
        },
    )
    service = ObserverDeploymentProposalService(
        store,
        constraints=StateStoreObserverConstraints(store),
        now=lambda: NOW + timedelta(seconds=2),
    )
    await service.observe((observation(),))
    proposal = await service.current(target)
    assert proposal.status == "needs_evidence"
    assert all(
        item.state == "blocked" for item in proposal.candidates if item.method != "existing_host"
    )


async def test_persistence_expiry_during_store_read_is_rejected() -> None:
    clock = [NOW]

    class SlowStore(InMemoryStateStore):
        async def read_state(self, key):
            result = await super().read_state(key)
            clock[0] += timedelta(minutes=10)
            return result

    store = SlowStore()
    service = ObserverDeploymentProposalService(
        store, constraints=Constraints(), now=lambda: clock[0]
    )
    with pytest.raises(ValueError, match="expired"):
        await service.observe((observation(),))
    assert list(store.audit_entries) == []


async def test_concurrent_identical_proposals_keep_one_atomic_audit() -> None:
    import asyncio

    class RacingStore(InMemoryStateStore):
        def __init__(self):
            super().__init__()
            self.reads = 0
            self.ready = asyncio.Event()

        async def read_state(self, key):
            result = await super().read_state(key)
            if key.startswith(OBSERVER_PROPOSAL_PREFIX) and result is None:
                self.reads += 1
                if self.reads == 2:
                    self.ready.set()
                await self.ready.wait()
            return result

    store = RacingStore()
    service = ObserverDeploymentProposalService(store, constraints=Constraints(), now=lambda: NOW)
    results = await asyncio.wait_for(
        asyncio.gather(service.observe((observation(),)), service.observe((observation(),))),
        timeout=2,
    )
    assert sorted(results) == [0, 1]
    assert len(list(store.audit_entries)) == 1
    assert await store.verify_chain()


@pytest.mark.parametrize("field", ["context", "fingerprint", "revision", "extra"])
async def test_corrupt_checkpoint_never_reads_as_a_valid_proposal(field) -> None:
    from fdai_service_contracts.compatibility import canonical_digest

    store = InMemoryStateStore()
    service = ObserverDeploymentProposalService(store, constraints=Constraints(), now=lambda: NOW)
    await service.observe((observation(),))
    target = to_neutral_id(CLUSTER)
    key = OBSERVER_PROPOSAL_PREFIX + canonical_digest({"target_ref": target})
    record = dict(await store.read_state(key))
    if field == "context":
        record[field]["private_cluster"] = False
    elif field == "fingerprint":
        record[field] = DIGEST
    elif field == "revision":
        record[field] = True
    else:
        record[field] = True
    await store.write_state(key, record)
    with pytest.raises(ValueError):
        await service.current(target)


async def test_readback_rejects_changed_constraints() -> None:
    store, reader = InMemoryStateStore(), Constraints()
    service = ObserverDeploymentProposalService(store, constraints=reader, now=lambda: NOW)
    await service.observe((observation(),))
    target = to_neutral_id(CLUSTER)
    reader.value = context(target_ref=target, facts=(), requested_method="run_command")
    with pytest.raises(ValueError, match="constraints changed"):
        await service.current(target)


async def test_removed_constraints_preserve_known_installation_owner() -> None:
    store = InMemoryStateStore()
    target = to_neutral_id(CLUSTER)
    reader = Constraints(
        context(
            target_ref=target,
            facts=(),
            existing_method="existing_host",
            requested_method="existing_host",
        )
    )
    service = ObserverDeploymentProposalService(store, constraints=reader, now=lambda: NOW)
    await service.observe((observation(),))
    reader.value = None
    assert await service.observe((observation(),)) == 0
    proposal = await service.current(target)
    assert proposal.status == "needs_evidence"
    assert all(
        item.state == "blocked" for item in proposal.candidates if item.method != "existing_host"
    )


async def test_projection_publishes_current_or_unavailable_without_core_state_access() -> None:
    from fdai.delivery.kubernetes_connector_projection import publish_observer_proposal
    from fdai_service_contracts.observer_deployment import (
        OBSERVER_PROPOSAL_TOPIC,
        ObserverProposalProjection,
    )

    store, reader = InMemoryStateStore(), Constraints()
    service = ObserverDeploymentProposalService(store, constraints=reader, now=lambda: NOW)
    await service.observe((observation(),))

    class Bus:
        def __init__(self):
            self.records = []

        async def publish(self, topic, key, payload):
            assert topic == OBSERVER_PROPOSAL_TOPIC
            self.records.append(ObserverProposalProjection.model_validate(payload))

    bus = Bus()
    target = to_neutral_id(CLUSTER)
    assert await publish_observer_proposal(
        target_ref=target, service=service, store=store, bus=bus, now=lambda: NOW
    )
    assert bus.records[-1].state == "current"
    assert bus.records[-1].expires_at == NOW + timedelta(minutes=1)
    reader.value = context(target_ref=target, facts=(), requested_method="run_command")
    assert await publish_observer_proposal(
        target_ref=target,
        service=service,
        store=store,
        bus=bus,
        now=lambda: NOW + timedelta(seconds=1),
    )
    assert bus.records[-1].state == "unavailable"
    assert bus.records[-1].proposal is None


async def test_subscription_discovery_creates_proposal_when_credentials_are_unavailable(
    monkeypatch,
) -> None:
    from datetime import UTC, datetime

    import httpx
    from fdai.delivery import inventory_sync_cli as cli
    from fdai.delivery.aks_subscription_discovery import AksSubscriptionDiscoveryResult
    from fdai.delivery.inventory_job_config import InventoryJobConfig

    store = InMemoryStateStore()
    current = AksPrivateClusterObservation(CLUSTER, datetime.now(UTC), DIGEST)

    class Discovery:
        def __init__(self, **kwargs):
            pass

        async def discover(self, subscription_id):
            return AksSubscriptionDiscoveryResult((), (), (current,))

    monkeypatch.setattr(cli, "AzureAksSubscriptionBindingDiscovery", Discovery)
    monkeypatch.setattr(cli, "PostgresStateStore", lambda **kwargs: store)
    from fdai.delivery import kubernetes_connector_observed as observation_runtime

    evidence_checks = []

    async def not_observing(target):
        evidence_checks.append(target)
        return False

    monkeypatch.setattr(
        observation_runtime, "build_observer_evidence", lambda *args, **kwargs: not_observing
    )
    from fdai.delivery import kubernetes_connector_projection as publication

    publications = []

    async def publish(**kwargs):
        publications.append(kwargs["targets"])

    monkeypatch.setattr(publication, "publish_discovered_proposals", publish)
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://localhost/example",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000001",
            "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "1",
        }
    )
    async with httpx.AsyncClient() as client:
        resolved = await cli._discover_subscription_kubernetes_bindings(
            config, identity=object(), http_client=client
        )
    assert resolved.kubernetes_bindings == ()
    rows = await store.read_states(OBSERVER_PROPOSAL_PREFIX, limit=10)
    assert len(rows) == 1
    assert rows[0]["proposal"]["status"] == "needs_evidence"
    assert publications == [(to_neutral_id(CLUSTER),)]
    assert evidence_checks == [to_neutral_id(CLUSTER)]
