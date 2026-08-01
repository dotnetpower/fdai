"""Idempotently reconcile the deployment-owned Foundry web-search agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_DEFINITION_DIGEST_KEY = "fdai_definition_sha256"
_AI_RESOURCE = "https://ai.azure.com"
_PROBE_QUERY = "Find the current Microsoft Learn page for Azure OpenAI web search."

JsonRequest = Callable[[str, str, str, Mapping[str, Any] | None], Mapping[str, Any]]
TokenProvider = Callable[[], str]


@dataclass(frozen=True, slots=True)
class FoundryWebSearchAgentSpec:
    project_endpoint: str
    agent_name: str
    model_deployment: str
    allowed_domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.project_endpoint.startswith("https://")
            or "/api/projects/" not in self.project_endpoint
            or "?" in self.project_endpoint
            or "#" in self.project_endpoint
        ):
            raise ValueError("project_endpoint MUST be a Foundry project HTTPS endpoint")
        if (
            not self.agent_name
            or len(self.agent_name) > 63
            or not self.agent_name[0].isalnum()
            or not self.agent_name[-1].isalnum()
            or any(not (character.isalnum() or character == "-") for character in self.agent_name)
        ):
            raise ValueError("agent_name MUST be a valid Foundry agent name")
        if not self.model_deployment.strip():
            raise ValueError("model_deployment MUST be non-empty")
        normalized = tuple(
            dict.fromkeys(domain.strip().casefold().rstrip(".") for domain in self.allowed_domains)
        )
        if (
            not normalized
            or normalized != self.allowed_domains
            or any(not _valid_domain(domain) for domain in normalized)
        ):
            raise ValueError("allowed_domains MUST be non-empty, normalized, and unique")

    def definition(self) -> dict[str, Any]:
        return {
            "kind": "prompt",
            "model": self.model_deployment,
            "instructions": (
                "Search only the configured public domains. Return concise evidence with "
                "source citations and do not infer facts that the retrieved pages do not support."
            ),
            "tools": [
                {
                    "type": "web_search",
                    "filters": {"allowed_domains": list(self.allowed_domains)},
                }
            ],
        }

    def definition_digest(self) -> str:
        canonical = json.dumps(
            self.definition(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class FoundryAgentReconcileResult:
    agent_name: str
    agent_version: str
    model_deployment: str
    definition_sha256: str
    changed: bool
    readiness: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "agent_name": self.agent_name,
                "agent_version": self.agent_version,
                "model_deployment": self.model_deployment,
                "definition_sha256": self.definition_sha256,
                "changed": self.changed,
                "readiness": self.readiness,
            },
            sort_keys=True,
        )


def reconcile_foundry_web_search_agent(
    spec: FoundryWebSearchAgentSpec,
    *,
    request_json: JsonRequest | None = None,
    token_provider: TokenProvider | None = None,
) -> FoundryAgentReconcileResult:
    request = request_json or _request_json
    get_token = token_provider or _azure_cli_token
    token = get_token()
    versions_url = (
        f"{spec.project_endpoint.rstrip('/')}/agents/{quote(spec.agent_name)}/versions"
        "?api-version=v1&limit=1&order=desc"
    )
    versions_payload = request("GET", versions_url, token, None)
    latest = _latest_version(versions_payload)
    digest = spec.definition_digest()
    latest_metadata = latest.get("metadata") if isinstance(latest, Mapping) else None
    changed = not (
        isinstance(latest_metadata, Mapping)
        and latest_metadata.get(_DEFINITION_DIGEST_KEY) == digest
    )
    if changed:
        latest = request(
            "POST",
            versions_url,
            token,
            {
                "description": "FDAI managed public web-search agent",
                "definition": spec.definition(),
                "metadata": {
                    _DEFINITION_DIGEST_KEY: digest,
                    "fdai_managed": "true",
                },
            },
        )
    version = str(latest.get("version") or latest.get("agent_version") or "")
    if not version:
        raise RuntimeError("Foundry agent version response is missing version")
    probe = request(
        "POST",
        f"{spec.project_endpoint.rstrip('/')}/openai/v1/responses",
        token,
        {
            "agent_reference": {"name": spec.agent_name, "type": "agent_reference"},
            "tool_choice": "required",
            "include": ["web_search_call.action.sources"],
            "input": _PROBE_QUERY,
        },
    )
    if not _contains_web_search_call(probe):
        raise RuntimeError("Foundry agent readiness probe did not execute web search")
    return FoundryAgentReconcileResult(
        agent_name=spec.agent_name,
        agent_version=version,
        model_deployment=spec.model_deployment,
        definition_sha256=digest,
        changed=changed,
        readiness="ready",
    )


def _latest_version(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    values = payload.get("data")
    if not isinstance(values, list) or not values:
        return {}
    candidates = [item for item in values if isinstance(item, Mapping)]
    if not candidates:
        return {}
    return max(candidates, key=lambda item: _version_key(item.get("version")))


def _version_key(value: object) -> tuple[int, str]:
    text = str(value or "")
    return (int(text), text) if text.isdigit() else (-1, text)


def _contains_web_search_call(payload: Mapping[str, Any]) -> bool:
    output = payload.get("output")
    return isinstance(output, list) and any(
        isinstance(item, Mapping) and item.get("type") == "web_search_call" for item in output
    )


def _valid_domain(domain: str) -> bool:
    if len(domain) > 253 or "." not in domain:
        return False
    return all(
        bool(label)
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in domain.split(".")
    )


def _azure_cli_token() -> str:
    executable = shutil.which("az")
    if executable is None:
        raise RuntimeError("Azure CLI is required to reconcile the Foundry agent")
    process = subprocess.run(  # noqa: S603 - fixed Azure CLI argument vector
        [
            executable,
            "account",
            "get-access-token",
            "--resource",
            _AI_RESOURCE,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    token = process.stdout.strip()
    if not token:
        raise RuntimeError("Azure CLI returned an empty Foundry access token")
    return token


def _request_json(
    method: str,
    url: str,
    token: str,
    payload: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(  # noqa: S310 - URL descends from validated HTTPS project endpoint
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=65) as response:  # noqa: S310 - validated HTTPS URL
            decoded = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Foundry agent API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Foundry agent API is unreachable") from exc
    if not isinstance(decoded, Mapping):
        raise RuntimeError("Foundry agent API returned an invalid JSON envelope")
    return decoded


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--model-deployment", required=True)
    parser.add_argument("--allowed-domain", action="append", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    spec = FoundryWebSearchAgentSpec(
        project_endpoint=args.project_endpoint,
        agent_name=args.agent_name,
        model_deployment=args.model_deployment,
        allowed_domains=tuple(args.allowed_domain),
    )
    print(reconcile_foundry_web_search_agent(spec).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
