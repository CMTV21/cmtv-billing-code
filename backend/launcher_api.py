"""Launcher API — endpoints for TV/STB launcher apps.
Authenticated via X-Launcher-Key header (operator API key).
"""
import secrets
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Header, Depends, BackgroundTasks
from bson import ObjectId
from xtreamui_service import xtream_api_call as _xtream_api_call

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/launcher", tags=["launcher"])

# These get set by init_launcher_api()
db = None
_get_settings = None
_provision_order_services = None

def init_launcher_api(database, get_settings_fn, provision_fn):
    global db, _get_settings, _provision_order_services
    db = database
    _get_settings = get_settings_fn
    _provision_order_services = provision_fn


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _parse_exp_date(exp_val) -> Optional[datetime]:
    """Parse expiry from various formats (epoch int, ISO string, datetime string). Returns None for unlimited (0/null)."""
    if not exp_val:
        return None
    if isinstance(exp_val, (int, float)):
        if exp_val <= 0:
            return None  # 0 = unlimited
        return datetime.utcfromtimestamp(exp_val)
    if isinstance(exp_val, str):
        s = exp_val.strip()
        if not s or s == "0" or s.lower() in ("null", "none", "unlimited", "never"):
            return None
        # Try epoch string
        try:
            epoch = int(s)
            if epoch <= 0:
                return None
            return datetime.utcfromtimestamp(epoch)
        except ValueError:
            pass
        # Try datetime formats
        for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(s.split(".")[0].replace("Z", ""), fmt)
            except ValueError:
                continue
    return None


async def _fetch_live_line_status(service: dict, settings: dict) -> dict:
    """Fetch live user_info from the panel for a service. Returns dict with connections, expires_at, days_remaining, status."""
    import httpx
    
    username = service.get("xtream_username") or service.get("vpn_username", "")
    password = service.get("xtream_password") or service.get("vpn_password", "")
    panel_type = service.get("panel_type", "xtream")
    panel_index = service.get("panel_index", 0)
    if isinstance(panel_index, str):
        try: panel_index = int(panel_index)
        except (ValueError, TypeError): panel_index = 0
    
    result = {
        "connections": service.get("max_connections", 1),
        "expires_at": None,
        "days_remaining": None,  # null = unlimited
        "status": service.get("status", "unknown"),
        "live": False,
    }
    
    if panel_type == "xtream":
        panels = settings.get("xtream", {}).get("panels", [])
        if panel_index < len(panels):
            panel = panels[panel_index]
            
            # API-key panel: use get_line_info or lookup_line
            if panel.get("api_key"):
                try:
                    # Try lookup_line first (by username)
                    data = await _xtream_api_call(panel, "lookup_line", {"username": username})
                    line = data.get("data", data) if isinstance(data, dict) else data
                    if isinstance(line, dict) and line.get("username"):
                        exp = _parse_exp_date(line.get("exp_date") or line.get("expiry"))
                        try: conn = int(line.get("max_connections", 1))
                        except (ValueError, TypeError): conn = 1
                        
                        result["connections"] = conn
                        result["expires_at"] = exp.isoformat() if exp else None
                        result["days_remaining"] = max(0, (exp - datetime.utcnow()).days) if exp else None
                        result["live"] = True
                        
                        raw_status = str(line.get("status", "")).lower()
                        if raw_status in ("disabled", "banned", "suspended"):
                            result["status"] = "suspended"
                        elif exp and exp < datetime.utcnow():
                            result["status"] = "expired"
                        else:
                            result["status"] = "active"
                        return result
                except Exception as e:
                    logger.debug(f"Live lookup_line failed for {username}: {e}")
            
            # Standard panel: use player_api.php
            streaming_url = panel.get("streaming_url") or panel.get("panel_url", "")
            if streaming_url and username and password:
                try:
                    clean_url = streaming_url.rstrip("/")
                    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                        resp = await client.get(f"{clean_url}/player_api.php?username={username}&password={password}")
                        if resp.status_code == 200:
                            pdata = resp.json()
                            ui = pdata.get("user_info", {})
                            if ui.get("username"):
                                exp = _parse_exp_date(ui.get("exp_date"))
                                try: conn = int(ui.get("max_connections", 1))
                                except (ValueError, TypeError): conn = 1
                                
                                result["connections"] = conn
                                result["expires_at"] = exp.isoformat() if exp else None
                                result["days_remaining"] = max(0, (exp - datetime.utcnow()).days) if exp else None
                                result["live"] = True
                                
                                raw_status = str(ui.get("status", "")).lower()
                                if raw_status in ("disabled", "banned"):
                                    result["status"] = "suspended"
                                elif exp and exp < datetime.utcnow():
                                    result["status"] = "expired"
                                else:
                                    result["status"] = "active"
                                return result
                except Exception as e:
                    logger.debug(f"Live player_api check failed for {username}: {e}")
    
    elif panel_type == "aether":
        ae_panels = settings.get("aether", {}).get("panels", [])
        if panel_index < len(ae_panels):
            try:
                from aether_service import get_aether_service, AetherService
                ae = get_aether_service(ae_panels[panel_index])
                if ae and username:
                    res = await ae.get_line(username)
                    if res.get("success"):
                        line = res["line"]
                        exp = None if line.get("unlimited") else AetherService.parse_exp(line.get("exp_date"))
                        result["connections"] = int(line.get("max_connections", 1) or 1)
                        result["expires_at"] = exp.isoformat() if exp else None
                        result["days_remaining"] = max(0, (exp - datetime.utcnow()).days) if exp else None
                        result["live"] = True
                        st = AetherService.line_status(line)
                        result["status"] = "suspended" if st in ("suspended", "banned") else st
                        return result
            except Exception as e:
                logger.debug(f"Live aether check failed for {username}: {e}")

    elif panel_type == "ghostsurf":
        gs_panels = settings.get("ghostsurf", {}).get("panels", [])
        if panel_index < len(gs_panels):
            try:
                from ghostsurf_service import get_ghostsurf_service
                gs = get_ghostsurf_service(settings, panel_index)
                acct_id = service.get("ghostsurf_account_id")
                if gs and acct_id:
                    acct = await gs.get_account(acct_id)
                    exp = _parse_exp_date(acct.get("expires_at"))
                    result["connections"] = acct.get("max_devices", 5)
                    result["expires_at"] = exp.isoformat() if exp else None
                    result["days_remaining"] = max(0, (exp - datetime.utcnow()).days) if exp else None
                    result["live"] = True
                    result["status"] = "active" if acct.get("status") == "active" else acct.get("status", "unknown")
                    if exp and exp < datetime.utcnow():
                        result["status"] = "expired"
                    return result
            except Exception as e:
                logger.debug(f"Live ghostsurf check failed: {e}")
    
    # Fallback to DB values
    exp = service.get("expiry_date")
    if exp:
        if isinstance(exp, str):
            exp = _parse_exp_date(exp)
        if exp:
            result["expires_at"] = exp.isoformat()
            result["days_remaining"] = max(0, (exp - datetime.utcnow()).days)
    
    return result


