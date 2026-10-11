// CMTV local addition 2026-10-11: Admin > Notices > Outage credits ("we fix it or make it right"; backend cmtv_promise.py).
// Settings ($ per outage, hours, auto-approve, the "try the other server" offer) and each qualifying outage to approve/skip.
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const when = (s) => (s ? new Date(s).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '');
const STATUS = { pending: 'Waiting for you', approved: 'Sending…', done: 'Credited', skipped: 'Skipped' };

export default function PromiseBox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-promise-admin'], queryFn: async () => (await api.get('/api/cmtv/promise/admin')).data });
  const [amount, setAmount] = useState('5');
  const [hours, setHours] = useState('6');
  const [busy, setBusy] = useState('');
  useEffect(() => { if (data) { setAmount(String(data.config.amount)); setHours(String(data.config.min_hours)); } }, [data]);
  const cfg = data?.config || {};
  const save = async (body, msg) => {
    setBusy('cfg');
    try { await api.post('/api/cmtv/promise/admin/config', body); qc.invalidateQueries({ queryKey: ['cmtv-promise-admin'] }); toast.success(msg); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not save.'); }
    setBusy('');
  };
  const decide = async (b, action) => {
    if (action === 'approve' && !window.confirm(`Give ${b.customers} customers $${b.amount} each ($${(b.customers * b.amount).toFixed(0)}) and email them?`)) return;
    setBusy(b.id);
    try {
      await api.post(`/api/cmtv/promise/admin/batches/${encodeURIComponent(b.id)}`, { action });
      qc.invalidateQueries({ queryKey: ['cmtv-promise-admin'] });
      toast.success(action === 'approve' ? 'Credits going out' : 'Skipped');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not save.'); }
    setBusy('');
  };
  return (
    <div className="rc-box" style={{ marginTop: 18 }}>
      <h2 style={{ margin: '0 0 4px' }}>Outage credits</h2>
      <p style={{ margin: '0 0 10px', opacity: 0.8 }}>
        When CCTV or Imperium is down longer than the hours below, every customer with a paid line on it gets account credit,
        once per outage, with a short "sorry" email (and Telegram if linked). It waits for your OK here unless auto-approve is on,
        so a monitor fault can never pay out by itself. You also get a note in Ops Billing.
      </p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label>Credit $<br /><input type="number" min="1" max="50" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 80 }} /></label>
        <label>Down longer than (hours)<br /><input type="number" min="1" max="72" value={hours} onChange={(e) => setHours(e.target.value)} style={{ width: 80 }} /></label>
        <button type="button" className="rc-btn" disabled={!!busy} onClick={() => save({ amount: Number(amount), min_hours: Number(hours) }, 'Saved')}>Save</button>
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 10 }}>
        <label><input type="checkbox" checked={!!cfg.outage_enabled} disabled={!!busy}
          onChange={(e) => save({ outage_enabled: e.target.checked }, e.target.checked ? 'Outage credits on' : 'Outage credits off')} /> Outage credits on</label>
        <label><input type="checkbox" checked={!!cfg.auto_approve} disabled={!!busy}
          onChange={(e) => save({ auto_approve: e.target.checked }, e.target.checked ? 'Will send without asking' : 'Will ask you first')} /> Send without asking me</label>
        <label><input type="checkbox" checked={!!cfg.switch_enabled} disabled={!!busy}
          onChange={(e) => save({ switch_enabled: e.target.checked }, 'Saved')} /> "Buffering? Try the other server free" on dashboards</label>
      </div>
      {(data?.batches || []).length === 0 ? (
        <p style={{ margin: '12px 0 0', opacity: 0.7 }}>No qualifying outages in the last 7 days.</p>
      ) : (
        <div style={{ marginTop: 12 }}>
          {data.batches.map((b) => (
            <div key={b.id} style={{ padding: '8px 0', borderTop: '1px solid rgba(255,255,255,.08)', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <b>{b.server}</b>
              <span style={{ opacity: 0.85 }}>{when(b.down_at)} to {when(b.up_at)} · {Math.floor(b.minutes / 60)} h {b.minutes % 60} min</span>
              <span style={{ opacity: 0.85 }}>{b.customers} customers · ${(b.customers * b.amount).toFixed(0)}</span>
              <span className="rc-pill">{STATUS[b.status] || b.status}{b.status === 'done' ? ` · ${b.emailed} emailed, ${b.telegram} Telegram` : ''}</span>
              {b.status === 'pending' && (
                <span style={{ display: 'flex', gap: 8 }}>
                  <button type="button" className="rc-btn" disabled={!!busy} onClick={() => decide(b, 'approve')}>Approve</button>
                  <button type="button" className="rc-btn" disabled={!!busy} onClick={() => decide(b, 'skip')}>Skip</button>
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
