"""Development-only helpers for the read-only ASGI (G-5).

Physically separated from the production route code so a packaging /
container build can drop the whole subpackage from the production image.
Nothing here is imported at production runtime.

- :mod:`.local` - the Azure CLI-backed interactive factory. It reads actual
  Azure development resources and never seeds runtime evidence. Pytest may
  opt into isolated fixtures explicitly through ``test_fixtures=True``.
"""
