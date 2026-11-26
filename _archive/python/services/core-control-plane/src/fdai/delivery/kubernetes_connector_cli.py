"""Explicit standalone connector workloads using the existing Core distribution."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from fdai_service_contracts import ServiceDescriptor, ServiceKind, record_runtime_scope_receipt

from fdai.delivery.kubernetes_connector_runtime import (
    ConnectorRuntimeConfig,
    load_connector_config,
    observe_events_once,
    observe_once,
    run_gateway,
)


async def _observe(config: ConnectorRuntimeConfig) -> dict[str, object]:
    """Deliver the snapshot first; an Event failure is reported but never hides that delivery."""
    result = await observe_once(config)
    try:
        result["events"] = await observe_events_once(config)
    except Exception as error:
        result["events"] = {"status": "unavailable", "error_type": type(error).__name__}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("observe", "observe-once", "observe-events-once", "serve")
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = load_connector_config(args.config)
        record_runtime_scope_receipt(
            ServiceDescriptor(
                service_id="core-control-plane",
                distribution="fdai-core-control-plane",
                image="fdai-core-control-plane",
                entrypoint="fdai-kubernetes-connector",
                kind=ServiceKind.CONTROL_PLANE,
            )
        )
        if args.operation == "observe-once":
            print(json.dumps(asyncio.run(observe_once(config))))
        elif args.operation == "observe-events-once":
            print(json.dumps(asyncio.run(observe_events_once(config))))
        elif args.operation == "observe":
            print(json.dumps(asyncio.run(_observe(config))))
        else:
            run_gateway(config)
        return 0
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "connector_configuration_or_runtime_failed",
                    "error_type": type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
