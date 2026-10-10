// CMTV local addition 2026-10-04: Admin > Customers > Possible duplicates (backend cmtv_dupes.py). Groups of customer
// accounts that share a device, an internet connection or a Gmail inbox (dots / +tags), with their trials and spend,
// plus the trials and referral rewards the duplicate checks refused or held. Read-only apart from "allow this IP".
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../../api/api';
import '../../components/cmtv/cmtv-reviews.css';

const MATCH = { device: 'Same device', ip: 'Same internet connection', inbox: 'Same Gmail inbox' };
const when = (v) => (v ? new Date(v).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '–');

// 2026-10-10 (owner): suspected duplicates put a connection + browser on hold (no new sign-ups / free trials) until lifted here
function Holds({ blocks }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState('');
  const act = async (id, action) => {
    if (action === 'clear' && !window.confirm('Lift the hold? New sign-ups and free trials from that connection and browser will work again.')) return;
    setBusy(id + action);
    try {
      await api.post(`/api/cmtv/dupes/admin/blocks/${id}`, { action });
      await qc.invalidateQueries({ queryKey: ['cmtv-dupes'] });
      qc.invalidateQueries({ queryKey: ['cmtv-admin-overview'] });
    } catch (e) { window.alert(e?.response?.data?.detail || 'Could not save that.'); }
    setBusy('');
  };
  if (!blocks.length) return null;
  const who = (p) => <><Link to={`/admin/customer/${p.id}`} style={{ color: '#22e6f2' }}>{p.name || '(no name)'}</Link> <span className="rv-empty">{p.email}</span></>;
  return (
    <div style={{ margin: '0 0 22px' }}>
      <h2 style={{ fontSize: 18, fontWeight: 800 }}>On hold</h2>
      <p className="rv-empty" style={{ margin: '0 0 10px' }}>No new sign-ups or free trials from these connections and browsers until you decide. Signing in and paying still work.</p>
      <div className="rv-list">
        {blocks.map((b) => (
          <div key={b.id} className={`rv-item${b.status === 'blocked' && !b.reviewed ? ' st-pending' : ''}`}>
            <div className="rv-item-head">
              <b>{b.status === 'cleared' ? 'Hold lifted' : b.reviewed ? 'Kept on hold' : 'Needs you'}</b>
              <span className="rv-empty" style={{ marginLeft: 'auto' }}>{when(b.created_at)} · {b.what} · same {b.match}{b.hits ? ` · ${b.hits} blocked attempt${b.hits === 1 ? '' : 's'}` : ''}</span>
            </div>
            <div style={{ margin: '8px 0 0' }}>{who(b.person)}</div>
            <div className="rv-empty" style={{ margin: '4px 0 0' }}>Same {b.match} as:</div>
            <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>{b.others.map((p) => <li key={p.id} style={{ margin: '2px 0' }}>{who(p)}</li>)}</ul>
            {b.status === 'blocked' && (
              <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                <button type="button" className="btn sm" disabled={!!busy} onClick={() => act(b.id, 'clear')}>It's fine: lift the hold</button>
                {!b.reviewed && <button type="button" className="btn sm" disabled={!!busy} onClick={() => act(b.id, 'keep')}>Keep blocked</button>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AdminDuplicatesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['cmtv-dupes'], queryFn: async () => (await api.get('/api/cmtv/dupes/admin/groups')).data,
  });
  const groups = data?.groups || [];
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
        <div><b>{data?.referral_holds?.length ?? '–'}</b><span>referral rewards held</span></div>
      </div>
      <div className="rv-invites">
        <div>
          <b>What's checked</b>
          <span>Sign-up refuses temporary inboxes ({data?.blocklist?.count?.toLocaleString?.() || '…'} domains, list updated {when(data?.blocklist?.updated_at)})
            and second spellings of a Gmail address. A free trial is refused when another account took the same trial from the same
            device or connection in the last 90 days (or from any browser or connection this account used before). A new account on the
            same browser or connection as another account, or a re-used trial, sends a Critical alert and puts that connection and browser
            on hold (see On hold above). A referral reward is held when the new customer uses the referrer's device or
            connection: award it yourself in Referrals if it's genuine.</span>
        </div>
      </div>
      <Holds blocks={data?.blocks || []} />
      {isLoading ? <p>Loading…</p> : groups.length === 0 ? (
        <p className="rv-empty">Nothing yet. Groups appear as customers sign up, sign in and take trials.</p>
      ) : (
        <div className="rv-list">
          {groups.map((g, i) => (
            <div key={i} className={`rv-item${g.paid === 0 && g.trials > 1 ? ' st-pending' : ''}`}>
              <div className="rv-item-head">
                <b>{g.matches.map((m) => MATCH[m] || m).join(' · ')}</b>
                <span className="rv-empty" style={{ marginLeft: 'auto' }}>{g.trials} trial{g.trials === 1 ? '' : 's'} · ${g.paid.toFixed(2)} paid</span>
              </div>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {g.people.map((p) => (
                  <li key={p.id} style={{ margin: '3px 0' }}>
                    <Link to={`/admin/customer/${p.id}`} style={{ color: '#22e6f2' }}>{p.name || '(no name)'}</Link>{' '}
                    <span className="rv-empty">{p.email} · joined {when(p.created_at)} · {p.trials} trial{p.trials === 1 ? '' : 's'} · ${p.paid.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
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
