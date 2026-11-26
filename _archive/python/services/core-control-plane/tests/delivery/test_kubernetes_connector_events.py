"""Lifecycle Event history crosses the gateway with one durable writer and no observer database."""

import json
import ssl
from datetime import timedelta

import pytest
from aiohttp import web
from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleBatch,
    KubernetesLifecycleCoverageSegment,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_connector_events import (
    ConnectorEventError,
    ConnectorEventTransport,
    LifecycleEventInbox,
    decode_batch,
    decode_cursor,
    encode_batch,
    encode_cursor,
)
from fdai.delivery.kubernetes_connector_gateway import create_connector_gateway
from fdai.delivery.kubernetes_connector_runtime import (
    ConnectorRuntimeConfig,
    observe_events_once,
)
from fdai.delivery.kubernetes_connector_transport import ConnectorTransportConfig

from .test_kubernetes_connector import registration
from .test_kubernetes_connector_gateway import certificates
from .test_kubernetes_connector_spool import NOW

CLUSTER = "cluster-example"
PRINCIPAL_HOLDER = "holder-example"


def observation(index=1, **changes):
    values = {
        "observation_id": f"sha256:{index:064x}",
        "cluster_ref": CLUSTER,
        "event_uid": f"event-{index}",
        "object_uid": "pod-uid",
        "object_kind": "Pod",
        "namespace": "example",
        "owner_uid": None,
        "reason": "Started",
        "event_type": "Normal",
        "lifecycle_kind": "started",
        "action": "added",
        "occurred_at": NOW,
        "recorded_at": NOW,
        "source_revision": "10",
        "occurrence_count": 1,
        "evidence_ref": f"kubernetes-lifecycle:{index}",
        **changes,
    }
    return KubernetesLifecycleObservation(**values)


def batch(*, sequence=0, observations=(), resume="200", segment=None, limitation=None):
    return KubernetesLifecycleBatch(
        cluster_ref=CLUSTER,
        expected_sequence=sequence,
        next_resume_token=resume,
        coverage_started_at=NOW,
        coverage_through_at=NOW + timedelta(seconds=30),
        observations=tuple(observations),
        limitation=limitation,
        incomplete_coverage_segment=segment,
    )


def test_a_batch_round_trips_through_the_domain_validators() -> None:
    segment = KubernetesLifecycleCoverageSegment(
        cluster_ref=CLUSTER,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=10),
        limitation="cursor_expired",
    )
    original = batch(
        observations=[observation(1), observation(2, namespace=None, owner_uid="owner")],
        segment=segment,
        limitation="cursor_expired",
    )
    assert decode_batch(encode_batch(original), cluster_ref=CLUSTER) == original


def test_a_cursor_round_trips() -> None:
    cursor = KubernetesLifecycleCursor(CLUSTER, 3, "300", NOW, NOW, NOW, None)
    assert decode_cursor(encode_cursor(cursor)) == cursor


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(cluster_ref="another-cluster"),
        lambda v: v.update(extra=1),
        lambda v: v.pop("limitation"),
        lambda v: v.update(expected_sequence="1"),
        lambda v: v.update(expected_sequence=True),
        lambda v: v.update(coverage_through_at="2026-01-01T00:00:00"),
        lambda v: v["observations"].append({"x": 1}),
        lambda v: v["observations"][0].update(message="leaked text"),
        lambda v: v["observations"][0].update(occurrence_count=0),
        lambda v: v["observations"][0].update(occurrence_count="1"),
        lambda v: v["observations"][0].update(cluster_ref="x"),
        lambda v: v.update(observations=v["observations"] * 300),
        lambda v: v.update(incomplete_coverage_segment={"started_at": "x"}),
    ],
)
def test_a_malformed_or_widened_batch_is_rejected(mutate) -> None:
    value = json.loads(encode_batch(batch(observations=[observation(1)])))
    mutate(value)
    with pytest.raises(ConnectorEventError):
        decode_batch(json.dumps(value).encode(), cluster_ref=CLUSTER)


def test_duplicate_fields_and_oversize_content_are_rejected() -> None:
    with pytest.raises(ConnectorEventError):
        decode_batch(b'{"cluster_ref": "a", "cluster_ref": "a"}', cluster_ref="a")
    with pytest.raises(ConnectorEventError, match="byte limit"):
        decode_batch(b" " * 2_097_153, cluster_ref=CLUSTER)
    with pytest.raises(ConnectorEventError):
        decode_cursor(b'{"sequence": 1}')


class FakeStore:
    """Model the lease and sequence contract of the durable lifecycle store."""

    def __init__(self):
        self.sequence, self.holder, self.expires, self.appended = 0, None, None, []
        self.token = None

    async def acquire(self, *, cluster_ref, holder, now, lease_until):
        if self.holder not in (None, holder) and self.expires > now:
            return None
        self.holder, self.expires = holder, lease_until
        return KubernetesLifecycleCursor(
            cluster_ref, self.sequence, self.token, NOW, NOW, NOW, None
        )

    async def append(self, batch, *, holder, now):
        if holder != self.holder or batch.expected_sequence != self.sequence:
            return False
        self.sequence += 1
        self.token = batch.next_resume_token
        self.holder = None
        self.appended.append(batch)
        return True


