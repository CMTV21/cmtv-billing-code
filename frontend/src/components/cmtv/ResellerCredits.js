// CMTV local addition 2026-09-28: "Choose your credits" on the storefront's Resellers tab. Any amount 50-1000, priced per
// credit in steps (GET /api/cmtv/reseller/pricing, cmtv_reseller_credits.py). The server recalculates the price at
// checkout; the amount travels as the cart item's `credits`. Signed out: the choice is remembered through sign-in.
import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { useAuthStore, useCartStore } from '../../store/store';
import { rememberPlan } from './pendingPlan';

export function creditPrice(tiers, n) {
  let rate = null;
  (tiers || []).forEach((t) => { if (n >= t.min) rate = t.rate; });
  return rate === null ? null : { rate, total: Math.round(n * rate * 100) / 100 };
}

const money = (v) => `$${v.toLocaleString(undefined, { minimumFractionDigits: v % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;

export default function ResellerCredits() {
  const { user } = useAuthStore();
  const { addItem } = useCartStore();
  const { data } = useQuery({ queryKey: ['reseller-pricing'], queryFn: async () => (await api.get('/api/cmtv/reseller/pricing')).data, staleTime: 300000 });
  const servers = data?.servers || {};
  const keys = Object.keys(servers);
  const [server, setServer] = useState('cctv');
  const [credits, setCredits] = useState(100);
  const s = servers[server] || servers[keys[0]];
  const min = data?.min || 50;
  const max = data?.max || 1000;
  const n = Math.min(max, Math.max(min, Math.round(Number(credits) || 0)));
  const quote = useMemo(() => (s ? creditPrice(s.tiers, n) : null), [s, n]);
  if (!s) return null;

  const buy = () => {
    if (!quote) return;
    if (!user) { rememberPlan(s.product_id, n); window.location.href = '/login?redirect=/'; return; }
    addItem({ product_id: s.product_id, product_name: `${s.label} Reseller Credits - ${n} credits`, term_months: 1,
      price: quote.total, account_type: 'reseller', credits: n });
    window.location.href = '/checkout';
  };

  return (
    <div className="rc">
      <div className="rc-head">
        <h3>Choose your credits</h3>
        <p>Any amount from {min} to {max.toLocaleString()}. The more you buy, the less each credit costs.</p>
      </div>
      <div className="rc-tabs" role="group" aria-label="Server">
        {keys.map((k) => (
          <button type="button" key={k} className={k === server ? 'on' : ''} aria-pressed={k === server} onClick={() => setServer(k)}>{servers[k].label}</button>
        ))}
      </div>
      <div className="rc-pick">
        <input type="range" min={min} max={max} step={10} value={n} onChange={(e) => setCredits(e.target.value)} aria-label="Credits" />
        <label className="rc-num">
          <input type="number" min={min} max={max} value={credits} onChange={(e) => setCredits(e.target.value)} onBlur={() => setCredits(n)} aria-label="Number of credits" />
          <span>credits</span>
        </label>
      </div>
      <div className="rc-tiers">
        {s.tiers.map((t, i) => {
          const next = s.tiers[i + 1];
          const on = n >= t.min && (!next || n < next.min);
          return (
            <div key={t.min} className={on ? 'on' : ''}>
              <b>{money(t.rate)}</b><span>{next ? `${t.min}-${next.min - 1}` : `${t.min}+`} credits</span>
            </div>
          );
        })}
      </div>
      <div className="rc-total">
        <div><span>{n} credits &times; {quote ? money(quote.rate) : '-'}</span><b>{quote ? money(quote.total) : '-'}</b></div>
        <button type="button" className="btn btn-glow" onClick={buy}>Buy {n} {s.label} credits</button>
      </div>
      <p className="rc-note">At checkout choose a new reseller panel (your own username and password) or add the credits to the panel you already have.</p>
    </div>
  );
}
