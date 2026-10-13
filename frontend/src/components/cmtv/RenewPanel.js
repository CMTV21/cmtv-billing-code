// CMTV local addition 2026-10-13 (owner; after Rick Wilkins bought 3 NEW lines instead of renewing): the renew panel on
// a TV line's dashboard card. The customer picks 1. how long (same server + same devices, every length on sale),
// 2. channels ("Keep my channels" by default; Full / no adult / North America), 3. listed first (Imperium only).
// Continue = a RENEWAL of this exact line in the cart (action extend + renewal_service_id) -> checkout. Never a new line.
// Backend: a picked package re-syncs the line's channel groups on renewal (server.py Imperium renew, cmtv_lineups CCTV).
// "Listed first" is free and is saved on the panel straight away (POST /api/cmtv/imperium/listed-first/{id}).
import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import { useCartStore } from '../../store/store';
import { LINEUPS, CCTV_LINEUPS, lineupName } from './lineups';

const priceOf = (p) => {
  const [term, price] = Object.entries(p?.prices || {})[0] || ['1', 0];
  return { term: parseInt(term, 10) || 1, price: parseFloat(price) || 0 };
};
const money = (n) => `$${Number(n).toFixed(n % 1 ? 2 : 0)}`;
const addMonths = (d, m) => { const x = new Date(d); const day = x.getDate(); x.setMonth(x.getMonth() + m); if (x.getDate() < day) x.setDate(0); return x; };
const fmt = (d) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

