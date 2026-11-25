"""Model providers: adapters between the neutral conversation and a vendor API.

``create_provider`` is the only place that maps a configured model's
``provider`` setting to an implementation. Adding a vendor means adding a
module here and one branch there; the agent loop does not change.
"""

from __future__ import annotations

from typing import Any

from .base import ModelProvider, ProviderError
from .openai_compatible import OpenAICompatibleProvider
from .openai_responses import OpenAIResponsesProvider

# openai_compatible: /chat/completions, which most services speak. openai_responses: OpenAI's
# /responses, which its newest models need for tools (the OpenAI preset uses it).
PROVIDER_KINDS = ("openai_compatible", "openai_responses")

__all__ = ["ModelProvider", "ProviderError", "PROVIDER_KINDS", "create_provider"]


def create_provider(model: dict[str, Any], no_thinking: bool = False) -> ModelProvider:
    """Build the provider for one entry of the ``models`` settings.

    ``no_thinking`` asks a reasoning model on this computer to answer without hidden thinking, for
    short tasks (``OpenAICompatibleProvider``); the Responses provider ignores it.
    """
    kind = model.get("provider")
    if kind == "openai_compatible":
        return OpenAICompatibleProvider(base_url=model["base_url"], model=model["model"],
                                        api_key=model.get("api_key", ""), headers=model.get("headers") or {},
                                        no_thinking=no_thinking)
    if kind in PROVIDER_KINDS:
        return OpenAIResponsesProvider(base_url=model["base_url"], model=model["model"],
                                       api_key=model.get("api_key", ""), headers=model.get("headers") or {})
    raise ProviderError(f"unknown model provider '{kind}'")
