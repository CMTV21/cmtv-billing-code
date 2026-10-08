// CMTV local addition 2026-09-25: PayPal auto-renew on My Services and at checkout (backend: cmtv_autorenew.py)
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { PayPalScriptProvider, PayPalButtons } from '@paypal/react-paypal-js';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import api, { ordersAPI } from '../../api/api';

const firstPrice = (p) => {
  const [term, price] = Object.entries(p?.prices || {})[0] || ['1', 0];
  return { term: parseInt(term, 10) || 1, price: parseFloat(price) || 0 };
};
// 2026-09-28: auto-renew is 10% off (cfg.discount_percent); a lower referral-tier price wins (the server decides)
const arPrice = (price, pct, member = null) => {
  const ar = Math.round(price * (100 - (pct || 0))) / 100;
  return member != null ? Math.min(ar, Number(member)) : ar;
};
const every = (m) => (m === 1 ? 'every month' : m === 12 ? 'every year' : `every ${m} months`);
const errText = (e, fallback) => e?.response?.data?.detail || fallback;

function useAutoRenewConfig() {
  return useQuery({
    queryKey: ['cmtv-autorenew-config'],
    queryFn: async () => (await api.get('/api/cmtv/autorenew/config')).data,
    staleTime: 5 * 60 * 1000,
  });
}

// ---------------- My Services: the switch on each service ----------------
export function AutoRenewControl({ service, products }) {
  const { data: cfg } = useAutoRenewConfig();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const product = (products || []).find((p) => p.id === service.product_id);
  const ar = service.auto_renew || {};
  const on = ar.status === 'ACTIVE';
  const { term, price } = firstPrice(product);
  const renewable = product && !product.is_trial && !product.is_bundle && product.account_type !== 'reseller' && price > 0;

  if (!cfg?.enabled || (!on && (!renewable || !['active', 'expired', 'suspended'].includes(service.status)))) return null;

  const turnOn = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/api/cmtv/autorenew/start', { service_id: service.id, origin: window.location.origin });
      window.location.href = data.approve_url;
    } catch (e) {
      toast.error(errText(e, "Couldn't start auto-renew. Please try again."));
      setBusy(false);
    }
  };
  const turnOff = async () => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/autorenew/cancel', { service_id: service.id });
      toast.success('Auto-renew is off. You will get reminders before it expires.');
      qc.invalidateQueries({ queryKey: ['services'] });
    } catch (e) {
      toast.error(errText(e, "Couldn't turn off auto-renew. Please try again."));
    }
    setBusy(false);
    setConfirmOff(false);
  };

  const box = 'mt-4 p-4 rounded-lg border text-sm flex flex-col sm:flex-row sm:items-center gap-3';
  if (on) {
    return (
      <div className={`${box} border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-900/20`}>
        <div className="flex-1 text-green-900 dark:text-green-200">
          <p className="font-semibold flex items-center gap-2"><RefreshCw className="w-4 h-4" /> Auto-renew is on</p>
          <p className="text-green-800 dark:text-green-300">
            Renews automatically with PayPal{ar.price ? `, ${cfg.currency} $${Number(ar.price).toFixed(2)} ${every(ar.term_months || term)}` : ''}.
            You won't need to do anything.
          </p>
        </div>
        {confirmOff ? (
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={turnOff} className="px-3 py-2 rounded-lg bg-red-600 text-white font-semibold disabled:opacity-50">Yes, turn off</button>
            <button type="button" onClick={() => setConfirmOff(false)} className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 dark:text-gray-200">Keep it on</button>
          </div>
        ) : (
          <button type="button" onClick={() => setConfirmOff(true)} className="px-3 py-2 rounded-lg border border-green-300 dark:border-green-700 text-green-900 dark:text-green-200 hover:bg-green-100 dark:hover:bg-green-900/40">Turn off</button>
        )}
      </div>
    );
  }
  const expiry = service.expiry_date ? new Date(service.expiry_date) : null;
  const firstCharge = expiry && expiry > new Date() ? new Date(expiry.getTime() - 86400000).toLocaleDateString() : 'today';
  return (
    <div className={`${box} border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-900/20`}>
      <div className="flex-1 text-blue-900 dark:text-blue-200">
        <p className="font-semibold flex items-center gap-2"><RefreshCw className="w-4 h-4" /> Never miss a renewal{cfg.discount_percent ? `, and save ${cfg.discount_percent}%` : ''}</p>
        <p className="text-blue-800 dark:text-blue-300">
          Renew automatically with PayPal: {cfg.currency} ${arPrice(price, cfg.discount_percent).toFixed(2)} {every(term)}
          {cfg.discount_percent ? ` (${cfg.discount_percent}% off, or your member price if that's lower)` : ''}, first charge {firstCharge}. Turn it off any time.
          {ar.status === 'APPROVAL_PENDING' && ' (Your last attempt wasn\'t finished in PayPal.)'}
        </p>
      </div>
      <button type="button" disabled={busy} onClick={turnOn} className="px-4 py-2 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap">
        {busy ? 'Opening PayPal...' : 'Turn on auto-renew'}
      </button>
    </div>
  );
}

