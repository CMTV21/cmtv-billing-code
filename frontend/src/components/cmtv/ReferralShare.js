// CMTV local addition 2026-10-05 (2027 marketing plan #3): the dashboard's referral card says what each side gets and makes
// sharing one tap (copy message, WhatsApp, text, email, phone share sheet); Admin > Notices "Referral campaign" box.
// Backend: /api/cmtv/refboost (cmtv_refboost.py).
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

export function useReferralOffer() {
  const { data } = useQuery({ queryKey: ['cmtv-refboost'], queryFn: async () => (await api.get('/api/cmtv/refboost')).data, staleTime: 300000 });
  return data;
}
const money = (n) => `$${Number(n || 0).toFixed(Number(n) % 1 ? 2 : 0)}`;
const endsText = (s) => (s ? new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric' }) : '');

export function ReferralOfferLine() {
  const o = useReferralOffer();
  if (!o || !o.enabled || !o.referrer) return <>You earn credit for each friend who joins.</>;
  return (
    <>
      {o.campaign && <span style={{ display: 'block', fontWeight: 800, color: '#fcd34d', margin: '4px 0' }}>🎉 {o.campaign.label}: until {endsText(o.campaign.end)}</span>}
      Your friends get <b>{money(o.referred)} credit</b> when they sign up with your link, and you get <b>{money(o.referrer)} credit</b> for
      each one who buys a plan{o.minimum ? ` of ${money(o.minimum)} or more` : ''}.
    </>
  );
}

export function ReferralShare({ link }) {
  const o = useReferralOffer();
  if (!link) return null;
  const gift = o?.referred ? ` and you'll get ${money(o.referred)} credit to start` : '';
  const msg = `I use CMTV for live TV, sports, movies and series. Sign up with my link${gift}: ${link}`;
  const enc = encodeURIComponent(msg);
  const copyMsg = () => { try { navigator.clipboard.writeText(msg); toast.success('Message copied: paste it anywhere'); } catch { toast(msg); } };
  const canShare = typeof navigator !== 'undefined' && !!navigator.share;
  const b = { font: 'inherit', fontSize: 13, fontWeight: 700, borderRadius: 9, padding: '6px 10px', border: '1px solid var(--line, #27345a)',
    background: 'transparent', color: 'inherit', cursor: 'pointer', textDecoration: 'none', display: 'inline-block' };
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
      {canShare && <button type="button" style={{ ...b, border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }}
        onClick={() => navigator.share({ title: 'CMTV', text: msg }).catch(() => {})}>Share…</button>}
      <button type="button" style={canShare ? b : { ...b, border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }} onClick={copyMsg}>Copy message</button>
      <a style={b} href={`https://wa.me/?text=${enc}`} target="_blank" rel="noopener noreferrer">WhatsApp</a>
      <a style={b} href={`sms:?&body=${enc}`}>Text</a>
      <a style={b} href={`mailto:?subject=${encodeURIComponent('Try CMTV')}&body=${enc}`}>Email</a>
    </div>
  );
}

// Admin > Notices
const field = { font: 'inherit', padding: '7px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' };
const STATUS = { off: ['Off', '#94a3b8'], scheduled: ['Scheduled', '#fcd34d'], running: ['Running now', '#6ee7b7'], ended: ['Ended', '#94a3b8'] };

export function RefBoostBox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-refboost-admin'], queryFn: async () => (await api.get('/api/cmtv/refboost/admin')).data });
  const [f, setF] = useState({ start: '', end: '', referrer: 25, referred: 10, label: 'Bring a friend' });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setF({ start: data.start || '', end: data.end || '', referrer: data.referrer, referred: data.referred, label: data.label || 'Bring a friend' }); }, [data]);
  const save = async (extra = {}, msg = 'Saved') => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/refboost/admin', { ...f, referrer: Number(f.referrer), referred: Number(f.referred), ...extra });
      qc.invalidateQueries({ queryKey: ['cmtv-refboost-admin'] }); qc.invalidateQueries({ queryKey: ['cmtv-refboost'] });
      toast.success(msg);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not save'); }
    setBusy(false);
  };
  const on = !!data?.enabled;
  const [label, color] = STATUS[data?.status || 'off'];
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const normal = data?.normal || {};
  return (
    <div className="rc-box" style={{ marginTop: 18 }}>
      <h2 style={{ margin: '0 0 4px' }}>Referral campaign</h2>
      <p style={{ margin: '0 0 10px', opacity: 0.8 }}>
        Bigger referral rewards for a few weeks (e.g. January and September). Normally a customer gets <b>${normal.referrer_reward ?? '?'}</b> credit
        per friend and the friend gets <b>${normal.referred_reward ?? '?'}</b>. Friends who sign up during the campaign get the campaign amounts;
        it goes back to normal by itself after the last day.
      </p>
      <p style={{ margin: '0 0 10px' }}>Status: <b style={{ color }}>{label}</b>{data?.start && data?.status !== 'off' ? ` · ${data.signups_since_start} referred sign-ups since ${data.start}` : ''}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <label>First day <input type="date" value={f.start} onChange={set('start')} style={field} /></label>
        <label>Last day <input type="date" value={f.end} onChange={set('end')} style={field} /></label>
        <label>Customer gets $<input type="number" min="0" value={f.referrer} onChange={set('referrer')} style={{ ...field, width: 70 }} /></label>
        <label>Friend gets $<input type="number" min="0" value={f.referred} onChange={set('referred')} style={{ ...field, width: 70 }} /></label>
        <label>Name <input value={f.label} maxLength={40} onChange={set('label')} style={{ ...field, width: 150 }} /></label>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button type="button" disabled={busy} onClick={() => save()} style={{ font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' }}>Save</button>
        <button type="button" disabled={busy} onClick={() => {
          if (!on && !window.confirm(`Switch it on? From ${f.start} to ${f.end}: customers get $${f.referrer} per friend, friends get $${f.referred}.`)) return;
          save({ enabled: !on }, on ? 'Switched off' : 'Switched on');
        }} style={{ font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: 0, cursor: 'pointer',
          background: on ? '#fca5a5' : 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f' }}>{on ? 'Switch off' : 'Switch on'}</button>
      </div>
    </div>
  );
}
