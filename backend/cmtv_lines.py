"""One rule for "is this a trial or a paid line?" (CMTV local addition 2026-10-08; spec "trial-named paid lines").
Billing keeps is_trial / "Trial" in the name when a trial line is later paid for and extended (e.g. "Imperium 48 hour Trial"
running to 2027). So a line marked as a trial (is_trial on the service or its product, or "trial" in either name) counts as
PAID when it runs longer than TRIAL_MAX: from created_at to its end, or from now to its end. The longest real trial is 7 days.
Same rule cmtv_campaigns._counts used first. Used by: cmtv_campaigns, cmtv_survey, cmtv_lapsed_winback, cmtv_reviews,
cmtv_trial_nurture, cmtv_customers_list, cmtv_admin_overview. Reseller / demo checks stay in each module."""
from datetime import datetime, timedelta

TRIAL_MAX = timedelta(days=8)


def _dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "").replace(" ", "T")[:19])
        except ValueError:
            return None
    return None


def trial_marked(s, product=None):
    """Flagged or named as a trial (the service or its product), whatever its length."""
    p = product or {}
    return bool(s.get("is_trial") or p.get("is_trial")) or "trial" in str(s.get("product_name") or "").lower() \
        or "trial" in str(p.get("name") or "").lower()


def is_trial_line(s, now=None, product=None):
    """A real trial: marked as one and no longer than TRIAL_MAX."""
    if not trial_marked(s, product):
        return False
    now = now or datetime.utcnow()
    exp, made = _dt(s.get("expiry_date")), _dt(s.get("created_at"))
    return not (exp and ((made and exp - made > TRIAL_MAX) or exp - now > TRIAL_MAX))


def is_paid_line(s, now=None, product=None):
    """Not a real trial (a normal plan, or a trial-named line that was paid for and extended)."""
    return not is_trial_line(s, now, product)
