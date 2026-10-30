"""Protected-main pool canaries and redacted, independently checked queue evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKFLOW = ".github/workflows/container-supply-chain.yml"
LIMITS = {"control": 4, "general": 64, "docker": 16}
PLAN_NAME = "plan pool canary"
HOLD_NAME = "Hold pool canary capacity"
CHECK_NAME = "Verify canary isolation and Docker runtime"
SCHEMA = "fdai.ci-pool-canary.v1"
ARTIFACTS = Path("artifacts/ci-canary")
FORBIDDEN_ENV = (
    "GITHUB_RUNNER_CREDENTIAL",
    "GITHUB_WEBHOOK_SECRET",
    "GITHUB_PAT",
    "GH_PAT",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "FDAI_RUNNER_BOOTSTRAP",
    "ACTIONS_RUNNER_INPUT_JITCONFIG",
    "RUNNER_JIT_CONFIG",
    "RUNNER_REGISTRATION_TOKEN",
    "CONFIG_JSON",
    "AZURE_CLIENT_SECRET",
    "ARM_CLIENT_SECRET",
    "IDENTITY_ENDPOINT",
    "IDENTITY_HEADER",
    "MSI_ENDPOINT",
    "MSI_SECRET",
    "AZURE_FEDERATED_TOKEN_FILE",
)


class CanaryError(Exception):
    """Redacted, fail-closed canary evidence failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CanaryError(message)


def integer(value: Any, maximum: int = 2**63 - 1) -> int:
    require(
        (type(value) is int or isinstance(value, str))
        and re.fullmatch(r"[1-9][0-9]*", str(value)) is not None,
        "canary integer is invalid",
    )
    result = int(value)
    require(result <= maximum, "canary integer exceeds its limit")
    return result


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str), "canary timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise CanaryError("canary timestamp is invalid") from None
    require(parsed.tzinfo is not None, "canary timestamp must include a timezone")
    return parsed


def object_value(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict), "canary evidence object is invalid")
    return dict(value)


def array(value: Any) -> list[Any]:
    require(isinstance(value, list), "canary evidence array is invalid")
    return list(value)


def text(value: Any) -> str:
    require(isinstance(value, str), "canary evidence text is invalid")
    return str(value)


def number(value: Any) -> float:
    require(type(value) in {int, float}, "canary evidence number is invalid")
    result = float(value)
    require(math.isfinite(result), "canary evidence number is invalid")
    return result


def api_integer(value: Any, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise CanaryError("canary API integer is invalid")
    return value


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "canary observation is missing")
    data = json.loads(path.read_text())
    require(isinstance(data, dict), "canary observation is invalid")
    return dict(data)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, allow_nan=False) + "\n")


@dataclass(frozen=True)
class Canary:
    pool: str
    count: int
    hold_seconds: int
    kind: str
    run_id: int
    attempt: int
    sha: str

    @classmethod
    def from_env(cls) -> Canary:
        require(
            os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("CANARY_ENABLED") == "true",
            "canary requires an explicit protected-main dispatch",
        )
        pool = os.environ.get("CANARY_POOL", "")
        require(pool in LIMITS, "canary pool is invalid")
        sha = os.environ.get("GITHUB_SHA", "")
        require(
            re.fullmatch(r"[0-9a-f]{40}", sha) is not None
            and os.environ.get("CANARY_TARGET_SHA") == sha,
            "canary target must equal this protected-main run",
        )
        hold = integer(os.environ.get("CANARY_HOLD_SECONDS", ""), 180)
        require(hold >= 120, "canary hold must be 120-180 seconds")
        kind = os.environ.get("CANARY_KIND", "")
        require(kind in {"warm", "burst"}, "canary kind is invalid")
        return cls(
            pool,
            integer(os.environ.get("CANARY_COUNT", ""), LIMITS[pool]),
            hold,
            kind,
            integer(os.environ.get("GITHUB_RUN_ID", "")),
            integer(os.environ.get("GITHUB_RUN_ATTEMPT", "")),
            sha,
        )

    def record(self, slot: int) -> dict[str, Any]:
        require(1 <= slot <= self.count, "canary slot is outside this dispatch")
        return {**asdict(self), "schema_version": SCHEMA, "slot": slot}


