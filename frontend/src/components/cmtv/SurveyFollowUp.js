// CMTV local addition 2026-10-05: Admin > Survey > Responses. Every answer (unhappy first), tick "Responded", or reply
// right here: the message goes to the customer as a branded email and the response is marked responded.
// Backend: /api/cmtv/survey/admin/followup (cmtv_survey_followup.py).
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const TEMPLATES = [
  ['Thank you', (f) => `Thanks so much for taking our survey, ${f}! It really helps, and we're glad to have you with CMTV.`],
  ['Sorry + fixing it', (f) => `Thanks for the honest feedback, ${f}. We're sorry it hasn't been perfect. We're working on it, and if anything is giving you trouble right now, just reply and we'll sort it out with you.`],
  ['Buffering help', (f) => `Thanks for the feedback, ${f}. For buffering, these quick fixes solve most problems: https://billing.cmtv.info/knowledge-base/cmtv-buffering\nIf it still happens, reply with your device and app and we'll help you directly.`],
  ["We're on it", (f) => `Thanks for the suggestion, ${f}! We've added it to our list and will let you know in our updates when it's ready.`],
];
const when = (iso) => (iso ? new Date(String(iso).endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '');
const npsColor = (n) => (n == null ? '#94a3b8' : n >= 9 ? '#6ee7b7' : n >= 7 ? '#fcd34d' : '#fca5a5');
const btn = { font: 'inherit', fontWeight: 700, fontSize: 13.5, borderRadius: 9, padding: '6px 11px', border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' };

function Row({ r, refetch }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const first = (r.name || '').split(' ')[0] || 'there';
  const tick = async () => {
    try { await api.post(`/api/cmtv/survey/admin/followup/${r.id}/done`, { done: !r.done }); refetch(); }
    catch { toast.error('Could not save'); }
  };
  const send = async () => {
    if (!window.confirm(`Email this reply to ${r.name} (${r.email})?`)) return;
    setBusy(true);
    try { await api.post(`/api/cmtv/survey/admin/followup/${r.id}/reply`, { text }); toast.success('Reply sent'); setOpen(false); setText(''); refetch(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not send'); }
    setBusy(false);
  };
  return (
    <div className="sv-cmt" style={{ padding: '12px 0', opacity: r.done && !open ? 0.75 : 1 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px', alignItems: 'center' }}>
        <Link to={`/admin/customer/${r.user_id}`}><b>{r.name || 'Customer'}</b></Link>
        <span style={{ fontWeight: 800, color: npsColor(r.nps) }}>{r.nps ?? '–'}/10</span>
        <span>{r.stars ? `${r.stars}★` : ''}</span>
        {r.servers.length > 0 && <small style={{ opacity: 0.7 }}>{r.servers.join(', ')}</small>}
        <small style={{ opacity: 0.6, marginLeft: 'auto' }}>{when(r.at)}</small>
      </div>
      {r.comment && <div style={{ margin: '6px 0' }}>“{r.comment}”</div>}
      {r.leave.length > 0 && !r.leave.includes("Nothing, I'll stay") && <div><small>Could leave over: <b>{r.leave.join(', ')}</b></small></div>}
      {r.improve.length > 0 && <div><small>Wants: {r.improve.join(', ')}</small></div>}
      {r.replies.map((x) => (
        <div key={x.at} style={{ margin: '6px 0 0', padding: '6px 10px', borderLeft: '3px solid #8b5cf6', fontSize: 13.5, opacity: 0.85 }}>
          <small>You replied {when(x.at)}:</small> {x.text}
        </div>
      ))}
      <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', fontWeight: 700, fontSize: 14 }}>
          <input type="checkbox" checked={r.done} onChange={tick} style={{ width: 17, height: 17 }} /> Responded
        </label>
        {r.email ? <button type="button" style={btn} onClick={() => setOpen(!open)}>{open ? 'Close' : r.replies.length ? 'Reply again' : 'Reply'}</button>
          : <small style={{ opacity: 0.7 }}>No email on file: reach them another way, then tick Responded.</small>}
      </div>
      {open && (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
            {TEMPLATES.map(([k, t]) => <button key={k} type="button" style={{ ...btn, fontWeight: 600, padding: '4px 9px' }} onClick={() => setText(t(first))}>{k}</button>)}
          </div>
          <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={`Write to ${first}…`}
            style={{ width: '100%', boxSizing: 'border-box', font: 'inherit', padding: '8px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' }} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <button type="button" disabled={busy || text.trim().length < 2} onClick={send}
              style={{ ...btn, border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }}>{busy ? 'Sending…' : 'Send reply'}</button>
            <small style={{ opacity: 0.7 }}>Goes to {r.email} as a CMTV-branded email, with their comment quoted. Marks them Responded.</small>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SurveyFollowUp() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-survey-followup'], queryFn: async () => (await api.get('/api/cmtv/survey/admin/followup')).data });
  const [tab, setTab] = useState('todo');
  const rows = (data?.rows || []).filter((r) => (tab === 'all' ? true : tab === 'done' ? r.done : !r.done));
  const tabs = [['todo', `To reply (${data?.to_reply ?? 0})`], ['done', 'Responded'], ['all', 'All']];
  return (
    <div className="sv-box" style={{ marginTop: 16 }}>
      <b>Responses</b>
      <p className="rs-sub" style={{ margin: '4px 0 10px' }}>Unhappy customers (0 to 6) first. Reply here, or tick Responded if you reached them another way.</p>
      <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
        {tabs.map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            style={{ ...btn, background: tab === k ? '#22e6f2' : '#1c2747', color: tab === k ? '#07101f' : '#e9edf8' }}>{l}</button>
        ))}
      </div>
      {!data ? <p className="rs-sub">Loading…</p> : rows.length === 0 ? <p className="rs-sub">{tab === 'todo' ? 'All caught up 🎉' : 'Nothing here yet.'}</p>
        : rows.map((r) => <Row key={r.id} r={r} refetch={refetch} />)}
    </div>
  );
}
