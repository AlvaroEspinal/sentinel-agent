"""
LLM Document Extractor — Multi-provider structured extraction.

Supports:
  - Anthropic Claude API (direct)
  - OpenRouter (OpenAI-compatible gateway → 100+ models)

Takes raw text from meeting minutes, zoning documents, and other
municipal records and extracts structured intelligence:
- Addresses and parcel IDs mentioned
- Decisions (approved, denied, continued)
- Topics (variance, demolition, subdivision, special permit)
- Summary paragraph
- Keywords
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

try:
    import openai
except ImportError:
    openai = None  # type: ignore


class LLMExtractor:
    """Extract structured data from municipal documents using LLMs.

    Supports two providers:
      - "anthropic" → Anthropic Claude API (default)
      - "openrouter" → OpenRouter gateway (OpenAI-compatible, 100+ models)

    Usage:
        # Use Anthropic Claude (default)
        llm = LLMExtractor()

        # Use OpenRouter with Gemini Flash
        llm = LLMExtractor(provider="openrouter", model="google/gemini-2.0-flash-001")

        # Use OpenRouter with DeepSeek
        llm = LLMExtractor(provider="openrouter", model="deepseek/deepseek-chat-v3-0324")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        provider: Optional[str] = None,
    ):
        from config import (
            ANTHROPIC_API_KEY,
            OPENROUTER_API_KEY,
            OPENROUTER_DEFAULT_MODEL,
            LLM_PROVIDER,
        )

        # Determine provider
        self.provider = (provider or LLM_PROVIDER or "anthropic").lower()

        if self.provider == "openrouter":
            self.api_key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
            self.model = model or OPENROUTER_DEFAULT_MODEL or "google/gemini-2.0-flash-001"
            if not self.api_key:
                logger.warning("OPENROUTER_API_KEY not set — LLM extraction will fail")
        else:
            # Default to Anthropic
            self.provider = "anthropic"
            self.api_key = api_key or ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
            self.model = model or "claude-sonnet-4-20250514"
            if not self.api_key:
                logger.warning("ANTHROPIC_API_KEY not set — LLM extraction will fail")

        self.max_tokens = max_tokens
        self._anthropic_client: Optional[Any] = None
        self._openrouter_client: Optional[Any] = None

        logger.info("LLMExtractor initialized: provider=%s, model=%s", self.provider, self.model)

    # ── Client Management ─────────────────────────────────────────────────

    def _ensure_anthropic_client(self) -> Any:
        if self._anthropic_client is None:
            if anthropic is None:
                raise RuntimeError("anthropic package required: pip install anthropic")
            self._anthropic_client = anthropic.Anthropic(api_key=self.api_key)
        return self._anthropic_client

    def _ensure_openrouter_client(self) -> Any:
        if self._openrouter_client is None:
            if openai is None:
                raise RuntimeError("openai package required: pip install openai")
            self._openrouter_client = openai.OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
            )
        return self._openrouter_client

    # ── Unified LLM Call ──────────────────────────────────────────────────

    def _call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Send a prompt to the configured LLM provider and return raw text.

        Routes to Anthropic or OpenRouter based on self.provider.
        Returns the model's text response.
        """
        tokens = max_tokens or self.max_tokens

        if self.provider == "openrouter":
            client = self._ensure_openrouter_client()
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return (response.choices[0].message.content or "").strip()
        else:
            # Anthropic
            client = self._ensure_anthropic_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()

    # ── JSON Parsing Helper ───────────────────────────────────────────────

    @staticmethod
    def _parse_json_response(text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)

    # ── Meeting Minutes Extraction ────────────────────────────────────────

    async def extract_from_minutes(
        self,
        text: str,
        town_name: str,
        board_name: str,
    ) -> Dict[str, Any]:
        """Extract structured data from meeting minutes text.

        Returns:
            {
                "summary": "Brief summary of the meeting...",
                "keywords": ["demolition", "variance", "subdivision"],
                "mentions": [
                    {
                        "address": "123 Main St",
                        "parcel_id": null,
                        "topic": "demolition",
                        "decision": "approved",
                        "context_snippet": "The board voted to approve..."
                    }
                ],
                "decisions": [
                    {
                        "topic": "Special permit for ADU at 45 Oak Ave",
                        "decision": "approved",
                        "vote": "5-0"
                    }
                ]
            }
        """
        # Truncate long documents
        if len(text) > 20000:
            text = text[:20000] + "\n\n[... document truncated ...]"

        prompt = f"""You are analyzing meeting minutes from the {board_name} in {town_name}, Massachusetts.

