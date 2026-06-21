"""Built-in skills package.

Importing this package registers all three deterministic built-in skills.
"""

from backend.skills.builtin import (  # noqa: F401 — side-effect imports
    extract_symbols_lexical,
    render_checklist,
    summarize_diff,
)

__all__ = ["summarize_diff", "extract_symbols_lexical", "render_checklist"]
