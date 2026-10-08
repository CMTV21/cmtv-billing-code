// CMTV local addition 2026-10-05: extend a CCTV / Imperium line from the customer profile (backend cmtv_admin_extend.py).
// 2026-10-08 (owner: "search a customer, click the server they have and extend them"): one extend panel used from the
// customer list (tap a line) and the profile ("Extend line"). It shows the end date now and after each choice, the price
// from the plan, how they paid (e-Transfer / PayPal / Cash / Other / Free), email on/off and a note. The big button says
// exactly what will happen; no browser pop-up. Payments go into Finances, so nothing lands in "Needs recording".
import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const C = { bg: '#0f1728', card: '#141d33', deep: '#0a1020', line: '#27345a', text: '#e9edf8', muted: '#9aa6c6', cyan: '#22e6f2', warn: '#fcd34d' };
const toDate = (iso) => (iso ? new Date(String(iso).endsWith('Z') ? iso : `${iso}Z`) : null);
const nice = (iso) => { const d = toDate(iso); return d ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'no date'; };
const label = (m) => (m === 12 ? '1 year' : `${m} month${m > 1 ? 's' : ''}`);
const METHODS = ['e-Transfer', 'PayPal', 'Cash', 'Other', 'Free'];
const chip = (on) => ({ font: 'inherit', fontSize: 14, fontWeight: 700, borderRadius: 10, padding: '9px 12px', cursor: 'pointer', textAlign: 'left',
  border: `1px solid ${on ? C.cyan : C.line}`, background: on ? 'rgba(34,230,242,.12)' : C.deep, color: C.text });

