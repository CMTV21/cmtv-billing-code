// CMTV local addition 2026-10-04: Admin > Customers > Possible duplicates (backend cmtv_dupes.py). Groups of customer
// accounts that share a device, an internet connection or a Gmail inbox (dots / +tags), with their trials and spend,
// plus the trials and referral rewards the duplicate checks refused or held. Read-only apart from "allow this IP".
// 2026-10-09: bans (an account + its IPs and devices, or one IP) to stop repeat trial accounts; see cmtv_dupes.py #7.
// An on/off switch for all bans, and every ban / unban / switch can be undone from "Recent ban changes".
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../../api/api';
import '../../components/cmtv/cmtv-reviews.css';

const MATCH = { device: 'Same device', ip: 'Same internet connection', inbox: 'Same Gmail inbox' };
const KIND = { user: 'Account', ip: 'IP', device: 'Device' };
const errText = (e) => e?.response?.data?.detail || e?.message || 'Something went wrong';
const when = (v) => (v ? new Date(v).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '–');

export default function AdminDuplicatesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['cmtv-dupes'], queryFn: async () => (await api.get('/api/cmtv/dupes/admin/groups')).data,
  });
  const groups = data?.groups || [];
  const bans = data?.bans || [];
  const qc = useQueryClient();
  const [who, setWho] = useState('');
  const [reason, setReason] = useState('');
  const [note, setNote] = useState(null);
  const done = () => qc.invalidateQueries({ queryKey: ['cmtv-dupes'] });
  const banM = useMutation({
    mutationFn: async (body) => (await api.post('/api/cmtv/dupes/admin/ban', { reason, ...body })).data,
    onSuccess: (r) => {
      const names = (r.accounts || []).map((a) => a.name || a.email).join(', ');
      setNote({ ok: true, text: `Banned${names ? ` ${names}` : ''}: ${r.ip} new IP${r.ip === 1 ? '' : 's'}, ${r.device} new device${r.device === 1 ? '' : 's'}`
        + (r.skipped_allowed_ips ? ` (${r.skipped_allowed_ips} allowed IP${r.skipped_allowed_ips === 1 ? '' : 's'} left alone)` : '') + '.' });
      setWho(''); done();
    },
    onError: (e) => setNote({ ok: false, text: errText(e) }),
  });
  const unbanM = useMutation({
    mutationFn: async (body) => (await api.post('/api/cmtv/dupes/admin/unban', body)).data,
    onSuccess: done, onError: (e) => setNote({ ok: false, text: errText(e) }),
  });
  const submitBan = (e) => {
    e.preventDefault();
    const v = who.trim();
    if (!v) return;
    const isIp = /^[0-9.]+$/.test(v) || (v.includes(':') && /^[0-9a-f:]+$/i.test(v));
    banM.mutate(isIp ? { ip: v } : { who: v });
  };
  const banGroup = (g) => {
    const names = g.people.map((p) => p.name || p.email).join(', ');
    if (window.confirm(`Ban ${names} and every IP and device they've used? They won't be able to sign up or take free trials.`)) {
      banM.mutate({ user_ids: g.people.map((p) => p.id) });
    }
  };
  const switchM = useMutation({
    mutationFn: async (on) => (await api.post('/api/cmtv/dupes/admin/bans-switch', { on })).data,
    onSuccess: done, onError: (e) => setNote({ ok: false, text: errText(e) }),
  });
  const undoM = useMutation({
    mutationFn: async (id) => (await api.post('/api/cmtv/dupes/admin/ban-undo', { id })).data,
    onSuccess: done, onError: (e) => setNote({ ok: false, text: errText(e) }),
  });
  const bansOn = data?.bans_on !== false;
  const logText = (e) => {
    const who = e.accounts.map((a) => a.name || a.email).join(', ') || e.ip;
    if (e.action === 'switch') return `Turned all bans ${e.on ? 'on' : 'off'}`;
    return `${e.action === 'ban' ? 'Banned' : 'Unbanned'} ${who || 'an entry'} (${e.count} entr${e.count === 1 ? 'y' : 'ies'})`;
  };
  const bannedUsers = new Set(bans.filter((b) => b.kind === 'user').map((b) => b.value));
  return (
    <div className="rv-admin">
      <div className="rv-admin-head">
        <h1>Possible duplicates</h1>
        <p>Customer accounts that look like the same person: the same device or internet connection (from sign-ups, sign-ins
          and trials since {when(data?.fingerprints_since)}), or the same Gmail inbox written differently. Households and
          shared Wi-Fi are normal, so treat these as hints, not proof.</p>
      </div>
      <div className="rv-stats">
        <div><b>{groups.length}</b><span>groups</span></div>
        <div><b>{groups.reduce((n, g) => n + g.trials, 0)}</b><span>trials in them</span></div>
        <div><b>{data?.trial_refusals?.length ?? '–'}</b><span>trials refused (recent)</span></div>
        <div><b>{bans.length}</b><span>bans</span></div>
      </div>
      <form className="rv-invites" onSubmit={submitBan}>
        <div>
          <b>Ban a repeat trial taker</b>
          <span>Type their email, name or account id to ban the account and every IP and device it has used. Or type one IP.
            Banned visitors can't sign up or take a free trial. They can still sign in and pay. If they sign in from somewhere new,
            that IP and device get banned too (IPs added like this expire after 30 days, because mobile and home IPs get passed on).</span>
          <div className="rv-row" style={{ marginTop: 8 }}>
            <label className="rv-field"><span>Account or IP</span>
              <input value={who} onChange={(e) => setWho(e.target.value)} placeholder="e.g. gamebattles or name@gmail.com" /></label>
            <label className="rv-field"><span>Reason (optional)</span>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="repeat free trials" /></label>
          </div>
          {note && <span style={{ color: note.ok ? '#34d399' : '#fca5a5', marginTop: 6 }}>{note.text}</span>}
          {!bansOn && <span style={{ color: '#fbbf24', marginTop: 6 }}>All bans are switched OFF: nobody is being refused. The list below is kept.</span>}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button className="rv-btn glow" type="submit" disabled={!who.trim() || banM.isPending}>{banM.isPending ? 'Banning…' : 'Ban'}</button>
          <button type="button" className="rv-btn" disabled={switchM.isPending || !data}
            onClick={() => (bansOn ? window.confirm('Switch every ban off? Nobody will be refused until you switch them back on. The list is kept.') : true) && switchM.mutate(!bansOn)}>
            {bansOn ? 'Switch all bans off' : 'Switch bans back on'}</button>
        </div>
      </form>
      <div className="rv-invites">
        <div>
          <b>What's checked</b>
          <span>Sign-up refuses temporary inboxes ({data?.blocklist?.count?.toLocaleString?.() || '…'} domains, list updated {when(data?.blocklist?.updated_at)})
            and second spellings of a Gmail address. A free trial is refused when another account took the same trial from the same
            device or connection in the last 90 days. A referral reward is held when the new customer uses the referrer's device or
            connection: award it yourself in Referrals if it's genuine.</span>
        </div>
      </div>
      {isLoading ? <p>Loading…</p> : groups.length === 0 ? (
        <p className="rv-empty">Nothing yet. Groups appear as customers sign up, sign in and take trials.</p>
      ) : (
        <div className="rv-list">
          {groups.map((g, i) => (
            <div key={i} className={`rv-item${g.paid === 0 && g.trials > 1 ? ' st-pending' : ''}`}>
              <div className="rv-item-head">
                <b>{g.matches.map((m) => MATCH[m] || m).join(' · ')}</b>
                <span className="rv-empty" style={{ marginLeft: 'auto' }}>{g.trials} trial{g.trials === 1 ? '' : 's'} · ${g.paid.toFixed(2)} paid</span>
                {g.people.every((p) => bannedUsers.has(p.id))
                  ? <span className="rv-status private">Banned</span>
                  : <button type="button" className="rv-btn" disabled={banM.isPending} onClick={() => banGroup(g)}>Ban these accounts</button>}
              </div>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {g.people.map((p) => (
                  <li key={p.id} style={{ margin: '3px 0' }}>
                    <Link to={`/admin/customer/${p.id}`} style={{ color: '#22e6f2' }}>{p.name || '(no name)'}</Link>{' '}
                    {bannedUsers.has(p.id) && <span className="rv-status private">Banned</span>}{' '}
                    <span className="rv-empty">{p.email} · joined {when(p.created_at)} · {p.trials} trial{p.trials === 1 ? '' : 's'} · ${p.paid.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {bans.length > 0 && (
        <div style={{ marginTop: 22 }}>
          <h2 style={{ fontSize: 18, fontWeight: 800 }}>Bans</h2>
          <div className="rv-list">
            {bans.map((b) => (
              <div key={b.id} className="rv-item rv-item-head">
                <b>{KIND[b.kind] || b.kind}</b>
                <span className="rv-empty" style={{ wordBreak: 'break-all' }}>
                  {b.kind === 'user' ? (b.name || b.email || b.value) : b.kind === 'device' ? `${b.value.slice(0, 8)}…` : b.value}
                  {b.kind !== 'user' && b.user_id && <> · from <Link to={`/admin/customer/${b.user_id}`} style={{ color: '#22e6f2' }}>{b.name || b.email || 'account'}</Link></>}
                  {' '}· {b.reason || 'no reason'} · {b.by === 'auto' ? 'added automatically' : `by ${b.by || 'admin'}`} · {when(b.at)}
                  {b.expires_at && ` · expires ${when(b.expires_at)}`}
                  {' '}· refused {b.hits} time{b.hits === 1 ? '' : 's'}{b.last_hit_at ? ` (last ${when(b.last_hit_at)})` : ''}
                </span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  {b.kind === 'user' && <button type="button" className="rv-btn" disabled={unbanM.isPending}
                    onClick={() => window.confirm('Lift this account\'s ban and every IP and device banned because of it?') && unbanM.mutate({ user_id: b.value })}>Unban all</button>}
                  <button type="button" className="rv-btn" disabled={unbanM.isPending} onClick={() => unbanM.mutate({ id: b.id })}>Unban</button>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {data?.ban_log?.length > 0 && (
        <div style={{ marginTop: 22 }}>
          <h2 style={{ fontSize: 18, fontWeight: 800 }}>Recent ban changes</h2>
          <div className="rv-list">
            {data.ban_log.map((e) => (
              <div key={e.id} className="rv-item rv-item-head">
                <b>{logText(e)}</b>
                <span className="rv-empty">{when(e.at)} · by {e.by || 'admin'}{e.undone_at ? ` · undone ${when(e.undone_at)} by ${e.undone_by || 'admin'}` : ''}</span>
                {!e.undone_at && (
                  <button type="button" className="rv-btn" style={{ marginLeft: 'auto' }} disabled={undoM.isPending}
                    onClick={() => window.confirm(`Undo "${logText(e)}"?`) && undoM.mutate(e.id)}>Undo</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {(data?.trial_refusals?.length > 0 || data?.referral_holds?.length > 0) && (
        <div style={{ marginTop: 22 }}>
          <h2 style={{ fontSize: 18, fontWeight: 800 }}>Recently refused or held</h2>
          <div className="rv-list">
            {(data.trial_refusals || []).map((r, i) => (
              <div key={`t${i}`} className="rv-item">
                <b>Trial refused</b> <span className="rv-empty">{when(r.at)} · {r.product_name} · same {r.match} as </span>
                <Link to={`/admin/customer/${r.other_user_id}`} style={{ color: '#22e6f2' }}>another account</Link>{' '}
                <span className="rv-empty">· asked by </span><Link to={`/admin/customer/${r.user_id}`} style={{ color: '#22e6f2' }}>this customer</Link>
              </div>
            ))}
            {(data.referral_holds || []).map((r, i) => (
              <div key={`r${i}`} className="rv-item">
                <b>Referral reward held</b> <span className="rv-empty">{when(r.at)} · at {r.stage} · code {r.referred_by} · {r.reason} · </span>
                <Link to={`/admin/customer/${r.user_id}`} style={{ color: '#22e6f2' }}>customer</Link>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
