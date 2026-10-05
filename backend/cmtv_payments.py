"""How an order was paid (CMTV local addition 2026-09-25).

Before this, every non-PayPal order was saved as payment_method "manual" (checkout never said which option the customer
picked). Now checkout sends it, the server checks it against the list below, and new orders carry
payment_method_recorded = True. Older "manual" orders are shown as "Manual / e-Transfer (not recorded)".
"""

LABELS = {
    "manual": "Manual",
    "emt": "e-Transfer",
    "zelle": "Zelle",
    "cashapp": "Cash App",
    "venmo": "Venmo",
    "wise": "Wise",
    "paypal": "PayPal",
    "paypal_autorenew": "PayPal (auto-renew)",
    "stripe": "Stripe",
    "square": "Square",
    "helcim": "Helcim",
    "tagadapay": "TagadaPay",
    "ghostpay": "GhostPay",
    "blockonomics": "Bitcoin",
    "manual_admin": "Added by admin",
    "credits": "Account credit",
    "free": "Free",
    "cash": "Cash",
    "other": "Other",
    "test": "Test (no money)",   # 2026-10-05: owner's test orders, kept out of Finances
}
# What checkout may send
CHECKOUT = {"manual", "emt", "zelle", "cashapp", "venmo", "wise", "paypal", "stripe", "square", "helcim",
            "tagadapay", "ghostpay", "blockonomics"}
# What the admin may choose when marking an order paid by hand
ADMIN = {"emt", "manual", "cash", "zelle", "cashapp", "venmo", "wise", "paypal", "ghostpay", "other", "test"}


def label(method, recorded=True):
    m = str(method or "").lower()
    if m == "manual" and not recorded:
        return "Manual / e-Transfer (not recorded)"
    return LABELS.get(m, m.replace("_", " ").title() if m else "Unknown")


def order_label(order):
    return label(order.get("payment_method"), bool(order.get("payment_method_recorded")))
