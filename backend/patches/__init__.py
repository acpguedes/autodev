"""Patches package — diff generation and flag-gated application."""

from backend.patches.engine import apply_patch, generate_patch
from backend.patches.models import Patch, PatchResult

__all__ = [
    "Patch",
    "PatchResult",
    "generate_patch",
    "apply_patch",
]