def assert_isolation() -> None:
    require(
        not any(key in os.environ for key in FORBIDDEN_ENV),
        "credential-bearing canary worker environment",
    )
    require(
        os.environ.get("RUNNER_ENVIRONMENT") == "self-hosted"
        and os.environ.get("RUNNER_OS") == "Linux"
        and os.environ.get("RUNNER_ARCH") == "X64"
        and bool(os.environ.get("RUNNER_NAME")),
        "canary requires a Linux X64 self-hosted worker",
    )


def command(args: list[str], *, data: bytes | None = None, cleanup: bool = False) -> None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed tools and validated canary identifiers
            args,
            input=data,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        if cleanup:
            return
        raise CanaryError("canary Docker smoke failed") from None
    require(cleanup or result.returncode == 0, "canary Docker smoke failed")


def docker_smoke(canary: Canary, slot: int) -> None:
    """Use a local scratch image, with no registry credentials, pulls, or network."""
    directory = ARTIFACTS / f"smoke-{canary.run_id}-{canary.attempt}-{slot}"
    directory.mkdir(parents=True, exist_ok=False)
    docker = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
    tag = f"fdai-ci-canary:{canary.run_id}-{canary.attempt}-{slot}"
    command([*docker, "info", "--format", "{{.ServerVersion}}"])
    command(
        ["/usr/bin/cc", "-static", "-s", "-x", "c", "-o", str(directory / "probe"), "-"],
        data=b"int main(void) { return 0; }\n",
    )
    (directory / "Dockerfile").write_text(
        'FROM scratch\nCOPY probe /probe\nUSER 65534:65534\nENTRYPOINT ["/probe"]\n'
    )
    completed = False
    try:
        command([*docker, "build", "--network=none", "--pull=false", "-t", tag, str(directory)])
        command(
            [
                *docker,
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                tag,
            ]
        )
        completed = True
    finally:
        command([*docker, "image", "rm", tag], cleanup=not completed)


def check_worker(canary: Canary, slot: int) -> None:
    record = canary.record(slot)
    assert_isolation()
    if canary.pool == "docker":
        docker_smoke(canary, slot)
    write_json(
        ARTIFACTS / f"check-{canary.pool}-{slot}.json",
        {
            **record,
            "credential_env_absent": True,
            "docker_verified": canary.pool == "docker",
        },
    )


def hold_worker(canary: Canary, slot: int) -> None:
    record = canary.record(slot)
    checked = read_json(ARTIFACTS / f"check-{canary.pool}-{slot}.json")
    require(
        all(checked.get(key) == value for key, value in record.items()),
        "canary check binding mismatch",
    )
    require(
        checked.get("credential_env_absent") is True
        and checked.get("docker_verified") is (canary.pool == "docker"),
        "canary isolation or Docker evidence is missing",
    )
    assert_isolation()
    started = datetime.now(UTC)
    monotonic = time.monotonic()
    time.sleep(canary.hold_seconds)
    elapsed = time.monotonic() - monotonic
    finished = datetime.now(UTC)
    require(
        elapsed >= canary.hold_seconds and abs((finished - started).total_seconds() - elapsed) <= 1,
        "canary hold timing is inconsistent",
    )
    write_json(
        ARTIFACTS / f"observation-{canary.pool}-{slot}.json",
        {
            **checked,
            "hold_started_at": started.isoformat(),
            "hold_completed_at": finished.isoformat(),
            "elapsed_seconds": elapsed,
            "credential_env_keys_checked": list(FORBIDDEN_ENV),
        },
    )


def step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = array(job.get("steps"))
    require(all(isinstance(row, dict) for row in steps), "canary proof steps are invalid")
    rows = [row for row in steps if row.get("name") == name]
    require(
        len(rows) == 1
        and rows[0].get("conclusion") == "success"
        and rows[0].get("status") == "completed",
        "canary proof step did not succeed",
    )
    return dict(rows[0])


