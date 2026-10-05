// CMTV local addition 2026-10-05: Admin > Business plan (the owner: "create a business plan section and put the marketing
// section on billing"). The 2027 marketing plan (agreed in chat 2026-10-05) with live progress on each target
// (backend cmtv_bizplan.py), the four priorities with the tools already built for each, the 2027 calendar and what we skip.
// More sections (finances, operations, servers) can be added as tabs later.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/reseller-credits.css';

const box = { background: '#141d33', border: '1px solid #27345a', borderRadius: 14, padding: '14px 16px' };
const muted = { color: '#8391b5' };
const btn = { font: 'inherit', fontWeight: 700, fontSize: 13.5, borderRadius: 9, padding: '6px 11px', border: '1px solid #27345a', background: '#1c2747', color: '#e9edf8', cursor: 'pointer' };

const KPIS = [
  ['revenue', (m) => `Revenue ${m.year}`, (v) => `$${Number(v).toLocaleString()}`, (m) => `last 12 months: $${Number(m.revenue_12m).toLocaleString()}`],
  ['reachable', () => 'Customers we can reach', (v) => v, (m) => `of ${m.active_customers} active paying customers`],
  ['yearly_share', () => 'Yearly plans', (v) => `${v}%`, () => 'of TV plans bought, last 12 months'],
  ['trial_conversion', () => 'Website trials → paid', (v) => `${v}%`, (m) => `${m.trials_counted} TV trials, last 4 months`],
  ['referrals', (m) => `Referrals ${m.year}`, (v) => v, (m) => `${m.referrals_completed} completed`],
  ['reviews', () => 'Reviews', (v) => v, () => 'approved, on the site'],
  ['autorenew', () => 'On auto-renew', (v) => v, () => 'PayPal, 10% off'],
];

const PRIORITIES = [
  { n: 1, title: 'Keep customers', why: '~91% of paying customers stay over 6 months. Most of the ones we lose are on monthly plans, or are panel-only customers we could never remind.',
    built: ['Renewal reminders 7 / 3 / 1 days before: renew, switch to a year (save up to 42%), auto-renew 10% off, "Test my line" for buffering',
      'Holiday bonus months: 12 months + 3 free (Admin > Notices)', 'Status page and Test my line (buffering is the #1 reason people say they could leave)'],
    next: ['Push yearly plans in every renewal', 'Reliability first: every outage costs renewals'] },
  { n: 2, title: 'Own your audience', why: 'Most active customers exist only on the panel: no email, so billing can never remind or tell them anything.',
    built: ['Reach customers: a personal link per customer, copy-ready message, sent / opened / done', 'Monday Ops note for lines ending soon that haven\'t had their link',
      '$5 credit when they finish their account'], link: ['/admin/reach', 'Reach customers'],
    next: ['Send the link with every "time to renew" message', 'Grow the Telegram updates group'] },
  { n: 3, title: 'Referrals and reviews', why: 'Customers like us (recommend score 53) but rarely tell anyone: few referrals, 1 review.',
    built: ['Referral card spells out "$5 for them, $15 for you" with Share / WhatsApp / Text / Email', 'Referral campaigns with bigger rewards for set dates (Admin > Notices)',
      'Review asks at happy moments: after a renewal or a solved ticket'], link: ['/admin/notices', 'Referral campaign'],
    next: ['January and September referral campaigns', 'Sign up 2-3 trusted resellers in other cities'] },
  { n: 4, title: 'Trials into customers', why: 'Website TV trials convert ~33%, and almost everyone who buys does it within a day: the decision happens during the trial.',
    built: ['Trial watch: billing checks if the trial is actually playing', 'Not playing 3 h in: setup help email + a note to you on Telegram', 'Trial ending: "glad you\'re enjoying it" or "we\'ll help you set it up"'],
    next: ['Let TV trials keep their login when they buy (needs a test on each panel)'] },
];

const CALENDAR = [
  ['January', 'Big renewal month', 'Renew-for-a-year push · referral campaign'],
  ['February', 'Super Bowl', 'Sports trial push on Telegram'],
  ['April', 'NHL / NBA playoffs · renewals', 'Playoff trial push · yearly renewals'],
  ['May – June', 'Slowest months', 'Small summer offer (bonus months switch)'],
  ['September', 'NFL starts · renewals', 'Referral campaign · yearly renewals'],
  ['November', 'Black Friday', '12 + 3 free · CMTV+ $45 · gift cards'],
  ['December', 'Holidays', 'Gift cards'],
];

