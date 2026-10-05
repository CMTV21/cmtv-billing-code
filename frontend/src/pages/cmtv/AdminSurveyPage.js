// CMTV local addition 2026-09-29: Admin > Survey. Send the customer survey (check first, then send) and read the results:
// recommend score (NPS), stars, ratings by server, what to add, what could make them leave, add-on interest, comments and
// the unhappy customers to follow up. Backend: /api/cmtv/survey/admin (cmtv_survey.py).
import React, { useState } from 'react';
import SurveyFollowUp from '../../components/cmtv/SurveyFollowUp'; // 2026-10-05: responses + replies
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/reseller-credits.css';
import '../../components/cmtv/cmtv-survey.css';

function Bars({ counts, total }) {
  const rows = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  return rows.map(([k, v]) => (
    <div className="sv-barrow" key={k}><span>{k}</span><div className="sv-bar"><i style={{ width: `${total ? (v * 100) / total : 0}%` }} /></div><b>{v}</b></div>
  ));
}

export default function AdminSurveyPage() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-survey-admin'], queryFn: async () => (await api.get('/api/cmtv/survey/admin')).data, refetchInterval: 60000 });
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const send = async (dry) => {
    setBusy(true);
    try {
      const r = (await api.post('/api/cmtv/survey/admin/send', { dry_run: dry })).data;
      if (dry) setCheck(r);
      else { toast.success(`Sending to ${r.count} customers in the background`); setCheck(null); setConfirm(false); refetch(); }
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not send'); }
    setBusy(false);
  };
  const d = data || {};
  const n = d.answered || 0;
  const servers = d.servers || [];

  return (
    <div className="rs-admin sv-admin">
      <h1>Customer survey</h1>
      <p className="rs-sub">About 2 minutes. Paying customers get one personal link by email (and Telegram if connected); finishing it adds $5 credit once.</p>

      <div className="sv-box">
        <b>Send it</b>
        <p className="rs-sub" style={{ margin: '4px 0 10px' }}>Goes to customers with an active paid plan and a real email who haven't been invited yet. Customers who unsubscribed from offers only get it on Telegram (if connected).</p>
        <div className="row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" className="rv-btn" disabled={busy} onClick={() => send(true)}>Check who gets it</button>
          {check && check.count > 0 && !confirm && <button type="button" className="rv-btn glow" onClick={() => setConfirm(true)}>Send to {check.count}</button>}
          {confirm && <><span>Send the survey to {check.count} customers now?</span>
            <button type="button" className="rv-btn glow" disabled={busy} onClick={() => send(false)}>Yes, send</button>
            <button type="button" className="rv-btn" onClick={() => setConfirm(false)}>Cancel</button></>}
          {check && check.count === 0 && <span>Everyone eligible has already been invited.</span>}
          {check && check.count > 0 && !confirm && <span className="rs-sub">e.g. {check.sample.join(', ')}</span>}
          {d.sending && <span className="rs-sub">Sending in progress…</span>}
        </div>
      </div>

      <div className="sv-kpis">
        <div className="sv-kpi"><span>Answered</span><b>{n} / {d.invited || 0}</b><span>{d.invited ? Math.round((n * 100) / d.invited) : 0}% of invited</span></div>
        <div className="sv-kpi"><span>Recommend score (NPS)</span><b>{d.nps ?? '–'}</b><span>{d.promoters || 0} would recommend · {d.detractors || 0} unhappy</span></div>
        <div className="sv-kpi"><span>Average stars</span><b>{d.stars ? `${d.stars} ★` : '–'}</b><span>out of 5</span></div>
        <div className="sv-kpi"><span>$5 credits given</span><b>{d.credit_given || 0}</b><span>${((d.credit_given || 0) * 5).toFixed(2)} in total</span></div>
      </div>

      {n === 0 ? <p className="rs-sub">No answers yet. Results appear here as they come in.</p> : (
        <>
          <div className="sv-box"><b>Ratings (1 to 5)</b>
            <div style={{ overflowX: 'auto' }}><table><thead><tr><th>What</th><th>All</th>{servers.map((s) => <th key={s}>{s}</th>)}</tr></thead>
              <tbody>{Object.entries(d.ratings || {}).map(([k, v]) => <tr key={k}><td>{k}</td><td><b>{v.all ?? '–'}</b></td>{servers.map((s) => <td key={s}>{v[s] ?? '–'}</td>)}</tr>)}</tbody>
            </table></div></div>
          <div className="sv-cols">
            <div className="sv-box"><b>What to add or improve</b><Bars counts={d.counts?.improve} total={n} /></div>
            <div className="sv-box"><b>What could make them not renew</b><Bars counts={d.counts?.leave} total={n} /></div>
            <div className="sv-box"><b>Devices</b><Bars counts={d.counts?.devices} total={n} /></div>
            <div className="sv-box"><b>App used most</b><Bars counts={d.app} total={n} /></div>
          </div>
          <div className="sv-box"><b>Add-ons</b>
            <table><thead><tr><th /><th>Have it</th><th>Interested</th><th>Not interested</th></tr></thead>
              <tbody>{Object.entries(d.addons || {}).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v['I have it']}</td><td><b>{v.Interested}</b></td><td>{v['Not interested']}</td></tr>)}</tbody></table></div>
          {d.unhappy?.length > 0 && (
            <div className="sv-box"><b>Unhappy customers to follow up (0 to 6 out of 10)</b>
              {d.unhappy.map((u) => <div className="sv-cmt" key={u.user_id}><Link to={`/admin/customer/${u.user_id}`}>{u.name}</Link> · {u.nps}/10 · {u.stars}★
                {u.leave.length > 0 && <small> · could leave over: {u.leave.join(', ')}</small>}</div>)}</div>
          )}
          <div className="sv-box"><b>Comments</b>
            {(d.comments || []).length === 0 ? <p className="rs-sub">None yet.</p> : d.comments.map((c) => (
              <div className="sv-cmt" key={`${c.user_id}-${c.at}`}><Link to={`/admin/customer/${c.user_id}`}>{c.name}</Link> <small>· {c.nps}/10 · {c.stars}★</small>
                {c.comment && <div>“{c.comment}”</div>}{c.other.map((o) => <div key={o}><small>Other: {o}</small></div>)}</div>
            ))}</div>
          <SurveyFollowUp />
        </>
      )}
    </div>
  );
}
