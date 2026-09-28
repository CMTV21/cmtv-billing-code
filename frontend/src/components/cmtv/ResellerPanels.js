// CMTV local addition 2026-09-28: "Your reseller panel" on the dashboard, for customers with an active reseller panel:
// login (copy / show), panel link, credit balance (CCTV: hourly panel sync; Imperium: live) and a top-up slider locked
// to that panel (ResellerCredits with topup = the panel username). Backend: GET /api/cmtv/reseller/mine.
import React, { useState } from 'react';
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
  const low = p.credits !== null && p.credits < 50;
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
      {topup
        ? <ResellerCredits lockServer={p.server} topup={p.username} compact />
        : <button type="button" className="ca-btn ca-glow" onClick={() => setTopup(true)}>Add credits</button>}
    </div>
  );
}

export default function ResellerPanels() {
  const { data } = useQuery({ queryKey: ['my-reseller-panels'], queryFn: async () => (await api.get('/api/cmtv/reseller/mine')).data, staleTime: 60000 });
  const panels = data?.panels || [];
  if (!panels.length) return null;
  return <section className="rp" aria-label="Your reseller panels">{panels.map((p) => <Panel key={p.id} p={p} />)}</section>;
}
