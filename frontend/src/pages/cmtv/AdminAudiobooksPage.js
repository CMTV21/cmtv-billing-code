// CMTV local addition 2026-09-25: Admin > Audiobooks (backend: cmtv_audiobooks.py -> abadmin on the Asus server).
// Every audiobook account in one place: who it belongs to, when it runs out, and one-tap extend / disable / reset.
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  AlertTriangle, ArrowLeft, BookOpen, Check, Clock, Copy, History, KeyRound, Link2, Plus, Power, RefreshCw, Search, Trash2, X,
} from 'lucide-react';
import api from '../../api/api';

const SOON_DAYS = 14;
const DAY = 86400000;
const errText = (e, fb) => e?.response?.data?.detail || fb;
const fmt = (d) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');

function statusOf(u, today) {
  const t = new Date(`${today}T00:00:00`).getTime();
  const days = u.expiry_date ? Math.round((new Date(`${u.expiry_date}T00:00:00`).getTime() - t) / DAY) : null;
  if (u.status === 'disabled') return { key: 'disabled', label: 'Disabled', days };
  if (u.status === 'expired') return { key: 'expired', label: 'Expired', days };
  if (days !== null && days < 0) return { key: 'overdue', label: 'Past date, still on', days };
  if (days !== null && days <= SOON_DAYS) return { key: 'soon', label: 'Expiring soon', days };
  if (days === null) return { key: 'nodate', label: 'No end date', days };
  return { key: 'active', label: 'Active', days };
}
const PILL = {
  active: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  soon: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  overdue: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  expired: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
  disabled: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
  nodate: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200',
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
    queryKey: ['ab-customers', q],
    queryFn: async () => (await api.get('/api/cmtv/audiobooks/customers', { params: { q } })).data,
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

function TermChips({ value, onChange, options = [1, 3, 12] }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {options.map((m) => (
        <button key={m} type="button" onClick={() => onChange(m)}
          className={`${btn} border ${value === m ? 'bg-blue-600 border-blue-600 text-white' : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'}`}>
          {m === 12 ? '1 year' : `${m} month${m === 1 ? '' : 's'}`}
        </button>
      ))}
    </div>
  );
}

