"""ViewpointCloud (OpenGov) API connector.

Ported from municipal-intel for Parcl Intelligence.

This connector uses the public ViewpointCloud API powering many OpenGov portals.
It is designed for:
- capability checks (general_settings allowPublic* flags)
- address/location search
- record enumeration for a single locationID (property-centric)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

import httpx


DEFAULT_API_BASES: Tuple[str, ...] = (
    "https://api-east.viewpointcloud.com/v2",
    "https://api-west.viewpointcloud.com/v2",
)


@dataclass(frozen=True)
class LocationHit:
    entity_id: str
    result_text: str
    secondary_text: Optional[str]
    score: Optional[float]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class RecordSummary:
    record_id: str
    record_no: Optional[str]
    record_type_name: Optional[str]
    date_created: Optional[str]
    status: Optional[Any]
    raw: Dict[str, Any]


class ViewpointCloudError(RuntimeError):
    pass


async def fetch_general_settings(
    *,
    community_slug: str,
    client: httpx.AsyncClient,
    api_bases: Sequence[str] = DEFAULT_API_BASES,
    timeout_s: float = 20.0,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """Fetch general_settings for a community slug.

    Returns (api_base, payload, error_message).
    """
    last_err: Optional[str] = None
    for api_base in api_bases:
        url = f"{api_base}/{community_slug}/general_settings"
        try:
            resp = await client.get(url, timeout=timeout_s)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return api_base, data, None
                last_err = "non_object_json"
                continue
            last_err = f"status={resp.status_code}"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:120]}"
    return None, None, last_err


class ViewpointCloudClient:
    """Async client for ViewpointCloud/OpenGov permit portals."""

    def __init__(
        self,
        *,
        community_slug: str,
        api_base: str,
        client: httpx.AsyncClient,
    ):
        self.community_slug = community_slug
        self.api_base = api_base.rstrip("/")
        self._http = client

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.api_base}/{self.community_slug}/{path}"

    async def general_settings(self) -> Dict[str, Any]:
        resp = await self._http.get(self._url("general_settings"), timeout=20.0)
        if resp.status_code != 200:
            raise ViewpointCloudError(
                f"general_settings failed: status={resp.status_code}"
            )
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ViewpointCloudError("general_settings returned non-object JSON")
        return payload

    async def search_results(
        self,
        *,
        criteria: str,
        key: str,
        ignore_community: bool = True,
        timestamp_ms: Optional[int] = None,
        timeout_s: float = 20.0,
    ) -> List[Dict[str, Any]]:
        if not key.strip():
            raise ValueError("key must be non-empty")
        params = {
            "criteria": criteria,
            "key": key,
            "timeStamp": str(
                int(
                    timestamp_ms
                    if timestamp_ms is not None
                    else time.time() * 1000
                )
            ),
            "ignoreCommunity": "true" if ignore_community else "false",
        }
        resp = await self._http.get(
            self._url("search_results"), params=params, timeout=timeout_s
        )
        if resp.status_code != 200:
            raise ViewpointCloudError(
                f"search_results failed: status={resp.status_code}"
            )
        data = resp.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        raise ViewpointCloudError("search_results returned non-list JSON")

    async def search_locations(
        self, *, query: str, limit: int = 10
    ) -> List[LocationHit]:
        results = await self.search_results(criteria="location", key=query)
        hits: List[LocationHit] = []
        for item in results:
            if item.get("entityType") != "location":
                continue
            entity_id = str(item.get("entityID") or "").strip()
            if not entity_id:
                continue
            hits.append(
                LocationHit(
                    entity_id=entity_id,
                    result_text=str(item.get("resultText") or "").strip(),
                    secondary_text=str(item.get("secondaryText") or "").strip()
                    or None,
                    score=float(item.get("@search.score"))
                    if item.get("@search.score") is not None
                    else None,
                    raw=item,
                )
            )
        hits.sort(key=lambda h: (h.score or 0.0), reverse=True)
        return hits[: max(limit, 1)]

    async def list_records_for_location(
        self,
        *,
        location_id: str,
        page_size: int = 50,
        page_number: int = 1,
        timeout_s: float = 30.0,
    ) -> Dict[str, Any]:
        params = {
            "locationID": location_id,
            "page[size]": str(page_size),
            "page[number]": str(page_number),
        }
        resp = await self._http.get(
            self._url("records"), params=params, timeout=timeout_s
        )
        if resp.status_code != 200:
            raise ViewpointCloudError(
                f"records list failed: status={resp.status_code}"
            )
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ViewpointCloudError("records list returned non-object JSON")
        return payload

    async def iter_record_summaries_for_location(
        self,
        *,
        location_id: str,
        page_size: int = 50,
        max_records: int = 500,
    ) -> AsyncIterator[RecordSummary]:
        fetched = 0
        page = 1
        total: Optional[int] = None

        while fetched < max_records:
            payload = await self.list_records_for_location(
                location_id=location_id,
                page_size=page_size,
                page_number=page,
            )
            data = payload.get("data") or []
            meta = payload.get("meta") or {}
            if (
                total is None
                and isinstance(meta, dict)
                and isinstance(meta.get("total"), int)
            ):
                total = int(meta["total"])

            if not isinstance(data, list) or not data:
                break

            for item in data:
                if not isinstance(item, dict):
                    continue
                record_id = str(item.get("id") or "").strip()
                attrs = item.get("attributes") or {}
                if not record_id or not isinstance(attrs, dict):
                    continue

                yield RecordSummary(
                    record_id=record_id,
                    record_no=str(attrs.get("recordNo")).strip()
                    if attrs.get("recordNo")
                    else None,
                    record_type_name=str(attrs.get("recordTypeName")).strip()
                    if attrs.get("recordTypeName")
                    else None,
                    date_created=str(attrs.get("dateCreated")).strip()
                    if attrs.get("dateCreated")
                    else None,
                    status=attrs.get("status"),
                    raw=item,
                )

                fetched += 1
                if fetched >= max_records:
                    break

            page += 1
            if total is not None and (page - 1) * page_size >= total:
                break

    async def fetch_record_detail(
        self, *, record_id: str, timeout_s: float = 30.0
    ) -> Dict[str, Any]:
        resp = await self._http.get(
            self._url(f"records/{record_id}"), timeout=timeout_s
        )
        if resp.status_code != 200:
            raise ViewpointCloudError(
                f"record detail failed: id={record_id} status={resp.status_code}"
            )
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ViewpointCloudError("record detail returned non-object JSON")
        return payload
