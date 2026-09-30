"""Shippo multi-carrier client (rates, labels, tracking) — plain REST via httpx."""
import logging
import math
import secrets
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

SHIPPO_BASE = "https://api.goshippo.com"
SHIPPO_API_VERSION = "2018-02-08"

# Shippo provider labels / carrier tokens → our carrier codes
PROVIDER_TO_CODE = {
    "ups": "ups", "fedex": "fedex", "usps": "usps",
    "canada post": "canadapost", "canada_post": "canadapost", "canadapost": "canadapost",
    "purolator": "purolator",
}
CODE_TO_PROVIDER_LABEL = {"ups": "UPS", "fedex": "FedEx", "usps": "USPS", "canadapost": "Canada Post", "purolator": "Purolator", "other": "Other"}

DEFAULT_SHIPPO_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "api_token": "",
    "default_parcel": {"length": 30, "width": 20, "height": 15, "unit": "cm"},
    "markup_percent": 0,
    "markup_flat": 0,
    "allowed_carriers": [],  # empty = every carrier Shippo returns
    "webhook_token": "",
    "webhook_registered_id": "",
}


class ShippoError(Exception):
    def __init__(self, message: str, status: int = 502, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def provider_code(provider: str) -> str:
    return PROVIDER_TO_CODE.get((provider or "").strip().lower(), "other")


def money(value) -> float:
    return float(Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


REGION_CODES = {
    "CA": {"alberta": "AB", "british columbia": "BC", "manitoba": "MB", "new brunswick": "NB", "newfoundland and labrador": "NL", "newfoundland": "NL",
           "nova scotia": "NS", "northwest territories": "NT", "nunavut": "NU", "ontario": "ON", "prince edward island": "PE", "pei": "PE",
           "quebec": "QC", "québec": "QC", "saskatchewan": "SK", "yukon": "YT"},
    "US": {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
           "district of columbia": "DC", "washington dc": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
           "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
           "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
           "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
           "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
           "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR"},
}


def normalize_region(state: str, country: str) -> str:
    """Carriers want 2-letter codes for US/CA ('Ontario' → 'ON'); other countries pass through."""
    s = (state or "").strip()
    table = REGION_CODES.get((country or "").upper())
    if not table or not s:
        return s
    if len(s) == 2:
        return s.upper()
    return table.get(s.lower().replace(".", ""), s)


def to_shippo_address(addr: dict, email: str = "") -> dict:
    addr = addr or {}
    country = (addr.get("country") or "").upper()
    out = {
        "name": addr.get("name") or addr.get("company") or "Customer",
        "company": addr.get("company") or "",
        "street1": addr.get("address1") or addr.get("street1") or "",
        "street2": addr.get("address2") or addr.get("street2") or "",
        "city": addr.get("city") or "",
        "state": normalize_region(addr.get("state") or "", country),
        "zip": (addr.get("postal_code") or addr.get("zip") or "").upper(),
        "country": country,
        "phone": addr.get("phone") or "",
        "email": addr.get("email") or email or "",
    }
    return {k: v for k, v in out.items() if v != ""}


def address_complete(addr: dict) -> bool:
    a = to_shippo_address(addr)
    return all(a.get(k) for k in ("street1", "city", "zip", "country"))


def build_parcel(items: List[dict], default_parcel: dict, weight_unit: str) -> dict:
    """One box per order: max L/W of the items, heights stacked, total weight. Missing dims fall back to the default box."""
    unit = (default_parcel or {}).get("unit") or "cm"
    dl = float((default_parcel or {}).get("length") or 30)
    dw = float((default_parcel or {}).get("width") or 20)
    dh = float((default_parcel or {}).get("height") or 15)
    max_l = max_w = 0.0
    stacked_h = 0.0
    total_kg = 0.0
    any_dims = False
    for entry in items:
        item = entry["item"]
        qty = max(1, int(entry.get("quantity", 1)))
        w = float(item.get("weight") or 0)
        total_kg += (w * 0.45359237 if item.get("weight_unit") == "lb" else w) * qty
        l, wd, h = float(item.get("length") or 0), float(item.get("width") or 0), float(item.get("height") or 0)
        if l > 0 and wd > 0 and h > 0:
            any_dims = True
            if item.get("dimension_unit") == "in" and unit == "cm":
                l, wd, h = l * 2.54, wd * 2.54, h * 2.54
            elif item.get("dimension_unit") == "cm" and unit == "in":
                l, wd, h = l / 2.54, wd / 2.54, h / 2.54
            max_l, max_w = max(max_l, l), max(max_w, wd)
            stacked_h += h * qty
    if not any_dims:
        max_l, max_w, stacked_h = dl, dw, dh
    if total_kg <= 0:
        total_kg = 0.5
    if weight_unit == "lb":
        weight, mass_unit = round(total_kg / 0.45359237, 3), "lb"
    else:
        weight, mass_unit = round(total_kg, 3), "kg"
    return {
        "length": str(round(max(max_l, 1), 2)), "width": str(round(max(max_w, 1), 2)), "height": str(round(max(stacked_h, 1), 2)),
        "distance_unit": unit, "weight": str(max(weight, 0.01)), "mass_unit": mass_unit,
    }


class ShippoClient:
    def __init__(self, token: str):
        if not token:
            raise ShippoError("Shippo API token is not configured", 400)
        self.token = token
        self.is_test = token.startswith("shippo_test_")
        self._headers = {
            "Authorization": f"ShippoToken {token}",
            "Shippo-API-Version": SHIPPO_API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        try:
            async with httpx.AsyncClient(base_url=SHIPPO_BASE, headers=self._headers, timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                resp = await client.request(method, path, json=json, params=params)
        except httpx.HTTPError as e:
            raise ShippoError(f"Could not reach Shippo: {e}", 502)
        if resp.status_code == 401:
            raise ShippoError("Shippo rejected the API token (401). Check the key in Shipping settings.", 401)
        if resp.is_error:
            body = resp.text[:600]
            logger.error(f"Shippo {method} {path} -> {resp.status_code}: {body}")
            try:
                detail = resp.json()
            except ValueError:
                detail = body
            raise ShippoError(f"Shippo request failed ({resp.status_code})", 502, detail)
        if not resp.content:
            return {}
        return resp.json()

    async def list_carrier_accounts(self) -> List[dict]:
        data = await self._request("GET", "/carrier_accounts/", params={"results": 100})
        seen = {}
        for acc in data.get("results", []):
            code = acc.get("carrier", "")
            seen.setdefault(code, {"carrier": code, "active": bool(acc.get("active")), "test": bool(acc.get("test")), "accounts": 0})
            seen[code]["accounts"] += 1
            seen[code]["active"] = seen[code]["active"] or bool(acc.get("active"))
        return sorted(seen.values(), key=lambda c: c["carrier"])

    async def create_shipment(self, address_from: dict, address_to: dict, parcel: dict, metadata: str = "") -> dict:
        payload = {"address_from": address_from, "address_to": address_to, "parcels": [parcel], "async": False}
        if metadata:
            payload["metadata"] = metadata[:100]
        return await self._request("POST", "/shipments/", json=payload)

    async def purchase_label(self, rate_id: str, metadata: str = "", label_file_type: str = "PDF") -> dict:
        return await self._request("POST", "/transactions/", json={"rate": rate_id, "label_file_type": label_file_type, "async": False, "metadata": metadata[:100]})

    async def get_transaction(self, transaction_id: str) -> dict:
        return await self._request("GET", f"/transactions/{transaction_id}")

    async def get_rate(self, rate_id: str) -> dict:
        return await self._request("GET", f"/rates/{rate_id}")

    async def register_webhook(self, url: str, event: str = "track_updated") -> dict:
        return await self._request("POST", "/webhooks/", json={"event": event, "url": url, "active": True, "is_test": self.is_test})

    async def list_webhooks(self) -> List[dict]:
        data = await self._request("GET", "/webhooks/")
        return data.get("results", data) if isinstance(data, dict) else data

    async def download(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as e:
            raise ShippoError(f"Could not download label: {e}", 502)


def convert_amount(amount: float, from_code: str, to_code: str, fx_rates: Optional[Dict[str, float]]) -> Optional[float]:
    """Convert via the store's USD-based FX table; None when either currency is unknown."""
    if not from_code or not to_code or from_code == to_code:
        return money(amount)
    rates = fx_rates or {}
    if from_code not in rates or to_code not in rates:
        return None
    return money(float(amount) / float(rates[from_code]) * float(rates[to_code]))


def normalize_rates(shipment: dict, shippo_cfg: dict, store_currency: str = "", fx_rates: Optional[Dict[str, float]] = None) -> List[dict]:
    """Shippo rates → checkout options (same shape as the rate-table options). Prices are converted into the store currency when given."""
    allowed = {c for c in (shippo_cfg.get("allowed_carriers") or [])}
    pct = float(shippo_cfg.get("markup_percent") or 0)
    flat = float(shippo_cfg.get("markup_flat") or 0)
    store_currency = (store_currency or "").upper()
    options = []
    for r in shipment.get("rates", []) or []:
        provider = r.get("provider") or ""
        code = provider_code(provider)
        if allowed and code not in allowed and "other" not in allowed:
            continue
        carrier_amount = money(r.get("amount"))
        carrier_currency = (r.get("currency") or "").upper()
        base = carrier_amount
        currency = carrier_currency
        if store_currency:
            converted = convert_amount(carrier_amount, carrier_currency, store_currency, fx_rates)
            if converted is None:
                logger.warning(f"Shippo rate in {carrier_currency} cannot be converted to {store_currency}; skipping {provider} rate")
                continue
            base, currency = converted, store_currency
        price = money(base * (1 + pct / 100.0) + flat)
        service = r.get("servicelevel") or {}
        days = r.get("estimated_days")
        options.append({
            "method_id": f"shippo:{r.get('object_id')}",
            "carrier": code,
            "carrier_name": provider or CODE_TO_PROVIDER_LABEL.get(code, "Carrier"),
            "service_name": service.get("name") or service.get("token") or "Service",
            "price": price,
            "currency": currency,
            "delivery_days": str(days) if days else (r.get("duration_terms") or ""),
            "source": "shippo",
            "shippo": {
                "rate_id": r.get("object_id"),
                "shipment_id": shipment.get("object_id"),
                "provider": provider,
                "servicelevel_token": service.get("token"),
                "carrier_amount": carrier_amount,
                "carrier_currency": carrier_currency,
                "converted_amount": base,
                "currency": currency,
                "test": bool(r.get("test")),
            },
        })
    options.sort(key=lambda o: (o["price"], o["service_name"]))
    return options


def shipment_messages(shipment: dict) -> List[str]:
    out = []
    for m in shipment.get("messages", []) or []:
        text = (m.get("text") or "").strip()
        if not text or "doesn't support one or more shipment options" in text or "restricted from using this carrier" in text:
            continue
        src = m.get("source") or "Shippo"
        out.append(f"{src}: {text}"[:200])
    return out[:8]


def new_webhook_token() -> str:
    return secrets.token_urlsafe(24)


def ceil_days(value) -> Optional[int]:
    try:
        return int(math.ceil(float(value)))
    except (TypeError, ValueError):
        return None
