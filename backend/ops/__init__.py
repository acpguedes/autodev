"""Operational tooling for packaging, self-host bootstrap, and upgrades (E34).

Distinct from ``backend.config`` (declarative runtime settings) and
``backend.persistence`` (data access): this package holds the day-2
operator-facing surfaces the ``autodev`` CLI exposes — version/build
metadata, preflight diagnostics, bootstrap, and upgrade — matching E34's
scope boundary (packaging, distribution, bootstrap, upgrade) versus E14's
(CLI command UX).
"""

from __future__ import annotations
