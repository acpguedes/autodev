"""Extended Pydantic contracts for specialized agents.

Keeps specialised agent metadata models out of the core ``contracts.py``
so that the existing contracts remain stable.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class SecurityOutput(BaseModel):
    """Structured security-review output."""

    findings: List[str] = Field(default_factory=list)
    severity: str = "info"
    recommendations: List[str] = Field(default_factory=list)


class RefactorOutput(BaseModel):
    """Structured refactoring analysis output."""

    targets: List[str] = Field(default_factory=list)
    smells: List[str] = Field(default_factory=list)
    suggested_changes: List[str] = Field(default_factory=list)


class DocsOutput(BaseModel):
    """Structured documentation generation output."""

    documents: List[str] = Field(default_factory=list)
    sections: List[str] = Field(default_factory=list)
    summary: str = ""


__all__ = ["SecurityOutput", "RefactorOutput", "DocsOutput"]
