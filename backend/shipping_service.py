"""Shipping engine: admin-configured rate table today, per-carrier live-rate providers pluggable later."""
import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CARRIERS: Dict[str, Dict[str, Any]] = {
    "ups": {"name": "UPS", "tracking_url": "https://www.ups.com/track?tracknum={tracking}",
            "credential_fields": ["client_id", "client_secret", "account_number"]},
    "fedex": {"name": "FedEx", "tracking_url": "https://www.fedex.com/fedextrack/?trknbr={tracking}",
              "credential_fields": ["api_key", "secret_key", "account_number"]},
    "purolator": {"name": "Purolator", "tracking_url": "https://www.purolator.com/en/shipping/tracker?pin={tracking}",
                  "credential_fields": ["api_key", "api_password", "account_number"]},
    "canadapost": {"name": "Canada Post", "tracking_url": "https://www.canadapost-postescanada.ca/track-reperage/en#/search?searchFor={tracking}",
                   "credential_fields": ["api_username", "api_password", "customer_number"]},
    "usps": {"name": "USPS", "tracking_url": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking}",
             "credential_fields": ["consumer_key", "consumer_secret"]},
    "other": {"name": "Other", "tracking_url": "", "credential_fields": []},
}

DEFAULT_SHIPPING_SETTINGS: Dict[str, Any] = {
    "ship_from": {"name": "", "company": "", "address1": "", "address2": "", "city": "", "state": "", "postal_code": "", "country": "CA", "phone": ""},
    "weight_unit": "kg",
    "dimension_unit": "cm",
    "carriers": {c: {"enabled": True, "mode": "table", "credentials": {}} for c in CARRIERS if c != "other"},
    "methods": [],
}


class CarrierNotConfigured(Exception):
    pass


def to_kg(weight: float, unit: str) -> float:
    return float(weight or 0) * (0.45359237 if unit == "lb" else 1.0)


def from_kg(weight_kg: float, unit: str) -> float:
    return weight_kg / 0.45359237 if unit == "lb" else weight_kg


def carrier_tracking_url(carrier: str, tracking_number: str) -> str:
    template = CARRIERS.get(carrier or "other", CARRIERS["other"])["tracking_url"]
    return template.format(tracking=tracking_number) if template and tracking_number else ""


def merge_shipping_settings(stored: Optional[dict]) -> dict:
    merged = {**DEFAULT_SHIPPING_SETTINGS, **(stored or {})}
    merged["ship_from"] = {**DEFAULT_SHIPPING_SETTINGS["ship_from"], **(merged.get("ship_from") or {})}
    carriers = {}
    for code, defaults in DEFAULT_SHIPPING_SETTINGS["carriers"].items():
        carriers[code] = {**defaults, **((merged.get("carriers") or {}).get(code) or {})}
        carriers[code]["credentials"] = carriers[code].get("credentials") or {}
    merged["carriers"] = carriers
    merged["methods"] = merged.get("methods") or []
    return merged


def summarize_package(items: List[dict], settings: dict) -> dict:
    """items: [{item: physical_item_doc, quantity: int}] -> total weight (in settings unit) and value"""
    unit = settings.get("weight_unit", "kg")
    total_kg = 0.0
    subtotal = 0.0
    count = 0
    for entry in items:
        item = entry["item"]
        qty = max(1, int(entry.get("quantity", 1)))
        total_kg += to_kg(item.get("weight", 0), item.get("weight_unit", "kg")) * qty
        subtotal += float(item.get("price", 0)) * qty
        count += qty
    return {"weight": round(from_kg(total_kg, unit), 3), "weight_unit": unit, "weight_kg": round(total_kg, 3), "subtotal": round(subtotal, 2), "item_count": count}


def method_serves_destination(method: dict, dest_country: str, origin_country: str) -> bool:
    zone = method.get("zone", "worldwide")
    dest = (dest_country or "").upper()
    origin = (origin_country or "").upper()
    if zone == "domestic":
        return bool(dest) and dest == origin
    if zone == "international":
        return bool(dest) and dest != origin
    if zone == "countries":
        return dest in [c.upper() for c in method.get("countries", [])]
    return True