def build_receipt(
    canary: Canary,
    jobs: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    slo: dict[str, Any],
) -> dict[str, Any]:
    """Compute eligible-to-start latency and actual hold overlap, never inferred scale/drain."""
    planners = [job for job in jobs if job.get("name") == PLAN_NAME]
    require(
        len(planners) == 1 and planners[0].get("conclusion") == "success",
        "canary planner did not succeed",
    )
    released = timestamp(planners[0].get("completed_at"))
    selected: dict[int, dict[str, Any]] = {}
    for job in jobs:
        name = job.get("name", "")
        require(isinstance(name, str), "canary job name is invalid")
        match = re.fullmatch(
            r"pool canary / (control|general|docker) / ([0-9]+|\$\{\{ matrix\.slot \}\})", name
        )
        if match is None:
            require(not name.startswith("pool canary / "), "unexpected canary job name")
            require(
                name in {PLAN_NAME, "collect pool canary"} or job.get("conclusion") == "skipped",
                "non-canary work ran during the canary",
            )
            continue
        pool, raw_slot = match.groups()
        if pool != canary.pool:
            require(job.get("conclusion") == "skipped", "an unselected pool executed")
            continue
        slot = integer(raw_slot, canary.count)
        require(
            slot not in selected
            and job.get("conclusion") == "success"
            and job.get("status") == "completed",
            "canary jobs are missing, duplicated or failed",
        )
        selected[slot] = job
    require(
        set(selected) == set(range(1, canary.count + 1)) and len(observations) == canary.count,
        "canary count is incomplete",
    )
    require(
        len({api_integer(row.get("id")) for row in selected.values()}) == canary.count
        and len({api_integer(row.get("runner_id")) for row in selected.values()}) == canary.count
        and len({row.get("runner_name") for row in selected.values()}) == canary.count
        and all(
            isinstance(row.get("runner_name"), str) and bool(row["runner_name"])
            for row in selected.values()
        ),
        "canary did not use distinct jobs and runners",
    )
    by_slot: dict[int, dict[str, Any]] = {}
    for observation in observations:
        slot = integer(observation.get("slot"), canary.count)
        require(slot not in by_slot, "duplicate canary observation")
        require(
            all(observation.get(key) == value for key, value in canary.record(slot).items()),
            "canary observation binding mismatch",
        )
        by_slot[slot] = observation
    require(set(by_slot) == set(selected), "canary observation slots are incomplete")
    rows: list[dict[str, Any]] = []
    for slot, job in sorted(selected.items()):
        record = by_slot[slot]
        require(
            isinstance(job.get("labels"), list)
            and all(isinstance(label, str) for label in job["labels"]),
            "canary labels are invalid",
        )
        labels = {str(label).casefold() for label in job.get("labels", [])}
        require(
            labels == {"self-hosted", "linux", "x64", f"fdai-ci-{canary.pool}"}
            and len(job["labels"]) == 4,
            "canary runner labels do not match its fixed pool",
        )
        step(job, CHECK_NAME)
        hold = step(job, HOLD_NAME)
        require(
            record.get("credential_env_absent") is True
            and record.get("credential_env_keys_checked") == list(FORBIDDEN_ENV)
            and record.get("docker_verified") is (canary.pool == "docker"),
            "canary credential or Docker evidence is invalid",
        )
        elapsed = number(record.get("elapsed_seconds"))
        require(elapsed >= canary.hold_seconds, "canary hold was too short")
        start, end = (
            timestamp(record.get("hold_started_at")),
            timestamp(record.get("hold_completed_at")),
        )
        require(
            abs((end - start).total_seconds() - elapsed) <= 1
            and (start - timestamp(hold.get("started_at"))).total_seconds() >= -1
            and (timestamp(hold.get("completed_at")) - end).total_seconds() >= -1
            and (start - timestamp(job.get("started_at"))).total_seconds() >= -1
            and (timestamp(job.get("completed_at")) - end).total_seconds() >= -1,
            "canary timing conflicts with GitHub job evidence",
        )
        queued = (timestamp(job.get("started_at")) - released).total_seconds()
        require(queued >= 0, "canary started before its planner completed")
        rows.append(
            {
                "job_id": integer(job.get("id")),
                "slot": slot,
                "conclusion": "success",
                "queue_seconds": queued,
                "hold_seconds": elapsed,
                "hold_started_at": start.isoformat(),
                "hold_completed_at": end.isoformat(),
            }
        )
    return {
        **asdict(canary),
        **measure(canary, rows, slo),
        "schema_version": SCHEMA,
        "complete": True,
        "successful": True,
        "expected_jobs": canary.count,
        "requested_concurrency": canary.count,
        "jobs": rows,
        "queue_basis": "GitHub planner.completed_at to job.started_at",
        "concurrency_basis": (
            "worker monotonic-backed hold windows checked against GitHub step times"
        ),
        "credential_env_absence_verified": True,
        "distinct_runners_verified": True,
        "github_jobs_verified": True,
        "docker_verified": canary.pool == "docker",
        "activation_ready": False,
        "authority": "none",
        "remaining_evidence": ["independent controller safe-drain and reserve observations"],
        "statistical_limit": "single-run nearest-rank observations, not a population guarantee",
    }


