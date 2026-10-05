// CMTV local addition 2026-10-05: holiday bonus months ("buy a 12-month plan, get 3 months free"; backend cmtv_promo.py).
// Shown only while the offer runs: a banner on the store, a tag on 12-month TV plans, a line at checkout. Admin > Notices
// has the box to set the days, the months and the name.
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

export function usePromo() {
  const { data } = useQuery({ queryKey: ['cmtv-promo'], queryFn: async () => (await api.get('/api/cmtv/promo')).data,
    staleTime: 300000, retry: 1 });
  return data?.active ? data : null;
}

const endsText = (s) => (s ? new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric' }) : '');
const term = (p) => Number(Object.keys(p?.prices || {})[0] || 0);
export const promoFits = (p) => !!p && ['aether', 'xtream'].includes(p.panel_type) && (p.account_type || 'subscriber') === 'subscriber'
  && !p.is_trial && term(p) === 12;

export function PromoBanner() {
  const promo = usePromo();
  if (!promo) return null;
  return (
    <div style={{ margin: '0 auto 18px', maxWidth: 760, padding: '12px 16px', borderRadius: 14, textAlign: 'center',
      background: 'linear-gradient(135deg, rgba(34,230,242,.14), rgba(139,92,246,.18))', border: '1px solid rgba(139,92,246,.45)' }}>
      <b style={{ fontSize: 17 }}>🎁 {promo.label}: buy any 12-month plan, get {promo.months} months free</b>
      <div style={{ fontSize: 14, opacity: 0.85, marginTop: 2 }}>CCTV or Imperium, new or renewing.
        {promo.plus_product_id ? ` Add CMTV+ for just $${promo.plus_price} with it (normally $${promo.plus_list_price}).` : ''} Ends {endsText(promo.end)}.</div>
    </div>
  );
}

// 2026-10-05: CMTV+ at the holiday price when the cart has a yearly TV plan (the server makes the same decision)
const yearlyTv = (i) => !i.gift && i.action_type !== 'upgrade' && i.account_type === 'subscriber' && Number(i.term_months) === 12
  && Number(i.price) > 0 && !/trial/i.test(i.product_name || '');
export function usePlusOffer(items) {
  const promo = usePromo();
  return promo?.plus_product_id && (items || []).some(yearlyTv) ? { id: promo.plus_product_id, price: promo.plus_price, label: promo.label } : null;
}
// Keeps a CMTV+ already in the cart at the right price (holiday price with a yearly plan, its normal price without one)
export function PromoPlusSync({ items, setItems }) {
  const promo = usePromo();
  const offer = usePlusOffer(items);
  useEffect(() => {
    const plusId = promo?.plus_product_id;
    if (!plusId) return;
    let left = offer ? (items || []).filter(yearlyTv).length : 0;
    let changed = false;
    const next = (items || []).map((i) => {
      if (i.product_id !== plusId || i.gift) return i;
      const want = left > 0 ? Math.min(offer.price, i.list_price ?? Number(i.price)) : (i.list_price ?? Number(i.price));
      if (left > 0) left -= 1;
      if (Number(i.price) === want) return i;
      changed = true;
      return { ...i, list_price: i.list_price ?? Number(i.price), price: want };
    });
    if (changed) setItems(next);
  }, [items, offer, promo, setItems]);
  return null;
}

export function PromoTag({ product }) {
  const promo = usePromo();
  if (!promo || !promoFits(product)) return null;
  return <span style={{ display: 'inline-block', marginLeft: 8, fontSize: 11.5, fontWeight: 800, color: '#07101f', borderRadius: 6,
    padding: '2px 7px', background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', verticalAlign: 'middle' }}>+{promo.months} MONTHS FREE</span>;
}

// Checkout: under a 12-month TV item (the server decides; this only shows it)
export function PromoCheckoutLine({ item }) {
  const promo = usePromo();
  if (!promo || item?.gift || item?.action_type === 'upgrade' || item?.account_type !== 'subscriber' || Number(item?.term_months) !== 12
      || Number(item?.price) <= 0) return null;
  return <p className="text-sm font-semibold mt-1" style={{ color: '#8b5cf6' }}>🎁 +{promo.months} bonus months free ({promo.label})</p>;
}

// Admin > Notices
const field = { font: 'inherit', padding: '7px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' };
const STATUS = { off: ['Off', '#94a3b8'], scheduled: ['Scheduled', '#fcd34d'], running: ['Running now', '#6ee7b7'], ended: ['Ended', '#94a3b8'] };

export function PromoBox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-promo-admin'], queryFn: async () => (await api.get('/api/cmtv/promo/admin')).data });
  const [f, setF] = useState({ start: '', end: '', months: 3, label: 'Black Friday', plus_price: 45 });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setF({ start: data.start || '', end: data.end || '', months: data.months || 3, label: data.label || 'Black Friday',
    plus_price: data.plus_price ?? 45 }); }, [data]);
  const save = async (extra = {}, msg = 'Saved') => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/promo/admin', { ...f, months: Number(f.months), plus_price: Number(f.plus_price) || 0, ...extra });
      qc.invalidateQueries({ queryKey: ['cmtv-promo-admin'] }); qc.invalidateQueries({ queryKey: ['cmtv-promo'] });
      toast.success(msg);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not save'); }
    setBusy(false);
  };
  const on = !!data?.enabled;
  const [label, color] = STATUS[data?.status || 'off'];
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="rc-box" style={{ marginTop: 18 }}>
      <h2 style={{ margin: '0 0 4px' }}>Holiday bonus months</h2>
      <p style={{ margin: '0 0 10px', opacity: 0.8 }}>
        Anyone buying or renewing a <b>12-month</b> CCTV or Imperium plan between these days gets free months added to the same line,
        automatically. It turns itself on and off on the days you pick.
      </p>
      <p style={{ margin: '0 0 10px' }}>Status: <b style={{ color }}>{label}</b>
        {data?.orders_with_bonus ? <> · {data.orders_with_bonus} order{data.orders_with_bonus === 1 ? '' : 's'} with the bonus ({data.bonus_added} added)</> : null}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <label>First day <input type="date" value={f.start} onChange={set('start')} style={field} /></label>
        <label>Last day <input type="date" value={f.end} onChange={set('end')} style={field} /></label>
        <label>Free months <input type="number" min="1" max="12" value={f.months} onChange={set('months')} style={{ ...field, width: 70 }} /></label>
        <label>Name <input value={f.label} maxLength={40} onChange={set('label')} style={{ ...field, width: 150 }} /></label>
        <label>CMTV+ with a yearly plan $<input type="number" min="0" step="1" value={f.plus_price} onChange={set('plus_price')} style={{ ...field, width: 70 }} /></label>
        <small style={{ opacity: 0.7 }}>0 = no CMTV+ offer</small>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <button type="button" disabled={busy} onClick={() => save({}, 'Saved')}
          style={{ font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' }}>Save</button>
        <button type="button" disabled={busy} onClick={() => {
          if (!on && !window.confirm(`Switch it on? From ${f.start} to ${f.end}, 12-month TV plans get ${f.months} free months`
            + (Number(f.plus_price) > 0 ? ` and CMTV+ is $${f.plus_price} with them.` : '.'))) return;
          save({ enabled: !on }, on ? 'Switched off' : 'Switched on');
        }} style={{ font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: 0, cursor: 'pointer',
          background: on ? '#fca5a5' : 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }}>{on ? 'Switch off' : 'Switch on'}</button>
      </div>
    </div>
  );
}
