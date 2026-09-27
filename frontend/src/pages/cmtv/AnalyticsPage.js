// CMTV local addition 2026-09-27: Admin > Analytics (backend: cmtv_analytics.py). Replaces the developer's page.
// History from the Finances ledger (matches Admin > Finances); the present (active, renewals due) from billing.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import api from '../../api/api';

// validated categorical palette on the navy surface (same as the admin home); "other" is the neutral grey
const FAM = [
  { key: 'cctv', label: 'CCTV', color: '#1596b3' },
  { key: 'imperium', label: 'Imperium', color: '#b08a34' },
  { key: 'addons', label: 'Add-ons', color: '#8b5cf6' },
  { key: 'other', label: 'Other', color: '#6b7799' },
];
const ONE = '#2e8bff';   // single-series charts
const GRID = '#202b4a', AXIS = '#6b7799';
const money = (v, cents = false) => `$${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 })}`;
const monthLabel = (k, long = false) => new Date(`${k}-15T12:00:00`).toLocaleDateString(undefined, long ? { month: 'long', year: 'numeric' } : { month: 'short', year: '2-digit' });
const weekLabel = (d) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const pct = (a, b) => (b ? Math.round(((a - b) / b) * 100) : null);

function Tip({ active, payload, label, render }) {
  if (!active || !payload?.length) return null;
  return <div className="chart-tip">{render(payload[0].payload, label)}</div>;
}
const axisProps = { stroke: AXIS, tick: { fill: AXIS, fontSize: 11 }, tickLine: false, axisLine: { stroke: GRID } };

function Card({ title, sub, children, style }) {
  return (
    <section className="card" style={style}>
      <h2>{title}</h2>
      {sub && <p className="note" style={{ margin: '-6px 0 10px' }}>{sub}</p>}
      {children}
    </section>
  );
}

