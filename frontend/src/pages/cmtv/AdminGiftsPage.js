// CMTV local addition 2026-10-05: Admin > Gift cards (backend cmtv_gifts.py). On-sale switch (the /gift page), the holiday
// give-and-get bonus, totals, every card (search, copy code, resend / change email, void) and "Give a free gift card".
import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/reseller-credits.css';

const field = { font: 'inherit', padding: '8px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8', minWidth: 0 };
const btn = { font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '7px 12px', border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' };
const glow = { ...btn, border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' };
const when = (iso) => (iso ? new Date(String(iso).endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const STATUS = { issued: ['Not sent (buyer gives it)', '#7dd3fc'], scheduled: ['Scheduled', '#fcd34d'], sent: ['Emailed', '#7dd3fc'],
  redeemed: ['Redeemed', '#6ee7b7'], void: ['Voided', '#94a3b8'] };

function Switch({ on, label, sub, onChange }) {
  return (
    <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer', margin: '8px 0' }}>
      <input type="checkbox" checked={!!on} onChange={(e) => onChange(e.target.checked)} style={{ marginTop: 4, width: 18, height: 18 }} />
      <span><b>{label}</b><br /><span style={{ opacity: 0.75, fontSize: 14 }}>{sub}</span></span>
    </label>
  );
}

function GiveFree({ onDone }) {
  const [f, setF] = useState({ amount: '', to_name: '', to_email: '', message: '', note: '' });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const go = async () => {
    if (!window.confirm(`Create a free $${f.amount} gift card${f.to_email ? ` and email it to ${f.to_email}` : ''}?`)) return;
    setBusy(true);
    try {
      const r = (await api.post('/api/cmtv/gifts/admin/issue', { ...f, amount: Number(f.amount), from_name: 'CMTV' })).data;
      toast.success(f.to_email ? `Sent ${r.code}` : `Created ${r.code}`);
      setF({ amount: '', to_name: '', to_email: '', message: '', note: '' });
      onDone();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not create it.'); }
    setBusy(false);
  };
  return (
    <details style={{ marginTop: 14 }}>
      <summary style={{ cursor: 'pointer', fontWeight: 700 }}>Give a free gift card (giveaways, making things right)</summary>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 10 }}>
        <input style={field} type="number" min="1" max="500" placeholder="Amount ($)" value={f.amount} onChange={set('amount')} />
        <input style={field} placeholder="Their name (optional)" value={f.to_name} onChange={set('to_name')} />
        <input style={field} type="email" placeholder="Their email (blank = just show me the code)" value={f.to_email} onChange={set('to_email')} />
        <input style={field} placeholder="Message (optional)" value={f.message} onChange={set('message')} />
        <input style={field} placeholder="Private note, e.g. Telegram giveaway" value={f.note} onChange={set('note')} />
        <button type="button" style={glow} disabled={busy || !(Number(f.amount) >= 1)} onClick={go}>Create</button>
      </div>
      <p style={{ opacity: 0.7, fontSize: 13, margin: '6px 0 0' }}>Free cards come "From CMTV" and show here with your note. They aren't counted as sales.</p>
    </details>
  );
}

export default function AdminGiftsPage() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-gifts-admin'], queryFn: async () => (await api.get('/api/cmtv/gifts/admin')).data });
  const [q, setQ] = useState('');
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data?.rows || []).filter((r) => !s || [r.code, r.to_name, r.to_email, r.from_name, r.buyer_name, r.buyer_email, r.redeemed_by_name, r.note]
      .some((v) => String(v || '').toLowerCase().includes(s)));
  }, [data, q]);
  const cfg = data?.config || {};
  const t = data?.totals || {};

  const setCfg = async (k, v) => {
    if (k === 'enabled' && v && !window.confirm('Put gift cards on sale? Customers will be able to open /gift and buy them.')) return;
    try { await api.post('/api/cmtv/gifts/admin/config', { [k]: v }); refetch(); toast.success('Saved'); } catch { toast.error('Could not save'); }
  };
  const resend = async (r) => {
    const to = window.prompt('Send the gift card email to:', r.to_email || '');
    if (to === null) return;
    try { await api.post(`/api/cmtv/gifts/admin/${r.id}/resend`, { to_email: to.trim() }); toast.success(`Sent to ${to.trim()}`); refetch(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not send'); }
  };
  const voidIt = async (r) => {
    if (!window.confirm(`Void ${r.code} ($${r.amount})? It will stop working. This doesn't refund the buyer.`)) return;
    try { await api.post(`/api/cmtv/gifts/admin/${r.id}/void`); toast.success('Voided'); refetch(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not void'); }
  };
  const copy = (c) => { try { navigator.clipboard.writeText(c); toast.success('Copied'); } catch { /* ignore */ } };

  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 style={{ margin: '0 0 4px' }}>Gift cards</h1>
      <p style={{ margin: '0 0 14px', opacity: 0.8 }}>Customers buy them at <a href="/gift" style={{ color: '#22e6f2' }}>/gift</a> and redeem at <a href="/redeem" style={{ color: '#22e6f2' }}>/redeem</a>. The amount goes on their account as credit. Codes never expire.</p>

      <div className="rc-box">
        <Switch on={cfg.enabled} label="On sale" onChange={(v) => setCfg('enabled', v)}
          sub={cfg.enabled ? 'Customers can buy gift cards at /gift.' : 'Hidden: only admins can open /gift (for testing). Redeeming always works.'} />
        <Switch on={cfg.give_get} label="Holiday give-and-get" onChange={(v) => setCfg('give_get', v)}
          sub="The buyer gets $10 credit on a $50+ gift card, $20 on $100+." />
        <GiveFree onDone={refetch} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, margin: '16px 0' }}>
        {[['Sold', `${t.sold || 0} · $${(t.sold_value || 0).toFixed(0)}`], ['Not redeemed yet', `$${(t.outstanding || 0).toFixed(0)}`],
          ['Redeemed', `$${(t.redeemed || 0).toFixed(0)}`], ['Scheduled to send', t.scheduled || 0]].map(([k, v]) => (
          <div key={k} className="rc-box" style={{ margin: 0, padding: '12px 14px' }}><div style={{ opacity: 0.7, fontSize: 13 }}>{k}</div><b style={{ fontSize: 20 }}>{v}</b></div>
        ))}
      </div>

      <input style={{ ...field, width: '100%', marginBottom: 10 }} placeholder="Search code, name, email…" value={q} onChange={(e) => setQ(e.target.value)} />
      {!rows.length && <p style={{ opacity: 0.7 }}>{data ? 'No gift cards yet.' : 'Loading…'}</p>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r) => {
          const [label, color] = STATUS[r.status] || [r.status, '#e9edf8'];
          const live = ['issued', 'scheduled', 'sent'].includes(r.status);
          return (
            <div key={r.id} className="rc-box" style={{ margin: 0, padding: '12px 14px' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px', alignItems: 'center' }}>
                <b style={{ fontSize: 18 }}>${r.amount}</b>
                <span style={{ color, fontWeight: 700, fontSize: 13 }}>{label}{r.status === 'scheduled' && r.deliver_on ? ` for ${r.deliver_on}` : ''}</span>
                <button type="button" onClick={() => copy(r.code)} style={{ ...btn, padding: '3px 8px', fontFamily: 'Consolas, Menlo, monospace', fontSize: 13 }} title="Copy">{r.code}</button>
                <span style={{ marginLeft: 'auto', opacity: 0.7, fontSize: 13 }}>{when(r.created_at)}</span>
              </div>
              <div style={{ fontSize: 14, marginTop: 6, opacity: 0.9, overflowWrap: 'anywhere' }}>
                {r.order_id ? <>Bought by <b>{r.buyer_name || r.buyer_email}</b></> : <>Free from CMTV{r.note ? ` · ${r.note}` : ''}</>}
                {' → '}{r.to_name || r.to_email || 'given by hand'}{r.to_email && r.to_name ? ` (${r.to_email})` : ''}
                {r.status === 'redeemed' && <> · redeemed by <b>{r.redeemed_by_name || 'a customer'}</b> {when(r.redeemed_at)}</>}
                {r.buyer_bonus ? ` · buyer got $${r.buyer_bonus} back` : ''}
              </div>
              {r.send_error && <div style={{ color: '#fca5a5', fontSize: 13, marginTop: 4 }}>Email failed: {r.send_error}</div>}
              {live && (
                <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                  <button type="button" style={btn} onClick={() => resend(r)}>{r.to_email ? 'Resend / change email' : 'Email it'}</button>
                  <button type="button" style={{ ...btn, color: '#fca5a5' }} onClick={() => voidIt(r)}>Void</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
