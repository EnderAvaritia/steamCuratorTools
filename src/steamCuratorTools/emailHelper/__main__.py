"""Launch the email helper GUI with ``python -m steamCuratorTools.emailHelper``."""

from __future__ import annotations

import sys

from .gui import main

if __name__ == "__main__":
    sys.exit(main())