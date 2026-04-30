"""LLM provider adapters."""

from .base import LLMProvider, ProviderError, ProviderTimeoutError
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

__all__ = [
    "LLMProvider",
    "OllamaProvider",
    "OpenAICompatProvider",
    "ProviderError",
    "ProviderTimeoutError",
]


def make_provider(
    provider: str,
    *,
    endpoint: str,
    model_name: str,
    api_key: str | None = None,
) -> LLMProvider:
    """Factory used by the registry: choose adapter by name."""

    if provider == "ollama":
        return OllamaProvider(endpoint=endpoint, model_name=model_name)
    if provider in ("vllm", "openai_compat"):
        # vLLM exposes an OpenAI-compatible API; same adapter.
        return OpenAICompatProvider(endpoint=endpoint, model_name=model_name, api_key=api_key)
    raise ValueError(f"unknown provider: {provider}")
