"""Bounded process boundary to the installed deployment-owned release verifier."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentFact


async def collect_artifact_fact(
    *,
    deployment_python: Path,
    request_path: Path,
    target_ref: str,
    source_commit: str,
    image_digest: str,
    now: Callable[[], datetime],
) -> ObserverDeploymentFact:
    """Run only the fixed offline-kit verifier; no imports of the independent CLI distribution."""
    from fdai.delivery.kubernetes_connector_runtime import _unique_fields, private_file

    observed = connector_time(now())
    if not deployment_python.is_absolute() or not request_path.is_absolute():
        raise ValueError("observer artifact verifier paths must be absolute")
    if (
        re.fullmatch(r"[a-f0-9]{40}", source_commit) is None
        or re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest) is None
    ):
        raise ValueError("observer artifact binding is invalid")
    request = json.loads(
        private_file(request_path, maximum=16384), object_pairs_hook=_unique_fields
    )
    if (
        not isinstance(request, dict)
        or request.get("source_commit") != source_commit
        or request.get("image_digest") != image_digest
    ):
        raise ValueError("observer artifact request differs from the selected source or image")
    process: asyncio.subprocess.Process | None = None
    accepted = False
    evidence: dict[str, object] = {
        "source_commit": source_commit,
        "image_digest": image_digest,
        "reason": "artifact_verification_unavailable",
    }
    environment = {
        key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    try:
        async with asyncio.timeout(60):
            process = await asyncio.create_subprocess_exec(
                str(deployment_python),
                "-I",
                "-m",
                "fdai_deployment_cli.observer_artifact",
                "--request",
                str(request_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
            if process.stdout is None:
                raise ValueError("observer artifact output unavailable")
            body = bytearray()
            while chunk := await process.stdout.read(4096):
                if len(body) + len(chunk) > 8192:
                    raise ValueError("observer artifact output exceeds its limit")
                body.extend(chunk)
            if await process.wait() != 0:
                raise ValueError("observer artifact verification failed")
            value = json.loads(body, object_pairs_hook=_unique_fields)
            keys = {
                "schema_version",
                "source_commit",
                "image_digest",
                "platform_tag",
                "runtime_digest",
                "bundle_digest",
                "release_signature_verified",
                "execution_authority",
                "evidence_digest",
            }
            if not isinstance(value, dict) or set(value) != keys:
                raise ValueError("observer artifact receipt shape is invalid")
            if (
                value["schema_version"] != "1.0.0"
                or value["source_commit"] != source_commit
                or value["image_digest"] != image_digest
                or value["platform_tag"] != "linux-x86_64"
                or value["execution_authority"] is not False
                or value["release_signature_verified"] is not True
            ):
                raise ValueError("observer artifact receipt binding is invalid")
            if any(
                not isinstance(value[name], str)
                or re.fullmatch(r"sha256:[a-f0-9]{64}", value[name]) is None
                for name in ("runtime_digest", "bundle_digest")
            ):
                raise ValueError("observer artifact receipt digest is invalid")
            if value["evidence_digest"] != canonical_digest(
                {key: item for key, item in value.items() if key != "evidence_digest"}
            ):
                raise ValueError("observer artifact receipt integrity failed")
            evidence = value
            accepted = True
    except (OSError, TimeoutError, ValueError):
        accepted = False
    finally:
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            async with asyncio.timeout(5):
                await process.wait()
    if not observed <= connector_time(now()) < observed + timedelta(minutes=5):
        raise ValueError("observer artifact verification expired")
    return ObserverDeploymentFact(
        target_ref=target_ref,
        name="artifact_verified",
        state="allowed" if accepted else "unknown",
        source="deployment_profile",
        evidence_digest=canonical_digest(evidence),
        observed_at=observed,
        expires_at=observed + timedelta(minutes=5),
    )
