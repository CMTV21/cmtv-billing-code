// CMTV local addition 2026-09-29: /survey?t=<token>, the customer survey (backend cmtv_survey.py). Personal link from the
// email / Telegram; finishing it adds $5 credit once. Questions come from the server, so they can change without a rebuild.
import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../../api/api';
import '../../components/cmtv/cmtv-kb.css';
import '../../components/cmtv/cmtv-survey.css';

const NPS_HINT = ['Not at all likely', 'Extremely likely'];
const STAR_WORDS = ['', 'Not happy', 'Could be better', 'OK', 'Happy', 'Very happy'];

function Chips({ options, value, multi, onChange, label }) {
  const on = (o) => (multi ? (value || []).includes(o) : value === o);
  const toggle = (o) => {
    if (!multi) return onChange(value === o ? null : o);
    const cur = value || [];
    return onChange(cur.includes(o) ? cur.filter((x) => x !== o) : [...cur, o]);
  };
  return (
    <div className="sv-chips" role="group" aria-label={label}>
      {options.map((o) => (
        <button type="button" key={o} className={on(o) ? 'on' : ''} aria-pressed={on(o)} onClick={() => toggle(o)}>{o}</button>
      ))}
    </div>
  );
}

function Question({ q, a, set }) {
  if (q.type === 'nps') {
    return (
      <>
        <div className="sv-nps" role="radiogroup" aria-label={q.text}>
          {Array.from({ length: 11 }, (_, i) => (
            <button type="button" key={i} role="radio" aria-checked={a === i} className={a === i ? 'on' : ''} onClick={() => set(i)}>{i}</button>
          ))}
        </div>
        <div className="sv-hint"><span>{NPS_HINT[0]}</span><span>{NPS_HINT[1]}</span></div>
      </>
    );
  }
  if (q.type === 'stars') {
    return (
      <div className="sv-stars" role="radiogroup" aria-label={q.text}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button type="button" key={n} role="radio" aria-checked={a === n} className={a >= n ? 'on' : ''} onClick={() => set(n)} aria-label={`${n} stars`}>★</button>
        ))}
        <span className="sv-word">{STAR_WORDS[a || 0]}</span>
      </div>
    );
  }
  if (q.type === 'multi') {
    const v = a || { picked: [], other: '' };
    return (
      <>
        <Chips multi options={q.options} value={v.picked} label={q.text} onChange={(picked) => set({ ...v, picked })} />
        {q.other && <input className="sv-other" value={v.other} maxLength={200} placeholder="Something else? Type it here"
          aria-label="Something else" onChange={(e) => set({ ...v, other: e.target.value })} />}
      </>
    );
  }
  if (q.type === 'single') return <Chips options={q.options} value={a} label={q.text} onChange={set} />;
  if (q.type === 'grid') {
    const v = a || {};
    return (
      <div className="sv-grid">
        {q.items.map((it) => (
          <div className="sv-grid-row" key={it}>
            <span>{it}</span>
            <div className="sv-scale" role="radiogroup" aria-label={it}>
              {[1, 2, 3, 4, 5].map((n) => (
                <button type="button" key={n} role="radio" aria-checked={v[it] === n} className={v[it] === n ? 'on' : ''}
                  onClick={() => { const nv = { ...v }; if (nv[it] === n) delete nv[it]; else nv[it] = n; set(nv); }}>{n}</button>
              ))}
            </div>
          </div>
        ))}
        <p className="sv-hint-line">1 = poor, 5 = great. Skip anything you don't use.</p>
      </div>
    );
  }
  if (q.type === 'addons') {
    const v = a || {};
    return (
      <div className="sv-grid">
        {q.items.map((it) => (
          <div className="sv-grid-row" key={it}>
            <span>{it}</span>
            <Chips options={q.choices} value={v[it] || null} label={it} onChange={(c) => { const nv = { ...v }; if (c) nv[it] = c; else delete nv[it]; set(nv); }} />
          </div>
        ))}
      </div>
    );
  }
  return <textarea className="sv-text" value={a || ''} maxLength={1500} rows={4} aria-label={q.text}
    placeholder="Optional" onChange={(e) => set(e.target.value)} />;
}

export default function SurveyPage() {
  const [params] = useSearchParams();
  const token = params.get('t') || '';
  const [info, setInfo] = useState(null);
  const [answers, setAnswers] = useState({});
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) { setError('This survey link is missing its code. Please use the link from your email.'); return; }
    api.get(`/api/cmtv/survey/q/${encodeURIComponent(token)}`)
      .then(({ data }) => { setInfo(data); if (data.answers) setAnswers(data.answers); })
      .catch((e) => setError(e.response?.data?.detail || 'This survey link isn\'t valid.'));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (answers.nps === undefined || answers.nps === null) { setError('Please answer the first question (0 to 10).'); window.scrollTo({ top: 0, behavior: 'smooth' }); return; }
    if (!answers.stars) { setError('Please pick a star rating.'); return; }
    setBusy(true);
    try {
      const { data } = await api.post(`/api/cmtv/survey/q/${encodeURIComponent(token)}`, { answers });
      setDone(data);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) { setError(err.response?.data?.detail || 'Something went wrong. Please try again.'); }
    setBusy(false);
  };

  return (
    <div className="cmtv-kb sv">
      <h1>CMTV survey</h1>
      {done ? (
        <div className="sv-done">
          <p className="kb-lede">Thank you{info?.first_name ? `, ${info.first_name}` : ''}! Your answers are in.</p>
          {done.credited ? <p>We've added <b>${Number(done.reward).toFixed(2)} credit</b> to your account. It's used automatically on your next order.</p>
            : <p>Your updated answers are saved. (The ${Number(done.reward || 5).toFixed(2)} credit was added the first time.)</p>}
          <Link className="kb-btn glow" to="/dashboard">Go to your dashboard</Link>
        </div>
      ) : !info ? (
        <p className="kb-lede">{error || 'Loading…'}</p>
      ) : (
        <form onSubmit={submit}>
          <p className="kb-lede">
            Hi {info.first_name}! About 2 minutes. {info.done ? 'You can change your answers below.' : `When you finish, we'll add $${Number(info.reward).toFixed(2)} credit to your account.`}
          </p>
          {error && <p className="sv-error" role="alert">{error}</p>}
          {info.questions.map((q, i) => (
            <fieldset className="sv-q" key={q.id}>
              <legend><span className="sv-n">{i + 1}</span>{q.text}{q.required && <span className="sv-req"> *</span>}</legend>
              <Question q={q} a={answers[q.id]} set={(v) => setAnswers((cur) => ({ ...cur, [q.id]: v }))} />
            </fieldset>
          ))}
          <button type="submit" className="kb-btn glow sv-submit" disabled={busy}>{busy ? 'Sending…' : 'Send my answers'}</button>
          <p className="sv-note">Your answers go to the CMTV team with your account, so we can follow up if something isn't right.</p>
        </form>
      )}
    </div>
  );
}