function Kpi({ k, m, t, edit, setEdit, save }) {
  const [label, fmt, sub] = [KPIS.find((x) => x[0] === k)[1](m), KPIS.find((x) => x[0] === k)[2], KPIS.find((x) => x[0] === k)[3](m)];
  const v = m[k]; const target = t[k];
  const pct = target ? Math.max(2, Math.min(100, (Number(v) / Number(target)) * 100)) : 0;
  const done = Number(v) >= Number(target);
  return (
    <div style={box}>
      <div style={{ ...muted, fontSize: 13 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 24 }}>{fmt(v)}</b>
        {edit === k ? (
          <span>target <input type="number" defaultValue={target} autoFocus onBlur={(e) => save(k, e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && e.target.blur()} style={{ width: 80, font: 'inherit', padding: '2px 6px', borderRadius: 6, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' }} /></span>
        ) : <button type="button" onClick={() => setEdit(k)} title="Change the target" style={{ ...muted, background: 'none', border: 0, cursor: 'pointer', font: 'inherit', fontSize: 13, padding: 0 }}>
          / {fmt(target)} target ✎</button>}
      </div>
      <div style={{ height: 6, background: '#0a1020', borderRadius: 6, margin: '8px 0 6px', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 6, background: done ? '#34d399' : 'linear-gradient(90deg,#22e6f2,#8b5cf6)' }} />
      </div>
      <div style={{ ...muted, fontSize: 12.5 }}>{done ? '✓ target reached · ' : ''}{sub}</div>
    </div>
  );
}

export default function AdminBusinessPlanPage() {
  const { data, refetch } = useQuery({ queryKey: ['cmtv-bizplan'], queryFn: async () => (await api.get('/api/cmtv/bizplan/admin')).data });
  const [edit, setEdit] = useState(null);
  const save = async (k, v) => {
    setEdit(null);
    if (v === '' || Number(v) === Number(data?.targets?.[k])) return;
    try { await api.post('/api/cmtv/bizplan/admin/targets', { [k]: Number(v) }); toast.success('Target saved'); refetch(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not save'); }
  };
  const m = data?.metrics; const t = data?.targets;
  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 style={{ margin: '0 0 2px' }}>Business plan</h1>
      <p style={{ ...muted, margin: '0 0 14px' }}>Sections: <b style={{ color: '#e9edf8' }}>Marketing 2027</b> · more (finances, operations, servers) can be added here later.</p>

      <h2 style={{ margin: '0 0 6px' }}>Marketing 2027</h2>
      <p style={{ margin: '0 0 12px', maxWidth: 820 }}>
        Growth comes from <b>keeping customers longer, reaching the ones we have, and turning happy customers into referrals</b>, not from
        advertising. Live numbers below update from billing; tap a target to change it.
      </p>
      {!m ? <p style={muted}>Working out the numbers…</p> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 10, marginBottom: 22 }}>
          {KPIS.map(([k]) => <Kpi key={k} k={k} m={m} t={t} edit={edit} setEdit={setEdit} save={save} />)}
        </div>
      )}

      <h3 style={{ margin: '0 0 8px' }}>The four priorities</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 10, marginBottom: 22 }}>
        {PRIORITIES.map((p) => (
          <div key={p.n} style={box}>
            <b style={{ fontSize: 16 }}>{p.n}. {p.title}</b>
            <p style={{ margin: '4px 0 8px', fontSize: 14, color: '#c7d2ee' }}>{p.why}</p>
            <div style={{ fontSize: 13, ...muted }}>In place</div>
            <ul style={{ margin: '2px 0 8px', paddingLeft: 18, fontSize: 13.5, lineHeight: 1.5 }}>{p.built.map((x) => <li key={x}>✓ {x}</li>)}</ul>
            <div style={{ fontSize: 13, ...muted }}>Next</div>
            <ul style={{ margin: '2px 0 8px', paddingLeft: 18, fontSize: 13.5, lineHeight: 1.5 }}>{p.next.map((x) => <li key={x}>{x}</li>)}</ul>
            {p.link && <Link to={p.link[0]} style={{ ...btn, textDecoration: 'none' }}>{p.link[1]} →</Link>}
          </div>
        ))}
      </div>

      <h3 style={{ margin: '0 0 8px' }}>2027 calendar</h3>
      <div style={{ ...box, padding: 0, overflow: 'hidden', marginBottom: 22 }}>
        {CALENDAR.map(([when, moment, action], i) => (
          <div key={when} style={{ display: 'grid', gridTemplateColumns: 'minmax(90px, 130px) minmax(0, 1fr) minmax(0, 1.4fr)', gap: 10, padding: '10px 14px',
            borderTop: i ? '1px solid #1d2846' : 0, fontSize: 14 }}>
            <b>{when}</b><span style={{ color: '#c7d2ee' }}>{moment}</span><span>{action}</span>
          </div>
        ))}
      </div>

      <h3 style={{ margin: '0 0 8px' }}>What we skip, and why</h3>
      <ul style={{ ...box, margin: 0, paddingLeft: 32, lineHeight: 1.7, fontSize: 14 }}>
        <li><b>Paid ads</b> (Google, Facebook, TikTok): their policies don't allow IPTV ads, so accounts get banned and money is wasted.</li>
        <li><b>Price cuts</b>: customers rank reliability far above price in our own survey.</li>
        <li><b>More emails</b>: one a month at most; Telegram and the 7 pm changelog do the rest.</li>
      </ul>
    </div>
  );
}
