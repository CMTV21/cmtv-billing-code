// CMTV local addition 2026-10-01: Reseller tools > Nuvio. Resellers switched on for Nuvio (Admin > Resellers) make and run
// Nuvio accounts on CMTV's Nuvio server with Nuvio credits: 1 credit = 1 account for 1 month with 2 devices,
// +1 a month for 3-4 devices, +1 a month for 4K. Free 48 h trials (HD). Backend: /api/cmtv/nuvio-reseller/* (cmtv_nuvio_reseller.py).
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import ResellerCredits from './ResellerCredits';
import './nuvio-reseller.css';

const MONTHS = [1, 3, 6, 12];
const UHD_EXTRA = 2; // CMTV 2026-10-02: 4K = 3 credits a month in total
const perMonth = (devices, uhd) => 1 + (devices > 2 ? 1 : 0) + (uhd ? UHD_EXTRA : 0);
const err = (e, d) => e?.response?.data?.detail || d;
const day = (s) => (s ? new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '–');
const daysLeft = (s) => (s ? Math.ceil((new Date(`${s}T23:59:59`) - new Date()) / 86400000) : 0);
const monthsLeft = (s) => Math.max(0, Math.ceil(Math.max(0, daysLeft(s) - 1) / 30.44));

function copy(text, what) {
  navigator.clipboard.writeText(text).then(() => toast.success(`${what} copied`)).catch(() => toast.error('Copy failed'));
}

function loginText(a) {
  return `Your Nuvio login\nUsername: ${a.login}\nPassword: ${a.password}\n\nInstall the Nuvio app on your TV or device, then sign in with these details.`
    + (a.expires ? `\nActive until ${day(a.expires)}.` : '');
}

function NewAccount({ balance, onDone }) {
  const [f, setF] = useState({ username: '', password: '', months: 12, devices: 2, uhd: false, notes: '' });
  const [busy, setBusy] = useState(false);
  const cost = f.months * perMonth(f.devices, f.uhd);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const make = async () => {
    setBusy(true);
    try {
      const r = (await api.post('/api/cmtv/nuvio-reseller/accounts', { ...f, months: Number(f.months), devices: Number(f.devices) })).data;
      toast.success(`${r.login} created (${r.cost} credits)`);
      copy(loginText({ login: r.login, password: r.password, expires: r.expires }), 'Login');
      setF({ ...f, username: '', password: '', notes: '' });
      onDone();
    } catch (e) { toast.error(err(e, 'Could not create the account')); }
    setBusy(false);
  };
  return (
    <div className="nvr-box">
      <h3 className="rt-h3">New account</h3>
      <div className="nvr-grid">
        <label>Username<input value={f.username} maxLength={32} onChange={set('username')} placeholder="Leave empty to make one" /></label>
        <label>Password<input value={f.password} maxLength={40} onChange={set('password')} placeholder="Leave empty to make one" /></label>
        <label>Length<select value={f.months} onChange={set('months')}>{MONTHS.map((m) => <option key={m} value={m}>{m} month{m > 1 ? 's' : ''}</option>)}</select></label>
        <label>Devices<select value={f.devices} onChange={set('devices')}>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}{n > 2 ? ' (+1 credit/month)' : ''}</option>)}</select></label>
        <label className="nvr-wide">Note for you (optional)<input value={f.notes} maxLength={120} onChange={set('notes')} placeholder="e.g. customer's name" /></label>
      </div>
      <div className="nvr-row">
        <label className="nvr-check"><input type="checkbox" checked={f.uhd} onChange={set('uhd')} /> 4K streams (+2 credits a month)</label>
        <span className="nvr-cost">Costs <b>{cost} credit{cost > 1 ? 's' : ''}</b>{cost > balance && <em> · you have {balance}</em>}</span>
        <button type="button" className="ca-btn ca-glow" disabled={busy || cost > balance} onClick={make}>{busy ? 'Creating…' : 'Create account'}</button>
      </div>
    </div>
  );
}

function AccountRow({ a, balance, refresh }) {
  const [open, setOpen] = useState(false);
  const [show, setShow] = useState(false);
  const [devs, setDevs] = useState(null);
  const [confirm, setConfirm] = useState('');
  const [months, setMonths] = useState(a.trial ? 1 : 12);
  const [keepUhd, setKeepUhd] = useState(false);
  const [keepDevices, setKeepDevices] = useState(2);
  const call = async (path, body, ok) => {
    try { const r = (await api.post(`/api/cmtv/nuvio-reseller/accounts/${a.username}/${path}`, body || {})).data; toast.success(ok(r)); refresh(); return r; }
    catch (e) { toast.error(err(e, 'That did not work')); return null; }
  };
  const extendCost = months * (a.trial ? perMonth(keepDevices, keepUhd) : a.per_month);
  const left = monthsLeft(a.expires);
  const loadDevices = async () => {
    try { setDevs((await api.get(`/api/cmtv/nuvio-reseller/accounts/${a.username}/devices`)).data.devices); }
    catch (e) { toast.error(err(e, 'Could not load devices')); }
  };
  const ends = a.status === 'off' ? <span className="nvr-off">Switched off</span>
    : !a.live ? <span className="nvr-end">Ended {day(a.expires)}</span>
      : daysLeft(a.expires) <= 7 ? <span className="nvr-soon">{day(a.expires)} · {daysLeft(a.expires)} day{daysLeft(a.expires) === 1 ? '' : 's'}</span>
        : day(a.expires);
  return (
    <>
      <tr className={a.live && a.status !== 'off' ? '' : 'nvr-dim'}>
        <td><button type="button" className="nvr-name" onClick={() => setOpen(!open)}>{a.login}</button>
          {a.trial && <span className="nvr-pill">Trial</span>}{a.notes && <small>{a.notes}</small>}</td>
        <td>{ends}</td>
        <td>{a.uhd ? <span className="nvr-pill nvr-4k">4K</span> : 'HD'}</td>
        <td>{a.devices} of {a.max_devices}</td>
        <td className="nvr-right"><button type="button" className="ca-icon" onClick={() => setOpen(!open)}>{open ? 'Close' : 'Manage'}</button></td>
      </tr>
      {open && (
        <tr className="nvr-detail"><td colSpan={5}>
          <div className="nvr-actions">
            <span>Password: <code>{show ? a.password : '••••••'}</code></span>
            <button type="button" className="ca-icon" onClick={() => setShow(!show)}>{show ? 'Hide' : 'Show'}</button>
            <button type="button" className="ca-icon" onClick={() => copy(loginText(a), 'Login and setup')}>Copy login and setup</button>
            <button type="button" className="ca-icon" onClick={() => call('password', {}, (r) => `New password: ${r.password}`)}>New password</button>
          </div>
          <div className="nvr-actions">
            <b>{a.trial ? 'Keep this trial' : a.live ? 'Extend' : 'Renew'}</b>
            <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>{MONTHS.map((m) => <option key={m} value={m}>{m} month{m > 1 ? 's' : ''}</option>)}</select>
            {a.trial && <>
              <select value={keepDevices} onChange={(e) => setKeepDevices(Number(e.target.value))}>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n} device{n > 1 ? 's' : ''}</option>)}</select>
              <label className="nvr-check"><input type="checkbox" checked={keepUhd} onChange={(e) => setKeepUhd(e.target.checked)} /> 4K</label>
            </>}
            <button type="button" className="ca-btn ca-glow" disabled={extendCost > balance}
              onClick={() => call('extend', { months, devices: keepDevices, uhd: keepUhd }, (r) => `Now runs to ${day(r.expires)} (${r.cost} credits)`)}>
              {extendCost} credit{extendCost > 1 ? 's' : ''}</button>
          </div>
          {!a.trial && (
            <div className="nvr-actions">
              <b>4K</b>
              {a.uhd ? <button type="button" className="ca-icon" onClick={() => window.confirm('Turn 4K off? Credits already used are not refunded.') && call('uhd', { on: false }, () => '4K off')}>Turn off</button>
                : <button type="button" className="ca-icon" disabled={left > balance}
                  onClick={() => window.confirm(`Turn 4K on? It costs ${(left || 0) * UHD_EXTRA} credits (2 for each month left).`) && call('uhd', { on: true }, (r) => `4K on (${r.cost} credits)`)}>Turn on · {(left || 0) * UHD_EXTRA} credits</button>}
              <b>Devices</b>
              <select value={a.max_devices} onChange={(e) => {
                const n = Number(e.target.value); const cost = n > 2 && a.max_devices <= 2 ? left : 0;
                if (!cost || window.confirm(`${n} devices costs ${cost} credit${cost === 1 ? '' : 's'} (1 for each month left). Continue?`)) call('devices', { devices: n }, (r) => `${n} devices${r.cost ? ` (${r.cost} credits)` : ''}`);
              }}>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}</select>
            </div>
          )}
          <div className="nvr-actions">
            <button type="button" className="ca-icon" onClick={loadDevices}>Devices in use</button>
            {a.status === 'off'
              ? <button type="button" className="ca-icon" onClick={() => call('status', { off: false }, () => 'Switched on')}>Switch on</button>
              : <button type="button" className="ca-icon" onClick={() => call('status', { off: true }, () => 'Switched off: streams stop, the account is kept')}>Switch off</button>}
            <span className="nvr-del"><input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={`Type ${a.login} to delete`} />
              <button type="button" className="ca-icon nvr-danger" disabled={confirm.toLowerCase() !== a.login.toLowerCase()}
                onClick={() => call('delete', { confirm }, () => `${a.login} deleted`)}>Delete</button></span>
          </div>
          {devs && (
            <ul className="nvr-devs">
              {devs.length === 0 && <li>No devices signed in.</li>}
              {devs.map((d) => (
                <li key={d.session_id}>{d.device || d.app || 'Device'} {d.platform && `· ${d.platform}`}
                  <small> last used {d.last_used_at ? new Date(d.last_used_at).toLocaleDateString() : '–'}</small>
                  <button type="button" className="ca-icon" onClick={async () => { await call('sign-out', { session_id: d.session_id }, () => 'Signed out'); loadDevices(); }}>Sign out</button></li>
              ))}
            </ul>
          )}
        </td></tr>
      )}
    </>
  );
}

