"""OPA-backed admission policy evaluator bound at composition time."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_service_contracts.policy_administration import (
    AdmissionPolicyContent,
    PolicyRevisionRecord,
    PolicyRevisionSignatureVerifier,
)

from fdai.core.risk_gate.approval_profile import OperatorPolicyOutcome


@dataclass(frozen=True, slots=True)
class OpaAdmissionPolicyEvaluator:
    """Evaluate one pinned admission revision with bounded OPA execution."""

    opa_binary: str = "opa"
    capabilities_file: Path | None = None
    timeout_seconds: float = 5.0
    signature_verifier: PolicyRevisionSignatureVerifier | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("OPA admission timeout MUST be in (0, 30]")

    async def evaluate(
        self,
        *,
        revision: PolicyRevisionRecord,
        action_input: Mapping[str, Any],
    ) -> OperatorPolicyOutcome:
        if shutil.which(self.opa_binary) is None:
            return OperatorPolicyOutcome.REQUIRE_APPROVAL
        if self.capabilities_file is None or not self.capabilities_file.is_file():
            return OperatorPolicyOutcome.REQUIRE_APPROVAL
        if not isinstance(revision.content, AdmissionPolicyContent):
            return OperatorPolicyOutcome.REQUIRE_APPROVAL
        if (
            self.signature_verifier is not None
            and not await self.signature_verifier.verify_policy_revision_signature(revision)
        ):
            return OperatorPolicyOutcome.REQUIRE_APPROVAL
        stdout = b""
        with tempfile.TemporaryDirectory(prefix="fdai-admission-policy-") as directory:
            root = Path(directory)
            policy_path = root / "policy.rego"
            input_path = root / "input.json"
            policy_path.write_text(revision.content.rego, encoding="utf-8")
            input_path.write_text(
                json.dumps(action_input, allow_nan=False, sort_keys=True),
                encoding="utf-8",
            )
            proc = await asyncio.create_subprocess_exec(
                self.opa_binary,
                "eval",
                "--format",
                "json",
                "--capabilities",
                str(self.capabilities_file),
                "--input",
                str(input_path),
                "--data",
                str(policy_path),
                "data.fdai.policy",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                return OperatorPolicyOutcome.REQUIRE_APPROVAL
            finally:
                if proc.returncode is None:
                    proc.kill()
                    try:
                        await proc.wait()
                    except asyncio.CancelledError:
                        await proc.wait()
                        raise
        if proc.returncode != 0:
            return OperatorPolicyOutcome.REQUIRE_APPROVAL
        try:
            payload = json.loads(stdout.decode("utf-8"))
            value = payload["result"][0]["expressions"][0]["value"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return OperatorPolicyOutcome.REQUIRE_APPROVAL
        if isinstance(value, dict):
            outcome = value.get("outcome")
            if outcome in {item.value for item in OperatorPolicyOutcome}:
                return OperatorPolicyOutcome(str(outcome))
            if value.get("deny") is True:
                return OperatorPolicyOutcome.DENY
            if value.get("require_approval") is True:
                return OperatorPolicyOutcome.REQUIRE_APPROVAL
            if value.get("allow") is True:
                return OperatorPolicyOutcome.ALLOW
        return OperatorPolicyOutcome.REQUIRE_APPROVAL


__all__ = ["OpaAdmissionPolicyEvaluator"]
