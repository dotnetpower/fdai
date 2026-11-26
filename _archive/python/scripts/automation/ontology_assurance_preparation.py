"""Isolated workspace and service preparation for ontology assurance."""

from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path

from scripts.automation.ontology_assurance_evidence import AssuranceRunError
from scripts.automation.ontology_assurance_execution import _git_output, _run_checked
from scripts.automation.ontology_assurance_supervisor import AtomicRunStatus, ProcessSpec


def _symlink(target: Path, link: Path) -> None:
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise AssuranceRunError(f"existing assurance link targets another path: {link}")
        return
    if link.exists():
        raise AssuranceRunError(f"assurance link path already exists: {link}")
    link.symlink_to(target, target_is_directory=target.is_dir())


class OntologyAssurancePreparationMixin:
    repo: Path
    worktree: Path
    run_root: Path
    run_id: str
    source_revision: str
    model_path: Path
    storage_state: Path
    stack_log: Path
    request_topic: str
    projection_topic: str
    status: AtomicRunStatus
    strict_output: Path
    full_output: Path
    strict_checkpoint: Path
    full_checkpoint: Path
    evidence_root: Path

    def _service_specs(self) -> tuple[ProcessSpec, ...]:
        core_command = (
            "/usr/bin/bash",
            "-c",
            """
set -euo pipefail
cd "$1"
set -a
source "$2/.fdai/local-runtime.env"
set +a
export LLM_RESOLVED_MODELS_PATH="$3"
export FDAI_CORE_CONSUMER_GROUP_ID="$4-core"
export FDAI_PANTHEON_CONSUMER_GROUP_PREFIX="$4-pantheon"
export FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID="$4-semantic-core"
export FDAI_SEMANTIC_TURN_REQUEST_TOPIC="$5"
export FDAI_SEMANTIC_TURN_PROJECTION_TOPIC="$6"
python_path="$1/services/core-control-plane/src:$1/packages/service-contracts/src"
exec env -u AZURE_CONFIG_DIR FDAI_RUNTIME_LOCK_FILE="$7" \
    PYTHONPATH="$python_path${PYTHONPATH:+:$PYTHONPATH}" \
  "$2/.venv/bin/python" -m fdai
""",
            "_",
            str(self.worktree),
            str(self.repo),
            str(self.model_path),
            self.run_id,
            self.request_topic,
            self.projection_topic,
            str(self.run_root / "core.lock"),
        )
        operator_command = (
            "/usr/bin/bash",
            "-c",
            """
set -euo pipefail
cd "$1"
set -a
source "$2/.fdai/local-operator-service.env"
set +a
export FDAI_OPERATOR_API_LOCAL_AZURE_CLI=0
export FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=0
export FDAI_OPERATOR_API_LOCAL_ENTRA=1
export FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS=http://localhost:5275
export FDAI_LIVE_STAGE_CONSUMER_GROUP_ID="$3-live-stage"
export FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID="$3-semantic-operator"
export FDAI_SEMANTIC_TURN_REQUEST_TOPIC="$4"
export FDAI_SEMANTIC_TURN_PROJECTION_TOPIC="$5"
export FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=
export FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE="${3,,}"
python_path="$1/services/operator-service/src:$1/packages/service-contracts/src"
exec env -u AZURE_CONFIG_DIR \
    PYTHONPATH="$python_path${PYTHONPATH:+:$PYTHONPATH}" \
  "$2/.venv/bin/python" -m uvicorn fdai_operator_service.main:create_app \
  --factory --host 127.0.0.1 --port 8014 --no-access-log
""",
            "_",
            str(self.worktree),
            str(self.repo),
            self.run_id,
            self.request_topic,
            self.projection_topic,
        )
        console_command = (
            "/usr/bin/bash",
            "-c",
            """
set -euo pipefail
cd "$1/console"
export VITE_CACHE_DIR="$2"
export VITE_DEV_MODE=0
export VITE_LOCAL_AZURE_CLI_AUTH=0
export VITE_LOCAL_AZURE_CLI_AUTH_CONFIRM=0
export VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8014
export VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5275 --strictPort
""",
            "_",
            str(self.worktree),
            str(self.run_root / "vite-cache"),
        )
        return (
            ProcessSpec(
                label="core",
                command=core_command,
                command_label="python -m fdai",
                cwd=self.worktree,
                log_path=self.run_root / "core.log",
            ),
            ProcessSpec(
                label="operator",
                command=operator_command,
                command_label="python -m uvicorn fdai_operator_service.main:create_app :8014",
                cwd=self.worktree,
                log_path=self.run_root / "operator.log",
            ),
            ProcessSpec(
                label="console",
                command=console_command,
                command_label="vite :5275",
                cwd=self.worktree / "console",
                log_path=self.run_root / "console.log",
            ),
        )

    def _preserve_artifact(self, artifact: Path, output: Path) -> Path:
        """Copy the governed artifact out of transient scratch into repository evidence."""
        destination = self.evidence_root / output.name / artifact.name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(artifact, destination)
        return destination

    def _prepare(self) -> None:
        self.status.update(
            state="preparing",
            phase="source_binding",
            outputs={
                "strict": str(self.strict_output),
                "seeded_100": str(self.full_output),
            },
            checkpoints={
                "strict": str(self.strict_checkpoint),
                "seeded_100": str(self.full_checkpoint),
            },
        )
        _run_checked(
            (
                sys.executable,
                str(self.repo / "scripts" / "automation" / "validation_queue.py"),
                "check-commit",
                self.source_revision,
            ),
            cwd=self.repo,
            log_path=self.stack_log,
        )
        required = (
            self.model_path,
            self.storage_state,
            self.repo / ".fdai" / "local-runtime.env",
            self.repo / ".fdai" / "local-operator-service.env",
            self.repo / "console" / "node_modules",
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise AssuranceRunError(f"required assurance inputs are missing: {', '.join(missing)}")
        if stat.S_IMODE(self.storage_state.stat().st_mode) != 0o600:
            raise AssuranceRunError("Browser Entra storage state MUST have mode 600")
        if self.strict_checkpoint.exists() or self.full_checkpoint.exists():
            raise AssuranceRunError("fresh assurance checkpoints already exist for this run id")
        occupied = (
            self.strict_output,
            self.full_output,
            self.evidence_root / self.strict_output.name,
            self.evidence_root / self.full_output.name,
        )
        if any(path.exists() for path in occupied):
            raise AssuranceRunError("fresh assurance output already exists for this run id")

        if not (self.worktree / ".git").exists():
            _run_checked(
                (
                    "git",
                    "-C",
                    str(self.repo),
                    "worktree",
                    "add",
                    "--detach",
                    str(self.worktree),
                    self.source_revision,
                ),
                cwd=self.repo,
                log_path=self.stack_log,
            )
        if _git_output(self.worktree, "rev-parse", "HEAD") != self.source_revision:
            raise AssuranceRunError("detached assurance worktree revision mismatch")
        if _git_output(self.worktree, "status", "--short"):
            raise AssuranceRunError("detached assurance worktree is not clean")
        _symlink(self.repo / ".venv", self.worktree / ".venv")
        _symlink(
            self.repo / "console" / "node_modules",
            self.worktree / "console" / "node_modules",
        )
        _symlink(self.repo / "console" / ".env.local", self.worktree / "console" / ".env.local")

        self.status.update(state="preparing", phase="transport_setup")
        _run_checked(
            (
                "docker",
                "exec",
                "fdai-redpanda",
                "rpk",
                "topic",
                "create",
                "--if-not-exists",
                "--partitions",
                "1",
                self.request_topic,
                self.projection_topic,
            ),
            cwd=self.repo,
            log_path=self.stack_log,
        )
