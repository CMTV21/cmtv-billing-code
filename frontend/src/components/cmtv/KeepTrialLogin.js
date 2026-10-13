// CMTV local addition 2026-10-05 (tested on both live panels): a customer with a RUNNING CCTV / Imperium trial who buys a
// plan on the same server keeps the trial's login: checkout pre-selects "Keep my trial login" (extend that line) instead
// of a new line. They can still pick "Create New Line". Ended trials aren't pre-selected (not tested yet).
import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';

const _t = (d) => (d ? new Date(String(d).endsWith('Z') ? d : `${d}Z`).getTime() : 0);
// 2026-10-13: a REAL TV trial = marked as a trial AND no longer than 8 days (same rule as billing's cmtv_lines.is_trial_line),
// so old paid lines wrongly flagged is_trial aren't treated (or labelled) as trials. Billing extends a RUNNING real trial
// (same login) and gives an ENDED one a new line, so checkout only offers/pre-selects running ones.
const TRIAL_MAX = 8 * 86400000;
export const isRealTvTrial = (s) => !!s && !!s.is_trial && ['xtream', 'aether'].includes(s.panel_type)
  && !(_t(s.expiry_date) && ((_t(s.created_at) && _t(s.expiry_date) - _t(s.created_at) > TRIAL_MAX) || _t(s.expiry_date) - Date.now() > TRIAL_MAX));
export const isRunningTvTrial = (s) => isRealTvTrial(s) && s.status === 'active' && _t(s.expiry_date) > Date.now();

export default function KeepTrialLogin({ items, services, updateItemAction }) {
  const { data: products } = useQuery({ queryKey: ['cmtv-keep-products'], queryFn: async () => (await api.get('/api/products')).data || [], staleTime: 300000 });
  const done = useRef(new Set());
  useEffect(() => {
    if (!products || !services) return;
    const byId = Object.fromEntries(products.map((p) => [p.id || p._id, p]));
    items.forEach((it) => {
      const key = `${it.product_id}-${it.term_months}`;
      if (done.current.has(key) || it.action_type || it.renewal_service_id || it.gift || Number(it.price) <= 0) return;
      const p = byId[it.product_id];
      if (!p || p.is_trial || (p.account_type || 'subscriber') !== 'subscriber' || !['xtream', 'aether'].includes(p.panel_type)) return;
      done.current.add(key);
      const trial = services.filter((s) => isRunningTvTrial(s) && s.panel_type === p.panel_type)
        .sort((a, b) => new Date(b.expiry_date) - new Date(a.expiry_date))[0];
      if (trial) updateItemAction(it.product_id, it.term_months, 'extend', trial.id);
    });
  }, [items, products, services, updateItemAction]);
  return null;
}
