"""Optional MySQL and Azure OpenAI substrate bindings for catalog chaos runs.

The `vm` and pod substrate comes from required `FDAI_ENFORCE_*` variables. The
`db` and `llm_endpoint` scenarios need more: a database connection factory and a
live model request function, plus the canonical ARM identity each injector
declares as its mutation scope.

Those dependencies are optional on purpose. A substrate without a MySQL server or
a model deployment still runs the pod and VM scenarios, and the affected catalog
entries keep refusing with `refused_target_type` instead of failing mid-run. So
each binding group is produced only when its complete environment is present;
a partial group is treated as absent rather than half-bound.

The database password is never read here. Only the file path is captured, and the
file is read inside the connection factory at connect time, so the secret never
enters the context mapping, a log line, or a report.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_MYSQL_ENV = ("FDAI_ENFORCE_MYSQL_HOST", "FDAI_ENFORCE_MYSQL_USER", "FDAI_ENFORCE_MYSQL_SERVER")
_MYSQL_SECRET_ENV = "FDAI_ENFORCE_MYSQL_PW_FILE"  # noqa: S105 - variable name pointing at a file, not a secret
_AOAI_ENV = (
    "FDAI_ENFORCE_AOAI_ENDPOINT",
    "FDAI_ENFORCE_AOAI_DEPLOYMENT",
    "FDAI_ENFORCE_AOAI_RESOURCE_ID",
)
_AOAI_SCOPE = "https://cognitiveservices.azure.com/.default"
_LOAD_PROMPT = "Reply with a long lorem ipsum paragraph."
_CONNECT_TIMEOUT_SECONDS = 15


def _present(env: Mapping[str, str], names: tuple[str, ...]) -> bool:
    return all(env.get(name, "").strip() for name in names)


def mysql_bindings(
    env: Mapping[str, str],
    *,
    sub_id: str,
    resource_group: str,
) -> dict[str, Any]:
    """Return the `db` substrate bindings, or an empty mapping when incomplete."""

    if not _present(env, _MYSQL_ENV) or not env.get(_MYSQL_SECRET_ENV, "").strip():
        return {}
    server = env["FDAI_ENFORCE_MYSQL_SERVER"].strip()
    return {
        "mysql_server_resource_id": (
            f"/subscriptions/{sub_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.DBforMySQL/flexibleServers/{server}"
        ),
        "mysql_connect_factory": _mysql_connect_factory(
            host=env["FDAI_ENFORCE_MYSQL_HOST"].strip(),
            user=env["FDAI_ENFORCE_MYSQL_USER"].strip(),
            password_file=Path(env[_MYSQL_SECRET_ENV].strip()),
        ),
    }


def _mysql_connect_factory(
    *,
    host: str,
    user: str,
    password_file: Path,
) -> Callable[[], Any]:
    """Return a factory that opens one TLS MySQL connection per call.

    The password is read from ``password_file`` at connect time so it is never
    held in the substrate context. ``pymysql`` is imported lazily because the
    control plane does not need a database driver to run pod or VM scenarios.
    """

    def _connect() -> Any:
        # The control plane keeps the driver out of its typed surface: every
        # other seam takes an injected connect factory. This is the one place a
        # deployment needs a real one, so the import is lazy and untyped.
        import pymysql  # type: ignore[import-untyped]

        return pymysql.connect(
            host=host,
            user=user,
            password=password_file.read_text(encoding="utf-8").strip(),
            ssl={"ssl": {}},
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        )

    return _connect


def aoai_bindings(
    env: Mapping[str, str],
    *,
    token_provider: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Return the `llm_endpoint` substrate bindings, or an empty mapping.

    The load and probe request functions are deliberately separate: the load
    function drives quota pressure, and the probe observes whether the endpoint
    answers with a throttled status. Sharing one function would let the probe's
    own traffic sustain the pressure it is supposed to observe independently.
    """

    if not _present(env, _AOAI_ENV):
        return {}
    from fdai.delivery.chaos.aoai_ratelimit import build_aoai_request_fn

    endpoint = env["FDAI_ENFORCE_AOAI_ENDPOINT"].strip()
    deployment = env["FDAI_ENFORCE_AOAI_DEPLOYMENT"].strip()
    provider = token_provider if token_provider is not None else _entra_token_provider()
    return {
        "aoai_resource_id": env["FDAI_ENFORCE_AOAI_RESOURCE_ID"].strip(),
        "aoai_load_request_fn": build_aoai_request_fn(
            endpoint=endpoint,
            deployment=deployment,
            token_provider=provider,
            prompt=_LOAD_PROMPT,
            max_tokens=400,
        ),
        "aoai_probe_request_fn": build_aoai_request_fn(
            endpoint=endpoint,
            deployment=deployment,
            token_provider=provider,
            prompt="ping",
            max_tokens=1,
        ),
    }


def _entra_token_provider() -> Callable[[], str]:
    """Return a per-request Microsoft Entra token provider for the model endpoint.

    The credential is constructed lazily on first use so an unbound checkout can
    import this module, and the token is fetched per request so a long hold does
    not outlive it.
    """

    credential: list[Any] = []

    def _token() -> str:
        if not credential:
            from azure.identity import DefaultAzureCredential

            credential.append(DefaultAzureCredential())
        token: str = credential[0].get_token(_AOAI_SCOPE).token
        return token

    return _token


def optional_substrate_bindings(
    env: Mapping[str, str],
    *,
    sub_id: str,
    resource_group: str,
) -> dict[str, Any]:
    """Return every complete optional substrate binding group."""

    bindings = mysql_bindings(env, sub_id=sub_id, resource_group=resource_group)
    bindings.update(aoai_bindings(env))
    return bindings


__all__ = [
    "aoai_bindings",
    "mysql_bindings",
    "optional_substrate_bindings",
]
