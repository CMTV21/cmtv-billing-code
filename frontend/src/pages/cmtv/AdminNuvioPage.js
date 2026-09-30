// CMTV local addition 2026-09-29: Admin > Nuvio (backend: cmtv_nuvio.py -> CMTV's own Nuvio server, nuvio.cmtv.info).
// Accounts: who owns them, end date, devices (max 4), watch activity; extend / switch off / password / devices / links /
// delete. Add-ons: the real add-on links (kept only in billing); customers get personal links through billing's relay.
import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ArrowDown, ArrowUp, Check, Clock, Copy, Eye, EyeOff, KeyRound, Link2, MonitorSmartphone, Plus, Power,
  RefreshCw, Search, Send, Trash2, X, AlertTriangle } from 'lucide-react';
import api from '../../api/api';

const DAY = 86400000;
const SOON_DAYS = 14;
const errText = (e, fb) => e?.response?.data?.detail || fb;
const fmt = (d) => (d ? new Date(`${String(d).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const ago = (d) => {
  if (!d) return 'never';
  const m = Math.round((Date.now() - new Date(d).getTime()) / 60000);
  if (m < 2) return 'just now';
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
};
const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition';
const input = 'px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';
const PILL = {
  active: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  soon: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  expired: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  off: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
};

function statusOf(a) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = a.expires ? Math.round((new Date(`${a.expires}T00:00:00`).getTime() - today.getTime()) / DAY) : null;
  if (a.status === 'off') return { key: 'off', label: 'Switched off', days };
  if (days !== null && days < 0) return { key: 'expired', label: 'Expired', days };
  if (days !== null && days <= SOON_DAYS) return { key: 'soon', label: 'Ending soon', days };
  return { key: 'active', label: 'Active', days };
}

function CopyBtn({ text }) {
  return (
    <button type="button" title="Copy" className="text-gray-500 hover:text-blue-600"
      onClick={() => { navigator.clipboard.writeText(text); toast.success('Copied'); }}>
      <Copy className="w-4 h-4" />
    </button>
  );
}

function Modal({ title, onClose, children, wide }) {
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div className={`bg-white dark:bg-gray-900 w-full ${wide ? 'sm:max-w-2xl' : 'sm:max-w-lg'} rounded-t-2xl sm:rounded-2xl shadow-xl max-h-[90vh] overflow-y-auto`}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="font-bold text-gray-900 dark:text-white">{title}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function CustomerPicker({ value, onChange }) {
  const [q, setQ] = useState('');
  const { data } = useQuery({
    queryKey: ['nuvio-customers', q],
    queryFn: async () => (await api.get('/api/cmtv/addons/customers', { params: { q } })).data,
    enabled: q.trim().length >= 2,
  });
  if (value) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2">
        <span className="text-sm text-gray-900 dark:text-white">{value.name} <span className="text-gray-500">{value.email}</span></span>
        <button type="button" className="text-gray-400 hover:text-gray-600" onClick={() => onChange(null)}><X className="w-4 h-4" /></button>
      </div>
    );
  }
  const list = data?.customers || data || [];
  return (
    <div>
      <input className={`${input} w-full`} placeholder="Search name or email (optional)" value={q} onChange={(e) => setQ(e.target.value)} />
      {Array.isArray(list) && list.length > 0 && (
        <div className="mt-1 border border-gray-200 dark:border-gray-700 rounded-lg max-h-48 overflow-y-auto">
          {list.slice(0, 20).map((c) => (
            <button type="button" key={c.id} onClick={() => onChange(c)}
              className="block w-full text-left px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-900 dark:text-white">
              {c.name} <span className="text-gray-500">{c.email}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function NewAccount({ onClose, onDone }) {
  const [f, setF] = useState({ username: '', password: '', months: 12, customer: null, send_email: true, notes: '' });
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState(null);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post('/api/cmtv/nuvio/accounts', {
        username: f.username.trim(), password: f.password.trim(), months: Number(f.months), notes: f.notes,
        user_id: f.customer?.id || undefined, send_email: !!f.customer && f.send_email,
      });
      setMade(r.data); onDone();
    } catch (e) { toast.error(errText(e, 'Could not create the account')); }
    setBusy(false);
  };
  if (made) {
    return (
      <Modal title="Account ready" onClose={onClose}>
        <div className="space-y-2 text-sm text-gray-900 dark:text-white">
          <p className="flex items-center gap-2">Username: <b>{made.username}</b> <CopyBtn text={made.username} /></p>
          <p className="flex items-center gap-2">Password: <b>{made.password}</b> <CopyBtn text={made.password} /></p>
          <p>Ends {fmt(made.expires)}</p>
          <p className="text-gray-500">Official Nuvio app: server <b>nuvio.cmtv.info</b>, sign in with <b>{made.username}@nuvio.cmtv.info</b>.</p>
        </div>
      </Modal>
    );
  }
  return (
    <Modal title="New Nuvio account" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm text-gray-700 dark:text-gray-300">Username
            <input className={`${input} w-full mt-1`} placeholder="automatic" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
          </label>
          <label className="text-sm text-gray-700 dark:text-gray-300">Password
            <input className={`${input} w-full mt-1`} placeholder="automatic" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          </label>
        </div>
        <label className="text-sm text-gray-700 dark:text-gray-300 block">Length
          <select className={`${input} w-full mt-1`} value={f.months} onChange={(e) => setF({ ...f, months: e.target.value })}>
            {[1, 3, 6, 12, 24].map((m) => <option key={m} value={m}>{m} month{m > 1 ? 's' : ''}</option>)}
          </select>
        </label>
        <div className="text-sm text-gray-700 dark:text-gray-300">Customer
          <div className="mt-1"><CustomerPicker value={f.customer} onChange={(c) => setF({ ...f, customer: c })} /></div>
        </div>
        {f.customer && (
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={f.send_email} onChange={(e) => setF({ ...f, send_email: e.target.checked })} /> Email them the login
          </label>
        )}
        <input className={`${input} w-full`} placeholder="Note (optional)" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        <button type="button" disabled={busy} onClick={submit} className={`${btn} bg-blue-600 text-white hover:bg-blue-700 w-full justify-center`}>
          <Plus className="w-4 h-4" /> {busy ? 'Creating…' : 'Create account'}
        </button>
      </div>
    </Modal>
  );
}

function Devices({ acc, onClose }) {
  const qc = useQueryClient();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['nuvio-devices', acc.username],
    queryFn: async () => (await api.get(`/api/cmtv/nuvio/accounts/${acc.username}/devices`)).data,
  });
  const [max, setMax] = useState(acc.max_devices || 4);
  const out = async (session_id) => {
    try {
      const r = await api.post(`/api/cmtv/nuvio/accounts/${acc.username}/devices/sign-out`, session_id ? { session_id } : {});
      toast.success(`Signed out ${r.data.signed_out} device${r.data.signed_out === 1 ? '' : 's'}`);
      refetch(); qc.invalidateQueries({ queryKey: ['nuvio-accounts'] });
    } catch (e) { toast.error(errText(e, 'Could not sign out')); }
  };
  const saveMax = async () => {
    try { await api.post(`/api/cmtv/nuvio/accounts/${acc.username}/max-devices`, { max_devices: Number(max) }); toast.success('Saved'); qc.invalidateQueries({ queryKey: ['nuvio-accounts'] }); }
    catch (e) { toast.error(errText(e, 'Could not save')); }
  };
  const devs = data?.devices || [];
  return (
    <Modal title={`Devices: ${acc.username}`} onClose={onClose} wide>
      {isLoading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="space-y-4">
          {devs.length === 0 ? <p className="text-sm text-gray-500">Not signed in on any device.</p> : (
            <div className="divide-y divide-gray-200 dark:divide-gray-700">
              {devs.map((d) => (
                <div key={d.session_id} className="flex items-center justify-between py-2 gap-3">
                  <div className="text-sm">
                    <p className="font-semibold text-gray-900 dark:text-white">{d.app || 'App'} {d.app_version ? `${d.app_version}` : ''}
                      {!d.counts && <span className="ml-2 text-xs text-gray-500">(idle 30+ days, doesn't count)</span>}</p>
                    <p className="text-gray-500">{[d.platform, d.device].filter(Boolean).join(' · ') || d.user_agent}</p>
                    <p className="text-gray-500">Signed in {fmt(d.signed_in_at)} · used {ago(d.last_used_at)}</p>
                  </div>
                  <button type="button" className={`${btn} bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200`} onClick={() => out(d.session_id)}>Sign out</button>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={`${btn} bg-red-600 text-white hover:bg-red-700`} disabled={!devs.length} onClick={() => out(null)}>Sign out all devices</button>
            <span className="ml-auto text-sm text-gray-700 dark:text-gray-300">Max devices</span>
            <select className={input} value={max} onChange={(e) => setMax(e.target.value)}>{[1, 2, 3, 4, 5, 6, 8, 10].map((n) => <option key={n}>{n}</option>)}</select>
            <button type="button" className={`${btn} bg-blue-600 text-white`} onClick={saveMax}>Save</button>
          </div>
          {data?.connections?.length > 0 && (
            <div>
              <p className="text-sm font-semibold text-gray-900 dark:text-white mb-1">Internet connections that asked for streams (last 3 days)</p>
              <ul className="text-sm text-gray-600 dark:text-gray-400 space-y-0.5">
                {data.connections.map((c) => <li key={c.ip}>{c.ip} · {ago(c.last)}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function Row({ a, refresh }) {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState('');
  const [modal, setModal] = useState('');
  const [date, setDate] = useState('');
  const [confirm, setConfirm] = useState('');
  const s = statusOf(a);
  const call = async (path, body, ok) => {
    try { const r = await api.post(`/api/cmtv/nuvio/accounts/${a.username}/${path}`, body || {}); toast.success(ok); refresh(); return r.data; }
    catch (e) { toast.error(errText(e, 'That did not work')); return null; }
  };
  const showPw = async () => {
    if (pw) { setPw(''); return; }
    try { setPw((await api.get(`/api/cmtv/nuvio/accounts/${a.username}/password`)).data.password); } catch (e) { toast.error(errText(e, 'Could not load')); }
  };
  return (
    <>
      <tr className="border-t border-gray-200 dark:border-gray-700 align-top">
        <td className="px-3 py-3">
          <button type="button" className="font-semibold text-blue-700 dark:text-blue-300 hover:underline" onClick={() => setOpen(!open)}>{a.username}</button>
          {a.share_alert && <span title={`${a.share_alert.ips} internet connections at once (${ago(a.share_alert.at)})`} className="ml-2 inline-flex items-center text-amber-600"><AlertTriangle className="w-4 h-4" /></span>}
          {a.notes && <p className="text-xs text-gray-500">{a.notes}</p>}
        </td>
        <td className="px-3 py-3 text-sm">
          {a.customer ? <a className="text-gray-900 dark:text-white hover:underline" href={`/admin/customer/${a.customer.id}`}>{a.customer.name}<br /><span className="text-gray-500">{a.customer.email}</span></a>
            : <span className="text-gray-400">No customer</span>}
        </td>
        <td className="px-3 py-3"><span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${PILL[s.key]}`}>{s.label}</span></td>
        <td className="px-3 py-3 text-sm text-gray-900 dark:text-white whitespace-nowrap">{fmt(a.expires)}</td>
        <td className="px-3 py-3 text-sm whitespace-nowrap">
          <button type="button" className="inline-flex items-center gap-1 text-gray-800 dark:text-gray-200 hover:text-blue-600" onClick={() => setModal('devices')}>
            <MonitorSmartphone className="w-4 h-4" /> {a.devices}/{a.max_devices}
          </button>
        </td>
        <td className="px-3 py-3 text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">{ago(a.last_seen)}<br />{a.watched} watched</td>
      </tr>
      {open && (
        <tr className="bg-gray-50 dark:bg-gray-800/50">
          <td colSpan={6} className="px-3 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-gray-700 dark:text-gray-300 flex items-center gap-2">Password: {pw ? <><b>{pw}</b><CopyBtn text={pw} /></> : '••••••'}
                <button type="button" onClick={showPw} className="text-gray-500">{pw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}</button></span>
              <span className="mx-2 h-5 w-px bg-gray-300 dark:bg-gray-600" />
              {[1, 3, 12].map((m) => (
                <button key={m} type="button" className={`${btn} bg-blue-600 text-white hover:bg-blue-700`} onClick={() => call('extend', { months: m }, `Extended ${m} month${m > 1 ? 's' : ''}`)}>
                  <Clock className="w-4 h-4" /> +{m} mo</button>
              ))}
              <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
              <button type="button" disabled={!date} className={`${btn} bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white`} onClick={() => call('extend', { expiry_date: date }, 'End date set')}>Set date</button>
              <span className="mx-2 h-5 w-px bg-gray-300 dark:bg-gray-600" />
              {a.status === 'off'
                ? <button type="button" className={`${btn} bg-emerald-600 text-white`} onClick={() => call('enable', {}, 'Switched on')}><Power className="w-4 h-4" /> Switch on</button>
                : <button type="button" className={`${btn} bg-gray-700 text-white`} onClick={() => call('disable', {}, 'Switched off: streams stop, history is kept')}><Power className="w-4 h-4" /> Switch off</button>}
              <button type="button" className={`${btn} bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white`} onClick={async () => { const r = await call('password', {}, 'New password set'); if (r) setPw(r.password); }}><KeyRound className="w-4 h-4" /> New password</button>
              <button type="button" className={`${btn} bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white`} onClick={() => call('push-addons', {}, 'Add-ons sent to the account')}><Send className="w-4 h-4" /> Re-send add-ons</button>
              <button type="button" title="Makes new personal add-on links; the old ones stop working (use if they were shared)" className={`${btn} bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white`} onClick={() => call('new-links', {}, 'New add-on links made')}><Link2 className="w-4 h-4" /> New links</button>
              <button type="button" className={`${btn} bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300 ml-auto`} onClick={() => setModal('delete')}><Trash2 className="w-4 h-4" /> Delete</button>
            </div>
            <p className="text-xs text-gray-500 mt-2">{a.profiles} profile{a.profiles === 1 ? '' : 's'} · {a.in_progress} in progress · official app login {a.username}@nuvio.cmtv.info</p>
          </td>
        </tr>
      )}
      {modal === 'devices' && <Devices acc={a} onClose={() => setModal('')} />}
      {modal === 'delete' && (
        <Modal title={`Delete ${a.username}?`} onClose={() => setModal('')}>
          <p className="text-sm text-gray-700 dark:text-gray-300 mb-3">This wipes their profiles, add-ons and watch history and removes the account from the Nuvio server.
            Billing keeps a copy of the account record. To stop streams but keep their history, use <b>Switch off</b> instead.</p>
          <input className={`${input} w-full`} placeholder={`Type ${a.username} to confirm`} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button type="button" disabled={confirm.toLowerCase() !== a.username} className={`${btn} bg-red-600 text-white w-full justify-center mt-3`}
            onClick={async () => { if (await call('delete', { confirm }, 'Deleted')) setModal(''); }}><Trash2 className="w-4 h-4" /> Delete for good</button>
        </Modal>
      )}
    </>
  );
}