class Registrations:
    def __init__(self, principal, capabilities=("inventory.snapshot", "lifecycle.events")):
        self.current = registration().model_copy(
            update={"principal_ref": principal, "capabilities": list(capabilities)}
        )
        self.current.scope.cluster_ref  # noqa: B018 - the scope is the enrolled cluster

    async def read(self, principal_ref):
        return self.current if self.current.principal_ref == principal_ref else None


def scoped(principal, capabilities=("inventory.snapshot", "lifecycle.events")):
    registrations = Registrations(principal, capabilities)
    registrations.current = registrations.current.model_copy(
        update={"scope": registrations.current.scope.model_copy(update={"cluster_ref": CLUSTER})}
    )
    return registrations


async def test_the_inbox_requires_the_capability_and_the_expected_sequence() -> None:
    store = FakeStore()
    inbox = LifecycleEventInbox(store, registrations=scoped("p"), now=lambda: NOW)
    cursor = await inbox.cursor("p")
    assert cursor.sequence == 0
    acknowledgment = await inbox.accept("p", encode_batch(batch(observations=[observation(1)])))
    assert (acknowledgment["status"], acknowledgment["sequence"]) == ("accepted", 1)
    await inbox.cursor("p")
    with pytest.raises(ConnectorEventError, match="not admitted"):
        await inbox.accept("p", encode_batch(batch(sequence=0)))
    without = LifecycleEventInbox(
        store, registrations=scoped("p", ("inventory.snapshot",)), now=lambda: NOW
    )
    with pytest.raises(ValueError):
        await without.cursor("p")
    with pytest.raises(ConnectorEventError, match="enrollment is unavailable"):
        await inbox.cursor("someone-else")


async def test_a_second_collector_cannot_take_a_live_lease() -> None:
    store = FakeStore()
    first = LifecycleEventInbox(store, registrations=scoped("a"), now=lambda: NOW)
    second = LifecycleEventInbox(store, registrations=scoped("b"), now=lambda: NOW)
    await first.cursor("a")
    with pytest.raises(ConnectorEventError, match="holds the lifecycle lease"):
        await second.cursor("b")


async def serve(tmp_path, store, capabilities=("inventory.snapshot", "lifecycle.events")):
    (server_context, _), (client_context, principal) = certificates(tmp_path)
    registrations = scoped(principal, capabilities)
    application = create_connector_gateway(
        inbox=None,  # type: ignore[arg-type] - the events routes never touch the snapshot inbox
        registrations=registrations,
        now=lambda: NOW,
        events=LifecycleEventInbox(store, registrations=registrations, now=lambda: NOW),
    )
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context).start()
    port = runner.addresses[0][1]
    sender = ConnectorEventTransport(
        ConnectorTransportConfig(f"https://127.0.0.1:{port}", "mtls"), tls_context=client_context
    )
    return runner, sender, principal


async def test_real_mtls_cursor_and_batch_with_one_durable_writer(tmp_path) -> None:
    store = FakeStore()
    runner, sender, _ = await serve(tmp_path, store)
    try:
        cursor = await sender.cursor()
        assert (cursor.cluster_ref, cursor.sequence) == (CLUSTER, 0)
        sent = batch(observations=[observation(1), observation(2)])
        acknowledgment = await sender.send(sent)
        assert acknowledgment["sequence"] == 1 and acknowledgment["observations"] == 2
        assert store.appended == [sent]
        assert (await sender.cursor()).sequence == 1
        with pytest.raises(ConnectorEventError):
            await sender.send(sent)
        assert len(store.appended) == 1
    finally:
        await sender.aclose()
        await runner.cleanup()


async def test_the_routes_refuse_an_observer_without_the_capability(tmp_path) -> None:
    runner, sender, _ = await serve(tmp_path, FakeStore(), ("inventory.snapshot",))
    try:
        with pytest.raises(ConnectorEventError):
            await sender.cursor()
    finally:
        await sender.aclose()
        await runner.cleanup()


async def test_the_events_routes_do_not_exist_unless_the_gateway_serves_them(tmp_path) -> None:
    (server_context, _), (client_context, principal) = certificates(tmp_path)
    registrations = scoped(principal)
    application = create_connector_gateway(
        inbox=None,  # type: ignore[arg-type]
        registrations=registrations,
        now=lambda: NOW,
    )
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context).start()
    sender = ConnectorEventTransport(
        ConnectorTransportConfig(f"https://127.0.0.1:{runner.addresses[0][1]}", "mtls"),
        tls_context=client_context,
    )
    try:
        with pytest.raises(ConnectorEventError):
            await sender.cursor()
    finally:
        await sender.aclose()
        await runner.cleanup()


