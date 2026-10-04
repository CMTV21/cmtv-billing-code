// CMTV local addition 2026-10-04: Admin > Orders, refreshed for phones (backend cmtv_admin_orders.py). Tabs Needs action /
// Paid / Cancelled / All, search (customer, email, order #, line username, product), one card per order that opens to show
// what was bought (new line / extend which line / add-on, line-up, channels), the money breakdown, how it was paid, the
// lines it created and any provisioning problem, with the actions on the existing endpoints. The developer's page is at
// /admin/orders-classic.
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import { paymentLabel, PAYMENT_LABELS, ADMIN_PAID_BY } from '../../components/cmtv/paymentMethod';
import '../../components/cmtv/cmtv-orders.css';

const LINEUP = { no_adult: 'no adult', na: 'North America', full: 'Full' };
const money = (v) => `$${Number(v || 0).toFixed(2)}`;
const ago = (iso) => {
  if (!iso) return '';
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 60) return `${m}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  if (m < 1440 * 30) return `${Math.round(m / 1440)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};
const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '–');
const problem = (o) => o.status === 'paid' && ['failed', 'partial'].includes(o.provisioning_status) && !o.setup_resolved;
const needsAction = (o) => o.status === 'pending' || problem(o);
const isTrial = (o) => o.total === 0 && o.items.some((i) => /trial/i.test(i.name));

export default function AdminOrdersPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['cmtv-orders'], queryFn: async () => (await api.get('/api/cmtv/admin/orders/list')).data, refetchInterval: 60000 });
  const orders = data?.orders || [];
  const [tab, setTab] = useState(null);
  const [q, setQ] = useState('');
  const [hideTrials, setHideTrials] = useState(true);
  const [limit, setLimit] = useState(30);
  const [openId, setOpenId] = useState(null);

  const counts = useMemo(() => ({
    action: orders.filter(needsAction).length,
    paid: orders.filter((o) => o.status === 'paid').length,
    cancelled: orders.filter((o) => o.status === 'cancelled').length,
    all: orders.length,
  }), [orders]);
  const curTab = tab || (counts.action ? 'action' : 'paid');
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return orders.filter((o) => {
      if (s) {
        const hay = [o.number, o.id, o.customer.name, o.customer.email, o.customer.line, o.payment_id,
          ...o.items.map((i) => `${i.name} ${i.extends || ''}`), ...o.services.map((x) => x.username)].join(' ').toLowerCase();
        return hay.includes(s);
      }
      if (hideTrials && curTab !== 'action' && isTrial(o)) return false;
      if (curTab === 'action') return needsAction(o);
      if (curTab === 'all') return true;
      return o.status === curTab;
    });
  }, [orders, q, curTab, hideTrials]);

  const stats = useMemo(() => {
    const now = Date.now();
    const paidSince = (days) => orders.filter((o) => o.status === 'paid' && o.total > 0 && now - new Date(o.paid_at || o.created_at).getTime() < days * 864e5);
    const day = paidSince(1); const week = paidSince(7);
    return { today: day.reduce((a, o) => a + o.total, 0), todayN: day.length, week: week.reduce((a, o) => a + o.total, 0), weekN: week.length,
      trials7: orders.filter((o) => isTrial(o) && now - new Date(o.created_at).getTime() < 7 * 864e5).length };
  }, [orders]);

  const refresh = () => qc.invalidateQueries({ queryKey: ['cmtv-orders'] });
  return (
    <div className="ord">
      <div className="ord-head">
        <h1>Orders</h1>
        <input className="ord-search" placeholder="Search name, email, order #, line, product…" value={q} onChange={(e) => { setQ(e.target.value); setLimit(30); }} />
      </div>
      <div className="ord-stats">
        <div className={counts.action ? 'hot' : ''}><b>{counts.action}</b><span>need action</span></div>
        <div><b>{money(stats.today)}</b><span>paid last 24 h ({stats.todayN})</span></div>
        <div><b>{money(stats.week)}</b><span>paid last 7 days ({stats.weekN})</span></div>
        <div><b>{stats.trials7}</b><span>free trials this week</span></div>
      </div>
      <div className="ord-tabs">
        {[['action', 'Needs action'], ['paid', 'Paid'], ['cancelled', 'Cancelled'], ['all', 'All']].map(([k, label]) => (
          <button type="button" key={k} className={curTab === k && !q ? 'on' : ''} onClick={() => { setTab(k); setQ(''); setLimit(30); }}>
            {label} <span>{counts[k]}</span>
          </button>
        ))}
        {curTab !== 'action' && !q && (
          <label className="ord-toggle"><input type="checkbox" checked={hideTrials} onChange={(e) => setHideTrials(e.target.checked)} /> Hide free trials</label>
        )}
      </div>
      {isLoading ? <p className="ord-muted">Loading…</p> : shown.length === 0 ? (
        <p className="ord-muted ord-empty">{q ? 'No orders match.' : curTab === 'action' ? 'Nothing needs you right now. 🎉' : 'No orders here.'}</p>
      ) : (
        <div className="ord-list">
          {shown.slice(0, limit).map((o) => (
            <OrderCard key={o.id} o={o} open={openId === o.id} onToggle={() => setOpenId(openId === o.id ? null : o.id)} onChanged={refresh} />
          ))}
          {shown.length > limit && <button type="button" className="ord-btn ord-more" onClick={() => setLimit(limit + 30)}>Show more ({shown.length - limit} left)</button>}
        </div>
      )}
      <p className="ord-muted ord-foot">Old orders page: <Link to="/admin/orders-classic">classic view</Link></p>
    </div>
  );
}

