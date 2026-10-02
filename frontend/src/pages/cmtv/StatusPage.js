// CMTV local addition 2026-10-02: public /status page. Every customer-facing service (from Uptime Kuma via cmtv_status.py,
// GET /api/cmtv/status/page): up or having a problem right now, uptime over 30 days, incidents of the last 14 days.
// Only outages of 3+ minutes count (same rule as the banner); Kuma's own connection drops are left out.
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import '../../components/cmtv/cmtv-kb.css';

const fmt = (iso) => new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const dur = (m) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ''}`.trim());

export default function StatusPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['cmtv-status-page'], queryFn: async () => (await api.get('/api/cmtv/status/page')).data, refetchInterval: 60000,
  });
  const services = data?.services || [];
  const down = services.filter((s) => s.status === 'down');
  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12 }}>
        <h1>Service status</h1>
        {isLoading ? <p className="kb-lede">Loading…</p> : isError ? <p className="kb-lede">Status can't be loaded right now. Please try again in a minute.</p> : (
          <>
            <p className="kb-lede" style={{ fontWeight: 600, color: down.length ? '#f87171' : '#34d399' }}>
              {down.length ? `⚠️ We're working on a problem with ${down.map((s) => s.name).join(' and ')}.` : '✅ All services are running normally.'}
            </p>
            <div style={{ display: 'grid', gap: 10, margin: '16px 0' }}>
              {services.map((s) => (
                <div key={s.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 16px',
                  borderRadius: 12, background: 'rgba(255,255,255,0.04)', border: `1px solid ${s.status === 'down' ? '#f87171' : 'rgba(255,255,255,0.08)'}` }}>
                  <span style={{ fontWeight: 700 }}>
                    <span aria-hidden="true" style={{ color: s.status === 'down' ? '#f87171' : '#34d399', marginRight: 8 }}>●</span>{s.name}
                  </span>
                  <span style={{ fontSize: 14, opacity: 0.85, textAlign: 'right' }}>
                    {s.status === 'down' ? 'Problem detected' : 'Running normally'} · {s.uptime_30d}% up (30 days)
                  </span>
                </div>
              ))}
            </div>
            <h2>Recent incidents (14 days)</h2>
            {data?.incidents?.length ? (
              <ul>{data.incidents.map((i) => (
                <li key={`${i.service}-${i.start}`}><b>{i.service}</b>: {fmt(i.start)}, {i.end ? `back after ${dur(i.minutes)}` : `ongoing (${dur(i.minutes)} so far)`}</li>
              ))}</ul>
            ) : <p>No incidents in the last 14 days.</p>}
            <p style={{ fontSize: 13, opacity: 0.7 }}>Checked every minute. Short blips under 3 minutes aren't listed. Updated {data?.updated_at ? fmt(data.updated_at) : ''}.</p>
          </>
        )}
      </article>
      <div className="kb-help">
        <div><b>Everything up, but it's not working for you?</b><span>Most problems are fixed in a minute with our quick fixes, or message us.</span></div>
        <Link className="kb-btn" to="/knowledge-base/cmtv-buffering">Buffering? Quick fixes</Link>
        <a className="kb-btn" href="https://t.me/Cmtv_support_bot" target="_blank" rel="noopener noreferrer">Message support</a>
      </div>
    </div>
  );
}
