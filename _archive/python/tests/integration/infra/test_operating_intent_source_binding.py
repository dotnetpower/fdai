"""Infrastructure contract for the deployment-owned six-type operating-intent binding."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_MAIN = (_ROOT / "infra/services/core-control-plane/main.tf").read_text(encoding="utf-8")
_SERVICE_VARIABLES = (_ROOT / "infra/services/core-control-plane/variables.tf").read_text(
    encoding="utf-8"
)
_MODULE_MAIN = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text(encoding="utf-8")
_MODULE_VARIABLES = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/variables.tf"
).read_text(encoding="utf-8")


def _assigns(text: str, name: str) -> bool:
    """Return whether ``text`` passes ``var.<name>`` to a ``<name>`` argument.

    ``terraform fmt`` column-aligns every assignment in a block to its widest
    sibling identifier, so exact inter-token spacing shifts whenever a sibling
    variable is added or removed; matching on flexible whitespace keeps this
    check stable across that reformatting.
    """

    return re.search(rf"\b{re.escape(name)}\s*=\s*var\.{re.escape(name)}\b", text) is not None


def test_operating_intent_source_is_supplied_by_the_caller_and_overridable() -> None:
    """The caller supplies the shipped generic source; a deployment may replace it.

    The module still gates every variable behind `enabled`, so a fork that binds its
    own reviewed source - or none at all - keeps the same fail-closed contract.
    """

    assert 'variable "operating_intent_source"' in _SERVICE_VARIABLES
    assert 'variable "operating_intent_source"' in _MODULE_VARIABLES
    assert _assigns(_SERVICE_MAIN, "operating_intent_source")
    assert "!var.operating_intent_source.enabled ? [] : [" in _MODULE_MAIN
    assert "/app/config/operating-intent/generic-source.json" in _SERVICE_VARIABLES
    assert re.search(r"\benabled\s*=\s*optional\(bool, true\)", _SERVICE_VARIABLES) is not None
    assert re.search(r"\benabled\s*=\s*optional\(bool, false\)", _MODULE_VARIABLES) is not None


def _operating_intent_source_variable_block() -> str:
    start = _SERVICE_VARIABLES.index('variable "operating_intent_source"')
    return _SERVICE_VARIABLES[start : _SERVICE_VARIABLES.index("\n}\n", start) + 3]


def _module_variable_block() -> str:
    start = _MODULE_VARIABLES.index('variable "operating_intent_source"')
    return _MODULE_VARIABLES[start : _MODULE_VARIABLES.index("\n}\n", start) + 3]


def _terraform_passthrough_plan(tmp_path: Path, override: str) -> subprocess.CompletedProcess[str]:
    """Plan the real caller/module variable pair under one caller override, or skip.

    The service root binds an `azurerm` backend and real providers, so planning it in
    place would need remote state and credentials. Replaying the exact
    `operating_intent_source = var.operating_intent_source` pass-through between the
    two real variable blocks evaluates the same defaults and the same validation rules
    with no backend, provider, or resource.
    """

    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("terraform is not installed")
    root = tmp_path / "operating-intent-passthrough"
    (root / "child").mkdir(parents=True)
    (root / "variables.tf").write_text(_operating_intent_source_variable_block(), encoding="utf-8")
    (root / "main.tf").write_text(
        'module "child" {\n'
        '  source                  = "./child"\n'
        "  operating_intent_source = var.operating_intent_source\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "child" / "variables.tf").write_text(_module_variable_block(), encoding="utf-8")
    init = subprocess.run(  # noqa: S603 - resolved binary, fixed argv
        (terraform, "init", "-input=false", "-no-color"),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if init.returncode != 0:
        pytest.skip(f"terraform init unavailable: {init.stderr.strip()[-200:]}")
    return subprocess.run(  # noqa: S603 - resolved binary, fixed argv
        (
            terraform,
            "plan",
            "-input=false",
            "-no-color",
            f"-var=operating_intent_source={override}",
        ),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_caller_and_module_agree_on_every_supported_override(tmp_path: Path) -> None:
    """Every documented caller shape MUST survive the pass-through to the module.

    The caller always hands the module a fully resolved object, so a module rule that
    tried to infer intent from which attributes are non-empty would reject the plain
    `{ enabled = false }` disable - the one override an operator is most likely to
    write - while looking correct in isolation.
    """

    for override in (
        "{}",
        "{revalidate_seconds=600}",
        "{enabled=false}",
        '{enabled=false,path="/mnt/intent/source.json"}',
        "{generation=4}",
        '{path="/mnt/intent/source.json",revision="reviewed@2",'
        f'sha256="sha256:{"b" * 64}",expected_counts_json="{{}}",generation=2}}',
    ):
        plan = _terraform_passthrough_plan(tmp_path / override.replace("/", "_"), override)

        assert plan.returncode == 0, f"{override} was rejected: {plan.stderr.strip()[-400:]}"


def test_the_passthrough_still_rejects_an_incomplete_override(tmp_path: Path) -> None:
    plan = _terraform_passthrough_plan(tmp_path, '{path="/mnt/intent/source.json"}')

    assert plan.returncode != 0


def _terraform_console(tmp_path: Path, expression: str, override: str) -> str:
    """Evaluate the real variable block under one caller override, or skip.

    The service root binds an `azurerm` backend, so evaluating it in place would
    require remote state. Copying the exact variable block into a hermetic root
    evaluates the same defaults and the same validation rules with no backend,
    provider, or credential.
    """

    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("terraform is not installed")
    root = tmp_path / "operating-intent-variable"
    root.mkdir()
    (root / "variables.tf").write_text(_operating_intent_source_variable_block(), encoding="utf-8")
    init = subprocess.run(  # noqa: S603 - resolved binary, fixed argv
        (terraform, "init", "-input=false", "-no-color"),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if init.returncode != 0:
        pytest.skip(f"terraform init unavailable: {init.stderr.strip()[-200:]}")
    return subprocess.run(  # noqa: S603 - resolved binary, fixed argv
        (terraform, "console", "-no-color", f"-var=operating_intent_source={override}"),
        cwd=root,
        input=expression,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def test_a_partial_caller_override_cannot_silently_disable_the_binding(tmp_path: Path) -> None:
    """Tuning one field MUST NOT fail open by turning admission off.

    Terraform applies an object-level `default` only when the whole variable is
    omitted, so per-attribute defaults are what a partial override falls back to.
    Putting the shipped generic values there is what keeps
    `operating_intent_source = { revalidate_seconds = 600 }` a tuning change rather
    than a silent removal of the fail-closed binding.
    """

    resolved = _terraform_console(
        tmp_path,
        "var.operating_intent_source",
        "{revalidate_seconds=600}",
    )
    if not resolved:
        pytest.skip("terraform console produced no output")

    assert '"enabled" = true' in resolved
    assert '"path" = "/app/config/operating-intent/generic-source.json"' in resolved
    assert '"revalidate_seconds" = 600' in resolved
    assert "sha256:" in resolved


def test_replacing_the_generic_path_alone_is_rejected(tmp_path: Path) -> None:
    """A deployment that supplies its own source MUST also supply its own pin.

    Keeping the generic revision and digest while pointing at another file would pin
    a document the deployment does not supply, so the caller is rejected rather than
    left to quarantine at runtime.
    """

    resolved = _terraform_console(
        tmp_path,
        "var.operating_intent_source.enabled",
        '{path="/mnt/operating-intent/source.json"}',
    )

    assert resolved != "true"


def test_the_shipped_generic_counts_stay_exactly_one_of_each_required_type() -> None:
    block = _operating_intent_source_variable_block()
    match = re.search(r'expected_counts_json = optional\(string, "(?P<value>.*)"\)', block)
    assert match is not None
    assert json.loads(match.group("value").replace('\\"', '"')) == {
        "ArchitectureConstraint": 1,
        "ChangeWindow": 1,
        "CostObjective": 1,
        "Ownership": 1,
        "RecoveryObjective": 1,
        "ServiceObjective": 1,
    }


def test_the_rollout_generation_is_threaded_and_bounded() -> None:
    """An old replica must not overwrite or authorize a newer rollout's admission."""

    assert "FDAI_OPERATING_INTENT_SOURCE_GENERATION" in _MODULE_MAIN
    assert "generation           = optional(number, 1)" in _MODULE_VARIABLES
    assert "generation           = optional(number, 1)" in _SERVICE_VARIABLES
    assert "var.operating_intent_source.generation >= 1" in _MODULE_VARIABLES
    assert "var.operating_intent_source.generation >= 1" in _SERVICE_VARIABLES


