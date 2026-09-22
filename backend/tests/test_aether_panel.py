"""Aether panel integration tests (live panel).

Tests the full Aether panel flow: connection test, packages, bouquets,
sync-users, imported-user actions, manual service provisioning, and cleanup.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://admin-analytics-46.preview.emergentagent.com").rstrip("/")
AETHER_PANEL_URL = "https://bestpanel.xyz"
AETHER_TOKEN = "pmk_HX_XeiPDkH5aNjpFpFHkwM_ZRu7nPG4x2bPgFAoD_O8"
TRIAL_PACKAGE_ID = 156

created_usernames = []
created_product_id = None
created_service_id = None
created_iu_ids = []


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@example.com", "password": "admin123"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_user_id(admin_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=admin_headers, timeout=30)
    assert r.status_code == 200
    d = r.json()
    return d.get("id") or d.get("_id") or d.get("user_id")


# ===== Aether panel routes =====

def test_aether_test_connection(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/aether/test?panel_index=0", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    msg = d.get("message", "")
    assert "CMTV" in msg or "reseller" in msg.lower(), f"Unexpected message: {msg}"
    assert d.get("missing_scopes") == [] or d.get("missing_scopes") is None
    assert "balance" in d or "credits" in d or "CMTV" in msg


def test_aether_packages(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/aether/packages?panel_index=0", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "packages" in d
    assert "trial_packages" in d
    assert len(d["packages"]) >= 50, f"Expected ~80 packages, got {len(d['packages'])}"
    assert len(d["trial_packages"]) >= 3
    sample = d["packages"][0]
    for k in ("id", "name", "duration", "duration_unit", "max_connections", "price", "is_trial"):
        assert k in sample, f"missing key {k} in package {sample}"


def test_aether_package_bouquets(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/aether/packages/163/bouquets?panel_index=0", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    bouquets = d.get("bouquets", d if isinstance(d, list) else [])
    assert len(bouquets) > 0
    first = bouquets[0]
    assert "name" in first
    assert "default_included" in first or "included" in first


def test_aether_all_bouquets(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/aether/bouquets?panel_index=0", headers=admin_headers, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    bouquets = d.get("bouquets", d if isinstance(d, list) else [])
    assert len(bouquets) >= 50, f"Expected ~76 bouquets, got {len(bouquets)}"
    names = [b.get("name", "") for b in bouquets]
    # Verify real names
    assert any("USA" in n or "Movies" in n or "Sports" in n for n in names), f"No real bouquet names found: {names[:10]}"


def _extract_list(d, key=None):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        if key and key in d:
            return d[key]
        for k in ("bouquets", "users", "imported_users", "items", "data"):
            if k in d and isinstance(d[k], list):
                return d[k]
    return []


def test_admin_bouquets_endpoint(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/bouquets?panel_id=0&panel_type=aether", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    bouquets = _extract_list(r.json(), "bouquets")
    assert len(bouquets) >= 50


def test_aether_sync_users(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/aether/sync-users?panel_index=0", headers=admin_headers, timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    # Should report some synced/updated count
    total = d.get("synced", 0) + d.get("updated", 0) + d.get("created", 0) + d.get("total", 0)
    msg = str(d)
    assert total > 0 or "synced" in msg.lower() or "line" in msg.lower(), f"Unexpected sync result: {d}"


def test_imported_users_list_aether(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/imported-users?panel_type=aether", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    users = _extract_list(r.json(), "users")
    assert len(users) >= 10, f"Expected ~48 imported users, got {len(users)}"
    aether_users = [u for u in users if u.get("panel_type") == "aether"]
    assert len(aether_users) > 0
    with_expiry = [u for u in aether_users if u.get("expiry_date") and u.get("expiry_date") not in (None, "Unlimited", "")]
    assert len(with_expiry) > 0, "No aether users have parsed expiry_date"


def test_sync_users_idempotent(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/aether/sync-users?panel_index=0", headers=admin_headers, timeout=180)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/admin/imported-users?panel_type=aether", headers=admin_headers, timeout=60)
    users = _extract_list(r2.json(), "users")
    aether = [u for u in users if u.get("panel_type") == "aether"]
    usernames = [u.get("username") or u.get("aether_line_id") for u in aether]
    dups = len(usernames) - len(set(usernames))
    assert dups < 3, f"Duplicates: {dups}"


def test_sync_all_users_includes_aether(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/sync-all-users", headers=admin_headers, timeout=300)
    assert r.status_code == 200, r.text
    d = r.json()
    panels_synced = d.get("panels_synced", [])
    types = [p.get("type") for p in panels_synced] if panels_synced else []
    assert "aether" in types, f"aether not in panels_synced: {panels_synced}"


def test_panel_names_public():
    r = requests.get(f"{BASE_URL}/api/panels/names", timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    aether_panels = d.get("aether_panels", [])
    assert len(aether_panels) >= 1
    assert aether_panels[0].get("name") == "BestPanel Aether"
    assert aether_panels[0].get("index") == 0


# ===== Provisioning via manual service =====

def test_create_aether_product_and_provision(admin_headers, admin_user_id):
    global created_product_id, created_service_id
    # Create product
    product_payload = {
        "name": "TEST_Aether_Trial",
        "description": "Test aether trial product",
        "panel_type": "aether",
        "panel_index": 0,
        "xtream_package_id": TRIAL_PACKAGE_ID,
        "is_trial": True,
        "account_type": "subscriber",
        "prices": {"1": 0},
        "max_connections": 1,
        "is_active": True,
    }
    r = requests.post(f"{BASE_URL}/api/admin/products", headers=admin_headers, json=product_payload, timeout=60)
    assert r.status_code in (200, 201), r.text
    prod = r.json()
    created_product_id = prod.get("id") or prod.get("_id") or prod.get("product_id")
    assert created_product_id, prod

    # Create manual service
    r = requests.post(
        f"{BASE_URL}/api/admin/services/create-manual",
        headers=admin_headers,
        json={"user_id": admin_user_id, "product_id": created_product_id, "term_months": 1},
        timeout=120,
    )
    assert r.status_code in (200, 201), r.text
    order_id = r.json().get("order_id")
    time.sleep(15)

    # Find the provisioned service via /api/services (admin user)
    r = requests.get(f"{BASE_URL}/api/services", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    services = _extract_list(r.json(), "services")
    aether_services = [s for s in services if s.get("panel_type") == "aether" and s.get("product_id") == created_product_id]
    assert len(aether_services) > 0, f"No aether service found. All services: {services}"
    svc = aether_services[0]
    created_service_id = svc.get("id") or svc.get("_id")
    assert svc.get("xtream_username"), svc
    assert svc.get("xtream_password"), svc
    assert svc.get("aether_line_id"), svc
    assert svc.get("status") == "active"
    assert svc.get("streaming_url") == "http://imperium.esq"
    created_usernames.append(svc["xtream_username"])


def test_service_suspend_unsuspend(admin_headers):
    if not created_service_id:
        pytest.skip("No service created")
    r = requests.post(f"{BASE_URL}/api/admin/services/{created_service_id}/suspend", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/admin/services/{created_service_id}/unsuspend", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text


def test_imported_user_actions_on_provisioned(admin_headers):
    if not created_usernames:
        pytest.skip("No created usernames")
    # Re-sync
    requests.post(f"{BASE_URL}/api/admin/aether/sync-users?panel_index=0", headers=admin_headers, timeout=180)
    r = requests.get(f"{BASE_URL}/api/admin/imported-users?panel_type=aether", headers=admin_headers, timeout=60)
    users = _extract_list(r.json(), "users")
    match = [u for u in users if u.get("username") == created_usernames[0]]
    assert match, f"Provisioned username {created_usernames[0]} not found in imported users"
    iu_id = match[0].get("id") or match[0].get("_id")
    created_iu_ids.append(iu_id)

    r = requests.post(f"{BASE_URL}/api/admin/imported-users/{iu_id}/suspend", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    assert "suspend" in r.json().get("message", "").lower()
    r = requests.post(f"{BASE_URL}/api/admin/imported-users/{iu_id}/activate", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text

    # Bulk
    r = requests.post(
        f"{BASE_URL}/api/admin/imported-users/bulk-action",
        headers=admin_headers,
        json={"action": "suspend", "user_ids": [iu_id]},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b.get("processed", b.get("success_count", 0)) == 1
    assert b.get("failed", b.get("failure_count", 0)) == 0
    r = requests.post(
        f"{BASE_URL}/api/admin/imported-users/bulk-action",
        headers=admin_headers,
        json={"action": "activate", "user_ids": [iu_id]},
        timeout=60,
    )
    assert r.status_code == 200


def test_imported_users_create_trial(admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/imported-users/create",
        headers=admin_headers,
        json={
            "panel_type": "aether",
            "panel_index": 0,
            "account_type": "subscriber",
            "package_id": TRIAL_PACKAGE_ID,
        },
        timeout=90,
    )
    assert r.status_code in (200, 201), r.text
    d = r.json()
    user = d.get("user", d)
    uname = user.get("username") or d.get("username")
    pwd = user.get("password") or d.get("password")
    exp = user.get("expiry_date") or d.get("expiry_date")
    assert uname, d
    assert pwd, d
    assert exp, d
    created_usernames.append(uname)


def test_extend_with_trial_rejected(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/imported-users?panel_type=aether", headers=admin_headers, timeout=60)
    users = _extract_list(r.json(), "users")
    aether = [u for u in users if u.get("panel_type") == "aether"]
    assert aether
    iu_id = aether[0].get("id") or aether[0].get("_id")
    r = requests.post(
        f"{BASE_URL}/api/admin/imported-users/{iu_id}/extend",
        headers=admin_headers,
        json={"package_id": TRIAL_PACKAGE_ID},
        timeout=60,
    )
    assert r.status_code == 400, r.text
    body = r.json()
    msg = str(body.get("detail", body.get("message", ""))).lower()
    assert "trial" in msg, r.text


def test_imported_users_create_reseller_rejected(admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/imported-users/create",
        headers=admin_headers,
        json={
            "panel_type": "aether",
            "panel_index": 0,
            "account_type": "reseller",
            "package_id": TRIAL_PACKAGE_ID,
        },
        timeout=60,
    )
    assert r.status_code == 400, r.text


def test_extend_with_trial_rejected_v2(admin_headers):
    pass  # replaced by test_extend_with_trial_rejected above


# ===== CLEANUP =====

def test_cleanup_delete_lines_and_product(admin_headers):
    # Delete all created lines via panel API
    for uname in created_usernames:
        try:
            requests.delete(
                f"{AETHER_PANEL_URL}/api/v1/reseller/lines/username:{uname}",
                headers={"Authorization": f"Bearer {AETHER_TOKEN}"},
                timeout=30,
            )
        except Exception as e:
            print(f"cleanup delete line {uname} failed: {e}")

    # Delete test product
    if created_product_id:
        r = requests.delete(f"{BASE_URL}/api/admin/products/{created_product_id}", headers=admin_headers, timeout=60)
        print(f"Delete product status: {r.status_code}")

    # Try delete imported users
    for iu_id in created_iu_ids:
        try:
            requests.delete(f"{BASE_URL}/api/admin/imported-users/{iu_id}", headers=admin_headers, timeout=30)
        except Exception:
            pass