function Accounts() {
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [adding, setAdding] = useState(false);
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['nuvio-accounts'],
    queryFn: async () => (await api.get('/api/cmtv/nuvio/accounts')).data,
  });
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (data?.accounts || []).filter((a) => !t || [a.username, a.customer?.name, a.customer?.email, a.notes].some((v) => (v || '').toLowerCase().includes(t)));
  }, [data, q]);
  const refresh = () => qc.invalidateQueries({ queryKey: ['nuvio-accounts'] });
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
          <input className={`${input} pl-9 w-64`} placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button type="button" onClick={() => refetch()} className={`${btn} bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white`}><RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /> Refresh</button>
        <button type="button" onClick={() => setAdding(true)} className={`${btn} bg-blue-600 text-white hover:bg-blue-700 ml-auto`}><Plus className="w-4 h-4" /> New account</button>
      </div>
      {data && !data.server_ok && <p className="mb-3 text-sm text-red-600">The Nuvio server didn't answer, so devices and activity aren't shown.</p>}
      {isLoading ? <p className="text-sm text-gray-500">Loading…</p> : rows.length === 0 ? (
        <p className="text-sm text-gray-500">No accounts yet. They're made automatically when a customer buys a product set to "Nuvio (CMTV server)", or with New account.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
          <table className="w-full text-left">
            <thead className="bg-gray-50 dark:bg-gray-800 text-xs uppercase text-gray-500">
              <tr><th className="px-3 py-2">Username</th><th className="px-3 py-2">Customer</th><th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Ends</th><th className="px-3 py-2">Devices</th><th className="px-3 py-2">Last used</th></tr>
            </thead>
            <tbody>{rows.map((a) => <Row key={a.username} a={a} refresh={refresh} />)}</tbody>
          </table>
        </div>
      )}
      {adding && <NewAccount onClose={() => setAdding(false)} onDone={refresh} />}
    </div>
  );
}

