"""Mocked-panel tests for the GhostAPK pin flow in XtreamUIService.create_subscriber_via_form"""
import json
from unittest.mock import MagicMock
from xtreamui_service import XtreamUIService


def _resp(status=200, text="", headers=None, cookies=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = headers or {}
    r.json = lambda: json.loads(text)
    return r


def _service(connected: bool, gapk_code: str = "482913"):
    svc = XtreamUIService("https://panel.test", "reseller1", "pw")
    sess = MagicMock()
    sess.cookies = {"PHPSESSID": "abc"}
    checkbox = '<input type="checkbox" name="ghostapk_sync" value="1">' if connected else ""
    page = f'<form><select name="member_id"><option value="7">reseller1</option></select>{checkbox}</form>'
    calls = {"posts": [], "gets": []}

    def get(url, **kw):
        calls["gets"].append((url, kw.get("params")))
        if "api.php" in url:
            return _resp(200, json.dumps({"result": True, "username": "u", "password": "p", "pin": "", "gapk_code": gapk_code, "server": "x"}))
        return _resp(200, page)

    def post(url, **kw):
        calls["posts"].append((url, kw.get("data")))
        if "login.php" in url:
            return _resp(200, "")
        return _resp(302, "", headers={"Location": "user_reseller.php?id=555"})

    sess.get = get
    sess.post = post
    svc.session = sess
    return svc, calls


def test_connected_reseller_requests_pin_and_returns_code():
    svc, calls = _service(connected=True)
    result = svc.create_subscriber_via_form("u", "p", 52, [1, 2], customer_name="Test")
    assert result["success"] is True
    assert result["user_id"] == "555"
    assert result["ghostapk_code"] == "482913"
    form_post = [d for u, d in calls["posts"] if "user_reseller.php" in u][0]
    assert form_post["ghostapk_sync"] == "1"
    label_calls = [p for u, p in calls["gets"] if "api.php" in u]
    assert label_calls == [{"action": "get_label_data", "username": "u", "password": "p"}]


def test_not_connected_reseller_skips_ghostapk():
    svc, calls = _service(connected=False)
    result = svc.create_subscriber_via_form("u", "p", 52, [1], customer_name="Test")
    assert result["success"] is True
    assert result["ghostapk_code"] == ""
    form_post = [d for u, d in calls["posts"] if "user_reseller.php" in u][0]
    assert "ghostapk_sync" not in form_post
    assert not [u for u, _ in calls["gets"] if "api.php" in u]


def test_connected_but_panel_returned_no_code():
    svc, _ = _service(connected=True, gapk_code="")
    result = svc.create_subscriber_via_form("u", "p", 52, [1])
    assert result["success"] is True
    assert result["ghostapk_code"] == ""


def test_sync_all_maps_panel_response():
    svc, _ = _service(connected=True)
    svc.session.get = lambda url, **kw: _resp(200, json.dumps({"result": True, "created": 3, "updated": 1, "codes_generated": 4, "errors": []}))
    out = svc.ghostapk_sync_all()
    assert out == {"success": True, "created": 3, "updated": 1, "codes_generated": 4, "errors": []}
    svc.session.get = lambda url, **kw: _resp(200, json.dumps({"result": False, "message": "Not connected"}))
    assert svc.ghostapk_sync_all() == {"success": False, "error": "Not connected"}