function summary(o) {
  const first = o.items[0];
  if (!first) return '(no items)';
  const extra = o.items.length > 1 ? ` + ${o.items.length - 1} more` : '';
  return `${first.name}${first.kind === 'extend' && first.extends ? ` · extend ${first.extends}` : ''}${extra}`;
}

function OrderCard({ o, open, onToggle, onChanged }) {
  const [paidBy, setPaidBy] = useState(o.payment_method && ADMIN_PAID_BY.includes(o.payment_method) ? o.payment_method : 'emt');
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const status = problem(o) ? 'problem' : o.status;
  const statusLabel = { problem: 'Not set up', pending: 'Waiting for payment', paid: 'Paid', cancelled: 'Cancelled' }[status] || o.status;

  const run = async (label, fn, okMsg) => {
    if (!window.confirm(label)) return;
    setBusy(true);
    try { await fn(); toast.success(okMsg); onChanged(); } catch (e) { toast.error(e?.response?.data?.detail || 'That didn\'t work.'); }
    setBusy(false);
  };
  const markPaid = () => run(`Mark order #${o.number} paid by ${PAYMENT_LABELS[paidBy]} and set up the service now?`,
    () => api.post(`/api/admin/orders/${o.id}/mark-paid`, { payment_method: paidBy }), 'Marked paid. Setting up the service…');
  const cancel = () => run(`Cancel order #${o.number}? The customer is emailed and any account credit used goes back to them.`,
    () => api.post(`/api/admin/orders/${o.id}/cancel`), 'Order cancelled.');
  const remove = () => run(`Permanently delete order #${o.number} with its invoice and payment records? This can't be undone.`,
    () => api.delete(`/api/admin/orders/${o.id}`), 'Order deleted.');
  const fixed = () => run('Mark this order as fixed (you set it up by hand)? It leaves "Needs action".',
    () => api.post(`/api/cmtv/admin/orders/${o.id}/setup-resolved`), 'Marked fixed.');
  const copy = (t, what) => { navigator.clipboard?.writeText(t).then(() => toast.success(`${what} copied`)).catch(() => {}); };

  return (
    <div className={`ord-card st-${status}${open ? ' open' : ''}`}>
      <button type="button" className="ord-row" onClick={onToggle} aria-expanded={open}>
        <div className="ord-main">
          <div className="ord-top"><b>{o.customer.name}</b><small>#{o.number} · {ago(o.created_at)}</small></div>
          <div className="ord-what">{summary(o)}</div>
          <div className="ord-tags">
            <span className={`ord-chip s-${status}`}>{statusLabel}</span>
            {o.total > 0 && <span className="ord-chip">{paymentLabel(o)}</span>}
            {isTrial(o) && <span className="ord-chip">Free trial</span>}
            {o.auto_renewal && <span className="ord-chip">Auto-renew</span>}
            {o.discount > 0 && <span className="ord-chip">−{money(o.discount)}{o.coupon ? ` ${o.coupon}` : ''}</span>}
            {o.credits_used > 0 && <span className="ord-chip">{money(o.credits_used)} credit</span>}
            {o.emt?.trusted && o.status === 'pending' && <span className="ord-chip s-paid">e-Transfer matched, set up</span>}
          </div>
        </div>
        <div className="ord-amt">{o.total > 0 ? money(o.total) : 'Free'}</div>
      </button>
      {open && (
        <div className="ord-detail">
          <div className="ord-sec">
            <h4>Items</h4>
            {o.items.map((i, k) => (
              <div key={k} className="ord-item">
                <span>{i.name}</span>
                <small>
                  {{ new: 'New line', extend: `Extends ${i.extends || 'a line'}`, addon: 'Add-on', reseller: 'Reseller', upgrade: 'Adds devices' }[i.kind]}
                  {i.term_months ? ` · ${i.term_months} mo` : ''}{i.lineup && i.lineup !== 'full' ? ` · ${LINEUP[i.lineup] || i.lineup}` : ''}
                  {i.groups ? ` · ${i.groups} channel groups` : ''}{i.credits ? ` · ${i.credits} credits` : ''} · {money(i.price)}
                </small>
              </div>
            ))}
          </div>
          <div className="ord-sec">
            <h4>Money</h4>
            {o.subtotal != null && o.subtotal !== o.total && <div className="ord-kv"><span>Subtotal</span><b>{money(o.subtotal)}</b></div>}
            {o.discount > 0 && <div className="ord-kv"><span>Discount{o.discount_source ? ` (${o.discount_source}${o.referral_tier ? ` ${o.referral_tier}` : ''})` : ''}{o.coupon ? ` · ${o.coupon}` : ''}</span><b>−{money(o.discount)}</b></div>}
            {o.credits_used > 0 && <div className="ord-kv"><span>Account credit used</span><b>−{money(o.credits_used)}</b></div>}
            {o.shipping > 0 && <div className="ord-kv"><span>Shipping</span><b>{money(o.shipping)}</b></div>}
            <div className="ord-kv total"><span>Total</span><b>{money(o.total)}</b></div>
            <div className="ord-kv"><span>Payment</span><b>{paymentLabel(o)}{o.paid_at ? ` · ${when(o.paid_at)}` : ''}</b></div>
            {o.payment_id && <div className="ord-kv"><span>Payment ref</span><b className="ord-mono">{o.payment_id}</b></div>}
          </div>
          {(o.services.length > 0 || problem(o)) && (
            <div className="ord-sec">
              <h4>Set up</h4>
              {problem(o) && (
                <div className="ord-problem">⚠️ Not set up automatically{o.provisioning_errors.length ? ':' : '.'}
                  {o.provisioning_errors.map((e, k) => <div key={k} className="ord-mono">{String(e).slice(0, 300)}</div>)}
                </div>
              )}
              {o.services.map((s) => (
                <div key={s.id} className="ord-item"><span>{s.username || '(no login)'}</span>
                  <small>{s.product} · {s.status}{s.expires ? ` · until ${new Date(s.expires).toLocaleDateString()}` : ''}</small></div>
              ))}
            </div>
          )}
          <div className="ord-sec">
            <h4>Customer</h4>
            <div className="ord-item">
              <span><Link to={`/admin/customer/${o.customer.id}`}>{o.customer.name}</Link></span>
              <small>{o.customer.email || (o.customer.line ? `TV login ${o.customer.line} · no email yet` : 'no email')}</small>
            </div>
          </div>
          <div className="ord-actions">
            {o.status === 'pending' && (
              <>
                <label className="ord-paidby">Paid by
                  <select value={paidBy} onChange={(e) => setPaidBy(e.target.value)}>
                    {ADMIN_PAID_BY.map((m) => <option key={m} value={m}>{PAYMENT_LABELS[m]}</option>)}
                  </select>
                </label>
                <button type="button" className="ord-btn glow" disabled={busy} onClick={markPaid}>Mark paid &amp; set up</button>
                <button type="button" className="ord-btn" disabled={busy} onClick={cancel}>Cancel order</button>
              </>
            )}
            {problem(o) && <button type="button" className="ord-btn glow" disabled={busy} onClick={fixed}>Mark fixed</button>}
            <button type="button" className="ord-btn" onClick={() => copy(o.id, 'Order number')}>Copy order #</button>
            <button type="button" className="ord-btn ghost" onClick={() => setMore(!more)}>{more ? 'Less' : 'More…'}</button>
            {more && <button type="button" className="ord-btn danger" disabled={busy} onClick={remove}>Delete permanently</button>}
          </div>
        </div>
      )}
    </div>
  );
}
