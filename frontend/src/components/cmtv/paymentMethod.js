// CMTV local addition 2026-09-25: how an order was paid (backend: cmtv_payments.py).
// Orders from before this was recorded say "manual" for every non-PayPal payment; they show as "Manual / e-Transfer".
import React from 'react';

export const PAYMENT_LABELS = {
  manual: 'Manual', emt: 'e-Transfer', zelle: 'Zelle', cashapp: 'Cash App', venmo: 'Venmo', wise: 'Wise',
  paypal: 'PayPal', paypal_autorenew: 'PayPal (auto-renew)', stripe: 'Stripe', square: 'Square', helcim: 'Helcim',
  tagadapay: 'TagadaPay', ghostpay: 'GhostPay', blockonomics: 'Bitcoin', manual_admin: 'Added by admin',
  credits: 'Account credit', free: 'Free', cash: 'Cash', other: 'Other', test: 'Test (no money)', // 2026-10-05
};
// Choices when marking an order paid by hand (same list as cmtv_payments.ADMIN)
export const ADMIN_PAID_BY = ['emt', 'manual', 'cash', 'zelle', 'cashapp', 'venmo', 'wise', 'paypal', 'ghostpay', 'other', 'test'];

export function paymentLabel(order) {
  const m = String(order?.payment_method || '').toLowerCase();
  if (m === 'manual' && !order?.payment_method_recorded) return 'Manual / e-Transfer';
  return PAYMENT_LABELS[m] || (m ? m.replace(/_/g, ' ') : 'Unknown');
}

const TONE = {
  emt: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
  paypal: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200',
  paypal_autorenew: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200',
  ghostpay: 'bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200',
  manual: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
};

export function PaymentBadge({ order }) {
  const m = String(order?.payment_method || '').toLowerCase();
  const legacy = m === 'manual' && !order?.payment_method_recorded;
  const tone = legacy ? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300' : (TONE[m] || 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200');
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-semibold whitespace-nowrap ${tone}`}
      title={legacy ? 'Placed before billing recorded the payment option (every non-PayPal order said "manual")' : undefined}>
      {paymentLabel(order)}
    </span>
  );
}
