"""Internal framework layer for the pantheon runtime (G-7).

The 15 named pantheon agents (odin, thor, forseti, huginn, heimdall,
var, vidar, bragi, saga, mimir, muninn, norns, njord, freyr, loki) live
flat under ``fdai.agents.*`` because they are a first-class catalog
(see :file:`../../.github/instructions/agent-pantheon.instructions.md`).

Everything else that supports them - the base ``Agent`` protocol, the
bus, the runtime, the registry, the arbitration policy, the
introspection surface, the KPI wiring, the candidate guard, the
divergence ledger, the topic vocabulary - is **framework code** and
lives here under ``fdai.agents._framework.*`` so the pantheon roster
stays the visible surface when a maintainer lists the ``agents/``
directory.

The leading underscore signals **not for external consumption**:
callers SHOULD import from ``fdai.agents`` (the facade), never from
``fdai.agents._framework.<X>``. A fork that reaches into this
subpackage breaks silently on renames or further splits.

Adding a new pantheon member is a **charter change**: it requires an
upstream doc PR to
:file:`../../../docs/roadmap/agents/agent-pantheon.md`, an
`agent-pantheon.instructions.md` update, and the standard fork-lock
review. Adding a helper here does not.
"""

from __future__ import annotations
