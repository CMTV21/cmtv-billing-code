"""
Aether Panel Integration Service
Reseller/Management API at https://{panel}/api/v1 — Bearer token auth.
The token kind (admin | reseller) is detected from GET /api/v1/me and every
call rides /api/v1/{kind}/... (same contract as the official WHMCS module).
"""
import logging
import re
import httpx
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import quote

logger = logging.getLogger(__name__)

_PACKAGE_CACHE: Dict[str, tuple] = {}


class AetherError(Exception):
    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class AetherService:
    """Aether panel API client"""

    CAP_USERNAME = "lines.create_custom_username"
    CAP_PASSWORD = "lines.create_custom_password"

    def __init__(self, panel_url: str, api_token: str, name: str = "", streaming_url: str = "", ssl_verify: bool = True):
        url = panel_url.strip().rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"
        url = re.sub(r"/api/v1(/.*)?$", "", url)
        self.origin = url
        self.api_token = api_token.strip()
        self.name = name
        self.streaming_url = streaming_url.strip().rstrip("/") if streaming_url else ""
        self.ssl_verify = ssl_verify
        self._me: Optional[dict] = None

    # ---- transport ----

    async def _request(self, method: str, path: str, json_data: dict = None, params: dict = None,
                       idem_key: str = None) -> Any:
        headers = {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}
        if json_data is not None:
            headers["Content-Type"] = "application/json"
        if idem_key:
            headers["Idempotency-Key"] = idem_key[:200]
        url = f"{self.origin}{path}"
        logger.info(f"Aether API {method} {path}")
        try:
            async with httpx.AsyncClient(verify=self.ssl_verify, timeout=30.0) as client:
                resp = await client.request(method, url, headers=headers, json=json_data, params=params)
        except httpx.RequestError as e:
            raise AetherError("connection_error", f"Cannot reach the panel: {e}")

        if 200 <= resp.status_code < 300:
            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return {}
        try:
            body = resp.json()
        except ValueError:
            body = {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = err.get("code", f"http_{resp.status_code}")
        message = err.get("message", resp.text[:300] or f"HTTP {resp.status_code}")
        logger.warning(f"Aether API error {resp.status_code} [{code}] {message}")
        raise AetherError(code, message, resp.status_code)

    async def me(self) -> dict:
        if self._me is None:
            self._me = await self._request("GET", "/api/v1/me")
        return self._me

    async def _base(self) -> str:
        me = await self.me()
        kind = me.get("kind", "reseller")
        if kind not in ("admin", "reseller"):
            raise AetherError("unknown_kind", f"Unrecognized token kind: {kind}")
        return f"/api/v1/{kind}"

    def _has_cap(self, cap: str) -> bool:
        return bool(self._me) and cap in (self._me.get("capabilities") or [])

    @staticmethod
    def ref(username: str) -> str:
        return f"username:{quote(str(username), safe='')}"

    # ---- helpers ----

    @staticmethod
    def parse_exp(val) -> Optional[datetime]:
        """RFC 3339 → naive UTC datetime"""
        if not val:
            return None
        if isinstance(val, (int, float)):
            try:
                return datetime.utcfromtimestamp(int(val))
            except (ValueError, OSError, OverflowError):
                return None
        s = str(val).strip()
        if s.isdigit():
            return AetherService.parse_exp(int(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", s)
            if not m:
                return None
            try:
                return datetime.strptime(m.group(1).replace("T", " "), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        if dt.tzinfo is not None:
            dt = (dt - dt.utcoffset()).replace(tzinfo=None)
        return dt.replace(microsecond=0)

    @staticmethod
    def line_status(line: dict) -> str:
        if line.get("banned"):
            return "banned"
        if not line.get("enabled", True):
            return "suspended"
        exp = AetherService.parse_exp(line.get("exp_date"))
        if not line.get("unlimited") and exp and exp < datetime.utcnow():
            return "expired"
        return "active"

    @staticmethod
    def normalize_package(p: dict) -> dict:
        kind = p.get("kind", "official")
        return {
            "id": p.get("id"),
            "name": p.get("name", f"Package {p.get('id')}"),
            "kind": kind,
            "duration": p.get("duration_value", 1),
            "duration_unit": p.get("duration_unit", "months"),
            "max_connections": p.get("max_connections", 1),
            "price": p.get("your_price") or p.get("credit_cost") or "0",
            "is_trial": kind == "trial",
            "bouquets": [],
        }

    # ---- core API ----

    async def test_connection(self) -> Dict[str, Any]:
        try:
            me = await self.me()
        except AetherError as e:
            return {"success": False, "error": e.message}
        needed = {
            "lines:read": "reading lines & sync",
            "lines:create": "provisioning",
            "lines:renew": "renew / extend",
            "lines:update": "suspend / unsuspend",
            "lines:credentials": "reading line passwords",
            "packages:read": "package list",
        }
        scopes = me.get("scopes") or []
        missing = [f"{s} ({why})" for s, why in needed.items() if s not in scopes]
        subject = (me.get("subject") or {}).get("username", "")
        msg = f"Connected as {me.get('kind', '?')} \"{subject}\""
        if missing:
            msg += f". Token lacks: {', '.join(missing)}"
        balance = None
        if "credits:read" in scopes:
            try:
                bal = await self._request("GET", f"{await self._base()}/credits/balance")
                balance = bal.get("balance")
            except AetherError:
                pass
        return {"success": True, "message": msg, "data": {**me, "balance": balance}, "missing_scopes": missing}

    async def get_packages(self) -> Dict[str, Any]:
        cache_key = f"{self.origin}|{self.api_token[:16]}"
        cached = _PACKAGE_CACHE.get(cache_key)
        if cached and (datetime.utcnow() - cached[0]).total_seconds() < 60:
            return cached[1]
        try:
            data = await self._request("GET", f"{await self._base()}/packages")
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code, "packages": [], "trial_packages": [], "extension_packages": [], "all_packages": []}
        rows = data.get("items") or data.get("packages") or (data if isinstance(data, list) else [])
        pk = [self.normalize_package(p) for p in rows]
        result = {
            "success": True,
            "packages": [p for p in pk if p["kind"] == "official"],
            "trial_packages": [p for p in pk if p["kind"] == "trial"],
            "extension_packages": [p for p in pk if p["kind"] == "extension"],
            "all_packages": pk,
        }
        _PACKAGE_CACHE[cache_key] = (datetime.utcnow(), result)
        return result

    async def get_package_bouquets(self, package_id: int) -> Dict[str, Any]:
        try:
            data = await self._request("GET", f"{await self._base()}/packages/{int(package_id)}/bouquets")
        except AetherError as e:
            return {"success": False, "error": e.message, "bouquets": []}
        return {"success": True, "bouquets": data.get("bouquets", [])}

    async def get_all_bouquets(self) -> Dict[str, Any]:
        """Union of bouquets across every sellable package (Aether has no global bouquet list)."""
        pk = await self.get_packages()
        if not pk.get("success"):
            return {"success": False, "error": pk.get("error"), "bouquets": []}
        seen: Dict[int, dict] = {}
        for p in pk["all_packages"]:
            res = await self.get_package_bouquets(p["id"])
            for b in res.get("bouquets", []):
                bid = int(b.get("id", 0))
                if bid and bid not in seen:
                    seen[bid] = {
                        "id": bid,
                        "name": b.get("name", f"Bouquet {bid}"),
                        "stream_count": b.get("stream_count", 0),
                        "movie_count": b.get("movie_count", 0),
                        "series_count": b.get("series_count", 0),
                    }
        return {"success": True, "bouquets": sorted(seen.values(), key=lambda x: x["id"])}

    async def list_lines(self, page: int = 1, per_page: int = 500, reveal: bool = True, search: str = "") -> Dict[str, Any]:
        params = {"page": page, "per_page": per_page, "sort": "id", "dir": "asc"}
        if reveal:
            params["reveal"] = "credentials"
        if search:
            params["search"] = search
        try:
            data = await self._request("GET", f"{await self._base()}/lines", params=params)
        except AetherError as e:
            if e.code == "insufficient_scope" and reveal:
                return await self.list_lines(page, per_page, reveal=False, search=search)
            return {"success": False, "error": e.message, "lines": []}
        return {
            "success": True,
            "lines": data.get("items", []),
            "total": data.get("total", 0),
            "page": data.get("page", page),
            "per_page": data.get("per_page", per_page),
        }

    async def get_all_lines(self) -> Dict[str, Any]:
        lines: List[dict] = []
        page = 1
        while True:
            res = await self.list_lines(page=page)
            if not res.get("success"):
                if lines:
                    break
                return res
            batch = res.get("lines", [])
            lines.extend(batch)
            if not batch or len(lines) >= res.get("total", 0) or len(batch) < res.get("per_page", 500):
                break
            page += 1
        return {"success": True, "lines": lines, "total": len(lines)}

    async def get_line(self, username: str) -> Dict[str, Any]:
        try:
            data = await self._request("GET", f"{await self._base()}/lines/{self.ref(username)}")
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code}
        return {"success": True, "line": data}

    async def find_line(self, username: str, password: str = "") -> Dict[str, Any]:
        res = await self.get_line(username)
        if not res.get("success"):
            return res
        line = res["line"]
        if password and line.get("password") and line["password"] != password:
            return {"success": False, "error": "Password does not match", "code": "bad_password"}
        return {"success": True, "line": line, "line_id": str(line.get("id", ""))}

    async def create_line(self, package_id: int, username: str = None, password: str = None,
                          bouquet_ids: list = None, notes: str = "", idem_key: str = None) -> Dict[str, Any]:
        """Create a line. Only sends credentials the token is allowed to choose; falls back to
        panel-generated ones on capability_denied. Same idempotency key is safe to retry."""
        try:
            await self.me()
            base = await self._base()
        except AetherError as e:
            return {"success": False, "error": e.message}

        body: Dict[str, Any] = {"package_id": int(package_id)}
        if username and self._has_cap(self.CAP_USERNAME):
            body["username"] = username
        if password and self._has_cap(self.CAP_PASSWORD):
            body["password"] = password
        if bouquet_ids:
            body["bouquet_ids"] = [int(b) for b in bouquet_ids]
        if notes:
            key = "admin_notes" if base.endswith("/admin") else "reseller_notes"
            body[key] = notes[:500]
        if base.endswith("/admin"):
            body["uncharged"] = False

        for attempt in range(3):
            try:
                data = await self._request("POST", f"{base}/lines", json_data=body, idem_key=idem_key)
                return {
                    "success": True,
                    "line_id": str(data.get("line_id") or data.get("id", "")),
                    "username": data.get("username", body.get("username", "")),
                    "password": data.get("password", body.get("password", "")),
                    "exp_date": data.get("exp_date"),
                    "charged": data.get("charged"),
                }
            except AetherError as e:
                if e.code == "capability_denied" and ("username" in body or "password" in body):
                    logger.info("Aether: credential choice denied, retrying with panel-generated credentials")
                    body.pop("username", None)
                    body.pop("password", None)
                    continue
                if e.code == "bouquet_outside_ceiling" and "bouquet_ids" in body:
                    logger.info("Aether: bouquets outside package ceiling, retrying with package defaults")
                    body.pop("bouquet_ids", None)
                    continue
                if e.code == "username_taken" and "username" in body:
                    return {"success": False, "error": e.message, "code": e.code}
                return {"success": False, "error": e.message, "code": e.code}
        return {"success": False, "error": "Line creation failed after retries"}

    async def renew_line(self, username: str, package_id: int, idem_key: str = None, kind: str = "official",
                         sync_bouquets: bool = False) -> Dict[str, Any]:
        """Renew (official package) or extend (extension package) a line."""
        try:
            base = await self._base()
            verb = "extend" if kind == "extension" else "renew"
            body: Dict[str, Any] = {"package_id": int(package_id)}
            if verb == "renew" and sync_bouquets:
                body["bouquet_sync_mode"] = "sync_all"
            if base.endswith("/admin"):
                body["uncharged"] = False
            data = await self._request("POST", f"{base}/lines/{self.ref(username)}/{verb}", json_data=body, idem_key=idem_key)
            return {"success": True, "line_id": str(data.get("line_id", "")), "exp_date": data.get("exp_date"),
                    "new_expiry": self.parse_exp(data.get("exp_date")), "charged": data.get("charged")}
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code}

    async def suspend_line(self, username: str) -> Dict[str, Any]:
        try:
            await self._request("POST", f"{await self._base()}/lines/{self.ref(username)}/suspend")
            return {"success": True}
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code}

    async def unsuspend_line(self, username: str) -> Dict[str, Any]:
        try:
            await self._request("POST", f"{await self._base()}/lines/{self.ref(username)}/unsuspend")
            return {"success": True}
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code}

    async def delete_line(self, username: str) -> Dict[str, Any]:
        try:
            await self._request("DELETE", f"{await self._base()}/lines/{self.ref(username)}")
            return {"success": True}
        except AetherError as e:
            if e.status == 404:
                return {"success": True, "already_gone": True}
            return {"success": False, "error": e.message, "code": e.code}

    async def change_password(self, username: str, new_password: str = None) -> Dict[str, Any]:
        try:
            await self.me()
            body = {"password": new_password} if (new_password and self._has_cap(self.CAP_PASSWORD)) else {"regenerate_password": True}
            data = await self._request("POST", f"{await self._base()}/lines/{self.ref(username)}/credentials", json_data=body)
            return {"success": True, "password": data.get("password", new_password or "")}
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code}

    async def get_credentials(self, username: str) -> Dict[str, Any]:
        try:
            data = await self._request("GET", f"{await self._base()}/lines/{self.ref(username)}/credentials")
            return {"success": True, **data}
        except AetherError as e:
            return {"success": False, "error": e.message, "code": e.code}

    async def resolve_streaming_url(self, username: str = "") -> str:
        """Panel-configured streaming DNS wins; otherwise read host/scheme from a line's credentials."""
        if self.streaming_url:
            return self.streaming_url
        if username:
            creds = await self.get_credentials(username)
            if creds.get("success") and creds.get("host"):
                return f"{creds.get('scheme', 'http')}://{creds['host']}"
        return ""

    async def get_balance(self) -> Optional[float]:
        try:
            data = await self._request("GET", f"{await self._base()}/credits/balance")
            return float(data.get("balance", 0))
        except (AetherError, ValueError, TypeError):
            return None

    async def get_dashboard(self) -> Dict[str, Any]:
        try:
            return {"success": True, **(await self._request("GET", f"{await self._base()}/dashboard"))}
        except AetherError as e:
            return {"success": False, "error": e.message}


def get_aether_service(panel_settings: dict) -> Optional[AetherService]:
    """Factory: create AetherService from panel config dict."""
    if not panel_settings:
        return None
    panel_url = panel_settings.get("panel_url", "")
    api_token = panel_settings.get("api_token", "")
    if not panel_url or not api_token:
        logger.warning("Aether: missing panel_url or api_token")
        return None
    return AetherService(
        panel_url=panel_url,
        api_token=api_token,
        name=panel_settings.get("name", ""),
        streaming_url=panel_settings.get("streaming_url", ""),
        ssl_verify=panel_settings.get("ssl_verify", True),
    )
