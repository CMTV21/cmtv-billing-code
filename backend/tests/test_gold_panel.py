"""Gold Panel integration backend tests (READ-only / free calls only).

STRICT: Do NOT create or renew any Gold device (spends credits).
Allowed: test, packages, refresh, suspend/activate, service suspend/unsuspend, list, negative.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback for tests: read frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"
CUSTOMER_EMAIL = "shippo.customer@example.com"
CUSTOMER_PASSWORD = "Customer123!"
GOLD_IMPORTED_USERNAME = "ff432cdad9"
GOLD_SERVICE_USERNAME = "ead79f775a"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def customer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"customer login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def customer_headers(customer_token):
    return {"Authorization": f"Bearer {customer_token}"}


# ---------- Gold admin free endpoints ----------

def test_gold_test_connection(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/gold/test", params={"panel_index": 0},
                      headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True
    msg = body.get("message", "")
    assert "rknox015" in msg, f"unexpected message: {msg}"
    assert "Balance" in msg
    data = body.get("data") or {}
    assert isinstance(data.get("credits"), (int, float)), f"credits not numeric: {data}"


def test_gold_packages(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/gold/packages", params={"panel_index": 0},
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    pkgs = body.get("packages") or body.get("data") or body
    if isinstance(pkgs, dict) and "packages" in pkgs:
        pkgs = pkgs["packages"]
    assert isinstance(pkgs, list), f"packages not list: {type(pkgs)} {body}"
    assert len(pkgs) == 36, f"expected 36 packages got {len(pkgs)}"
    # Each package is a single (bouquet × term) combo: id "packId:sub" with duration=sub months
    subs_seen = set()
    for p in pkgs:
        pid = p.get("id", "")
        assert ":" in pid, f"bad id: {p}"
        assert p.get("duration_unit") == "months"
        assert p.get("duration") == p.get("sub")
        subs_seen.add(p.get("sub"))
    assert subs_seen == {1, 3, 6, 12}, f"terms found: {subs_seen}"
    # 9 bouquets × 4 terms
    pack_ids = {p.get("pack_id") for p in pkgs}
    assert len(pack_ids) == 9, f"expected 9 bouquets, got {len(pack_ids)}"


def test_gold_refresh_users(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/gold/refresh-users", params={"panel_index": 0},
                      headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "synced" in body
    assert "updated" in body
    assert body.get("total", 0) >= 1
    assert "errors" in body


def test_panel_names_includes_gold(admin_headers):
    r = requests.get(f"{BASE_URL}/api/panels/names", headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    gp = body.get("gold_panels", [])
    assert any(p.get("index") == 0 and p.get("name") == "Gold Panel" for p in gp), f"gold_panels={gp}"


def test_bouquets_gold_empty(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/bouquets",
                     params={"panel_id": 0, "panel_type": "gold"},
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json() == []


# ---------- Negative ----------

def test_gold_test_bad_index(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/gold/test", params={"panel_index": 5},
                      headers=admin_headers, timeout=30)
    assert r.status_code == 400, r.text
    assert "Panel index 5 not found" in r.text


# ---------- Imported user actions on existing device ----------

def _find_gold_imported(admin_headers, username):
    r = requests.get(f"{BASE_URL}/api/admin/imported-users",
                     params={"panel_type": "gold", "search": username},
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    users = body if isinstance(body, list) else body.get("users") or body.get("items") or body.get("data") or []
    for u in users:
        if u.get("username") == username:
            return u
    # Fallback: fetch all gold and search
    r = requests.get(f"{BASE_URL}/api/admin/imported-users",
                     params={"panel_type": "gold"},
                     headers=admin_headers, timeout=30)
    body = r.json()
    users = body if isinstance(body, list) else body.get("users") or body.get("items") or body.get("data") or []
    for u in users:
        if u.get("username") == username:
            return u
    return None


def test_gold_imported_suspend_activate(admin_headers):
    user = _find_gold_imported(admin_headers, GOLD_IMPORTED_USERNAME)
    assert user is not None, f"gold imported user {GOLD_IMPORTED_USERNAME} not found"
    uid = user.get("id") or user.get("_id")
    assert uid, f"no id on user: {user}"

    r = requests.post(f"{BASE_URL}/api/admin/imported-users/{uid}/suspend",
                      headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Device disabled successfully on Gold Panel" in body.get("message", ""), body

    time.sleep(1)
    r2 = requests.post(f"{BASE_URL}/api/admin/imported-users/{uid}/activate",
                       headers=admin_headers, timeout=30)
    assert r2.status_code == 200, r2.text
    assert "Device enabled successfully on Gold Panel" in r2.json().get("message", ""), r2.text

    # Bulk suspend then activate
    rb = requests.post(f"{BASE_URL}/api/admin/imported-users/bulk-action",
                       json={"action": "suspend", "user_ids": [uid]},
                       headers=admin_headers, timeout=60)
    assert rb.status_code == 200, rb.text
    bbody = rb.json()
    assert bbody.get("success_count", bbody.get("success", 0)) == 1, bbody

    time.sleep(1)
    rb2 = requests.post(f"{BASE_URL}/api/admin/imported-users/bulk-action",
                        json={"action": "activate", "user_ids": [uid]},
                        headers=admin_headers, timeout=60)
    assert rb2.status_code == 200, rb2.text
    bbody2 = rb2.json()
    assert bbody2.get("success_count", bbody2.get("success", 0)) == 1, bbody2


# ---------- Service (customer) suspend/unsuspend ----------

def _find_customer_gold_service(customer_headers, username):
    r = requests.get(f"{BASE_URL}/api/services", headers=customer_headers, timeout=30)
    assert r.status_code == 200, r.text
    items = r.json()
    if isinstance(items, dict):
        items = items.get("services") or items.get("data") or items.get("items") or []
    for s in items:
        if s.get("username") == username or s.get("m3u_username") == username:
            return s
    return None


def test_gold_service_suspend_unsuspend(admin_headers, customer_headers):
    svc = _find_customer_gold_service(customer_headers, GOLD_SERVICE_USERNAME)
    assert svc is not None, f"gold service {GOLD_SERVICE_USERNAME} not found on customer"
    sid = svc.get("id") or svc.get("_id")
    assert sid, f"no id on service: {svc}"

    r = requests.post(f"{BASE_URL}/api/admin/services/{sid}/suspend",
                      headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    assert "Service suspended successfully" in r.json().get("message", ""), r.text

    time.sleep(1)
    r2 = requests.post(f"{BASE_URL}/api/admin/services/{sid}/unsuspend",
                       headers=admin_headers, timeout=30)
    assert r2.status_code == 200, r2.text
    assert "Service unsuspended successfully" in r2.json().get("message", ""), r2.text


def test_customer_sees_gold_service_with_m3u(customer_headers):
    svc = _find_customer_gold_service(customer_headers, GOLD_SERVICE_USERNAME)
    assert svc is not None
    # M3U URL check
    m3u = svc.get("gold_m3u_url") or svc.get("m3u_url") or svc.get("playlist_url") or ""
    assert "half60642.cdngold.me" in m3u, f"m3u url unexpected: {m3u}"
    assert f"username={GOLD_SERVICE_USERNAME}" in m3u
    assert "password=7929a6aeb5" in m3u
    assert "type=m3u_plus" in m3u
