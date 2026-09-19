#!/usr/bin/env python3
"""Generate connector metadata schemas; semantic admission remains mandatory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts.cluster_connector import (
    ConnectorEvidence,
    ConnectorRegistration,
    ConnectorWork,
)
from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentContext,
    ObserverDeploymentProposal,
)
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"
MODELS: dict[str, type[BaseModel]] = {
    "cluster-connector-evidence": ConnectorEvidence,
    "cluster-connector-registration": ConnectorRegistration,
    "cluster-connector-work": ConnectorWork,
    "observer-deployment-context": ObserverDeploymentContext,
    "observer-deployment-proposal": ObserverDeploymentProposal,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, model in MODELS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://fdai.dev/service-contracts/{name}/1.0.0"
        rendered = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        path = OUTPUT / name / "1.0.0.json"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
    if stale:
        print("cluster-connector-schemas: stale: " + ", ".join(stale))
        return 1
    print("cluster-connector-schemas: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
