"""Validate Trivy exception metadata and expiration before the Trivy scan runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.security.exceptions import (  # noqa: E402
    SecurityExceptionError,
    validate_trivy_exceptions,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate Trivy exception metadata and expiration.

    Args:
        argv: Argument vector to parse; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` if every exception is well-formed and unexpired, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".trivyignore.yaml")
    args = parser.parse_args(argv)
    try:
        exceptions = validate_trivy_exceptions(Path(args.path))
    except SecurityExceptionError as exc:
        print(f"security exception policy invalid: {exc}", file=sys.stderr)
        return 1
    print(f"security exceptions valid: {len(exceptions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
