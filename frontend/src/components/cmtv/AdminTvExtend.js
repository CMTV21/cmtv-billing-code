// CMTV local addition 2026-10-05: extend a CCTV / Imperium line from the customer profile (backend cmtv_admin_extend.py).
// +1 mo / +3 mo / +6 mo / +1 yr -> a small form: free or paid (amount + how; goes into Finances), email the customer, note.
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const field = { font: 'inherit', padding: '6px 8px', borderRadius: 8, border: '1px solid var(--line, #27345a)', background: 'var(--bg, #0a1020)', color: 'inherit' };

export default function AdminTvExtend({ s, onDone }) {
  const [open, setOpen] = useState(null);   // months
  const [free, setFree] = useState(false);
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState('e-Transfer');
  const [email, setEmail] = useState(true);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: ['cmtv-extend-opts', s.id], queryFn: async () => (await api.get(`/api/cmtv/admin/extend/${s.id}/options`)).data,
    staleTime: 300000 });
  if (!data) return null;
  const pick = (o) => { setOpen(o.months); setAmount(String(o.price || '')); setFree(false); setNote(''); setEmail(!!data.can_email); };
  const opt = (data.options || []).find((o) => o.months === open);
  const go = async () => {
    const amt = free ? 0 : Number(amount || 0);
    if (!window.confirm(`Extend ${s.username} by ${open === 12 ? '1 year' : `${open} month${open > 1 ? 's' : ''}`} on the panel `
      + `(${opt?.product})? ${amt > 0 ? `Records $${amt.toFixed(2)} ${method} in Finances.` : 'Free: no payment recorded.'}`)) return;
    setBusy(true);
    try {
      const r = (await api.post(`/api/cmtv/admin/extend/${s.id}`, { months: open, amount: amt, method, email, note })).data;
      toast.success(`${s.username} now ends ${new Date(String(r.new_expiry).endsWith('Z') ? r.new_expiry : `${r.new_expiry}Z`).toLocaleDateString()}${r.emailed ? ' · customer emailed' : ''}`);
      setOpen(null);
      onDone && onDone();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not extend'); }
    setBusy(false);
  };
  return (
    <>
      {(data.options || []).map((o) => (
        <button key={o.months} type="button" className="btn sm" disabled={busy} onClick={() => pick(o)}
          title={`${o.product} · $${o.price}`}>+{o.months === 12 ? '1 yr' : `${o.months} mo`}</button>
      ))}
      {open && (
        <div style={{ flexBasis: '100%', marginTop: 8, padding: 10, borderRadius: 10, border: '1px solid var(--line, #27345a)', display: 'flex', flexDirection: 'column', gap: 6 }}>
          <b style={{ fontSize: 14 }}>Extend {s.username}: +{open === 12 ? '1 year' : `${open} month${open > 1 ? 's' : ''}`} · {opt?.product}</b>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 14 }}>
            <input type="checkbox" checked={free} onChange={(e) => setFree(e.target.checked)} /> Free (gift or making things right)</label>
          {!free && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', fontSize: 14 }}>
              Paid $<input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ ...field, width: 90 }} />
              by <select value={method} onChange={(e) => setMethod(e.target.value)} style={field}>
                <option>e-Transfer</option><option>PayPal</option><option>Other</option></select>
              <small style={{ opacity: 0.7 }}>goes into Finances</small>
            </div>
          )}
          {data.can_email
            ? <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 14 }}><input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> Email the customer (new end date)</label>
            : <small style={{ opacity: 0.7 }}>No email on file: tell them yourself.</small>}
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="Note (optional), e.g. paid in person" style={field} />
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" className="btn sm" disabled={busy} onClick={go} style={{ fontWeight: 700 }}>{busy ? 'Extending…' : 'Extend on the panel'}</button>
            <button type="button" className="btn sm" disabled={busy} onClick={() => setOpen(null)}>Cancel</button>
          </div>
        </div>
      )}
    </>
  );
}
