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
function NoticeBox() {
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

export default function AdminResellersPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['cmtv-resellers-admin'], queryFn: async () => (await api.get('/api/cmtv/reseller/admin')).data });
  const [levels, setLevels] = useState({ reseller_low: '', own_imperium_low: '' });
  useEffect(() => { if (data?.levels) setLevels(data.levels); }, [data]);
  const rows = data?.resellers || [];
  const imp = data?.own?.imperium;
  const impLow = imp !== null && imp !== undefined && data?.levels && imp < data.levels.own_imperium_low;

  const save = async () => {
    try {
      await api.post('/api/cmtv/reseller/admin/alerts', { reseller_low: levels.reseller_low, own_imperium_low: levels.own_imperium_low });
      qc.invalidateQueries({ queryKey: ['cmtv-resellers-admin'] });
      toast.success('Alert levels saved');
    } catch { toast.error('Could not save'); }
  };

  return (
    <div className="rs-admin">
      <h1>Resellers</h1>
      <p className="rs-sub">Reseller panels, their credit balances and what they've spent. Balances: CCTV refreshes hourly from the panel, Imperium is live.</p>

      <div className="rs-top">
        <div className={`rs-own${impLow ? ' low' : ''}`}>
          <span>Your Imperium credits</span>
          <b>{imp === null || imp === undefined ? '–' : Number(imp).toLocaleString()}</b>
          <small>{impLow ? 'Below your alert level. ' : ''}Imperium credits resellers buy come out of this. Customers can buy at most this many online.</small>
        </div>
        <div className="rs-levels">
          <b>Alert levels</b>
          <label>Warn a reseller under <input type="number" min="0" value={levels.reseller_low} onChange={(e) => setLevels({ ...levels, reseller_low: e.target.value })} /> credits</label>
          <label>Warn me when my Imperium balance is under <input type="number" min="0" value={levels.own_imperium_low} onChange={(e) => setLevels({ ...levels, own_imperium_low: e.target.value })} /> credits</label>
          <button type="button" className="rv-btn glow" onClick={save}>Save</button>
        </div>
      </div>

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
