"""
Permit Semantic Search Service for Parcl Intelligence.

Provides RAG-powered search over permit data using OpenAI embeddings.
Falls back to Anthropic for LLM answers, then to keyword search when
no LLM is available.
"""

import logging
import math
import re
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import OpenAI
    _openai_available = True
except ImportError:
    _openai_available = False

# Try to import Anthropic
try:
    import anthropic as _anthropic_mod
    _anthropic_available = True
except ImportError:
    _anthropic_available = False


def _merge_results(existing: list, new: list, limit: int) -> list:
    """Merge permit result lists, deduplicating by id."""
    seen = {p.get("id") for p in existing}
    merged = list(existing)
    for p in new:
        pid = p.get("id")
        if pid and pid not in seen:
            merged.append(p)
            seen.add(pid)
        if len(merged) >= limit:
            break
    return merged


class PermitSearchService:
    """Semantic search over permit data with RAG capabilities."""

    def __init__(self, permit_loader):
        """Initialize with a PermitDataLoader instance."""
        self.loader = permit_loader
        self.client = None
        self.llm_provider = None  # "openai", "anthropic", or None
        self._embeddings_cache: dict[str, list[float]] = {}

        # Try OpenAI first
        if _openai_available:
            try:
                from config import OPENAI_API_KEY
                if OPENAI_API_KEY:
                    self.client = OpenAI(api_key=OPENAI_API_KEY)
                    self.llm_provider = "openai"
                    logger.info("PermitSearchService: Using OpenAI LLM")
                else:
                    logger.info("No OPENAI_API_KEY - trying Anthropic next")
            except Exception as e:
                logger.warning("Failed to init OpenAI client: %s", e)

        # Try Anthropic as fallback
        if not self.client and _anthropic_available:
            try:
                from config import ANTHROPIC_API_KEY
                if ANTHROPIC_API_KEY:
                    self.client = _anthropic_mod.Anthropic(api_key=ANTHROPIC_API_KEY)
                    self.llm_provider = "anthropic"
                    logger.info("PermitSearchService: Using Anthropic LLM")
                else:
                    logger.info("No ANTHROPIC_API_KEY - using keyword search only")
            except ImportError:
                logger.info("PermitSearchService: anthropic not installed")
            except Exception as e:
                logger.warning("PermitSearchService: Anthropic init failed: %s", e)

        if not self.client:
            logger.info("PermitSearchService: No LLM available -- fallback summaries only")

    def _embed_text(self, text: str) -> Optional[list[float]]:
        """Generate embedding for text using OpenAI."""
        if not self.client or self.llm_provider != "openai":
            return None
        if text in self._embeddings_cache:
            return self._embeddings_cache[text]
        try:
            response = self.client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            embedding = response.data[0].embedding
            self._embeddings_cache[text] = embedding
            return embedding
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def search(
        self,
        query: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: float = 2.0,
        limit: int = 10,
    ) -> list[dict]:
        """Search permits with smart query parsing and optional semantic re-ranking."""
        results = []

        # Strategy 1: Direct search with full query
        results = await self.loader.search(
            query=query,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            limit=limit * 2,  # get more for re-ranking
        )

        if len(results) < 3:
            # Strategy 2: Extract address-like terms and search by address
            addr_match = re.search(
                r'\d+\s+[\w\s]+(st|street|ave|avenue|rd|road|dr|drive|way|blvd|pl|ct|ln|lane)',
                query, re.I,
            )
            if addr_match:
                addr_results = await self.loader.search(
                    address=addr_match.group(0),
                    latitude=latitude,
                    longitude=longitude,
                    radius_km=radius_km,
                    limit=limit,
                )
                results = _merge_results(results, addr_results, limit * 2)

        if len(results) < 3:
            # Strategy 3: Extract town names and search by town
            town_keywords = [
                "boston", "cambridge", "somerville", "brookline", "back bay",
                "seaport", "newton", "quincy", "watertown", "arlington",
                "medford", "malden", "chelsea", "revere", "waltham",
                "dorchester", "south boston", "southie", "fenway", "allston",
                "brighton", "jamaica plain", "roxbury", "charlestown",
            ]
            for town in town_keywords:
                if town in query.lower():
                    town_slug = town.replace(" ", "_")
                    # Map neighborhood aliases to their town_id
                    neighborhood_map = {
                        "back_bay": "boston", "seaport": "boston",
                        "dorchester": "boston", "south_boston": "boston",
                        "southie": "boston", "fenway": "boston",
                        "allston": "boston", "brighton": "boston",
                        "jamaica_plain": "boston", "roxbury": "boston",
                        "charlestown": "boston",
                    }
                    search_town = neighborhood_map.get(town_slug, town_slug)
                    town_results = await self.loader.search(
                        town=search_town,
                        latitude=latitude,
                        longitude=longitude,
                        radius_km=radius_km,
                        limit=limit,
                    )
                    results = _merge_results(results, town_results, limit * 2)
                    break

        if len(results) < 3:
            # Strategy 4: Extract key terms (strip stop words) and search individually
            stop_words = {
                "what", "are", "the", "near", "in", "at", "for", "is", "any",
                "there", "how", "many", "about", "can", "you", "tell", "me",
                "should", "know", "i", "do", "does", "have", "has", "been",
                "this", "that", "with", "from", "on", "of", "and", "or",
                "a", "an", "to", "my", "all", "show", "find", "get",
                "permits", "permit", "building", "construction",
            }
            terms = [w for w in query.lower().split() if w not in stop_words and len(w) > 2]
            if terms:
                for term in terms[:3]:
                    term_results = await self.loader.search(
                        query=term,
                        latitude=latitude,
                        longitude=longitude,
                        radius_km=radius_km,
                        limit=limit,
                    )
                    results = _merge_results(results, term_results, limit * 2)
                    if len(results) >= limit:
                        break

        # If OpenAI available, re-rank by semantic similarity
        query_embedding = self._embed_text(query)
        if query_embedding:
            for r in results:
                text = "{} {} {}".format(
                    r.get("description", ""),
                    r.get("address", ""),
                    r.get("permit_type", ""),
                )
                doc_embedding = self._embed_text(text)
                if doc_embedding:
                    r["relevance_score"] = self._cosine_similarity(query_embedding, doc_embedding)
                else:
                    r["relevance_score"] = 0.5
            results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        else:
            # Assign basic relevance scores
            for i, r in enumerate(results):
                r["relevance_score"] = 1.0 - (i / max(len(results), 1))

        return results[:limit]

    async def generate_answer(
        self,
        question: str,
        context_permits: list[dict],
        property_address: Optional[str] = None,
    ) -> Tuple[str, list[str], float]:
        """Generate a RAG answer from permits context.

        Returns: (answer_text, suggested_questions, confidence)
        """
        if not self.client:
            # No LLM available -- generate a structured summary
            return self._fallback_summary(context_permits, question)

        # Build context for LLM
        context_text = ""
        for p in context_permits[:10]:
            est_val = p.get("estimated_value")
            val_str = "${:,.0f}".format(est_val) if est_val else "N/A"
            context_text += (
                "Permit: {}\n"
                "Address: {}\n"
                "Type: {}\n"
                "Status: {}\n"
                "Description: {}\n"
                "Estimated Value: {}\n"
                "Filed: {}\n"
                "Applicant: {}\n"
                "---\n"
            ).format(
                p.get("permit_number", "N/A"),
                p.get("address", "N/A"),
                p.get("permit_type", "N/A"),
                p.get("status", "N/A"),
                p.get("description", "N/A"),
                val_str,
                p.get("filed_date", "N/A"),
                p.get("applicant_name", "N/A"),
            )

        property_context = ""
        if property_address:
            property_context = "\nThe user is asking about property at: {}\n".format(property_address)

        system_prompt = (
            "You are Parcl Intelligence, an AI assistant for real estate professionals.\n"
            "You analyze building permits, construction activity, and development trends.\n"
            "Answer questions based on the permit data provided. Be specific about addresses, values, and dates.\n"
            "If the data doesn't contain enough info to answer, say so."
            + property_context
        )

        user_prompt = (
            "Based on these permits:\n\n{}\n\n"
            "Question: {}\n\n"
            "Provide a concise, actionable answer for a real estate professional. "
            "End with 2-3 suggested follow-up questions."
        ).format(context_text, question)

        try:
            if self.llm_provider == "anthropic":
                response = self.client.messages.create(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=800,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                answer = response.content[0].text
            elif self.llm_provider == "openai":
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=800,
                )
                answer = response.choices[0].message.content or "Unable to generate response."
            else:
                return self._fallback_summary(context_permits, question)

            # Extract suggested questions (simple heuristic)
            suggested = []
            lines = answer.split("\n")
            for line in lines:
                line = line.strip()
                if line and line.endswith("?") and len(line) > 20:
                    clean = line.lstrip("- *)")
                    # Also strip leading digits and dots
                    clean = re.sub(r'^[\d.\s]+', '', clean)
                    if clean:
                        suggested.append(clean)

            return answer, suggested[:3], 0.85

        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            return self._fallback_summary(context_permits, question)

    # -- Fallback summary (no LLM) ----------------------------------------

    @staticmethod
    def _fallback_summary(
        permits: list[dict], question: str
    ) -> Tuple[str, list[str], float]:
        """Generate a useful structured summary without an LLM."""
        if not permits:
            return (
                "I couldn't find specific permits matching your query. "
                "Try searching for a specific address like '100 Main St' "
                "or ask about permits in a specific town like 'Boston' or 'Cambridge'.",
                [],
                0.3,
            )

        lines = ["I found {} relevant permit(s):\n".format(len(permits))]
        for i, p in enumerate(permits[:5], 1):
            addr = p.get("address") or "Unknown address"
            ptype = p.get("permit_type") or "Unknown type"
            status = p.get("status") or "Unknown"
            est_val = p.get("estimated_value")
            val_str = " - ${:,.0f}".format(est_val) if est_val else ""
            desc = (p.get("description") or "")[:120]
            lines.append("{}. **{}** -- {} ({}){}".format(i, addr, ptype, status, val_str))
            if desc:
                lines.append("   {}".format(desc))

        if len(permits) > 5:
            lines.append("\n...and {} more permit(s).".format(len(permits) - 5))

        suggested = [
            "What types of permits are most common here?",
            "Show me the most recent permits",
            "Are there any large construction projects nearby?",
        ]
        return "\n".join(lines), suggested, 0.6
