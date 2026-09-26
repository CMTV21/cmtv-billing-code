// CMTV local addition 2026-09-26: Admin > Add-ons (backend: cmtv_addons.py -> cockpit_helper.py).
// Every Stremio (or CMTVpn) user in Cockpit: who it belongs to, when it runs out, and extend / switch off / new password.
// Routes /admin/stremio and /admin/cmtvpn (separate pages, 2026-09-26); /admin/addons redirects to Stremio.
import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AlertTriangle, Check, Clock, Copy, Eye, EyeOff, KeyRound, Link2, Plus, Power, RefreshCw, Search, X } from 'lucide-react';
import api from '../../api/api';

const SOON_DAYS = 14;
const DAY = 86400000;
const MODS = { nuvio: 'Stremio', vpn: 'CMTVpn' };
const LOGO = { vpn: '/cmtv/cmtvpn.png' };   // no Stremio logo on the site: Stremio gets a lettered tile
const errText = (e, fb) => e?.response?.data?.detail || fb;
const fmt = (d) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const enc = encodeURIComponent;

function statusOf(u, today) {
  const t = new Date(`${today}T00:00:00`).getTime();
  const days = u.expiry_date ? Math.round((new Date(`${u.expiry_date}T00:00:00`).getTime() - t) / DAY) : null;
  if (u.paused) return { key: 'off', label: 'Switched off', days };
  if (days !== null && days < 0) return { key: 'expired', label: 'Expired', days };
  if (days !== null && days <= SOON_DAYS) return { key: 'soon', label: 'Ending soon', days };
  return { key: 'active', label: 'Active', days };
}
const PILL = {
  active: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  soon: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  expired: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  off: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
};
function daysText(s) {
  if (s.days === null) return '';
  if (s.days === 0) return 'today';
  return s.days > 0 ? `in ${s.days} day${s.days === 1 ? '' : 's'}` : `${-s.days} day${s.days === -1 ? '' : 's'} ago`;
}

const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition';
const input = 'px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';

