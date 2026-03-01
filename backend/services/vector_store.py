"""Vector Store for document embedding and retrieval (RAG Agent backing store)."""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from loguru import logger

from config import CHROMA_PERSIST_DIR


class VectorStore:
    """Lightweight vector store wrapping ChromaDB for SEC filing RAG.

    Falls back to an in-memory dictionary cache when ChromaDB is not
    installed, which is sufficient for the POC.
    """

    def __init__(self, collection_name: str = "sentinel_filings") -> None:
        self._collection_name = collection_name
        self._client = None
        self._collection = None
        self._fallback_cache: dict[str, dict] = {}
        self._initialised = False
        self._try_init_chroma()

    def _try_init_chroma(self) -> None:
        try:
            import chromadb

            self._client = chromadb.Client(
                chromadb.config.Settings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=CHROMA_PERSIST_DIR,
                    anonymized_telemetry=False,
                )
            )
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name
            )
            self._initialised = True
            logger.info("VectorStore: ChromaDB initialised")
        except Exception as exc:
            logger.warning(
                f"VectorStore: ChromaDB unavailable ({exc}), using in-memory fallback"
            )
            self._initialised = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upsert(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """Store or update a document chunk.  Returns the doc_id."""
        metadata = metadata or {}
        if self._initialised and self._collection is not None:
            self._collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata],
            )
        else:
            self._fallback_cache[doc_id] = {
                "text": text,
                "metadata": metadata,
            }
        logger.debug(f"VectorStore upsert: {doc_id}")
        return doc_id

    async def query(
        self,
        query_text: str,
        n_results: int = 5,
        where_filter: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search.  Returns list of {id, text, metadata, distance}."""
        if self._initialised and self._collection is not None:
            kwargs: dict = {"query_texts": [query_text], "n_results": n_results}
            if where_filter:
                kwargs["where"] = where_filter
            results = self._collection.query(**kwargs)
            out = []
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for i, doc_id in enumerate(ids):
                out.append(
                    {
                        "id": doc_id,
                        "text": docs[i] if i < len(docs) else "",
                        "metadata": metas[i] if i < len(metas) else {},
                        "distance": dists[i] if i < len(dists) else 1.0,
                    }
                )
            return out

        # Fallback: naive keyword search
        query_lower = query_text.lower()
        scored: list[tuple[float, str, dict]] = []
        for doc_id, doc in self._fallback_cache.items():
            text = doc["text"].lower()
            words = query_lower.split()
            hits = sum(1 for w in words if w in text)
            if hits > 0:
                score = hits / max(len(words), 1)
                scored.append((score, doc_id, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id": doc_id,
                "text": doc["text"][:2000],
                "metadata": doc["metadata"],
                "distance": 1.0 - score,
            }
            for score, doc_id, doc in scored[:n_results]
        ]

    async def get(self, doc_id: str) -> Optional[dict]:
        """Retrieve a single document by id."""
        if self._initialised and self._collection is not None:
            result = self._collection.get(ids=[doc_id])
            ids = result.get("ids", [])
            if ids:
                docs = result.get("documents", [])
                metas = result.get("metadatas", [])
                return {
                    "id": ids[0],
                    "text": docs[0] if docs else "",
                    "metadata": metas[0] if metas else {},
                }
            return None
        return self._fallback_cache.get(doc_id)

    async def delete(self, doc_id: str) -> bool:
        """Remove a document by id."""
        if self._initialised and self._collection is not None:
            self._collection.delete(ids=[doc_id])
            return True
        removed = self._fallback_cache.pop(doc_id, None)
        return removed is not None

    @property
    def count(self) -> int:
        if self._initialised and self._collection is not None:
            return self._collection.count()
        return len(self._fallback_cache)