def measure(canary: Canary, rows: list[dict[str, Any]], slo: dict[str, Any]) -> dict[str, Any]:
    require(
        len(rows) == canary.count
        and {integer(row.get("slot"), canary.count) for row in rows}
        == set(range(1, canary.count + 1))
        and len({integer(row.get("job_id")) for row in rows}) == canary.count,
        "canary receipt count is invalid",
    )
    intervals: list[tuple[datetime, int]] = []
    for row in rows:
        require(row.get("conclusion") == "success", "canary receipt contains failed work")
        queued, held = number(row.get("queue_seconds")), number(row.get("hold_seconds"))
        require(queued >= 0 and held >= canary.hold_seconds, "canary receipt durations are invalid")
        start, end = timestamp(row.get("hold_started_at")), timestamp(row.get("hold_completed_at"))
        require(
            abs((end - start).total_seconds() - held) <= 1, "canary receipt hold is inconsistent"
        )
        intervals.extend(((start, 1), (end, -1)))
    active = peak = 0
    for _, delta in sorted(intervals, key=lambda value: (value[0], value[1])):
        active += delta
        peak = max(peak, active)
    overlap = (
        min(value[0] for value in intervals if value[1] == -1)
        - max(value[0] for value in intervals if value[1] == 1)
    ).total_seconds()
    queues = sorted(row["queue_seconds"] for row in rows)
    p95, p99 = (queues[math.ceil(len(queues) * q) - 1] for q in (0.95, 0.99))
    passed = peak == canary.count and overlap >= 5 and max(queues) <= slo["maximum_queue_seconds"]
    passed = passed and p99 <= slo["burst_queue_p99_seconds"]
    if canary.kind == "warm":
        passed = passed and p95 <= slo["warm_queue_p95_seconds"]
    return {
        "passed": passed,
        "peak_concurrency": peak,
        "all_jobs_overlap_seconds": max(0, overlap),
        "queue_p95_seconds": p95,
        "queue_p99_seconds": p99,
        "queue_max_seconds": max(queues),
    }