async def _verify_admin(request: Request):
    """Verify admin JWT from Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin auth required")
    from auth import verify_token
    token = auth_header.split(" ", 1)[1]
    payload = verify_token(token)
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


async def _verify_launcher_key(x_launcher_key: str = Header(None)):
    """Verify the launcher API key from X-Launcher-Key header."""
    if not x_launcher_key:
        raise HTTPException(status_code=401, detail="Missing X-Launcher-Key header")
    
    settings = await _get_settings()
    launcher = settings.get("launcher", {})
    keys = launcher.get("api_keys", [])
    
    for key_entry in keys:
        if _hash_token(x_launcher_key) == key_entry.get("key_hash"):
            if key_entry.get("status") == "revoked":
                raise HTTPException(status_code=403, detail="API key revoked")
            # Update last_used
            await db.settings.update_one(
                {"launcher.api_keys.key_hash": key_entry["key_hash"]},
                {"$set": {"launcher.api_keys.$.last_used": datetime.utcnow()}}
            )
            return key_entry
    
    raise HTTPException(status_code=401, detail="Invalid API key")


# ──────────────────────────────────────────────
# Admin: Manage launcher API keys
# ──────────────────────────────────────────────

@router.post("/admin/keys")
async def create_launcher_key(request: Request):
    """Generate a new launcher API key. Returns plaintext ONCE."""
    await _verify_admin(request)
    
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    label = body.get("label", "Launcher Key")
    
    # Generate key
    plaintext = f"lk_{secrets.token_urlsafe(32)}"
    key_hash = _hash_token(plaintext)
    
    key_entry = {
        "id": secrets.token_hex(8),
        "label": label,
        "key_hash": key_hash,
        "key_prefix": plaintext[:12] + "...",
        "status": "active",
        "created_at": datetime.utcnow(),
        "last_used": None
    }
    
    await db.settings.update_one(
        {},
        {"$push": {"launcher.api_keys": key_entry}},
        upsert=True
    )
    
    return {
        "api_key": plaintext,
        "id": key_entry["id"],
        "label": label,
        "prefix": key_entry["key_prefix"],
        "message": "Store this key securely — it cannot be retrieved again."
    }


@router.get("/admin/keys")
async def list_launcher_keys(request: Request):
    """List all launcher API keys (prefix only, no plaintext)."""
    await _verify_admin(request)
    
    settings = await _get_settings()
    keys = settings.get("launcher", {}).get("api_keys", [])
    return [{"id": k["id"], "label": k.get("label", ""), "prefix": k.get("key_prefix", ""), "status": k.get("status", "active"), "created_at": k.get("created_at"), "last_used": k.get("last_used")} for k in keys]


@router.delete("/admin/keys/{key_id}")
async def revoke_launcher_key(key_id: str, request: Request):
    """Revoke a launcher API key."""
    await _verify_admin(request)
    
    result = await db.settings.update_one(
        {"launcher.api_keys.id": key_id},
        {"$set": {"launcher.api_keys.$.status": "revoked"}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"message": "Key revoked"}


# ──────────────────────────────────────────────
# Launcher: Packages
# ──────────────────────────────────────────────

@router.get("/packages")
async def get_launcher_packages(key: dict = Depends(_verify_launcher_key)):
    """Operator-curated purchasable packages."""
    settings = await _get_settings()
    
    # Get enabled gateways for the launcher to show payment options
    enabled_gateways = []
    gateway_configs = {
        "ghostpay": settings.get("ghostpay", {}),
        "tagadapay": settings.get("tagadapay", {}),
        "stripe": settings.get("stripe", {}),
        "paypal": settings.get("paypal", {}),
        "helcim": settings.get("helcim", {}),
    }
    for gw_name, gw_conf in gateway_configs.items():
        if gw_conf.get("enabled"):
            enabled_gateways.append(gw_name)
    
    default_gateway = settings.get("launcher", {}).get("default_gateway", "")
    
    # Get active products
    products = []
    async for p in db.products.find({"active": True}).sort("display_order", 1):
        # Build price info
        prices = p.get("prices", {})
        if not prices:
            continue
        
        # Use first available price
        first_term = list(prices.keys())[0] if prices else "1"
        price = prices.get(first_term, 0)
        
        duration_days = int(first_term) * 30  # term_months → days
        if p.get("duration") and p.get("duration_unit"):
            d = int(p["duration"])
            u = p["duration_unit"]
            if u in ("months", "month"):
                duration_days = d * 30
            elif u in ("years", "year"):
                duration_days = d * 365
            elif u in ("days", "day"):
                duration_days = d
            elif u in ("hours", "hour"):
                duration_days = max(1, d // 24)
        
        currency = settings.get("currency", "USD")
        if isinstance(currency, dict):
            currency = currency.get("code", "USD")
        
        products.append({
            "id": str(p["_id"]),
            "display_name": p.get("name", ""),
            "description": p.get("description", ""),
            "price": float(price),
            "currency": currency,
            "connections": p.get("max_connections", 1),
            "duration_days": duration_days,
            "term_months": int(first_term),
            "panel_type": p.get("panel_type", "xtream"),
            "is_trial": p.get("is_trial", False),
        })
    
    return {
        "packages": products,
        "gateways": enabled_gateways,
        "default_gateway": default_gateway or (enabled_gateways[0] if enabled_gateways else None),
    }


# ──────────────────────────────────────────────
# Launcher: Account status
# ──────────────────────────────────────────────

@router.get("/account")
async def get_launcher_account(
    device_token: str = Header(None, alias="X-Device-Token"),
    key: dict = Depends(_verify_launcher_key)
):
    """Active line status for a device — fetches LIVE data from the panel."""
    if not device_token:
        raise HTTPException(status_code=401, detail="Missing X-Device-Token header")
    
    token_hash = _hash_token(device_token)
    device = await db.launcher_devices.find_one({"token_hash": token_hash, "status": "active"})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or token revoked")
    
    # Update last_seen
    await db.launcher_devices.update_one(
        {"_id": device["_id"]},
        {"$set": {"last_seen_at": datetime.utcnow()}}
    )
    
    # Get the linked service
    service = None
    if device.get("service_id"):
        service = await db.services.find_one({"_id": ObjectId(device["service_id"])})
    elif device.get("xtream_username"):
        service = await db.services.find_one({
            "$or": [
                {"xtream_username": device["xtream_username"]},
                {"vpn_username": device["xtream_username"]}
            ],
            "status": {"$in": ["active", "expired"]}
        })
    
    if not service:
        return {
            "status": "no_service",
            "device_id": device.get("device_id"),
            "message": "No active service linked to this device"
        }
    
    settings = await _get_settings()
    
    # Fetch LIVE status from the panel
    live = await _fetch_live_line_status(service, settings)
    
    return {
        "status": live["status"],
        "username": service.get("xtream_username") or service.get("vpn_username", ""),
        "password": service.get("xtream_password") or service.get("vpn_password", ""),
        "streaming_url": service.get("streaming_url", ""),
        "ghostapk_code": service.get("ghostapk_code", ""),
        "expires_at": live["expires_at"],
        "days_remaining": live["days_remaining"],
        "package": service.get("product_name", ""),
        "connections": live["connections"],
        "panel_type": service.get("panel_type", "xtream"),
        "device_id": device.get("device_id"),
        "live": live["live"],
    }


# ──────────────────────────────────────────────
# Launcher: Import existing line (adopt)
# ──────────────────────────────────────────────

@router.post("/import")
async def import_existing_line(request: Request, key: dict = Depends(_verify_launcher_key)):
    """Adopt an existing IPTV/VPN line into the launcher by username + password.
    Verifies credentials against the panel, creates a service record + device token.
    
    Body: { "username": "...", "password": "...", "device_id": "uuid" }
    Returns: { "device_token": "...", "status": "active", "expires_at": "...", ... }
    """
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    device_id = (body.get("device_id") or "").strip()
    
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    
    settings = await _get_settings()
    
    # 1. Check if this line already has a device token for this device
    existing_device = await db.launcher_devices.find_one({
        "xtream_username": username, "device_id": device_id, "status": "active"
    })
    if existing_device:
        # Already imported — return fresh status without issuing new token
        service = await db.services.find_one({"xtream_username": username, "status": {"$in": ["active", "expired"]}})
        if not service:
            service = await db.services.find_one({"vpn_username": username, "status": {"$in": ["active", "expired"]}})
        
        expiry = service.get("expiry_date") if service else None
        days_remaining = 0
        if expiry:
            if isinstance(expiry, str):
                expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            days_remaining = max(0, (expiry - datetime.utcnow()).days)
        
        await db.launcher_devices.update_one({"_id": existing_device["_id"]}, {"$set": {"last_seen_at": datetime.utcnow()}})
        
        return {
            "status": "already_imported",
            "device_token_issued": True,
            "service_status": service.get("status", "unknown") if service else "no_service",
            "username": username,
            "expires_at": expiry.isoformat() if expiry else None,
            "days_remaining": days_remaining,
            "package": service.get("product_name", "") if service else "",
            "message": "Line already imported on this device. Use your existing device token."
        }
    
    # 2. Try to verify the line on each panel
    line_data = None
    matched_panel_type = None
    matched_panel_index = None
    matched_panel_name = None
    
    # Try XtreamUI panels (API-key panels use lookup_line, standard panels use get_line_info)
    xtream_panels = settings.get("xtream", {}).get("panels", [])
    for idx, panel in enumerate(xtream_panels):
        try:
            if panel.get("api_key"):
                # API-key panel: use lookup_line
                data = await _xtream_api_call(panel, "lookup_line", {"username": username})
                line = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(line, dict) and line.get("username"):
                    # Verify password if returned
                    if line.get("password") and password and line["password"] != password:
                        continue  # Wrong password, try next panel
                    line_data = line
                    matched_panel_type = "xtream"
                    matched_panel_index = idx
                    matched_panel_name = panel.get("name", f"Panel {idx + 1}")
                    break
            else:
                # Standard panel: try XtreamUI player API for credential check
                import httpx
                panel_url = panel.get("streaming_url") or panel.get("panel_url", "")
                if panel_url:
                    clean_url = panel_url.rstrip("/")
                    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                        resp = await client.get(f"{clean_url}/player_api.php?username={username}&password={password}")
                        if resp.status_code == 200:
                            pdata = resp.json()
                            if pdata.get("user_info") and pdata["user_info"].get("username"):
                                user_info = pdata["user_info"]
                                line_data = {
                                    "username": user_info.get("username", username),
                                    "password": password,
                                    "exp_date": user_info.get("exp_date"),
                                    "max_connections": user_info.get("max_connections", "1"),
                                    "status": user_info.get("status", "Active"),
                                    "id": user_info.get("id") or user_info.get("user_id"),
                                }
                                matched_panel_type = "xtream"
                                matched_panel_index = idx
                                matched_panel_name = panel.get("name", f"Panel {idx + 1}")
                                break
        except Exception as e:
            logger.debug(f"Import check failed on xtream panel {idx}: {e}")
            continue
    
    # Try Aether panels if not found yet
    if not line_data:
        for idx, panel in enumerate(settings.get("aether", {}).get("panels", [])):
            try:
                from aether_service import get_aether_service, AetherService
                ae = get_aether_service(panel)
                if not ae:
                    continue
                res = await ae.find_line(username, password)
                if res.get("success"):
                    line = res["line"]
                    line_data = {
                        "username": line.get("username", username),
                        "password": line.get("password") or password,
                        "exp_date": None if line.get("unlimited") else line.get("exp_date"),
                        "max_connections": line.get("max_connections", 1),
                        "status": AetherService.line_status(line),
                        "id": line.get("id"),
                    }
                    matched_panel_type = "aether"
                    matched_panel_index = idx
                    matched_panel_name = panel.get("name", f"Aether {idx + 1}")
                    break
            except Exception as e:
                logger.debug(f"Import check failed on aether panel {idx}: {e}")
                continue

    # Try GhostSurf panels if not found yet
    if not line_data:
        gs_panels = settings.get("ghostsurf", {}).get("panels", [])
        for idx, panel in enumerate(gs_panels):
            try:
                from ghostsurf_service import get_ghostsurf_service
                gs = get_ghostsurf_service(settings, idx)
                if gs:
                    accounts = await gs.list_accounts()
                    if not isinstance(accounts, list):
                        accounts = accounts.get("accounts", accounts.get("data", []))
                    for acct in accounts:
                        if acct.get("username") == username:
                            creds = await gs.get_credentials(str(acct.get("id", "")))
                            if password and creds.get("password") and creds["password"] != password:
                                continue
                            line_data = {
                                "username": acct.get("username"),
                                "password": creds.get("password", ""),
                                "exp_date": acct.get("expires_at"),
                                "id": acct.get("id"),
                                "max_connections": acct.get("max_devices", 5),
                                "status": acct.get("status", "active"),
                            }
                            matched_panel_type = "ghostsurf"
                            matched_panel_index = idx
                            matched_panel_name = panel.get("name", f"GhostSurf {idx + 1}")
                            break
                if line_data:
                    break
            except Exception as e:
                logger.debug(f"Import check failed on ghostsurf panel {idx}: {e}")
                continue
    
    if not line_data:
        raise HTTPException(status_code=404, detail="Line not found on any configured panel. Check username and password.")
    
    # 3. Parse line data using shared helper
    expiry_date = _parse_exp_date(line_data.get("exp_date") or line_data.get("expiry") or line_data.get("expires_at"))
    
    line_status = "active"
    raw_status = str(line_data.get("status", "")).lower()
    if raw_status in ("disabled", "banned", "suspended"):
        line_status = "suspended"
    elif expiry_date and expiry_date < datetime.utcnow():
        line_status = "expired"
    
    days_remaining = None  # null = unlimited
    if expiry_date:
        days_remaining = max(0, (expiry_date - datetime.utcnow()).days)
    
    max_conn = 1
    try:
        max_conn = int(line_data.get("max_connections", 1))
    except (ValueError, TypeError):
        max_conn = 1
    
    # 4. Create or find launcher customer
    customer = await db.users.find_one({"launcher_device_id": device_id})
    if not customer:
        result = await db.users.insert_one({
            "email": f"launcher_{device_id[:8]}@device.local",
            "name": f"Launcher {device_id[:8]}",
            "password": "",
            "role": "user",
            "email_verified": True,
            "credit_balance": 0.0,
            "launcher_device_id": device_id,
            "created_via": "launcher_import",
            "created_at": datetime.utcnow()
        })
        customer_id = str(result.inserted_id)
    else:
        customer_id = str(customer["_id"])
    
    # 5. Create or update service record
    existing_service = await db.services.find_one({
        "xtream_username" if matched_panel_type != "ghostsurf" else "vpn_username": username,
        "panel_type": matched_panel_type,
        "panel_index": matched_panel_index,
    })
    
    streaming_url = ""
    if matched_panel_type == "xtream":
        panel = xtream_panels[matched_panel_index]
        streaming_url = panel.get("streaming_url", panel.get("panel_url", ""))
    elif matched_panel_type == "aether":
        try:
            from aether_service import get_aether_service
            ae = get_aether_service(settings["aether"]["panels"][matched_panel_index])
            streaming_url = await ae.resolve_streaming_url(username) if ae else ""
        except Exception:
            streaming_url = ""
    
    if existing_service:
        service_id = str(existing_service["_id"])
        await db.services.update_one({"_id": existing_service["_id"]}, {"$set": {
            "user_id": customer_id,
            "status": line_status,
            "expiry_date": expiry_date,
            "max_connections": max_conn,
            "last_synced": datetime.utcnow(),
        }})
    else:
        svc_doc = {
            "user_id": customer_id,
            "product_name": f"Imported Line ({matched_panel_name})",
            "account_type": "subscriber",
            "panel_type": matched_panel_type,
            "panel_index": matched_panel_index,
            "panel_name": matched_panel_name,
            "status": line_status,
            "expiry_date": expiry_date,
            "max_connections": max_conn,
            "streaming_url": streaming_url,
            "start_date": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            "imported_via": "launcher",
        }
        if matched_panel_type == "ghostsurf":
            svc_doc["vpn_username"] = username
            svc_doc["vpn_password"] = line_data.get("password", "")
            svc_doc["ghostsurf_account_id"] = str(line_data.get("id", ""))
        else:
            svc_doc["xtream_username"] = username
            svc_doc["xtream_password"] = line_data.get("password", password)
            svc_doc["xtream_user_id"] = line_data.get("id")
        
        result = await db.services.insert_one(svc_doc)
        service_id = str(result.inserted_id)
    
    # 6. Issue device token
    plaintext = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext)
    
    await db.launcher_devices.insert_one({
        "device_id": device_id,
        "token_hash": token_hash,
        "service_id": service_id,
        "customer_id": customer_id,
        "xtream_username": username,
        "status": "active",
        "imported_via": "launcher_import",
        "created_at": datetime.utcnow(),
        "last_seen_at": datetime.utcnow(),
    })
    
    logger.info(f"Launcher import: {username} on {matched_panel_name} → device {device_id[:12]}...")
    
    return {
        "status": "imported",
        "device_token": plaintext,
        "service_status": line_status,
        "username": username,
        "streaming_url": streaming_url,
        "expires_at": expiry_date.isoformat() if expiry_date else None,
        "days_remaining": days_remaining,
        "connections": max_conn,
        "panel_type": matched_panel_type,
        "panel_name": matched_panel_name,
        "package": f"Imported Line ({matched_panel_name})",
        "manage_url": f"/launcher/manage/{plaintext}",
    }



# ──────────────────────────────────────────────
# Launcher: Checkout
# ──────────────────────────────────────────────

@router.post("/checkout")
async def create_launcher_checkout(request: Request, key: dict = Depends(_verify_launcher_key)):
    """Create an order and return checkout URL + QR payload.
    
    Body: {
      package_id, device_id, gateway?, email (required),
      mode: "new" | "renew" (default "new"),
      device_token: required when mode=renew (identifies the existing line)
    }
    """
    body = await request.json()
    package_id = body.get("package_id")
    device_id = body.get("device_id")
    gateway = body.get("gateway")
    email = (body.get("email") or "").strip()
    mode = body.get("mode", "new")  # "new" or "renew"
    device_token_str = body.get("device_token", "")
    
    if not package_id:
        raise HTTPException(status_code=400, detail="package_id required")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    
    # ── MODE=RENEW: resolve existing line ──
    renewal_service = None
    renewal_service_id = None
    existing_username = None
    
    if mode == "renew":
        if not device_token_str:
            raise HTTPException(status_code=400, detail="device_token required for mode=renew")
        
        token_hash = _hash_token(device_token_str)
        device_row = await db.launcher_devices.find_one({"token_hash": token_hash, "status": "active"})
        if not device_row:
            raise HTTPException(status_code=404, detail="Device token not found or revoked — cannot renew")
        
        # Find the service linked to this device
        if device_row.get("service_id"):
            renewal_service = await db.services.find_one({"_id": ObjectId(device_row["service_id"])})
        if not renewal_service and device_row.get("xtream_username"):
            renewal_service = await db.services.find_one({
                "$or": [
                    {"xtream_username": device_row["xtream_username"]},
                    {"vpn_username": device_row["xtream_username"]}
                ],
                "status": {"$in": ["active", "expired"]}
            })
        
        if not renewal_service:
            raise HTTPException(status_code=404, detail="No service found for this device token — cannot renew. Use mode=new to create a new line.")
        
        renewal_service_id = str(renewal_service["_id"])
        existing_username = renewal_service.get("xtream_username") or renewal_service.get("vpn_username", "")
        logger.info(f"Launcher renew: resolved service {renewal_service_id} user={existing_username}")
    
    # Get product
    product = await db.products.find_one({"_id": ObjectId(package_id)})
    if not product or not product.get("active"):
        raise HTTPException(status_code=404, detail="Package not found")
    
    settings = await _get_settings()
    
    # Resolve gateway
    if gateway:
        gw_conf = settings.get(gateway, {})
        if not gw_conf.get("enabled"):
            raise HTTPException(status_code=400, detail=f"Gateway '{gateway}' is not enabled")
    else:
        gateway = settings.get("launcher", {}).get("default_gateway", "")
        if not gateway:
            for gw in ["ghostpay", "tagadapay", "stripe", "paypal", "helcim"]:
                if settings.get(gw, {}).get("enabled"):
                    gateway = gw
                    break
        if not gateway:
            raise HTTPException(status_code=400, detail="No payment gateway configured")
    
    # Get price
    prices = product.get("prices", {})
    first_term = list(prices.keys())[0] if prices else "1"
    price = float(prices.get(first_term, 0))
    
    currency = settings.get("currency", "USD")
    if isinstance(currency, dict):
        currency = currency.get("code", "USD")
    
    # Create or find customer — use email, never @device.local
    customer = await db.users.find_one({"email": email})
    if not customer:
        customer = await db.users.find_one({"launcher_device_id": device_id})
    
    if customer:
        customer_id = str(customer["_id"])
        # Update email if it was a placeholder
        if customer.get("email", "").endswith("@device.local"):
            await db.users.update_one({"_id": customer["_id"]}, {"$set": {"email": email}})
    else:
        result = await db.users.insert_one({
            "email": email,
            "name": email.split("@")[0],
            "password": "",
            "role": "user",
            "email_verified": True,
            "credit_balance": 0.0,
            "launcher_device_id": device_id,
            "created_via": "launcher",
            "created_at": datetime.utcnow()
        })
        customer_id = str(result.inserted_id)
    
    # Build order item
    action_type = "renew" if mode == "renew" else "new"
    order_item = {
        "product_id": str(product["_id"]),
        "product_name": product.get("name", ""),
        "term_months": int(first_term),
        "price": price,
        "account_type": product.get("account_type", "subscriber"),
        "action_type": action_type,
    }
    if renewal_service_id:
        order_item["renewal_service_id"] = renewal_service_id
    
    # Create order
    order_dict = {
        "user_id": customer_id,
        "items": [order_item],
        "total": price,
        "status": "pending",
        "payment_method": gateway,
        "launcher_device_id": device_id,
        "launcher_gateway": gateway,
        "launcher_mode": mode,
        "created_at": datetime.utcnow()
    }
    if renewal_service_id:
        order_dict["launcher_renewal_service_id"] = renewal_service_id
        order_dict["launcher_renewal_username"] = existing_username
    
    result = await db.orders.insert_one(order_dict)
    order_id = str(result.inserted_id)
    
    # Create invoice
    await db.invoices.insert_one({
        "order_id": order_id,
        "user_id": customer_id,
        "amount": price,
        "currency": currency,
        "status": "unpaid",
        "created_at": datetime.utcnow()
    })
    
    import os
    site_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", ""))
    checkout_url = f"{site_url}/launcher/pay/{order_id}"
    
    resp = {
        "order_id": order_id,
        "checkout_url": checkout_url,
        "qr_payload": checkout_url,
        "amount": price,
        "currency": currency,
        "gateway": gateway,
        "package": product.get("name", ""),
        "mode": mode,
    }
    if mode == "renew":
        resp["renewing_username"] = existing_username
    
    return resp


# ──────────────────────────────────────────────
# Launcher: Poll order status
# ──────────────────────────────────────────────

@router.get("/order/{order_id}")
async def get_launcher_order(order_id: str, key: dict = Depends(_verify_launcher_key)):
    """Poll order status. Returns device_token once provisioned.
    For mode=renew: extends existing line instead of creating new."""
    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    mode = order.get("launcher_mode", "new")
    
    result = {
        "order_id": order_id,
        "status": order.get("status", "pending"),
        "amount": order.get("total", 0),
        "package": order["items"][0]["product_name"] if order.get("items") else "",
        "mode": mode,
    }
    
    if order.get("status") == "paid" and order.get("provisioned"):
        device_id = order.get("launcher_device_id")
        
        if mode == "renew":
            # Renewal — the existing service was extended by provision_order_services
            renewal_service_id = order.get("launcher_renewal_service_id")
            service = None
            if renewal_service_id:
                service = await db.services.find_one({"_id": ObjectId(renewal_service_id)})
            if not service:
                service = await db.services.find_one({"order_id": order_id})
            
            if service:
                # Fetch live status
                settings = await _get_settings()
                live = await _fetch_live_line_status(service, settings)
                
                result["status"] = "provisioned"
                result["expires_at"] = live["expires_at"]
                result["days_remaining"] = live["days_remaining"]
                result["username"] = service.get("xtream_username") or service.get("vpn_username", "")
                result["connections"] = live["connections"]
                result["renewed"] = True
                
                # For renewals, don't issue a new device token — the existing one still works
                result["device_token_issued"] = True
        else:
            # New purchase — find the created service and issue device token
            service = await db.services.find_one({"order_id": order_id})
            
            if service:
                settings = await _get_settings()
                live = await _fetch_live_line_status(service, settings)
                
                result["status"] = "provisioned"
                result["expires_at"] = live["expires_at"]
                result["days_remaining"] = live["days_remaining"]
                result["username"] = service.get("xtream_username") or service.get("vpn_username", "")
                result["password"] = service.get("xtream_password") or service.get("vpn_password", "")
                result["streaming_url"] = service.get("streaming_url", "")
                result["ghostapk_code"] = service.get("ghostapk_code", "")
                result["connections"] = live["connections"]
                
                # Issue device token if not already issued for this order
                existing_device = await db.launcher_devices.find_one({"order_id": order_id})
                if existing_device:
                    result["device_token_issued"] = True
                elif device_id:
                    plaintext = secrets.token_urlsafe(32)
                    token_hash = _hash_token(plaintext)
                    
                    await db.launcher_devices.insert_one({
                        "device_id": device_id,
                        "token_hash": token_hash,
                        "order_id": order_id,
                        "service_id": str(service["_id"]),
                        "customer_id": order.get("user_id"),
                        "xtream_username": service.get("xtream_username") or service.get("vpn_username", ""),
                        "status": "active",
                        "created_at": datetime.utcnow(),
                        "last_seen_at": datetime.utcnow()
                    })
                    
                    result["device_token"] = plaintext
                    logger.info(f"Issued device token for order {order_id}, device {device_id}")
    
    elif order.get("status") == "paid":
        result["status"] = "paid"  # Paid but not yet provisioned
    
    return result


# ──────────────────────────────────────────────
# Launcher: Config (enabled gateways, etc.)
# ──────────────────────────────────────────────

@router.get("/config")
async def get_launcher_config(key: dict = Depends(_verify_launcher_key)):
    """Launcher configuration: enabled gateways, branding, etc."""
    settings = await _get_settings()
    
    enabled_gateways = []
    gateway_info = {
        "ghostpay": {"name": "Crypto (BTC/ETH/USDT)", "type": "qr"},
        "tagadapay": {"name": "Card Payment", "type": "webview"},
        "stripe": {"name": "Card Payment (Stripe)", "type": "webview"},
        "paypal": {"name": "PayPal", "type": "webview"},
        "helcim": {"name": "Card/ACH (Helcim)", "type": "webview"},
    }
    
    for gw_name, gw_meta in gateway_info.items():
        if settings.get(gw_name, {}).get("enabled"):
            enabled_gateways.append({
                "id": gw_name,
                "name": gw_meta["name"],
                "type": gw_meta["type"],
            })
    
    branding = settings.get("branding", {})
    
    return {
        "gateways": enabled_gateways,
        "default_gateway": settings.get("launcher", {}).get("default_gateway", ""),
        "branding": {
            "company_name": branding.get("company_name") or settings.get("company_name", "IPTV"),
            "logo_url": branding.get("logo_url", ""),
            "primary_color": branding.get("primary_color", "#2563eb"),
        },
        "currency": settings.get("currency", "USD") if isinstance(settings.get("currency"), str) else settings.get("currency", {}).get("code", "USD"),
    }


# ──────────────────────────────────────────────
# Launcher: Pay info (public — for checkout page)
# ──────────────────────────────────────────────

@router.get("/pay-info/{order_id}")
async def get_launcher_pay_info(order_id: str):
    """Public endpoint for the launcher checkout page to fetch order details."""
    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    result = {
        "order_id": order_id,
        "status": order.get("status", "pending"),
        "amount": order.get("total", 0),
        "currency": "USD",
        "gateway": order.get("launcher_gateway", order.get("payment_method", "")),
        "package": order["items"][0]["product_name"] if order.get("items") else "",
    }
    
    settings = await _get_settings()
    currency = settings.get("currency", "USD")
    if isinstance(currency, dict):
        currency = currency.get("code", "USD")
    result["currency"] = currency
    
    if order.get("status") == "paid":
        service = await db.services.find_one({"order_id": order_id})
        if service:
            result["status"] = "provisioned"
            result["expires_at"] = service.get("expiry_date").isoformat() if service.get("expiry_date") else None
    
    return result


# ──────────────────────────────────────────────
# Launcher: Initiate payment (public — checkout page triggers this)
# ──────────────────────────────────────────────

@router.post("/pay/{order_id}/initiate")
async def initiate_launcher_payment(order_id: str, request: Request):
    """Initiate payment for a launcher order. Returns gateway-specific data (QR, redirect, card form info)."""
    import os
    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") == "paid":
        return {"status": "already_paid", "message": "Order already paid"}
    
    gateway = order.get("launcher_gateway", order.get("payment_method", ""))
    settings = await _get_settings()
    
    base_url = os.getenv("BACKEND_PUBLIC_URL", os.getenv("SITE_URL", ""))
    currency = settings.get("currency", "USD")
    if isinstance(currency, dict):
        currency = currency.get("code", "USD")
    
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    
    if gateway == "ghostpay":
        from ghostpay_service import get_ghostpay_service
        gp = get_ghostpay_service(settings)
        if not gp:
            raise HTTPException(status_code=400, detail="GhostPay not configured")
        
        crypto = body.get("crypto", "BTC")
        callback_url = f"{base_url}/api/webhooks/ghostpay"
        
        result = await gp.create_payment(
            crypto=crypto,
            amount=order["total"],
            external_id=order_id,
            fiat=currency,
            callback_url=callback_url
        )
        
        if result["success"]:
            await db.payment_transactions.insert_one({
                "order_id": order_id,
                "user_id": order.get("user_id", ""),
                "gateway": "ghostpay",
                "invoice_id": result["invoice_id"],
                "crypto": crypto,
                "amount_fiat": order["total"],
                "amount_crypto": result.get("amount_crypto"),
                "wallet": result.get("wallet"),
                "payment_status": "pending",
                "created_at": datetime.utcnow()
            })
            return {
                "gateway": "ghostpay",
                "invoice_id": result["invoice_id"],
                "payment_url": result["payment_url"],
                "wallet": result["wallet"],
                "amount_crypto": result["amount_crypto"],
                "crypto": crypto,
                "qr_data": result.get("wallet", ""),
                "expires_at": result.get("expires_at"),
            }
        raise HTTPException(status_code=500, detail=result.get("error", "Payment creation failed"))
    
    elif gateway == "tagadapay":
        # For TagadaPay card payments — return info needed for the card form
        # The actual charge happens via /pay/{order_id}/tagadapay-charge
        from tagadapay_service import get_tagadapay_service
        tagada = get_tagadapay_service(settings)
        if not tagada:
            raise HTTPException(status_code=400, detail="TagadaPay not configured")
        
        return {
            "gateway": "tagadapay",
            "requires_card": True,
            "amount": order["total"],
            "currency": currency,
            "order_id": order_id,
        }
    
    elif gateway == "stripe":
        # Could create a Stripe Checkout session
        return {
            "gateway": "stripe",
            "requires_redirect": True,
            "message": "Stripe checkout — redirect to payment page",
            "amount": order["total"],
            "currency": currency,
        }
    
    elif gateway == "paypal":
        return {
            "gateway": "paypal",
            "requires_redirect": True,
            "message": "PayPal checkout — redirect to payment page",
            "amount": order["total"],
            "currency": currency,
        }
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported gateway: {gateway}")


@router.post("/pay/{order_id}/tagadapay-charge")
async def launcher_tagadapay_charge(order_id: str, request: Request, background_tasks: BackgroundTasks):
    """Process TagadaPay card payment for a launcher order (server-side tokenization)."""
    import os, base64, json as json_mod, httpx
    
    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") == "paid":
        return {"status": "already_paid"}
    
    body = await request.json()
    card_number = body.get("card_number", "").replace(" ", "")
    expiry = body.get("expiry", "")
    cvc = body.get("cvc", "")
    cardholder_name = body.get("cardholder_name", "")
    
    if not card_number or not expiry or not cvc:
        raise HTTPException(status_code=400, detail="Card details required")
    
    settings = await _get_settings()
    from tagadapay_service import get_tagadapay_service
    tagada = get_tagadapay_service(settings)
    if not tagada:
        raise HTTPException(status_code=400, detail="TagadaPay not configured")
    
    # Get customer info
    user = await db.users.find_one({"_id": ObjectId(order.get("user_id", ""))})
    customer_email = user.get("email", "") if user else ""
    name_parts = (user.get("name", "") if user else "").split(" ", 1)
    first_name = name_parts[0] if name_parts else "Customer"
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    
    # Server-side BasisTheory tokenization
    BT_API_KEY = "key_prod_us_pub_PNMB2AiaECJ463K6QAPNU6"
    try:
        exp_parts = expiry.split("/")
        exp_month = int(exp_parts[0])
        exp_year = int(exp_parts[1]) + 2000
        
        async with httpx.AsyncClient() as client:
            bt_resp = await client.post(
                "https://api.basistheory.com/tokens",
                headers={"BT-API-KEY": BT_API_KEY, "Content-Type": "application/json"},
                json={
                    "type": "card",
                    "data": {"number": card_number, "expiration_month": exp_month, "expiration_year": exp_year, "cvc": cvc},
                    **({"metadata": {"cardholderName": cardholder_name}} if cardholder_name else {})
                },
                timeout=15.0
            )
            if bt_resp.status_code not in (200, 201):
                raise HTTPException(status_code=400, detail=f"Card tokenization failed")
            
            bt_data = bt_resp.json()
            bt_token_id = bt_data.get("id")
            
            tagada_token_obj = {
                "type": "card", "token": bt_token_id, "provider": "basistheory",
                "nonSensitiveMetadata": {"cardType": "card", "expiryMonth": exp_month, "expiryYear": exp_year, "createdAt": datetime.utcnow().isoformat() + "Z"}
            }
            tagada_token = base64.b64encode(json_mod.dumps(tagada_token_obj).encode()).decode()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Card processing error: {str(e)}")
    
    # Create payment instrument + process
    instrument_result = await tagada.create_payment_instrument(tagada_token, customer_email, first_name, last_name)
    if not instrument_result["success"]:
        raise HTTPException(status_code=400, detail=f"Payment failed: {instrument_result['error']}")
    
    pi_id = instrument_result["payment_instrument_id"]
    customer_id = instrument_result["customer_id"]
    
    site_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", ""))
    return_url = f"{site_url}/launcher/pay/{order_id}?status=success"
    amount_cents = int(float(order["total"]) * 100)
    
    payment_result = await tagada.process_payment(
        payment_instrument_id=pi_id, customer_id=customer_id,
        amount=amount_cents, currency=settings.get("currency", "USD") if isinstance(settings.get("currency"), str) else settings.get("currency", {}).get("code", "USD"),
        return_url=return_url, metadata={"order_id": order_id}
    )
    
    await db.payment_transactions.insert_one({
        "order_id": order_id, "user_id": order.get("user_id", ""), "gateway": "tagadapay",
        "payment_id": payment_result.get("payment_id"), "payment_status": payment_result.get("status", "unknown"),
        "amount": order["total"], "created_at": datetime.utcnow()
    })
    
    if payment_result.get("requires_redirect"):
        return {"success": True, "requires_redirect": True, "redirect_url": payment_result["redirect_url"]}
    
    if payment_result["success"]:
        await db.orders.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "tagadapay", "payment_id": payment_result.get("payment_id")}}
        )
        await db.invoices.update_one({"order_id": order_id}, {"$set": {"status": "paid", "paid_date": datetime.utcnow()}})
        
        user = await db.users.find_one({"_id": ObjectId(order.get("user_id", ""))})
        if user:
            background_tasks.add_task(_provision_order_services, order_id, order, user)
        
        return {"success": True, "status": "paid"}
    
    raise HTTPException(status_code=400, detail=payment_result.get("error", "Payment failed"))


@router.get("/pay/{order_id}/ghostpay-status/{invoice_id}")
async def check_launcher_ghostpay_status(order_id: str, invoice_id: str, background_tasks: BackgroundTasks):
    """Poll GhostPay payment status for a launcher order."""
    from ghostpay_service import GhostPayService
    gp = GhostPayService("")
    result = await gp.check_invoice(invoice_id)
    
    if result.get("success") and result.get("status") in ("PAID", "OVERPAID"):
        order = await db.orders.find_one({"_id": ObjectId(order_id)})
        if order and order.get("status") != "paid":
            await db.orders.update_one(
                {"_id": ObjectId(order_id)},
                {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "ghostpay"}}
            )
            await db.invoices.update_one({"order_id": order_id}, {"$set": {"status": "paid", "paid_date": datetime.utcnow()}})
            await db.payment_transactions.update_one({"invoice_id": invoice_id}, {"$set": {"payment_status": "paid"}})
            
            user = await db.users.find_one({"_id": ObjectId(order.get("user_id", ""))})
            if user:
                background_tasks.add_task(_provision_order_services, order_id, order, user)
        
        return {"status": "paid", "message": "Payment confirmed"}
    
    return {"status": result.get("status", "pending"), "message": "Waiting for payment"}


# ──────────────────────────────────────────────
# Launcher: Admin Dashboard / Analytics
# ──────────────────────────────────────────────

@router.get("/admin/analytics")
async def get_launcher_analytics(request: Request):
    """Device analytics: active launchers, revenue, activity."""
    await _verify_admin(request)
    
    # Total devices
    total_devices = await db.launcher_devices.count_documents({})
    active_devices = await db.launcher_devices.count_documents({"status": "active"})
    
    # Recently active (last 24h)
    recently_active = await db.launcher_devices.count_documents({
        "last_seen_at": {"$gte": datetime.utcnow() - timedelta(hours=24)}
    })
    
    # Revenue from launcher orders
    pipeline = [
        {"$match": {"launcher_device_id": {"$exists": True}, "status": "paid"}},
        {"$group": {"_id": None, "total_revenue": {"$sum": "$total"}, "order_count": {"$sum": 1}}}
    ]
    revenue_data = await db.orders.aggregate(pipeline).to_list(1)
    total_revenue = revenue_data[0]["total_revenue"] if revenue_data else 0
    total_orders = revenue_data[0]["order_count"] if revenue_data else 0
    
    # Recent devices with details
    recent_devices = []
    async for device in db.launcher_devices.find({"status": "active"}).sort("last_seen_at", -1).limit(50):
        svc = None
        if device.get("service_id"):
            svc = await db.services.find_one({"_id": ObjectId(device["service_id"])})
        
        recent_devices.append({
            "id": str(device["_id"]),
            "device_id": device.get("device_id", ""),
            "username": device.get("xtream_username", ""),
            "status": "active" if svc and svc.get("status") == "active" else "expired",
            "last_seen": device.get("last_seen_at").isoformat() if device.get("last_seen_at") else None,
            "created_at": device.get("created_at").isoformat() if device.get("created_at") else None,
            "service_name": svc.get("product_name", "") if svc else "",
            "expiry": svc.get("expiry_date").isoformat() if svc and svc.get("expiry_date") else None,
        })
    
    # Monthly revenue breakdown (last 6 months)
    monthly_pipeline = [
        {"$match": {"launcher_device_id": {"$exists": True}, "status": "paid", "paid_at": {"$exists": True}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$paid_at"}},
            "revenue": {"$sum": "$total"},
            "orders": {"$sum": 1}
        }},
        {"$sort": {"_id": -1}},
        {"$limit": 6}
    ]
    monthly = await db.orders.aggregate(monthly_pipeline).to_list(6)
    
    return {
        "total_devices": total_devices,
        "active_devices": active_devices,
        "recently_active_24h": recently_active,
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "monthly_revenue": monthly,
        "devices": recent_devices,
    }


# ──────────────────────────────────────────────
# Launcher: Manage page data (token in URL)
# ──────────────────────────────────────────────

@router.get("/manage-info/{device_token}")
async def get_launcher_manage_info(device_token: str):
    """Public endpoint for the launcher manage page — looks up device by token."""
    token_hash = _hash_token(device_token)
    device = await db.launcher_devices.find_one({"token_hash": token_hash})
    if not device:
        raise HTTPException(status_code=404, detail="Invalid or expired device token")
    
    if device.get("status") == "revoked":
        raise HTTPException(status_code=403, detail="Device token has been revoked")
    
    # Update last_seen
    await db.launcher_devices.update_one({"_id": device["_id"]}, {"$set": {"last_seen_at": datetime.utcnow()}})
    
    # Get linked service
    service = None
    if device.get("service_id"):
        service = await db.services.find_one({"_id": ObjectId(device["service_id"])})
    elif device.get("xtream_username"):
        service = await db.services.find_one({"xtream_username": device["xtream_username"], "status": {"$in": ["active", "expired"]}})
    
    # Get customer info
    customer = None
    if device.get("customer_id"):
        customer = await db.users.find_one({"_id": ObjectId(device["customer_id"])})
    
    settings = await _get_settings()
    currency = settings.get("currency", "USD")
    if isinstance(currency, dict):
        currency = currency.get("code", "USD")
    
    # Find compatible renewal products
    renewal_products = []
    if service and service.get("product_id"):
        product = await db.products.find_one({"_id": ObjectId(service["product_id"]), "active": True})
        if product:
            prices = product.get("prices", {})
            for term, price in prices.items():
                renewal_products.append({
                    "product_id": str(product["_id"]),
                    "name": product.get("name", ""),
                    "term_months": int(term),
                    "price": float(price),
                    "currency": currency,
                })
        # Also find other active products for the same panel
        async for p in db.products.find({
            "active": True,
            "panel_type": service.get("panel_type", "xtream"),
            "panel_index": service.get("panel_index", 0),
            "_id": {"$ne": ObjectId(service["product_id"])}
        }).limit(10):
            prices = p.get("prices", {})
            for term, price in prices.items():
                renewal_products.append({
                    "product_id": str(p["_id"]),
                    "name": p.get("name", ""),
                    "term_months": int(term),
                    "price": float(price),
                    "currency": currency,
                })
    
    # Build response
    result = {
        "device_id": device.get("device_id", ""),
        "customer_name": customer.get("name", "") if customer else "",
        "customer_email": customer.get("email", "") if customer else "",
        "credit_balance": customer.get("credit_balance", 0) if customer else 0,
    }
    
    if service:
        expiry = service.get("expiry_date")
        days_remaining = 0
        if expiry:
            if isinstance(expiry, str):
                expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            delta = expiry - datetime.utcnow()
            days_remaining = max(0, delta.days)
        
        result.update({
            "has_service": True,
            "service_status": service.get("status", "unknown"),
            "product_name": service.get("product_name", ""),
            "username": service.get("xtream_username") or service.get("vpn_username", ""),
            "expires_at": expiry.isoformat() if expiry else None,
            "days_remaining": days_remaining,
            "connections": service.get("max_connections", 1),
            "panel_type": service.get("panel_type", "xtream"),
            "streaming_url": service.get("streaming_url", ""),
        })
    else:
        result["has_service"] = False
    
    result["renewal_products"] = renewal_products
    result["currency"] = currency
    
    # Branding
    branding = settings.get("branding", {})
    result["branding"] = {
        "company_name": branding.get("company_name") or settings.get("company_name", "IPTV"),
        "logo_url": branding.get("logo_url", ""),
        "support_email": settings.get("support_email", settings.get("company_email", "")),
    }
    
    return result

