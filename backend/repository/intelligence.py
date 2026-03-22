"""Lightweight repository intelligence used by the navigator and API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(slots=True)
class RepositoryFileMatch:
    """Represents a file selected as relevant for a query."""

    path: str
    score: int
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class RepositoryContext:
    """Structured repository context returned for a query."""

    query: str
    root: str
    total_files: int
    top_directories: list[str]
    candidate_files: list[RepositoryFileMatch]
    inventory_sample: list[str]
    matched_terms: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "root": self.root,
            "total_files": self.total_files,
            "top_directories": list(self.top_directories),
            "candidate_files": [item.to_dict() for item in self.candidate_files],
            "inventory_sample": list(self.inventory_sample),
            "matched_terms": list(self.matched_terms),
        }


class RepositoryIntelligenceService:
    """Collect and rank repository context without requiring external infrastructure."""

    _ignored_directories = {
        ".git",
        ".next",
        ".venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".turbo",
        ".idea",
        ".vscode",
    }

    _preferred_extensions = {
        ".md",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".yml",
        ".yaml",
        ".toml",
        ".sh",
        ".tf",
    }

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = (project_root or Path.cwd()).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def build_context(self, query: str, limit: int = 8) -> RepositoryContext:
        normalized_query = query.strip()
        files = self._list_files()
        top_directories = self._top_directories(files)
        matches = self._rank_files(files, normalized_query, limit=limit)
        inventory_sample = [self._relative_path(path) for path in files[: min(12, len(files))]]
        matched_terms = self._extract_terms(normalized_query)
        return RepositoryContext(
            query=normalized_query,
            root=str(self._root),
            total_files=len(files),
            top_directories=top_directories,
            candidate_files=matches,
            inventory_sample=inventory_sample,
            matched_terms=matched_terms,
        )

    def _list_files(self) -> list[Path]:
        files: list[Path] = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            if self._should_ignore(path):
                continue
            if path.suffix and path.suffix not in self._preferred_extensions:
                continue
            files.append(path)
        return files

    def _should_ignore(self, path: Path) -> bool:
        return any(part in self._ignored_directories for part in path.parts)

    def _rank_files(self, files: Sequence[Path], query: str, limit: int) -> list[RepositoryFileMatch]:
        terms = self._extract_terms(query)
        if not terms:
            return [
                RepositoryFileMatch(path=self._relative_path(path), score=0, reasons=["inventory_sample"])
                for path in files[:limit]
            ]

        scored: list[RepositoryFileMatch] = []
        for path in files:
            relative_path = self._relative_path(path)
            path_lower = relative_path.lower()
            name_lower = path.name.lower()
            parent_lower = str(path.parent.relative_to(self._root)).lower() if path.parent != self._root else ""
            score = 0
            reasons: list[str] = []

            for term in terms:
                if term in name_lower:
                    score += 5
                    reasons.append(f"filename:{term}")
                elif term in path_lower:
                    score += 3
                    reasons.append(f"path:{term}")
                elif term in parent_lower:
                    score += 2
                    reasons.append(f"directory:{term}")

            if score <= 0:
                continue

            preferred_boost = 2 if path.name.lower() in {"readme.md", "description.md", "docker-compose.yml"} else 0
            scored.append(
                RepositoryFileMatch(
                    path=relative_path,
                    score=score + preferred_boost,
                    reasons=self._unique(reasons),
                )
            )

        scored.sort(key=lambda item: (-item.score, item.path))
        return scored[:limit]

    def _top_directories(self, files: Iterable[Path]) -> list[str]:
        counts: dict[str, int] = {}
        for path in files:
            relative_parts = path.relative_to(self._root).parts
            if len(relative_parts) < 2:
                continue
            first = relative_parts[0]
            counts[first] = counts.get(first, 0) + 1
        return [name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:6]]

    def _extract_terms(self, query: str) -> list[str]:
        stop_words = {
            "a",
            "the",
            "do",
            "da",
            "de",
            "e",
            "o",
            "os",
            "as",
            "to",
            "for",
            "and",
            "agente",
            "configurar",
            "implementar",
            "etapa",
            "proxima",
            "próxima",
        }
        terms: list[str] = []
        for chunk in query.replace("/", " ").replace("_", " ").replace("-", " ").split():
            normalized = chunk.strip().lower().strip(".,:;!?()[]{}\"'")
            if len(normalized) < 3 or normalized in stop_words:
                continue
            terms.append(normalized)
        return self._unique(terms)

    def _relative_path(self, path: Path) -> str:
        return str(path.relative_to(self._root))

    def _unique(self, items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered
