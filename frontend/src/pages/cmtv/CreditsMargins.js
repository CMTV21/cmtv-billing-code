// CMTV local addition 2026-09-27: Admin > Finances > Credits & margins (backend: cmtv_finance.py /credits).
// Credit purchases per provider -> average cost per credit (credits on hand blended with each new batch), and the
// pricing sheet: every plan's credits, store price, cost, profit and margin, with a test price per row.
import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const money = (v, d = 2) => `$${Number(v || 0).toLocaleString('en-CA', { minimumFractionDigits: d, maximumFractionDigits: d })}`;
const cpcFmt = (v) => `$${Number(v || 0).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}`;
const today = () => new Date().toISOString().slice(0, 10);
const errText = (e, f) => e?.response?.data?.detail || f;
const term = (m) => (m === 12 ? '12 months' : `${m} month${m > 1 ? 's' : ''}`);
function marginClass(m) {
  if (m === null || m === undefined) return '';
  if (m < 50) return 'bad';
  if (m < 70) return 'warn';
  return 'ok';
}

function Purchase({ server, onSaved }) {
  const [f, setF] = useState({ date: today(), credits: '', total_paid: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const per = Number(f.credits) > 0 && f.total_paid !== '' ? Number(f.total_paid) / Number(f.credits) : null;
  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await api.post('/api/cmtv/finance/credits/purchases', { server, ...f, credits: Number(f.credits), total_paid: Number(f.total_paid) });
      toast.success(`Saved. ${server} now costs ${cpcFmt(data.cost_per_credit)} a credit${data.recosted ? `; ${data.recosted} sale${data.recosted > 1 ? 's' : ''} re-costed` : ''}`);
      setF({ date: today(), credits: '', total_paid: '', notes: '' });
      onSaved();
    } catch (err) { toast.error(errText(err, "Couldn't save the purchase")); }
    setSaving(false);
  };
  return (
    <form className="form cm-buy" onSubmit={save}>
      <label>Date<input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} required /></label>
      <label>Credits<input type="number" step="0.5" min="0" value={f.credits} onChange={(e) => setF({ ...f, credits: e.target.value })} placeholder="200" required /></label>
      <label>Total paid<input type="number" step="0.01" min="0" value={f.total_paid} onChange={(e) => setF({ ...f, total_paid: e.target.value })} placeholder="500.00" required /></label>
      <label>Note<input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="optional" /></label>
      <div className="calc">
        <span>Per credit <b>{per === null ? '-' : cpcFmt(per)}</b></span>
        <button className="btn primary" type="submit" disabled={saving}>{saving ? 'Saving...' : 'Add purchase'}</button>
      </div>
    </form>
  );
}

