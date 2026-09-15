#!/usr/bin/env python3
"""Generate versioned alert-noise schemas from canonical immutable boundary models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts.alert_noise import AlertEvidence, NoiseAssessment
from fdai_service_contracts.alert_noise_base import AlertContractBase
from fdai_service_contracts.alert_noise_codec import ALERT_WIRE_MODELS, AlertUnavailable
from fdai_service_contracts.alert_noise_evaluation import (
    EvaluationReceipt,
    TemporalEvaluationScenarioSet,
)
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.alert_noise_wire import (
    SignedAlertCommand,
    SignedAlertReadiness,
    SignedAlertResult,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"
MODELS: dict[str, type[AlertContractBase]] = {
    "alert-noise-evidence": AlertEvidence,
    "alert-noise-assessment": NoiseAssessment,
    "alert-noise-plan": AlertChangePlan,
    "alert-noise-command": SignedAlertCommand,
    "alert-noise-result": SignedAlertResult,
    "alert-noise-readiness": SignedAlertReadiness,
    "alert-noise-evaluation": EvaluationReceipt,
    "alert-noise-temporal-scenarios": TemporalEvaluationScenarioSet,
}


def main() -> int:
    """Regenerate only this capability's schemas, or check exact byte parity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    entries = [(name, "1.0.0", model) for name, model in MODELS.items()]
    entries.extend((name, "0.0.0", AlertUnavailable) for name in ALERT_WIRE_MODELS)
    for name, version, model in entries:
        schema = model.model_json_schema()
        schema["$id"] = f"https://fdai.dev/service-contracts/{name}/{version}"
        rendered = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        target = SCHEMAS / name / f"{version}.json"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                mismatches.append(name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
    if mismatches:
        print("Alert schema mismatch: " + ", ".join(mismatches))
    return int(bool(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
