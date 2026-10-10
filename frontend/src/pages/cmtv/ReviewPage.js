// CMTV local addition 2026-09-28: /review?t=<one-time token> — the customer's review form (no sign-in needed; the link
// comes from the review request email / Telegram message). Backend: cmtv_reviews.py. Shown in the navy account frame.
import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../../api/api';
import '../../components/cmtv/cmtv-kb.css';
import '../../components/cmtv/cmtv-reviews.css';

export default function ReviewPage() {
  const [params] = useSearchParams();
  const token = params.get('t') || '';
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  // CMTV 2026-10-10: ?r=1..5 = the star tapped in the ticket-closed email
  const [rating, setRating] = useState(() => { const r = parseInt(params.get('r'), 10); return r >= 1 && r <= 5 ? r : 0; });
  const [hover, setHover] = useState(0);
  const [text, setText] = useState('');
  const [name, setName] = useState('');
  const [province, setProvince] = useState('');
  const [consent, setConsent] = useState(true);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    if (!token) { setError('This review link is missing its code. Use the link from your email.'); return; }
    api.get(`/api/cmtv/reviews/invite/${encodeURIComponent(token)}`)
      .then((r) => { setInfo(r.data); setName(r.data.name); })
      .catch((e) => setError(e?.response?.data?.detail || 'This review link has expired.'));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (!rating) { setError('Pick a star rating first.'); return; }
    setBusy(true); setError('');
    try {
      const r = await api.post('/api/cmtv/reviews/submit', { token, rating, text, display_name: name, province, consent });
      setDone(r.data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not send your review. Try again in a minute.');
    } finally { setBusy(false); }
  };

  const labels = ['', 'Poor', 'Not great', 'OK', 'Good', 'Excellent'];
  return (
    <div className="cmtv-kb">
      <article className="kb-article cmtv-review" style={{ marginTop: 12 }}>
        <h1>How's CMTV going?</h1>
        {done ? (
          <>
            <p className="kb-lede">Thank you{info?.name ? `, ${info.name.split(' ')[0]}` : ''}! Your review is in.</p>
            {done.low
              ? <p>Sorry it hasn't been perfect. We read every review, and we'll be in touch. If something isn't working right now, <Link to="/tickets">open a ticket</Link> or message us on Telegram and we'll fix it.</p>
              : <p>{consent ? 'Once we\'ve checked it, it may appear on cmtv.info with your first name and last initial.' : 'We\'ll keep it private, as you asked.'}</p>}
            <Link className="kb-btn glow" to="/dashboard">Go to my account</Link>
          </>
        ) : info?.already ? (
          <p className="kb-lede">You've already left a review. Thank you!</p>
        ) : error && !info ? (
          <p className="kb-lede">{error}</p>
        ) : !info ? (
          <p className="kb-lede">Loading…</p>
        ) : (
          <form onSubmit={submit} className="rv-form">
            <p className="kb-lede">It takes 30 seconds, and it really helps other people choose us.</p>
            <div className="rv-stars" role="radiogroup" aria-label="Your rating" onMouseLeave={() => setHover(0)}>
              {[1, 2, 3, 4, 5].map((n) => (
                <button type="button" key={n} role="radio" aria-checked={rating === n} aria-label={`${n} star${n > 1 ? 's' : ''}`}
                  className={(hover || rating) >= n ? 'on' : ''} onMouseEnter={() => setHover(n)} onClick={() => setRating(n)}>★</button>
              ))}
              <span className="rv-label">{labels[hover || rating] || 'Tap a star'}</span>
            </div>
            <label className="rv-field">
              <span>Your review</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={600} rows={4}
                placeholder="What do you like? How's the picture, the channels, the support?" />
              <small>{600 - text.length} characters left</small>
            </label>
            <div className="rv-row">
              <label className="rv-field"><span>Name to show</span>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} />
              </label>
              <label className="rv-field"><span>Province (optional)</span>
                <select value={province} onChange={(e) => setProvince(e.target.value)}>
                  <option value="">Don't show</option>
                  {(info.provinces || []).map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </label>
            </div>
            <label className="rv-consent">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>CMTV may show my review on cmtv.info with the name above (and province, if chosen).</span>
            </label>
            {error && <p className="rv-error">{error}</p>}
            <button type="submit" className="kb-btn glow" disabled={busy}>{busy ? 'Sending…' : 'Send my review'}</button>
          </form>
        )}
      </article>
    </div>
  );
}
