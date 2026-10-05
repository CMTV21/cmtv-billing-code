// CMTV local addition 2026-10-04: "Help us improve" on the customer dashboard (backend cmtv_feedback.py):
// send a suggestion / report something / anything else, and "Leave a review" (opens the same one-time review page the
// emailed invites use; only for paying customers who haven't reviewed yet).
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const KINDS = [['suggestion', 'Suggestion'], ['problem', 'Something isn\'t working'], ['other', 'Something else']];
const field = { width: '100%', boxSizing: 'border-box', font: 'inherit', fontSize: 14, color: 'var(--text, #e9edf8)', background: 'var(--deep, #0a1020)',
  border: '1px solid var(--line, #27345a)', borderRadius: 10, padding: '8px 10px' };

export default function FeedbackBox() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ['cmtv-feedback-me'], queryFn: async () => (await api.get('/api/cmtv/feedback/me')).data, staleTime: 60000 });
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState('suggestion');
  const [text, setText] = useState('');
  const [contact, setContact] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const review = data?.review;

  const send = async () => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/feedback', { kind, text, contact_ok: contact });
      setSent(true); setText(''); setOpen(false);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not send that. Please try again.'); }
    setBusy(false);
  };
  const leaveReview = async () => {
    try { navigate((await api.post('/api/cmtv/feedback/review-link')).data.link); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not open the review page.'); qc.invalidateQueries({ queryKey: ['cmtv-feedback-me'] }); }
  };

  return (
    <div className="ca-panel">
      <h2 className="ca-h2">Help us improve</h2>
      {sent ? <p>Thanks! We read every message. 💙</p> : <p>Ideas, something that bugs you, or a feature you'd like? We read every message.</p>}
      {!open ? (
        <div className="ca-help">
          <button type="button" className="ca-btn ca-ghost" onClick={() => { setOpen(true); setSent(false); }}>Send a suggestion</button>
          {review?.can && <button type="button" className="ca-btn ca-glow" onClick={leaveReview}>Leave a review ⭐</button>}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={field} aria-label="What is it about?">
            {KINDS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
          <textarea rows={4} maxLength={1500} value={text} onChange={(e) => setText(e.target.value)} style={field}
            placeholder={kind === 'problem' ? 'What happened? (For help with your line, the support bot is faster.)' : 'Tell us…'} />
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
            <input type="checkbox" checked={contact} onChange={(e) => setContact(e.target.checked)} /> You can contact me about this
          </label>
          <div className="ca-help">
            <button type="button" className="ca-btn ca-glow" disabled={busy || text.trim().length < 3} onClick={send}>{busy ? 'Sending…' : 'Send'}</button>
            <button type="button" className="ca-btn ca-ghost" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
      {review?.already && <p style={{ marginTop: 8, fontSize: 13 }}>Thanks for your review! ⭐</p>}
    </div>
  );
}