function Addons() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['nuvio-addons'],
    queryFn: async () => (await api.get('/api/cmtv/nuvio/addons')).data,
  });
  const [rows, setRows] = useState(null);
  const [show, setShow] = useState({});
  const [busy, setBusy] = useState(false);
  const list = rows ?? data?.addons ?? [];
  const set = (i, patch) => setRows(list.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i, d) => { const r = [...list]; const [x] = r.splice(i, 1); r.splice(i + d, 0, x); setRows(r); };
  const save = async () => {
    setBusy(true);
    try { await api.put('/api/cmtv/nuvio/addons', { addons: list }); toast.success('Saved'); setRows(null); refetch(); }
    catch (e) { toast.error(errText(e, 'Could not save')); }
    setBusy(false);
  };
  const pushAll = async () => {
    if (!window.confirm('Send this add-on list to every Nuvio account now? Add-ons customers added themselves are kept.')) return;
    try { const r = await api.post('/api/cmtv/nuvio/addons/push-all'); toast.success(`Sending to ${r.data.accounts} accounts in the background`); }
    catch (e) { toast.error(errText(e, 'Could not start')); }
  };
  if (isLoading) return <p className="text-sm text-gray-500">Loading…</p>;
  return (
    <div className="max-w-4xl">
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Paste the real add-on links here (they end in <b>/manifest.json</b>). They stay in billing only:
        each customer gets their own link through <b>{data?.base}</b>, which stops giving streams when their account ends or is switched off.
        New accounts get this list automatically. After changing it, use <b>Send to all accounts</b>.</p>
      <div className="space-y-3">
        {list.map((a, i) => (
          <div key={a.slug || `new-${i}`} className="rounded-xl border border-gray-200 dark:border-gray-700 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <input className={`${input} flex-1`} placeholder="Name shown in the app (e.g. AIOStreams)" value={a.name} onChange={(e) => set(i, { name: e.target.value })} />
              <label className="flex items-center gap-1 text-sm text-gray-700 dark:text-gray-300"><input type="checkbox" checked={a.enabled !== false} onChange={(e) => set(i, { enabled: e.target.checked })} /> On</label>
              <button type="button" disabled={i === 0} onClick={() => move(i, -1)} className="text-gray-500 disabled:opacity-30"><ArrowUp className="w-4 h-4" /></button>
              <button type="button" disabled={i === list.length - 1} onClick={() => move(i, 1)} className="text-gray-500 disabled:opacity-30"><ArrowDown className="w-4 h-4" /></button>
              <button type="button" onClick={() => setRows(list.filter((_, j) => j !== i))} className="text-red-500" title="Remove"><Trash2 className="w-4 h-4" /></button>
            </div>
            <div className="flex items-center gap-2">
              <input type={show[i] ? 'text' : 'password'} className={`${input} flex-1 font-mono text-xs`} placeholder="https://…/manifest.json" value={a.url} onChange={(e) => set(i, { url: e.target.value })} />
              <button type="button" onClick={() => setShow({ ...show, [i]: !show[i] })} className="text-gray-500">{show[i] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}</button>
            </div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="button" onClick={() => setRows([...list, { name: '', url: '', enabled: true }])} className={`${btn} bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white`}><Plus className="w-4 h-4" /> Add an add-on</button>
        <button type="button" disabled={busy || rows === null} onClick={save} className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}><Check className="w-4 h-4" /> Save</button>
        <button type="button" disabled={rows !== null || !list.length} onClick={pushAll} className={`${btn} bg-emerald-600 text-white hover:bg-emerald-700 ml-auto`}><Send className="w-4 h-4" /> Send to all accounts</button>
      </div>
    </div>
  );
}

const ABI_LABEL = { 'arm64-v8a': 'Newer Fire Sticks / Android TV (arm64)', 'armeabi-v7a': 'Older Fire Sticks (armv7)',
  x86_64: 'Emulators / BlueStacks (x86_64)', x86: 'Old emulators (x86)', universal: 'Any device (large)' };
const mb = (n) => `${Math.round((n || 0) / 1048576)} MB`;

function AppTab() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['nuvio-app'],
    queryFn: async () => (await api.get('/api/cmtv/nuvio/app')).data,
  });
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState('');
  const publish = async (b) => {
    const msg = b.updater
      ? `Publish ${b.version}? Every CMTV Nuvio app (from cmtv.3 on) will be offered this update.`
      : `Publish ${b.version}? This build can't update itself later (it's from before cmtv.3), so only use it for testing.`;
    if (!window.confirm(msg)) return;
    setBusy(b.version);
    try { await api.post('/api/cmtv/nuvio/app/publish', { version: b.version, notes }); toast.success(`${b.version} published`); setNotes(''); refetch(); }
    catch (e) { toast.error(errText(e, 'Could not publish')); }
    setBusy('');
  };
  if (isLoading) return <p className="text-sm text-gray-500">Loading…</p>;
  const pub = data?.published;
  return (
    <div className="max-w-4xl space-y-6">
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <h2 className="font-bold text-gray-900 dark:text-white mb-1">Published version</h2>
        {!pub ? <p className="text-sm text-gray-500">Nothing published yet. Apps won't be offered an update until you publish one.</p> : (
          <>
            <p className="text-sm text-gray-700 dark:text-gray-300"><b>{pub.tag}</b> · published {fmt(pub.published_at)} by {pub.published_by}</p>
            {pub.notes && <p className="text-sm text-gray-500 mt-1 whitespace-pre-line">{pub.notes}</p>}
            <div className="mt-3 space-y-1">
              {(pub.assets || []).map((a) => (
                <div key={a.name} className="flex items-center gap-2 text-sm">
                  <span className="w-72 text-gray-700 dark:text-gray-300">{ABI_LABEL[a.abi] || a.abi}</span>
                  <a className="text-blue-600 hover:underline truncate" href={a.url}>{a.name}</a>
                  <span className="text-gray-500">{mb(a.size)}</span><CopyBtn text={a.url} />
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-500 mt-2">Use the arm64 / armv7 links for Downloads and the Downloader code page.</p>
          </>
        )}
      </div>
      <div>
        <h2 className="font-bold text-gray-900 dark:text-white mb-2">Builds</h2>
        <textarea className={`${input} w-full mb-2`} rows={2} placeholder="What's new (shown in the app's update prompt, optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="divide-y divide-gray-200 dark:divide-gray-700 rounded-xl border border-gray-200 dark:border-gray-700">
          {(data?.builds || []).map((b) => (
            <div key={b.version} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="flex-1 min-w-[12rem]">
                <p className="font-semibold text-gray-900 dark:text-white">{b.version}
                  {b.published && <span className="ml-2 px-2 py-0.5 rounded-full text-xs bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">Published</span>}
                  {!b.updater && <span className="ml-2 px-2 py-0.5 rounded-full text-xs bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200">No auto-update</span>}</p>
                <p className="text-xs text-gray-500">Built {fmt(b.built_at)} · {b.abis.length} files · up to {mb(b.size)}</p>
              </div>
              <button type="button" disabled={!!busy || b.published} onClick={() => publish(b)}
                className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}><Send className="w-4 h-4" /> {busy === b.version ? 'Publishing…' : 'Publish'}</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AdminNuvioPage() {
  const [tab, setTab] = useState(() => {
    const t = new URLSearchParams(window.location.search).get('tab');
    return ['addons', 'app'].includes(t) ? t : 'accounts';
  });
  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Nuvio</h1>
        <span className="text-sm text-gray-500">CMTV's own Nuvio server · nuvio.cmtv.info</span>
        <div className="ml-auto flex rounded-lg bg-gray-100 dark:bg-gray-800 p-1">
          {[['accounts', 'Accounts'], ['addons', 'Add-ons'], ['app', 'App']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setTab(k)}
              className={`px-4 py-1.5 rounded-md text-sm font-semibold ${tab === k ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow' : 'text-gray-600 dark:text-gray-400'}`}>{l}</button>
          ))}
        </div>
      </div>
      {tab === 'accounts' ? <Accounts /> : tab === 'addons' ? <Addons /> : <AppTab />}
    </div>
  );
}
