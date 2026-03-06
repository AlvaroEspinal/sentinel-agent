"""
ATTOM Property API connector.

Async client for fetching property characteristics, sales/deed history,
mortgage/lien detail, and foreclosure status from the ATTOM Data Solutions
Property API (v1.0.0).

Authentication is header-based:  apikey: <key>
Docs: https://api.gateway.attomdata.com/propertyapi/v1.0.0
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class AttomAPIError(Exception):
    """Raised when the ATTOM API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"ATTOM API {status_code}: {detail}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AttomClient:
    """Async client for the ATTOM Property API.

    Parameters
    ----------
    api_key : str
        ATTOM API key.  Falls back to ``config.ATTOM_API_KEY`` if omitted.
    timeout : float
        Request timeout in seconds (default 15).
    """

    def __init__(self, api_key: str | None = None, timeout: float = 15.0):
        if api_key is None:
            from config import ATTOM_API_KEY

            api_key = ATTOM_API_KEY
        if not api_key:
            raise ValueError(
                "ATTOM_API_KEY is required.  Set it in .env or pass api_key= to AttomClient."
            )
        self._api_key = api_key
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._api_key,
            "accept": "application/json",
        }

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict:
        """Issue a GET to *endpoint* and return the parsed JSON body.

        Raises ``AttomAPIError`` on non-2xx responses and logs rate-limit
        warnings on 429.
        """
        url = f"{BASE_URL}{endpoint}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers=self._headers(), params=params)

        if resp.status_code == 429:
            logger.warning("[ATTOM] Rate-limited (HTTP 429) on %s", endpoint)
            raise AttomAPIError(429, "Rate limit exceeded – retry later")

        if resp.status_code != 200:
            body = resp.text[:300]
            logger.error(
                "[ATTOM] %s returned %s: %s", endpoint, resp.status_code, body
            )
            raise AttomAPIError(resp.status_code, body)

        return resp.json()

    @staticmethod
    def _address_params(address1: str, address2: str) -> dict[str, str]:
        return {"address1": address1, "address2": address2}

    @staticmethod
    def _coord_params(lat: float, lon: float) -> dict[str, str]:
        return {"latitude": str(lat), "longitude": str(lon)}

    # ------------------------------------------------------------------
    # Property characteristics
    # ------------------------------------------------------------------

    async def get_property_detail(
        self, address1: str, address2: str
    ) -> dict:
        """Fetch full property characteristics by street address.

        Parameters
        ----------
        address1 : str   Street address, e.g. ``"83 Longfellow Rd"``
        address2 : str   City/State/Zip, e.g. ``"Wellesley, MA"``
        """
        try:
            raw = await self._request(
                "/property/detail", self._address_params(address1, address2)
            )
            return self._normalise_property_detail(raw)
        except Exception as exc:
            logger.error("[ATTOM] get_property_detail failed: %s", exc)
            return self._empty_property_detail(str(exc))

    async def get_property_detail_by_coords(
        self, lat: float, lon: float
    ) -> dict:
        """Fetch full property characteristics by lat/lon."""
        try:
            raw = await self._request(
                "/property/detail", self._coord_params(lat, lon)
            )
            return self._normalise_property_detail(raw)
        except Exception as exc:
            logger.error("[ATTOM] get_property_detail_by_coords failed: %s", exc)
            return self._empty_property_detail(str(exc))

    # ------------------------------------------------------------------
    # Sales / deed history
    # ------------------------------------------------------------------

    async def get_sales_history(
        self, address1: str, address2: str
    ) -> dict:
        """Fetch deed / sales transaction history by address."""
        try:
            raw = await self._request(
                "/sale/detail", self._address_params(address1, address2)
            )
            return self._normalise_sales(raw)
        except Exception as exc:
            logger.error("[ATTOM] get_sales_history failed: %s", exc)
            return self._empty_sales(str(exc))

    async def get_sales_history_by_coords(
        self, lat: float, lon: float
    ) -> dict:
        """Fetch deed / sales transaction history by lat/lon."""
        try:
            raw = await self._request(
                "/sale/detail", self._coord_params(lat, lon)
            )
            return self._normalise_sales(raw)
        except Exception as exc:
            logger.error("[ATTOM] get_sales_history_by_coords failed: %s", exc)
            return self._empty_sales(str(exc))

    # ------------------------------------------------------------------
    # Mortgage / lien detail
    # ------------------------------------------------------------------

    async def get_mortgage_detail(
        self, address1: str, address2: str
    ) -> dict:
        """Fetch current mortgage & lien information by address."""
        try:
            raw = await self._request(
                "/property/detailmortgage",
                self._address_params(address1, address2),
            )
            return self._normalise_mortgage(raw)
        except Exception as exc:
            logger.error("[ATTOM] get_mortgage_detail failed: %s", exc)
            return self._empty_mortgage(str(exc))

    async def get_mortgage_detail_by_coords(
        self, lat: float, lon: float
    ) -> dict:
        """Fetch current mortgage & lien information by lat/lon."""
        try:
            raw = await self._request(
                "/property/detailmortgage", self._coord_params(lat, lon)
            )
            return self._normalise_mortgage(raw)
        except Exception as exc:
            logger.error("[ATTOM] get_mortgage_detail_by_coords failed: %s", exc)
            return self._empty_mortgage(str(exc))

    # ------------------------------------------------------------------
    # Convenience: full profile
    # ------------------------------------------------------------------

    async def get_full_profile(
        self, address1: str, address2: str
    ) -> dict:
        """Call all endpoints and merge results into a single dict."""
        detail = await self.get_property_detail(address1, address2)
        sales = await self.get_sales_history(address1, address2)
        mortgage = await self.get_mortgage_detail(address1, address2)

        return {
            "property_detail": detail,
            "sales_history": sales,
            "mortgage_detail": mortgage,
            "address": {"address1": address1, "address2": address2},
            "source": "ATTOM Property API",
        }

    # ==================================================================
    # Response normalisers
    # ==================================================================

    @staticmethod
    def _safe_get(data: dict, *keys: str, default=None):
        """Walk a nested dict safely."""
        node = data
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k)
            if node is None:
                return default
        return node

    # ---- property detail ----

    def _normalise_property_detail(self, raw: dict) -> dict:
        props = self._first_property(raw)
        if not props:
            return self._empty_property_detail("No property found in response")

        building = self._safe_get(props, "building", "size") or {}
        summary = self._safe_get(props, "building", "summary") or {}
        rooms = self._safe_get(props, "building", "rooms") or {}
        lot = self._safe_get(props, "lot") or {}
        address = self._safe_get(props, "address") or {}
        vintage = self._safe_get(props, "summary") or {}
        assessment = self._safe_get(props, "assessment") or {}

        return {
            "attom_id": self._safe_get(props, "identifier", "attomId"),
            "fips": self._safe_get(props, "identifier", "fips"),
            "apn": self._safe_get(props, "identifier", "apn"),
            "address_one_line": self._safe_get(address, "oneLine"),
            "city": self._safe_get(address, "locality"),
            "state": self._safe_get(address, "countrySubd"),
            "zip": self._safe_get(address, "postal1"),
            "county": self._safe_get(address, "countrySecSubd"),
            "latitude": self._safe_get(address, "latitude"),
            "longitude": self._safe_get(address, "longitude"),
            "property_type": self._safe_get(vintage, "propclass"),
            "property_subtype": self._safe_get(vintage, "propsubtype"),
            "year_built": self._safe_get(vintage, "yearbuilt"),
            "bedrooms": self._safe_get(rooms, "beds"),
            "bathrooms_full": self._safe_get(rooms, "bathsfull"),
            "bathrooms_half": self._safe_get(rooms, "bathshalf"),
            "bathrooms_total": self._safe_get(rooms, "bathstotal"),
            "living_area_sqft": self._safe_get(building, "livingsize"),
            "building_area_sqft": self._safe_get(building, "universalsize"),
            "stories": self._safe_get(summary, "levels"),
            "lot_size_sqft": self._safe_get(lot, "lotsize1"),
            "lot_size_acres": self._safe_get(lot, "lotsize2"),
            "assessed_total": self._safe_get(assessment, "assessed", "assdttlvalue"),
            "assessed_land": self._safe_get(assessment, "assessed", "assdlandvalue"),
            "assessed_improvement": self._safe_get(
                assessment, "assessed", "assdimprvalue"
            ),
            "market_total": self._safe_get(assessment, "market", "mktttlvalue"),
            "tax_amount": self._safe_get(assessment, "tax", "taxamt"),
            "tax_year": self._safe_get(assessment, "tax", "taxyear"),
            "source": "ATTOM Property API",
        }

    @staticmethod
    def _empty_property_detail(error: str = "") -> dict:
        return {
            "attom_id": None,
            "address_one_line": None,
            "error": error or None,
            "source": "ATTOM Property API",
        }

    # ---- sales / deed history ----

    def _normalise_sales(self, raw: dict) -> dict:
        props = self._first_property(raw)
        if not props:
            return self._empty_sales("No property found in response")

        sale_history = self._safe_get(props, "salehistory") or []
        if isinstance(sale_history, dict):
            sale_history = [sale_history]

        transactions: list[dict] = []
        for sale in sale_history:
            amount = self._safe_get(sale, "amount") or {}
            deed_info = self._safe_get(sale, "calculation") or {}
            transactions.append(
                {
                    "sale_date": self._safe_get(sale, "amount", "salerecdate"),
                    "sale_price": self._safe_get(amount, "saleamt"),
                    "sale_transaction_type": self._safe_get(
                        amount, "saletranstype"
                    ),
                    "deed_type": self._safe_get(sale, "deed", "documenttype"),
                    "buyer_name": self._safe_get(sale, "buyer", "fullname"),
                    "seller_name": self._safe_get(sale, "seller", "fullname"),
                    "recording_date": self._safe_get(sale, "amount", "salerecdate"),
                    "document_number": self._safe_get(
                        sale, "deed", "documentnumber"
                    ),
                    "price_per_sqft": self._safe_get(
                        deed_info, "pricepersizeunit"
                    ),
                }
            )

        return {
            "attom_id": self._safe_get(props, "identifier", "attomId"),
            "address_one_line": self._safe_get(props, "address", "oneLine"),
            "transaction_count": len(transactions),
            "transactions": transactions,
            "source": "ATTOM Property API",
        }

    @staticmethod
    def _empty_sales(error: str = "") -> dict:
        return {
            "attom_id": None,
            "transaction_count": 0,
            "transactions": [],
            "error": error or None,
            "source": "ATTOM Property API",
        }

    # ---- mortgage / lien detail ----

    def _normalise_mortgage(self, raw: dict) -> dict:
        props = self._first_property(raw)
        if not props:
            return self._empty_mortgage("No property found in response")

        mortgages: list[dict] = []
        for key in ("mortgage1", "mortgage2", "mortgage3", "mortgage4"):
            m = self._safe_get(props, key)
            if not m:
                continue
            amount = m.get("amount") or {}
            mortgages.append(
                {
                    "lien_position": key.replace("mortgage", ""),
                    "lender_name": self._safe_get(m, "lender", "fullname"),
                    "loan_amount": self._safe_get(amount, "loanamt"),
                    "interest_rate": self._safe_get(m, "interestrate", "rate"),
                    "interest_rate_type": self._safe_get(
                        m, "interestrate", "type"
                    ),
                    "loan_type": self._safe_get(m, "loantype"),
                    "deed_type": self._safe_get(m, "deedtype"),
                    "due_date": self._safe_get(m, "duedate"),
                    "recording_date": self._safe_get(m, "recordingdate"),
                }
            )

        return {
            "attom_id": self._safe_get(props, "identifier", "attomId"),
            "address_one_line": self._safe_get(props, "address", "oneLine"),
            "mortgage_count": len(mortgages),
            "mortgages": mortgages,
            "source": "ATTOM Property API",
        }

    @staticmethod
    def _empty_mortgage(error: str = "") -> dict:
        return {
            "attom_id": None,
            "mortgage_count": 0,
            "mortgages": [],
            "error": error or None,
            "source": "ATTOM Property API",
        }

    # ---- shared ----

    @staticmethod
    def _first_property(raw: dict) -> Optional[dict]:
        """Extract the first property dict from a typical ATTOM response envelope."""
        status = raw.get("status", {})
        if status.get("code") and status["code"] != 0:
            logger.warning("[ATTOM] API status code %s: %s", status.get("code"), status.get("msg"))
            return None
        prop_list = raw.get("property")
        if isinstance(prop_list, list) and prop_list:
            return prop_list[0]
        if isinstance(prop_list, dict):
            return prop_list
        return None
