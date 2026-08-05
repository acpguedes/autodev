"""Provider-neutral model contracts plus legacy LangChain factory utilities."""

from .contracts import (
    AttemptTelemetry,
    EstimatedCost,
    ExecutionMetadata,
    MessageContent,
    ModelCapabilities,
    ModelGatewayError,
    ModelProvider,
    ModelRateLimitError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    ModelUnavailableError,
    NormalizedMessage,
    StreamChunk,
    StreamingModelProvider,
    StructuredOutput,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

from .factory import (
    LLMConfigurationError,
    StubChatModel,
    get_chat_model,
    is_configured_model,
)
from .errors import (
    ModelAuthenticationError,
    ModelBudgetExceededError,
    ModelInvalidRequestError,
    ModelProviderError,
    ModelProviderNotConfiguredError,
    ModelUnsupportedCapabilityError,
    redact_error_message,
)
from .gateway import ModelGateway
from .langchain_adapter import LangChainModelProvider
from .legacy_adapter import LegacyLLMProviderAdapter
from .model_config import (
    ModelConfig,
    ModelConfigError,
    ModelLimits,
    ModelTarget,
    parse_model_config,
)
from .registry import ModelProviderRegistry, resolve_model_config
from .stub_provider import StubModelOutput, StubModelProvider, StubProviderCall

__all__ = [
    "AttemptTelemetry",
    "EstimatedCost",
    "ExecutionMetadata",
    "LLMConfigurationError",
    "MessageContent",
    "ModelCapabilities",
    "ModelAuthenticationError",
    "ModelBudgetExceededError",
    "ModelConfig",
    "ModelConfigError",
    "ModelGatewayError",
    "ModelGateway",
    "ModelInvalidRequestError",
    "ModelLimits",
    "ModelProvider",
    "ModelProviderError",
    "ModelProviderNotConfiguredError",
    "ModelProviderRegistry",
    "ModelRateLimitError",
    "ModelRequest",
    "ModelResponse",
    "ModelTarget",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "ModelUnsupportedCapabilityError",
    "NormalizedMessage",
    "StubChatModel",
    "StubModelOutput",
    "StubModelProvider",
    "StubProviderCall",
    "StreamChunk",
    "StreamingModelProvider",
    "StructuredOutput",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "get_chat_model",
    "is_configured_model",
    "parse_model_config",
    "LangChainModelProvider",
    "LegacyLLMProviderAdapter",
    "redact_error_message",
    "resolve_model_config",
]
