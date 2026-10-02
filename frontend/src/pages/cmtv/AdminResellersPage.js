// CMTV local addition 2026-09-28: Admin > Resellers. Every active reseller panel with its balance (CCTV hourly from the
// panel, Imperium live), total spent on credits, last top-up; CMTV's own Imperium balance (what customers can buy online);
// the two alert levels. Backend: GET /api/cmtv/reseller/admin, POST /api/cmtv/reseller/admin/alerts (cmtv_reseller_credits.py).
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/reseller-credits.css';

const money = (v) => `$${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
function ago(iso) {
  if (!iso) return 'never';
  const h = (Date.now() - new Date(iso).getTime()) / 3600000;
  if (h < 1) return 'just now';
  if (h < 48) return `${Math.round(h)} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '–');

// 2026-09-28: a notice to every active reseller (email + Telegram if connected + their dashboard for 7 days).
// "Check" is a dry run that lists who gets it; "Send" asks once more.
export function NoticeBox() {   // also on Admin > Notices
  const [text, setText] = useState('');
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const { data, refetch } = useQuery({ queryKey: ['cmtv-reseller-notices'], queryFn: async () => (await api.get('/api/cmtv/reseller/admin/notices')).data });
  const post = async (dry) => {
    setBusy(true);
    try {
      const r = (await api.post('/api/cmtv/reseller/admin/notice', { text, dry_run: dry })).data;
      if (dry) setCheck(r);
      else {
        toast.success(`Sent to ${r.resellers} reseller${r.resellers === 1 ? '' : 's'} (${r.emailed} emailed, ${r.telegram} on Telegram)`);
        setText(''); setCheck(null); refetch();
      }
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not send'); }
    setBusy(false);
  };
  const send = () => { if (window.confirm(`Send this notice to ${check.resellers} reseller(s) now?`)) post(false); };
  return (
    <div className="rs-notice">
      <b>Send a notice to all resellers</b>
      <textarea value={text} maxLength={1000} onChange={(e) => { setText(e.target.value); setCheck(null); }}
        placeholder="e.g. CCTV maintenance tonight 2-3 AM ET. Your customers may see a short outage." aria-label="Notice text" />
      <div className="row">
        <button type="button" className="rv-btn" disabled={busy || text.trim().length < 5} onClick={() => post(true)}>Check who gets it</button>
        {check && <button type="button" className="rv-btn glow" disabled={busy} onClick={send}>Send to {check.resellers}</button>}
        {check && <span>{check.names.join(', ')}</span>}
      </div>
      {data?.notices?.length > 0 && (
        <ul>{data.notices.slice(0, 5).map((n) => (
          <li key={n.id}>{day(n.created_at)}: {n.text.length > 90 ? `${n.text.slice(0, 90)}…` : n.text} ({n.resellers} resellers, {n.emailed} emailed, {n.telegram} Telegram)</li>
        ))}</ul>
      )}
    </div>
  );
}

// 2026-09-28: partner applications from cmtv.info/partners (each one also goes to the Ops Billing topic)
function Applications() {
  const { data } = useQuery({ queryKey: ['cmtv-partner-apps'], queryFn: async () => (await api.get('/api/cmtv/reseller/admin/applications')).data });
  const apps = data?.applications || [];
  if (!apps.length) return null;
  return (
    <div className="rs-notice">
      <b>Partner applications</b>
      <ul>{apps.map((a) => (
        <li key={a.id}>{day(a.created_at)}: <b>{`${a.first_name} ${a.last_name}`.trim()}</b>, <a href={`mailto:${a.email}`}>{a.email}</a>
          {a.telegram && ` · ${a.telegram}`}{a.interest && ` · ${a.interest}`}{a.message && <div>{a.message}</div>}</li>
      ))}</ul>
    </div>
  );
}

// 2026-10-01: only existing resellers and customers approved here can buy reseller credits (storefront + checkout)
function ApprovedBox() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const { data, refetch } = useQuery({ queryKey: ['cmtv-reseller-approved'], queryFn: async () => (await api.get('/api/cmtv/reseller/admin/approved')).data });
  const set = async (body, msg) => {
    setBusy(true);
    try {
      const r = (await api.post('/api/cmtv/reseller/admin/approve', body)).data;
      toast.success(`${r.name || r.email} ${msg}`);
      setEmail(''); refetch();
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not save'); }
    setBusy(false);
  };
  const list = data?.approved || [];
  return (
    <div className="rs-notice">
      <b>Approve a new reseller</b>
      <div style={{ fontSize: 13, opacity: 0.8, margin: '4px 0 8px' }}>
        Reseller credits are hidden from the store and refused at checkout for everyone except your current resellers (top-ups)
        and the customers approved here. They need a billing account first.
      </div>
      <div className="row">
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Customer's email"
          aria-label="Customer's email" style={{ flex: 1, minWidth: 200 }} />
        <button type="button" className="rv-btn glow" disabled={busy || !email.includes('@')}
          onClick={() => set({ email, approved: true }, 'can now buy reseller credits')}>Approve</button>
      </div>
      {list.length > 0 && (
        <ul>{list.map((a) => (
          <li key={a.user_id}><b>{a.name || a.email}</b> ({a.email}) · approved {day(a.approved_at)}{a.has_panel ? ' · has a panel' : ''}{' '}
            <button type="button" className="rv-btn" disabled={busy}
              onClick={() => window.confirm(`Take back reseller approval for ${a.email}?`) && set({ user_id: a.user_id, approved: false }, 'is no longer approved')}>Remove</button>
          </li>
        ))}</ul>
      )}
    </div>
  );
}

// 2026-10-01: Nuvio resellers (cmtv_nuvio_reseller.py): switch on (with welcome credits), balances, credit changes, add-on set
function NuvioResellersBox() {
  const [email, setEmail] = useState('');
  const [free, setFree] = useState(10);
  const [busy, setBusy] = useState(false);
  const { data, refetch } = useQuery({ queryKey: ['nuvio-resellers-admin'], queryFn: async () => (await api.get('/api/cmtv/nuvio-reseller/admin')).data });
  const post = async (path, body, ok) => {
    setBusy(true);
    try { const r = (await api.post(`/api/cmtv/nuvio-reseller/admin/${path}`, body)).data; toast.success(ok(r)); refetch(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Could not save'); }
    setBusy(false);
  };
  const list = data?.resellers || [];
  return (
    <div className="rs-notice">
      <b>Nuvio resellers</b>
      <div style={{ fontSize: 13, opacity: 0.8, margin: '4px 0 8px' }}>
        They make and run Nuvio accounts in Reseller tools &gt; Nuvio. $1.00 a credit; 1 credit = 1 account-month with 2 devices,
        +1 for 3-4 devices, +2 for 4K. Free 48 h trials (10 a week).
        {data && !data.reseller_addons_ready && ' No reseller add-ons yet (Admin > Nuvio > Add-ons, For: Resellers\' customers), so everyone uses your own add-ons for now.'}
      </div>
      <div className="row">
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Customer's email" aria-label="Customer's email" style={{ flex: 1, minWidth: 200 }} />
        <label style={{ fontSize: 13 }}>Welcome credits <input type="number" min="0" value={free} onChange={(e) => setFree(e.target.value)} style={{ width: 70 }} /></label>
        <button type="button" className="rv-btn glow" disabled={busy || !email.includes('@')}
          onClick={() => post('enable', { email, on: true, free_credits: Number(free) }, (r) => `${r.name || r.email}: Nuvio reselling on${r.free_credits ? `, ${r.free_credits} credits` : ''}`)}>Switch on</button>
      </div>
      {list.length > 0 && (
        <ul>{list.map((r) => (
          <li key={r.user_id}><b>{r.name || r.email}</b> ({r.email}) · <b>{r.balance}</b> credits · {r.accounts} account{r.accounts === 1 ? '' : 's'}{r.trials ? ` (${r.trials} trials)` : ''} ·
            add-ons: {r.pool === 'reseller' ? 'reseller set' : 'yours'}{' '}
            <button type="button" className="rv-btn" disabled={busy} onClick={() => {
              const v = window.prompt(`Add (or remove with -) credits for ${r.name || r.email}:`, '10'); if (!v) return;
              const why = window.prompt('Reason (they see it in their history):', 'Credit from CMTV'); if (!why) return;
              post('credit', { user_id: r.user_id, delta: Number(v), reason: why }, (x) => `Balance now ${x.balance}`);
            }}>Credits</button>{' '}
            <button type="button" className="rv-btn" disabled={busy}
              onClick={() => window.confirm(`Move ${r.name || r.email} and their accounts to ${r.pool === 'reseller' ? 'your own' : 'the reseller'} add-ons?`)
                && post('pool', { user_id: r.user_id, pool: r.pool === 'reseller' ? 'retail' : 'reseller' }, (x) => `${x.moved} accounts moved`)}>
              Use {r.pool === 'reseller' ? 'your add-ons' : 'reseller add-ons'}</button>{' '}
            <button type="button" className="rv-btn" disabled={busy}
              onClick={() => window.confirm(`Switch off Nuvio reselling for ${r.name || r.email}? Their accounts keep running to their end dates.`)
                && post('enable', { user_id: r.user_id, on: false }, () => 'Switched off')}>Switch off</button>
          </li>
        ))}</ul>
      )}
    </div>
  );
}

export default function AdminResellersPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['cmtv-resellers-admin'], queryFn: async () => (await api.get('/api/cmtv/reseller/admin')).data });
  const [levels, setLevels] = useState({ reseller_low: '', own_imperium_low: '', own_cctv_low: '' });
  useEffect(() => { if (data?.levels) setLevels(data.levels); }, [data]);
  const rows = data?.resellers || [];
  const imp = data?.own?.imperium;
  const impLow = imp !== null && imp !== undefined && data?.levels && imp < data.levels.own_imperium_low;
  const cctv = data?.own?.cctv;   // 2026-09-29: CMTV's own CCTV balance too
  const cctvLow = cctv !== null && cctv !== undefined && data?.levels && cctv < data.levels.own_cctv_low;
  const fmt = (v) => (v === null || v === undefined ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }));

  const save = async () => {
    try {
      await api.post('/api/cmtv/reseller/admin/alerts', { reseller_low: levels.reseller_low, own_imperium_low: levels.own_imperium_low,
        own_cctv_low: levels.own_cctv_low });
      qc.invalidateQueries({ queryKey: ['cmtv-resellers-admin'] });
      toast.success('Alert levels saved');
    } catch { toast.error('Could not save'); }
  };

  return (
    <div className="rs-admin">
      <h1>Resellers</h1>
      <p className="rs-sub">Reseller panels, their credit balances and what they've spent. Balances: CCTV refreshes hourly from the panel, Imperium is live.</p>

      <div className="rs-top">
        <div className={`rs-own${cctvLow ? ' low' : ''}`}>
          <span>Your CCTV credits</span>
          <b>{fmt(cctv)}</b>
          <small>{cctvLow ? 'Below your alert level. ' : ''}New CCTV lines and the CCTV credits resellers buy come out of this. Resellers can buy at most this many online.</small>
        </div>
        <div className={`rs-own${impLow ? ' low' : ''}`}>
          <span>Your Imperium credits</span>
          <b>{fmt(imp)}</b>
          <small>{impLow ? 'Below your alert level. ' : ''}Imperium credits resellers buy come out of this. Customers can buy at most this many online.</small>
        </div>
        <div className="rs-levels">
          <b>Alert levels</b>
          <label>Warn a reseller under <input type="number" min="0" value={levels.reseller_low} onChange={(e) => setLevels({ ...levels, reseller_low: e.target.value })} /> credits</label>
          <label>Warn me when my CCTV balance is under <input type="number" min="0" value={levels.own_cctv_low} onChange={(e) => setLevels({ ...levels, own_cctv_low: e.target.value })} /> credits</label>
          <label>Warn me when my Imperium balance is under <input type="number" min="0" value={levels.own_imperium_low} onChange={(e) => setLevels({ ...levels, own_imperium_low: e.target.value })} /> credits</label>
          <button type="button" className="rv-btn glow" onClick={save}>Save</button>
        </div>
      </div>

      <ApprovedBox />
      <NuvioResellersBox />
      <NoticeBox />
      <Applications />

      {isLoading ? <p>Loading…</p> : rows.length === 0 ? <p className="rs-sub">No active reseller panels.</p> : (
        <div className="rs-table-wrap">
          <table className="rs-table">
            <thead><tr><th>Reseller</th><th>Server</th><th>Panel</th><th>Credits</th><th>Spent on credits</th><th>Last top-up</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.service_id} className={r.low ? 'low' : ''}>
                  <td>
                    <Link to={`/admin/customer/${r.user_id}`}>{r.name || r.username}</Link>
                    <small>{r.placeholder ? 'no email yet' : r.email}</small>
                  </td>
                  <td><span className={`rs-srv ${r.server}`}>{r.label}</span></td>
                  <td><code>{r.username}</code></td>
                  <td><b>{r.credits === null ? '–' : Number(r.credits).toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
                    <small>{r.low ? 'low · ' : ''}{ago(r.as_of)}</small></td>
                  <td>{money(r.spent)}<small>{r.orders} order{r.orders === 1 ? '' : 's'} in billing</small></td>
                  <td>{day(r.last_topup)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="rs-note">Spent / last top-up count orders paid through billing only (earlier sales from your spreadsheet are in Finances).</p>
    </div>
  );
}
