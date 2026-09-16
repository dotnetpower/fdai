"""Reviewed provider-neutral telemetry evidence recipe catalog."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from fdai_service_contracts.ontology_query import content_digest

from .telemetry_evidence import (
    TelemetryEvidenceRecipe,
    TelemetryLookbackProfile,
    TelemetryMechanism,
)

TELEMETRY_RECIPE_CATALOG_VERSION: Final[str] = "1.0.0"
TELEMETRY_RECIPE_OUTPUT_SCHEMA_DIGEST: Final[str] = content_digest(
    {
        "schema_version": "1.0.0",
        "columns": {
            "signal_count": "non_negative_integer",
            "observed_until": "rfc3339_or_null",
            "band": ["low", "elevated", "high"],
        },
        "raw_records": False,
    }
)


@dataclass(frozen=True, slots=True)
class ReviewedTelemetryRecipeCatalog:
    """Exact-version lookup for recipes accepted by adaptive investigation."""

    version: str
    recipes: tuple[TelemetryEvidenceRecipe, ...]
    catalog_digest: str

    def __post_init__(self) -> None:
        if self.version != TELEMETRY_RECIPE_CATALOG_VERSION:
            raise ValueError("unsupported telemetry recipe catalog version")
        if not self.recipes:
            raise ValueError("telemetry recipe catalog MUST be non-empty")
        keys = tuple((item.recipe_id, item.version) for item in self.recipes)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("telemetry recipes MUST be sorted and unique")
        if {item.mechanism for item in self.recipes} != set(TelemetryMechanism):
            raise ValueError("telemetry recipe catalog MUST cover every reviewed mechanism")
        if self.catalog_digest != _catalog_digest(self.version, self.recipes):
            raise ValueError("telemetry recipe catalog digest does not match content")

    def get(self, recipe_id: str, version: str) -> TelemetryEvidenceRecipe:
        """Return one exact recipe or fail without selecting a fallback version."""

        try:
            return _recipe_index(self.recipes)[(recipe_id, version)]
        except KeyError as exc:
            raise ValueError("telemetry evidence recipe is not in the reviewed catalog") from exc


def _recipe(
    recipe_id: str,
    mechanism: TelemetryMechanism,
    *,
    lookback: TelemetryLookbackProfile = TelemetryLookbackProfile.FIFTEEN_MINUTES,
    cost_units: int = 10,
) -> TelemetryEvidenceRecipe:
    return TelemetryEvidenceRecipe(
        recipe_id=recipe_id,
        version="1.0.0",
        mechanism=mechanism,
        output_schema_digest=TELEMETRY_RECIPE_OUTPUT_SCHEMA_DIGEST,
        estimated_cost_units=cost_units,
        default_lookback=lookback,
        supports_no_data_refutation=True,
    )


_RECIPES: Final[tuple[TelemetryEvidenceRecipe, ...]] = tuple(
    sorted(
        (
            _recipe("container.restarts", TelemetryMechanism.CONTAINER_RESTARTS),
            _recipe("dependencies.latency", TelemetryMechanism.DEPENDENCY_LATENCY),
            _recipe("errors.timeline", TelemetryMechanism.ERROR_TIMELINE),
            _recipe("guest.shutdown", TelemetryMechanism.GUEST_SHUTDOWN),
            _recipe("requests.failed", TelemetryMechanism.FAILED_REQUESTS),
            _recipe("resource.saturation", TelemetryMechanism.RESOURCE_SATURATION),
            _recipe("throttling.events", TelemetryMechanism.THROTTLING),
            _recipe("traces.slow", TelemetryMechanism.SLOW_TRACES),
        ),
        key=lambda item: (item.recipe_id, item.version),
    )
)


def _recipe_index(
    recipes: tuple[TelemetryEvidenceRecipe, ...],
) -> MappingProxyType[tuple[str, str], TelemetryEvidenceRecipe]:
    return MappingProxyType({(item.recipe_id, item.version): item for item in recipes})


def _catalog_digest(version: str, recipes: tuple[TelemetryEvidenceRecipe, ...]) -> str:
    return content_digest(
        {
            "version": version,
            "recipes": [
                {
                    "recipe_id": item.recipe_id,
                    "version": item.version,
                    "mechanism": item.mechanism.value,
                    "output_schema_digest": item.output_schema_digest,
                    "estimated_cost_units": item.estimated_cost_units,
                    "default_lookback": item.default_lookback.value,
                    "supports_no_data_refutation": item.supports_no_data_refutation,
                }
                for item in recipes
            ],
        }
    )


DEFAULT_TELEMETRY_RECIPE_CATALOG: Final[ReviewedTelemetryRecipeCatalog] = (
    ReviewedTelemetryRecipeCatalog(
        version=TELEMETRY_RECIPE_CATALOG_VERSION,
        recipes=_RECIPES,
        catalog_digest=_catalog_digest(TELEMETRY_RECIPE_CATALOG_VERSION, _RECIPES),
    )
)


__all__ = [
    "DEFAULT_TELEMETRY_RECIPE_CATALOG",
    "TELEMETRY_RECIPE_CATALOG_VERSION",
    "TELEMETRY_RECIPE_OUTPUT_SCHEMA_DIGEST",
    "ReviewedTelemetryRecipeCatalog",
]
