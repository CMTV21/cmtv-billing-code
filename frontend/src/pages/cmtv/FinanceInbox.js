// CMTV local addition 2026-09-30: Finances > Needs recording (backend: cmtv_fin_inbox.py).
// Sales billing noticed but didn't take (renewals done on the panel, e-Transfers with no order). Nothing reaches the ledger
// until the owner checks the figures and clicks Record, or clicks Not a sale.
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../api/api';

const money = (v) => `$${Number(v || 0).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const day = (d) => (d ? new Date(d).toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' }) : '');
const errText = (e, f) => e?.response?.data?.detail || f;

function headline(it) {
  if (it.kind === 'etransfer') return <>e-Transfer <b>{money(it.amount)}</b> from <b>{it.sender}</b> · no order matched</>;
  const plan = `${it.server} · ${it.connections || '?'} connection${it.connections === 1 ? '' : 's'} · ${it.months} month${it.months === 1 ? '' : 's'}`;
  return (
    <>
      <b>{it.customer}</b> {it.kind === 'panel_renewal' ? 'renewed on the panel' : 'new line made on the panel'} · {plan}
      <span className="sub"> · line {it.username}{it.old_expiry ? `: ${day(it.old_expiry)} → ${day(it.new_expiry)}` : ` until ${day(it.new_expiry)}`}</span>
    </>
  );
}

function Item({ it, cfg, onDone }) {
  const [f, setF] = useState({
    date: String(it.date).slice(0, 10), server: it.server || 'CCTV', customer: it.customer || '',
    amount: it.amount ?? '', method: it.method || 'e-Transfer', credits: it.credits ?? '', new_user: !!it.new_user,
    notes: it.kind === 'etransfer' ? `e-Transfer ${it.etransfer_ref || ''}`.trim()
      : `${it.kind === 'panel_renewal' ? 'Renewed' : 'New line'} on the panel: ${it.username}, ${it.months} mo${it.etransfer_ref ? `, e-Transfer ${it.etransfer_ref}` : ''}`,
  });
  const [busy, setBusy] = useState('');
  const [why, setWhy] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const record = async () => {
    if (f.amount === '' || f.amount === null) { toast.error('Enter the amount received'); return; }
    setBusy('record');
    try {
      await api.post(`/api/cmtv/finance/inbox/${it.id}/record`, { ...f, amount: Number(f.amount), credits: Number(f.credits) || 0 });
      toast.success('Recorded in the ledger');
      onDone();
    } catch (e) { toast.error(errText(e, "Couldn't record it")); }
    setBusy('');
  };
  const dismiss = async () => {
    setBusy('dismiss');
    try {
      await api.post(`/api/cmtv/finance/inbox/${it.id}/dismiss`, { reason: why || '' });
      toast.success('Marked as not a sale');
      onDone();
    } catch (e) { toast.error(errText(e, "Couldn't update it")); }
    setBusy('');
  };
  const id = (k) => `fi-${it.id}-${k}`;
  return (
    <div className="panel" style={{ marginBottom: 12 }}>
      <p style={{ margin: '0 0 6px' }}>{headline(it)}</p>
      <p className="hint" style={{ marginTop: 0 }}>
        {it.amount_from === 'e-Transfer' ? `Amount from the e-Transfer email${it.message ? ` · message: “${it.message}”` : ''}.`
          : it.amount_from === 'store price' ? 'Amount is the store price for this plan: change it to what they actually paid.'
            : 'Enter what they paid.'}
        {it.kind !== 'etransfer' && it.credits_known === false && ' Credits for this plan aren\'t in the credits table: enter them.'}
      </p>
      <div className="form">
        <label htmlFor={id('date')}>Date<input id={id('date')} type="date" value={f.date} onChange={set('date')} /></label>
        <label htmlFor={id('server')}>Server<select id={id('server')} value={f.server} onChange={set('server')}>{(cfg?.servers || []).map((s) => <option key={s}>{s}</option>)}</select></label>
        <label htmlFor={id('cust')}>Customer<input id={id('cust')} value={f.customer} onChange={set('customer')} /></label>
        <label htmlFor={id('amt')}>Amount received<input id={id('amt')} type="number" step="0.01" value={f.amount} onChange={set('amount')} /></label>
        <label htmlFor={id('method')}>Method<select id={id('method')} value={f.method} onChange={set('method')}>{(cfg?.methods || []).map((m) => <option key={m}>{m}</option>)}</select></label>
        <label htmlFor={id('cr')}>Credits used<input id={id('cr')} type="number" step="0.5" value={f.credits} onChange={set('credits')} /></label>
        <label htmlFor={id('notes')}>Notes<input id={id('notes')} value={f.notes} onChange={set('notes')} /></label>
        <label htmlFor={id('new')} style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 20 }}>
          <input id={id('new')} type="checkbox" checked={f.new_user} onChange={set('new_user')} /> New customer</label>
        <div className="calc">
          {why === null ? (
            <>
              <button type="button" className="btn primary" disabled={!!busy} onClick={record}>{busy === 'record' ? 'Saving...' : 'Record'}</button>
              <button type="button" className="btn" disabled={!!busy} onClick={() => setWhy('')}>Not a sale</button>
            </>
          ) : (
            <>
              <input aria-label="Why it isn't a sale (optional)" placeholder="Why? e.g. free extension, test line (optional)" value={why}
                onChange={(e) => setWhy(e.target.value)} style={{ minWidth: 260 }} />
              <button type="button" className="btn" disabled={!!busy} onClick={dismiss}>{busy === 'dismiss' ? 'Saving...' : 'Confirm'}</button>
              <button type="button" className="btn" onClick={() => setWhy(null)}>Back</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function FinanceInbox({ cfg, onChanged }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ['fin-inbox'], queryFn: async () => (await api.get('/api/cmtv/finance/inbox')).data });
  const done = () => { qc.invalidateQueries({ queryKey: ['fin-inbox'] }); onChanged?.(); };
  const scan = async () => {
    setBusy(true);
    try {
      const { data: r } = await api.post('/api/cmtv/finance/inbox/scan');
      toast.success(r.new ? `${r.new} new to record` : 'Nothing new');
      done();
    } catch (e) { toast.error(errText(e, 'Check failed')); }
    setBusy(false);
  };
  const reopen = async (id) => {
    try { await api.post(`/api/cmtv/finance/inbox/${id}/reopen`); done(); } catch (e) { toast.error(errText(e, "Couldn't reopen it")); }
  };
  return (
    <>
      <div className="panel">
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>Needs recording
          <button type="button" className="btn small" onClick={scan} disabled={busy} style={{ marginLeft: 'auto' }}>
            <RefreshCw className="w-3.5 h-3.5" /> {busy ? 'Checking...' : 'Check now'}</button></h2>
        <p className="hint">Sales billing noticed but didn't take itself: lines renewed or made straight on the panel, and e-Transfers
          that matched no order. Check the figures, then Record (it goes into the ledger) or Not a sale. Checked every 10 minutes;
          panel end dates refresh hourly. Sales billing can't see (cash, a line renewed on the panel you haven't synced yet) still go
          in Record payment.</p>
      </div>
      {isLoading ? <div className="spinner" /> : !data?.open?.length
        ? <div className="panel"><p className="empty" style={{ margin: 0 }}>Nothing to record right now.</p></div>
        : data.open.map((it) => <Item key={it.id} it={it} cfg={cfg} onDone={done} />)}
      {data?.recent?.length > 0 && (
        <div className="panel">
          <h2>Recently handled</h2>
          <div className="scroll"><table><tbody>{data.recent.map((it) => (
            <tr key={it.id}>
              <td>{day(it.handled_at)}</td>
              <td>{it.kind === 'etransfer' ? `e-Transfer from ${it.sender}` : `${it.customer} · ${it.server} ${it.months} mo`}</td>
              <td>{it.status === 'recorded' ? <span className="pill bill">Recorded</span> : <span className="pill">Not a sale{it.reason ? `: ${it.reason}` : ''}</span>}</td>
              <td className="n">{it.status === 'dismissed' && <button type="button" className="btn small" onClick={() => reopen(it.id)}>Reopen</button>}</td>
            </tr>
          ))}</tbody></table></div>
        </div>
      )}
    </>
  );
}