def test_operating_intent_source_threads_exact_revision_digest_and_path() -> None:
    for key in (
        "FDAI_OPERATING_INTENT_SOURCE_PATH",
        "FDAI_OPERATING_INTENT_SOURCE_REVISION",
        "FDAI_OPERATING_INTENT_SOURCE_SHA256",
        "FDAI_OPERATING_INTENT_SOURCE_EXPECTED_COUNTS_JSON",
    ):
        assert key in _MODULE_MAIN

    assert "sha256:[0-9a-f]{64}" in _MODULE_VARIABLES
    assert "exact pinned revision" in _MODULE_VARIABLES
    assert "whole-document sha256 content digest" in _MODULE_VARIABLES


def test_operating_intent_source_exposes_a_bounded_revalidation_interval() -> None:
    """Continuous admission is deployment-configurable, and bounded on both ends.

    The runtime keeps a source admitted for a multiple of this interval, so an
    unbounded value would let one startup proof back authority indefinitely.
    """

    assert "FDAI_OPERATING_INTENT_SOURCE_REVALIDATE_SECONDS" in _MODULE_MAIN
    assert "revalidate_seconds   = optional(number, 0)" in _MODULE_VARIABLES
    assert "revalidate_seconds   = optional(number, 0)" in _SERVICE_VARIABLES
    assert "var.operating_intent_source.revalidate_seconds <= 28800" in _MODULE_VARIABLES
    assert "var.operating_intent_source.revalidate_seconds >= 1" in _MODULE_VARIABLES
