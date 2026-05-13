"""Anthropic Claude client with Claude Code OAuth2 token support.

Credential discovery (first hit wins):
  1. ANTHROPIC_AUTH_TOKEN env var (explicit Bearer override)
  2. CLAUDE_CODE_OAUTH_TOKEN env var (explicit Claude Code token)
  3. macOS Keychain entry "Claude Code-credentials" (auto-refreshed by
     Claude Code itself; preferred over .env so a stale OAuth token in
     ANTHROPIC_API_KEY doesn't shadow the live session credentials)
  4. ANTHROPIC_API_KEY env var (classic API key, or OAuth token placed
     there by users who don't know about ANTHROPIC_AUTH_TOKEN — detected
     by the ``sk-ant-oat`` prefix and routed via Bearer auth)

When an OAuth token is used, ChatAnthropic is configured with
``betas=["oauth-2025-04-20"]`` and the underlying anthropic SDK picks
up ``ANTHROPIC_AUTH_TOKEN`` automatically and sends ``Authorization:
Bearer …`` instead of ``x-api-key``. This lets the trading graph share
the user's interactive Claude Code session credentials without storing
a separate API key.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from typing import Any, Optional, Tuple

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient
from .validators import validate_model


_OAUTH_BETA = "oauth-2025-04-20"
_KEYCHAIN_SERVICE = "Claude Code-credentials"


def _read_macos_keychain_oauth_token() -> Optional[str]:
    """Return the Claude Code OAuth access token from macOS Keychain, or None.

    Triggers a Keychain access prompt the first time, then silent on
    subsequent calls. Returns None on any failure (not macOS, missing
    entry, malformed JSON, user denied).
    """
    if platform.system() != "Darwin":
        return None
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        data = json.loads(proc.stdout)
        token = (data.get("claudeAiOauth") or {}).get("accessToken")
        if isinstance(token, str) and token.strip():
            return token.strip()
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        pass
    return None


def _discover_anthropic_credential() -> Tuple[Optional[str], Optional[str], str]:
    """Return (api_key, auth_token, kind).

    Exactly one of api_key / auth_token is non-None. ``kind`` is one of
    ``"api_key"`` / ``"oauth"`` / ``"none"`` (the last meaning no
    credential was found — caller should let ChatAnthropic raise its
    usual error).
    """
    auth = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if auth:
        return None, auth, "oauth"

    claude_code = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if claude_code:
        kind = "oauth" if claude_code.startswith("sk-ant-oat") else "api_key"
        if kind == "oauth":
            return None, claude_code, "oauth"
        return claude_code, None, "api_key"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    # When ANTHROPIC_API_KEY holds an OAuth token (sk-ant-oat prefix), the
    # Keychain entry is the authoritative source — Claude Code auto-refreshes
    # it, while a token written to .env once stays frozen. Prefer Keychain
    # so a stale .env entry doesn't shadow a live session.
    if api_key.startswith("sk-ant-oat"):
        keychain = _read_macos_keychain_oauth_token()
        if keychain:
            return None, keychain, "oauth"
        return None, api_key, "oauth"

    if api_key:
        return api_key, None, "api_key"

    keychain = _read_macos_keychain_oauth_token()
    if keychain:
        return None, keychain, "oauth"

    return None, None, "none"


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic Claude models (API key OR OAuth2 token)."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """Return configured ChatAnthropic instance with the discovered credential."""
        self.warn_if_unknown_model()
        llm_kwargs: dict[str, Any] = {"model": self.model}

        # Forward optional user-provided kwargs
        for key in ("timeout", "max_retries", "max_tokens", "callbacks"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Explicit api_key from kwargs always wins (programmatic override).
        if "api_key" in self.kwargs:
            llm_kwargs["api_key"] = self.kwargs["api_key"]
            return ChatAnthropic(**llm_kwargs)

        api_key, auth_token, kind = _discover_anthropic_credential()
        if kind == "oauth":
            # Ensure the anthropic SDK picks up the bearer token from env.
            # We don't pop ANTHROPIC_API_KEY here — anthropic.Anthropic
            # raises if both are present, so just remove it from this run.
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ["ANTHROPIC_AUTH_TOKEN"] = auth_token
            llm_kwargs.setdefault("betas", []).append(_OAUTH_BETA)
        elif kind == "api_key":
            llm_kwargs["api_key"] = api_key
        # kind == "none": let ChatAnthropic surface its usual missing-credential error.

        return ChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for Anthropic."""
        return validate_model("anthropic", self.model)
