#!/usr/bin/env python3
"""Repository entry point for service-owned migrations."""

from service_migrations.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
