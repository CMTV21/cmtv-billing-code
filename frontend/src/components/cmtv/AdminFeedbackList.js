// CMTV local addition 2026-10-04: customer suggestions / feedback from the dashboard (cmtv_feedback.py), shown on
// Admin > Reviews & feedback. Mark read / done; email link when the customer said it's OK to contact them.
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '');

export default function AdminFeedbackList() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-feedback-admin'], queryFn: async () => (await api.get('/api/cmtv/feedback/admin')).data });
  const list = data?.feedback || [];
  const set = async (f, status) => {
    try { await api.post(`/api/cmtv/feedback/admin/${f.id}`, { status }); qc.invalidateQueries({ queryKey: ['cmtv-feedback-admin'] }); }
    catch { toast.error('Could not save that.'); }
  };
  return (
    <div style={{ marginBottom: 22 }}>
      <h2 style={{ fontSize: 20, fontWeight: 800, margin: '0 0 4px' }}>Suggestions &amp; feedback</h2>
      <p className="rv-empty" style={{ margin: '0 0 10px' }}>From the "Help us improve" box on customers' dashboards. {list.filter((f) => f.status === 'new').length} new.</p>
      {list.length === 0 ? <p className="rv-empty">Nothing yet.</p> : (
        <div className="rv-list">
          {list.map((f) => (
            <div key={f.id} className={`rv-item${f.status === 'new' ? ' st-pending' : ''}`}>
              <div className="rv-item-head">
                <b>{f.kind}</b>
                <span className="rv-empty">{when(f.created_at)} · <Link to={`/admin/customer/${f.user_id}`} style={{ color: '#22e6f2' }}>{f.customer || 'customer'}</Link>
                  {f.contact_ok && f.email ? <> · <a href={`mailto:${f.email}`} style={{ color: '#22e6f2' }}>reply by email</a></> : ' · prefers no contact'}</span>
              </div>
              <p style={{ margin: '8px 0', whiteSpace: 'pre-wrap' }}>{f.text}</p>
              <div style={{ display: 'flex', gap: 8 }}>
                {f.status !== 'done' && <button type="button" className="rv-btn" onClick={() => set(f, 'done')}>Mark done</button>}
                {f.status === 'new' && <button type="button" className="rv-btn" onClick={() => set(f, 'read')}>Mark read</button>}
                {f.status !== 'new' && <span className="rv-empty">{f.status === 'done' ? 'Done' : 'Read'}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
