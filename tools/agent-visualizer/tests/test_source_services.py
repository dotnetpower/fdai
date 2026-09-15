"""Adapter source metadata remains static, explicit, and free of runtime execution."""

# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from source_index import SourceIndex  # noqa: E402
from source_services import service_group, service_metadata  # noqa: E402


def test_groups_do_not_reassign_agents_or_include_model_provisioning() -> None:
    assert service_group("fdai.agents.bragi") is None
    assert service_group("fdai.delivery.azure.llm.resolver_queries") is None
    assert service_group("fdai.delivery.azure.llm.adaptive_answer") == "azure-openai"
    assert service_group("fdai_operator_service.streaming.live_stream") == "channels"


def test_missing_source_entries_fail_instead_of_fabricating_adapter_nodes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Service entry definition is missing"):
        service_metadata(SourceIndex(tmp_path, []))


def test_ports_match_concrete_source_definitions_without_importing_them(tmp_path: Path) -> None:
    modules = {
        "fdai.delivery.azure.arg_query": (
            "class AzureArgQueryFactory:\n def _fetch_all_pages(self): pass\n"
        ),
        "fdai_operator_service.adapters.local_narrator": (
            "class LocalAzureNarratorAdapters:\n async def _stream_answer(self): pass\n"
        ),
        "fdai_operator_service.streaming.live_stream": "async def _live_chunks(): pass\n",
        "fdai.delivery.notifications.teams": (
            "class TeamsWebhookChannel:\n async def send(self): pass\n"
        ),
        "fdai.delivery.notifications.slack": (
            "class SlackWebhookChannel:\n async def send(self): pass\n"
        ),
    }
    paths = []
    for name, body in modules.items():
        path = tmp_path / "services/example/src" / f"{name.replace('.', '/')}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raise RuntimeError('Do not import')\n" + body, encoding="utf-8")
        paths.append(path)
    index = SourceIndex(tmp_path, paths)
    services = service_metadata(index)
    assert len(services) == 3
    ports = {port["id"]: port for service in services for port in service["ports"]}
    assert ports["console"]["mode"] == "stream"
    assert ports["teams"]["mode"] == ports["slack"]["mode"] == "message"
    assert all(port["function_id"] in index.functions for port in ports.values())
