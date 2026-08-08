"""OPA/Rego :class:`PolicyEvaluator` implementation.

The evaluator shells out to the ``opa`` binary via ``opa eval --stdin-input``
and interprets the JSON result under the deterministic conventions in
[`policies/README.md`](../../../../../policies/README.md):

- Every module declares ``package fdai.<derived path>`` matching its
  file location. Given ``rule.check_logic.reference == "policies/foo/bar.rego"``,
  the query is ``data.fdai.foo.bar``.
- Every module exports ``default deny := false`` and ``deny if { ... }``.
- Every module MAY export ``deny_reason`` (a string). When present it is
  carried into :attr:`PolicyResult.context` for the audit log.

The evaluator is a pure adapter: it does NOT persist audit records, does NOT
mutate resources, and does NOT catch semantic errors - a failing subprocess
raises :class:`OpaEvaluatorError`, and the T0 engine's own fail-close path
converts that to an abstain for the specific rule (see
:class:`fdai.core.tiers.t0_deterministic.T0Engine`).

Fail-fast at construction
-------------------------

:class:`OpaRegoEvaluator` looks up the OPA binary with :func:`shutil.which` at
construction time and raises :class:`MissingOpaBinaryError` when it is not on
``PATH``. A composition root that runs in an environment without OPA
(local-dev tooling, degraded CI runner) MUST catch that error and bind
:class:`~fdai.core.tiers.t0_deterministic.AbstainEvaluator` explicitly;
the evaluator itself never silently degrades to abstain, so the operational
posture is auditable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from fdai.core.tiers.t0_deterministic.engine import PolicyResult
from fdai.shared.contracts.models import CheckLogicKind, Rule

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0
_PACKAGE_ROOT: Final[str] = "fdai"


class MissingOpaBinaryError(RuntimeError):
    """Raised at construction when the ``opa`` binary is not on ``PATH``."""


class OpaEvaluatorError(RuntimeError):
    """Raised when an ``opa eval`` invocation fails or returns unusable output."""


class OpaRegoEvaluator:
    """Subprocess-backed :class:`PolicyEvaluator` for the T0 engine.

    Bound at the composition root once ``opa`` is installed; the T0 engine
    itself never imports this module directly - it only knows the
    Protocol.
    """

    def __init__(
        self,
        *,
        policies_root: Path,
        opa_binary: str = "opa",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        resolved = shutil.which(opa_binary)
        if resolved is None:
            raise MissingOpaBinaryError(
                f"OPA binary {opa_binary!r} not found on PATH; "
                "install from https://www.openpolicyagent.org/docs/latest/#running-opa "
                "or bind AbstainEvaluator at the composition root"
            )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not policies_root.is_dir():
            raise ValueError(f"policies_root MUST be an existing directory; got {policies_root!r}")
        self._opa: Final[str] = resolved
        self._policies_root: Final[Path] = policies_root
        self._timeout: Final[float] = timeout_seconds

    # ------------------------------------------------------------------
    # PolicyEvaluator
    # ------------------------------------------------------------------

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        """Evaluate a rule's Rego module against the resource properties.

        Returns ``None`` to abstain when the rule's ``check_logic`` is not a
        Rego reference this evaluator handles (kind != ``rego`` or
        reference not prefixed by ``policies/``); the engine treats that
        the same way as :class:`AbstainEvaluator`.

        Raises :class:`OpaEvaluatorError` when OPA is invoked but its
        output is unusable - a corrupt policy file, a timeout, or a
        subprocess failure. The T0 engine converts that into a fail-close
        abstain for the offending rule; other rules keep evaluating.
        """
        if rule.check_logic.kind is not CheckLogicKind.REGO:
            return None
        reference = rule.check_logic.reference
        if not reference.startswith("policies/"):
            return None

        rel = reference[len("policies/") :]
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise OpaEvaluatorError(
                f"policy reference {reference!r} MUST be a repo-relative path without '..'"
            )
        rego_path = self._policies_root / rel_path
        if not rego_path.is_file():
            raise OpaEvaluatorError(f"policy file not found: {rego_path.as_posix()!r}")

        package = self._derive_package(rel_path)
        query = f"data.{package}"

        input_doc = {
            "resource": {
                "type": rule.resource_type,
                "props": dict(resource_props),
            },
            "parameters": dict(rule.parameters),
        }

        try:
            proc = subprocess.run(  # noqa: S603 - opa binary is resolved via shutil.which
                [
                    self._opa,
                    "eval",
                    "--stdin-input",
                    "--format",
                    "json",
                    "--data",
                    str(rego_path),
                    query,
                ],
                input=json.dumps(input_doc),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpaEvaluatorError(
                f"opa eval timed out after {self._timeout}s on {reference!r}"
            ) from exc

        if proc.returncode != 0:
            stderr = proc.stderr.strip() or "(no stderr)"
            raise OpaEvaluatorError(
                f"opa eval failed (exit {proc.returncode}) for {reference!r}: {stderr}"
            )

        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise OpaEvaluatorError(
                f"opa eval returned non-JSON for {reference!r}: {proc.stdout[:200]!r}"
            ) from exc

        return _interpret_result(parsed)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_package(relative: Path) -> str:
        """Derive ``fdai.<a>.<b>.<c>`` from ``<a>/<b>/<c>.rego``."""
        parts = [*relative.parent.parts, relative.stem]
        return ".".join([_PACKAGE_ROOT, *parts])


def _interpret_result(parsed: dict[str, Any]) -> PolicyResult | None:
    """Translate the raw ``opa eval`` JSON into a :class:`PolicyResult`.

    Undefined query results (empty ``result`` list, empty ``expressions``,
    or a non-object value) map to :class:`None` - the engine treats that
    as an abstain, distinguishing "policy did not decide" from
    "policy allowed".
    """
    result_list = parsed.get("result")
    if not isinstance(result_list, list) or not result_list:
        return None
    expressions = result_list[0].get("expressions")
    if not isinstance(expressions, list) or not expressions:
        return None
    module_val = expressions[0].get("value")
    if not isinstance(module_val, dict):
        return None

    denied = bool(module_val.get("deny", False))
    context: dict[str, Any] = {}
    reason = module_val.get("deny_reason")
    if isinstance(reason, str) and reason:
        context["deny_reason"] = reason
    return PolicyResult(denied=denied, context=context)


__all__ = [
    "MissingOpaBinaryError",
    "OpaEvaluatorError",
    "OpaRegoEvaluator",
]
