// CMTV local addition 2026-09-28: "Your reseller panel" on the dashboard, for customers with an active reseller panel:
// login (copy / show), panel link, credit balance (CCTV: hourly panel sync; Imperium: live) and a top-up slider locked
// to that panel (ResellerCredits with topup = the panel username). Backend: GET /api/cmtv/reseller/mine.
// 2026-09-28: notices from CMTV (last 7 days) and a "Reseller tools" button (/reseller).
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import ResellerCredits from './ResellerCredits';

function copy(text, what) {
  navigator.clipboard.writeText(text).then(() => toast.success(`${what} copied`)).catch(() => toast.error('Copy failed'));
}

function Panel({ p }) {
  const [show, setShow] = useState(false);
  const [topup, setTopup] = useState(false);
  const low = p.credits !== null && p.credits < (p.low_level || 50);
  return (
    <div className="ca-panel rp-panel">
      <div className="rp-head">
        <div>
          <h2 className="ca-h2">{p.label} reseller panel</h2>
          {p.panel_url && <a className="rp-link" href={p.panel_url} target="_blank" rel="noopener noreferrer">{p.panel_url.replace(/^https?:\/\//, '')} &rarr;</a>}
        </div>
        <div className={`rp-bal${low ? ' low' : ''}`}>
          <b>{p.credits === null ? '–' : p.credits.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
          <span>credits{p.server === 'cctv' ? ' (updated hourly)' : ''}</span>
        </div>
      </div>
      <div className="rp-login">
        <div><span>Username</span><code>{p.username}</code><button type="button" className="ca-icon" onClick={() => copy(p.username, 'Username')}>Copy</button></div>
        {p.password && (
          <div><span>Password</span><code>{show ? p.password : '••••••••'}</code>
            <button type="button" className="ca-icon" onClick={() => setShow((v) => !v)}>{show ? 'Hide' : 'Show'}</button>
            <button type="button" className="ca-icon" onClick={() => copy(p.password, 'Password')}>Copy</button></div>
        )}
      </div>
      {low && <p className="rp-warn">Running low. Top up so you can keep creating lines.</p>}
      {p.demo && <p className="rp-warn">Demo account: everything here is for show. Buying credits and other changes are switched off.</p>}
      {topup
        ? <ResellerCredits lockServer={p.server} topup={p.username} compact />
        : (
          <div className="rp-actions">
            <button type="button" className="ca-btn ca-glow" onClick={() => setTopup(true)}>Add credits</button>
            <Link className="ca-btn ca-ghost" to="/reseller">Reseller tools</Link>
            <Link className="ca-btn ca-ghost" to="/knowledge-base/cmtv-reseller-guide">Reseller guide</Link>
          </div>
        )}
    </div>
  );
}

export default function ResellerPanels() {
  const { data } = useQuery({ queryKey: ['my-reseller-panels'], queryFn: async () => (await api.get('/api/cmtv/reseller/mine')).data, staleTime: 60000 });
  const panels = data?.panels || [];
  // 2026-09-28: notices from CMTV to resellers (Admin > Resellers), shown here for 7 days
  const { data: nd } = useQuery({ queryKey: ['reseller-notices'], queryFn: async () => (await api.get('/api/cmtv/reseller/notices')).data,
    enabled: panels.length > 0, staleTime: 300000 });
  const recent = (nd?.notices || []).filter((n) => Date.now() - new Date(n.created_at).getTime() < 7 * 86400000);
  if (!panels.length) return null;
  return (
    <section className="rp" aria-label="Your reseller panels">
      {recent.length > 0 && (
        <div className="ca-panel rt-notices">
          <h2 className="ca-h2">Notice for resellers</h2>
          {recent.map((n) => <div key={n.id} className="rt-notice"><small>{new Date(n.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</small><p>{n.text}</p></div>)}
        </div>
      )}
      {panels.map((p) => <Panel key={p.id} p={p} />)}
    </section>
  );
}
