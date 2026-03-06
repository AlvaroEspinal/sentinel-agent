"""
CIP Extractor — LLM-powered Capital Improvement Plan parser.

Extracts structured infrastructure-project data from Capital Improvement Plan
(CIP) documents and Town Meeting Warrants.  Returns JSON with project name,
budget, proposed year, location, department, funding source, and category.

LLM back-end preference order:
  1. OpenRouter  (OPENROUTER_API_KEY)   — OpenAI-compatible; any model
  2. Anthropic   (ANTHROPIC_API_KEY)    — native SDK fallback
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Optional: native Anthropic SDK as fallback
try:
    import anthropic as _anthropic_sdk
except ImportError:
    _anthropic_sdk = None  # type: ignore

# ── OpenRouter constants ──────────────────────────────────────────────────
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_SITE_URL = "https://github.com/sentinel-agent"
_OPENROUTER_APP_NAME = "Sentinel-Agent-CIP-Extractor"


class CIPExtractor:
    """Extract municipal infrastructure projects from CIP / Warrant text.

    Uses OpenRouter by default (OPENROUTER_API_KEY), falling back to the
    native Anthropic SDK (ANTHROPIC_API_KEY) if OpenRouter is not configured.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        provider: Optional[str] = None,
    ):
        from config import (
            OPENROUTER_API_KEY,
            OPENROUTER_DEFAULT_MODEL,
            ANTHROPIC_API_KEY,
        )

        # Resolve provider
        env_provider = os.getenv("LLM_PROVIDER", "openrouter")
        self._provider = (provider or env_provider).lower()

        if self._provider == "openrouter":
            self._or_key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
            self._model = model or OPENROUTER_DEFAULT_MODEL or "google/gemini-2.0-flash-001"
            if not self._or_key:
                logger.warning("OPENROUTER_API_KEY not set — falling back to Anthropic")
                self._provider = "anthropic"

        if self._provider == "anthropic":
            self._anth_key = api_key or ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
            self._model = model or "claude-sonnet-4-20250514"
            if not self._anth_key:
                logger.warning("ANTHROPIC_API_KEY not set — CIP extraction will fail")

        self._max_tokens = max_tokens
        self._anth_client: Optional[Any] = None

        logger.info("[CIP] Provider=%s model=%s", self._provider, self._model)

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _strip_json(text: str) -> str:
        """Remove markdown code fences that LLMs sometimes wrap around JSON."""
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            # parts[1] is either 'json\n{...}' or just '{...}'
            inner = parts[1]
            if inner.startswith("json"):
                inner = inner[4:]
            text = inner.strip()
        return text

    def _build_prompt(self, text: str, town_name: str, doc_type: str) -> str:
        doc_label = doc_type.replace("_", " ").title()
        return f"""You are analyzing a {doc_label} document from {town_name}, Massachusetts.

Extract EVERY identifiable municipal infrastructure or capital project from
the text below.  Return a JSON object with a single top-level key "projects"
containing an array.  Each element must have these exact fields:

{{
  "project_name": "Short descriptive name of the project",
  "budget": 1200000,
  "budget_display": "$1,200,000",
  "proposed_year": 2027,
  "location": "Street or area name, null if not specified",
  "department": "Responsible department or board, null if not specified",
  "funding_source": "General Fund / Free Cash / Bond / Grant / null",
  "category": "roads | water_sewer | schools | parks | public_safety | municipal_buildings | technology | other",
  "description": "One-sentence summary of scope"
}}

Rules:
- "budget" is a numeric dollar value (integer or float).  Use null if not stated.
- "budget_display" is the human-readable dollar string.  Use "Not specified" when budget is null.
- "proposed_year" is the fiscal or calendar year planned.  Use null if unclear.
- "category" MUST be one of the pipe-delimited enum values listed above.
- If the text contains NO identifiable projects, return {{"projects": []}}.

Document text:
---
{text}
---

Return ONLY valid JSON, no other text."""

    # ── OpenRouter call ───────────────────────────────────────────────────

    def _call_openrouter(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._or_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": _OPENROUTER_SITE_URL,
            "X-Title": _OPENROUTER_APP_NAME,
        }
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(_OPENROUTER_BASE_URL, json=payload, headers=headers)
            resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # ── Anthropic SDK call ────────────────────────────────────────────────

    def _call_anthropic(self, prompt: str) -> str:
        if _anthropic_sdk is None:
            raise RuntimeError("anthropic package not installed")
        if self._anth_client is None:
            self._anth_client = _anthropic_sdk.Anthropic(api_key=self._anth_key)
        response = self._anth_client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    # ── Public API ────────────────────────────────────────────────────────

    async def extract_cip_projects(
        self,
        text: str,
        town_name: str,
        doc_type: str = "capital_plan",
    ) -> Dict[str, Any]:
        """Extract infrastructure projects from CIP or Town Warrant text.

        Args:
            text:      Raw text of the CIP document or warrant article.
            town_name: Municipality name (e.g. "Wellesley").
            doc_type:  "capital_plan" or "warrant".

        Returns:
            {
                "town": "Wellesley",
                "doc_type": "capital_plan",
                "provider": "openrouter",
                "model": "google/gemini-2.0-flash-001",
                "projects": [ {...}, ... ],
                "project_count": 5
            }
        """
        # Cap input to avoid token blow-up
        if len(text) > 20_000:
            text = text[:20_000] + "\n\n[... document truncated ...]"

        prompt = self._build_prompt(text, town_name, doc_type)

        try:
            if self._provider == "openrouter":
                raw = self._call_openrouter(prompt)
            else:
                raw = self._call_anthropic(prompt)

            result_text = self._strip_json(raw)
            parsed = json.loads(result_text)
            projects: List[Dict[str, Any]] = parsed.get("projects", [])

            return {
                "town": town_name,
                "doc_type": doc_type,
                "provider": self._provider,
                "model": self._model,
                "projects": projects,
                "project_count": len(projects),
            }

        except json.JSONDecodeError as exc:
            logger.warning("[CIP] JSON parse error: %s", exc)
        except Exception as exc:
            logger.error("[CIP] Extraction failed: %s", exc)

        return {
            "town": town_name,
            "doc_type": doc_type,
            "provider": self._provider,
            "model": self._model,
            "projects": [],
            "project_count": 0,
        }
