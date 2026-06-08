"""Module entry point: ``python -m filerouter ...`` delegates to the CLI.

The console-script entry point declared in pyproject.toml is
``filerouter.__main__:main``; ``main`` is imported here from the CLI so both the
script and ``python -m filerouter`` share one code path.
"""

from __future__ import annotations

import sys

from filerouter.cli.commands import main  # re-exported for console_scripts

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
