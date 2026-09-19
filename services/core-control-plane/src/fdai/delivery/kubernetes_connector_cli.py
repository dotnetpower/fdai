"""Explicit standalone connector workloads using the existing Core distribution."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from fdai_service_contracts import ServiceDescriptor, ServiceKind, record_runtime_scope_receipt

from fdai.delivery.kubernetes_connector_runtime import (
    load_connector_config,
    observe_once,
    run_gateway,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("observe-once", "serve"))
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
        else:
            run_gateway(config)
        return 0
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        print(
            json.dumps(
                {"status": "unavailable", "reason": "connector_configuration_or_runtime_failed"}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
