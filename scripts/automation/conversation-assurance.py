#!/usr/bin/env python3
"""Run the explicit Pantheon conversation-assurance CLI."""

import sys

from conversation_assurance_cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "improve":
        from conversation_assurance_improvement_cli import main as improvement_main

        raise SystemExit(improvement_main(sys.argv[2:]))
    raise SystemExit(main())
