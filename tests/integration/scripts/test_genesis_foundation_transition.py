"""Private-runner Foundation transition transport regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_foundation_state_archive as state_archive  # noqa: E402
import genesis_foundation_transition as transition  # noqa: E402
import genesis_foundation_transition_remote as remote  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"
_TENANT = "00000000-0000-0000-0000-000000000001"


def _parse_remote(arguments: tuple[str, ...]) -> argparse.Namespace:
    """Parse helper arguments exactly as the runner-side helper does."""

    args = remote._parser().parse_args(list(arguments))  # noqa: SLF001
    remote._validate(args)  # noqa: SLF001
    return args


class TransitionTunnel:
    def __init__(self, home: Path, username: str = "runner") -> None:
        self.home = home
        self.username = username
        self.operations: list[str] = []
        self.copied_to: list[str] = []
        self.failure: subprocess.CompletedProcess[str] | None = None

    def _path(self, remote_path: str) -> Path:
        prefix = f"/home/{self.username}/"
        assert remote_path.startswith(prefix)
        return self.home / remote_path.removeprefix(prefix)

    def ssh(
        self, command: tuple[str, ...], *, timeout: int, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        del timeout, input_text
        if command[0] == "/usr/bin/sha256sum":
            path = self._path(command[1])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return subprocess.CompletedProcess(command, 0, f"{digest}  {command[1]}\n", "")
        if command[0] == "/usr/bin/rm":
            self._path(command[-1]).unlink(missing_ok=True)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ("/usr/bin/python3", command[1]):
            try:
                args = _parse_remote(command[2:])
            except SystemExit as exc:
                return subprocess.CompletedProcess(command, int(exc.code or 2), "", "usage\n")
            if self.failure is not None:
                return self.failure
            mode = args.mode
            work_id = args.work_id
            # The real helper publishes evidence below the Bastion evidence boundary.
            work = self.home / ".fdai-state-handoff" / f"transition-{work_id[:24]}"
            work.mkdir(mode=0o700, parents=True, exist_ok=True)
            if mode == "plan":
                self.operations.append("plan")
                _write_remote_plan(work, zero=False)
                marker = f"foundation_transition_plan_complete work_ref={work_id[:24]}"
                return subprocess.CompletedProcess(command, 0, marker + "\n", "")
            if mode == "apply":
                self.operations.append("apply")
                _write_remote_plan(work, zero=True, observation="apply-observation.json")
                marker = f"foundation_transition_verified work_ref={work_id[:24]}"
                return subprocess.CompletedProcess(command, 0, marker + "\n", "")
            if mode == "verify":
                self.operations.append("verify")
                _write_remote_plan(work, zero=True, observation="apply-observation.json")
                marker = f"foundation_transition_verified work_ref={work_id[:24]}"
                return subprocess.CompletedProcess(command, 0, marker + "\n", "")
        raise AssertionError(f"unexpected ssh command: {command}")

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        del timeout
        # Mirror genesis_bastion.BastionTunnel.copy_to: only transfer-prefixed destinations.
        if not destination.startswith(f"/home/{self.username}/.fdai-transfer-"):
            raise ValueError("Bastion remote destination is invalid")
        target = self._path(destination)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        self.copied_to.append(destination)

    def copy_from(self, source: str, destination: Path, *, timeout: int) -> None:
        del timeout
        # Mirror genesis_bastion.BastionTunnel.copy_from: evidence boundary and no replacement.
        if not source.startswith(f"/home/{self.username}/.fdai-state-handoff/"):
            raise ValueError("Bastion remote evidence source is invalid")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Bastion local evidence destination already exists")
        if destination.parent.stat().st_mode & 0o777 != 0o700:
            raise PermissionError("Bastion local evidence directory must be owner-only")
        shutil.copyfile(self._path(source), destination)
        destination.chmod(0o600)


def _write_remote_plan(
    work: Path, *, zero: bool, observation: str = "plan-observation.json"
) -> None:
    plan = {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": "azurerm_role_assignment.bootstrap",
                "type": "azurerm_role_assignment",
                "change": {"actions": ["no-op"] if zero else ["update"]},
            }
        ],
    }
    plan_name = "remote-zero-plan.json" if zero else "remote-plan.json"
    (work / plan_name).write_text(json.dumps(plan), encoding="utf-8")
    state_digest = "1" * 64
    plan_json_digest = hashlib.sha256((work / plan_name).read_bytes()).hexdigest()
    value = {
        "schema_version": "fdai.genesis-foundation-transition-observation.v1",
        "state": "verified",
        "work_id": "c" * 64,
        "archive_digest": "a" * 64,
        "helper_digest": "b" * 64,
        "remote_state_digest": state_digest,
        "plan_json_digest": plan_json_digest,
        "plan_digest": "d" * 64,
        "zero_change_verified": zero,
        "mutation_performed": observation == "apply-observation.json",
        "subscription_ready": False,
    }
    (work / observation).write_text(json.dumps(value), encoding="utf-8")


def _kwargs(tmp_path: Path, tunnel: TransitionTunnel) -> dict[str, object]:
    retained = tmp_path / "retained"
    transition_dir = tmp_path / "transition"
    retained.mkdir(mode=0o700)
    transition_dir.mkdir(mode=0o700)
    archive = transition_dir / "foundation-transition-cccccccccccc.tar.gz"
    write_private_bytes(archive, b"archive")
    helper = b"print('helper')\n"
    return {
        "args": argparse.Namespace(timeout_seconds=900),
        "retained": retained,
        "transition": transition_dir,
        "connection": {
            "username": tunnel.username,
            "vm_id": "vm-id",
            "resource_group": "rg",
            "bastion_name": "bas",
        },
        "handoff": {"subscription_id": _SUBSCRIPTION, "tenant_id": _TENANT},
        "state": {
            "account_id": "id",
            "account_name": "acct",
            "container_name": "tfstate",
            "foundation_key": "key",
        },
        "runner": {"client_id": "client", "principal_id": "principal"},
        "ops": {"resource_group_name": "rg"},
        "private_key": tmp_path / "key",
        "known_hosts": tmp_path / "known-hosts",
        "work_id": "c" * 64,
        "archive_digest": hashlib.sha256(b"archive").hexdigest(),
        "helper": helper,
        "helper_digest": hashlib.sha256(helper).hexdigest(),
        "expected_plan_digest": "d" * 64,
    }


def test_remote_plan_ships_helper_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    result = transition._run_remote("plan", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert tunnel.operations == ["plan"]
    assert any(item.endswith(".py") for item in tunnel.copied_to)
    assert any(item.endswith(".tar.gz") for item in tunnel.copied_to)
    assert result["observation"]["zero_change_verified"] is False


def test_remote_apply_uses_saved_plan_after_local_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    result = transition._run_remote("apply", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert tunnel.operations == ["apply"]
    assert result["observation"]["zero_change_verified"] is True
    assert result["observation"]["mutation_performed"] is True


def test_remote_verify_never_applies_after_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    result = transition._run_remote("verify", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert tunnel.operations == ["verify"]
    assert "apply" not in tunnel.operations
    assert result["observation"]["zero_change_verified"] is True


class _TunnelContext:
    def __init__(self, tunnel: TransitionTunnel) -> None:
        self.tunnel = tunnel

    def __enter__(self) -> TransitionTunnel:
        return self.tunnel

    def __exit__(self, *_args: object) -> None:
        return None


def _remote_arguments(kwargs: dict[str, object], *, archive: str) -> tuple[str, ...]:
    return transition.transition_remote_arguments(
        archive=archive,
        work_id=str(kwargs["work_id"]),
        archive_digest=str(kwargs["archive_digest"]),
        handoff=kwargs["handoff"],  # type: ignore[arg-type]
        state=kwargs["state"],  # type: ignore[arg-type]
        runner=kwargs["runner"],  # type: ignore[arg-type]
        ops=kwargs["ops"],  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("mode", ["plan", "apply", "verify", "cleanup"])
def test_transport_arguments_parse_in_the_runner_helper(tmp_path: Path, mode: str) -> None:
    tmp_path.chmod(0o700)
    kwargs = _kwargs(tmp_path, TransitionTunnel(tmp_path / "remote"))
    digests = (
        "--expected-helper-digest",
        str(kwargs["helper_digest"]),
        "--expected-archive-digest",
        str(kwargs["archive_digest"]),
    )

    args = _parse_remote(
        (mode, *_remote_arguments(kwargs, archive="/home/runner/archive"), *digests)
    )

    assert args.mode == mode
    assert args.work_id == kwargs["work_id"]
    assert args.backend_key == "key"


def test_runner_helper_rejects_the_former_placeholder_state_digest(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    kwargs = _kwargs(tmp_path, TransitionTunnel(tmp_path / "remote"))
    arguments = (
        "plan",
        *_remote_arguments(kwargs, archive="/home/runner/archive"),
        "--expected-state-digest",
        "0" * 64,
        "--expected-helper-digest",
        str(kwargs["helper_digest"]),
        "--expected-archive-digest",
        str(kwargs["archive_digest"]),
    )

    with pytest.raises(SystemExit):
        _parse_remote(arguments)


def test_remote_failure_surfaces_the_helper_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    tunnel.failure = subprocess.CompletedProcess(
        (),
        3,
        "",
        "Error: Invalid function argument\n"
        "fdai-foundation-transition: Foundation transition remote plan failed\n",
    )
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    with pytest.raises(ValueError) as caught:
        transition._run_remote("plan", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert str(caught.value) == (
        "Foundation transition remote operation failed: Foundation transition remote plan failed"
    )


def test_remote_failure_reason_is_bounded_and_identifier_free() -> None:
    guid = "00000000-0000-0000-0000-000000000009"
    found = subprocess.CompletedProcess(
        (), 3, "", f"fdai-foundation-transition: lookup failed for {guid}\n"
    )
    unsafe = subprocess.CompletedProcess((), 3, "", 'fdai-foundation-transition: token="x"\n')
    rejected = subprocess.CompletedProcess((), 2, "", "usage: helper\n")

    assert transition.remote_failure_reason(found) == (
        "Foundation transition remote operation failed: lookup failed for redacted-id"
    )
    assert transition.remote_failure_reason(unsafe) == (
        "Foundation transition remote operation failed"
    )
    assert transition.remote_failure_reason(rejected) == (
        "Foundation transition remote operation failed: remote helper rejected its arguments"
    )


def test_work_identity_is_scoped_to_one_attempt() -> None:
    identity = {
        "foundation_receipt_digest": "1" * 64,
        "enrollment_receipt_digest": "2" * 64,
        "helper_digest": "3" * 64,
    }

    first = transition.transition_work_id(
        **identity, transition_ref="foundation-transition-attempt-1"
    )

    assert first == transition.transition_work_id(
        **identity, transition_ref="foundation-transition-attempt-1"
    )
    assert (
        first[:24]
        != transition.transition_work_id(
            **identity, transition_ref="foundation-transition-attempt-2"
        )[:24]
    )


def _state(
    *,
    tags: object = None,
    second_tags: object = "same",
    patch: object = None,
    bypass: object = None,
    nat: bool = True,
) -> dict[str, object]:
    def resource(kind: str, name: str, attributes: dict[str, object]) -> dict[str, object]:
        return {
            "mode": "managed",
            "module": "module.bootstrap",
            "type": kind,
            "name": name,
            "instances": [{"index_key": 0, "attributes": {"id": f"{kind}-{name}", **attributes}}],
        }

    resources = [resource("azurerm_public_ip", "bastion", {"ip_tags": tags})]
    if nat:
        resources.append(
            resource(
                "azurerm_public_ip",
                "nat",
                {"ip_tags": tags if second_tags == "same" else second_tags},
            )
        )
    vm: dict[str, object] = {"patch_mode": patch}
    if bypass is not None:
        vm["bypass_platform_safety_checks_on_user_schedule_enabled"] = bypass
    resources.append(resource("azurerm_linux_virtual_machine", "runner", vm))
    return {"version": 4, "serial": 7, "lineage": "lineage", "resources": resources}


_MANAGED_STATE = json.dumps(_state()).encode()
_MODULE_SOURCE = re.compile(r'source\s*=\s*"(\.\.?/[^"]+)"')
_MODULE_FILE = re.compile(r"path\.module\}/((?:\.\./)+[A-Za-z0-9_.-]+)")


def _reached_infra_roots(start: Path) -> set[str]:
    infra = (ROOT / "infra").resolve()
    roots: set[str] = set()
    seen: set[Path] = set()
    pending = [start.resolve()]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        roots.add(module.relative_to(infra).parts[0])
        for source in module.glob("*.tf"):
            text = source.read_text(encoding="utf-8")
            pending.extend((module / match).resolve() for match in _MODULE_SOURCE.findall(text))
            roots.update(
                (module / match).resolve().relative_to(infra).parts[0]
                for match in _MODULE_FILE.findall(text)
            )
    return roots


def test_transition_archive_ships_every_directory_the_foundation_root_reaches() -> None:
    reached = _reached_infra_roots(ROOT / "infra/genesis-foundation")

    assert "genesis-runner-image" in reached
    assert reached - {"genesis-foundation"} <= set(transition.FOUNDATION_SIBLINGS)


def _archive_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, backend: bytes | None
) -> tuple[argparse.Namespace, Path, Path]:
    tmp_path.chmod(0o700)
    bundle = tmp_path / "bundle"
    for relative in (
        "infra/genesis-foundation/main.tf",
        "infra/bootstrap/main.tf",
        "infra/modules/private-endpoint/main.tf",
        "infra/genesis-runner-image/toolchain.json",
    ):
        (bundle / relative).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private_bytes(bundle / relative, b"{}\n")
    if backend is not None:
        write_private_bytes(bundle / "infra/genesis-foundation/backend.azurerm.tf.example", backend)
    mirror = tmp_path / "mirror"
    mirror.mkdir(mode=0o700)
    write_private_bytes(mirror / "provider.zip", b"provider")
    for name in ("release.pub", "bundle.pub", "variables.json", "profile.json"):
        write_private_bytes(tmp_path / name, b"{}\n")
    (tmp_path / "kit").mkdir(mode=0o700)
    monkeypatch.setattr(
        transition,
        "verify_offline_kit",
        lambda *_args, **_kwargs: SimpleNamespace(manifest_digest="9" * 64),
    )
    monkeypatch.setattr(
        transition,
        "materialize_verified_artifacts",
        lambda *_args, **_kwargs: SimpleNamespace(
            deployment_bundle=tmp_path / "bundle.tar", provider_mirror=mirror
        ),
    )
    monkeypatch.setattr(transition, "extract_bundle_archive", lambda *_args: bundle)
    monkeypatch.setattr(transition, "verify_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transition.foundation_apply, "_platform_tag", lambda: "linux")
    monkeypatch.setattr(
        transition.foundation_apply,
        "_foundation_target",
        lambda **kwargs: write_private_bytes(kwargs["destination"], b"{}\n"),
    )
    transition_dir = tmp_path / "transition"
    transition_dir.mkdir(mode=0o700)
    args = argparse.Namespace(
        release_root=tmp_path / "release.pub",
        bundle_public_key=tmp_path / "bundle.pub",
        offline_kit=tmp_path / "kit",
        variables_file=tmp_path / "variables.json",
        profile=tmp_path / "profile.json",
    )
    return args, transition_dir, bundle


def _prepare(args: argparse.Namespace, tmp_path: Path, transition_dir: Path) -> Path:
    archive = transition_dir / "foundation-transition-cccccccccccc.tar.gz"
    transition._prepare_archive(  # noqa: SLF001
        args=args,
        retained=tmp_path,
        transition=transition_dir,
        archive=archive,
        context={},
        helper_digest="b" * 64,
    )
    return archive


def test_prepare_archive_ships_sibling_inputs_and_kit_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, transition_dir, _bundle = _archive_inputs(
        tmp_path,
        monkeypatch,
        backend=state_archive._REMOTE_BACKEND,  # noqa: SLF001
    )

    archive = _prepare(args, tmp_path, transition_dir)

    with tarfile.open(archive) as packed:
        names = set(packed.getnames())
        member = packed.extractfile("manifest.json")
        assert member is not None
        manifest = json.loads(member.read())
        backend = packed.extractfile("root/backend.azurerm.tf")
        assert backend is not None
        assert backend.read() == state_archive._REMOTE_BACKEND  # noqa: SLF001
    assert {
        "root/main.tf",
        "bootstrap/main.tf",
        "modules/private-endpoint/main.tf",
        "genesis-runner-image/toolchain.json",
    } <= names
    assert manifest["kit_manifest_digest"] == "9" * 64
    assert "source_commit" not in manifest


@pytest.mark.parametrize("backend", [None, b'terraform {\n  backend "local" {}\n}\n'])
def test_prepare_archive_refuses_without_the_remote_backend_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: bytes | None
) -> None:
    args, transition_dir, _bundle = _archive_inputs(tmp_path, monkeypatch, backend=backend)

    with pytest.raises(ValueError, match="remote backend contract"):
        _prepare(args, tmp_path, transition_dir)


def test_prepare_archive_refuses_a_second_local_state_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, transition_dir, bundle = _archive_inputs(
        tmp_path,
        monkeypatch,
        backend=state_archive._REMOTE_BACKEND,  # noqa: SLF001
    )
    write_private_bytes(bundle / "infra/genesis-foundation/terraform.tfstate", b"{}\n")

    with pytest.raises(ValueError, match="second state owner"):
        _prepare(args, tmp_path, transition_dir)


def test_repository_backend_example_matches_the_remote_backend_contract() -> None:
    example = ROOT / "infra/genesis-foundation/backend.azurerm.tf.example"

    assert example.read_bytes() == state_archive._REMOTE_BACKEND  # noqa: SLF001


@pytest.mark.parametrize(
    "state",
    [
        b"",
        b"{}",
        b'{"version":4,"lineage":"","resources":[{"mode":"managed"}]}',
        b'{"version":4,"lineage":"a","resources":[]}',
        b'{"version":4,"lineage":"a","resources":[{"mode":"data"}]}',
    ],
)
def test_runner_helper_refuses_an_empty_or_unmanaged_remote_state(state: bytes) -> None:
    with pytest.raises(ValueError, match="remote state is empty or invalid"):
        remote._require_managed_state(state)  # noqa: SLF001


def test_runner_helper_accepts_a_managed_remote_state() -> None:
    remote._require_managed_state(_MANAGED_STATE)  # noqa: SLF001


_POLICY = {"FirstPartyUsage": "/Unprivileged"}
_BINDING_STATES = [
    _state(tags=_POLICY, patch="AutomaticByPlatform", bypass=True),
    _state(patch="ImageDefault"),
    _state(tags={}),
    _state(tags=_POLICY, second_tags={}),
    _state(tags={"FirstPartyUsage": "/Privileged"}),
    _state(tags=_POLICY, nat=False),
    _state(patch="Manual"),
    _state(patch="ImageDefault", bypass=True),
]


def _plan_json(state: dict[str, object]) -> bytes:
    resources = []
    for resource in state["resources"]:  # type: ignore[attr-defined]
        for instance in resource["instances"]:
            address = f"{resource['module']}.{resource['type']}.{resource['name']}"
            resources.append(
                {
                    "address": f"{address}[{instance['index_key']}]",
                    "mode": "managed",
                    "type": resource["type"],
                    "name": resource["name"],
                    "index": instance["index_key"],
                    "values": instance["attributes"],
                }
            )
    module = {"address": "module.bootstrap", "resources": resources}
    plan = {"prior_state": {"values": {"root_module": {"child_modules": [module]}}}}
    return json.dumps(plan).encode()


def _outcome(read: object) -> object:
    try:
        return read()  # type: ignore[operator]
    except ValueError:
        return ValueError


@pytest.mark.parametrize("state", _BINDING_STATES)
def test_refreshed_binding_matches_the_state_binding(state: dict[str, object]) -> None:
    from_state = _outcome(lambda: remote.observed_policy_variables(json.dumps(state).encode()))

    assert _outcome(lambda: remote.refreshed_policy_variables(_plan_json(state))) == from_state


def test_state_identity_digest_ignores_unordered_check_results() -> None:
    first = {**_state(), "check_results": [{"config_addr": "a"}, {"config_addr": "b"}]}
    second = {**_state(), "check_results": [{"config_addr": "b"}, {"config_addr": "a"}]}
    changed = {**_state(), "serial": 8}

    digest = remote.state_identity_digest(json.dumps(first).encode())

    assert digest == remote.state_identity_digest(json.dumps(second, indent=1).encode())
    assert digest != remote.state_identity_digest(json.dumps(changed).encode())


def test_refreshed_binding_requires_a_refreshed_state() -> None:
    with pytest.raises(ValueError, match="refreshed state is unavailable"):
        remote.refreshed_policy_variables(b'{"prior_state":{"values":{}}}')


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            _state(tags=_POLICY, patch="AutomaticByPlatform", bypass=True),
            {
                "operations_public_ip_tags": _POLICY,
                "runner_patch_mode": "AutomaticByPlatform",
                "runner_bypass_platform_safety_checks": True,
            },
        ),
        (
            _state(patch="ImageDefault"),
            {"runner_patch_mode": "ImageDefault", "runner_bypass_platform_safety_checks": False},
        ),
        (_state(tags={}), {}),
    ],
)
def test_runner_helper_binds_supported_policy_values(
    state: dict[str, object], expected: dict[str, object]
) -> None:
    assert remote.observed_policy_variables(json.dumps(state).encode()) == expected


@pytest.mark.parametrize(
    "state",
    [
        _state(tags=_POLICY, second_tags={}),
        _state(tags={"FirstPartyUsage": "/Privileged"}),
        _state(tags=_POLICY, nat=False),
        _state(patch="Manual"),
        _state(patch="ImageDefault", bypass=True),
    ],
)
def test_runner_helper_refuses_unsupported_policy_values(state: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        remote.observed_policy_variables(json.dumps(state).encode())


@pytest.mark.parametrize(
    "state",
    [
        _state(tags=_POLICY, patch="AutomaticByPlatform", bypass=True),
        _state(patch="ImageDefault"),
        _state(tags={}),
        _state(tags=_POLICY, second_tags={}),
        _state(tags={"FirstPartyUsage": "/Privileged"}),
        _state(tags=_POLICY, nat=False),
        _state(patch="Manual"),
        _state(patch="ImageDefault", bypass=True),
    ],
)
def test_runner_binding_matches_the_foundation_apply_binding(state: dict[str, object]) -> None:
    import genesis_foundation_apply as foundation_apply
    import genesis_foundation_recovery as recovery

    def local() -> dict[str, object]:
        observed: dict[str, object] = {}
        tags = recovery.select_public_ip_tags(state)
        if tags:
            observed["operations_public_ip_tags"] = tags
        observed.update(foundation_apply._observed_runner_patch_selection(state))  # noqa: SLF001
        return observed

    try:
        expected: object = local()
    except ValueError:
        expected = ValueError
    try:
        actual: object = remote.observed_policy_variables(json.dumps(state).encode())
    except ValueError:
        actual = ValueError

    assert actual == expected


def test_runner_helper_plan_consumes_the_transport_archive_then_prunes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    kwargs = _kwargs(tmp_path, TransitionTunnel(tmp_path / "remote"))
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    stage = tmp_path / "stage"
    stage.mkdir(mode=0o700)
    (stage / "root").mkdir(mode=0o700)
    write_private_bytes(stage / "root/main.tf", b"locals {}\n")
    write_private_bytes(stage / "variables.auto.tfvars.json", b"{}\n")
    manifest: dict[str, object] = {
        "schema_version": "fdai.genesis-foundation-transition-archive.v1",
        "kit_manifest_digest": "9" * 64,
        "helper_digest": "b" * 64,
        "files": transition._file_manifest(stage),  # noqa: SLF001
    }
    manifest["manifest_digest"] = transition.canonical_digest(manifest)
    write_private_bytes(stage / "manifest.json", json.dumps(manifest).encode())
    work_id = str(kwargs["work_id"])
    archive = home / f".fdai-transfer-{work_id[:24]}-transition.tar.gz"
    transition._write_archive(stage, archive)  # noqa: SLF001
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    base = home / ".fdai-foundation-transition"
    base.mkdir(mode=0o700)
    superseded = base / ("d" * 24)
    superseded.mkdir(mode=0o700)
    superseded_archive = home / f".fdai-transfer-{'d' * 24}-transition.tar.gz"
    superseded_archive.write_bytes(b"old")
    execution_copy = home / f".fdai-transfer-{'e' * 24}"
    execution_copy.mkdir(mode=0o700)
    handoff = home / ".fdai-state-handoff"
    handoff.mkdir(mode=0o700)
    superseded_evidence = handoff / f"transition-{'d' * 24}"
    superseded_evidence.mkdir(mode=0o700)
    migration_evidence = handoff / ("f" * 24)
    migration_evidence.mkdir(mode=0o700)

    refreshed = _plan_json(_state(tags=_POLICY, patch="AutomaticByPlatform", bypass=True))
    seen: dict[str, object] = {}

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert command[:2] == (remote._TERRAFORM, "plan")  # noqa: SLF001
        output = next(item for item in command if item.startswith("-out="))
        Path(output.removeprefix("-out=")).write_bytes(b"plan")
        if "-refresh-only" in command:
            assert not any("observed" in item for item in command)
            return subprocess.CompletedProcess(command, 0)
        assert "-var-file=../observed.tfvars.json" in command
        observed = Path(str(kwargs["cwd"])).parent / "observed.tfvars.json"
        seen["observed"] = json.loads(observed.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(command, 2)

    def capture(command: tuple[str, ...], **_kwargs: object) -> bytes:
        if command[1:] == ("state", "pull"):
            return _MANAGED_STATE
        if command[1:3] == ("show", "-json") and command[3].endswith("refresh.tfplan"):
            return refreshed
        if command[1:3] == ("show", "-json"):
            return b'{"resource_changes":[]}'
        raise AssertionError(command)

    monkeypatch.setattr(remote, "_terraform_environment", lambda *_args: {})
    monkeypatch.setattr(remote, "_managed_identity_login", lambda *_args: None)
    monkeypatch.setattr(remote, "_terraform_init", lambda *_args: None)
    monkeypatch.setattr(remote, "_capture", capture)
    monkeypatch.setattr(remote.subprocess, "run", run)
    arguments = transition.transition_remote_arguments(
        archive=str(archive),
        work_id=work_id,
        archive_digest=archive_digest,
        handoff=kwargs["handoff"],  # type: ignore[arg-type]
        state=kwargs["state"],  # type: ignore[arg-type]
        runner=kwargs["runner"],  # type: ignore[arg-type]
        ops=kwargs["ops"],  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "helper",
            "plan",
            *arguments,
            "--expected-helper-digest",
            "b" * 64,
            "--expected-archive-digest",
            archive_digest,
        ],
    )

    assert remote.main() == 0

    # The stale stored state carries no policy values; the refreshed state decides the binding.
    assert seen["observed"] == {
        "operations_public_ip_tags": _POLICY,
        "runner_patch_mode": "AutomaticByPlatform",
        "runner_bypass_platform_safety_checks": True,
    }
    published = handoff / f"transition-{work_id[:24]}"
    assert (published / "remote-plan.json").exists()
    assert (published / "plan-observation.json").exists()
    assert not archive.exists()
    assert not superseded.exists()
    assert not superseded_archive.exists()
    assert not superseded_evidence.exists()
    assert execution_copy.exists()
    assert migration_evidence.exists()
