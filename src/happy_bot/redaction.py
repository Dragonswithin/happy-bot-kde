"""Hides passwords, API keys and private keys in text before it leaves the computer.

When the answering model is hosted (its address is not on this computer,
``is_local_address``), every tool result passes through ``redact`` before it
is added to the conversation (``agent_loop.run_turn``). A tool may read a
config file, a shell history or the clipboard that happens to hold a secret;
the model rarely needs the secret itself, and the user did not choose to
send it.

What is hidden, each replaced by ``[hidden secret]``:

- PEM private key blocks (``-----BEGIN ... PRIVATE KEY-----`` to its end);
- tokens with a well-known shape: OpenAI/Anthropic style ``sk-...``, GitHub
  ``ghp_``/``gho_``/``ghu_``/``ghs_``/``ghr_``/``github_pat_``, GitLab
  ``glpat-``, Slack ``xox?-``, AWS access key ids ``AKIA...``, Google API keys
  ``AIza...``, Hugging Face ``hf_...``;
- ``Authorization: Bearer|Basic <value>`` header values;
- the value after a sensitive name in ``name = value``, ``name: value`` and
  JSON ``"name": "value"`` forms (password, passwd, secret, token, api key,
  access key, private key, client secret, auth), the name itself kept so the
  model still knows what was there.

This is pattern matching and can miss a secret in an unusual form; it is a
safety net, not a guarantee, and the settings page says so for hosted models.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

HIDDEN = "[hidden secret]"

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S)
_TOKENS = re.compile(
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|glpat-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}"
    r"|hf_[A-Za-z0-9]{30,})\b")
_AUTH_HEADER = re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic|token)\s+)[^\s\"',;]+")
_NAMES = r"(?:[A-Za-z0-9_.-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|auth))"
_JSON_VALUE = re.compile(r"(?i)(\"" + _NAMES + r"\"\s*:\s*\")([^\"]{4,})(\")")
_ASSIGNMENT = re.compile(r"(?i)(\b" + _NAMES + r"\b\s*[:=]\s*)(['\"]?)([^\s'\",;]{4,})(\2)")


def redact(text: str) -> str:
    """``text`` with every secret it recognises replaced by ``HIDDEN``."""
    text = _PEM.sub(HIDDEN, text)
    text = _TOKENS.sub(HIDDEN, text)
    text = _AUTH_HEADER.sub(lambda match: match.group(1) + HIDDEN, text)
    text = _JSON_VALUE.sub(lambda match: match.group(1) + HIDDEN + match.group(3), text)
    return _ASSIGNMENT.sub(lambda match: match.group(1) + match.group(2) + HIDDEN + match.group(4), text)


def is_local_address(base_url: str) -> bool:
    """Whether a model service address is on this computer (loopback), so nothing read leaves it."""
    host = (urlparse(base_url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.")