// Every length on sale for this line: same server, same devices, subscriber, not a trial/bundle/CMTV+; one plan per length
export function renewOptions(d, products) {
  const base = d.renewWith;
  if (!base || base.account_type !== 'subscriber' || !['xtream', 'aether'].includes(base.panel_type)) return [];
  const byTerm = {};
  (products || []).filter((p) => p.panel_type === base.panel_type && p.account_type === 'subscriber' && !p.is_trial
      && !p.is_bundle && !p.cmtv_plus && Number(p.max_connections) === Number(base.max_connections)
      && priceOf(p).price > 0 && p.is_active !== false)
    .forEach((p) => {
      const { term } = priceOf(p);
      const cur = byTerm[term];
      const score = (x) => (x.group_id === base.group_id ? 2 : 0) + (/\(/.test(x.name) ? 0 : 1);
      if (!cur || score(p) > score(cur)) byTerm[term] = p;
    });
  return Object.values(byTerm).sort((a, b) => priceOf(a).term - priceOf(b).term);
}

export default function RenewPanel({ d, products, onClose }) {
  const navigate = useNavigate();
  const { addRenewalItem } = useCartStore();
  const s = d.s;
  const imperium = s.panel_type === 'aether';
  const opts = useMemo(() => renewOptions(d, products), [d, products]);
  const monthly = useMemo(() => {   // the best 1-month price, to show "save $X" on longer plans
    const one = opts.find((p) => priceOf(p).term === 1);
    return one ? priceOf(one).price : null;
  }, [opts]);
  const [term, setTerm] = useState(() => (opts.find((p) => priceOf(p).term === d.rp.term) ? d.rp.term : priceOf(opts[0] || d.renewWith).term));
  const [lineup, setLineup] = useState('');   // '' = keep my channels
  const list = imperium ? LINEUPS : CCTV_LINEUPS;
  const current = list.find((l) => l.key === (s.cmtv_lineup || 'full')) || list[0];
  const lf = useQuery({   // Imperium "listed first": the line's current choice + the options, read from the panel
    queryKey: ['cmtv-listed-first-line', s.id],
    queryFn: async () => (await api.get(`/api/cmtv/imperium/listed-first/${s.id}`)).data,
    enabled: imperium, staleTime: 300000, retry: 1,
  });
  const [listed, setListed] = useState(null);
  const credit = useQuery({ queryKey: ['credit-balance'], queryFn: async () => (await api.get('/api/credits/balance')).data, staleTime: 60000 });
  const [busy, setBusy] = useState(false);

  const plan = opts.find((p) => priceOf(p).term === term) || d.renewWith;
  const { price } = priceOf(plan);
  const from = d.expiry && d.expiry > new Date() ? d.expiry : new Date();
  const until = addMonths(from, term);
  const bal = Number(credit.data?.balance || 0);
  const listedNow = listed ?? lf.data?.id;

  const go = async () => {
    setBusy(true);
    try {
      if (imperium && listed !== null && listed !== lf.data?.id) {
        await api.post(`/api/cmtv/imperium/listed-first/${s.id}`, { profile_id: listed });
      }
    } catch (e) {
      toast.error("Couldn't save the channel order right now; you can change it later on your dashboard.");
    }
    addRenewalItem({
      product_id: plan.id, base_name: plan.name, product_name: lineup ? lineupName(plan.name, lineup) : plan.name,
      term_months: term, price, account_type: 'subscriber', lineup: lineup || undefined, channels_confirmed: true,
    }, s.id, 'extend');
    toast.success(`Renewal added: same login (${d.username || s.product_name}), nothing to set up again.`);
    navigate('/checkout');
  };

  if (!opts.length) return null;
  return (
    <div className="ca-renew" role="region" aria-label={`Renew ${s.product_name}`}>
      <div className="ca-renew-head">
        <b>Renew {imperium ? 'Imperium' : 'CCTV'}</b>
        <button type="button" className="ca-icon" onClick={onClose} aria-label="Close">Close</button>
      </div>
      <p className="ca-note">Line {d.username} · {s.max_connections || plan.max_connections} device{Number(s.max_connections || plan.max_connections) === 1 ? '' : 's'}
        {d.expiry ? ` · ${d.ended ? 'ended' : 'ends'} ${fmt(d.expiry)}` : ''}</p>

      <p className="ca-renew-step">1. How long</p>
      <div className="ca-renew-grid">
        {opts.map((p) => {
          const pr = priceOf(p);
          const save = monthly && pr.term > 1 ? Math.round(monthly * pr.term - pr.price) : 0;
          return (
            <button type="button" key={p.id} className={`ca-renew-opt${pr.term === term ? ' on' : ''}`} aria-pressed={pr.term === term} onClick={() => setTerm(pr.term)}>
              <b>{pr.term === 12 ? '12 months' : pr.term === 1 ? '1 month' : `${pr.term} months`}</b>
              <small>{money(pr.price)}{pr.term === d.rp.term ? ' · current' : save > 0 ? ` · save ${money(save)}` : ''}</small>
            </button>
          );
        })}
      </div>

      <label className="ca-renew-step" htmlFor={`rl-${s.id}`}>2. Channels</label>
      <select id={`rl-${s.id}`} className="ca-select" value={lineup} onChange={(e) => setLineup(e.target.value)}>
        <option value="">Keep my channels ({current.label})</option>
        {list.filter((l) => l.key !== current.key).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
      </select>
      {lineup && <p className="ca-note ca-renew-hint">{list.find((l) => l.key === lineup)?.note} Your channel list changes when the renewal goes through.</p>}

      {imperium && (lf.data?.options || []).length > 0 && (<>
        <label className="ca-renew-step" htmlFor={`rlf-${s.id}`}>3. Listed first</label>
        <select id={`rlf-${s.id}`} className="ca-select" value={listedNow ?? ''} onChange={(e) => setListed(Number(e.target.value))}>
          {lf.data.options.map((o) => <option key={o.id} value={o.id}>{o.name}{o.id === lf.data.id ? ' (current)' : ''}</option>)}
        </select>
      </>)}

      <div className="ca-renew-sum">
        Runs until <b>{fmt(until)}</b>. Same login, nothing to set up again.
        {bal > 0 && <span className="ca-renew-credit">You have {money(bal)} store credit to use at checkout.</span>}
      </div>
      <button type="button" className="ca-btn ca-glow ca-renew-go" disabled={busy} onClick={go}>
        {busy ? 'One moment…' : `Continue to payment · ${money(price)}`}
      </button>
    </div>
  );
}
