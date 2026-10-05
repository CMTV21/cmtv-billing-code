// CMTV local addition 2026-10-05: /hi/<token>, the personal link the owner sends a panel-only customer (backend
// cmtv_reach.py). One tap signs them into their account (no TV password needed) and goes to /link-email, where they add
// their email and a website password and get the claim credit.
import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import { usePageMeta } from '../../components/cmtv/CmtvSEO';
import '../../components/cmtv/cmtv-kb.css';

const day = (iso) => (iso ? new Date(String(iso).endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' }) : '');

export default function HiPage() {
  usePageMeta({ title: 'Finish your account | CMTV', description: 'Finish your CMTV account in 30 seconds.' });
  const { token } = useParams();
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const { data, isLoading, isError } = useQuery({ queryKey: ['cmtv-hi', token], retry: false,
    queryFn: async () => (await api.get(`/api/cmtv/reach/t/${encodeURIComponent(token)}`)).data });

  const go = async () => {
    setBusy(true); setErr('');
    try {
      const r = (await api.post(`/api/cmtv/reach/t/${encodeURIComponent(token)}/start`)).data;
      setAuth(r.user, r.access_token);
      navigate('/link-email');
    } catch (e) { setErr(e?.response?.data?.detail || 'Something went wrong. Please try again.'); setBusy(false); }
  };

  let body;
  if (isLoading) body = <p className="kb-lede">One moment…</p>;
  else if (isError) body = (<>
    <p className="kb-lede">This link isn't valid anymore.</p>
    <p>You can still sign in with your TV app's username and password.</p>
    <p><Link className="kb-btn glow" to="/login">Sign in</Link></p></>);
  else if (data.done) body = (<>
    <p className="kb-lede">Your account is already set up. 🎉</p>
    <p><Link className="kb-btn glow" to="/login">Sign in with your email</Link></p></>);
  else body = (<>
    <p className="kb-lede">Finish your CMTV account in 30 seconds{data.reward ? <> and we'll add <b>${data.reward.toFixed(0)} credit</b></> : ''}.</p>
    <div style={{ background: '#141d33', border: '1px solid #27345a', borderRadius: 14, padding: '12px 14px', margin: '0 0 16px' }}>
      <div style={{ fontSize: 13, color: '#8391b5' }}>Your line</div>
      <b style={{ fontFamily: 'Consolas, Menlo, monospace', fontSize: 17 }}>{data.line}</b>
      <div style={{ fontSize: 14, color: '#c7d2ee' }}>{data.server}{data.ends ? ` · active until ${day(data.ends)}` : ''}</div>
    </div>
    <ul style={{ margin: '0 0 18px', paddingLeft: 20, lineHeight: 1.8 }}>
      <li>A reminder before your plan ends, so you're never cut off</li>
      <li>Renew online any time, by e-Transfer or PayPal</li>
      <li>Your logins and setup guides, whenever you need them</li>
    </ul>
    <button type="button" className="kb-btn glow" disabled={busy} onClick={go} style={{ border: 0, cursor: 'pointer', fontSize: 16, padding: '12px 22px' }}>
      {busy ? 'Opening…' : 'Continue'}
    </button>
    {err && <p style={{ color: '#fca5a5', marginTop: 10 }}>{err}</p>}
    <p style={{ fontSize: 13, color: '#8391b5', marginTop: 14 }}>Next you add your email and choose a website password. Your TV login doesn't change.</p>
  </>);

  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12, maxWidth: 560, marginLeft: 'auto', marginRight: 'auto' }}>
        <h1>{data?.name ? `Hi ${data.name}! 👋` : 'Hi! 👋'}</h1>
        {body}
      </article>
    </div>
  );
}
