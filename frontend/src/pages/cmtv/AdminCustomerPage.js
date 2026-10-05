// CMTV local addition 2026-09-27: one page per customer (backend: cmtv_customer.py). Route /admin/customer/:id and
// /admin/customer (search). Services with quick actions, orders, tickets, notes, referrals + credit, emails, activity.
import React, { useEffect, useRef, useState } from 'react';
import AdminTvExtend from '../../components/cmtv/AdminTvExtend'; // 2026-10-05: extend TV lines here
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import { AdminCustomerReferrals } from '../../components/cmtv/ReferralTier';

const FAMILY = {
  cctv: { label: 'CCTV', c: 'var(--s-cctv)' }, imperium: { label: 'Imperium', c: 'var(--s-imp)' },
  addons: { label: 'Add-on', c: 'var(--s-add)' }, trials: { label: 'Trial', c: 'var(--s-other)' },
  resellers: { label: 'Reseller', c: 'var(--s-other)' }, other: { label: 'Other', c: 'var(--s-other)' },
};
const money = (v) => `$${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const utc = (s) => (s ? new Date(/Z|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`) : null);
const day = (s) => (s ? utc(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const ago = (s) => {
  if (!s) return '';
  const d = Math.floor((Date.now() - utc(s).getTime()) / 86400000);
  return d <= 0 ? 'today' : d === 1 ? 'yesterday' : d < 60 ? `${d} days ago` : day(s);
};
const errText = (e, fb) => e?.response?.data?.detail || fb;
const enc = encodeURIComponent;

export function CustomerSearch({ autoFocus = false, compact = false }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const box = useRef(null);
  const { data } = useQuery({
    queryKey: ['cust-search', q],
    queryFn: async () => (await api.get('/api/cmtv/admin/customers/search', { params: { q } })).data,
    enabled: q.trim().length >= 2,
  });
  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, []);
  const go = (id) => { setOpen(false); setQ(''); navigate(`/admin/customer/${id}`); };
  return (
    <div className={`cust-search ${compact ? 'compact' : ''}`} ref={box}>
      <input value={q} autoFocus={autoFocus} onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onKeyDown={(e) => { if (e.key === 'Enter' && data?.[0]) go(data[0].id); }}
        placeholder="Find a customer: name, email or any login" aria-label="Find a customer" />
      {open && q.trim().length >= 2 && (
        <ul role="listbox">
          {(data || []).length === 0 ? <li className="none">No matches</li> : data.map((c) => (
            <li key={c.id}><button type="button" onClick={() => go(c.id)}>
              <b>{c.name || '(no name)'}</b><span>{c.email}</span>{c.match && <em>{c.match}</em>}
            </button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Secret({ value }) {
  const [show, setShow] = useState(false);
  if (!value) return null;
  return (
    <span className="secret">
      <code>{show ? value : '••••••••'}</code>
      <button type="button" className="mini" onClick={() => setShow(!show)}>{show ? 'Hide' : 'Show'}</button>
      {show && <button type="button" className="mini" onClick={() => { navigator.clipboard.writeText(value); toast.success('Copied'); }}>Copy</button>}
    </span>
  );
}

function ServiceCard({ s, onChanged }) {
  const [busy, setBusy] = useState('');
  const fam = FAMILY[s.family] || FAMILY.other;
  const run = async (key, fn, ok) => {
    setBusy(key);
    try { await fn(); toast.success(ok); onChanged(); } catch (e) { toast.error(errText(e, 'Something went wrong')); }
    setBusy('');
  };
  const addonPath = s.cockpit_module === 'audiobooks'
    ? (what) => `/api/cmtv/audiobooks/users/${enc(s.username)}/${what}`
    : (what) => `/api/cmtv/addons/${s.cockpit_module}/users/${enc(s.username)}/${what}`;
  const isAddon = ['nuvio', 'vpn', 'audiobooks'].includes(s.cockpit_module) && s.username;
  const canSuspend = ['xtream', 'aether'].includes(s.panel_type) && s.username;
  const pill = s.status === 'active' ? (s.days_left !== null && s.days_left < 0 ? 'p-crit' : s.days_left !== null && s.days_left <= 7 ? 'p-warn' : 'p-good')
    : s.status === 'suspended' ? 'p-warn' : 'p-mute';
  const left = s.days_left === null ? '' : s.days_left < 0 ? `ended ${-s.days_left} days ago` : s.days_left === 0 ? 'ends today' : `${s.days_left} days left`;
  const extend = (months) => window.confirm(`Add ${months === 12 ? '1 year' : `${months} month${months > 1 ? 's' : ''}`} to ${s.username} (${s.product_name})?`)
    && run(`ext${months}`, () => api.post(addonPath('extend'), { months }), `${s.username} extended`);
  return (
    <div className="svc" style={{ '--c': fam.c }}>
      <div className="svc-top">
        <span className="dot" />
        <div className="svc-name"><b>{s.product_name}</b><small>{fam.label}{s.is_trial ? ' · trial' : ''}{s.connections ? ` · ${s.connections} conn.` : ''}{s.panel_name ? ` · ${s.panel_name}` : ''}</small></div>
        <span className={`pill ${pill}`}>{s.status}</span>
      </div>
      {s.username && <div className="svc-row"><span>Login</span><code>{s.username}</code><Secret value={s.password} /></div>}
      <div className="svc-row"><span>Ends</span><b>{day(s.expiry) || 'no date'}</b><small>{left}</small>
        {s.auto_renew && <span className="pill p-good">auto-renew</span>}</div>
      <div className="svc-acts">
        {isAddon && [1, 3, 12].map((m) => (
          <button key={m} type="button" className="btn sm" disabled={!!busy} onClick={() => extend(m)}>+{m === 12 ? '1 yr' : `${m} mo`}</button>
        ))}
        {canSuspend && <AdminTvExtend s={s} onDone={onChanged} />}{/* 2026-10-05 */}
        {isAddon && s.cockpit_module !== 'audiobooks' && (
          <Link className="btn sm" to={s.cockpit_module === 'vpn' ? '/admin/cmtvpn' : '/admin/stremio'}>Manage</Link>
        )}
        {isAddon && s.cockpit_module === 'audiobooks' && <Link className="btn sm" to="/admin/audiobooks">Manage</Link>}
        {canSuspend && s.status === 'active' && (
          <button type="button" className="btn sm" disabled={!!busy}
            onClick={() => window.confirm(`Suspend ${s.username} on the panel? The customer loses access until unsuspended.`)
              && run('susp', () => api.post(`/api/admin/services/${s.id}/suspend`), 'Suspended')}>Suspend</button>
        )}
        {canSuspend && s.status === 'suspended' && (
          <button type="button" className="btn sm" disabled={!!busy}
            onClick={() => run('unsusp', () => api.post(`/api/admin/services/${s.id}/unsuspend`), 'Unsuspended')}>Unsuspend</button>
        )}
      </div>
    </div>
  );
}

function Notes({ customerId, notes, onChanged }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const add = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await api.post(`/api/cmtv/admin/customers/${customerId}/notes`, { text }); setText(''); onChanged(); }
    catch (e) { toast.error(errText(e, "Couldn't save the note")); }
    setBusy(false);
  };
  return (
    <section className="card">
      <h2>Notes</h2>
      <p className="note">Only admins see these.</p>
      <div className="note-add">
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Pays by e-Transfer; Sarah2025 is on this account" />
        <button type="button" className="btn sm" disabled={busy || !text.trim()} onClick={add}>Add note</button>
      </div>
      <ul className="notes">
        {notes.map((n) => (
          <li key={n.id}>
            <p>{n.text}</p>
            <small>{n.by ? `${n.by} · ` : ''}{ago(n.at)}
              <button type="button" className="mini" onClick={async () => {
                if (!window.confirm('Remove this note?')) return;
                await api.post(`/api/cmtv/admin/customers/${customerId}/notes/${n.id}/delete`); onChanged();
              }}>Remove</button></small>
          </li>
        ))}
      </ul>
    </section>
  );
}

function orderPill(o) {
  if (o.status === 'paid' && ['failed', 'partial'].includes(o.provisioning)) return <span className="pill p-crit">Not set up</span>;
  if (o.status === 'paid') return <span className="pill p-good">Paid</span>;
  if (o.status === 'pending') return <span className="pill p-warn">Waiting</span>;
  return <span className="pill p-mute">{o.status}</span>;
}

export default function AdminCustomerPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [showAllOrders, setShowAllOrders] = useState(false);
  const { data: d, error, isLoading } = useQuery({
    queryKey: ['cust-profile', id],
    queryFn: async () => (await api.get(`/api/cmtv/admin/customers/${id}/profile`)).data,
    enabled: !!id,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['cust-profile', id] });

  if (!id) {
    return (
      <div className="adm-home adm-cust">
        <h1>Customers</h1>
        <p className="note" style={{ margin: '4px 0 16px' }}>Search by name, email, or any login (TV line, Stremio, CMTVpn, Audiobooks).</p>
        <CustomerSearch autoFocus />
        <p className="note" style={{ marginTop: 16 }}>The full list is still in <Link className="link" to="/admin/customers">Customers</Link>.</p>
      </div>
    );
  }
  if (error) return <div className="adm-home adm-cust"><CustomerSearch /><div className="card" style={{ marginTop: 16 }}>{errText(error, "Couldn't load this customer")}</div></div>;
  if (isLoading || !d) return <div className="adm-home adm-cust"><CustomerSearch /><p className="skeleton">Loading…</p></div>;

  const c = d.customer, t = d.totals;
  const initials = (c.name || c.email || '?').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  const orders = showAllOrders ? d.orders : d.orders.slice(0, 8);
  return (
    <div className="adm-home adm-cust">
      <CustomerSearch compact />

      <section className="card cust-head">
        <div className="avatar" aria-hidden="true">{initials}</div>
        <div className="who">
          <h1>{c.name || '(no name)'}</h1>
          <p>
            {c.real_email ? <a className="link" href={`mailto:${c.email}`}>{c.email}</a> : <span className="note">{c.email} (no real email)</span>}
            {c.username && <> · login <code>{c.username}</code></>}
          </p>
          <p className="note">
            Customer since {day(c.created_at)}{c.created_via === 'panel_sync' ? ' (imported from a panel)' : ''}
            {c.referred_by && <> · referred by {c.referred_by.id ? <Link className="link" to={`/admin/customer/${c.referred_by.id}`}>{c.referred_by.name || c.referred_by.email}</Link> : c.referred_by.code}</>}
          </p>
        </div>
        <div className="badges">
          {d.referrals.tier?.tier && <span className="pill p-good">{d.referrals.tier.tier}</span>}
          <span className={`pill ${c.email_verified ? 'p-good' : 'p-mute'}`}>{c.email_verified ? 'email verified' : 'not verified'}</span>
        </div>
      </section>

      <section className="kpis" aria-label="Totals">
        <div className="card kpi"><label>Lifetime spend</label><div className="big">{money(t.paid_total)}</div>
          <div className="delta">{t.paid_orders} paid order{t.paid_orders === 1 ? '' : 's'}{t.first_paid ? ` since ${day(t.first_paid)}` : ''}</div></div>
        <div className="card kpi"><label>Active services</label><div className="big">{t.active_services}</div>
          <div className="delta">{d.services.length} in total, trials included</div></div>
        <div className="card kpi"><label>Last paid</label><div className="big" style={{ fontSize: 22 }}>{t.last_paid ? ago(t.last_paid) : 'never'}</div>
          <div className="delta">{t.last_paid ? day(t.last_paid) : 'no paid orders yet'}</div></div>
        <div className="card kpi"><label>Credit · Support</label><div className="big">{money(c.credit_balance)}</div>
          <div className="delta">{t.open_tickets ? `${t.open_tickets} open ticket${t.open_tickets > 1 ? 's' : ''}` : 'no open tickets'}</div></div>
      </section>

      <section className="card" style={{ marginBottom: 14 }}>
        <h2>Services</h2>
        {d.services.length === 0 ? <p className="note">No services.</p> : (
          <div className="svc-grid">{d.services.map((s) => <ServiceCard key={s.id} s={s} onChanged={refresh} />)}</div>
        )}
      </section>

      <div className="grid2">
        <section className="card">
          <h2>Orders</h2>
          {d.orders.length === 0 ? <p className="note">No orders.</p> : (
            <div className="tablewrap"><table>
              <thead><tr><th>Date</th><th>Items</th><th>Paid by</th><th className="num">Total</th><th>Status</th></tr></thead>
              <tbody>{orders.map((o) => (
                <tr key={o.id}>
                  <td>{day(o.paid_at || o.created_at)}</td>
                  <td className="clip" title={o.items}>{o.items}{o.coupon ? ` · ${o.coupon}` : ''}</td>
                  <td>{o.method}</td>
                  <td className="num">{money(o.total)}</td>
                  <td>{orderPill(o)}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
          {d.orders.length > 8 && <button type="button" className="link" onClick={() => setShowAllOrders(!showAllOrders)}>{showAllOrders ? 'Show fewer' : `Show all ${d.orders.length}`}</button>}
        </section>
        <Notes customerId={c.id} notes={d.notes} onChanged={refresh} />
      </div>

      <div className="grid2">
        <section className="card">
          <h2>Support tickets</h2>
          {d.tickets.length === 0 ? <p className="note">No tickets.</p> : (
            <ul className="list">{d.tickets.map((tk) => (
              <li key={tk.id}>
                <b>{tk.subject}</b>
                <small>{tk.status}{tk.waiting_on_us ? ' · waiting on you' : ''} · {tk.messages} message{tk.messages === 1 ? '' : 's'} · {ago(tk.updated_at)}</small>
              </li>
            ))}</ul>
          )}
          <Link className="link" to="/admin/tickets">Open Support →</Link>
        </section>
        <section className="card">
          <h2>Emails sent</h2>
          {d.emails.length === 0 ? <p className="note">None logged.</p> : (
            <ul className="list">{d.emails.map((e, i) => (
              <li key={i}>
                <b>{e.subject}</b>
                <small>{ago(e.at)} · <span className={e.status === 'failed' ? 'bad' : ''}>{e.status === 'pending' ? 'sent (before logging was fixed)' : e.status}</span>{e.error ? ` · ${e.error}` : ''}</small>
              </li>
            ))}</ul>
          )}
        </section>
      </div>

      <div className="grid2">
        <section className="card">
          <h2>Activity</h2>
          {d.activity.length === 0 ? <p className="note">Nothing yet.</p> : (
            <ol className="timeline">{d.activity.map((a, i) => (
              <li key={i} className={a.kind}><span className="when">{day(a.at)}</span><span>{a.text}</span></li>
            ))}</ol>
          )}
        </section>
        <section className="card ref-box">
          <h2>Referrals &amp; credit</h2>
          {d.referrals.referred.length > 0 && (
            <p className="note" style={{ marginBottom: 8 }}>Referred: {d.referrals.referred.map((r) => `${r.email} (${r.status})`).join(', ')}</p>
          )}
          <AdminCustomerReferrals customerId={c.id} />
        </section>
      </div>
    </div>
  );
}
