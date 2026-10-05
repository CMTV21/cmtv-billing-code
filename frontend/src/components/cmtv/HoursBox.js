// CMTV local addition 2026-10-05: Admin > Notices "Support hours": regular hours (Eastern) and an "Away" switch for days
// off. Customers see them at checkout (e-Transfer), in the new-ticket window, on the Tickets and Status pages and in the
// e-Transfer order email. Backend: /api/cmtv/hours/admin (cmtv_hours.py).
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const field = { font: 'inherit', padding: '7px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' };
const btn = { font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: 0, cursor: 'pointer' };

export default function HoursBox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-hours-admin'], queryFn: async () => (await api.get('/api/cmtv/hours/admin')).data });
  const [open, setOpen] = useState('08:00');
  const [close, setClose] = useState('21:00');
  const [back, setBack] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) { setOpen(data.open); setClose(data.close); setBack(data.away_until || ''); setNote(data.away_note || ''); } }, [data]);

  const save = async (body, msg) => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/hours/admin', body);
      qc.invalidateQueries({ queryKey: ['cmtv-hours-admin'] }); qc.invalidateQueries({ queryKey: ['cmtv-hours'] });
      toast.success(msg);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not save.'); }
    setBusy(false);
  };

  return (
    <div className="rc-box" style={{ marginTop: 18 }}>
      <h2 style={{ margin: '0 0 4px' }}>Support hours</h2>
      <p style={{ margin: '0 0 10px', opacity: 0.8 }}>
        Customers see these at checkout (e-Transfer), when opening a ticket, on the Tickets and Status pages, and in the e-Transfer order email.
      </p>
      {data && (
        <p style={{ margin: '0 0 12px' }}>
          Right now customers see: <b>{data.open_now ? '🟢 Online now' : `🌙 Back at ${data.next_open_text}`}</b>
          {data.away && <> · <span style={{ color: '#fbbf24' }}>Away switch is on</span></>}
        </p>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <label>Open <input type="time" value={open} onChange={(e) => setOpen(e.target.value)} style={field} /></label>
        <label>Close <input type="time" value={close} onChange={(e) => setClose(e.target.value)} style={field} /></label>
        <span style={{ opacity: 0.7 }}>Eastern, every day</span>
        <button type="button" disabled={busy} onClick={() => save({ open, close }, 'Hours saved.')}
          style={{ ...btn, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }}>Save hours</button>
      </div>
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #27345a' }}>
        <b>Away (days off)</b>
        <p style={{ margin: '2px 0 8px', opacity: 0.8 }}>Customers see you as offline until opening time on the date you pick.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <label>Back on <input type="date" value={back} onChange={(e) => setBack(e.target.value)} style={field} /></label>
          <input value={note} maxLength={160} onChange={(e) => setNote(e.target.value)} placeholder="Optional note, e.g. away for the long weekend"
            style={{ ...field, flex: 1, minWidth: 220 }} />
          <button type="button" disabled={busy || !back} onClick={() => save({ away_until: back, away_note: note }, 'Away switch on.')}
            style={{ ...btn, background: '#fbbf24', color: '#1a1300' }}>Turn on</button>
          {data?.away && (
            <button type="button" disabled={busy} onClick={() => save({ away_until: null }, "Away switch off: you're back.")}
              style={{ ...btn, background: '#1c2747', color: '#e9edf8' }}>I'm back</button>
          )}
        </div>
      </div>
    </div>
  );
}