def validate_receipt(receipt: dict[str, Any], slo: dict[str, Any]) -> dict[str, Any]:
    """Validate pre-cutover queue evidence without claiming full activation or safe drain."""
    pool = text(receipt.get("pool"))
    require(pool in LIMITS, "canary receipt pool is invalid")
    hold = integer(receipt.get("hold_seconds"), 180)
    require(
        hold >= 120 and receipt.get("kind") in {"warm", "burst"},
        "canary receipt hold or kind is invalid",
    )
    sha = text(receipt.get("sha"))
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "canary receipt source is invalid")
    canary = Canary(
        pool,
        integer(receipt.get("count"), LIMITS[pool]),
        hold,
        receipt["kind"],
        integer(receipt.get("run_id")),
        integer(receipt.get("attempt")),
        sha,
    )
    require(
        receipt.get("schema_version") == SCHEMA
        and receipt.get("complete") is True
        and receipt.get("successful") is True
        and receipt.get("activation_ready") is False
        and receipt.get("authority") == "none"
        and receipt.get("github_jobs_verified") is True
        and receipt.get("github_run_verified") is True
        and receipt.get("credential_env_absence_verified") is True
        and receipt.get("distinct_runners_verified") is True
        and receipt.get("docker_verified") is (pool == "docker"),
        "canary receipt proof is incomplete",
    )
    rows = [object_value(row) for row in array(receipt.get("jobs"))]
    measured = measure(canary, rows, slo)
    require(
        all(receipt.get(key) == value for key, value in measured.items()),
        "canary receipt metrics were modified",
    )
    return {
        **measured,
        "activation_ready": False,
        "authority": "none",
        "remaining_evidence": ["independent controller safe-drain and reserve observations"],
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise CanaryError("canary GitHub evidence unavailable")


def collect(canary: Canary) -> dict[str, Any]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None,
        "canary repository is invalid",
    )
    token = os.environ.get("CANARY_GITHUB_TOKEN", "")
    require(bool(token) and "\n" not in token and "\r" not in token, "canary read token is missing")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 120

    def get(path: str) -> dict[str, Any]:
        require(time.monotonic() < deadline, "canary collection deadline exceeded")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with opener.open(request, timeout=15) as response:
                require(response.status == 200, "canary GitHub evidence unavailable")
                raw = response.read(8_000_001)
            require(len(raw) <= 8_000_000, "canary GitHub evidence is oversized")
            data = json.loads(raw)
            require(isinstance(data, dict), "canary GitHub evidence is invalid")
            return dict(data)
        except (OSError, ValueError):
            raise CanaryError("canary GitHub evidence unavailable") from None

    base = f"/actions/runs/{canary.run_id}/attempts/{canary.attempt}"
    run = get(base)
    repository_record = object_value(run.get("repository"))
    require(
        api_integer(run.get("id")) == canary.run_id
        and api_integer(run.get("run_attempt")) == canary.attempt
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and run.get("head_sha") == canary.sha
        and run.get("path") == WORKFLOW
        and api_integer(repository_record.get("id"))
        == integer(os.environ.get("GITHUB_REPOSITORY_ID", ""))
        and repository_record.get("full_name") == repository,
        "canary run binding mismatch",
    )
    jobs: list[dict[str, Any]] = []
    seen: set[int] = set()
    expected_total: int | None = None
    for page in range(1, 101):
        data = get(f"{base}/jobs?per_page=100&page={page}")
        batch, total = array(data.get("jobs")), api_integer(data.get("total_count"), 0)
        require(
            len(batch) <= 100 and (expected_total is None or total == expected_total),
            "canary job page is invalid",
        )
        expected_total = total
        for job in batch:
            require(
                isinstance(job, dict) and api_integer(job.get("id")) not in seen,
                "canary job pages contain duplicates",
            )
            require(
                job.get("run_id") == canary.run_id and job.get("head_sha") == canary.sha,
                "canary job binding mismatch",
            )
            seen.add(api_integer(job.get("id")))
            jobs.append(job)
        if len(jobs) == total:
            break
        require(len(batch) == 100 and len(jobs) < total, "canary job pagination is incomplete")
    else:
        raise CanaryError("canary job pagination limit exceeded")
    observations = [
        read_json(path) for path in Path("canary-observations").glob("observation-*.json")
    ]
    by_slot = {
        int(obs["slot"]): obs
        for obs in observations
        if isinstance(obs.get("slot"), int)
        and "hold_started_at" in obs
        and "hold_completed_at" in obs
    }
    for job in jobs:
        name = str(job.get("name", ""))
        match = re.fullmatch(r"pool canary / (control|general|docker) / ([0-9]+)", name)
        completed_steps = {
            row.get("name")
            for row in (job.get("steps") or [])
            if isinstance(row, dict)
            and row.get("conclusion") == "success"
            and row.get("status") == "completed"
        }
        if (
            match is not None
            and match.group(1) == canary.pool
            and not ({CHECK_NAME, HOLD_NAME} <= completed_steps)
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"
            and int(match.group(2)) in by_slot
        ):
            obs = by_slot[int(match.group(2))]
            job["steps"] = [
                {"name": CHECK_NAME, "status": "completed", "conclusion": "success"},
                {
                    "name": HOLD_NAME,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": obs["hold_started_at"],
                    "completed_at": obs["hold_completed_at"],
                },
            ]
    policy = read_json(Path("config/ci-runner-pools.json"))
    return {**build_receipt(canary, jobs, observations, policy["slo"]), "github_run_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "check", "hold", "collect"))
    args = parser.parse_args()
    try:
        canary = Canary.from_env()
        assert_isolation()
        if args.operation == "plan":
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                for key, value in asdict(canary).items():
                    output.write(f"{key}={value}\n")
                for pool in LIMITS:
                    matrix = {
                        "slot": list(range(1, canary.count + 1)) if pool == canary.pool else [0]
                    }
                    output.write(f"matrix_{pool}={json.dumps(matrix)}\n")
        elif args.operation == "collect":
            receipt = collect(canary)
            write_json(ARTIFACTS / "receipt.json", receipt)
            return 0 if receipt["passed"] else 1
        else:
            slot = integer(os.environ.get("CANARY_SLOT", ""), canary.count)
            if args.operation == "check":
                check_worker(canary, slot)
            else:
                hold_worker(canary, slot)
    except Exception as error:
        message = str(error) if isinstance(error, CanaryError) else "canary evidence is invalid"
        if args.operation == "collect":
            write_json(
                ARTIFACTS / "receipt.json",
                {
                    "schema_version": SCHEMA,
                    "complete": False,
                    "successful": False,
                    "passed": False,
                    "activation_ready": False,
                    "authority": "none",
                    "error": message,
                },
            )
        print(f"canary: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