export function ExtendSheet({ serviceId, onClose, onDone }) {
  const { data, error } = useQuery({ queryKey: ['cmtv-extend-opts', serviceId], staleTime: 0, retry: false,
    queryFn: async () => (await api.get(`/api/cmtv/admin/extend/${serviceId}/options`)).data });
  const [months, setMonths] = useState(null);
  const [method, setMethod] = useState('e-Transfer');
  const [amount, setAmount] = useState('');
  const [email, setEmail] = useState(true);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const opts = data?.options || [];
  const opt = opts.find((o) => o.months === months);
  useEffect(() => { if (data) { setEmail(!!data.can_email); const first = opts.find((o) => o.months === 12) || opts[0]; if (first) { setMonths(first.months); setAmount(String(first.price || '')); } } },
    [data]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const k = (e) => e.key === 'Escape' && !busy && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [busy, onClose]);
  const pick = (o) => { setMonths(o.months); if (method !== 'Free') setAmount(String(o.price || '')); };
  const free = method === 'Free';
  const amt = free ? 0 : Number(amount || 0);
  const go = async () => {
    if (!opt || busy) return;
    setBusy(true);
    try {
      const r = (await api.post(`/api/cmtv/admin/extend/${serviceId}`, { months, amount: amt, method: free ? 'Other' : method, email, note })).data;
      toast.success(`${data.login} now ends ${nice(r.new_expiry)}${r.emailed ? ' · customer emailed' : ''}`);
      onDone && onDone(r);
      onClose();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not extend'); }
    setBusy(false);
  };
  return (
    <div role="dialog" aria-modal="true" aria-label="Extend line" onClick={() => !busy && onClose()}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(3,6,14,.7)', display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: 520, maxHeight: '92vh', overflowY: 'auto', background: C.bg, color: C.text, border: `1px solid ${C.line}`,
          borderRadius: '16px 16px 0 0', padding: '16px 16px 20px', boxSizing: 'border-box', margin: '0 auto', alignSelf: 'flex-end' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <b style={{ fontSize: 18, flex: 1 }}>Extend {data?.login || 'line'}</b>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close"
            style={{ font: 'inherit', fontSize: 22, lineHeight: 1, background: 'none', border: 0, color: C.muted, cursor: 'pointer' }}>×</button>
        </div>
        {error && <p style={{ color: C.warn }}>{error?.response?.data?.detail || 'This line can’t be extended here.'}</p>}
        {!data && !error && <p style={{ color: C.muted }}>Loading…</p>}
        {data && <>
          <div style={{ fontSize: 14, color: C.muted, margin: '2px 0 12px' }}>
            {data.customer ? `${data.customer} · ` : ''}{data.server} · {data.devices} device{data.devices === 1 ? '' : 's'}<br />
            {data.ended ? 'Ended' : 'Ends'} <b style={{ color: C.text }}>{nice(data.ends)}</b>
            {data.ends_from === 'panel' && <span> (from the panel)</span>}
            {data.ended && <span> · extending starts from today</span>}
          </div>
          {opts.length === 0 && <p style={{ color: C.warn }}>No {data.server} plan for {data.devices} devices in Products, so it can't be extended here.</p>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 8 }}>
            {opts.map((o) => (
              <button key={o.months} type="button" style={chip(o.months === months)} onClick={() => pick(o)}>
                +{label(o.months)}<br /><span style={{ fontWeight: 400, fontSize: 13, color: C.muted }}>to {nice(o.new_end)} · ${o.price}</span>
              </button>
            ))}
          </div>
          <div style={{ fontSize: 13, color: C.muted, margin: '14px 0 6px' }}>How did they pay?</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {METHODS.map((m) => (
              <button key={m} type="button" style={{ ...chip(m === method), padding: '7px 11px' }}
                onClick={() => { setMethod(m); if (m !== 'Free' && !Number(amount) && opt) setAmount(String(opt.price || '')); }}>{m}</button>
            ))}
          </div>
          {!free && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 14 }}>Amount $
              <input type="number" inputMode="decimal" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
                style={{ font: 'inherit', fontSize: 16, width: 110, padding: '7px 9px', borderRadius: 8, border: `1px solid ${C.line}`, background: C.deep, color: C.text }} />
              <small style={{ color: C.muted }}>goes into Finances</small>
            </label>
          )}
          {data.can_email
            ? <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 14 }}>
                <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> Email the customer their new end date</label>
            : <p style={{ fontSize: 13, color: C.muted, margin: '10px 0 0' }}>No email on file: tell them yourself.</p>}
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="Note (optional), e.g. paid in person"
            style={{ font: 'inherit', fontSize: 15, width: '100%', boxSizing: 'border-box', marginTop: 10, padding: '9px 10px', borderRadius: 8,
              border: `1px solid ${C.line}`, background: C.deep, color: C.text }} />
          <button type="button" disabled={!opt || busy || (!free && !(amt > 0))} onClick={go}
            style={{ font: 'inherit', fontSize: 16, fontWeight: 800, width: '100%', marginTop: 14, padding: '13px 14px', borderRadius: 12, border: 0, cursor: 'pointer',
              background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f', opacity: !opt || busy || (!free && !(amt > 0)) ? 0.5 : 1 }}>
            {busy ? 'Extending on the panel…' : opt ? `Extend to ${nice(opt.new_end)} · ${free ? 'free' : `$${amt.toFixed(2)} ${method}`}` : 'Pick how long'}
          </button>
          {!free && !(amt > 0) && opt && <p style={{ fontSize: 12.5, color: C.warn, margin: '6px 0 0' }}>Enter the amount, or pick Free.</p>}
          <p style={{ fontSize: 12, color: C.muted, margin: '8px 0 0' }}>Uses the panel's {data.server} package for {data.devices} devices (normal panel credits).
            The panel sets the exact date.</p>
        </>}
      </div>
    </div>
  );
}

// The profile's line card: one clear button (was four bare "+1 mo" buttons)
export default function AdminTvExtend({ s, onDone }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn sm" style={{ fontWeight: 700 }} onClick={() => setOpen(true)}>Extend line</button>
      {open && <ExtendSheet serviceId={s.id} onClose={() => setOpen(false)} onDone={onDone} />}
    </>
  );
}
