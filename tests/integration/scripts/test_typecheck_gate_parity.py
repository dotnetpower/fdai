"""Static contract keeping local type checks aligned with CI."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_strict_mypy_runs_in_ci_fast_verify_and_central_queue() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    verify = (_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    pre_commit = (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    validation_queue = "\n".join(
        (_ROOT / "scripts" / "automation" / path).read_text(encoding="utf-8")
        for path in ("validation_queue.py", "validation_queue_runner.py")
    )
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "- name: mypy --strict\n        run: uv run mypy" in ci
    assert 'run_gate_scoped "mypy (strict)"' in verify
    assert verify.index('run_gate_scoped "mypy (strict)"') < verify.index(
        'if [[ "$MODE" == "full" ]]'
    )
    assert "- id: mypy-strict" not in pre_commit
    assert '"scripts/verify.sh",' in validation_queue
    assert '"--fast",' in validation_queue
    assert '"--diff",' in validation_queue
    assert '"scripts/**" = ["N999", "S603", "S607"]' in pyproject


def test_ruff_uses_the_same_monorepo_roots_in_ci_and_local_gates() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    verify = (_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    roots = "services packages tests extensions/code-assurance"

    for command in (f"ruff format --check {roots}", f"ruff check {roots}"):
        assert command in ci
        assert command in makefile
        assert command in verify
    assert "ruff format --check src tests" not in ci
    assert "ruff check src tests" not in ci


def test_pre_push_ruff_uses_locked_development_dependencies() -> None:
    pre_push = (_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")

    assert 'uv run --extra dev ruff check "${py[@]}"' in pre_push
    assert 'uv run --extra dev ruff format --check "${py[@]}"' in pre_push


def test_opa_downloads_are_bounded_and_checksum_verified() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert ci.count("--retry 3 --retry-delay 2 --retry-all-errors") == 2
    assert ci.count("--retry-max-time 90 --connect-timeout 10 --max-time 60") == 2
    assert ci.count("dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa") == 2


def test_container_opa_build_overrides_vulnerable_go_modules() -> None:
    dockerfile = (_ROOT / "services" / "core-control-plane" / "docker" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "ARG OPA_VERSION=v1.18.2" in dockerfile
    assert "ARG OPA_GRPC_VERSION=v1.82.1" in dockerfile
    assert "ARG OPA_X_TEXT_VERSION=v0.39.0" in dockerfile
    assert 'go mod edit -require="google.golang.org/grpc@${OPA_GRPC_VERSION}"' in dockerfile
    assert 'go mod edit -require="golang.org/x/text@${OPA_X_TEXT_VERSION}"' in dockerfile
    assert "go build -mod=mod -o /go/bin/opa ." in dockerfile
    assert "awk '$2 == \"google.golang.org/grpc\" {print $3}'" in dockerfile
    assert "awk '$2 == \"golang.org/x/text\" {print $3}'" in dockerfile