def table_rate(method: dict, weight: float, subtotal: float) -> Optional[float]:
    """Price for a method from the admin table, or None when it cannot ship this package."""
    max_weight = float(method.get("max_weight") or 0)
    if max_weight and weight > max_weight:
        return None
    free_over = float(method.get("free_shipping_over") or 0)
    if free_over and subtotal >= free_over:
        return 0.0
    pricing = method.get("pricing_type", "flat")
    if pricing == "per_weight":
        base = float(method.get("base_rate") or 0)
        per_unit = float(method.get("rate_per_unit") or 0)
        return round(base + per_unit * math.ceil(max(weight, 0)), 2)
    if pricing == "brackets":
        brackets = sorted(method.get("brackets") or [], key=lambda b: float(b.get("max_weight") or 0))
        for bracket in brackets:
            if weight <= float(bracket.get("max_weight") or 0):
                return round(float(bracket.get("price") or 0), 2)
        return None
    return round(float(method.get("base_rate") or 0), 2)


class LiveRateProvider:
    """Base for carrier APIs. Subclasses are wired in when the admin adds credentials."""
    carrier = "other"

    def __init__(self, credentials: dict):
        self.credentials = credentials or {}

    def is_configured(self) -> bool:
        fields = CARRIERS[self.carrier]["credential_fields"]
        return all(self.credentials.get(f) for f in fields)

    async def get_rates(self, ship_from: dict, ship_to: dict, package: dict) -> List[dict]:
        raise CarrierNotConfigured(f"Live rating for {CARRIERS[self.carrier]['name']} is not wired yet")


class UPSRateProvider(LiveRateProvider):
    carrier = "ups"


class FedExRateProvider(LiveRateProvider):
    carrier = "fedex"


class PurolatorRateProvider(LiveRateProvider):
    carrier = "purolator"


class CanadaPostRateProvider(LiveRateProvider):
    carrier = "canadapost"


class USPSRateProvider(LiveRateProvider):
    carrier = "usps"


LIVE_PROVIDERS = {p.carrier: p for p in (UPSRateProvider, FedExRateProvider, PurolatorRateProvider, CanadaPostRateProvider, USPSRateProvider)}


async def get_shipping_rates(settings: dict, items: List[dict], ship_to: dict) -> Dict[str, Any]:
    """Return every available shipping option for the package, cheapest first."""
    settings = merge_shipping_settings(settings)
    package = summarize_package(items, settings)
    origin_country = (settings.get("ship_from") or {}).get("country", "")
    dest_country = (ship_to or {}).get("country", "")
    options: List[dict] = []
    live_done: set = set()

    for method in settings["methods"]:
        if not method.get("enabled", True):
            continue
        carrier = method.get("carrier", "other")
        carrier_cfg = settings["carriers"].get(carrier, {"enabled": True, "mode": "table"})
        if not carrier_cfg.get("enabled", True):
            continue
        if not method_serves_destination(method, dest_country, origin_country):
            continue

        if carrier_cfg.get("mode") == "api" and carrier in LIVE_PROVIDERS and carrier not in live_done:
            live_done.add(carrier)
            provider = LIVE_PROVIDERS[carrier](carrier_cfg.get("credentials"))
            if provider.is_configured():
                try:
                    for rate in await provider.get_rates(settings["ship_from"], ship_to, package):
                        options.append({**rate, "carrier": carrier, "carrier_name": CARRIERS[carrier]["name"], "source": "api"})
                    continue
                except CarrierNotConfigured as e:
                    logger.info(f"{e}; falling back to rate table")
                except Exception as e:
                    logger.error(f"Live rating failed for {carrier}: {e}; falling back to rate table")

        price = table_rate(method, package["weight"], package["subtotal"])
        if price is None:
            continue
        options.append({
            "method_id": method.get("id"),
            "carrier": carrier,
            "carrier_name": CARRIERS.get(carrier, CARRIERS["other"])["name"],
            "service_name": method.get("service_name") or CARRIERS.get(carrier, CARRIERS["other"])["name"],
            "price": price,
            "delivery_days": method.get("delivery_days", ""),
            "source": "table",
        })

    options.sort(key=lambda o: (o["price"], o["service_name"]))
    return {"package": package, "options": options}