// ---------------- My Services: coming back from PayPal ----------------
export function AutoRenewReturn() {
  const qc = useQueryClient();
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get('autorenew');
    if (!mode) return;
    const clean = () => window.history.replaceState({}, '', window.location.pathname);
    if (mode === 'cancelled') { toast.info('Auto-renew was not turned on.'); clean(); return; }
    if (mode !== 'return') return;
    api.post('/api/cmtv/autorenew/confirm', { service_id: params.get('service_id'), subscription_id: params.get('subscription_id') })
      .then(({ data }) => {
        toast.success(data.status === 'ACTIVE' || data.status === 'APPROVED'
          ? 'Auto-renew is on. PayPal will renew this service for you.' : `PayPal says: ${data.status}`);
        qc.invalidateQueries({ queryKey: ['services'] });
      })
      .catch((e) => toast.error(errText(e, "Couldn't confirm auto-renew with PayPal.")))
      .finally(clean);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

// ---------------- Checkout: "Renew automatically" option for PayPal ----------------
// Shown only for a single, full-price plan (no coupon or credits). Otherwise the normal PayPal buttons show unchanged.
// memberPrice: the referral-tier price when the tier discount applies (2026-09-25); it renews at that price.
// 2026-09-28: the subscription is 10% off (or the member price if lower) from the first payment.
// The one cart item that can be bought on auto-renew, or null
const checkoutItem = (cfg, items, total, discounted, memberPrice) => {
  const item = items?.length === 1 ? items[0] : null;
  const ok = cfg?.enabled && item && item.account_type !== 'reseller' && Number(item.price) > 0
    && !discounted && memberPrice !== 0 && Math.abs(Number(total) - Number(item.price)) < 0.01 && !item.gift; // 2026-10-05: not gift cards
  return ok ? item : null;
};
const yearlySaving = (cfg, item, memberPrice) => (item && Number(item.term_months) === 12
  ? Math.round((Number(item.price) - arPrice(Number(item.price), cfg?.discount_percent, memberPrice)) * 100) / 100 : 0);

// 2026-10-08 (nobody used auto-renew; plan target 25%): on a yearly plan, say what it saves before a payment method is
// picked, so e-Transfer payers see it too. "Use PayPal" just selects PayPal; the tick box there stays unticked.
export function CheckoutAutoRenewHint({ items, total, discounted, memberPrice = null, paymentMethod, onPickPaypal }) {
  const { data: cfg } = useAutoRenewConfig();
  const item = checkoutItem(cfg, items, total, discounted, memberPrice);
  const save = yearlySaving(cfg, item, memberPrice);
  if (!item || save <= 0 || paymentMethod === 'paypal') return null;
  return (
    <div className="flex items-start gap-3 p-3 mb-4 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20">
      <RefreshCw className="w-5 h-5 mt-0.5 text-blue-600 dark:text-blue-300 shrink-0" aria-hidden="true" />
      <div className="text-sm text-blue-900 dark:text-blue-200 flex-1">
        <span className="font-semibold">Save ${save.toFixed(2)} every year with auto-renew</span><br />
        Pay with PayPal and tick <b>Renew automatically</b>: {cfg.currency} ${(Number(item.price) - save).toFixed(2)} a year instead
        of ${Number(item.price).toFixed(2)}, and you never get cut off. Turn it off any time in My Services.
      </div>
      <button type="button" onClick={onPickPaypal}
        className="shrink-0 px-3 py-2 rounded-lg text-sm font-semibold bg-blue-600 text-white hover:bg-blue-700">Use PayPal</button>
    </div>
  );
}

export function CheckoutAutoRenew({ items, total, discounted, memberPrice = null, clientId, onDone, onError, children }) {
  const { data: cfg } = useAutoRenewConfig();
  const [auto, setAuto] = useState(false);
  const [orderId, setOrderId] = useState(null);
  const item = checkoutItem(cfg, items, total, discounted, memberPrice);
  if (!item) return children;
  const save = yearlySaving(cfg, item, memberPrice);   // 2026-10-08: yearly plans say the dollar saving

  const ensureOrder = async () => {
    if (orderId) return orderId;
    const { data } = await ordersAPI.create({
      items: [{ product_id: item.product_id, product_name: item.product_name, term_months: item.term_months, price: item.price,
                account_type: item.account_type, action_type: item.action_type, renewal_service_id: item.renewal_service_id }],
      total, coupon_code: null, use_credits: 0, reseller_credentials: null, payment_method: 'paypal',
    });
    const id = data.order_id || data.id;
    setOrderId(id);
    return id;
  };

  return (
    <div className="space-y-3">
      <label className="flex items-start gap-3 p-3 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 cursor-pointer">
        <input type="checkbox" className="mt-1" checked={auto} onChange={(e) => setAuto(e.target.checked)} id="cmtv-autorenew" />
        <span className="text-sm text-blue-900 dark:text-blue-200">
          <span className="font-semibold">Renew automatically with PayPal{save > 0 ? ` and save $${save.toFixed(2)} every year`
            : cfg.discount_percent ? ` and save ${cfg.discount_percent}%` : ''}</span><br />
          {cfg.currency} ${arPrice(Number(item.price), cfg.discount_percent, memberPrice).toFixed(2)} {every(Number(item.term_months) || 1)}
          {memberPrice != null && Number(memberPrice) <= arPrice(Number(item.price), cfg.discount_percent) ? ' (your member price)'
            : cfg.discount_percent ? ` (${cfg.discount_percent}% off), starting today` : ''}. PayPal charges this price instead of the total above. Turn it off any time in My Services.
        </span>
      </label>
      {!auto ? children : (
        <PayPalScriptProvider key="cmtv-sub" options={{ 'client-id': clientId, vault: true, intent: 'subscription', 'data-namespace': 'paypalCmtvSub' }}>
          <PayPalButtons
            style={{ layout: 'vertical', color: 'blue', label: 'subscribe' }}
            createSubscription={async (data, actions) => {
              try {
                const id = await ensureOrder();
                const { data: p } = await api.post('/api/cmtv/autorenew/checkout-plan', { order_id: id });
                return actions.subscription.create({ plan_id: p.plan_id, custom_id: p.custom_id, application_context: { shipping_preference: 'NO_SHIPPING' } });
              } catch (e) {
                onError(errText(e, "Couldn't set up auto-renew. Untick it to pay once instead."));
                throw e;
              }
            }}
            onApprove={async (data) => {
              try {
                const { data: r } = await api.post('/api/cmtv/autorenew/checkout-approved', { order_id: orderId, subscription_id: data.subscriptionID });
                toast.success(r.status === 'paid' ? 'Payment successful! Your service is being set up, and it will renew automatically.'
                  : 'Subscribed! PayPal is finishing your first payment; your service will be ready in a few minutes.');
                onDone();
              } catch (e) {
                onError(errText(e, 'PayPal approved, but we could not confirm it. Please contact support.'));
              }
            }}
            onError={() => onError('PayPal auto-renew failed. Untick it to pay once instead.')}
          />
        </PayPalScriptProvider>
      )}
    </div>
  );
}
