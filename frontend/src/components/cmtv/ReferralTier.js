// CMTV local addition 2026-09-25: referral tiers (backend: cmtv_referral.py).
// TierCard: the customer's tier on the Referrals page. AdminCustomerReferrals: tier, past referrals and credit in
// Admin > Customers. useTierQuote: the member discount shown at checkout (the server works it out again on the order).
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Award, Check, Gift, Plus, Trash2, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../api/api';

const fmtDate = (d) => (d ? new Date(d).toLocaleDateString() : '');
const money = (n) => `$${Number(n || 0).toFixed(2)}`;

function perkText(t) {
  if (!t.pct && !t.free_cmtv_plus) return '$15 credit for each friend who joins, and $5 off for them';
  return `${t.pct}% off every purchase${t.free_cmtv_plus ? ', plus CMTV+ free for life (Stremio, CMTVpn and Audiobooks)' : ''}`;
}

export function useTierQuote(items) {
  const key = (items || []).map((i) => `${i.product_id}:${i.renewal_service_id || ''}`).join(',');
  const { data } = useQuery({
    queryKey: ['cmtv-tier-quote', key],
    queryFn: async () => (await api.post('/api/cmtv/referral/quote', {
      items: (items || []).map((i) => ({ product_id: i.product_id, renewal_service_id: i.renewal_service_id })),
    })).data,
    enabled: (items || []).length > 0,
    staleTime: 60000,
  });
  return data || { amount: 0, tier: null, pct: 0, lines: [] };
}

export function TierCard() {
  const { data } = useQuery({
    queryKey: ['cmtv-tier-me'],
    queryFn: async () => (await api.get('/api/cmtv/referral/me')).data,
  });
  if (!data || data.enabled === false) return null;
  const next = data.next;
  const prevMin = [...data.tiers].reverse().find((t) => t.min <= data.count)?.min || 0;
  const pct = next ? Math.min(100, Math.round(((data.count - prevMin) / (next.min - prevMin)) * 100)) : 100;
  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6" data-testid="tier-card">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-amber-100 dark:bg-amber-900/40 rounded-lg flex items-center justify-center">
            <Award className="w-6 h-6 text-amber-600" />
          </div>
          <div>
            <p className="text-sm text-gray-600 dark:text-gray-400">Your tier</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{data.tier}</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-600 dark:text-gray-400">Lifetime referrals</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{data.count}</p>
        </div>
      </div>

      <div className="mt-5">
        <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          <div className="h-full bg-amber-500 rounded-full" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
          {next
            ? `${next.needs} more referral${next.needs === 1 ? '' : 's'} to reach ${next.name}: ${perkText(next)}.`
            : 'You have reached the top tier. Thank you!'}
        </p>
      </div>

      <div className="mt-5 grid gap-2">
        {data.tiers.map((t) => {
          const reached = data.count >= t.min;
          return (
            <div key={t.name} className={`flex items-start gap-3 rounded-lg p-3 border ${t.name === data.tier
              ? 'border-amber-400 bg-amber-50 dark:bg-amber-900/20' : 'border-gray-200 dark:border-gray-700'}`}>
              {reached ? <Check className="w-5 h-5 text-green-600 mt-0.5 flex-shrink-0" /> : <Gift className="w-5 h-5 text-gray-400 mt-0.5 flex-shrink-0" />}
              <div>
                <p className="font-semibold text-gray-900 dark:text-white">
                  {t.name} <span className="text-sm font-normal text-gray-500 dark:text-gray-400">({t.min ? `${t.min} referrals` : 'everyone'})</span>
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-300">{perkText(t)}</p>
              </div>
            </div>
          );
        })}
      </div>
      {data.pct > 0 && (
        <p className="text-sm text-green-700 dark:text-green-400 mt-4">
          Your {data.pct}% discount is applied automatically at checkout on your account. There's no code to enter.
        </p>
      )}
      {data.past?.length > 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
          Includes {data.past.length} referral{data.past.length === 1 ? '' : 's'} from before the billing portal tracked them.
        </p>
      )}
    </div>
  );
}

const box = 'bg-gray-50 dark:bg-gray-700 rounded-lg p-6';
const input = 'px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';

