// CMTV local addition 2026-10-05 (tested on both live panels): a customer with a RUNNING CCTV / Imperium trial who buys a
// plan on the same server keeps the trial's login: checkout pre-selects "Keep my trial login" (extend that line) instead
// of a new line. They can still pick "Create New Line". Ended trials aren't pre-selected (not tested yet).
import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';

export const isRunningTvTrial = (s) => !!s && s.is_trial && ['xtream', 'aether'].includes(s.panel_type) && s.status === 'active'
  && s.expiry_date && new Date(String(s.expiry_date).endsWith('Z') ? s.expiry_date : `${s.expiry_date}Z`) > new Date();

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
