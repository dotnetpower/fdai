"""End-to-end pantheon chain for agent-owned document ingestion."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.muninn import Muninn
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var


def test_inspected_document_reaches_muninn_without_thor_action() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus)
    forseti = Forseti(bus=bus)
    saga = Saga()
    saga.bind_bus(bus)
    muninn = Muninn()
    muninn.bind_bus(bus)
    thor = Thor(bus=bus)

    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.audit-entry", "Muninn", muninn.on_typed_message)

    asyncio.run(
        bus.publish(
            "Huginn",
            "object.event",
            {
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "event_type": "document.inspected",
                "correlation_id": "upload-1",
                "idempotency_key": "document.inspected:version-1",
                "resource_id": "doc-1",
                "resource_type": "document",
                "document_id": "doc-1",
                "record": {
                    "upload_id": "upload-1",
                    "version_id": "version-1",
                    "malware_verdict": "clean",
                    "protection_state": "none",
                    "failure_code": "",
                },
            },
        )
    )

    assert len(bus.messages_on("object.anomaly")) == 1
    assert len(bus.messages_on("object.verdict")) == 1
    assert len(bus.messages_on("object.audit-entry")) == 1
    commands = bus.messages_on("object.context-index")
    assert len(commands) == 1
    assert commands[0].payload["producer_principal"] == "Muninn"
    assert commands[0].payload["command"] == "index"
    assert bus.messages_on("object.action-run") == []
    assert thor.action_runs == {}


def test_blocked_document_never_reaches_muninn_or_thor() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus)
    forseti = Forseti(bus=bus)
    saga = Saga()
    saga.bind_bus(bus)
    muninn = Muninn()
    muninn.bind_bus(bus)
    thor = Thor(bus=bus)

    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.audit-entry", "Muninn", muninn.on_typed_message)

    asyncio.run(
        bus.publish(
            "Huginn",
            "object.event",
            {
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "event_type": "document.inspected",
                "correlation_id": "upload-2",
                "idempotency_key": "document.inspected:version-2",
                "resource_id": "doc-2",
                "document_id": "doc-2",
                "record": {
                    "upload_id": "upload-2",
                    "malware_verdict": "infected",
                    "protection_state": "unknown",
                    "failure_code": "malware_detected",
                },
            },
        )
    )

    verdict = bus.messages_on("object.verdict")[0].payload
    assert verdict["decision"] == "hold"
    assert verdict["reason"] == "malware_detected"
    assert bus.messages_on("object.context-index") == []
    assert bus.messages_on("object.action-run") == []


def test_authoritative_document_waits_for_var_before_muninn() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus)
    forseti = Forseti(bus=bus)
    saga = Saga()
    saga.bind_bus(bus)
    var = Var(bus=bus)
    muninn = Muninn()
    muninn.bind_bus(bus)
    thor = Thor(bus=bus)

    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.audit-entry", "Var", var.on_typed_message)
    bus.subscribe("object.audit-entry", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.approval", "Saga", saga.on_typed_message)
    bus.subscribe("object.approval", "Thor", thor.on_typed_message)

    asyncio.run(
        bus.publish(
            "Huginn",
            "object.event",
            {
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "event_type": "document.inspected",
                "correlation_id": "upload-hil",
                "idempotency_key": "document.inspected:version-hil",
                "resource_id": "doc-hil",
                "document_id": "doc-hil",
                "record": {
                    "upload_id": "upload-hil",
                    "malware_verdict": "clean",
                    "protection_state": "none",
                    "failure_code": "",
                    "purposes": ["handover_bootstrap"],
                    "uploader_id": "uploader@example.com",
                },
            },
        )
    )

    assert bus.messages_on("object.verdict")[0].payload["decision"] == "hil"
    assert len(var.pending_tickets()) == 1
    assert bus.messages_on("object.context-index") == []

    asyncio.run(
        var.decide(
            "upload-hil",
            approver="reviewer@example.com",
            decision="approve",
        )
    )

    commands = bus.messages_on("object.context-index")
    assert len(commands) == 1
    assert commands[0].payload["producer_principal"] == "Muninn"
    assert bus.messages_on("object.action-run") == []
    assert thor.action_runs == {}
