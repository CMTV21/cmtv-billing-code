"""GhostPay Crypto Payment Gateway Service - Updated API v1"""
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

BASE_URL = "https://gateway.ghostpay.cash"


class GhostPayService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}
    
    async def get_cryptos(self) -> Dict[str, Any]:
        """List enabled cryptocurrencies with active wallets"""
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(f"{BASE_URL}/api/v1/crypto", headers=self.headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    # New format: {status: "success", cryptos: [...]}
                    if isinstance(data, dict) and data.get("status") == "success":
                        return {"success": True, "cryptos": data.get("cryptos", [])}
                    # Fallback for array response
                    if isinstance(data, list):
                        return {"success": True, "cryptos": data}
                    return {"success": True, "cryptos": data.get("cryptos", [])}
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.error(f"GhostPay get_cryptos error: {e}")
            return {"success": False, "error": str(e)}
    
    async def create_payment(self, crypto: str, amount: float, external_id: str,
                             fiat: str = "USD", callback_url: str = "", return_url: str = "") -> Dict[str, Any]:
        """Create a payment invoice
        POST /api/v1/{crypto}/payment_request
        """
        try:
            params = {
                "external_id": external_id,
                "amount": amount,
                "fiat": fiat,
            }
            if callback_url:
                params["callback_url"] = callback_url
            if return_url:
                params["return_url"] = return_url
            
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.post(
                    f"{BASE_URL}/api/v1/{crypto}/payment_request",
                    headers=self.headers,
                    params=params,
                    timeout=15
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Check for error status
                    if data.get("status") == "error":
                        return {"success": False, "error": data.get("message", "Payment creation failed")}
                    
                    invoice_id = data.get("id")
                    return {
                        "success": True,
                        "invoice_id": invoice_id,
                        "wallet": data.get("wallet"),
                        "amount_crypto": data.get("amount"),
                        "amount_fiat": data.get("amount_fiat"),
                        "crypto": crypto,
                        "fiat": data.get("fiat", fiat),
                        "rate": data.get("rate"),
                        "rate_locked": data.get("rate_locked", True),
                        "expires_at": data.get("expires_at"),
                        "payment_url": f"{BASE_URL}/pay/{invoice_id}"
                    }
                else:
                    error = resp.text[:200]
                    logger.error(f"GhostPay create_payment error: {resp.status_code} {error}")
                    return {"success": False, "error": f"Payment creation failed ({resp.status_code})"}
        except Exception as e:
            logger.error(f"GhostPay create_payment exception: {e}")
            return {"success": False, "error": str(e)}
    
    async def check_invoice(self, invoice_id: str) -> Dict[str, Any]:
        """Check invoice status - public endpoint, no auth needed
        GET /api/public/invoice/{invoice_id}
        Statuses: UNPAID, PARTIAL, PAID, OVERPAID, EXPIRED
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(f"{BASE_URL}/api/public/invoice/{invoice_id}", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "success": True,
                        "id": data.get("id"),
                        "status": data.get("status"),
                        "crypto": data.get("crypto"),
                        "crypto_name": data.get("crypto_name"),
                        "amount_fiat": data.get("amount_fiat"),
                        "fiat_currency": data.get("fiat_currency"),
                        "amount_crypto": data.get("amount_crypto"),
                        "address": data.get("address"),
                        "amount_received": data.get("amount_received"),
                        "current_rate": data.get("current_rate"),
                        "locked_rate": data.get("locked_rate"),
                        "expires_at": data.get("expires_at"),
                        "transactions": data.get("transactions", [])
                    }
                elif resp.status_code == 404:
                    return {"success": False, "error": "Invoice not found", "status": "UNKNOWN"}
                return {"success": False, "error": f"HTTP {resp.status_code}", "status": "UNKNOWN"}
        except Exception as e:
            logger.error(f"GhostPay check_invoice error: {e}")
            return {"success": False, "error": str(e), "status": "UNKNOWN"}
    
    async def get_prices(self) -> Dict[str, Any]:
        """Get live crypto prices - public, no auth
        GET /api/crypto/prices
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(f"{BASE_URL}/api/crypto/prices", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    return {"success": True, "prices": data.get("prices", data if isinstance(data, list) else [])}
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error(f"GhostPay get_prices error: {e}")
            return {"success": False, "error": str(e)}


def get_ghostpay_service(settings: dict) -> Optional[GhostPayService]:
    """Get GhostPay service from settings"""
    ghostpay = settings.get("ghostpay", {})
    api_key = ghostpay.get("api_key", "")
    if not api_key or not ghostpay.get("enabled"):
        return None
    return GhostPayService(api_key)
