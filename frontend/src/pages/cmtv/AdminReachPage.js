// CMTV local addition 2026-10-05: Admin > Reach customers (backend cmtv_reach.py). Panel-only customers (no email, they
// renew with the owner directly): copy each one's personal message + link, send it your usual way, mark it sent; the status
// moves by itself to Opened and Done when they finish their account.
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/reseller-credits.css';

const btn = { font: 'inherit', fontWeight: 700, fontSize: 13.5, borderRadius: 9, padding: '6px 11px', border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' };
const PILL = { new: ['Not sent', '#94a3b8'], sent: ['Sent', '#7dd3fc'], opened: ['Opened', '#fcd34d'], done: ['Done', '#6ee7b7'] };
const when = (iso) => (iso ? new Date(String(iso).endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '');
const copy = (text, label) => { try { navigator.clipboard.writeText(text); toast.success(`${label} copied`); } catch { toast(text); } };

function Row({ r, via, refetch }) {
  const [pick, setPick] = useState(false);
  const [label, color] = PILL[r.status];
  const mark = async (v) => {
    try { await api.post(`/api/cmtv/reach/admin/${r.user_id}/sent`, v ? { via: v } : { undo: true }); setPick(false); refetch(); }
    catch { toast.error('Could not save'); }
  };
  const soon = r.days_left != null && r.days_left <= 30;
  return (
    <div className="rc-box" style={{ margin: 0, padding: '12px 14px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', alignItems: 'center' }}>
        <b style={{ fontFamily: 'Consolas, Menlo, monospace' }}>{r.line}</b>
        {r.name && <span>{r.name}</span>}
        <span style={{ opacity: 0.75 }}>{r.server}{r.devices ? ` · ${r.devices} device${r.devices === 1 ? '' : 's'}` : ''}{r.lines > 1 ? ` · ${r.lines} lines` : ''}</span>
        <span style={{ color: soon ? '#fca5a5' : undefined, fontWeight: soon ? 700 : 400 }}>
          {r.days_left == null ? '' : r.days_left < 0 ? 'ended' : `ends in ${r.days_left} day${r.days_left === 1 ? '' : 's'}`}
        </span>
        <span style={{ marginLeft: 'auto', fontWeight: 800, fontSize: 12.5, color }}>{label}
          {r.sent_at ? ` ${when(r.sent_at)}${r.sent_via ? ` by ${r.sent_via}` : ''}` : ''}{r.opened_at ? ` · opened ${when(r.opened_at)}` : ''}</span>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <button type="button" style={{ ...btn, border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }} onClick={() => copy(r.message, 'Message')}>Copy message</button>
        <button type="button" style={btn} onClick={() => copy(r.link, 'Link')}>Copy link</button>
        {r.status === 'new' ? (
          pick ? via.map((v) => <button key={v} type="button" style={{ ...btn, fontWeight: 600 }} onClick={() => mark(v)}>{v}</button>)
            : <button type="button" style={btn} onClick={() => setPick(true)}>Mark sent…</button>
        ) : <button type="button" style={{ ...btn, opacity: 0.7 }} onClick={() => mark(null)}>Undo sent</button>}
        <Link to={`/admin/customer/${r.user_id}`} style={{ ...btn, textDecoration: 'none' }}>Customer</Link>
      </div>
    </div>
  );
}

export default function AdminReachPage() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-reach-admin'], queryFn: async () => (await api.get('/api/cmtv/reach/admin')).data });
  const [tab, setTab] = useState('soon');
  const [q, setQ] = useState('');
  const c = data?.counts || {};
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const all = data?.rows || [];
    const f = tab === 'soon' ? all.filter((r) => r.days_left != null && r.days_left <= 30 && r.status !== 'opened')
      : tab === 'new' ? all.filter((r) => r.status === 'new') : tab === 'sent' ? all.filter((r) => r.status !== 'new') : all;
    return f.filter((r) => !s || [r.line, r.name, r.server].some((v) => String(v || '').toLowerCase().includes(s)));
  }, [data, tab, q]);
  const tabs = [['soon', `Ending in 30 days (${c.soon ?? 0})`], ['new', `Not sent (${c.new ?? 0})`], ['sent', `Sent / opened (${(c.sent || 0) + (c.opened || 0)})`],
    ['done', `Done (${c.done ?? 0})`], ['all', `All (${c.active ?? 0})`]];
  return (
    <div style={{ maxWidth: 1000 }}>
      <h1 style={{ margin: '0 0 4px' }}>Reach customers</h1>
      <p style={{ margin: '0 0 12px', opacity: 0.85 }}>
        These customers only exist on the panel: no email, so billing can't remind or contact them. Send each one their personal
        message the way you usually talk to them (text, Telegram, Facebook). The link signs them straight in to add their email
        {data?.reward ? <> and get <b>${data.reward.toFixed(0)} credit</b></> : ''}. Best moment: when they're about to renew.
      </p>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        {tabs.map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)} style={{ ...btn, background: tab === k ? '#22e6f2' : '#1c2747', color: tab === k ? '#07101f' : '#e9edf8' }}>{l}</button>
        ))}
      </div>
      {tab !== 'done' && <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search line or name…"
        style={{ width: '100%', boxSizing: 'border-box', font: 'inherit', padding: '8px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8', marginBottom: 10 }} />}
      {!data ? <p style={{ opacity: 0.7 }}>Loading…</p> : tab === 'done' ? (
        (data.done || []).length === 0 ? <p style={{ opacity: 0.7 }}>Nobody yet: the first ones will show up here.</p> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.done.map((r) => (
              <div key={r.user_id} className="rc-box" style={{ margin: 0, padding: '10px 14px' }}>
                <b>{r.name || 'Customer'}</b> · {r.email} <span style={{ color: '#6ee7b7', fontWeight: 800, marginLeft: 8 }}>Done {when(r.done_at)}</span>
                {r.sent_via ? <small style={{ opacity: 0.7 }}> · reached by {r.sent_via}</small> : null}
              </div>
            ))}
          </div>)
      ) : rows.length === 0 ? <p style={{ opacity: 0.7 }}>Nothing here.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map((r) => <Row key={r.user_id} r={r} via={data.via} refetch={refetch} />)}
        </div>
      )}
    </div>
  );
}
