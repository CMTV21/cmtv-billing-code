// CMTV local addition 2026-09-28: Admin > Reviews. Reviews customers left through their review link (cmtv_reviews.py):
// approve (only if they agreed to publish) -> shown on cmtv.info; reject / move back to pending. Switch for the
// automatic review requests (off until the admin turns it on) with how many customers are waiting for one.
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/cmtv-reviews.css';

const STATUS = { pending: 'Waiting', approved: 'On cmtv.info', rejected: 'Not shown' };

export default function AdminReviewsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['cmtv-reviews-admin'], queryFn: async () => (await api.get('/api/cmtv/reviews/admin')).data });
  const reviews = data?.reviews || [];
  const approved = reviews.filter((r) => r.status === 'approved');
  const avg = approved.length ? (approved.reduce((n, r) => n + r.rating, 0) / approved.length).toFixed(1) : '–';

  const decide = async (r, status) => {
    try { await api.post(`/api/cmtv/reviews/admin/${r.id}`, { status }); qc.invalidateQueries({ queryKey: ['cmtv-reviews-admin'] }); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not save that.'); }
  };
  const toggleInvites = async () => {
    const on = !data?.invites_enabled;
    if (on && !window.confirm(`Start sending review requests? Up to 10 customers a day get one email (and a Telegram message if connected). ${data?.waiting || 0} customers qualify right now.`)) return;
    try { await api.post('/api/cmtv/reviews/admin-settings', { invites_enabled: on }); qc.invalidateQueries({ queryKey: ['cmtv-reviews-admin'] }); toast.success(on ? 'Review requests are on.' : 'Review requests are off.'); }
    catch { toast.error('Could not save that.'); }
  };

  return (
    <div className="rv-admin">
      <div className="rv-admin-head">
        <div>
          <h1>Reviews</h1>
          <p>Reviews your customers left through their review link. Only approved reviews from customers who agreed appear on cmtv.info.</p>
        </div>
      </div>
      <div className="rv-stats">
        <div><b>{approved.length}</b><span>on cmtv.info</span></div>
        <div><b>{avg}</b><span>average ★ (shown)</span></div>
        <div><b>{reviews.filter((r) => r.status === 'pending').length}</b><span>waiting for you</span></div>
        <div><b>{data?.invites_sent ?? '–'}</b><span>requests sent</span></div>
      </div>
      <div className="rv-invites">
        <div>
          <b>Automatic review requests: {data?.invites_enabled ? 'on' : 'off'}</b>
          <span>Customers who have paid for 30+ days and have an active plan get one friendly email (plus Telegram if connected), 10 a day at most, between 11 am and 7 pm. {data?.waiting ?? 0} qualify right now.</span>
        </div>
        <button type="button" className={`rv-btn${data?.invites_enabled ? '' : ' glow'}`} onClick={toggleInvites} disabled={!data}>
          {data?.invites_enabled ? 'Turn off' : 'Turn on'}
        </button>
      </div>
      {isLoading ? <p>Loading…</p> : reviews.length === 0 ? (
        <p className="rv-empty">No reviews yet. Once review requests are on, they'll appear here for you to approve.</p>
      ) : (
        <div className="rv-list">
          {reviews.map((r) => (
            <div key={r.id} className={`rv-item st-${r.status}`}>
              <div className="rv-item-head">
                <span className="rv-stars-sm">{'★'.repeat(r.rating)}<i>{'★'.repeat(5 - r.rating)}</i></span>
                <span className={`rv-status st-${r.status}`}>{STATUS[r.status]}</span>
                {!r.consent && <span className="rv-status private">Private feedback</span>}
                <span className="rv-date">{r.date}</span>
              </div>
              <p className="rv-text">“{r.text}”</p>
              <div className="rv-meta">
                Shown as <b>{r.name}</b>{r.province ? `, ${r.province}` : ''} · from <Link to={`/admin/customer/${r.user_id}`}>{r.customer || r.email}</Link>
              </div>
              <div className="rv-actions">
                {r.status !== 'approved' && <button type="button" className="rv-btn glow" disabled={!r.consent} title={r.consent ? '' : 'The customer asked to keep it private'} onClick={() => decide(r, 'approved')}>Approve</button>}
                {r.status === 'approved' && <button type="button" className="rv-btn" onClick={() => decide(r, 'pending')}>Take off cmtv.info</button>}
                {r.status !== 'rejected' && <button type="button" className="rv-btn" onClick={() => decide(r, 'rejected')}>Don't show</button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