Extract the following structured information from the text below. Return valid JSON only.

{{
  "summary": "2-3 sentence summary of key topics discussed",
  "keywords": ["list", "of", "relevant", "keywords"],
  "mentions": [
    {{
      "address": "street address if mentioned (null if not)",
      "parcel_id": "parcel ID if mentioned (null if not)",
      "topic": "what was discussed about this property",
      "decision": "approved/denied/continued/tabled/withdrawn (null if no decision)",
      "is_subdivision": "boolean (true if this discussion involves a subdivision of land)",
      "is_site_plan": "boolean (true if this involves a site plan approval or review)",
      "context_snippet": "brief relevant quote or paraphrase (max 100 chars)"
    }}
  ],
  "decisions": [
    {{
      "topic": "what was decided",
      "decision": "approved/denied/continued/tabled/withdrawn",
      "vote": "vote count if mentioned (e.g. '5-0')"
    }}
  ]
}}

Focus on:
- Property addresses and any associated actions (permits, variances, special permits)
- Zoning changes, overlay districts, bylaw amendments
- Demolition requests
- Subdivision plans
- Site plan approvals
- Conservation restrictions
- Any real estate development topics

If no relevant property information is found, return empty arrays for mentions and decisions.

Meeting minutes text:
---
{text}
---

Return ONLY valid JSON, no other text."""

        try:
            result_text = self._call_llm(prompt)
            parsed = self._parse_json_response(result_text)
            return {
                "summary": parsed.get("summary", ""),
                "keywords": parsed.get("keywords", []),
                "mentions": parsed.get("mentions", []),
                "decisions": parsed.get("decisions", []),
            }

        except json.JSONDecodeError as exc:
            logger.warning("[LLM] JSON parse error in extraction: %s", exc)
            return {"summary": "", "keywords": [], "mentions": [], "decisions": []}

        except Exception as exc:
            logger.error("[LLM] Extraction failed: %s", exc)
            return {"summary": "", "keywords": [], "mentions": [], "decisions": []}

    # ── Generic Document Extraction ───────────────────────────────────────

    async def extract_from_document(
        self,
        text: str,
        doc_type: str,
        town_name: str,
    ) -> Dict[str, Any]:
        """Extract structured data from any municipal document.

        Args:
            text: Document text
            doc_type: Type of document (zoning_bylaw, capital_plan, etc.)
            town_name: Town name for context

        Returns:
            Dict with summary, keywords, and type-specific fields
        """
        if len(text) > 15000:
            text = text[:15000] + "\n\n[... document truncated ...]"

        prompt = f"""You are analyzing a {doc_type.replace('_', ' ')} document from {town_name}, Massachusetts.

Extract structured information and return valid JSON:

{{
  "summary": "2-3 sentence summary of key content",
  "keywords": ["relevant", "keywords"],
  "addresses_mentioned": ["list of any street addresses mentioned"],
  "key_facts": ["list of important facts or data points"],
  "effective_date": "date if mentioned (YYYY-MM-DD format, null if not found)"
}}

Document text:
---
{text}
---

Return ONLY valid JSON."""

        try:
            result_text = self._call_llm(prompt)
            return self._parse_json_response(result_text)

        except Exception as exc:
            logger.error("[LLM] Document extraction failed: %s", exc)
            return {"summary": "", "keywords": [], "addresses_mentioned": [], "key_facts": []}

    # ── Permit Intelligence ───────────────────────────────────────────────

    async def analyze_permit_significance(
        self,
        permit_type: str,
        description: str,
        value: Optional[float],
        address: str,
        town_name: str,
    ) -> Dict[str, Any]:
        """Analyze a permit's significance for realtors.

        Returns insight about why this permit matters for property values.
        """
        prompt = f"""As a real estate analyst, briefly analyze this building permit's significance:

Town: {town_name}, MA
Address: {address}
Type: {permit_type}
Value: ${value:,.0f} if value else "Not specified"
Description: {description}

Return JSON:
{{
  "significance": "high/medium/low",
  "impact_summary": "1 sentence on how this affects nearby property values",
  "category": "new_construction/renovation/demolition/addition/other"
}}

Return ONLY valid JSON."""

        try:
            result_text = self._call_llm(prompt, max_tokens=500)
            return self._parse_json_response(result_text)

        except Exception as exc:
            logger.warning("[LLM] Permit analysis failed: %s", exc)
            return {"significance": "unknown", "impact_summary": "", "category": "other"}
