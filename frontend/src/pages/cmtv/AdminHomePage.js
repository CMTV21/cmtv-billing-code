// CMTV local addition 2026-09-26: admin home "command centre" on /admin (backend: cmtv_admin_overview.py).
// Money from the Finances ledger; what needs attention, services, expiring and recent orders from billing.
// Staff keep the developer's dashboard (AdminDashboard), which filters by their permissions.
import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import AdminDashboard from '../AdminDashboard';
import { CmtvAdminFrame, useAdminOverview, useStuckAudiobooks } from '../../components/cmtv/AdminShell';

const FAMILY = {
  cctv: { label: 'CCTV', c: 'var(--s-cctv)' },
  imperium: { label: 'Imperium', c: 'var(--s-imp)' },
  addons: { label: 'Add-ons', c: 'var(--s-add)' },
  other: { label: 'Other', c: 'var(--s-other)' },
};
const FAMILY_ORDER = ['cctv', 'imperium', 'addons', 'other'];
const money = (v, cents = true) => `$${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 })}`;
const utc = (s) => (s ? new Date(/Z|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`) : null);
const day = (d) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const errText = (e, fb) => e?.response?.data?.detail || fb;

function Spark({ values }) {
  if (!values || values.length < 2) return null;
  const last = values[values.length - 1] || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${34 - (v / last) * 30 - 2}`).join(' ');
  return (
    <svg className="spark" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts} fill="none" stroke="#1596b3" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Delta({ now, before, suffix }) {
  if (!before) return <span>{suffix}</span>;
  const pct = Math.round(((now - before) / before) * 100);
  return <><span className={pct >= 0 ? 'up' : 'down'}>{pct >= 0 ? '▲' : '▼'} {Math.abs(pct)}%</span> {suffix}</>;
}

// Daily revenue bars, drawn in real pixels so text never stretches. 2px gaps, 4px rounded tops, dashed average.
function RevenueChart({ days }) {
  const box = useRef(null);
  const [w, setW] = useState(800);
  const [hot, setHot] = useState(null);
  useEffect(() => {
    if (!box.current || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  const H = 220, L = 48, R = 8, T = 10, B = 26;
  const top = Math.max(...days.map((d) => d.revenue), 1);
  const step = [50, 100, 200, 250, 500, 1000, 2000, 5000].find((s) => top / s <= 4) || 10000;
  const max = Math.ceil(top / step) * step;
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const slot = (w - L - R) / days.length, bw = Math.max(2, slot - 2);
  const avg = days.reduce((a, d) => a + d.revenue, 0) / days.length;
  const ticks = [];
  for (let t = 0; t <= max; t += step) ticks.push(t);
  const labelEvery = w < 520 ? 10 : 7;
  return (
    <div className="chart" ref={box} onMouseLeave={() => setHot(null)}>
      <svg viewBox={`0 0 ${w} ${H}`} role="img" aria-label={`Daily revenue for the last 30 days, average ${money(avg)} a day`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={L} x2={w - R} y1={y(t)} y2={y(t)} />
            <text className="axis" x={L - 8} y={y(t) + 4} textAnchor="end">{money(t, false)}</text>
          </g>
        ))}
        {days.map((d, i) => {
          const x = L + i * slot + 1, t0 = y(d.revenue), h = H - B - t0, r = Math.min(4, bw / 2, h);
          return (
            <g key={d.date}>
              {d.revenue > 0 && (
                <path className={`bar ${hot === i ? 'hot' : ''}`}
                  d={`M${x},${H - B} V${t0 + r} Q${x},${t0} ${x + r},${t0} H${x + bw - r} Q${x + bw},${t0} ${x + bw},${t0 + r} V${H - B} Z`} />
              )}
              {i % labelEvery === 0 && <text className="axis" x={x + bw / 2} y={H - 8} textAnchor="middle">{day(new Date(`${d.date}T12:00:00`))}</text>}
              <rect x={L + i * slot} y={T} width={slot} height={H - T - B} fill="transparent" onMouseEnter={() => setHot(i)} />
            </g>
          );
        })}
        <line className="avg" x1={L} x2={w - R} y1={y(avg)} y2={y(avg)} />
      </svg>
      {hot !== null && (
        <div className="tip" style={{ left: L + hot * slot + slot / 2, top: y(days[hot].revenue) }}>
          {day(new Date(`${days[hot].date}T12:00:00`))} · <b>{money(days[hot].revenue)}</b>
        </div>
      )}
    </div>
  );
}

function HBars({ rows }) {
  const max = Math.max(...rows.map((r) => r.v), 1);
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hb" key={r.label} style={{ '--c': r.c }}>
          <span className={r.dot ? '' : 'n'}>{r.dot && <span className="dot" />}{r.label}</span>
          <div className="track"><i style={{ width: `${Math.max(1, (r.v / max) * 100)}%` }} /></div>
          <span className="v">{money(r.v, false)}</span>
        </div>
      ))}
    </div>
  );
}

