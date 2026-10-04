// CMTV local addition 2026-10-04: Admin > Support inbox (backend cmtv_support_inbox.py). Website tickets and Telegram
// support-bot tickets in one list: tabs Needs a reply / Waiting on customer / Closed, search, the full conversation,
// the customer's account beside it, saved replies, and reply / close / reopen that go back where the ticket came from
// (website: email through billing's own ticket endpoints; Telegram: queued for the support bot, delivered within ~15 s).
// The developer's AdminTickets page is still at /admin/tickets-classic.
import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/cmtv-inbox.css';

const TABS = [['needs', 'Needs a reply'], ['waiting', 'Waiting on customer'], ['closed', 'Closed']];
const ago = (iso) => {
  if (!iso) return '';
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 60) return `${m}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
};
const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '');
const mins = (m) => (m == null ? '–' : m < 60 ? `${m} min` : m < 1440 ? `${(m / 60).toFixed(1)} h` : `${(m / 1440).toFixed(1)} days`);

export default function AdminSupportInbox() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get('tab') || 'needs');
  const [q, setQ] = useState('');
  const sel = params.get('t');   // "web:<id>" or "tg:<id>"
  const list = useQuery({ queryKey: ['inbox'], queryFn: async () => (await api.get('/api/cmtv/inbox/list')).data, refetchInterval: 20000 });
  const all = list.data?.tickets || [];
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return all.filter((t) => (s ? `${t.number} ${t.subject} ${t.customer} ${t.customer_sub} ${t.preview}`.toLowerCase().includes(s) : t.state === tab))
      .sort((a, b) => (tab === 'needs' && !s ? (a.updated_at > b.updated_at ? 1 : -1) : (a.updated_at < b.updated_at ? 1 : -1)));
  }, [all, tab, q]);
  const counts = useMemo(() => Object.fromEntries(TABS.map(([k]) => [k, all.filter((t) => t.state === k).length])), [all]);
  const open = (t) => setParams({ t: `${t.kind}:${t.id}`, tab });
  const st = list.data?.stats || {};

  return (
    <div className="ibx">
      <div className="ibx-head">
        <div>
          <h1>Support inbox</h1>
          <p>Website and Telegram tickets together. Replies go back where the ticket came from: email for website tickets, a
            Telegram message for Telegram ones. You can still answer in Admin Ops &gt; Tickets; both stay in step.</p>
        </div>
        <CannedEditor />
      </div>
      <div className="ibx-stats">
        <div className={st.needs ? 'hot' : ''}><b>{st.needs ?? '–'}</b><span>need a reply</span></div>
        <div><b>{st.oldest_needs ? ago(st.oldest_needs).replace(' ago', '') : '–'}</b><span>oldest waiting on you</span></div>
        <div><b>{mins(st.avg_first_reply_mins)}</b><span>average first reply (30 days)</span></div>
        <div><b>{st.closed_7d ?? '–'}</b><span>closed this week</span></div>
      </div>
      {list.data?.issues?.length > 0 && (
        <div className="ibx-issue">⚠️ Server problem right now: {list.data.issues.map((i) => i.service).join(', ')}. Expect related tickets.</div>
      )}
      {list.data && !st.telegram_db && <div className="ibx-issue">Telegram tickets can't be read right now (support bot database not found).</div>}
      <div className={`ibx-body${sel ? ' has-sel' : ''}`}>
        <div className="ibx-list">
          <div className="ibx-tabs">
            {TABS.map(([k, label]) => (
              <button type="button" key={k} className={tab === k && !q ? 'on' : ''} onClick={() => { setTab(k); setQ(''); }}>
                {label} <span>{counts[k] || 0}</span>
              </button>
            ))}
          </div>
          <input className="ibx-search" placeholder="Search all tickets: name, number, words…" value={q} onChange={(e) => setQ(e.target.value)} />
          {list.isLoading ? <p className="ibx-muted">Loading…</p> : shown.length === 0 ? (
            <p className="ibx-muted">{q ? 'No tickets match.' : tab === 'needs' ? 'Nothing waiting on you. 🎉' : 'Nothing here.'}</p>
          ) : shown.map((t) => (
            <button type="button" key={`${t.kind}:${t.id}`} className={`ibx-row${sel === `${t.kind}:${t.id}` ? ' sel' : ''}`} onClick={() => open(t)}>
              <div className="ibx-row-top">
                <span className={`ibx-src ${t.kind}`}>{t.kind === 'tg' ? 'Telegram' : 'Website'}</span>
                <b>{t.customer}</b>
                <small>{ago(t.updated_at)}</small>
              </div>
              <div className="ibx-row-subj">{t.number} · {t.subject}</div>
              <div className="ibx-row-prev">{t.last_from === 'us' ? 'You: ' : ''}{t.preview}</div>
              {t.pending && <div className="ibx-row-pend">sending to Telegram…</div>}
            </button>
          ))}
        </div>
        <div className="ibx-detail">
          {sel ? <TicketView key={sel} sel={sel} onBack={() => setParams({ tab })} onChanged={() => qc.invalidateQueries({ queryKey: ['inbox'] })} />
            : <p className="ibx-muted ibx-pick">Pick a ticket on the left.</p>}
        </div>
      </div>
    </div>
  );
}

function TicketView({ sel, onBack, onChanged }) {
  const [kind, id] = sel.split(':');
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [linkQ, setLinkQ] = useState('');
  const d = useQuery({
    queryKey: ['inbox-t', sel], queryFn: async () => (await api.get(`/api/cmtv/inbox/ticket/${kind}/${id}`)).data,
    refetchInterval: (q) => (q.state.data?.messages?.some((m) => m.pending) ? 5000 : 30000),
  });
  const canned = useQuery({ queryKey: ['inbox-canned'], queryFn: async () => (await api.get('/api/cmtv/inbox/canned')).data });
  const draftKey = `cmtv_inbox_draft_${sel}`;
  useEffect(() => { try { setText(localStorage.getItem(draftKey) || ''); } catch (e) { /* ignore */ } }, [draftKey]);
  useEffect(() => { try { if (text) localStorage.setItem(draftKey, text); else localStorage.removeItem(draftKey); } catch (e) { /* ignore */ } }, [text, draftKey]);

  const refresh = () => { qc.invalidateQueries({ queryKey: ['inbox-t', sel] }); onChanged(); };
  const t = d.data?.ticket;
  const closed = t?.state === 'closed';

  const send = async (close = false) => {
    if (!text.trim()) { toast.error('Write a reply first.'); return; }
    setBusy(true);
    try {
      if (kind === 'web') {
        await api.post(`/api/admin/tickets/${id}/reply`, { message: text.trim(), status: 'in_progress' });
        if (close) await api.put(`/api/admin/tickets/${id}/status`, { status: 'closed' });
        toast.success(close ? 'Reply emailed and ticket closed.' : 'Reply emailed to the customer.');
      } else {
        await api.post(`/api/cmtv/inbox/tg/${id}/reply`, { text: text.trim(), close });
        toast.success('Reply queued: the support bot sends it on Telegram within ~15 seconds.');
      }
      setText('');
      refresh();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not send that.'); }
    setBusy(false);
  };
  const act = async (action) => {
    setBusy(true);
    try {
      if (kind === 'web') {
        await api.put(`/api/admin/tickets/${id}/status`, { status: action === 'close' ? 'closed' : 'open' });
      } else {
        await api.post(`/api/cmtv/inbox/tg/${id}/action`, { action });
      }
      toast.success({ close: 'Closed.', reopen: 'Reopened.', need: 'Asked the customer for more info.' }[action]);
      refresh();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not do that.'); }
    setBusy(false);
  };
  const link = async (unlink = false) => {
    try {
      await api.post(`/api/cmtv/inbox/tg/${id}/link`, unlink ? { unlink: true } : { customer: linkQ });
      setLinkQ(''); refresh(); toast.success(unlink ? 'Unlinked.' : 'Linked to that customer.');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not link.'); }
  };

  if (d.isLoading) return <p className="ibx-muted">Loading…</p>;
  if (d.isError || !t) return <p className="ibx-muted">That ticket couldn't be loaded.</p>;
  const c = d.data.customer;
  return (
    <div className="ibx-view">
      <div className="ibx-convo">
        <button type="button" className="ibx-back" onClick={onBack}>← All tickets</button>
        <div className="ibx-title">
          <span className={`ibx-src ${t.kind}`}>{t.kind === 'tg' ? 'Telegram' : 'Website'}</span>
          <h2>{t.number} · {t.subject}</h2>
          <small>{t.customer} · {t.customer_sub} · opened {when(t.created_at)}{t.claimed_by ? ` · picked up by ${t.claimed_by}` : ''}</small>
          {d.data.facts && Object.keys(d.data.facts).length > 0 && (
            <div className="ibx-facts">{Object.entries(d.data.facts).map(([k, v]) => <span key={k}><i>{k.replace('_ref', '')}</i> {v}</span>)}</div>
          )}
        </div>
        <div className="ibx-msgs">
          {d.data.messages.map((m, i) => (
            m.from === 'event' ? <div key={i} className="ibx-event">{m.text} · {when(m.at)}</div> : (
              <div key={i} className={`ibx-msg ${m.from}${m.pending ? ' pending' : ''}`}>
                <div className="ibx-msg-text">{m.text}</div>
                <small>{m.from === 'us' ? (m.via ? `${m.via} · ` : 'CMTV Support · ') : ''}{m.pending ? 'sending…' : when(m.at)}</small>
              </div>
            )
          ))}
        </div>
        <div className="ibx-reply">
          <div className="ibx-reply-tools">
            <select value="" onChange={(e) => { const it = (canned.data?.items || [])[+e.target.value]; if (it) setText((x) => (x ? `${x}\n\n` : '') + it.text); }}>
              <option value="">Insert a saved reply…</option>
              {(canned.data?.items || []).map((it, i) => <option key={i} value={i}>{it.title}</option>)}
            </select>
            <span className="ibx-muted">{kind === 'tg' ? 'Sent on Telegram as “CMTV Support”' : 'Emailed to the customer'}</span>
          </div>
          <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder={closed ? 'Replying reopens the ticket…' : 'Write a reply…'} />
          <div className="ibx-actions">
            <button type="button" className="ibx-btn glow" disabled={busy} onClick={() => send(false)}>Send</button>
            {!closed && <button type="button" className="ibx-btn" disabled={busy} onClick={() => send(true)}>Send &amp; close</button>}
            {!closed && kind === 'tg' && <button type="button" className="ibx-btn" disabled={busy} onClick={() => act('need')}>Ask for more info</button>}
            {!closed ? <button type="button" className="ibx-btn" disabled={busy} onClick={() => act('close')}>Close</button>
              : <button type="button" className="ibx-btn" disabled={busy} onClick={() => act('reopen')}>Reopen</button>}
          </div>
        </div>
      </div>
      <aside className="ibx-side">
        {d.data.issues?.length > 0 && <div className="ibx-issue small">⚠️ Down right now: {d.data.issues.map((i) => i.service).join(', ')}</div>}
        {c ? (
          <>
            <div className="ibx-card">
              <b><Link to={`/admin/customer/${c.id}`}>{c.name || '(no name)'}</Link></b>
              <small>{c.email || (c.panel_username ? `TV login ${c.panel_username} · no email yet` : 'no email yet')}</small>
              <small>Paid ${c.paid_total.toFixed(2)} in total{c.credit ? ` · $${Number(c.credit).toFixed(2)} credit` : ''}{c.telegram ? ' · Telegram alerts on' : ''}</small>
              {d.data.match && <small className="ibx-muted">Matched by {d.data.match}{kind === 'tg' && d.data.match === 'linked by you' && (
                <> · <button type="button" className="ibx-link" onClick={() => link(true)}>unlink</button></>)}</small>}
            </div>
            <div className="ibx-card">
              <b>Services</b>
              {c.services.length === 0 ? <small className="ibx-muted">No current services.</small> : c.services.map((s, i) => (
                <div key={i} className={`ibx-svc st-${s.status}`}>
                  <span>{s.product}{s.trial ? ' (trial)' : ''}</span>
                  <small>{s.username ? `${s.username} · ` : ''}{s.status}{s.days_left != null ? ` · ${s.days_left < 0 ? `ended ${-s.days_left}d ago` : `${s.days_left}d left`}` : ''}{s.auto_renew ? ' · auto-renew' : ''}</small>
                </div>
              ))}
            </div>
            <div className="ibx-card">
              <b>Recent orders</b>
              {c.orders.length === 0 ? <small className="ibx-muted">None.</small> : c.orders.map((o) => (
                <small key={o.id}>{when(o.at)} · ${Number(o.total || 0).toFixed(2)} · {o.status} · {o.items}</small>
              ))}
            </div>
          </>
        ) : (
          <div className="ibx-card">
            <b>Customer not matched</b>
            <small className="ibx-muted">Link this Telegram person to a billing customer (email or TV line username). Their future tickets match too.</small>
            <div className="ibx-linkrow">
              <input value={linkQ} onChange={(e) => setLinkQ(e.target.value)} placeholder="email or line username" />
              <button type="button" className="ibx-btn" disabled={!linkQ.trim()} onClick={() => link(false)}>Link</button>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function CannedEditor() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const canned = useQuery({ queryKey: ['inbox-canned'], queryFn: async () => (await api.get('/api/cmtv/inbox/canned')).data });
  useEffect(() => { if (open) setItems(canned.data?.items || []); }, [open, canned.data]);
  const save = async () => {
    try { await api.post('/api/cmtv/inbox/canned', { items }); qc.invalidateQueries({ queryKey: ['inbox-canned'] }); setOpen(false); toast.success('Saved replies updated.'); }
    catch { toast.error('Could not save.'); }
  };
  return (
    <>
      <button type="button" className="ibx-btn" onClick={() => setOpen(true)}>Saved replies</button>
      {open && (
        <div className="ibx-modal" onClick={() => setOpen(false)}>
          <div className="ibx-modal-box" onClick={(e) => e.stopPropagation()}>
            <h2>Saved replies</h2>
            <p className="ibx-muted">Pick these in the reply box. You can edit the text before sending.</p>
            {items.map((it, i) => (
              <div key={i} className="ibx-canned">
                <input value={it.title} placeholder="Title" onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                <textarea rows={3} value={it.text} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
                <button type="button" className="ibx-link" onClick={() => setItems(items.filter((_, j) => j !== i))}>Remove</button>
              </div>
            ))}
            <div className="ibx-actions">
              <button type="button" className="ibx-btn" onClick={() => setItems([...items, { title: '', text: '' }])}>+ Add one</button>
              <button type="button" className="ibx-btn glow" onClick={save}>Save</button>
              <button type="button" className="ibx-btn" onClick={() => setOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