export default function NuvioReseller() {
  const qc = useQueryClient();
  const ref = useRef(null);
  const [params] = useSearchParams();
  const [buy, setBuy] = useState(false);
  const [q, setQ] = useState('');
  const { data: access } = useQuery({ queryKey: ['nuvio-reseller-access'], queryFn: async () => (await api.get('/api/cmtv/nuvio-reseller/access')).data, staleTime: 60000 });
  const { data, isLoading } = useQuery({ queryKey: ['nuvio-reseller'], enabled: !!access?.enabled,
    queryFn: async () => (await api.get('/api/cmtv/nuvio-reseller/mine')).data });
  const refresh = () => qc.invalidateQueries({ queryKey: ['nuvio-reseller'] });
  useEffect(() => { if (data && params.get('tab') === 'nuvio' && ref.current) ref.current.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [!!data]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (data?.accounts || []).filter((a) => !t || [a.login, a.notes].some((v) => (v || '').toLowerCase().includes(t)));
  }, [data, q]);
  if (!access?.enabled) return null;
  const trial = async () => {
    try {
      const r = (await api.post('/api/cmtv/nuvio-reseller/trials', {})).data;
      toast.success(`Trial ${r.login} made, login copied`);
      copy(loginText({ login: r.login, password: r.password, expires: r.expires }), 'Trial login');
      refresh();
    } catch (e) { toast.error(err(e, 'Could not make a trial')); }
  };
  const running = (data?.accounts || []).filter((a) => a.live && a.status !== 'off').length;
  return (
    <section className="ca-panel nvr" ref={ref} aria-label="Nuvio">
      <h2 className="ca-h2">Nuvio</h2>
      <p className="rt-note">Movies and series accounts for your customers. 1 credit = one account for one month with 2 devices;
        3-4 devices add 1 credit a month, 4K adds 2. When an account ends, your customer is told to contact you (your brand settings below).</p>
      {isLoading || !data ? <p>Loading…</p> : (
        <>
          <div className="nvr-stats">
            <div><span>Nuvio credits</span><b>{data.balance}</b><small>$1.00 each</small></div>
            <div><span>Accounts</span><b>{running}</b><small>{data.accounts.length - running} ended or off</small></div>
            <div><span>Free trials left</span><b>{data.trials_left}</b><small>this week · {data.trial_days * 24} h, HD</small></div>
          </div>
          <div className="rp-actions">
            <button type="button" className="ca-btn ca-ghost" onClick={() => setBuy(!buy)}>{buy ? 'Close' : 'Buy credits'}</button>
            <button type="button" className="ca-btn ca-ghost" disabled={!data.trials_left} onClick={trial}>Make a free trial</button>
          </div>
          {buy && <ResellerCredits lockServer="nuvio" topup="Nuvio" compact />}
          <NewAccount balance={data.balance} onDone={refresh} />
          {data.accounts.length > 0 && (
            <>
              <div className="nvr-row"><h3 className="rt-h3">Your accounts</h3>
                {data.accounts.length > 8 && <input className="nvr-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" />}</div>
              <div className="nvr-table-wrap">
                <table className="nvr-table">
                  <thead><tr><th>Account</th><th>Ends</th><th>Quality</th><th>Devices</th><th /></tr></thead>
                  <tbody>{rows.map((a) => <AccountRow key={a.username} a={a} balance={data.balance} refresh={refresh} />)}</tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
