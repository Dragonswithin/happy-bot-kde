"""Online AI services the AI Model page offers by name, with directions for getting a key.

Each preset is what a person needs to go from "I use Claude" to a working model without knowing an
API address: the service's OpenAI-compatible address (``base_url``, used through
``providers.openai_compatible``, or OpenAI's own Responses API when ``provider`` says
``openai_responses``), the page where keys are made (``key_url``), two or three plain
steps (``key_steps``), where the user's words go (``privacy``), and suggested models (``models``,
each ``{"id", "label"}``, best start first, with prices per million tokens when the service
publishes them, copied into the model entry for the spending cap). ``context_window`` is used when
the service does not report one. ``model_setup.use`` fills a model entry from the preset; the
settings page lists them through ``GET /models/presets`` (``listing``).

Presets are suggestions the user picks from; nothing here is used unless chosen, and services not
listed are added by hand. Every entry was checked against the service's own documentation on the
date in ``CHECKED``; addresses and model names change, so update them deliberately and keep the
suggested models to ones the service documents as supporting tool calls. Where a service's own
documents disagree (OpenAI's newer models limit tool calls on this API), the test that
``model_setup.use`` runs when a model is added is what tells the user whether it can act. Meta's
key page address could not be confirmed, so its ``key_url`` is the developer site and its steps
say where to click.
"""

from __future__ import annotations

import copy
from typing import Any

CHECKED = "2026-11-24"

PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "claude", "title": "Claude",
        "description": "Anthropic's Claude models, strong at careful reasoning, writing and using tools.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Anthropic.",
        "base_url": "https://api.anthropic.com/v1",
        "key_url": "https://platform.claude.com/settings/keys",
        "key_steps": "Sign in to the Claude Console and choose Create key. Pick a workspace for it (Default is "
                     "fine), then copy the key: it is shown only once. A Claude.ai subscription is separate: the "
                     "Console bills API use on its own.",
        "context_window": 1_000_000,
        "models": [
            {"id": "claude-opus-5-5", "label": "best for most things", "input_price": 4, "output_price": 20},
            {"id": "claude-sonnet-5-5", "label": "faster", "input_price": 2, "output_price": 10},
            {"id": "claude-haiku-5-5", "label": "fastest, cheapest"},
        ],
    },
    {
        "id": "openai", "title": "OpenAI",
        "description": "The company behind ChatGPT, with its newest GPT models, paid per use.",
        "privacy": "Whatever Happy Bot reads for a request is sent to OpenAI.",
        "base_url": "https://api.openai.com/v1",
        # Its newest models refuse tools on /chat/completions and need the Responses API.
        "provider": "openai_responses",
        "key_url": "https://platform.openai.com/api-keys",
        "key_steps": "Sign in to the OpenAI platform, choose Create new secret key, and copy it. A ChatGPT "
                     "subscription is separate: API use is billed on its own.",
        "models": [
            {"id": "gpt-6.2-sol", "label": "good start"},
            {"id": "gpt-6.2-astra", "label": "strongest"},
            {"id": "gpt-6-luna", "label": "cheapest"},
        ],
    },
    {
        "id": "gemini", "title": "Google Gemini",
        "description": "Google's Gemini models, with a free tier from Google AI Studio.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Google.",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_url": "https://aistudio.google.com/apikey",
        "key_steps": "Sign in to Google AI Studio with your Google account, choose Create API key, and copy it.",
        "models": [
            {"id": "gemini-4-hydrogen", "label": "fast, good start"},
            {"id": "gemini-4-carbon", "label": "strongest"},
        ],
    },
    {
        "id": "grok", "title": "Grok (xAI)",
        "description": "xAI's Grok models.",
        "privacy": "Whatever Happy Bot reads for a request is sent to xAI.",
        "base_url": "https://api.x.ai/v1",
        "key_url": "https://console.x.ai/team/default/api-keys",
        "key_steps": "Sign in to the xAI console, open API Keys, create a key and copy it.",
        "models": [
            {"id": "grok-4.7", "label": "strongest"},
            {"id": "grok-4.3", "label": "cheaper"},
        ],
    },
    {
        "id": "qwen", "title": "Qwen",
        "description": "Alibaba Cloud's Qwen models (international region). Keys work only in the region they "
                       "were made in; for a US account choose Qwen (US).",
        "privacy": "Whatever Happy Bot reads for a request is sent to Alibaba Cloud (Singapore).",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_url": "https://modelstudio.console.alibabacloud.com/model/settings/api-key",
        "key_steps": "Sign in to Alibaba Cloud Model Studio, open API Key, create a key and copy it.",
        "models": [
            {"id": "qwen3.7-plus", "label": "good start"},
            {"id": "qwen4-max", "label": "strongest"},
            {"id": "qwen3.8-flash", "label": "fastest, cheapest"},
        ],
    },
    {
        "id": "qwen-us", "title": "Qwen (US)",
        "description": "Alibaba Cloud's Qwen models, for accounts in the US (Virginia) region.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Alibaba Cloud (US).",
        "base_url": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
        "key_url": "https://modelstudio.console.alibabacloud.com/model/settings/api-key",
        "key_steps": "Sign in to Alibaba Cloud Model Studio in the US region, open API Key, create a key and "
                     "copy it.",
        "models": [
            {"id": "qwen3.7-plus", "label": "good start"},
            {"id": "qwen4-max", "label": "strongest"},
            {"id": "qwen3.8-flash", "label": "fastest, cheapest"},
        ],
    },
    {
        "id": "muse", "title": "Muse (Meta)",
        "description": "Meta's Muse models. The API is in preview for developers in the US.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Meta.",
        "base_url": "https://api.meta.ai/v1",
        "key_url": "https://dev.meta.ai",
        "key_steps": "Sign in at dev.meta.ai, open the API keys tab of the dashboard, create a key and copy it.",
        "models": [
            {"id": "muse-spark-1.3", "label": "good start"},
            {"id": "muse-ember-1.0", "label": "fast"},
            {"id": "muse-wonder-1.0", "label": "strongest, preview"},
        ],
    },
    {
        "id": "mistral", "title": "Mistral",
        "description": "Mistral AI's models, made and hosted in the EU.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Mistral AI.",
        "base_url": "https://api.mistral.ai/v1",
        "key_url": "https://console.mistral.ai/api-keys",
        "key_steps": "Sign in to the Mistral console, set up billing if it asks, then create an API key and copy it.",
        "models": [
            {"id": "mistral-large-latest", "label": "strongest"},
            {"id": "mistral-small-2603", "label": "cheapest", "input_price": 0.15, "output_price": 0.6},
        ],
    },
    {
        "id": "deepseek", "title": "DeepSeek",
        "description": "DeepSeek's low-cost models.",
        "privacy": "Whatever Happy Bot reads for a request is sent to DeepSeek.",
        "base_url": "https://api.deepseek.com",
        "key_url": "https://platform.deepseek.com/api_keys",
        "key_steps": "Sign in to the DeepSeek platform, open API keys, create a key and copy it.",
        "models": [
            {"id": "deepseek-v4-pro", "label": "strongest"},
            {"id": "deepseek-flash", "label": "cheapest"},
        ],
    },
    {
        "id": "kimi", "title": "Kimi (Moonshot)",
        "description": "Moonshot's Kimi models, strong with long documents and code.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Moonshot AI.",
        "base_url": "https://api.moonshot.ai/v1",
        "key_url": "https://platform.kimi.ai/console/api-keys",
        "key_steps": "Sign in to the Kimi platform (platform.kimi.ai, not the China site), create an API key and "
                     "copy it.",
        "models": [
            {"id": "kimi-k3.1-pro", "label": "strongest"},
            {"id": "kimi-k3.1-pro-highspeed", "label": "fast"},
        ],
    },
    {
        "id": "groq", "title": "Groq",
        "description": "Very fast hosting of open models.",
        "privacy": "Whatever Happy Bot reads for a request is sent to Groq.",
        "base_url": "https://api.groq.com/openai/v1",
        "key_url": "https://console.groq.com/keys",
        "key_steps": "Sign in to the Groq console, choose Create API Key, and copy it.",
        "models": [
            {"id": "openai/gpt-oss-120b", "label": "strongest"},
            {"id": "openai/gpt-oss-20b", "label": "fastest"},
        ],
    },
    {
        "id": "openrouter", "title": "OpenRouter",
        "description": "One account and key that reaches hundreds of models from many companies.",
        "privacy": "Whatever Happy Bot reads for a request is sent to OpenRouter and the company whose model "
                   "you pick.",
        "base_url": "https://openrouter.ai/api/v1",
        "key_url": "https://openrouter.ai/keys",
        "key_steps": "Sign in to OpenRouter, add credit if you want paid models, create a key and copy it.",
        "models": [
            {"id": "~openai/gpt-sol-latest", "label": "good start"},
            {"id": "x-ai/grok-4.7", "label": "Grok"},
            {"id": "~deepseek/deepseek-flash-latest", "label": "cheapest"},
        ],
    },
)


def find(preset_id: str) -> dict[str, Any] | None:
    return next((preset for preset in PRESETS if preset["id"] == preset_id), None)


def suggested(preset_id: str, model_id: str) -> dict[str, Any]:
    """The preset's entry for ``model_id`` (labels and prices), or {} when it is not a suggested one."""
    preset = find(preset_id)
    return next((model for model in (preset or {}).get("models", []) if model["id"] == model_id), {})


def listing() -> list[dict[str, Any]]:
    """Every preset, for the settings page."""
    return copy.deepcopy(list(PRESETS))
