"""``fdai-lifecycle-agent enroll``: submit this installation's own pending enrollment.

The Agent proposes; a human decides. The command signs with the installation's existing
private key, derives Entities and reported state from the Agent's own namespace, reads every
setting from the customer-owned declaration, and POSTs the signed request to the Hub as pending.
It prints only public facts and never retries after an uncertain delivery.

Re-running is idempotent: once the Hub holds a pending, enrolled or rejected record for the
installation, it answers `installation_exists` and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from fdai_deployment_cli.lifecycle_enrollment import (
    ENROLLMENT_PROOF_WINDOW,
    installation_key_id,
    raw_installation_public_key,
    sign_enrollment_payload,
)

from fdai_lifecycle_agent.enrollment import (
    EntityWorkloadSource,
    derive_enrollment_facts,
    enrollment_template,
)
from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError
from fdai_lifecycle_agent.installation_declaration import DeclarationError, load_declaration
from fdai_lifecycle_agent.native_cli import load_installation_identity
from fdai_lifecycle_agent.workload import WorkloadError, is_dns_label

EXIT_OK = 0
EXIT_LOCAL_FAILURE = 2
EXIT_HUB_REFUSED = 3
EXIT_UNCERTAIN = 4
MAX_TIMEOUT_SECONDS = 60.0


class EnrollmentSubmitter(Protocol):
    def submit_enrollment_request(
        self, installation_id: str, signed_payload: bytes, proof: bytes
    ) -> None: ...


type SourceConnector = Callable[[str], EntityWorkloadSource]
type HubConnector = Callable[[str, str, float], AbstractContextManager[EnrollmentSubmitter]]


def register_enroll_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = commands.add_parser(
        "enroll",
        help="Submit this installation's pending enrollment; a human still approves it.",
    )
    command.add_argument("--installation-id", required=True)
    command.add_argument(
        "--installation-key",
        type=Path,
        required=True,
        help="Existing owner-only installation private key; it is never printed or exported.",
    )
    command.add_argument(
        "--declaration",
        type=Path,
        required=True,
        help="Owner-only customer declaration of settings and configuration.",
    )
    command.add_argument("--namespace", required=True, help="Namespace whose workloads to read.")
    command.add_argument("--hub-url", required=True)
    command.add_argument("--hub-scope", required=True, help="Exact api:// Hub /.default scope.")
    command.add_argument("--timeout-seconds", type=float, default=10.0)


@contextmanager
def connect_workload_identity_hub(
    url: str, scope: str, timeout_seconds: float
) -> Iterator[EnrollmentSubmitter]:
    from fdai_lifecycle_agent.remote_auth import WorkloadIdentityAuthorization

    with ExitStack() as resources:
        authorization = WorkloadIdentityAuthorization(scope)
        resources.callback(authorization.close)
        yield resources.enter_context(
            HttpHubClient(url, timeout_seconds=timeout_seconds, authorization=authorization)
        )


def connect_in_cluster_source(namespace: str) -> EntityWorkloadSource:
    # Imported here so that no other command loads a Kubernetes client.
    from fdai_lifecycle_agent.kube import KubernetesCluster

    return KubernetesCluster(in_cluster=True, namespace=namespace)


def run_enroll(
    arguments: argparse.Namespace,
    *,
    clock: Callable[[], datetime],
    connect_source: SourceConnector = connect_in_cluster_source,
    connect_hub: HubConnector = connect_workload_identity_hub,
) -> int:
    try:
        if not math.isfinite(arguments.timeout_seconds) or not (
            0 < arguments.timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("enrollment_timeout_invalid")
        if not is_dns_label(arguments.namespace):
            raise ValueError("enrollment_namespace_invalid")
        declaration = load_declaration(arguments.declaration)
        if declaration.installation_id != arguments.installation_id:
            raise ValueError("enrollment_installation_mismatch")
        key = load_installation_identity(arguments.installation_key)
        entities, reported = derive_enrollment_facts(
            connect_source(arguments.namespace), namespace=arguments.namespace, now=clock()
        )
        requested_at = clock()
        payload, proof = sign_enrollment_payload(
            enrollment_template(declaration, entities, reported), key, requested_at
        )
        key_id = installation_key_id(raw_installation_public_key(key))
    except (ValueError, OSError, WorkloadError, DeclarationError) as error:
        logging.error("lifecycle_agent.enroll_failed error_type=%s", type(error).__name__)
        print(
            "Enrollment was not submitted; verify the declaration, installation key, "
            "in-cluster read access and Entity labels.",
            file=sys.stderr,
        )
        return EXIT_LOCAL_FAILURE
    try:
        with connect_hub(arguments.hub_url, arguments.hub_scope, arguments.timeout_seconds) as hub:
            hub.submit_enrollment_request(arguments.installation_id, payload, proof)
    except HubProtocolError as error:
        return _hub_failure(error)
    except (ValueError, OSError):
        print(
            "Enrollment was not submitted; verify the Hub URL and workload identity.",
            file=sys.stderr,
        )
        return EXIT_LOCAL_FAILURE
    logging.info("lifecycle_agent.enrollment_submitted")
    print(
        json.dumps(
            {
                "installation_id": arguments.installation_id,
                "installation_key_id": key_id,
                "enrollment": "pending",
                "submit_before": (requested_at + ENROLLMENT_PROOF_WINDOW).isoformat(),
            },
            sort_keys=True,
        )
    )
    return EXIT_OK


def _hub_failure(error: HubProtocolError) -> int:
    logging.error("lifecycle_agent.enroll_hub_failed code=%s", error.code or "unknown")
    if error.code == "installation_exists":
        print(
            "The Hub already holds a pending, enrolled or rejected record for this installation; "
            "nothing was changed. Check the Hub's pending enrollment list.",
            file=sys.stderr,
        )
        return EXIT_HUB_REFUSED
    if error.code:
        print(
            f"The Hub refused the enrollment request ({error.code}); nothing was recorded.",
            file=sys.stderr,
        )
        return EXIT_HUB_REFUSED
    print(
        "The delivery result is unknown and was not retried. Check the Hub's pending enrollment "
        "list before running enroll again.",
        file=sys.stderr,
    )
    return EXIT_UNCERTAIN
