// CMTV local addition 2026-10-11 (owner, after a customer renewing by "Create New Line" got a second line): when a customer
// buys a TV plan (or an add-on) and already has a line it can extend, checkout pre-selects "Extend: <their line>" instead of
// "Create New Line". Which line: a running trial on that server first (as KeepTrialLogin), else the active line ending
// soonest, else the most recently ended one. They can still choose "Create New Line" (and are asked to confirm).
import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { isRunningTvTrial, isRealTvTrial } from './KeepTrialLogin';

const ts = (d) => (d ? new Date(String(d).endsWith('Z') ? d : `${d}Z`).getTime() : 0);

export function bestLine(all, now = Date.now()) {
  // 2026-10-11 (owner): other lines within 30 days of ending. 2026-10-13 (owner, option B): a real trial only while it's
  // running (billing gives an ended trial a new line); old paid lines wrongly flagged is_trial count as normal lines
  const tv = (s) => ['xtream', 'aether'].includes(s.panel_type);
  const lines = all.filter((s) => (isRealTvTrial(s) ? isRunningTvTrial(s)
    : (s.is_trial && !tv(s) ? isRunningTvTrial(s) || ts(s.expiry_date) > now - 7 * 86400000   // add-on trials: as before
      : ts(s.expiry_date) > now - 30 * 86400000)));
  const trial = lines.filter(isRunningTvTrial).sort((a, b) => ts(b.expiry_date) - ts(a.expiry_date))[0];
  if (trial) return trial;
  const active = lines.filter((s) => ts(s.expiry_date) > now).sort((a, b) => ts(a.expiry_date) - ts(b.expiry_date))[0];
  if (active) return active;
  return lines.slice().sort((a, b) => ts(b.expiry_date) - ts(a.expiry_date))[0] || null;
}

export default function PreferExtend({ items, services, choicesFor, updateItemAction }) {
  const { data: products } = useQuery({ queryKey: ['cmtv-keep-products'], queryFn: async () => (await api.get('/api/products')).data || [], staleTime: 300000 });
  const done = useRef(new Set());
  useEffect(() => {
    if (!products || !services) return;
    const byId = Object.fromEntries(products.map((p) => [p.id || p._id, p]));
    items.forEach((it) => {
      const key = `${it.product_id}-${it.term_months}`;
      if (done.current.has(key) || it.action_type || it.renewal_service_id || it.gift || Number(it.price) <= 0) return;
      const p = byId[it.product_id];
      if (!p || p.is_trial) return;
      done.current.add(key);
      // TV plans: only lines on the same server; add-ons: extendChoices already limits to that add-on
      const lines = (choicesFor(it) || []).filter((s) => p.panel_type === 'manual' || s.panel_type === p.panel_type)
        .filter((s) => !['failed', 'duplicate', 'removed'].includes(s.status));
      const pick = bestLine(lines);
      if (pick) updateItemAction(it.product_id, it.term_months, 'extend', pick.id);
    });
  }, [items, products, services, choicesFor, updateItemAction]);
  return null;
}
