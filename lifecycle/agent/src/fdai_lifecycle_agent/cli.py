"""``fdai-lifecycle-agent`` command line. Lifecycle I0 offers only ``poll-once``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TypedDict, cast, get_args

from fdai_deployment_cli.lifecycle_plan import CapabilityMode, LifecycleEffectEnvelope

from fdai_lifecycle_agent.agent import AgentDependencies, AgentSettings, HubTrust, LifecycleAgent
from fdai_lifecycle_agent.dry_run import load_current_state
from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError
from fdai_lifecycle_agent.inputs import DirectoryArtifactStore
from fdai_lifecycle_agent.signatures import (
    Ed25519ArtifactVerifier,
    Ed25519HubKeyring,
    load_ed25519_public_key,
)
from fdai_lifecycle_agent.state import AgentStateError, LocalStateStore
from fdai_lifecycle_agent.strict_json import load_json, read_limited

LOCAL_POLICY_SCHEMA = "fdai.lifecycle-local-policy.v1"
_LOCAL_POLICY_KEYS = frozenset(
    {
        "schema",
        "entity_ids",
        "regions",
        "capability_modes",
        "destructive_allowed",
        "max_duration_minutes",
        "entity_components",
    }
)
_MAX_LOCAL_POLICY_BYTES = 64 * 1024
_EXIT_OK = 0
_EXIT_FAILED = 1
_EXIT_CONFIGURATION = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai-lifecycle-agent",
        description="Hub-managed lifecycle agent (Lifecycle I0: dry-run only, never applies).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    poll = commands.add_parser(
        "poll-once", help="Fetch one Plan, admit it, dry-run it, and report the result."
    )
    poll.add_argument("--hub-url", required=True, help="Hub base URL (http only on loopback).")
    poll.add_argument("--installation-id", required=True, help="This installation's Plan audience.")
    poll.add_argument(
        "--state-dir", required=True, type=Path, help="Durable agent state directory."
    )
    poll.add_argument("--hub-public-key", required=True, type=Path, help="Hub Ed25519 PEM key.")
    poll.add_argument("--hub-key-id", required=True, help="Key id the Hub uses in Plans.")
    poll.add_argument("--hub-key-epoch", required=True, type=int, help="Current Hub key epoch.")
    poll.add_argument(
        "--revoked-hub-key-id", action="append", default=[], help="Revoked Hub key id."
    )
    poll.add_argument("--fencing-generation", required=True, type=int)
    poll.add_argument("--release-public-key", required=True, type=Path)
    poll.add_argument("--configuration-public-key", required=True, type=Path)
    poll.add_argument(
        "--inputs-dir",
        required=True,
        type=Path,
        help="Directory with releases/ and configurations/ signed documents.",
    )
    poll.add_argument("--current-state", required=True, type=Path, help="Current-state fixture.")
    poll.add_argument(
        "--local-policy",
        required=True,
        type=Path,
        help="Local hard policy: maximum effect envelope and the components each Entity runs.",
    )
    poll.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _connect_hub(url: str, timeout_seconds: float) -> HttpHubClient:
    return HttpHubClient(url, timeout_seconds=timeout_seconds)


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] = _utc_now,
    connect_hub: Callable[[str, float], HttpHubClient] = _connect_hub,
) -> int:
    """Run the command. ``clock`` and ``connect_hub`` are seams for tests; defaults are real."""

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    # Keep stderr to the agent's structured events; httpx logs every request URL at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = build_parser().parse_args(argv)
    try:
        settings = AgentSettings(
            installation_id=arguments.installation_id,
            trust=HubTrust(
                hub_key_epochs={arguments.hub_key_id: arguments.hub_key_epoch},
                revoked_hub_key_ids=frozenset(arguments.revoked_hub_key_id),
                current_hub_key_epoch=arguments.hub_key_epoch,
                fencing_generation=arguments.fencing_generation,
            ),
            **load_local_policy(arguments.local_policy),
        )
        hub_keyring = Ed25519HubKeyring(
            {arguments.hub_key_id: load_ed25519_public_key(arguments.hub_public_key)}
        )
        release_verifier = Ed25519ArtifactVerifier.from_file(arguments.release_public_key)
        configuration_verifier = Ed25519ArtifactVerifier.from_file(
            arguments.configuration_public_key
        )
        # Fail fast as a configuration error; each poll then reads the current state again.
        load_current_state(arguments.current_state)
        hub = connect_hub(arguments.hub_url, arguments.timeout_seconds)
    except ValueError as error:
        print(f"fdai-lifecycle-agent: configuration error: {error}", file=sys.stderr)
        return _EXIT_CONFIGURATION
    with hub:
        dependencies = AgentDependencies(
            hub=hub,
            state_store=LocalStateStore(arguments.state_dir),
            artifact_store=DirectoryArtifactStore(arguments.inputs_dir),
            verify_plan_signature=hub_keyring,
            verify_release_signature=release_verifier,
            verify_configuration_signature=configuration_verifier,
            read_current_state=partial(load_current_state, arguments.current_state),
            clock=clock,
        )
        try:
            result = LifecycleAgent(settings, dependencies).poll_once()
        except (HubProtocolError, AgentStateError) as error:
            print(f"fdai-lifecycle-agent: poll failed: {error}", file=sys.stderr)
            return _EXIT_FAILED
    print(json.dumps(result.to_json(), sort_keys=True))
    if result.outcome == "malformed-plan":
        return _EXIT_FAILED
    if result.outcome in {"dry-run-admitted", "rejected"} and not result.reported:
        return _EXIT_FAILED
    return _EXIT_OK


class LocalPolicy(TypedDict):
    maximum_envelope: LifecycleEffectEnvelope
    entity_components: dict[str, frozenset[str]]


def load_local_policy(path: Path) -> LocalPolicy:
    """Load local hard policy. A Hub Plan and the signed inputs can only narrow its envelope."""

    try:
        raw = read_limited(path, limit=_MAX_LOCAL_POLICY_BYTES, label="local policy")
    except OSError as error:
        raise ValueError(f"local policy is unreadable: {type(error).__name__}") from error
    document = load_json(raw, label="local policy")
    if not isinstance(document, dict) or set(document) != _LOCAL_POLICY_KEYS:
        raise ValueError("local policy fields are invalid")
    if document["schema"] != LOCAL_POLICY_SCHEMA:
        raise ValueError("local policy schema is unsupported")
    modes = document["capability_modes"]
    if not isinstance(modes, dict) or not set(modes.values()) <= set(get_args(CapabilityMode)):
        raise ValueError("local policy capability mode is unsupported")
    components = document["entity_components"]
    if not isinstance(components, dict):
        raise ValueError("local policy entity_components MUST be an object")
    try:
        envelope = LifecycleEffectEnvelope(
            entity_ids=_strings(document["entity_ids"], "entity_ids"),
            regions=_strings(document["regions"], "regions"),
            capability_modes=cast(dict[str, CapabilityMode], modes),
            destructive_allowed=document["destructive_allowed"],
            max_duration_minutes=document["max_duration_minutes"],
        )
    except TypeError as error:
        raise ValueError(f"local policy is invalid: {error}") from error
    return LocalPolicy(
        maximum_envelope=envelope,
        entity_components={
            str(entity_id): _strings(names, "entity_components")
            for entity_id, names in components.items()
        },
    )


def _strings(value: object, label: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"local policy {label} MUST be a list of strings")
    return frozenset(value)


if __name__ == "__main__":
    raise SystemExit(main())
