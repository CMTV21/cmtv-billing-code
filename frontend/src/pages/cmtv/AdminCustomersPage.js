// CMTV local addition 2026-10-05: Admin > Customers, phone-first (the owner: the developer's table "isn't mobile friendly").
// One search across name, email and every service login; quick filters; a card per customer -> their profile.
// The developer's page is at /admin/customers-classic (Add customer, Delete). Backend: cmtv_customers_list.py.
import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { ExtendSheet } from '../../components/cmtv/AdminTvExtend'; // 2026-10-08: tap a line to extend it

const FILTERS = [['all', 'All'], ['active', 'Active'], ['soon', 'Ending soon'], ['ended', 'Ended'], ['trials', 'On a trial'], ['panel', 'Panel-only'], ['new', 'New this week']];
const STATE = { active: ['Active', '#6ee7b7'], trial: ['Trial', '#7dd3fc'], ended: ['Ended', '#fca5a5'], none: ['No service', '#94a3b8'] };
const COLOR = { CCTV: '#22e6f2', Imperium: '#d8b35a', Nuvio: '#a78bfa', Stremio: '#a78bfa', CMTVpn: '#34d399', Audiobooks: '#f9a8d4' };
const day = (iso) => (iso ? new Date(String(iso).endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');

export default function AdminCustomersPage() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [filter, setFilter] = useState('all');
  const [limit, setLimit] = useState(40);
  const [extending, setExtending] = useState(null);   // 2026-10-08: service id being extended
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => { setLimit(40); }, [debounced, filter]);
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['cmtv-customers-list', debounced, filter, limit],
    queryFn: async () => (await api.get('/api/cmtv/admin/customers-list', { params: { q: debounced, filter, limit } })).data,
    keepPreviousData: true,
  });
  const c = data?.counts || {};
  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <div>
          <h1 style={{ margin: 0 }}>Customers</h1>
          <div style={{ opacity: 0.7, fontSize: 14 }}>{c.all ?? '…'} customers · {c.active ?? '…'} active</div>
        </div>
        <Link to="/admin/customers-classic" style={{ fontWeight: 700, fontSize: 14, color: '#22e6f2', textDecoration: 'none' }}>+ Add customer (classic page)</Link>
      </div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email or any login (TV line, Nuvio, VPN…)"
        style={{ width: '100%', boxSizing: 'border-box', font: 'inherit', fontSize: 16, padding: '12px 14px', borderRadius: 12,
          border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8', marginBottom: 10 }} />
      <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 6, marginBottom: 8, WebkitOverflowScrolling: 'touch' }}>
        {FILTERS.map(([k, l]) => (
          <button key={k} type="button" onClick={() => setFilter(k)}
            style={{ flex: 'none', font: 'inherit', fontSize: 13.5, fontWeight: 700, borderRadius: 999, padding: '7px 12px', cursor: 'pointer',
              border: '1px solid #27345a', background: filter === k ? '#22e6f2' : '#141d33', color: filter === k ? '#07101f' : '#e9edf8' }}>
            {l}{c[k] != null ? ` · ${c[k]}` : ''}
          </button>
        ))}
      </div>
      {isLoading && !data ? <p style={{ opacity: 0.7 }}>Loading…</p> : (data?.rows || []).length === 0 ? <p style={{ opacity: 0.7 }}>No customers match.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.rows.map((r) => {
            const [sl, sc] = STATE[r.state] || STATE.none;
            const dl = r.days_left;
            const soon = r.state === 'active' && dl != null && dl <= 14;
            return (
              <div key={r.id} style={{ background: '#141d33', border: '1px solid #27345a', borderLeft: `4px solid ${COLOR[r.server] || '#3a4a78'}`, borderRadius: 12 }}>
              <button type="button" onClick={() => navigate(`/admin/customer/${r.id}`)}
                style={{ textAlign: 'left', font: 'inherit', color: 'inherit', cursor: 'pointer', background: 'transparent', border: 0,
                  borderRadius: 12, padding: '11px 13px 8px', width: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <b style={{ fontSize: 16, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
                    {r.panel_only ? (r.login || r.name) : (r.name || r.email)}
                  </b>
                  <span style={{ flex: 'none', fontSize: 12, fontWeight: 800, color: sc }}>{sl}</span>
                </div>
                <div style={{ fontSize: 13.5, opacity: 0.8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.panel_only ? <span style={{ color: '#fcd34d' }}>Panel-only · no email</span> : r.email}
                </div>
                {r.credit > 0 && (r.lines || []).length > 0 && <div style={{ fontSize: 13, color: '#6ee7b7' }}>${r.credit.toFixed(0)} credit</div>}
                {r.server && !(r.lines || []).length && (   /* 2026-10-08: TV customers show their lines below instead */
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 13, marginTop: 4, opacity: 0.9 }}>
                    <span style={{ color: COLOR[r.server] || '#c7d2ee', fontWeight: 700 }}>{r.server}</span>
                    {r.login && !r.panel_only && <code style={{ opacity: 0.8 }}>{r.login}</code>}
                    {r.ends && <span style={{ color: soon ? '#fcd34d' : undefined }}>
                      {r.state === 'ended' ? `ended ${day(r.ends)}` : dl != null && dl <= 60 ? `ends in ${dl} day${dl === 1 ? '' : 's'}` : `ends ${day(r.ends)}`}</span>}
                    {r.live_services > 1 && <span style={{ opacity: 0.7 }}>+{r.live_services - 1} more</span>}
                    {r.credit > 0 && <span style={{ color: '#6ee7b7' }}>${r.credit.toFixed(0)} credit</span>}
                  </div>
                )}
              </button>
              {(r.lines || []).length > 0 && (   /* 2026-10-08: each TV line, tap to extend */
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '0 13px 11px' }}>
                  {r.lines.map((l) => {
                    const left = l.days_left;
                    const when = l.ends == null ? 'no end date' : left < 0 ? `ended ${day(l.ends)}` : left <= 60 ? `ends in ${left} day${left === 1 ? '' : 's'}` : `ends ${day(l.ends)}`;
                    return (
                      <button key={l.service_id} type="button" disabled={!l.can_extend} title={l.why_not || 'Extend this line'}
                        onClick={() => setExtending(l.service_id)}
                        style={{ font: 'inherit', fontSize: 13, textAlign: 'left', cursor: l.can_extend ? 'pointer' : 'not-allowed', borderRadius: 10, padding: '6px 10px',
                          border: `1px solid ${l.can_extend ? (COLOR[l.server] || '#27345a') : '#27345a'}`, background: '#0a1020', color: '#e9edf8', opacity: l.can_extend ? 1 : 0.6 }}>
                        <b style={{ color: COLOR[l.server] || '#c7d2ee' }}>{l.server}</b> <code>{l.login}</code>{l.trial ? ' · trial' : ''}
                        <span style={{ opacity: 0.8, color: left != null && left <= 14 ? '#fcd34d' : undefined }}> · {when}</span>
                        {l.can_extend ? <b style={{ color: '#22e6f2' }}> · Extend</b> : <span style={{ opacity: 0.8 }}> · {l.why_not}</span>}
                      </button>
                    );
                  })}
                </div>
              )}
              </div>
            );
          })}
          {data.total > data.rows.length && (
            <button type="button" onClick={() => setLimit(limit + 60)}
              style={{ font: 'inherit', fontWeight: 700, padding: 12, borderRadius: 12, border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' }}>
              Show more ({data.total - data.rows.length} left)
            </button>
          )}
        </div>
      )}
      {extending && <ExtendSheet serviceId={extending} onClose={() => setExtending(null)} onDone={() => refetch()} />}
    </div>
  );
}