function ServerCard({ s, onSaved }) {
  const [open, setOpen] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const remove = async (id) => {
    try {
      const { data } = await api.delete(`/api/cmtv/finance/credits/purchases/${id}`);
      toast.success(`Purchase removed${data.recosted ? `; ${data.recosted} sale${data.recosted > 1 ? 's' : ''} re-costed` : ''}`);
      onSaved();
    } catch (e) { toast.error(errText(e, "Couldn't remove it")); }
    setConfirmId(null);
  };
  return (
    <div className="panel cm-server">
      <div className="cm-head">
        <div>
          <h2>{s.server}</h2>
          <p className="hint">{s.from_purchases
            ? `Average of the credits on hand · about ${s.stock} credits left`
            : 'Fixed rate (no purchases recorded yet)'}</p>
        </div>
        <div className="cm-cpc"><span>{cpcFmt(s.cost_per_credit)}</span><small>per credit</small></div>
      </div>
      {s.purchases.length > 0 && (
        <div className="scroll"><table>
          <thead><tr><th>Date</th><th className="n">Credits</th><th className="n">Paid</th><th className="n">Per credit</th><th>Note</th><th /></tr></thead>
          <tbody>{s.purchases.map((b) => (
            <tr key={b.id}>
              <td>{String(b.date).slice(0, 10)}</td><td className="n">{b.credits}</td><td className="n">{money(b.total_paid)}</td>
              <td className="n">{cpcFmt(b.per_credit)}</td><td>{b.notes || '-'}</td>
              <td className="n">{confirmId === b.id
                ? <><button type="button" className="btn small danger" onClick={() => remove(b.id)}>Remove</button> <button type="button" className="btn small" onClick={() => setConfirmId(null)}>Keep</button></>
                : <button type="button" className="btn small" onClick={() => setConfirmId(b.id)}>Remove</button>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {open ? <Purchase server={s.server} onSaved={() => { setOpen(false); onSaved(); }} />
        : <button type="button" className="btn small" onClick={() => setOpen(true)}>+ Add a credit purchase</button>}
    </div>
  );
}

function MarginRow({ r, onCreditsSaved }) {
  const [test, setTest] = useState('');
  const [credits, setCredits] = useState(String(r.credits));
  const [saving, setSaving] = useState(false);
  const cr = Number(credits) || 0;
  const cost = Math.round(cr * r.cost_per_credit * 100) / 100;
  const price = test !== '' ? Number(test) : r.price;
  const profit = price === null || price === undefined ? null : price - cost;
  const margin = price ? Math.round((profit / price) * 1000) / 10 : null;
  const saveCredits = async () => {
    if (Number(credits) === r.credits) return;
    setSaving(true);
    try {
      await api.put('/api/cmtv/finance/credits/table', { server: r.server, connections: r.connections, months: r.months, credits: Number(credits) });
      toast.success(`${r.server} ${r.connections} device${r.connections > 1 ? 's' : ''}, ${term(r.months)}: ${credits} credits`);
      onCreditsSaved();
    } catch (e) { toast.error(errText(e, "Couldn't save")); setCredits(String(r.credits)); }
    setSaving(false);
  };
  return (
    <tr className={test !== '' ? 'testing' : ''}>
      <td className="n">{r.connections}</td>
      <td>{term(r.months)}</td>
      <td className="n"><input className="cm-num" type="number" step="0.5" min="0" value={credits} disabled={saving}
        aria-label="Credits" onChange={(e) => setCredits(e.target.value)} onBlur={saveCredits}
        onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }} /></td>
      <td className="n">{r.price === null ? <span className="muted" title="No product in the store for this plan">not sold</span> : money(r.price, 0)}</td>
      <td className="n"><input className="cm-num" type="number" step="1" min="0" value={test} placeholder="try" aria-label="Test price"
        onChange={(e) => setTest(e.target.value)} /></td>
      <td className="n">{money(cost)}</td>
      <td className="n">{profit === null ? '-' : money(profit)}</td>
      <td className="n">{margin === null ? '-' : <span className={`pill ${marginClass(margin)}`}>{margin.toFixed(1)}%</span>}</td>
    </tr>
  );
}

export default function CreditsMargins() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['fin-credits'],
    queryFn: async () => (await api.get('/api/cmtv/finance/credits')).data,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['fin-credits'] });
    qc.invalidateQueries({ queryKey: ['fin-summary'] });
    qc.invalidateQueries({ queryKey: ['fin-tx'] });
    qc.invalidateQueries({ queryKey: ['fin-config'] });
  };
  const byServer = useMemo(() => {
    const m = {};
    (data?.margins || []).forEach((r) => { (m[r.server] = m[r.server] || []).push(r); });
    return m;
  }, [data]);
  if (error) return <p className="empty">Couldn't load credits and margins.</p>;
  if (isLoading || !data) return <div className="spinner" />;
  const withCredits = data.servers.filter((s) => byServer[s.server] || s.from_purchases);
  return (
    <>
      <p className="hint cm-intro">Add each credit purchase and the cost per credit updates itself: new credits are blended with the ones you still have
        (for example 100 at $3 plus 200 at $2.50 = $2.67). Sales from your first recorded purchase on are re-costed; earlier months keep their old cost.</p>
      <div className="grid2">
        {withCredits.map((s) => <ServerCard key={s.server} s={s} onSaved={refresh} />)}
      </div>
      {Object.entries(byServer).map(([server, rows]) => (
        <div className="panel" key={server}>
          <h2>{server} plans</h2>
          <p className="hint">Store prices from billing, cost at {cpcFmt(rows[0].cost_per_credit)} a credit. Type a test price to see its margin (nothing is changed); edit credits to update what a plan uses.</p>
          <div className="scroll"><table className="cm-table">
            <thead><tr><th className="n">Devices</th><th>Length</th><th className="n">Credits</th><th className="n">Store price</th><th className="n">Test price</th><th className="n">Cost</th><th className="n">Profit</th><th className="n">Margin</th></tr></thead>
            <tbody>{rows.map((r) => <MarginRow key={`${r.connections}-${r.months}-${r.credits}-${r.cost_per_credit}`} r={r} onCreditsSaved={refresh} />)}</tbody>
          </table></div>
        </div>
      ))}
    </>
  );
}
