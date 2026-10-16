// CMTV local addition 2026-10-16 (owner, batch 3): tapping an order on My Orders (pages/OrdersPage.js) opens its receipt:
// what was bought (plain names), the money (subtotal, discount, credit used, total), how and when it was paid, and what
// it did ("Renewed your line abc123, now runs until Nov 9, 2026"). Receipts only: no PDF invoices (owner's decision).
import React from 'react';
import { Link } from 'react-router-dom';
import { plainItemName } from './orderNames';
import { paymentLabel } from './paymentMethod';

const money = (n) => `$${Number(n || 0).toFixed(2)}`;
const day = (d) => (d ? new Date(String(d).endsWith('Z') || String(d).includes('+') ? d : `${d}Z`)
  .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');

function didWhat(item, servicesById, paid) {
  if (!paid) return null;
  if (item.gift) return item.gift.to_email ? `Gift card for ${item.gift.to_email}` : 'Gift card code emailed to you';
  if (item.account_type === 'reseller') return item.credits ? `${item.credits} credits added` : 'Reseller credits added';
  const svc = item.renewal_service_id ? servicesById[item.renewal_service_id] : null;
  const login = svc?.xtream_username || svc?.username;
  if (item.action_type === 'extend' || item.action_type === 'upgrade') {
    const until = svc?.expiry_date ? `, now runs until ${day(svc.expiry_date)}` : '';
    return item.action_type === 'upgrade' ? `More devices on your line${login ? ` ${login}` : ''}` : `Renewed your line${login ? ` ${login}` : ''}${until}`;
  }
  if (Number(item.price) === 0 && /trial/i.test(item.product_name || '')) return 'Free trial started';
  return 'New service set up: your login was emailed to you and is on your dashboard';
}

export default function OrderReceipt({ order, productsById, services }) {
  const servicesById = Object.fromEntries((services || []).map((s) => [s.id, s]));
  const paid = order.status === 'paid';
  const discount = Number(order.discount_amount || 0);
  const credit = Number(order.credits_used || 0);
  const subtotal = Number(order.subtotal || 0) || (order.items || []).reduce((n, i) => n + Number(i.price || 0) * (i.quantity || 1), 0);
  const row = 'flex justify-between gap-3 py-1';
  return (
    <div className="text-sm text-gray-700 dark:text-gray-300 space-y-3" data-testid="order-receipt">
      <div>
        <p className="font-semibold text-gray-900 dark:text-white">Receipt · order #{String(order.id).slice(0, 10).toUpperCase()}</p>
        <p className="text-gray-500 dark:text-gray-400">Ordered {day(order.created_at)}{paid && order.paid_at ? ` · paid ${day(order.paid_at)}` : ''}</p>
      </div>
      <div className="divide-y divide-gray-200 dark:divide-gray-700">
        {(order.items || []).map((item, i) => {
          const what = didWhat(item, servicesById, paid);
          return (
            <div key={i} className="py-2">
              <div className={row}><span className="font-medium text-gray-900 dark:text-white">{plainItemName(item, productsById)}</span>
                <span>{money(Number(item.price || 0) * (item.quantity || 1))}</span></div>
              {what && <p className="text-xs text-gray-500 dark:text-gray-400">{what}</p>}
            </div>
          );
        })}
      </div>
      <div className="border-t border-gray-200 dark:border-gray-700 pt-2">
        {(discount > 0 || credit > 0) && <div className={row}><span>Subtotal</span><span>{money(subtotal)}</span></div>}
        {discount > 0 && <div className={row}><span>Discount{order.coupon_code ? ` (${order.coupon_code})` : /tier/i.test(order.discount_source || '') ? ' (member discount)' : ''}</span>
          <span>-{money(discount)}</span></div>}
        {credit > 0 && <div className={row}><span>Account credit used</span><span>-{money(credit)}</span></div>}
        <div className={`${row} font-semibold text-gray-900 dark:text-white`}><span>{paid ? 'Total paid' : 'Total'}</span><span>{money(order.total)}</span></div>
        {paid && <div className={row}><span>Paid with</span><span>{Number(order.total) > 0 ? paymentLabel(order) : credit > 0 ? 'Account credit' : 'Free'}</span></div>}
      </div>
      {!paid && order.status === 'pending' && Number(order.total) > 0 && (
        <Link to={`/pay/${order.id}`} className="inline-block font-semibold text-blue-600 hover:underline">Complete payment →</Link>
      )}
      {order.status === 'cancelled' && <p className="text-gray-500 dark:text-gray-400">This order was cancelled. Nothing was charged for it.</p>}
    </div>
  );
}