function NewUserModal({ onClose, onDone }) {
  const [customer, setCustomer] = useState(null);
  const [months, setMonths] = useState(12);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/api/cmtv/audiobooks/users', {
        months, username: username.trim(), customer_id: customer?.id, email_customer: !!customer && email,
      });
      setResult(data); onDone();
      if (data.warning) toast.warning(`Created, but ${data.warning}`);
    } catch (e) { toast.error(errText(e, "Couldn't create the account")); } finally { setBusy(false); }
  };
  return (
    <Modal title="New audiobook account" onClose={onClose}>
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
            <TermChips value={months} onChange={setMonths} />
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
      const { data } = await api.post(`/api/cmtv/audiobooks/users/${encodeURIComponent(user.username)}/extend`, date ? { expiry_date: date } : { months });
      toast.success(`${user.username} now runs until ${fmt(data.expiry_date)}`);
      if (data.warning) toast.warning(data.warning);
      onDone(); onClose();
    } catch (e) { toast.error(errText(e, "Couldn't extend")); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Extend ${user.username}`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {user.expiry_date ? <>Currently until <b>{fmt(user.expiry_date)}</b>. Time is added from that date, or from today if it has passed.</> : 'No end date yet. Time is added from today.'}
        </p>
        <TermChips value={date ? null : months} onChange={(m) => { setMonths(m); setDate(''); }} />
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Or pick an exact end date</label>
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        {user.status !== 'active' && <p className="text-sm text-emerald-700 dark:text-emerald-400">This also switches the account back on.</p>}
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
        <p className="text-xs text-gray-500">The account then shows in their My Services, and extending it here updates billing too.</p>
        <button type="button" disabled={!customer || busy} className={`${btn} bg-blue-600 text-white w-full justify-center py-2`}
          onClick={async () => {
            setBusy(true);
            try { await api.post('/api/cmtv/audiobooks/link', { username: user.username, customer_id: customer.id }); toast.success('Linked'); onDone(); onClose(); }
            catch (e) { toast.error(errText(e, "Couldn't link")); } finally { setBusy(false); }
          }}>Link</button>
      </div>
    </Modal>
  );
}

function ActivityModal({ onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ['ab-activity'],
    queryFn: async () => (await api.get('/api/cmtv/audiobooks/activity')).data,
  });
  return (
    <Modal title="Recent activity" onClose={onClose}>
      {isLoading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <ul className="space-y-2 text-sm">
          {(data?.entries || []).map((e, i) => (
            <li key={i} className={`rounded-lg px-3 py-2 ${/error/.test(e.action) ? 'bg-red-50 dark:bg-red-900/20' : 'bg-gray-50 dark:bg-gray-800'}`}>
              <div className="flex justify-between gap-2">
                <span className="font-semibold text-gray-900 dark:text-white">{e.action.replace(/_/g, ' ')}{e.username ? ` · ${e.username}` : ''}</span>
                <span className="text-xs text-gray-500 whitespace-nowrap">{e.created_at}</span>
              </div>
              {e.detail && <p className="text-xs text-gray-600 dark:text-gray-400 break-all mt-0.5">{e.detail}</p>}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

// ---- Stuck requests (2026-09-26): requests-app requests where no MAM result scored 50/100 ----
const ago = (d) => {
  const days = Math.floor((Date.now() - new Date(d).getTime()) / DAY);
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;
};

function MatchBadge({ r }) {
  if (r.author_ok && r.length_ok) return <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">Looks right</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {!r.author_ok && <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200">Different author</span>}
      {!r.length_ok && <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">Length doesn't fit</span>}
    </span>
  );
}

function StuckRow({ req, onGrabbed }) {
  const [open, setOpen] = useState(false);
  const [words, setWords] = useState(req.customSearchTerms || req.title || '');
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState('');
  const search = async (title) => {
    setBusy('search'); setResults(null);
    try {
      const { data } = await api.post(`/api/cmtv/audiobooks/stuck/${req.requestId}/search`, { title: title || '', author: req.author });
      setResults(data.results || []);
    } catch (e) { toast.error(errText(e, 'Search failed')); setResults([]); } finally { setBusy(''); }
  };
  const grab = async (r) => {
    const warn = !r.author_ok || !r.length_ok;
    if (warn && !window.confirm(`This result has a warning (${[!r.author_ok && 'different author', !r.length_ok && "length doesn't fit"].filter(Boolean).join(', ')}). Grab it anyway?`)) return;
    setBusy(`grab-${r.index}`);
    try { await api.post(`/api/cmtv/audiobooks/stuck/${req.requestId}/grab`, { index: r.index }); toast.success('Grabbed. It downloads and lands in the library by itself.'); onGrabbed(req.requestId); }
    catch (e) { toast.error(errText(e, "Couldn't grab it")); } finally { setBusy(''); }
  };
  const saveWords = async () => {
    setBusy('terms');
    try { await api.post(`/api/cmtv/audiobooks/stuck/${req.requestId}/terms`, { terms: words }); toast.success('Saved. Automatic searches now use these words.'); }
    catch (e) { toast.error(errText(e, "Couldn't save")); } finally { setBusy(''); }
  };
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[200px]">
          <p className="font-semibold text-gray-900 dark:text-white">{req.title}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">{req.author} · asked by {req.user || 'someone'} · {ago(req.createdAt)}{req.customSearchTerms ? ` · searching as "${req.customSearchTerms}"` : ''}</p>
        </div>
        <button type="button" onClick={() => { setOpen(!open); if (!open && results === null) search(''); }}
          className={`${btn} ${open ? 'border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200' : 'bg-blue-600 text-white hover:bg-blue-700'}`}>
          {open ? 'Close' : 'Find matches'}
        </button>
      </div>
      {open && (
        <div className="mt-3 rounded-lg bg-gray-50 dark:bg-gray-800 p-3 space-y-3">
          <div className="flex flex-wrap gap-2">
            <input className={`${input} flex-1 min-w-[200px]`} value={words} onChange={(e) => setWords(e.target.value)} placeholder="Search words" />
            <button type="button" disabled={!!busy} onClick={() => search(words)} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}><Search className="w-4 h-4" /> Search these words</button>
            <button type="button" disabled={!!busy} onClick={saveWords} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`} title="Use these words for this request's automatic searches too">Save for auto-search</button>
          </div>
          {busy === 'search' && <p className="text-sm text-gray-500">Searching MAM… (can take up to a minute)</p>}
          {results && results.length === 0 && busy !== 'search' && (
            <p className="text-sm text-gray-600 dark:text-gray-300">Nothing on MAM for this yet. New releases often take a while to appear; the app keeps checking by itself.</p>
          )}
          {results && results.length > 0 && (
            <ul className="space-y-2">
              {results.map((r) => (
                <li key={r.index} className="bg-white dark:bg-gray-900 rounded-lg px-3 py-2 flex flex-wrap items-center gap-2">
                  <div className="flex-1 min-w-[220px]">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">{r.title}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {r.format || '?'} · {r.size_mb >= 1024 ? `${(r.size_mb / 1024).toFixed(1)} GB` : `${r.size_mb} MB`} · {r.seeders ?? '?'} seeders · score {r.score}/100
                      {r.link && <> · <a href={r.link} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">view on MAM</a></>}
                    </p>
                  </div>
                  <MatchBadge r={r} />
                  <button type="button" disabled={!!busy} onClick={() => grab(r)} className={`${btn} ${r.author_ok && r.length_ok ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'}`}>
                    {busy === `grab-${r.index}` ? 'Grabbing…' : 'Grab'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function StuckRequests() {
  const [hidden, setHidden] = useState([]);
  const [q, setQ] = useState('');
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['ab-stuck'],
    queryFn: async () => (await api.get('/api/cmtv/audiobooks/stuck')).data,
    staleTime: 60000,
  });
  const rows = (data?.requests || []).filter((r) => !hidden.includes(r.requestId))
    .filter((r) => !q.trim() || `${r.title} ${r.author} ${r.user}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 p-4 text-sm text-blue-900 dark:text-blue-200">
        These are requests where no MAM result scored 50 out of 100, so the requests app won't grab one by itself. Open one to see
        what MAM has. <b>Looks right</b> means the author and the length both match; <b>Different author</b> or <b>Length doesn't fit</b> usually means a
        different book with the same title. If nothing fits, it's probably not on MAM yet, and the app keeps checking by itself.
      </div>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input className={`${input} w-full pl-9 py-2.5`} placeholder="Search stuck requests" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button type="button" onClick={() => refetch()} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}><RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /></button>
      </div>
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm overflow-hidden">
        {error ? <p className="p-6 text-sm text-red-600">{errText(error, "Couldn't load the stuck requests")}</p>
          : isLoading ? <p className="p-6 text-sm text-gray-500">Loading stuck requests…</p>
          : rows.length === 0 ? <p className="p-6 text-sm text-gray-500 dark:text-gray-400">Nothing stuck.</p>
          : <ul className="divide-y divide-gray-100 dark:divide-gray-800">{rows.map((r) => <StuckRow key={r.requestId} req={r} onGrabbed={(id) => setHidden((h) => [...h, id])} />)}</ul>}
      </div>
    </div>
  );
}

export default function AdminAudiobooksPage() {
  const [view, setView] = useState(() => (new URLSearchParams(window.location.search).get('tab') === 'stuck' ? 'stuck' : 'accounts'));   // CMTV 2026-09-26: admin home links to ?tab=stuck
  const qc = useQueryClient();
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [modal, setModal] = useState(null);   // {type, user}
  const [pw, setPw] = useState(null);
  const [busy, setBusy] = useState('');
  const [importTerm, setImportTerm] = useState({});
  const [linkPick, setLinkPick] = useState({});
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['ab-users'],
    queryFn: async () => (await api.get('/api/cmtv/audiobooks/users')).data,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['ab-users'] });
  const today = data?.today || new Date().toISOString().slice(0, 10);

  const users = useMemo(() => (data?.users || []).map((u) => ({ ...u, s: statusOf(u, today) }))
    .sort((a, b) => (a.s.days ?? 99999) - (b.s.days ?? 99999)), [data, today]);
  const counts = useMemo(() => {
    const c = { all: users.length, active: 0, soon: 0, expired: 0, disabled: 0 };
    users.forEach((u) => {
      if (u.s.key === 'active' || u.s.key === 'nodate') c.active += 1;
      if (u.s.key === 'soon') c.soon += 1;
      if (u.s.key === 'expired' || u.s.key === 'overdue') c.expired += 1;
      if (u.s.key === 'disabled') c.disabled += 1;
    });
    return c;
  }, [users]);
  const shown = users.filter((u) => {
    const f = filter === 'all' || (filter === 'active' && ['active', 'nodate'].includes(u.s.key)) || (filter === 'soon' && u.s.key === 'soon')
      || (filter === 'expired' && ['expired', 'overdue'].includes(u.s.key)) || (filter === 'disabled' && u.s.key === 'disabled');
    const t = q.trim().toLowerCase();
    return f && (!t || [u.username, u.display_name, u.customer?.name, u.customer?.email].some((x) => String(x || '').toLowerCase().includes(t)));
  });
  const attention = (data?.unmanaged || []).length + (data?.unlinked_services || []).length;

  const act = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (ok) toast.success(ok); if (r?.data?.warning) toast.warning(r.data.warning); refresh(); return r; }
    catch (e) { toast.error(errText(e, 'Something went wrong')); return null; } finally { setBusy(''); }
  };

  const tiles = [
    ['all', 'All accounts', counts.all, 'text-gray-900 dark:text-white'],
    ['active', 'Active', counts.active, 'text-emerald-600'],
    ['soon', `Ending in ${SOON_DAYS} days`, counts.soon, 'text-amber-600'],
    ['expired', 'Expired', counts.expired, 'text-red-600'],
    ['disabled', 'Disabled', counts.disabled, 'text-gray-500'],
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-4 flex flex-wrap items-center gap-3">
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600"><ArrowLeft className="w-5 h-5" /> Admin</Link>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2"><BookOpen className="w-5 h-5" /> Audiobooks</h1>
          <div className="ml-auto flex gap-2">
            <button type="button" onClick={() => setModal({ type: 'activity' })} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}><History className="w-4 h-4" /> Activity</button>
            <button type="button" onClick={refresh} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}><RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /></button>
            <button type="button" onClick={() => setModal({ type: 'new' })} className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}><Plus className="w-4 h-4" /> New account</button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-5">
        <div className="inline-flex rounded-lg bg-gray-200 dark:bg-gray-800 p-1">
          {[['accounts', 'Accounts'], ['stuck', 'Stuck requests']].map(([k, label]) => (
            <button key={k} type="button" onClick={() => setView(k)}
              className={`px-4 py-1.5 rounded-md text-sm font-semibold ${view === k ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm' : 'text-gray-600 dark:text-gray-400'}`}>
              {label}
            </button>
          ))}
        </div>
        {view === 'stuck' ? <StuckRequests /> : (<>
        {error && <div className="rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 p-4 text-sm">{errText(error, "Couldn't load the audiobook accounts")}</div>}
        {data?.error && <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200 p-3 text-sm">{data.error}</div>}

        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {tiles.map(([key, label, n, color]) => (
            <button key={key} type="button" onClick={() => setFilter(key)}
              className={`text-left rounded-xl p-4 bg-white dark:bg-gray-900 shadow-sm border-2 transition ${filter === key ? 'border-blue-500' : 'border-transparent hover:border-gray-200 dark:hover:border-gray-700'}`}>
              <p className={`text-2xl font-bold ${color}`}>{n}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</p>
            </button>
          ))}
        </div>

        {attention > 0 && (
          <section className="rounded-xl bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800 p-4 space-y-4">
            <h2 className="font-semibold text-amber-900 dark:text-amber-200 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> Needs attention ({attention})</h2>
            {(data?.unmanaged || []).length > 0 && (
              <div>
                <p className="text-sm text-amber-900 dark:text-amber-200 mb-2">In Audiobookshelf but not managed, so nothing expires them and billing can't extend them. Import to start managing:</p>
                <ul className="space-y-2">
                  {data.unmanaged.map((u) => (
                    <li key={u.username} className="flex flex-wrap items-center gap-2 bg-white dark:bg-gray-900 rounded-lg px-3 py-2">
                      <span className="font-semibold text-gray-900 dark:text-white flex-1 min-w-[140px]">{u.username}
                        {!u.has_rmab && <span className="ml-2 text-xs font-normal text-gray-500">(no requests login)</span>}</span>
                      <select className={input} value={importTerm[u.username] ?? '12'} onChange={(e) => setImportTerm({ ...importTerm, [u.username]: e.target.value })}>
                        <option value="1">Ends in 1 month</option><option value="3">Ends in 3 months</option><option value="12">Ends in 1 year</option><option value="">No end date yet</option>
                      </select>
                      <button type="button" disabled={busy === `imp-${u.username}`} className={`${btn} bg-blue-600 text-white`}
                        onClick={() => act(`imp-${u.username}`, () => api.post('/api/cmtv/audiobooks/import', { username: u.username, months: Number(importTerm[u.username] ?? 12) || undefined }), `${u.username} imported`)}>
                        Import
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(data?.unlinked_services || []).length > 0 && (
              <div>
                <p className="text-sm text-amber-900 dark:text-amber-200 mb-2">Audiobook orders in billing that aren't tied to an account yet (set up by hand). Pick their account:</p>
                <ul className="space-y-2">
                  {data.unlinked_services.map((s) => (
                    <li key={s.service_id} className="flex flex-wrap items-center gap-2 bg-white dark:bg-gray-900 rounded-lg px-3 py-2">
                      <span className="flex-1 min-w-[180px] text-sm">
                        <span className="font-semibold text-gray-900 dark:text-white">{s.customer?.name || 'Unknown customer'}</span>
                        <span className="text-gray-500"> · {s.product_name}</span>
                        <span className="block text-xs text-gray-500">{s.customer?.email}</span>
                      </span>
                      <select className={input} value={linkPick[s.service_id] || ''} onChange={(e) => setLinkPick({ ...linkPick, [s.service_id]: e.target.value })}>
                        <option value="">Choose account…</option>
                        {users.map((u) => <option key={u.username} value={u.username}>{u.username}</option>)}
                      </select>
                      <button type="button" disabled={!linkPick[s.service_id] || busy === `lnk-${s.service_id}`} className={`${btn} bg-blue-600 text-white`}
                        onClick={() => act(`lnk-${s.service_id}`, () => api.post('/api/cmtv/audiobooks/link', { username: linkPick[s.service_id], service_id: s.service_id }), 'Linked')}>
                        <Link2 className="w-4 h-4" /> Link
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-amber-800 dark:text-amber-300 mt-2">Their account isn't in the list? Import it above first.</p>
              </div>
            )}
          </section>
        )}

        <div className="relative">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input className={`${input} w-full pl-9 py-2.5`} placeholder="Search by username, customer name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm overflow-hidden">
          {isLoading ? <p className="p-6 text-sm text-gray-500">Loading accounts…</p> : shown.length === 0 ? (
            <p className="p-6 text-sm text-gray-500 dark:text-gray-400">No accounts match.</p>
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-gray-800">
              {shown.map((u) => (
                <li key={u.username} className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-cyan-500 to-violet-600 text-white font-bold flex items-center justify-center flex-shrink-0">
                    {u.username.slice(0, 1).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-[160px]">
                    <p className="font-semibold text-gray-900 dark:text-white">{u.username}</p>
                    {u.abs_missing && <p className="text-xs text-red-600">Deleted in Audiobookshelf (only abadmin still lists it)</p>}
                    {u.customer ? (
                      <p className="text-xs text-gray-500 dark:text-gray-400">{u.customer.name} · {u.customer.email}</p>
                    ) : (
                      <button type="button" onClick={() => setModal({ type: 'link', user: u })} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                        <Link2 className="w-3 h-3" /> Not linked to a billing customer
                      </button>
                    )}
                  </div>
                  <div className="min-w-[150px]">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${PILL[u.s.key]}`}>{u.s.label}</span>
                    {u.expiry_date && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 flex items-center gap-1"><Clock className="w-3 h-3" /> {fmt(u.expiry_date)} · {daysText(u.s)}</p>}
                  </div>
                  <div className="flex items-center gap-2 ml-auto">
                    <button type="button" onClick={() => setModal({ type: 'extend', user: u })} className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>Extend</button>
                    <button type="button" title="New password" disabled={busy === `pw-${u.username}`} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
                      onClick={async () => {
                        const r = await act(`pw-${u.username}`, () => api.post(`/api/cmtv/audiobooks/users/${encodeURIComponent(u.username)}/password`, {}));
                        if (r) setPw({ username: u.username, password: r.data.password });
                      }}><KeyRound className="w-4 h-4" /></button>
                    {u.status === 'disabled' || u.status === 'expired' ? (
                      <button type="button" title="Switch on" disabled={busy === `on-${u.username}`} className={`${btn} border border-emerald-300 text-emerald-700 dark:text-emerald-300`}
                        onClick={() => act(`on-${u.username}`, () => api.post(`/api/cmtv/audiobooks/users/${encodeURIComponent(u.username)}/enable`), `${u.username} switched on`)}><Power className="w-4 h-4" /></button>
                    ) : (
                      <button type="button" title="Switch off" disabled={busy === `off-${u.username}`} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-500 hover:text-red-600`}
                        onClick={() => window.confirm(`Switch off ${u.username}? They lose access to audiobooks and requests until switched on or extended.`)
                          && act(`off-${u.username}`, () => api.post(`/api/cmtv/audiobooks/users/${encodeURIComponent(u.username)}/disable`), `${u.username} switched off`)}><Power className="w-4 h-4" /></button>
                    )}
                    {/* CMTV 2026-09-26: delete for good (type the username to confirm) */}
                    <button type="button" title="Delete" disabled={busy === `del-${u.username}`} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-500 hover:text-red-600`}
                      onClick={() => {
                        const typed = window.prompt(`Delete ${u.username} for good?\n\nThis removes them from Audiobookshelf (with their listening progress and bookmarks) and the requests app.`
                          + `${u.customer ? ` ${u.customer.name}'s service in billing is marked ended.` : ''}\n\nType the username to confirm:`);
                        if (typed === null) return;
                        if (typed.trim().toLowerCase() !== u.username.toLowerCase()) { toast.error("The username didn't match, so nothing was deleted"); return; }
                        act(`del-${u.username}`, () => api.post(`/api/cmtv/audiobooks/users/${encodeURIComponent(u.username)}/delete`), `${u.username} deleted`);
                      }}><Trash2 className="w-4 h-4" /></button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Accounts are switched off automatically the day after their end date (00:05, Asus server). Changes here update the customer's My Services too.
        </p>
        </>)}
      </main>

      {modal?.type === 'new' && <NewUserModal onClose={() => setModal(null)} onDone={refresh} />}
      {modal?.type === 'extend' && <ExtendModal user={modal.user} onClose={() => setModal(null)} onDone={refresh} />}
      {modal?.type === 'link' && <LinkModal user={modal.user} onClose={() => setModal(null)} onDone={refresh} />}
      {modal?.type === 'activity' && <ActivityModal onClose={() => setModal(null)} />}
      {pw && (
        <Modal title="New password set" onClose={() => setPw(null)}>
          <div className="space-y-3">
            <p className="text-sm text-gray-600 dark:text-gray-400">For audiobooks and requests. It's also saved in the customer's My Services.</p>
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
