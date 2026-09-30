// CMTV local addition 2026-09-25: Admin > Finances (backend: cmtv_finance.py). Replaces the CMTV Financials spreadsheet.
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ChevronLeft, ChevronRight, Download, Plus, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/cmtv-finance.css';
import CreditsMargins from './CreditsMargins';   // 2026-09-27: Credits & margins tab
import FinanceInbox from './FinanceInbox';   // 2026-09-30: Needs recording tab

const money = (v) => `$${Number(v || 0).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (a, b) => (b ? Math.round(((a - b) / Math.abs(b)) * 100) : null);
const monthLabel = (ym, style = 'long') => new Date(`${ym}-01T12:00:00`).toLocaleDateString('en-CA', { month: style, year: 'numeric' });
const shiftMonth = (ym, n) => { const d = new Date(`${ym}-01T12:00:00`); d.setMonth(d.getMonth() + n); return d.toISOString().slice(0, 7); };
const today = () => new Date().toISOString().slice(0, 10);
const errText = (e, f) => e?.response?.data?.detail || f;

function Change({ now, before }) {
  const c = pct(now, before);
  if (c === null) return null;
  return <span className={c >= 0 ? 'up' : 'down'}>{c >= 0 ? '▲' : '▼'} {Math.abs(c)}%</span>;
}

function MonthsChart({ months }) {
  const [hover, setHover] = useState(null);
  const W = 640, H = 270, L = 48, R = 10, T = 14, B = 28;
  const top = Math.max(1000, ...months.map((m) => m.revenue));
  const step = top > 8000 ? 2500 : top > 4000 ? 1500 : 1000;
  const max = Math.ceil(top / step) * step;
  const pw = (W - L - R) / months.length, bw = Math.min(30, pw * 0.62);
  const y = (v) => T + (H - T - B) * (1 - Math.max(0, v) / max);
  const grid = [];
  for (let g = 0; g <= max; g += step) grid.push(g);
  const h = hover !== null ? months[hover] : null;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monthly revenue split into profit and costs">
        {grid.map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="#202b4a" />
            <text x={L - 8} y={y(g) + 4} fill="#6b7799" fontSize="11" textAnchor="end">{g ? `$${g / 1000}k` : '$0'}</text>
          </g>
        ))}
        {months.map((m, i) => {
          const x = L + i * pw + (pw - bw) / 2, cost = Math.min(m.costs, m.revenue), yc = y(cost), yr = y(m.revenue);
          const dim = hover !== null && hover !== i ? 0.45 : 1;
          return (
            <g key={m.month} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={L + i * pw} y={T} width={pw} height={H - T - B} fill="transparent" />
              {cost > 0 && <path d={`M${x},${y(0)} V${yc} H${x + bw} V${y(0)} Z`} fill="#8b5cf6" opacity={dim} />}
              {m.revenue > cost && (
                <path d={`M${x},${yc - 2} V${yr + 4} Q${x},${yr} ${x + 4},${yr} H${x + bw - 4} Q${x + bw},${yr} ${x + bw},${yr + 4} V${yc - 2} Z`} fill="#1596b3" opacity={dim} />
              )}
              <text x={x + bw / 2} y={H - 10} fill="#9aa6c6" fontSize="10.5" textAnchor="middle">{monthLabel(m.month, 'short').split(' ')[0]}</text>
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="tip" style={{ left: `${Math.min(70, (hover / months.length) * 100 + 4)}%`, top: 8 }}>
          <b>{monthLabel(h.month)}</b>
          <div className="r"><span>Revenue</span><span>{money(h.revenue)}</span></div>
          <div className="r"><span><span className="dot" style={{ background: '#1596b3' }} />Profit</span><span>{money(h.profit)}</span></div>
          <div className="r"><span><span className="dot" style={{ background: '#8b5cf6' }} />Costs</span><span>{money(h.costs)}</span></div>
          <div className="r"><span>Margin</span><span>{h.revenue ? `${Math.round((h.profit / h.revenue) * 100)}%` : '-'}</span></div>
        </div>
      )}
    </div>
  );
}

function RecordPayment({ cfg, onSaved }) {
  const blank = { date: today(), server: 'CCTV', customer: '', amount: '', method: 'e-Transfer', credits: '', new_user: false, notes: '' };
  const [f, setF] = useState(blank);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const rate = useMemo(() => {
    const d = new Date(`${f.date}T12:00:00`);
    // 2026-09-27: from credit purchases (average of credits on hand) once a server has any, else the dated rates
    const pts = (cfg?.avg?.[f.server] || []).filter(([when]) => new Date(when) <= d);
    if (pts.length) return pts[pts.length - 1][1];
    const rs = (cfg?.rates || []).filter((r) => r.server === f.server && (!r.from || new Date(r.from) <= d));
    rs.sort((a, b) => new Date(a.from || 0) - new Date(b.from || 0));
    return rs.length ? rs[rs.length - 1].cost_per_credit : 0;
  }, [cfg, f.date, f.server]);
  const amt = Number(f.amount) || 0, cr = Number(f.credits) || 0;
  const fee = f.method === 'PayPal' && amt ? Math.round((amt * (cfg?.paypal_fee?.pct ?? 0.0349) + (cfg?.paypal_fee?.fixed ?? 0.49)) * 100) / 100 : 0;
  const cost = Math.round(cr * rate * 100) / 100;
  const save = async (e) => {
    e.preventDefault();
    if (!f.amount) { toast.error('Enter the amount received'); return; }
    setSaving(true);
    try {
      await api.post('/api/cmtv/finance/transactions', { ...f, amount: amt, credits: cr });
      toast.success('Payment recorded');
      setF({ ...blank, date: f.date, method: f.method });
      onSaved();
    } catch (err) { toast.error(errText(err, "Couldn't save the payment")); }
    setSaving(false);
  };
  return (
    <form className="form" onSubmit={save}>
      <label htmlFor="rp-date">Date<input id="rp-date" type="date" value={f.date} onChange={set('date')} required /></label>
      <label htmlFor="rp-server">Server<select id="rp-server" value={f.server} onChange={set('server')}>{(cfg?.servers || []).map((s) => <option key={s}>{s}</option>)}</select></label>
      <label htmlFor="rp-customer">Customer<input id="rp-customer" value={f.customer} onChange={set('customer')} placeholder="Name" /></label>
      <label htmlFor="rp-amount">Amount received<input id="rp-amount" type="number" step="0.01" value={f.amount} onChange={set('amount')} placeholder="120.00" /></label>
      <label htmlFor="rp-method">Method<select id="rp-method" value={f.method} onChange={set('method')}>{(cfg?.methods || []).map((m) => <option key={m}>{m}</option>)}</select></label>
      <label htmlFor="rp-credits">Credits used<input id="rp-credits" type="number" step="0.5" value={f.credits} onChange={set('credits')} placeholder="12" /></label>
      <label htmlFor="rp-notes">Notes<input id="rp-notes" value={f.notes} onChange={set('notes')} /></label>
      <label htmlFor="rp-new" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 20 }}><input id="rp-new" type="checkbox" checked={f.new_user} onChange={set('new_user')} /> New customer</label>
      <div className="calc">
        <span>Cost per credit <b>{money(rate)}</b></span><span>PayPal fee <b>{money(fee)}</b></span>
        <span>Total cost <b>{money(cost)}</b></span><span>Profit <b>{money(amt - cost - fee)}</b></span>
        <button className="btn primary" type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save payment'}</button>
      </div>
    </form>
  );
}

function AddExpense({ cfg, onSaved }) {
  const blank = { date: today(), category: 'Hosting', description: '', amount: '', notes: '' };
  const [f, setF] = useState(blank);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = async (e) => {
    e.preventDefault();
    if (!f.amount) { toast.error('Enter the amount'); return; }
    setSaving(true);
    try {
      await api.post('/api/cmtv/finance/expenses', { ...f, amount: Number(f.amount) });
      toast.success('Expense added');
      setF({ ...blank, date: f.date, category: f.category });
      onSaved();
    } catch (err) { toast.error(errText(err, "Couldn't save the expense")); }
    setSaving(false);
  };
  return (
    <form className="form" onSubmit={save}>
      <label htmlFor="ex-date">Date<input id="ex-date" type="date" value={f.date} onChange={set('date')} required /></label>
      <label htmlFor="ex-cat">Category<select id="ex-cat" value={f.category} onChange={set('category')}>{(cfg?.expense_categories || []).map((c) => <option key={c}>{c}</option>)}</select></label>
      <label htmlFor="ex-desc">Description<input id="ex-desc" value={f.description} onChange={set('description')} placeholder="Server rent" /></label>
      <label htmlFor="ex-amt">Amount<input id="ex-amt" type="number" step="0.01" value={f.amount} onChange={set('amount')} placeholder="30.00" /></label>
      <label htmlFor="ex-notes">Notes<input id="ex-notes" value={f.notes} onChange={set('notes')} /></label>
      <div className="calc"><button className="btn primary" type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save expense'}</button></div>
    </form>
  );
}

function Transactions({ month }) {
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [source, setSource] = useState('');
  const [confirmId, setConfirmId] = useState(null);
  const { data: rows, isLoading } = useQuery({
    queryKey: ['fin-tx', month, q, source],
    queryFn: async () => (await api.get('/api/cmtv/finance/transactions', { params: { month, q, source } })).data,
  });
  const remove = async (id) => {
    try {
      await api.delete(`/api/cmtv/finance/transactions/${id}`);
      toast.success('Payment removed');
      qc.invalidateQueries({ queryKey: ['fin-tx'] }); qc.invalidateQueries({ queryKey: ['fin-summary'] });
    } catch (e) { toast.error(errText(e, "Couldn't remove it")); }
    setConfirmId(null);
  };
  const tag = (r) => r.source === 'billing' ? <span className="pill bill">Billing{r.auto_renewal ? ' · auto-renew' : ''}</span>
    : r.source === 'manual' ? <span className="pill">Recorded</span> : <span className="pill">Imported</span>;
  return (
    <>
      <div className="filters">
        <input aria-label="Search payments" placeholder="Search customer, server or notes" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option><option value="billing">Billing</option><option value="manual">Recorded</option><option value="import">Imported</option>
        </select>
      </div>
      {isLoading ? <div className="spinner" /> : !rows?.length ? <p className="empty">No payments in {monthLabel(month)}.</p> : (
        <div className="scroll"><table>
          <thead><tr><th>Date</th><th>Customer</th><th>Server</th><th>Method</th><th className="n">Amount</th><th className="n">Credits</th><th className="n">Cost</th><th className="n">Fee</th><th className="n">Profit</th><th>Source</th><th /></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td>{String(r.date).slice(0, 10)}</td>
              <td>{r.customer || '-'}{r.new_user && <span className="pill" style={{ marginLeft: 6 }}>new</span>}</td>
              <td>{r.server}</td><td>{r.method || '-'}</td>
              <td className="n">{money(r.amount)}</td><td className="n">{r.credits || 0}</td>
              <td className="n">{money(r.total_cost)}</td><td className="n">{r.paypal_fee ? money(r.paypal_fee) : '-'}</td>
              <td className="n">{money(r.profit)}</td>
              <td>{tag(r)}{r.needs_review && <span className="pill warn" style={{ marginLeft: 6 }} title={r.notes}>check credits</span>}</td>
              <td className="n">{confirmId === r.id
                ? <><button type="button" className="btn small danger" onClick={() => remove(r.id)}>Remove</button> <button type="button" className="btn small" onClick={() => setConfirmId(null)}>Keep</button></>
                : <button type="button" className="btn small" onClick={() => setConfirmId(r.id)} aria-label={`Remove payment from ${r.customer || 'customer'}`}>Remove</button>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}

export default function FinancesPage() {
  const qc = useQueryClient();
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [panel, setPanel] = useState(null);   // 'payment' | 'expense' | null
  const [tab, setTab] = useState('overview');   // 2026-09-27: 'overview' | 'credits'
  const [busy, setBusy] = useState('');
  const { data: s, isLoading } = useQuery({
    queryKey: ['fin-summary', month],
    queryFn: async () => (await api.get('/api/cmtv/finance/summary', { params: { month } })).data,
  });
  const { data: cfg } = useQuery({ queryKey: ['fin-config'], queryFn: async () => (await api.get('/api/cmtv/finance/config')).data });
  const refresh = () => { qc.invalidateQueries({ queryKey: ['fin-summary'] }); qc.invalidateQueries({ queryKey: ['fin-tx'] }); };

  const exportXlsx = async () => {
    setBusy('export');
    try {
      const r = await api.get('/api/cmtv/finance/export', { responseType: 'blob' });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a');
      a.href = url; a.download = `CMTV-finances-${today()}.xlsx`; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) { toast.error("Couldn't create the Excel file"); }
    setBusy('');
  };
  const sync = async () => {
    setBusy('sync');
    try {
      const { data } = await api.post('/api/cmtv/finance/sync');
      toast.success(data.added ? `${data.added} billing order${data.added > 1 ? 's' : ''} added` : 'Billing orders are up to date');
      refresh();
    } catch (e) { toast.error(errText(e, 'Sync failed')); }
    setBusy('');
  };

  const cur = new Date().toISOString().slice(0, 7);
  return (
    <div className="cmtv-fin">
      <div className="wrap">
        <div className="top">
          <h1><Link to="/admin" aria-label="Back to admin"><ArrowLeft className="w-5 h-5" /></Link>
            <span>Finances<small>All income, costs and profit in one place</small></span></h1>
          <span className="monthnav">
            <button type="button" className="btn small" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}><ChevronLeft className="w-4 h-4" /></button>
            {monthLabel(month)}
            <button type="button" className="btn small" aria-label="Next month" disabled={month >= cur} onClick={() => setMonth(shiftMonth(month, 1))}><ChevronRight className="w-4 h-4" /></button>
          </span>
          <button type="button" className="btn" onClick={() => setPanel(panel === 'expense' ? null : 'expense')}><Plus className="w-4 h-4" /> Add expense</button>
          <button type="button" className="btn primary" onClick={() => setPanel(panel === 'payment' ? null : 'payment')}><Plus className="w-4 h-4" /> Record payment</button>
          <button type="button" className="btn" onClick={exportXlsx} disabled={busy === 'export'}><Download className="w-4 h-4" /> {busy === 'export' ? 'Preparing...' : 'Export to Excel'}</button>
        </div>

        <div className="cm-tabs" role="tablist" aria-label="Finances view">
          {[['overview', 'Overview'], ['inbox', `Needs recording${s?.billing?.to_record ? ` (${s.billing.to_record})` : ''}`], ['credits', 'Credits & margins']].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>

        {tab === 'credits' ? <CreditsMargins /> : tab === 'inbox' ? <FinanceInbox cfg={cfg} onChanged={refresh} /> : (<>
        {panel && (
          <div className="panel">
            <h2>{panel === 'payment' ? 'Record payment' : 'Add expense'}</h2>
            <p className="hint">{panel === 'payment'
              ? "For money that doesn't go through billing. Billing's own orders are added automatically; don't record them here."
              : 'Running costs: hosting, apps, equipment, free trials and referral credits.'}</p>
            {panel === 'payment' ? <RecordPayment cfg={cfg} onSaved={refresh} /> : <AddExpense cfg={cfg} onSaved={refresh} />}
          </div>
        )}

        {isLoading || !s ? <div className="spinner" /> : (
          <>
            <div className="tiles">
              <div className="tile"><div className="lab">Revenue</div><div className="val">{money(s.mtd.revenue)}</div>
                <div className="sub"><Change now={s.mtd.revenue} before={s.prev.revenue} /> vs {monthLabel(shiftMonth(month, -1), 'short')} · YTD {money(s.ytd.revenue)}</div></div>
              <div className="tile"><div className="lab"><span className="dot" style={{ background: '#8b5cf6' }} />Costs</div><div className="val">{money(s.mtd.costs)}</div>
                <div className="sub">credits {money(s.mtd.credit_cost)} · fees {money(s.mtd.fees)} · expenses {money(s.mtd.expenses)}</div></div>
              <div className="tile"><div className="lab"><span className="dot" style={{ background: '#1596b3' }} />Net profit</div><div className="val">{money(s.mtd.profit)}</div>
                <div className="sub"><Change now={s.mtd.profit} before={s.prev.profit} /> · {s.mtd.revenue ? Math.round((s.mtd.profit / s.mtd.revenue) * 100) : 0}% margin · YTD {money(s.ytd.profit)}</div></div>
              <div className="tile"><div className="lab">New customers</div><div className="val">{s.mtd.new_users}</div>
                <div className="sub">{s.mtd.payments} payments this month · {s.ytd.new_users} new this year</div></div>
            </div>

            <div className="grid2">
              <div className="panel">
                <h2>Last 12 months</h2>
                <p className="hint">Each bar is a month's revenue, split into profit and costs. Hover a month for the numbers.</p>
                <div className="legend"><span><span className="dot" style={{ background: '#1596b3' }} />Profit</span><span><span className="dot" style={{ background: '#8b5cf6' }} />Costs</span></div>
                <MonthsChart months={s.months} />
              </div>
              <div className="panel">
                <h2>Margin by server</h2>
                <p className="hint">All time. Revenue minus credit costs and PayPal fees.</p>
                <div className="scroll"><table>
                  <thead><tr><th>Server</th><th className="n">Revenue</th><th className="n">Margin</th><th className="barcell" /></tr></thead>
                  <tbody>{s.servers.map((r) => (
                    <tr key={r.server}><td>{r.server}{r.margin !== null && r.margin < 0 && <span className="pill bad" style={{ marginLeft: 6 }}>loses money</span>}</td>
                      <td className="n">{money(r.revenue)}</td><td className="n">{r.margin === null ? '-' : `${(r.margin * 100).toFixed(1)}%`}</td>
                      <td className="barcell">{r.margin > 0 && <span className="bar" style={{ width: `${Math.min(100, r.margin * 100)}%` }} />}</td></tr>
                  ))}</tbody>
                </table></div>
              </div>
            </div>

            <div className="tiles">
              <div className="tile"><div className="lab">Active services</div><div className="val">{s.billing.active_services}</div><div className="sub">in billing right now</div></div>
              <div className="tile"><div className="lab">Renewals due · 30 days</div><div className="val">{s.billing.due_30d}</div><div className="sub">services expiring soon</div></div>
              <div className="tile"><div className="lab">On PayPal auto-renew</div><div className="val">{s.billing.auto_renew}</div><div className="sub">renew by themselves</div></div>
              <div className="tile"><div className="lab">Paying customers</div><div className="val">{s.billing.paying_customers}</div><div className="sub">with a paid billing order</div></div>
            </div>

            <div className="grid2">
              <div className="panel">
                <h2 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>Payments · {monthLabel(month)}
                  <button type="button" className="btn small" onClick={sync} disabled={busy === 'sync'} style={{ marginLeft: 'auto' }}><RefreshCw className="w-3.5 h-3.5" /> {busy === 'sync' ? 'Checking...' : 'Check billing orders'}</button></h2>
                <p className="hint">Billing orders add themselves every 10 minutes{cfg?.cutover ? ` (from ${String(cfg.cutover).slice(0, 10)})` : ''}. {s.billing.needs_review > 0 && <span className="pill warn">{s.billing.needs_review} need a credits check</span>}
                  {s.billing.to_record > 0 && <button type="button" className="pill warn" style={{ marginLeft: 6, cursor: 'pointer', border: 0 }} onClick={() => setTab('inbox')}>{s.billing.to_record} sale{s.billing.to_record > 1 ? 's' : ''} to record</button>}</p>
                <Transactions month={month} />
              </div>
              <div className="panel">
                <h2>Expenses by category</h2>
                <p className="hint">All time · {money(s.expense_categories.reduce((a, c) => a + c.total, 0))}</p>
                <div className="scroll"><table><tbody>{s.expense_categories.map((c) => (
                  <tr key={c.category}><td>{c.category}</td><td className="n">{money(c.total)}</td>
                    <td className="barcell"><span className="bar" style={{ background: '#8b5cf6', width: `${(c.total / (s.expense_categories[0]?.total || 1)) * 100}%` }} /></td></tr>
                ))}</tbody></table></div>
              </div>
            </div>
          </>
        )}
        </>)}
      </div>
    </div>
  );
}
