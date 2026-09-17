# FDAI AKS Commerce Scenario

This package maps a public commerce journey to exact AKS, messaging, SLO, and recovery evidence.
It contains no tenant values and grants no execution authority.

## Layout

| Path | Responsibility |
|------|----------------|
| `assessment.py` | Deterministic business-impact reduction |
| `coordinator.py` | Bounded collection, projection, and retention |
| `synthetic.py` | Identity-free Playwright storefront journey |
| `resources/` | Immutable topology and workload SLO declarations |

## Testing

Run `uv run pytest -q --no-cov extensions/aks-commerce/tests`.
