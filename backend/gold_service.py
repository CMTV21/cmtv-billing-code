"""
Gold Panel Integration Service
Reseller API at https://{panel}/api/api.php?action=...&api_key=KEY (GET, JSON).
Only M3U devices are provisioned. Subscription length `sub` is 1/3/6/12 months.
Packages are Gold "bouquets" (id + name) with no built-in duration, so each
sellable package is exposed as "{bouquet_id}:{sub}" (bouquet × term).
No list-users or delete endpoints exist: users can only be refreshed one by one
via device_info, and "delete" maps to disable.
"""
import logging
import re
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

VALID_TERMS = (1, 3, 6, 12)
_PACKAGE_CACHE: Dict[str, tuple] = {}


class GoldError(Exception):
    def __init__(self, message: str, code: str = "api_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class GoldPanelService:
    def __init__(self, panel_url: str, api_key: str, name: str = "", streaming_url: str = "", ssl_verify: bool = True):
        url = panel_url.strip().rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"
        url = re.sub(r"/api(/api\.php)?$", "", url)
        self.origin = url
        self.api_url = f"{url}/api/api.php"
        self.api_key = api_key.strip()
        self.name = name
        self.streaming_url = streaming_url.strip().rstrip("/") if streaming_url else ""
        self.ssl_verify = ssl_verify

    # ---- transport ----

    async def _call(self, action: str, **params) -> dict:
        query = {"action": action, "api_key": self.api_key, **{k: v for k, v in params.items() if v not in (None, "")}}
        logger.info(f"Gold API {action} {[k for k in params]}")
        try:
            async with httpx.AsyncClient(verify=self.ssl_verify, timeout=30.0) as client:
                resp = await client.get(self.api_url, params=query)
        except httpx.RequestError as e:
            raise GoldError(f"Cannot reach the panel: {e}", "connection_error")
        if resp.status_code >= 400:
            raise GoldError(f"HTTP {resp.status_code}: {resp.text[:200]}", f"http_{resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise GoldError(f"Non-JSON response: {resp.text[:200]}", "bad_response")
        if isinstance(body, list):
            if action == "bouquet":
                return {"status": "true", "items": body}
            body = body[0] if body else {}
        if not isinstance(body, dict):
            raise GoldError("Unexpected response shape", "bad_response")
        if str(body.get("status", "")).lower() in ("error", "false"):
            msg = body.get("result") or body.get("message") or "Request failed"
            code = "invalid_key" if "api key" in str(msg).lower() else ("not_found" if "not found" in str(msg).lower() else "api_error")
            raise GoldError(str(msg), code)
        return body

    # ---- helpers ----

    @staticmethod
    def parse_package_id(value) -> Tuple[Optional[int], Optional[int]]:
        """'60094:12' → (60094, 12); 60094 → (60094, None)."""
        if value in (None, ""):
            return None, None
        s = str(value)
        if ":" in s:
            pack, sub = s.split(":", 1)
            try:
                return int(pack), int(sub)
            except ValueError:
                return None, None
        try:
            return int(s), None
        except ValueError:
            return None, None

    @staticmethod
    def normalize_term(months) -> Optional[int]:
        try:
            m = int(months)
        except (TypeError, ValueError):
            return None
        return m if m in VALID_TERMS else None

    @staticmethod
    def parse_expire(val) -> Optional[datetime]:
        if not val:
            return None
        s = str(val).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:19], fmt)
                return dt if fmt != "%Y-%m-%d" else dt.replace(hour=23, minute=59, second=59)
            except ValueError:
                continue
        if s.isdigit():
            try:
                return datetime.utcfromtimestamp(int(s))
            except (ValueError, OSError, OverflowError):
                return None
        return None

    @staticmethod
    def parse_m3u_url(url: str) -> dict:
        """http://host/get.php?username=U&password=P&... → credentials + streaming host."""
        if not url:
            return {}
        try:
            p = urlparse(url)
            q = parse_qs(p.query)
            host = f"{p.scheme or 'http'}://{p.netloc}" if p.netloc else ""
            return {"username": (q.get("username") or [""])[0], "password": (q.get("password") or [""])[0], "streaming_url": host}
        except Exception:
            return {}

    @staticmethod
    def device_status(info: dict) -> str:
        enabled = str(info.get("enabled", "1"))
        if enabled in ("0", "false", "False"):
            return "suspended"
        exp = GoldPanelService.parse_expire(info.get("expire"))
        if exp and exp < datetime.utcnow():
            return "expired"
        return "active"

    # ---- core API ----

    async def test_connection(self) -> Dict[str, Any]:
        try:
            data = await self._call("reseller")
        except GoldError as e:
            return {"success": False, "error": e.message, "code": e.code}
        credits = data.get("credits")
        try:
            credits = float(credits) if credits is not None else None
        except (TypeError, ValueError):
            credits = None
        return {"success": True, "message": f"Connected as \"{data.get('username', '?')}\"",
                "data": {"username": data.get("username", ""), "credits": credits, "enabled": data.get("enabled")}}

    async def get_balance(self) -> Optional[float]:
        try:
            data = await self._call("reseller")
            return float(data.get("credits", 0))
        except (GoldError, TypeError, ValueError):
            return None

    async def get_bouquets(self) -> Dict[str, Any]:
        cache_key = f"{self.origin}|{self.api_key[:10]}"
        cached = _PACKAGE_CACHE.get(cache_key)
        if cached and (datetime.utcnow() - cached[0]).total_seconds() < 120:
            return cached[1]
        try:
            data = await self._call("bouquet")
        except GoldError as e:
            return {"success": False, "error": e.message, "code": e.code, "bouquets": []}
        bouquets = [{"id": int(b["id"]), "name": b.get("name", f"Package {b['id']}")} for b in data.get("items", []) if str(b.get("id", "")).isdigit()]
        result = {"success": True, "bouquets": bouquets}
        _PACKAGE_CACHE[cache_key] = (datetime.utcnow(), result)
        return result

    async def get_packages(self) -> Dict[str, Any]:
        """Sellable packages = bouquet × term, plus plain terms for renewals."""
        res = await self.get_bouquets()
        if not res.get("success"):
            return {**res, "packages": [], "terms": []}
        packages: List[dict] = []
        for b in res["bouquets"]:
            for sub in VALID_TERMS:
                packages.append({
                    "id": f"{b['id']}:{sub}", "pack_id": b["id"], "sub": sub,
                    "name": f"{b['name']} — {sub} month{'s' if sub > 1 else ''}",
                    "duration": sub, "duration_unit": "months", "max_connections": 1,
                    "bouquets": [], "is_trial": False, "kind": "official",
                })
        terms = [{"id": sub, "name": f"{sub} month{'s' if sub > 1 else ''}", "duration": sub, "duration_unit": "months", "max_connections": 1} for sub in VALID_TERMS]
        return {"success": True, "packages": packages, "bouquets": res["bouquets"], "terms": terms}

    async def create_m3u(self, pack_id: int, sub: int, notes: str = "", country: str = "") -> Dict[str, Any]:
        term = self.normalize_term(sub)
        if not term:
            return {"success": False, "error": f"Subscription length must be one of {VALID_TERMS} months (got {sub})", "code": "bad_term"}
        try:
            data = await self._call("new", type="m3u", sub=term, pack=int(pack_id), notes=(notes or "")[:200], country=country or None)
        except GoldError as e:
            return {"success": False, "error": e.message, "code": e.code}
        creds = self.parse_m3u_url(data.get("url", ""))
        if not creds.get("username"):
            return {"success": False, "error": f"Panel did not return M3U credentials: {data}", "code": "bad_response"}
        return {"success": True, "user_id": str(data.get("user_id", "")), "url": data.get("url", ""),
                "username": creds["username"], "password": creds["password"],
                "streaming_url": self.streaming_url or creds.get("streaming_url", ""),
                "message": data.get("message", ""), "term": term}

    async def renew_m3u(self, username: str, password: str, sub: int) -> Dict[str, Any]:
        term = self.normalize_term(sub)
        if not term:
            return {"success": False, "error": f"Subscription length must be one of {VALID_TERMS} months (got {sub})", "code": "bad_term"}
        try:
            data = await self._call("renew", type="m3u", username=username, password=password, sub=term)
        except GoldError as e:
            return {"success": False, "error": e.message, "code": e.code}
        info = await self.device_info(username, password)
        return {"success": True, "message": data.get("message") or data.get("messasge", ""), "term": term,
                "new_expiry": info.get("expiry") if info.get("success") else None}

    async def device_info(self, username: str, password: str) -> Dict[str, Any]:
        try:
            data = await self._call("device_info", username=username, password=password)
        except GoldError as e:
            return {"success": False, "error": e.message, "code": e.code}
        return {"success": True, "info": data, "user_id": str(data.get("user_id", "")),
                "username": data.get("username", username), "password": data.get("password", password),
                "expiry": self.parse_expire(data.get("expire")), "status": self.device_status(data),
                "enabled": str(data.get("enabled", "1")) not in ("0", "false", "False"),
                "url": data.get("url", ""), "country": data.get("country", ""), "note": data.get("note", "")}

    async def set_status(self, user_id: str, enable: bool) -> Dict[str, Any]:
        if not user_id:
            return {"success": False, "error": "Gold user_id is unknown for this device", "code": "no_user_id"}
        try:
            data = await self._call("device_status", status="enable" if enable else "disable", id=user_id)
        except GoldError as e:
            return {"success": False, "error": e.message, "code": e.code}
        return {"success": True, "message": data.get("message", "")}

    async def resolve_user_id(self, username: str, password: str, known: str = "") -> str:
        if known:
            return str(known)
        info = await self.device_info(username, password)
        return info.get("user_id", "") if info.get("success") else ""

    @staticmethod
    def fallback_expiry(term: int, start: Optional[datetime] = None) -> datetime:
        return (start or datetime.utcnow()) + timedelta(days=30 * int(term))


def get_gold_service(panel_settings: dict) -> Optional[GoldPanelService]:
    if not panel_settings:
        return None
    panel_url = panel_settings.get("panel_url", "")
    api_key = panel_settings.get("api_key", "") or panel_settings.get("api_token", "")
    if not panel_url or not api_key:
        logger.warning("Gold Panel: missing panel_url or api_key")
        return None
    return GoldPanelService(panel_url=panel_url, api_key=api_key, name=panel_settings.get("name", ""),
                            streaming_url=panel_settings.get("streaming_url", ""), ssl_verify=panel_settings.get("ssl_verify", True))
