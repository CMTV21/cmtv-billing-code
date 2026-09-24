import requests
import os
import logging
import json

logger = logging.getLogger(__name__)

class PayPalService:
    """PayPal payment processing service using Orders API v2"""
    
    def __init__(self, client_id=None, secret=None, mode="sandbox"):
        self.client_id = client_id or os.getenv("PAYPAL_CLIENT_ID", "")
        self.secret = secret or os.getenv("PAYPAL_SECRET", "")
        self.mode = mode or "sandbox"
        self.base_url = "https://api.sandbox.paypal.com" if mode == "sandbox" else "https://api.paypal.com"
        self.access_token = None
        
        if self.client_id and self.secret:
            self._get_access_token()
            logger.info(f"PayPal configured in {self.mode} mode with Orders API v2")
    
    def _get_access_token(self):
        """Get OAuth access token"""
        try:
            response = requests.post(
                f"{self.base_url}/v1/oauth2/token",
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
                auth=(self.client_id, self.secret),
                data={"grant_type": "client_credentials"}
            )
            
            if response.status_code == 200:
                self.access_token = response.json()["access_token"]
                logger.info("PayPal access token obtained")
            else:
                logger.error(f"Failed to get PayPal access token: {response.text}")
                
        except Exception as e:
            logger.error(f"PayPal auth error: {e}")
    
    def create_order(self, amount, currency="USD", return_url="", cancel_url="", order_id=""):
        """Create PayPal order using Orders API v2"""
        if not self.access_token:
            return {"success": False, "error": "PayPal not authenticated"}
        
        try:
            order_data = {
                "intent": "CAPTURE",
                "purchase_units": [{
                    "reference_id": order_id,
                    "custom_id": order_id,
                    "amount": {
                        "currency_code": currency,
                        "value": f"{float(amount):.2f}"
                    },
                    "description": f"Order #{order_id[:8]}"
                }],
                "application_context": {
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                    "brand_name": "Digital Services",
                    "user_action": "PAY_NOW"
                }
            }
            
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.access_token}"
                },
                json=order_data
            )
            
            if response.status_code == 201:
                order = response.json()
                logger.info(f"PayPal order created: {order['id']}")
                
                # Get approval URL
                approval_url = None
                for link in order.get("links", []):
                    if link.get("rel") == "approve":
                        approval_url = link.get("href")
                        break
                
                return {
                    "success": True,
                    "order_id": order["id"],  # EC-XXX token
                    "approval_url": approval_url
                }
            else:
                logger.error(f"PayPal order creation failed: {response.text}")
                return {"success": False, "error": response.json()}
                
        except Exception as e:
            logger.error(f"PayPal order creation error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_order(self, order_id):
        """Look up a PayPal order (CMTV local change 2026-09-24): lets billing check which billing order and
        amount it was created for before capturing it."""
        if not self.access_token:
            return {"success": False, "error": "PayPal not authenticated"}
        try:
            response = requests.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=20
            )
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}"}
            data = response.json()
            unit = (data.get("purchase_units") or [{}])[0]
            amount = unit.get("amount") or {}
            return {
                "success": True,
                "status": data.get("status"),
                "reference_id": unit.get("reference_id") or unit.get("custom_id") or "",
                "amount": amount.get("value"),
                "currency": amount.get("currency_code"),
            }
        except Exception as e:
            logger.error(f"PayPal get_order error: {e}")
            return {"success": False, "error": str(e)}

    def get_capture(self, capture_id):
        """Look up a PayPal capture (CMTV local change 2026-09-24), so webhooks can be verified with PayPal
        instead of trusting the webhook body."""
        if not self.access_token:
            return {"success": False, "error": "PayPal not authenticated"}
        try:
            response = requests.get(
                f"{self.base_url}/v2/payments/captures/{capture_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=20
            )
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}"}
            data = response.json()
            amount = data.get("amount") or {}
            return {
                "success": True,
                "status": data.get("status"),
                "custom_id": data.get("custom_id") or data.get("invoice_id") or "",
                "paypal_order_id": ((data.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id", ""),
                "amount": amount.get("value"),
                "currency": amount.get("currency_code"),
            }
        except Exception as e:
            logger.error(f"PayPal get_capture error: {e}")
            return {"success": False, "error": str(e)}

    def capture_order(self, order_id):
        """Capture/complete a PayPal order"""
        if not self.access_token:
            return {"success": False, "error": "PayPal not authenticated"}
        
        try:
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.access_token}"
                }
            )
            
            if response.status_code == 201:
                capture = response.json()
                logger.info(f"PayPal order captured: {order_id}")
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "status": capture.get("status"),
                    "payer_email": capture.get("payer", {}).get("email_address")
                }
            else:
                logger.error(f"PayPal capture failed: {response.text}")
                return {"success": False, "error": response.json()}
                
        except Exception as e:
            logger.error(f"PayPal capture error: {e}")
            return {"success": False, "error": str(e)}

def get_paypal_service(paypal_settings=None):
    """Get PayPal service instance"""
    if not paypal_settings:
        return None
    
    if not paypal_settings.get("enabled"):
        return None
    
    return PayPalService(
        client_id=paypal_settings.get("client_id"),
        secret=paypal_settings.get("secret"),
        mode=paypal_settings.get("mode", "sandbox")
    )
