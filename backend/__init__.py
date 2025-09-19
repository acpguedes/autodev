"""Backend package for the AutoDev Architect project."""

from importlib import metadata


def get_version() -> str:
    """Return the installed version of the backend package.

    When running from source the package might not be installed; in that case we
    fall back to returning ``"0.0.0"`` to keep tooling stable.
    """

    try:
        return metadata.version("autodev-backend")
    except metadata.PackageNotFoundError:
        return "0.0.0"


__all__ = ["get_version"]