function HBars({ rows, color = ONE, fmt = (v) => money(v) }) {
  const max = Math.max(...rows.map((r) => r.v), 1);
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hb" key={r.label} style={{ '--c': r.c || color }}>
          <span className="n">{r.label}</span>
          <div className="track"><i style={{ width: `${Math.max(1, (r.v / max) * 100)}%` }} /></div>
          <span className="v">{fmt(r.v)}</span>
        </div>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const [months, setMonths] = useState(12);
  const { data: d, isLoading, error } = useQuery({
    queryKey: ['cmtv-analytics', months],
    queryFn: async () => (await api.get('/api/cmtv/analytics', { params: { months } })).data,
    placeholderData: (prev) => prev,   // keep the charts on screen while another period loads
  });
  const k = d?.kpis;
  const monthly = (d?.monthly || []).map((m) => ({ ...m, label: monthLabel(m.month) }));
  const fams = FAM.filter((f) => monthly.some((m) => m[f.key] > 0));
  const change = k && k.prev_revenue ? pct(k.revenue, k.prev_revenue) : null;

  return (
    <div className="adm-home adm-analytics">
      <div className="top">
        <div>
          <h1>Analytics</h1>
          <p>{d ? `${monthLabel(d.from, true)} to ${monthLabel(d.to, true)} · money from Finances, subscriptions from billing` : 'Loading…'}</p>
        </div>
        <div className="quick" role="group" aria-label="Period">
          {[[6, '6 months'], [12, '12 months'], [18, '18 months']].map(([m, l]) => (
            <button key={m} type="button" className={`btn ${months === m ? 'glow' : ''}`} aria-pressed={months === m} onClick={() => setMonths(m)}>{l}</button>
          ))}
        </div>
      </div>

      {error ? <div className="card" style={{ marginTop: 20 }}>Couldn't load analytics.</div>
        : isLoading || !d ? <div className="skeleton">Loading…</div> : (
        <>
          <section className="kpis" aria-label="Headline numbers">
            <div className="card kpi"><label>Revenue · {months} months</label><div className="big">{money(k.revenue)}</div>
              <div className="delta">{change !== null ? <><span className={change >= 0 ? 'up' : 'down'}>{change >= 0 ? '▲' : '▼'} {Math.abs(change)}%</span> vs the {months} months before</> : 'Finances only goes back to April 2025, so no full period to compare'}</div></div>
            <div className="card kpi"><label>Profit</label><div className="big">{money(k.profit)}</div>
              <div className="delta">{k.margin !== null ? `${k.margin}% margin` : ''} · after credits, PayPal fees and expenses</div></div>
            <div className="card kpi"><label>Typical month</label><div className="big">{k.avg_month !== null ? money(k.avg_month) : '–'}</div>
              <div className="delta">average of the last 3 full months · {money(k.avg_payment)} per payment</div></div>
            <div className="card kpi"><label>Renewals due · 90 days</label><div className="big">{money(k.due90.value)}</div>
              <div className="delta">{k.due90.count} subscriptions · {k.due90.auto_renew} on auto-renew · priced plans only</div></div>
          </section>

          <Card title="Revenue by service" sub="Stacked by service type; hover a month for the breakdown. The current month is so far." style={{ marginBottom: 14 }}>
            <div className="chart-box" style={{ height: 300 }}>
              <ResponsiveContainer>
                <BarChart data={monthly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
                  <CartesianGrid vertical={false} stroke={GRID} />
                  <XAxis dataKey="label" {...axisProps} />
                  <YAxis {...axisProps} tickFormatter={(v) => money(v)} width={58} />
                  <Tooltip cursor={{ fill: 'rgba(154,166,198,.08)' }} content={<Tip render={(m) => (
                    <>
                      <b>{monthLabel(m.month, true)}{m.partial ? ' (so far)' : ''}</b>
                      {fams.map((f) => <span key={f.key} className="row"><i style={{ background: f.color }} />{f.label}<em>{money(m[f.key], true)}</em></span>)}
                      <span className="row total">Total<em>{money(m.revenue, true)}</em></span>
                    </>
                  )} />} />
                  <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12, color: AXIS, paddingTop: 6 }} />
                  {fams.map((f, i) => (
                    <Bar key={f.key} dataKey={f.key} name={f.label} stackId="rev" fill={f.color} stroke="#141d33" strokeWidth={1}
                      radius={i === fams.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}>
                      {monthly.map((m) => <Cell key={m.month} fillOpacity={m.partial ? 0.55 : 1} />)}
                    </Bar>
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid2">
            <Card title="Profit per month" sub="Same maths as Finances. Negative months show below the line.">
              <div className="chart-box" style={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={monthly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
                    <CartesianGrid vertical={false} stroke={GRID} />
                    <XAxis dataKey="label" {...axisProps} />
                    <YAxis {...axisProps} tickFormatter={(v) => money(v)} width={58} />
                    <ReferenceLine y={0} stroke={AXIS} />
                    <Tooltip cursor={{ fill: 'rgba(154,166,198,.08)' }} content={<Tip render={(m) => (
                      <>
                        <b>{monthLabel(m.month, true)}{m.partial ? ' (so far)' : ''}</b>
                        <span className="row">Revenue<em>{money(m.revenue, true)}</em></span>
                        <span className="row">Costs<em>−{money(m.costs, true)}</em></span>
                        {m.expenses > 0 && <span className="row sub">incl. expenses<em>{money(m.expenses, true)}</em></span>}
                        <span className="row total">Profit<em>{money(m.profit, true)}</em></span>
                      </>
                    )} />} />
                    <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
                      {monthly.map((m) => <Cell key={m.month} fill={m.profit < 0 ? '#f87171' : ONE} fillOpacity={m.partial ? 0.55 : 1} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="New customers per month" sub={`${k.new_customers} in the period, from the "new user" column in Finances.`}>
              <div className="chart-box" style={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={monthly} margin={{ top: 8, right: 8, left: -18, bottom: 0 }} barCategoryGap="28%">
                    <CartesianGrid vertical={false} stroke={GRID} />
                    <XAxis dataKey="label" {...axisProps} />
                    <YAxis {...axisProps} allowDecimals={false} />
                    <Tooltip cursor={{ fill: 'rgba(154,166,198,.08)' }} content={<Tip render={(m) => (
                      <><b>{monthLabel(m.month, true)}</b><span className="row">New customers<em>{m.new_customers}</em></span>
                        <span className="row">All payments<em>{m.payments}</em></span></>
                    )} />} />
                    <Bar dataKey="new_customers" fill={ONE} radius={[4, 4, 0, 0]}>
                      {monthly.map((m) => <Cell key={m.month} fillOpacity={m.partial ? 0.55 : 1} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <div className="grid2">
            <Card title="Renewals coming up" sub="Active subscriptions by the week they end (next 13 weeks). Dollar values only count plans with a price in billing; lines imported from the panels count as $0.">
              <div className="chart-box" style={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={d.renewals.map((w) => ({ ...w, label: weekLabel(w.week) }))} margin={{ top: 8, right: 8, left: -18, bottom: 0 }} barCategoryGap="22%">
                    <CartesianGrid vertical={false} stroke={GRID} />
                    <XAxis dataKey="label" {...axisProps} interval={1} />
                    <YAxis {...axisProps} allowDecimals={false} />
                    <Tooltip cursor={{ fill: 'rgba(154,166,198,.08)' }} content={<Tip render={(w) => (
                      <>
                        <b>Week of {weekLabel(w.week)}</b>
                        {FAM.filter((f) => w[f.key]).map((f) => <span key={f.key} className="row"><i style={{ background: f.color }} />{f.label}<em>{w[f.key]}</em></span>)}
                        <span className="row total">{w.count} ending<em>{money(w.value, true)}</em></span>
                      </>
                    )} />} />
                    {FAM.map((f, i) => (
                      <Bar key={f.key} dataKey={f.key} name={f.label} stackId="w" fill={f.color} stroke="#141d33" strokeWidth={1}
                        radius={i === FAM.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Active subscriptions" sub={`${k.active} now (trials and reseller packs not counted)`}>
              <HBars rows={FAM.filter((f) => d.active[f.key]).map((f) => ({ label: f.label, v: d.active[f.key], c: f.color }))} fmt={(v) => v} />
              <h2 style={{ marginTop: 20 }}>By plan length</h2>
              <HBars rows={Object.entries(d.by_term).sort((a, b) => b[1] - a[1]).map(([l, v]) => ({ label: l, v }))} fmt={(v) => v} />
            </Card>
          </div>

          <div className="grid2">
            <Card title="Providers" sub="What each line earns after credit costs and PayPal fees (expenses not included).">
              <div className="tablewrap"><table>
                <thead><tr><th>Provider</th><th className="num">Revenue</th><th className="num">Costs</th><th className="num">Profit</th><th className="num">Margin</th></tr></thead>
                <tbody>{d.providers.map((p) => (
                  <tr key={p.server}>
                    <td><span className="dot" style={{ '--c': (FAM.find((f) => f.key === p.family) || FAM[3]).color }} />{p.server}</td>
                    <td className="num">{money(p.revenue)}</td><td className="num">{money(p.cost)}</td>
                    <td className="num">{money(p.profit)}</td><td className="num">{p.margin !== null ? `${p.margin}%` : '–'}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </Card>
            <Card title="Payment methods" sub="Older spreadsheet rows didn't record a method, so they show as Not recorded.">
              <HBars rows={d.methods.map((m) => ({ label: m.method, v: m.total }))} />
              {d.expenses.length > 0 && (<>
                <h2 style={{ marginTop: 20 }}>Expenses by category</h2>
                <HBars rows={d.expenses.map((e) => ({ label: e.category, v: e.total }))} color="#9aa6c6" />
              </>)}
            </Card>
          </div>

          <Card title="Top customers" sub="By what they paid in the period (names as recorded in Finances).">
            <div className="tablewrap"><table>
              <thead><tr><th>#</th><th>Customer</th><th className="num">Payments</th><th className="num">Total</th><th>Last paid</th></tr></thead>
              <tbody>{d.top_customers.map((c, i) => (
                <tr key={c.name}><td>{i + 1}</td><td>{c.name}</td><td className="num">{c.payments}</td><td className="num">{money(c.total, true)}</td>
                  <td>{c.last ? new Date(`${c.last}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : ''}</td></tr>
              ))}</tbody>
            </table></div>
            <p className="note" style={{ marginTop: 8 }}>Need one person's full history? Use <Link className="link" to="/admin/customer">Customer profile</Link>.</p>
          </Card>
        </>
      )}
    </div>
  );
}
