// CMTV local addition 2026-10-11 (owner): "Buffering? Try the other server free" on a paid CCTV / Imperium service card
// (backend cmtv_promise.py switch_offers: only customers who never had the other server's trial). The trial goes through
// the normal checkout (?add=<trial product>), so every usual trial rule still applies.
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';

export default function SwitchTrialOffer({ service }) {
  const { data } = useQuery({
    queryKey: ['cmtv-switch-trial'], staleTime: 300000, retry: false,
    queryFn: async () => { try { return (await api.get('/api/cmtv/promise/switch-trial')).data; } catch { return { offers: [] }; } },
  });
  const o = (data?.offers || []).find((x) => x.for_panel === service.panel_type);
  if (!o) return null;
  return (
    <p className="ca-note" style={{ flexBasis: '100%', margin: '6px 0 0' }}>
      Buffering? <Link to={`/?add=${encodeURIComponent(o.product_id)}`} style={{ fontWeight: 700 }}>Try {o.to} free for {o.hours} hours</Link>
      {' '}on the same devices. Your {o.from} plan stays exactly as it is.
    </p>
  );
}
