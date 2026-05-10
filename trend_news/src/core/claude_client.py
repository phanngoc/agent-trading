"""
Thin Anthropic /v1/messages client supporting Claude Code OAuth tokens
and standard API keys.

Credential discovery (first hit wins):
  1. CLAUDE_CODE_OAUTH_TOKEN env var
  2. ANTHROPIC_API_KEY env var
  3. macOS Keychain entry "Claude Code-credentials" (dev convenience;
     produced by `claude setup-token`)

This client only exposes /v1/messages. Cost efficiency on multi-article
workloads is achieved by prompt batching (multiple articles per call) at
the caller layer (see src.core.claude_sentiment), not via the Anthropic
Batches API — which OAuth tokens cannot use anyway.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
OAUTH_BETA = "oauth-2025-04-20"

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_TIMEOUT = 60

KEYCHAIN_SERVICE = "Claude Code-credentials"


class ClaudeAuthError(RuntimeError):
    """No usable credential found."""


class ClaudeAPIError(RuntimeError):
    """Anthropic API returned an error."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def _read_macos_keychain() -> Optional[str]:
    """Read the OAuth access token from macOS Keychain (dev machines only).

    Returns the access token string, or None if anything goes wrong
    (not on macOS, item missing, user denies prompt, JSON malformed).
    """
    if platform.system() != "Darwin":
        return None
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        data = json.loads(proc.stdout)
        token = (data.get("claudeAiOauth") or {}).get("accessToken")
        if isinstance(token, str) and token.strip():
            return token.strip()
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None
    return None


def _discover_credential() -> tuple[str, str]:
    """Return (token, kind) where kind in {'oauth', 'api_key'}."""
    oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if oauth:
        kind = "oauth" if oauth.startswith("sk-ant-oat") else "api_key"
        return oauth, kind
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return api_key, "api_key"
    keychain = _read_macos_keychain()
    if keychain:
        return keychain, "oauth"
    raise ClaudeAuthError(
        "No Anthropic credential found. Set CLAUDE_CODE_OAUTH_TOKEN, "
        "ANTHROPIC_API_KEY, or run `claude setup-token` on macOS."
    )


class ClaudeClient:
    """Sync Anthropic client over plain HTTPS — no SDK dependency."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        token: Optional[str] = None,
        token_kind: Optional[str] = None,
    ):
        if token is None:
            token, token_kind = _discover_credential()
        elif token_kind is None:
            token_kind = "oauth" if token.startswith("sk-ant-oat") else "api_key"
        self._token = token
        self._kind = token_kind
        self.model = model
        self.timeout = timeout

    @property
    def auth_kind(self) -> str:
        return self._kind

    def _headers(self) -> Dict[str, str]:
        h = {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._kind == "oauth":
            h["anthropic-beta"] = OAUTH_BETA
            h["Authorization"] = f"Bearer {self._token}"
        else:
            h["x-api-key"] = self._token
        return h

    # ------------------------------------------------------------------
    # Sync messages
    # ------------------------------------------------------------------
    def messages_create(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 1024,
        system: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        resp = requests.post(
            f"{API_BASE}/v1/messages",
            headers=self._headers(),
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise ClaudeAPIError(resp.status_code, resp.text)
        return resp.json()

    @staticmethod
    def extract_text(response: Dict[str, Any]) -> str:
        """Concatenate all text blocks from a /v1/messages response."""
        parts = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
