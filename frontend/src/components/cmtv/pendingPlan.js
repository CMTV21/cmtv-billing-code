// CMTV local addition 2026-09-28: a plan picked while signed out (a storefront card, or cmtv.info's
// https://billing.cmtv.info/?add=<product id>) is remembered for 2 hours in this browser, so after signing in (or
// signing up, then in) the storefront puts it in the cart and opens checkout. Used by CmtvHomePage + CmtvDashboardPage.
const KEY = 'cmtv-pending-add';
const TTL = 2 * 60 * 60 * 1000;

export function rememberPlan(id) {
  try { localStorage.setItem(KEY, JSON.stringify({ id: String(id), at: Date.now() })); } catch { /* private mode */ }
}

export function pendingPlan() {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || 'null');
    return p && p.id && Date.now() - p.at < TTL ? p.id : null;
  } catch { return null; }
}

export function forgetPlan() {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}
