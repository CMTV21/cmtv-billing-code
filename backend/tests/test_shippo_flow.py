"""Backend tests for the Shippo shipping integration.

Covers:
  * Admin shipping settings (GET/PUT) — verify token stays masked & test-mode badge
  * Shippo test-connection endpoint
  * Live rate quote (rates endpoint including live Shippo carriers)
  * Order + shipment + buy-label + duplicate 409 + label PDF
  * Webhook auth (bad token → 401)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") \
    else "https://admin-analytics-46.preview.emergentagent.com"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"
CUSTOMER_EMAIL = "shippo.customer@example.com"
CUSTOMER_PASSWORD = "Customer123!"

SHIP_TO = {
    "name": "Shippo Customer", "phone": "2125550199",
    "address1": "350 5th Ave", "address2": "",
    "city": "New York", "state": "NY", "postal_code": "10118", "country": "US",
}


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def customer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"customer login failed: {r.status_code} {r.text}")
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def customer_headers(customer_token):
    return {"Authorization": f"Bearer {customer_token}"}


@pytest.fixture(scope="session")
def physical_item():
    r = requests.get(f"{BASE_URL}/api/physical-items", timeout=15)
    assert r.status_code == 200
    items = [x for x in r.json() if x.get("name") == "Shippo Test Box"]
    assert items, "Shippo Test Box not seeded"
    return items[0]


# ---- Settings ----
class TestShippingSettings:
    def test_admin_get_settings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/shipping/settings", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "shippo" in d
        s = d["shippo"]
        assert s.get("enabled") is True
        assert s.get("api_token_set") is True
        assert s.get("mode") == "test"
        # token should be masked (contains …) not raw
        assert "…" in (s.get("api_token") or "")
        assert d.get("ship_from", {}).get("country") == "US"

    def test_admin_save_without_touching_token(self, admin_headers):
        cur = requests.get(f"{BASE_URL}/api/admin/shipping/settings", headers=admin_headers, timeout=15).json()
        payload = dict(cur)
        # Do NOT include api_token — should keep it as-is
        payload["shippo"] = {**cur["shippo"]}
        payload["shippo"].pop("api_token", None)
        r = requests.put(f"{BASE_URL}/api/admin/shipping/settings", headers=admin_headers, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        after = r.json()
        assert after["shippo"]["api_token_set"] is True
        assert after["shippo"]["mode"] == "test"

    def test_shippo_test_connection(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/admin/shipping/shippo/test", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True or "carriers" in d
        assert isinstance(d.get("carriers", []), list)

    def test_admin_rate_tester_live(self, admin_headers):
        payload = {"weight": 1, "subtotal": 100, "country": "US",
                   "address1": "1600 Amphitheatre Pkwy", "city": "Mountain View",
                   "state": "CA", "postal_code": "94043"}
        r = requests.post(f"{BASE_URL}/api/admin/shipping/test-rates", headers=admin_headers, json=payload, timeout=45)
        assert r.status_code == 200, r.text
        opts = r.json().get("options", [])
        assert opts, "no rate options returned"
        assert any(o.get("source") == "shippo" for o in opts), "no live shippo option present"


# ---- Public rate quote ----
class TestPublicRates:
    def test_rates_us(self, physical_item, customer_headers):
        r = requests.post(f"{BASE_URL}/api/shipping/rates", timeout=45, headers=customer_headers,
                          json={"items": [{"physical_item_id": physical_item["id"], "quantity": 1}],
                                "ship_to": {"country": "US", "state": "NY", "postal_code": "10118", "city": "New York", "address1": "350 5th Ave"}})
        assert r.status_code == 200, r.text
        d = r.json()
        opts = d.get("options", [])
        assert opts
        live = [o for o in opts if o.get("source") == "shippo"]
        assert live, "expected at least one live shippo rate"


# ---- Full order → shipment → buy label → label pdf → duplicate 409 ----
class TestOrderShippingFlow:
    def test_full_flow(self, customer_headers, admin_headers, physical_item):
        # 1) Get rates and grab a live shippo option
        rate_r = requests.post(f"{BASE_URL}/api/shipping/rates", timeout=45, headers=customer_headers,
                               json={"items": [{"physical_item_id": physical_item["id"], "quantity": 1}],
                                     "ship_to": {"country": "US", "state": "NY",
                                                 "postal_code": "10118", "city": "New York",
                                                 "address1": "350 5th Ave"}})
        assert rate_r.status_code == 200
        options = rate_r.json()["options"]
        live_opt = next((o for o in options if o.get("source") == "shippo"), None)
        assert live_opt, "no live shippo rate"

        # 2) Create order (manual payment method) — wait 30s to avoid dedup guard
        time.sleep(31)
        order_payload = {
            "items": [{
                "product_id": physical_item["id"], "product_name": physical_item["name"],
                "price": physical_item["price"], "account_type": "physical",
                "item_type": "physical", "quantity": 1, "term_months": 0,
            }],
            "total": physical_item["price"] + live_opt["price"],
            "shipping_address": SHIP_TO,
            "shipping_method_id": live_opt["method_id"],
        }
        order_r = requests.post(f"{BASE_URL}/api/orders", headers=customer_headers, json=order_payload, timeout=30)
        assert order_r.status_code in (200, 201), order_r.text
        order_id = order_r.json().get("order_id") or order_r.json().get("id")
        assert order_id
        pytest.order_id = order_id
        pytest.chosen_price = live_opt["price"]

        # 3) Admin mark-paid
        mp = requests.post(f"{BASE_URL}/api/admin/orders/{order_id}/mark-paid",
                           headers=admin_headers, timeout=30)
        assert mp.status_code in (200, 204), mp.text

        # 4) GET admin shipments — new pending shipment for this order
        sh = requests.get(f"{BASE_URL}/api/admin/shipments", headers=admin_headers, timeout=15)
        assert sh.status_code == 200
        shipments = sh.json() if isinstance(sh.json(), list) else sh.json().get("items", [])
        mine = [s for s in shipments if s.get("order_id") == order_id]
        assert mine, "no shipment created for order"
        shp = mine[0]
        pytest.shipment_id = shp["id"]
        assert shp.get("status") in ("pending", "processing")
        assert abs(float(shp.get("shipping_cost", 0)) - live_opt["price"]) < 0.02

        # 5) Get shippo rates for this shipment
        rr = requests.post(f"{BASE_URL}/api/admin/shipments/{shp['id']}/shippo-rates",
                           headers=admin_headers, timeout=45)
        assert rr.status_code == 200, rr.text
        srates = rr.json().get("options", [])
        assert srates
        pick = srates[0]
        rate_id = pick.get("shippo", {}).get("rate_id") or pick.get("rate_id")
        assert rate_id, f"no rate_id in {pick}"

        # 6) Buy label
        bl = requests.post(f"{BASE_URL}/api/admin/shipments/{shp['id']}/buy-label",
                           headers=admin_headers,
                           json={"rate_id": rate_id}, timeout=60)
        assert bl.status_code == 200, bl.text
        body = bl.json()
        assert body.get("tracking_number")
        pytest.tracking = body["tracking_number"]

        # 7) Duplicate buy-label → 409
        dup = requests.post(f"{BASE_URL}/api/admin/shipments/{shp['id']}/buy-label",
                            headers=admin_headers,
                            json={"rate_id": rate_id}, timeout=30)
        assert dup.status_code == 409, f"expected 409 got {dup.status_code}: {dup.text}"

        # 8) Label PDF
        pdf = requests.get(f"{BASE_URL}/api/admin/shipments/{shp['id']}/label",
                           headers=admin_headers, timeout=30)
        assert pdf.status_code == 200
        assert pdf.headers.get("content-type", "").startswith("application/pdf")
        assert len(pdf.content) > 1000


# ---- Webhook auth ----
class TestWebhook:
    def test_bad_token_401(self):
        r = requests.post(f"{BASE_URL}/api/webhooks/shippo?token=bad",
                          json={"event": "track_updated", "data": {}}, timeout=15)
        assert r.status_code == 401
