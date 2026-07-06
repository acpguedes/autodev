"""Context Provider extension point + composer (E7-S4).

An extension point analogous to
:class:`backend.repository.providers.RepositoryProvider`: providers
contribute attributable context items, :class:`ContextComposer` runs and
composes them under isolation, and :class:`backend.agents.runtime.AgentRuntime`
attaches the composed result to the runtime context before a handler runs.
"""

from backend.context.composer import ComposedContext, ContextComposer, ProviderConfig
from backend.context.provider import ContextItem, ContextProvider

__all__ = [
    "ComposedContext",
    "ContextComposer",
    "ContextItem",
    "ContextProvider",
    "ProviderConfig",
]
