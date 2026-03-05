"""
Supabase REST API Client for Parcl Intelligence.

Uses the PostgREST API (Supabase REST) instead of direct PostgreSQL connections.
This bypasses connection authentication issues while providing full query capability
against the municipal-intel permit database (125K+ permits, 351 MA municipalities).

Usage:
    client = SupabaseRestClient(url="https://xxx.supabase.co", service_key="eyJ...")
    await client.connect()
    rows = await client.fetch("documents", select="*", filters={"source_type": "eq.permit"}, limit=50)
    count = await client.count("documents", filters={"source_type": "eq.permit"})
    await client.disconnect()
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


class SupabaseRestClient:
    """
    Async client for Supabase PostgREST API.

    Provides query methods that map to PostgREST URL conventions:
    - fetch: SELECT with optional filters, ordering, pagination
    - count: COUNT with optional filters
    - rpc:   Call stored procedures / edge functions
    """

    def __init__(self, url: str, service_key: str):
        self._base_url = url.rstrip("/")
        self._rest_url = f"{self._base_url}/rest/v1"
        self._service_key = service_key
        self._client: Optional[Any] = None
        self._connected = False

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def base_url(self) -> str:
        return self._base_url

    # ── Connection lifecycle ────────────────────────────────────────────

    async def connect(self) -> bool:
        """Initialize HTTP client and verify connectivity."""
        if httpx is None:
            logger.error(
                "httpx is not installed — cannot use Supabase REST API. "
                "Install with: pip install httpx"
            )
            return False

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

        # Test connectivity with a lightweight query
        try:
            resp = await self._client.get(
                f"{self._rest_url}/towns",
                headers=self._headers(),
                params={"select": "id", "limit": "1"},
            )
            if resp.status_code == 200:
                self._connected = True
                logger.info("Supabase REST API connected")
                return True
            else:
                logger.error(
                    "Supabase connection test failed: HTTP %d — %s",
                    resp.status_code, resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Supabase connection failed: %s", exc)
            return False

    async def disconnect(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        logger.info("Supabase REST client disconnected")

    # ── Query methods ───────────────────────────────────────────────────

    async def fetch(
        self,
        table: str,
        select: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> list[dict]:
        """
        Query a table via PostgREST.

        Args:
            table:   Table name (e.g. "documents", "towns")
            select:  Column selection with optional embedded resources
                     e.g. "*,document_metadata(*),document_locations(*)"
            filters: Dict of PostgREST filters
                     e.g. {"source_type": "eq.permit", "town_id": "eq.boston"}
            order:   Order clause e.g. "created_at.desc"
            limit:   Max rows to return
            offset:  Skip rows (for pagination)

        Returns:
            List of row dicts (with embedded resources as nested dicts/lists)
        """
        if not self._client:
            raise RuntimeError("Supabase client not connected — call connect() first")

        params: dict[str, str] = {"select": select}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)

        resp = await self._client.get(
            f"{self._rest_url}/{table}",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_all(
        self,
        table: str,
        select: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        page_size: int = 1000,
    ) -> list[dict]:
        """
        Fetch ALL rows from a table, paginating through PostgREST's 1000-row limit.

        Uses offset-based pagination to retrieve every matching row.
        Suitable for tables with <50K rows (e.g. coverage matrix = 12,987 rows).
        """
        all_rows: list[dict] = []
        offset = 0
        while True:
            batch = await self.fetch(
                table, select=select, filters=filters,
                order=order, limit=page_size, offset=offset,
            )
            all_rows.extend(batch)
            if len(batch) < page_size:
                break  # Last page
            offset += page_size
        return all_rows

    async def count(
        self,
        table: str,
        filters: Optional[dict] = None,
    ) -> int:
        """
        Get count of rows matching filters.

        Uses ``Prefer: count=exact`` header and reads ``Content-Range``.
        This is very fast — it only returns the count, not the rows.
        """
        if not self._client:
            raise RuntimeError("Supabase client not connected — call connect() first")

        params: dict[str, str] = {"select": "id"}
        if filters:
            params.update(filters)

        headers = self._headers({"Prefer": "count=exact", "Range": "0-0"})

        resp = await self._client.get(
            f"{self._rest_url}/{table}",
            headers=headers,
            params=params,
        )

        # Count is in Content-Range header: "0-0/125795"
        content_range = resp.headers.get("content-range", "")
        if "/" in content_range:
            total = content_range.split("/")[-1]
            if total != "*":
                return int(total)
        return 0

    async def rpc(self, function_name: str, params: Optional[dict] = None) -> Any:
        """
        Call a Supabase RPC (stored function / edge function).

        Args:
            function_name: Name of the function
            params: Function parameters as a dict
        """
        if not self._client:
            raise RuntimeError("Supabase client not connected — call connect() first")

        resp = await self._client.post(
            f"{self._rest_url}/rpc/{function_name}",
            headers=self._headers(),
            json=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    async def insert(
        self,
        table: str,
        data: dict | list[dict],
        upsert: bool = False,
    ) -> list[dict]:
        """
        Insert one or more rows into a table.

        Uses PostgREST POST method.

        Args:
            table:   Table name
            data:    Dict (single row) or list of dicts (batch insert)
            upsert:  If True, use Prefer: resolution=merge-duplicates

        Returns:
            List of inserted row dicts (if Prefer: return=representation)
        """
        if not self._client:
            raise RuntimeError("Supabase client not connected — call connect() first")

        prefer = "return=representation"
        if upsert:
            prefer += ",resolution=merge-duplicates"

        headers = self._headers({"Prefer": prefer})

        resp = await self._client.post(
            f"{self._rest_url}/{table}",
            headers=headers,
            json=data,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Insert failed: status={resp.status_code} body={resp.text[:300]}"
            )

        try:
            return resp.json()
        except Exception:
            return []

    async def delete(
        self,
        table: str,
        filters: dict,
    ) -> bool:
        """
        Delete rows matching filters.

        Uses PostgREST DELETE method.

        Args:
            table:   Table name
            filters: PostgREST filters to select rows (e.g. {"id": "eq.uuid-here"})

        Returns:
            True if request succeeded
        """
        if not self._client:
            raise RuntimeError("Supabase client not connected — call connect() first")

        params: dict[str, str] = {}
        params.update(filters)

        headers = self._headers({"Prefer": "return=minimal"})

        resp = await self._client.delete(
            f"{self._rest_url}/{table}",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        return True

    async def update(
        self,
        table: str,
        filters: dict,
        data: dict,
    ) -> list[dict]:
        """
        Update rows matching filters with the given data.

        Uses PostgREST PATCH method.

        Args:
            table:   Table name
            filters: PostgREST filters to select rows (e.g. {"id": "eq.uuid-here"})
            data:    Dict of column→value pairs to update

        Returns:
            List of updated row dicts (if Prefer: return=representation is set)
        """
        if not self._client:
            raise RuntimeError("Supabase client not connected — call connect() first")

        params: dict[str, str] = {}
        params.update(filters)

        headers = self._headers({"Prefer": "return=minimal"})

        resp = await self._client.patch(
            f"{self._rest_url}/{table}",
            headers=headers,
            params=params,
            json=data,
        )
        resp.raise_for_status()
        return []

    # ── Internal helpers ────────────────────────────────────────────────

    def _headers(self, extra: Optional[dict] = None) -> dict:
        """Build request headers with auth."""
        h = {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h