export function AdminCustomerReferrals({ customerId }) {
  const qc = useQueryClient();
  const [past, setPast] = useState({ name: '', date: '', note: '' });
  const [credit, setCredit] = useState({ amount: '', reason: '' });
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const { data, isLoading } = useQuery({
    queryKey: ['cmtv-ref-admin', customerId],
    queryFn: async () => (await api.get(`/api/cmtv/referral/admin/user/${customerId}`)).data,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['cmtv-ref-admin', customerId] });
    qc.invalidateQueries({ queryKey: ['cmtv-ref-overview'] });
  };
  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); toast.success(ok); refresh(); return true; }
    catch (e) { toast.error(e.response?.data?.detail || 'Something went wrong'); return false; }
    finally { setBusy(false); }
  };
  if (isLoading || !data) return <div className={box}><p className="text-sm text-gray-500">Loading referrals…</p></div>;

  return (
    <div className={box} data-testid="admin-referrals-box">
      <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-gray-900 dark:text-white">
        <Award className="w-5 h-5" /> Referrals &amp; Credit
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <Stat label="Tier" value={data.tier} sub={data.pct ? `${data.pct}% off${data.free_cmtv_plus ? ' + CMTV+ free' : ''}` : 'Member'} />
        <Stat label="Lifetime referrals" value={data.count} sub={`${data.billing_count} in billing, ${data.past_count} past`} />
        <Stat label="Next tier" value={data.next ? data.next.name : '—'} sub={data.next ? `${data.next.needs} more` : 'top tier'} />
        <Stat label="Credit balance" value={money(data.credit_balance)} sub={data.referral_code ? `code ${data.referral_code}` : ''} />
      </div>

      <div className="grid md:grid-cols-2 gap-5">
        <form className="space-y-2" onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api.post(`/api/cmtv/referral/admin/user/${customerId}/past`, past), 'Past referral added')) setPast({ name: '', date: '', note: '' });
        }}>
          <p className="font-semibold text-sm text-gray-900 dark:text-white">Add a past referral</p>
          <input className={`${input} w-full`} placeholder="Who they referred (name)" value={past.name}
            onChange={(e) => setPast({ ...past, name: e.target.value })} required maxLength={120} />
          <div className="flex gap-2">
            <input className={`${input} flex-1`} type="date" value={past.date} onChange={(e) => setPast({ ...past, date: e.target.value })} />
            <input className={`${input} flex-1`} placeholder="Note (optional)" value={past.note} maxLength={300}
              onChange={(e) => setPast({ ...past, note: e.target.value })} />
          </div>
          <button disabled={busy} className="flex items-center gap-1 px-3 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
            <Plus className="w-4 h-4" /> Add referral
          </button>
        </form>

        <form className="space-y-2" onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api.post(`/api/cmtv/referral/admin/user/${customerId}/credit`, { amount: Number(credit.amount), reason: credit.reason }),
            Number(credit.amount) > 0 ? 'Credit added' : 'Credit removed')) setCredit({ amount: '', reason: '' });
        }}>
          <p className="font-semibold text-sm text-gray-900 dark:text-white">Add or remove credit</p>
          <div className="flex gap-2">
            <input className={`${input} w-28`} type="number" step="0.01" placeholder="15 or -15" value={credit.amount}
              onChange={(e) => setCredit({ ...credit, amount: e.target.value })} required />
            <input className={`${input} flex-1`} placeholder="Reason (the customer sees this)" value={credit.reason} maxLength={200}
              onChange={(e) => setCredit({ ...credit, reason: e.target.value })} required />
          </div>
          <button disabled={busy} className="flex items-center gap-1 px-3 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 disabled:opacity-50">
            <Wallet className="w-4 h-4" /> Save credit
          </button>
        </form>
      </div>

      <div className="grid md:grid-cols-2 gap-5 mt-6">
        <div>
          <p className="font-semibold text-sm text-gray-900 dark:text-white mb-2">Referrals ({data.referrals.length + data.past.length})</p>
          {data.referrals.length + data.past.length === 0 && <p className="text-sm text-gray-500 dark:text-gray-400">None yet</p>}
          <ul className="space-y-1 text-sm">
            {data.referrals.map((r, i) => (
              <li key={`b${i}`} className="flex justify-between gap-2 text-gray-700 dark:text-gray-200">
                <span>{r.name || r.email} <span className="text-gray-500">({r.status}{r.rewarded ? `, ${money(r.reward)} paid` : ''})</span></span>
                <span className="text-gray-500">{fmtDate(r.completed_at || r.created_at)}</span>
              </li>
            ))}
            {data.past.map((h) => (
              <li key={h.id} className="flex justify-between gap-2 text-gray-700 dark:text-gray-200">
                <span>{h.referred_name} <span className="text-gray-500">(past{h.note ? `: ${h.note}` : ''})</span></span>
                <span className="flex items-center gap-2 text-gray-500">
                  {fmtDate(h.date)}
                  {confirmId === h.id ? (
                    <>
                      <button type="button" className="text-red-600 font-semibold" disabled={busy}
                        onClick={() => run(() => api.delete(`/api/cmtv/referral/admin/past/${h.id}`), 'Removed').then(() => setConfirmId(null))}>Remove?</button>
                      <button type="button" onClick={() => setConfirmId(null)}>Keep</button>
                    </>
                  ) : (
                    <button type="button" title="Remove" onClick={() => setConfirmId(h.id)}><Trash2 className="w-4 h-4" /></button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="font-semibold text-sm text-gray-900 dark:text-white mb-2">Recent credit</p>
          {data.credits.length === 0 && <p className="text-sm text-gray-500 dark:text-gray-400">No credit history</p>}
          <ul className="space-y-1 text-sm">
            {data.credits.map((c, i) => (
              <li key={i} className="flex justify-between gap-2 text-gray-700 dark:text-gray-200">
                <span className="truncate">{c.description}</span>
                <span className={c.amount < 0 ? 'text-red-600' : 'text-green-600'}>{c.amount < 0 ? '-' : '+'}{money(Math.abs(c.amount))}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div>
      <p className="text-sm text-gray-600 dark:text-gray-400">{label}</p>
      <p className="font-bold text-lg text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-500 dark:text-gray-400">{sub}</p>}
    </div>
  );
}
