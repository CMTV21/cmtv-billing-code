// CMTV local addition 2026-09-28: Admin > Notices. Customer service notices by Telegram (customers who connected Telegram
// on their dashboard and left notices on, with an active service in the chosen family) and the reseller notice box
// (shared with Admin > Resellers). Backend: /api/cmtv/telegram/admin/{stats,notice} (cmtv_telegram_alerts.py),
// /api/cmtv/reseller/admin/notice (cmtv_reseller_kit.py).
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import { NoticeBox } from './AdminResellersPage';
import '../../components/cmtv/reseller-credits.css';

const FAMILIES = [
  ['all', 'Everyone with an active service'], ['cctv', 'CCTV'], ['imperium', 'Imperium'], ['extreme', 'Extreme'],
  ['amethyst', 'Amethyst'], ['stremio', 'Stremio'], ['cmtvpn', 'CMTVpn'], ['audiobooks', 'Audiobooks'],
];
const when = (iso) => (iso ? new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '');

function CustomerNotice() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-tg-stats'], queryFn: async () => (await api.get('/api/cmtv/telegram/admin/stats')).data });
  const [family, setFamily] = useState('all');
  const [text, setText] = useState('');
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const label = Object.fromEntries(FAMILIES)[family];
  const post = async (dry) => {
    setBusy(true);
    try {
      const r = (await api.post('/api/cmtv/telegram/admin/notice', { family, text, dry_run: dry })).data;
      if (dry) setCheck(r.recipients);
      else { toast.success(`Sent to ${r.recipients} customer${r.recipients === 1 ? '' : 's'} on Telegram`); setText(''); setCheck(null); refetch(); }
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not send'); }
    setBusy(false);
  };
  const send = () => { if (window.confirm(`Send this to ${check} customer(s) (${label}) on Telegram now?`)) post(false); };
  const count = (k) => (k === 'all' ? null : data?.by_family?.[k]);
  return (
    <div className="rs-notice">
      <b>Send a notice to customers (Telegram)</b>
      <p className="rs-sub" style={{ margin: '4px 0 8px' }}>
        {data ? `${data.linked} customer${data.linked === 1 ? ' has' : 's have'} connected Telegram on their dashboard. ` : ''}
        Only those with notices switched on and an active service in the group you pick get it.
      </p>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>Who
        <select style={{ background: '#0a1020', color: '#e9edf8', border: '1px solid #26314d', borderRadius: 10, padding: '8px 10px' }} value={family} onChange={(e) => { setFamily(e.target.value); setCheck(null); }}>
          {FAMILIES.map(([k, l]) => <option key={k} value={k}>{l}{count(k) !== null && count(k) !== undefined ? ` (${count(k)})` : ''}</option>)}
        </select>
      </label>
      <textarea value={text} maxLength={1500} onChange={(e) => { setText(e.target.value); setCheck(null); }}
        placeholder="e.g. Imperium is doing maintenance tonight 2-3 AM ET. Channels may drop for a few minutes." aria-label="Notice text" />
      <div className="row">
        <button type="button" className="rv-btn" disabled={busy || !text.trim()} onClick={() => post(true)}>Check who gets it</button>
        {check !== null && (check > 0
          ? <button type="button" className="rv-btn glow" disabled={busy} onClick={send}>Send to {check}</button>
          : <span>Nobody in that group has Telegram connected yet.</span>)}
      </div>
      {data?.recent_notices?.length > 0 && (
        <ul>{data.recent_notices.map((n) => (
          <li key={`${n.at}-${n.family}`}>{when(n.at)} · {Object.fromEntries(FAMILIES)[n.family] || n.family}: {n.text.length > 90 ? `${n.text.slice(0, 90)}…` : n.text} ({n.count} sent)</li>
        ))}</ul>
      )}
    </div>
  );
}

export default function AdminNoticesPage() {
  return (
    <div className="rs-admin">
      <h1>Notices</h1>
      <p className="rs-sub">
        For something everyone should see (an outage, big news), post in your CMTV Updates Telegram channel: it goes to the
        customer group, every customer's dashboard and cmtv.info. Use these boxes for targeted messages.
      </p>
      <ServiceStatus />
      <CustomerNotice />
      <NoticeBox />
    </div>
  );
}

// 2026-09-29: what Uptime Kuma last reported (cmtv_status.py). Mapped monitors that are down for 3+ minutes show a banner to
// customers (dashboard, Support, new ticket, cmtv.info) until Kuma reports them up; "Clear" is for a stuck one.
function ServiceStatus() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-status-admin'], queryFn: async () => (await api.get('/api/cmtv/status/admin')).data,
    refetchInterval: 60000 });
  const mons = data?.monitors || [];
  const clear = async (monitor) => {
    try { await api.post('/api/cmtv/status/admin/clear', { monitor }); toast.success(`${monitor} marked as up`); refetch(); }
    catch { toast.error('Could not clear it'); }
  };
  return (
    <div className="rs-notice">
      <b>Service status from Uptime Kuma</b>
      <p className="rs-sub" style={{ margin: '4px 0 8px' }}>
        {mons.length ? `Customers see a banner when a service below is down for ${data.public_after_min}+ minutes. It clears when Kuma says it's back.`
          : 'Nothing received from Uptime Kuma yet.'}
      </p>
      {mons.length > 0 && (
        <ul>{mons.map((m) => (
          <li key={m.monitor}>
            <b style={{ color: m.status === 'down' ? '#f87171' : '#34d399' }}>{m.status === 'down' ? '● Down' : '● Up'}</b> {m.monitor}
            {m.public ? ` (customers see "${m.public}")` : ' (not shown to customers)'} · since {when(m.since)}
            {m.status === 'down' && <> · <button type="button" className="rv-btn" onClick={() => clear(m.monitor)}>Clear</button></>}
          </li>
        ))}</ul>
      )}
      {data?.events?.length > 0 && (
        <details style={{ marginTop: 8 }}><summary>Recent changes</summary>
          <ul>{data.events.slice(0, 15).map((e) => <li key={`${e.monitor}-${e.at}`}>{when(e.at)} · {e.monitor} {e.status}{e.msg ? ` · ${e.msg}` : ''}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