def test_the_transport_requires_verified_tls() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="verification"):
        ConnectorEventTransport(
            ConnectorTransportConfig("https://gateway.example:8443", "mtls"), tls_context=context
        )


def watch_line(index):
    stamp = (NOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps(
        {
            "type": "ADDED",
            "object": {
                "metadata": {"uid": f"event-{index}", "resourceVersion": str(100 + index)},
                "involvedObject": {"uid": "pod-uid", "kind": "Pod", "namespace": "example"},
                "reason": "Started",
                "type": "Normal",
                "lastTimestamp": stamp,
                "message": "free text that must never be forwarded",
            },
        }
    )


async def test_the_observer_cycle_collects_one_window_and_sends_it_without_message_text(
    tmp_path,
) -> None:
    store = FakeStore()
    runner, _, principal = await serve(tmp_path, store)
    gateway_port = runner.addresses[0][1]

    async def api(request):
        if request.query.get("watch") == "true":
            lines = [watch_line(1), watch_line(2)]
            return web.Response(text="\n".join(lines) + "\n")
        return web.json_response({"metadata": {"resourceVersion": "100"}})

    api_app = web.Application()
    api_app.router.add_get("/api/v1/events", api)
    api_runner = web.AppRunner(api_app, access_log=None)
    await api_runner.setup()
    api_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    api_tls.load_cert_chain(str(tmp_path / "server.pem"), str(tmp_path / "server.key"))
    await web.TCPSite(api_runner, "127.0.0.1", 0, ssl_context=api_tls).start()
    api_port = api_runner.addresses[0][1]

    registrations = scoped(principal)
    (tmp_path / "registrations.json").write_text(
        json.dumps([registrations.current.model_dump(mode="json")])
    )
    (tmp_path / "registrations.json").chmod(0o600)
    (tmp_path / "token").write_text("example-token")
    (tmp_path / "token").chmod(0o600)
    (tmp_path / "client.key").chmod(0o600)
    config = ConnectorRuntimeConfig(
        role="observer",
        registration_path=tmp_path / "registrations.json",
        tls_ca_path=tmp_path / "ca.pem",
        tls_certificate_path=tmp_path / "client.pem",
        tls_key_path=tmp_path / "client.key",
        gateway_origin=f"https://127.0.0.1:{gateway_port}",
        observer_principal_ref=principal,
        stream_id="example",
        producer_revision="sha256:" + "a" * 64,
        spool_directory=tmp_path / "spool",
        api_server=f"https://127.0.0.1:{api_port}",
        api_ca_path=tmp_path / "ca.pem",
        api_token_path=tmp_path / "token",
    )
    import fdai.delivery.kubernetes_lifecycle_collection as collection

    original = collection._WATCH_SECONDS
    collection._WATCH_SECONDS = 1
    try:
        seed = await observe_events_once(config, now=lambda: NOW)
        assert (seed["status"], seed["observations"]) == ("accepted", 0)
        stored = store.appended[0]
        assert stored.next_resume_token == "100" and stored.expected_sequence == 0
        # The seed checkpoint advances the durable cursor, so the next window resumes from it.
        store.appended.clear()
        window = await observe_events_once(config, now=lambda: NOW)
    finally:
        collection._WATCH_SECONDS = original
        await runner.cleanup()
        await api_runner.cleanup()
    assert (window["status"], window["observations"], window["sequence"]) == ("accepted", 2, 2)
    assert all(
        "free text" not in json.dumps(encode_batch(item).decode()) for item in store.appended
    )
    assert {item.event_uid for item in store.appended[0].observations} == {"event-1", "event-2"}


async def test_an_observer_without_the_capability_reports_it_and_does_nothing(tmp_path) -> None:
    _, (_, principal) = certificates(tmp_path)
    registrations = scoped(principal, ("inventory.snapshot",))
    (tmp_path / "registrations.json").write_text(
        json.dumps([registrations.current.model_dump(mode="json")])
    )
    (tmp_path / "registrations.json").chmod(0o600)
    (tmp_path / "client.key").chmod(0o600)
    config = ConnectorRuntimeConfig(
        role="observer",
        registration_path=tmp_path / "registrations.json",
        tls_ca_path=tmp_path / "ca.pem",
        tls_certificate_path=tmp_path / "client.pem",
        tls_key_path=tmp_path / "client.key",
        gateway_origin="https://127.0.0.1:9",
        observer_principal_ref=principal,
        stream_id="example",
        producer_revision="sha256:" + "a" * 64,
        spool_directory=tmp_path / "spool",
        api_server="https://127.0.0.1:9",
        api_ca_path=tmp_path / "ca.pem",
        api_token_path=tmp_path / "token",
    )
    assert await observe_events_once(config, now=lambda: NOW) == {
        "status": "not_enrolled",
        "capability": "lifecycle.events",
    }
