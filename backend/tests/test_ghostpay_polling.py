"""GhostPay settlement + poller tests (run against the live backend module with a mocked GhostPay API)."""
import asyncio
import os
import sys
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def pending_order():
    user_id = ObjectId()
    order_id = ObjectId()
    invoice_id = f"test-{uuid.uuid4()}"
    _run(server.users_collection.insert_one({"_id": user_id, "email": f"gp-{uuid.uuid4().hex[:6]}@test.local", "name": "GP Test", "role": "customer"}))
    _run(server.orders_collection.insert_one({"_id": order_id, "user_id": str(user_id), "items": [], "total": 5.0, "status": "pending", "created_at": datetime.utcnow()}))
    _run(server.db.payment_transactions.insert_one({"order_id": str(order_id), "user_id": str(user_id), "gateway": "ghostpay",
                                                    "invoice_id": invoice_id, "payment_status": "pending", "created_at": datetime.utcnow()}))
    yield str(order_id), invoice_id
    _run(server.users_collection.delete_one({"_id": user_id}))
    _run(server.orders_collection.delete_one({"_id": order_id}))
    _run(server.db.payment_transactions.delete_many({"invoice_id": invoice_id}))


def test_poller_settles_paid_invoice_and_provisions(pending_order):
    order_id, invoice_id = pending_order
    paid = {"success": True, "status": "PAID", "crypto": "BTC", "amount_received": 0.0001, "transactions": [{"txid": "abc"}]}
    with patch("ghostpay_service.GhostPayService.check_invoice", new=AsyncMock(return_value=paid)), \
         patch.object(server, "provision_order_services", new=AsyncMock()) as prov:
        _run(server.poll_pending_ghostpay_payments())
        order = _run(server.orders_collection.find_one({"_id": ObjectId(order_id)}))
        tx = _run(server.db.payment_transactions.find_one({"invoice_id": invoice_id}))
        assert order["status"] == "paid"
        assert order["payment_method"] == "ghostpay"
        assert order["payment_id"] == invoice_id
        assert tx["payment_status"] == "paid" and tx["settled_via"] == "poll"
        prov.assert_awaited_once()
        assert prov.await_args.args[0] == order_id

        # Second run must be a no-op (idempotent: order already paid, tx no longer pending)
        _run(server.poll_pending_ghostpay_payments())
        prov.assert_awaited_once()


def test_poller_leaves_unpaid_invoice_pending(pending_order):
    order_id, invoice_id = pending_order
    unpaid = {"success": True, "status": "UNPAID", "amount_received": 0}
    with patch("ghostpay_service.GhostPayService.check_invoice", new=AsyncMock(return_value=unpaid)), \
         patch.object(server, "provision_order_services", new=AsyncMock()) as prov:
        _run(server.poll_pending_ghostpay_payments())
        order = _run(server.orders_collection.find_one({"_id": ObjectId(order_id)}))
        assert order["status"] == "pending"
        prov.assert_not_awaited()


def test_poller_marks_expired(pending_order):
    order_id, invoice_id = pending_order
    expired = {"success": True, "status": "EXPIRED"}
    with patch("ghostpay_service.GhostPayService.check_invoice", new=AsyncMock(return_value=expired)):
        _run(server.poll_pending_ghostpay_payments())
        tx = _run(server.db.payment_transactions.find_one({"invoice_id": invoice_id}))
        assert tx["payment_status"] == "expired"


def test_settle_is_idempotent_when_webhook_and_poll_race(pending_order):
    order_id, invoice_id = pending_order
    with patch.object(server, "provision_order_services", new=AsyncMock()) as prov:
        first = _run(server.settle_ghostpay_payment(order_id, invoice_id, {"crypto": "BTC"}, source="webhook"))
        second = _run(server.settle_ghostpay_payment(order_id, invoice_id, {"crypto": "BTC"}, source="poll"))
        assert first is True
        assert second is False  # already paid, services check prevents double provisioning
        prov.assert_awaited_once()
