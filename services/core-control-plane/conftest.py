"""Make this service's own `tests` package importable before its modules load.

The repository root owns a `tests/` directory with no package marker, so on a
`sys.path` that reaches the root first, `import tests` binds to that namespace and
every `tests.core.*` helper import fails. Putting this service root first makes the
regular package here win regardless of invocation, environment, or worker process.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = str(Path(__file__).resolve().parent)

if _SERVICE_ROOT in sys.path:
    sys.path.remove(_SERVICE_ROOT)
sys.path.insert(0, _SERVICE_ROOT)

# A `tests` already bound to another root would shadow this service's package for
# the rest of the session, so drop that binding and let the next import resolve here.
_bound = sys.modules.get("tests")
if _bound is not None and getattr(_bound, "__file__", None) is None:
    for name in [key for key in sys.modules if key == "tests" or key.startswith("tests.")]:
        del sys.modules[name]
