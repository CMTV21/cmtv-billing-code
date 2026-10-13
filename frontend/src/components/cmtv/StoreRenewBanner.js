// CMTV local addition 2026-10-13 (owner; Rick Wilkins bought 3 NEW lines instead of renewing): on the store's CCTV and
// Imperium sections, a signed-in customer who already has a paid line on that server is told so first, with
// "Renew my line" (-> /dashboard?renew=<service id> opens that line's renew panel). Buying a plan below still works:
// it's a second line (the checkout's own "start a NEW line?" tick still applies).
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { servicesAPI } from '../../api/api';
import { useAuthStore } from '../../store/store';

const PANEL = { cctv: 'xtream', imperium: 'aether' };
const DAY = 86400000;
const fmt = (d) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

export default function StoreRenewBanner({ family }) {
  const { user } = useAuthStore();
  const { data } = useQuery({
    queryKey: ['services'], queryFn: async () => (await servicesAPI.getAll()).data || [],
    enabled: !!user && !!PANEL[family], staleTime: 30000,
  });
  if (!user || !PANEL[family] || !data) return null;
  const now = Date.now();
  const lines = data.filter((s) => s.panel_type === PANEL[family] && s.account_type !== 'reseller' && !s.is_trial
      && ['active', 'expired', 'suspended'].includes(s.status)
      && (!s.expiry_date || new Date(s.expiry_date).getTime() > now - 30 * DAY))
    .sort((a, b) => new Date(a.expiry_date || 0) - new Date(b.expiry_date || 0));
  if (!lines.length) return null;
  const s = lines[0];
  const login = s.xtream_username || s.username;
  const ended = s.expiry_date && new Date(s.expiry_date).getTime() < now;
  const name = family === 'cctv' ? 'CCTV' : 'Imperium';
  const accent = family === 'imperium' ? 'var(--gold, #d8b35a)' : 'var(--cyan, #22e6f2)';
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px 16px', margin: '0 0 14px', padding: '12px 14px',
                  border: `1px solid ${accent}`, borderRadius: 14, background: 'rgba(255,255,255,.03)' }}>
      <div style={{ flex: '1 1 260px', fontSize: 14, color: 'var(--muted, #9aa6c6)' }}>
        <b style={{ color: 'var(--text, #e9edf8)', display: 'block', fontSize: 15 }}>You already have {lines.length > 1 ? `${lines.length} ${name} lines` : `a ${name} line`}</b>
        {login} · {ended ? 'ended' : 'ends'} {s.expiry_date ? fmt(s.expiry_date) : ''}. Renew it to keep the same login.
        <span style={{ display: 'block', marginTop: 2, fontSize: 12.5 }}>Picking a plan below adds a second line with a new login.</span>
      </div>
      <Link to={`/dashboard?renew=${s.id}`} style={{ background: accent, color: '#0a1020', fontWeight: 800, borderRadius: 10, padding: '10px 16px',
                                                     textDecoration: 'none', whiteSpace: 'nowrap' }}>Renew my line</Link>
    </div>
  );
}
