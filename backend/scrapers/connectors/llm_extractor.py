"""
LLM Document Extractor — Claude-powered structured extraction.

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


class LLMExtractor:
    """Extract structured data from municipal documents using Claude."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2000,
    ):
        from config import ANTHROPIC_API_KEY
        self.api_key = api_key or ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.max_tokens = max_tokens
        self._client: Optional[Any] = None

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set — LLM extraction will fail")

    def _ensure_client(self) -> Any:
        if self._client is None:
            if anthropic is None:
                raise RuntimeError("anthropic package required: pip install anthropic")
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

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
        client = self._ensure_client()

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
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            result_text = response.content[0].text.strip()

            # Try to parse JSON — handle potential markdown code blocks
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            parsed = json.loads(result_text)
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
        client = self._ensure_client()

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
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            result_text = response.content[0].text.strip()

            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            return json.loads(result_text)

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
        client = self._ensure_client()

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
            response = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            result_text = response.content[0].text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            return json.loads(result_text)

        except Exception as exc:
            logger.warning("[LLM] Permit analysis failed: %s", exc)
            return {"significance": "unknown", "impact_summary": "", "category": "other"}