function CopyBtn({ text }) {
  return (
    <button type="button" title="Copy" className="text-gray-500 hover:text-blue-600"
      onClick={() => { navigator.clipboard.writeText(text); toast.success('Copied'); }}>
      <Copy className="w-4 h-4" />
    </button>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-900 w-full sm:max-w-lg rounded-t-2xl sm:rounded-2xl shadow-xl max-h-[90vh] overflow-y-auto"
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
    queryKey: ['addon-customers', q],
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
  return (
    <div>
      <input className={`${input} w-full`} placeholder="Search billing customers by name or email" value={q} onChange={(e) => setQ(e.target.value)} />
      {(data || []).length > 0 && (
        <ul className="mt-1 border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-800 max-h-48 overflow-y-auto">
          {data.map((c) => (
            <li key={c.id}>
              <button type="button" className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={() => { onChange(c); setQ(''); }}>
                <span className="text-gray-900 dark:text-white">{c.name}</span> <span className="text-gray-500">{c.email}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Chips({ value, onChange, options }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {options.map(([v, label]) => (
        <button key={v} type="button" onClick={() => onChange(v)}
          className={`${btn} border ${value === v ? 'bg-blue-600 border-blue-600 text-white' : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'}`}>
          {label}
        </button>
      ))}
    </div>
  );
}
const TERMS = [[1, '1 month'], [3, '3 months'], [12, '1 year']];

function NewUserModal({ module, onClose, onDone }) {
  const [customer, setCustomer] = useState(null);
  const [months, setMonths] = useState(12);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/api/cmtv/addons/${module}/users`, {
        months, username: username.trim(), customer_id: customer?.id, email_customer: !!customer && email,
      });
      setResult(data); onDone();
    } catch (e) { toast.error(errText(e, "Couldn't create the account")); } finally { setBusy(false); }
  };
  return (
    <Modal title={`New ${MODS[module]} account`} onClose={onClose}>
      {result ? (
        <div className="space-y-3">
          <p className="text-sm text-gray-700 dark:text-gray-300">Account created until <b>{fmt(result.expiry_date)}</b>{result.emailed ? ', and the login was emailed to the customer.' : '.'}</p>
          <div className="rounded-lg bg-gray-900 text-white p-4 space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-gray-400">Username</span><span className="flex items-center gap-2 font-mono">{result.username}<CopyBtn text={result.username} /></span></div>
            <div className="flex justify-between"><span className="text-gray-400">Password</span><span className="flex items-center gap-2 font-mono">{result.password}<CopyBtn text={result.password} /></span></div>
          </div>
          <button type="button" className={`${btn} bg-blue-600 text-white w-full justify-center py-2`} onClick={onClose}>Done</button>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Billing customer <span className="text-gray-400 font-normal">(optional)</span></label>
            <CustomerPicker value={customer} onChange={setCustomer} />
            <p className="text-xs text-gray-500 mt-1">Linking a customer puts the account in their My Services.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Length</label>
            <Chips value={months} onChange={setMonths} options={TERMS} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Username <span className="text-gray-400 font-normal">(leave blank for a random one)</span></label>
            <input className={`${input} w-full`} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="e.g. johnsmith" />
          </div>
          {customer && (
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> Email the login to {customer.name}
            </label>
          )}
          <button type="button" disabled={busy} onClick={submit} className={`${btn} bg-blue-600 text-white w-full justify-center py-2`}>
            {busy ? 'Creating…' : 'Create account'}
          </button>
        </div>
      )}
    </Modal>
  );
}

function ExtendModal({ user, onClose, onDone }) {
  const [months, setMonths] = useState(12);
  const [date, setDate] = useState('');
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/api/cmtv/addons/${user.module}/users/${enc(user.username)}/extend`, date ? { expiry_date: date } : { months });
      toast.success(`${user.username} now runs until ${fmt(data.expiry_date)}`);
      onDone(); onClose();
    } catch (e) { toast.error(errText(e, "Couldn't extend")); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Extend ${user.username} (${user.label})`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {user.expiry_date ? <>Currently until <b>{fmt(user.expiry_date)}</b>. Time is added from that date, or from today if it has passed.</> : 'Time is added from today.'}
        </p>
        <Chips value={date ? null : months} onChange={(m) => { setMonths(m); setDate(''); }} options={TERMS} />
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Or pick an exact end date</label>
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        {user.paused && <p className="text-sm text-emerald-700 dark:text-emerald-400">This also switches the account back on.</p>}
        <button type="button" disabled={busy} onClick={go} className={`${btn} bg-blue-600 text-white w-full justify-center py-2`}>{busy ? 'Saving…' : 'Extend'}</button>
      </div>
    </Modal>
  );
}

function LinkModal({ user, onClose, onDone }) {
  const [customer, setCustomer] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`Link ${user.username} to a customer`} onClose={onClose}>
      <div className="space-y-4">
        <CustomerPicker value={customer} onChange={setCustomer} />
        <p className="text-xs text-gray-500">The account then shows in their My Services, and changes made here update billing too.</p>
        <button type="button" disabled={!customer || busy} className={`${btn} bg-blue-600 text-white w-full justify-center py-2`}
          onClick={async () => {
            setBusy(true);
            try { await api.post(`/api/cmtv/addons/${user.module}/link`, { username: user.username, customer_id: customer.id }); toast.success('Linked'); onDone(); onClose(); }
            catch (e) { toast.error(errText(e, "Couldn't link")); } finally { setBusy(false); }
          }}>Link</button>
      </div>
    </Modal>
  );
}

function Password({ value }) {
  const [show, setShow] = useState(false);
  if (!value) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
      <KeyRound className="w-3 h-3" />
      <span className="font-mono">{show ? value : '••••••••'}</span>
      <button type="button" title={show ? 'Hide' : 'Show'} onClick={() => setShow(!show)} className="hover:text-blue-600">{show ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}</button>
      {show && <CopyBtn text={value} />}
    </span>
  );
}

// One page per add-on (2026-09-26, the user's choice): <AdminAddonsPage module="nuvio" /> or module="vpn"
export default function AdminAddonsPage({ module = 'nuvio' }) {
  const qc = useQueryClient();
  const mod = module;
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [modal, setModal] = useState(null);
  const [pw, setPw] = useState(null);
  const [busy, setBusy] = useState('');
  const [linkPick, setLinkPick] = useState({});
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['addon-users'],
    queryFn: async () => (await api.get('/api/cmtv/addons/users')).data,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['addon-users'] });
  const today = data?.today || new Date().toISOString().slice(0, 10);

  const users = useMemo(() => (data?.users || []).map((u) => ({ ...u, s: statusOf(u, today) }))
    .sort((a, b) => (a.s.days ?? 99999) - (b.s.days ?? 99999)), [data, today]);
  const inMod = users.filter((u) => u.module === mod);
  const counts = useMemo(() => {
    const c = { all: inMod.length, active: 0, soon: 0, expired: 0, off: 0, unlinked: 0 };
    inMod.forEach((u) => { c[u.s.key] += 1; if (!u.customer) c.unlinked += 1; });
    return c;
  }, [inMod]);
  const shown = inMod.filter((u) => {
    const f = filter === 'all' || (filter === 'unlinked' ? !u.customer : u.s.key === filter);
    const t = q.trim().toLowerCase();
    return f && (!t || [u.username, u.customer?.name, u.customer?.email].some((x) => String(x || '').toLowerCase().includes(t)));
  });
  const unlinked = (data?.unlinked_services || []).filter((s) => s.module === mod);
  const errors = (data?.errors || []).filter((e) => e.startsWith(`${MODS[mod]}:`));

  const act = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (ok) toast.success(ok); refresh(); return r; }
    catch (e) { toast.error(errText(e, 'Something went wrong')); return null; } finally { setBusy(''); }
  };

  const tiles = [
    ['all', 'All accounts', counts.all, 'text-gray-900 dark:text-white'],
    ['active', 'Active', counts.active, 'text-emerald-600'],
    ['soon', `Ending in ${SOON_DAYS} days`, counts.soon, 'text-amber-600'],
    ['expired', 'Expired', counts.expired, 'text-red-600'],
    ['off', 'Switched off', counts.off, 'text-gray-500'],
    ['unlinked', 'No billing customer', counts.unlinked, 'text-blue-600'],
  ];
  const path = (u, what) => `/api/cmtv/addons/${u.module}/users/${enc(u.username)}/${what}`;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-4 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">{MODS[mod]}</h1>
          <div className="ml-auto flex gap-2">
            <button type="button" onClick={refresh} title="Reload" className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}><RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /></button>
            <button type="button" onClick={() => setModal({ type: 'new' })} className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}><Plus className="w-4 h-4" /> New {MODS[mod]} account</button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-5">
        {error && <div className="rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 p-4 text-sm">{errText(error, "Couldn't load the Cockpit accounts")}</div>}
        {errors.map((e) => <div key={e} className="rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200 p-3 text-sm">{e}</div>)}

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {tiles.map(([key, label, n, color]) => (
            <button key={key} type="button" onClick={() => setFilter(key)}
              className={`text-left rounded-xl p-4 bg-white dark:bg-gray-900 shadow-sm border-2 transition ${filter === key ? 'border-blue-500' : 'border-transparent hover:border-gray-200 dark:hover:border-gray-700'}`}>
              <p className={`text-2xl font-bold ${color}`}>{n}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</p>
            </button>
          ))}
        </div>

        {unlinked.length > 0 && (
          <section className="rounded-xl bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800 p-4 space-y-3">
            <h2 className="font-semibold text-amber-900 dark:text-amber-200 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> Orders not tied to an account ({unlinked.length})</h2>
            <p className="text-sm text-amber-900 dark:text-amber-200">{MODS[mod]} services in billing that were set up by hand. Pick their Cockpit account so renewals and changes work:</p>
            <ul className="space-y-2">
              {unlinked.map((s) => (
                <li key={s.service_id} className="flex flex-wrap items-center gap-2 bg-white dark:bg-gray-900 rounded-lg px-3 py-2">
                  <span className="flex-1 min-w-[180px] text-sm">
                    <span className="font-semibold text-gray-900 dark:text-white">{s.customer?.name || 'Unknown customer'}</span>
                    <span className="text-gray-500"> · {s.product_name}{s.expiry_date ? ` · until ${fmt(s.expiry_date)}` : ''}</span>
                    <span className="block text-xs text-gray-500">{s.customer?.email}</span>
                  </span>
                  <select className={input} value={linkPick[s.service_id] || ''} onChange={(e) => setLinkPick({ ...linkPick, [s.service_id]: e.target.value })}>
                    <option value="">Choose account…</option>
                    {users.filter((u) => u.module === s.module).map((u) => <option key={u.username} value={u.username}>{u.username}{u.customer ? ` (${u.customer.name})` : ''}</option>)}
                  </select>
                  <button type="button" disabled={!linkPick[s.service_id] || busy === `lnk-${s.service_id}`} className={`${btn} bg-blue-600 text-white`}
                    onClick={() => act(`lnk-${s.service_id}`, () => api.post(`/api/cmtv/addons/${s.module}/link`, { username: linkPick[s.service_id], service_id: s.service_id }), 'Linked')}>
                    <Link2 className="w-4 h-4" /> Link
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="relative">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input className={`${input} w-full pl-9 py-2.5`} placeholder="Search by username, customer name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm overflow-hidden">
          {isLoading ? <p className="p-6 text-sm text-gray-500">Loading accounts from Cockpit…</p> : shown.length === 0 ? (
            <p className="p-6 text-sm text-gray-500 dark:text-gray-400">No accounts match.</p>
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-gray-800">
              {shown.map((u) => (
                <li key={`${u.module}-${u.username}`} className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                  {LOGO[u.module] ? (
                    <img src={LOGO[u.module]} alt={u.label} title={u.label} className="w-9 h-9 rounded-lg object-contain bg-gray-900 p-1 flex-shrink-0" />
                  ) : (
                    <div title={u.label} className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-600 to-fuchsia-600 text-white font-bold flex items-center justify-center flex-shrink-0">{u.label.slice(0, 1)}</div>
                  )}
                  <div className="flex-1 min-w-[180px]">
                    <p className="font-semibold text-gray-900 dark:text-white">{u.username}</p>
                    {u.customer ? (
                      <p className="text-xs text-gray-500 dark:text-gray-400">{u.customer.name} · {u.customer.email}</p>
                    ) : (
                      <button type="button" onClick={() => setModal({ type: 'link', user: u })} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                        <Link2 className="w-3 h-3" /> Not linked to a billing customer
                      </button>
                    )}
                    <div className="flex flex-wrap gap-x-3 mt-0.5">
                      <Password value={u.password} />
                      {u.module === 'nuvio' && <span className="text-xs text-gray-500 dark:text-gray-400">{u.last_login ? `Last app sign-in ${fmt(u.last_login)}` : 'Never signed in to the app'}</span>}
                    </div>
                  </div>
                  <div className="min-w-[150px]">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${PILL[u.s.key]}`}>{u.s.label}</span>
                    {u.expiry_date && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 flex items-center gap-1"><Clock className="w-3 h-3" /> {u.paused ? `Kept: ${fmt(u.expiry_date)}` : `${fmt(u.expiry_date)} · ${daysText(u.s)}`}</p>}
                  </div>
                  <div className="flex items-center gap-2 ml-auto">
                    <button type="button" onClick={() => setModal({ type: 'extend', user: u })} className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>Extend</button>
                    <button type="button" title="New password" disabled={busy === `pw-${u.module}-${u.username}`} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
                      onClick={async () => {
                        if (!window.confirm(`Give ${u.username} a new ${u.label} password? Their app signs out until they use the new one.`)) return;
                        const r = await act(`pw-${u.module}-${u.username}`, () => api.post(path(u, 'password'), {}));
                        if (r) setPw({ username: u.username, label: u.label, password: r.data.password });
                      }}><KeyRound className="w-4 h-4" /></button>
                    {u.paused ? (
                      <button type="button" title="Switch on" disabled={busy === `on-${u.module}-${u.username}`} className={`${btn} border border-emerald-300 text-emerald-700 dark:text-emerald-300`}
                        onClick={() => act(`on-${u.module}-${u.username}`, () => api.post(path(u, 'enable')), `${u.username} switched back on`)}><Power className="w-4 h-4" /></button>
                    ) : (
                      <button type="button" title="Switch off" disabled={busy === `off-${u.module}-${u.username}`} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-500 hover:text-red-600`}
                        onClick={() => window.confirm(`Switch off ${u.username} (${u.label})? They lose access now. Their end date (${fmt(u.expiry_date)}) is kept and comes back when you switch them on.`)
                          && act(`off-${u.module}-${u.username}`, () => api.post(path(u, 'disable')), `${u.username} switched off`)}><Power className="w-4 h-4" /></button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Straight from Cockpit ({MODS[mod]}). Changes here update the customer's My Services too. Switching off ends access now and keeps the end date for when you switch them back on.
        </p>
      </main>

      {modal?.type === 'new' && <NewUserModal module={mod} onClose={() => setModal(null)} onDone={refresh} />}
      {modal?.type === 'extend' && <ExtendModal user={modal.user} onClose={() => setModal(null)} onDone={refresh} />}
      {modal?.type === 'link' && <LinkModal user={modal.user} onClose={() => setModal(null)} onDone={refresh} />}
      {pw && (
        <Modal title="New password set" onClose={() => setPw(null)}>
          <div className="space-y-3">
            <p className="text-sm text-gray-600 dark:text-gray-400">For {pw.label}. It's also saved in the customer's My Services.</p>
            <div className="rounded-lg bg-gray-900 text-white p-4 flex justify-between items-center font-mono text-sm">
              <span>{pw.username}</span><span className="flex items-center gap-2">{pw.password}<CopyBtn text={pw.password} /></span>
            </div>
            <button type="button" className={`${btn} bg-blue-600 text-white w-full justify-center py-2`} onClick={() => setPw(null)}><Check className="w-4 h-4" /> Done</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