function orderPill(o) {
  if (o.status === 'paid' && ['failed', 'partial'].includes(o.provisioning)) return <span className="pill p-crit">Not set up</span>;
  if (o.status === 'paid') return <span className="pill p-good">Paid</span>;
  if (o.status === 'pending') return <span className="pill p-warn">Waiting payment</span>;
  return <span className="pill p-mute">{o.status}</span>;
}

function CommandCentre() {
  const qc = useQueryClient();
  const { user } = useAuthStore();
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(null);
  const { data: d, error, isLoading } = useAdminOverview();
  const { data: stuck } = useStuckAudiobooks();
  const stuckN = stuck?.requests?.length || 0;

  const markFixed = async (id) => {
    setBusy(id);
    try {
      await api.post(`/api/cmtv/admin/orders/${id}/setup-resolved`);
      toast.success('Marked as fixed');
      qc.invalidateQueries({ queryKey: ['cmtv-admin-overview'] });
    } catch (e) { toast.error(errText(e, "Couldn't save that")); }
    setBusy(null);
  };

  const n = d?.needs || {};
  const pending = n.pending_payment || [];
  const waiting = n.tickets_waiting || [];
  const notSetUp = n.not_set_up || [];
  const urgent = notSetUp.length + (pending.length ? 1 : 0) + (waiting.length ? 1 : 0);
  const hour = new Date().getHours();
  const hello = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const first = String(user?.name || '').split(' ')[0];

  return (
    <CmtvAdminFrame>
        <div className="adm-home">
          <div className="top">
            <div>
              <h1>{hello}{first ? `, ${first}` : ''}</h1>
              <p>
                {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
                {d && ` · ${urgent ? `${plural(urgent, 'thing needs', 'things need')} you` : 'nothing urgent'}`}
              </p>
            </div>
            <div className="quick">
              <Link className="btn" to="/admin/finances">Record payment</Link>
              <Link className="btn" to="/admin/customers">Customers</Link>
              <Link className="btn glow" to="/admin/orders">Confirm payments</Link>
            </div>
          </div>

          {error ? <div className="card" style={{ marginTop: 20 }}><p>{errText(error, "Couldn't load the overview.")}</p></div>
            : isLoading || !d ? <div className="skeleton">Loading…</div> : (
            <>
              <section className="kpis" aria-label="Headline numbers">
                <div className="card kpi">
                  <label>Revenue · {d.month}</label>
                  <div className="big">{money(d.revenue.month)}</div>
                  <div className="delta"><Delta now={d.revenue.month} before={d.revenue.prev_same_point} suffix={`vs ${money(d.revenue.prev_same_point, false)} by this day last month`} /></div>
                  <Spark values={d.revenue.month_cumulative} />
                </div>
                <div className="card kpi">
                  <label>Profit · {d.month}</label>
                  <div className="big">{money(d.revenue.profit_month)}</div>
                  <div className="delta">After {money(d.revenue.costs_month, false)} in credits, PayPal fees and expenses. Same numbers as Finances.</div>
                </div>
                <div className="card kpi">
                  <label>Active services</label>
                  <div className="big">{d.active_total}</div>
                  <div className="seg" aria-hidden="true">
                    {FAMILY_ORDER.filter((k) => d.active[k]).map((k) => <i key={k} style={{ flex: d.active[k], background: FAMILY[k].c }} />)}
                  </div>
                  <div className="legend">
                    {FAMILY_ORDER.filter((k) => d.active[k]).map((k) => <span key={k} style={{ '--c': FAMILY[k].c }}>{FAMILY[k].label} {d.active[k]}</span>)}
                  </div>
                  <div className="delta" style={{ marginTop: 4 }}>{d.auto_renew_on} on auto-renew · trials and resellers not counted</div>
                </div>
                <div className="card kpi">
                  <label>New paying customers · 30 days</label>
                  <div className="big">{d.customers.new_paying30}</div>
                  <div className="delta">
                    {plural(d.customers.new30, 'sign-up', 'sign-ups')} ({d.customers.referred30} referred)
                    {d.customers.prev30 ? <> · <Delta now={d.customers.new30} before={d.customers.prev30} suffix="vs the 30 days before" /></> : null}
                  </div>
                </div>
              </section>

              <div className="grid2">
                <section className="card" aria-label="Needs you">
                  <h2>Needs you</h2>
                  <div className="todo">
                    {notSetUp.map((o) => (
                      <div className="row" key={o.id} style={{ '--c': 'var(--crit)' }}>
                        <div className="what">
                          <span className="sev">▲ Urgent</span>
                          <b>Paid order didn't set up</b>
                          <small>{o.customer} · {o.items}{o.reason ? ` · ${o.reason}` : ''}</small>
                        </div>
                        <div className="acts">
                          <Link className="btn" to="/admin/orders">Open orders</Link>
                          <button type="button" className="btn" disabled={busy === o.id} onClick={() => markFixed(o.id)}
                            title="I've sorted it out by hand: hide it from this list">Mark fixed</button>
                        </div>
                      </div>
                    ))}
                    {pending.length > 0 && (
                      <div className="row" style={{ '--c': 'var(--warn)' }}>
                        <div className="what">
                          <span className="sev">● Waiting</span>
                          <b>{plural(pending.length, 'payment', 'payments')} to confirm</b>
                          <small>{pending.slice(0, 4).map((p) => `${p.customer} ${money(p.total)} (${p.method})`).join(' · ')}
                            {pending[0].days ? `, oldest ${plural(Math.max(...pending.map((p) => p.days || 0)), 'day', 'days')}` : ''}</small>
                        </div>
                        <Link className="btn" to="/admin/orders">Confirm</Link>
                      </div>
                    )}
                    {waiting.length > 0 && (
                      <div className="row" style={{ '--c': 'var(--warn)' }}>
                        <div className="what">
                          <span className="sev">● Reply</span>
                          <b>{plural(waiting.length, 'ticket', 'tickets')} waiting on you</b>
                          <small>“{waiting[0].subject}”{waiting[0].hours != null ? ` · ${waiting[0].hours < 24 ? `${waiting[0].hours}h` : plural(Math.floor(waiting[0].hours / 24), 'day', 'days')}` : ''} · you can also reply in Telegram</small>
                        </div>
                        <Link className="btn" to="/admin/tickets">Open</Link>
                      </div>
                    )}
                    {n.ending_week_no_autorenew > 0 && (
                      <div className="row" style={{ '--c': 'var(--info)' }}>
                        <div className="what">
                          <span className="sev">◆ Heads-up</span>
                          <b>{plural(n.ending_week_no_autorenew, 'service ends', 'services end')} this week without auto-renew</b>
                          <small>See the list below. Reminder emails go out automatically.</small>
                        </div>
                        <button type="button" className="btn" onClick={() => document.getElementById('expiring')?.scrollIntoView({ behavior: 'smooth' })}>View</button>
                      </div>
                    )}
                    {stuckN > 0 && (
                      <div className="row" style={{ '--c': 'var(--info)' }}>
                        <div className="what">
                          <span className="sev">◆ Heads-up</span>
                          <b>{plural(stuckN, 'audiobook request', 'audiobook requests')} stuck</b>
                          <small>No search result scored high enough to download by itself</small>
                        </div>
                        <Link className="btn" to="/admin/audiobooks?tab=stuck">Review</Link>
                      </div>
                    )}
                    {!urgent && !n.ending_week_no_autorenew && !stuckN && <p className="allclear">✓ All clear. Nothing needs you right now.</p>}
                  </div>
                </section>

                <section className="card" aria-label={`Revenue by service, ${d.month}`}>
                  <h2>Revenue by service · {d.month}</h2>
                  <HBars rows={FAMILY_ORDER.filter((k) => d.by_family[k]).map((k) => ({ label: FAMILY[k].label, v: d.by_family[k], c: FAMILY[k].c, dot: true }))} />
                  <h2 style={{ marginTop: 22 }}>Payment methods · {d.month}</h2>
                  <HBars rows={d.by_method.map((m) => ({ label: m.method, v: m.total, c: 'var(--s-cctv)' }))} />
                  <p className="note" style={{ marginTop: 12 }}>From Finances. {money(d.revenue.billing_orders_month)} of it came through billing orders.</p>
                </section>
              </div>

              <section className="card" style={{ marginBottom: 14 }} aria-label="Revenue, last 30 days">
                <h2>Revenue · last 30 days</h2>
                <RevenueChart days={d.revenue.last30} />
                <div className="legend" style={{ marginTop: 6 }}>
                  <span style={{ '--c': 'var(--s-cctv)' }}>Daily revenue</span>
                  <span className="line" style={{ '--c': 'var(--muted)' }}>Average {money(d.revenue.last30.reduce((a, x) => a + x.revenue, 0) / 30)} / day</span>
                </div>
              </section>

              <div className="grid2">
                <section className="card" id="expiring" aria-label="Ending in the next 14 days">
                  <h2>Ending in the next 14 days</h2>
                  {d.expiring.length === 0 ? <p className="note">Nothing ends in the next two weeks.</p> : (
                    <div className="tablewrap"><table>
                      <thead><tr><th>Customer</th><th>Service</th><th>Ends</th><th>Auto-renew</th></tr></thead>
                      <tbody>
                        {(showAll ? d.expiring : d.expiring.slice(0, 8)).map((e, i) => (
                          <tr key={`${e.user_id}-${i}`}>
                            <td className="clip" title={e.email || ''}>{e.customer}</td>
                            <td className="clip"><span className="dot" style={{ '--c': (FAMILY[e.family] || FAMILY.other).c }} />{e.service}</td>
                            <td>{day(utc(e.ends))}</td>
                            <td>{e.auto_renew ? <span className="pill p-good">On</span> : <span className="pill p-mute">Off</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table></div>
                  )}
                  {d.expiring.length > 8 && (
                    <button type="button" className="link" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show fewer' : `Show all ${d.expiring_count} →`}</button>
                  )}
                </section>

                <section className="card" aria-label="Recent orders">
                  <h2>Recent orders</h2>
                  <div className="tablewrap"><table>
                    <thead><tr><th>Customer</th><th>Items</th><th>Paid by</th><th className="num">Total</th><th>Status</th></tr></thead>
                    <tbody>
                      {d.recent_orders.map((o) => (
                        <tr key={o.id}>
                          <td className="clip">{o.customer}</td>
                          <td className="clip" title={o.items}>{o.items}</td>
                          <td>{o.method}</td>
                          <td className="num">{money(o.total)}</td>
                          <td>{orderPill(o)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table></div>
                  <Link className="link" to="/admin/orders">All orders →</Link>
                </section>
              </div>
            </>
          )}
        </div>
    </CmtvAdminFrame>
  );
}

export default function AdminHomePage() {
  const { user } = useAuthStore();
  if (user?.role === 'staff') return <AdminDashboard />;
  return <CommandCentre />;
}
