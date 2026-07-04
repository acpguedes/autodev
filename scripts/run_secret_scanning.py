#!/usr/bin/env python3
"""Run AutoDev's dependency-free secret scanner."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.security.secrets import main


if __name__ == "__main__":
    raise SystemExit(main())
