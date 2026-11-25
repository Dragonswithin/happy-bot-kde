"""Rewriting the text the user selected: fix its grammar, shorten it, translate it or explain it.

"Fix selected text" (the "Fix selected text" shortcut, ``happy-bot app fix``) shows the
selection in Happy Bot with one button per ``STYLES`` entry, and the user may type an
instruction of their own instead ("make it formal", "translate into French"). ``rewrite`` asks
one AI once, with no tools, and returns its text: the rewritten text, which the user can put
back in place of the selection (``selection_fix``) or copy, or for ``explain`` an
explanation, which only makes sense to read.

Which AI: the first model in the user's ``model_order`` that may see it. What is selected was
read from the user's application, so the user's ``agent.app_context`` privacy setting applies
exactly as to tools that read inside applications (``app_context.shows_private_results``): with
the default ("local"), only AIs on this computer are asked, which is what the feature promises.
"Local only", and a model's monthly spending limit, skip models as they do for requests. A model
that fails hands the text to the next one; the cost of the one that answered is recorded
(``spend``). Nothing is saved: the selection and the answer live only in the request and the
reply.

Local reasoning models are asked to skip their hidden thinking (``create_provider(...,
no_thinking=True)``), which on the maintainer's local Qwen3.6 turned a 15-second rewrite into a
third of a second with the same result. "translate" asks for the text's language on the reply's first line and the translation below
it (``_translation``): asked instead to say when the text was already in the user's language, the
local model called Spanish English, while naming the language it gets right; text already in
the user's language is then refused with a hint to type the language wanted. "explain" has its
own system prompt, since under the rewriting one the model rewrote the text instead.
The reply is cleaned of what models add around an answer: hidden-reasoning blocks
(``<think>…</think>``), a code fence around the whole reply, and matching quotes. ``rewrite``
blocks until the model answers (a local model may take some seconds) and raises
``RewriteError`` with a message for the user when no AI may see the text or none answered.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any

from . import app_context, spend
from .conversation import Message, TextDelta, TurnEnd
from .providers import ProviderError, create_provider
from .redaction import is_local_address

MAX_TEXT_CHARS = 8000
MAX_INSTRUCTION_CHARS = 300
REWRITE_SYSTEM = ("You rewrite text the user selected in one of their applications. Reply with the result only: "
                  "no introduction, no quotes around it, no notes about what you changed. Keep the text's language, "
                  "meaning, names, numbers, line breaks and formatting unless the task says otherwise.")
EXPLAIN_SYSTEM = ("You explain text the user selected in one of their applications. Reply with the explanation "
                  "only, in a few plain sentences, without repeating or rewriting the text.")
# style: (task given to the model, whether the result replaces the selection)
STYLES: dict[str, tuple[str, bool]] = {
    "fix": ("Correct the spelling, grammar and punctuation. Change nothing else.", True),
    "shorter": ("Make it shorter and clearer, keeping everything that matters.", True),
    # The first line names the text's language, so ``rewrite`` can tell when there is nothing to translate.
    "translate": ("On the first line write only the English name of the language the text is written in. "
                  "Then, from the second line, its translation into {language}.", True),
    "explain": ("Explain briefly, in {language}, what this text means or says.", False),
}
LANGUAGES = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
             "nl": "Dutch", "pl": "Polish", "sv": "Swedish", "da": "Danish", "nb": "Norwegian", "fi": "Finnish",
             "cs": "Czech", "ru": "Russian", "uk": "Ukrainian", "tr": "Turkish", "ja": "Japanese", "zh": "Chinese",
             "ko": "Korean", "ar": "Arabic", "hi": "Hindi"}
_THINKING = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"\A```[\w-]*\n(.*)\n```\Z", re.S)


class RewriteError(RuntimeError):
    """No rewrite: no AI may see the text, or none answered. The message says what to do."""


def user_language() -> str:
    """The user's language as a name the model understands ("German"), from the locale settings."""
    value = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en"
    code = value.split(".")[0].split("@")[0]
    return LANGUAGES.get(code.split("_")[0].lower(), code if code not in ("C", "POSIX") else "English")


def task(style: str, instruction: str = "") -> tuple[str, bool]:
    """``(what the model is asked to do, whether the result replaces the selection)``."""
    instruction = " ".join(instruction.split())[:MAX_INSTRUCTION_CHARS]
    if instruction:
        return f"Do this with the text: {instruction}", True
    if style not in STYLES:
        raise RewriteError(f"unknown way to rewrite: {style!r}")
    wording, replaces = STYLES[style]
    return wording.format(language=user_language()), replaces


def allowed_models(settings: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The models that may see text read from the user's applications, in the user's order."""
    agent = settings.get("agent") or {}
    policy = agent.get("app_context", app_context.DEFAULT_POLICY)
    found = []
    for name in settings.get("model_order") or []:
        model = (settings.get("models") or {}).get(name)
        if not model:
            continue
        local = is_local_address(str(model.get("base_url") or ""))
        if (agent.get("local_only") and not local) or not app_context.shows_private_results(policy, local):
            continue
        if spend.over_cap(name, model):
            continue
        found.append((name, model))
    return found


def clean(reply: str) -> str:
    """The reply without reasoning blocks, a fence around all of it, or quotes around all of it."""
    text = _THINKING.sub("", reply).strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”" or (text[:1], text[-1:]) == ("“", "”"):
        text = text[1:-1].strip()
    return text


def _translation(reply: str) -> str:
    """The translation from a "translate" reply (its language on the first line, then the text)."""
    first, _, rest = reply.partition("\n")
    language = first.strip().strip("*:.").strip().lower()
    if language == user_language().lower():
        raise RewriteError(f"It is already in {user_language()}. Type the language you want instead, "
                           "for example “translate into French”, and press Enter.")
    return clean(rest)


def rewrite(settings: dict[str, Any], text: str, style: str, instruction: str = "") -> dict[str, Any]:
    """``{"text", "model", "replaces"}`` for the selected ``text``; raises ``RewriteError``."""
    text = text.strip()
    if not text:
        raise RewriteError("Nothing is selected. Select some text first, then try again.")
    if len(text) > MAX_TEXT_CHARS:
        raise RewriteError(f"That is too much text at once (at most {MAX_TEXT_CHARS} characters).")
    wording, replaces = task(style, instruction)
    models = allowed_models(settings)
    if not models:
        raise RewriteError("No AI may see text from your applications. Add an AI on this computer, or allow "
                           "online AIs to see what Happy Bot reads in your apps (Behaviour page).")
    system = REWRITE_SYSTEM if replaces else EXPLAIN_SYSTEM
    messages = [Message("system", system), Message("user", f"Task: {wording}\n\nText:\n{text}")]
    problems = []
    for name, model in models:
        try:
            provider = create_provider(model, no_thinking=True)  # a short task: thinking only costs time
            reply, used_in, used_out = "", 0, 0
            for event in provider.stream(messages, [], threading.Event()):
                if isinstance(event, TextDelta):
                    reply += event.text
                elif isinstance(event, TurnEnd):
                    used_in, used_out = event.input_tokens, event.output_tokens
        except ProviderError as error:
            problems.append(f"{name}: {error}")
            continue
        spend.record(name, model, used_in, used_out)
        result = clean(reply)
        if style == "translate" and not instruction:
            result = _translation(result)
        if result:
            return {"text": result, "model": name, "replaces": replaces}
        problems.append(f"{name}: the answer was empty")
    raise RewriteError("No AI could do it (" + "; ".join(problems) + ").")
