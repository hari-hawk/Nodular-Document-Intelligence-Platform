"""LLM provider adapters.

Each provider implements `BaseProvider.call(...)` returning
`(text, raw, input_tokens, output_tokens)`. The provider registry
(`get_provider(name)`) resolves a string id to an instance lazily.

Adding a new provider takes three steps:
  1. subclass BaseProvider in a new module under this package
  2. register it via `register_provider("name", FactoryFn)` at module-load time
  3. enable it in `kernel/provider_router.py` for the organ tiers it supports
"""
from mdi.kernel.providers.base import (
    BaseProvider,
    ProviderCallResult,
    ProviderError,
    ProviderNotConfigured,
    get_provider,
    list_providers,
    register_provider,
)
from mdi.kernel.providers.anthropic_provider import AnthropicProvider
from mdi.kernel.providers.gemini_provider import GeminiProvider

__all__ = [
    "BaseProvider",
    "ProviderCallResult",
    "ProviderError",
    "ProviderNotConfigured",
    "get_provider",
    "list_providers",
    "register_provider",
    "AnthropicProvider",
    "GeminiProvider",
]
