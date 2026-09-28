// CMTV local addition 2026-09-28: posts from the "CMTV Updates" Telegram channel on the website (GET /api/cmtv/updates,
// cmtv_updates.py; the support bot forwards them). variant:
//   "dashboard" - the latest post if there was news in the last 48 h, with its follow-ups
//   "tickets"   - the Support page: the last 7 days (or "no known issues")
//   "modal"     - the new-ticket form: "Known issues right now" (last 48 h), so people can skip writing in
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import './cmtv-updates.css';

function ago(iso) {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return mins <= 1 ? 'just now' : `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? 'yesterday' : `${d} days ago`;
}

function Text({ text }) {
  const parts = String(text || '').split(/(https?:\/\/[^\s)]+[^\s).,])/g);
  return (
    <p className="cu-text">
      {parts.map((p, i) => (/^https?:\/\//.test(p)
        ? <a key={i} href={p} target="_blank" rel="noopener noreferrer">{p.replace(/^https?:\/\//, '')}</a>
        : <React.Fragment key={i}>{p}</React.Fragment>))}
    </p>
  );
}

function Post({ item, open }) {
  const [more, setMore] = useState(open);
  const replies = item.replies || [];
  const shown = more ? replies : replies.slice(-1);
  return (
    <article className={`cu-post${item.recent ? ' recent' : ''}`}>
      <header><b>📢 CMTV update</b><time dateTime={item.at}>{ago(item.at)}</time></header>
      <Text text={item.text} />
      {shown.map((r) => (
        <div className="cu-reply" key={r.id}>
          <span className="cu-tag">Update · {ago(r.at)}</span>
          <Text text={r.text} />
        </div>
      ))}
      {!more && replies.length > 1 && (
        <button type="button" className="cu-more" onClick={() => setMore(true)}>Show {replies.length - 1} earlier update{replies.length > 2 ? 's' : ''}</button>
      )}
    </article>
  );
}

export default function CmtvUpdates({ variant = 'dashboard' }) {
  const { data } = useQuery({
    queryKey: ['cmtv-updates'], queryFn: async () => (await api.get('/api/cmtv/updates')).data,
    staleTime: 60000, refetchInterval: 120000,
  });
  const items = data?.items || [];
  const recent = items.filter((x) => x.recent);

  if (variant === 'dashboard') {
    if (!recent.length) return null;
    return <section className="cu cu-dash" aria-label="Latest from CMTV"><Post item={recent[0]} open={false} /></section>;
  }
  if (variant === 'modal') {
    if (!recent.length) return null;
    return (
      <section className="cu cu-modal" aria-label="Known issues right now">
        <h3>Known issues right now</h3>
        <p className="cu-lede">If your problem is one of these, there's no need to open a ticket. We're already on it and post here when it's fixed.</p>
        {recent.slice(0, 2).map((x) => <Post key={x.id} item={x} open={false} />)}
      </section>
    );
  }
  return (
    <section className="cu cu-tickets" aria-label="Latest from CMTV">
      <h2>Latest from CMTV</h2>
      {items.length ? (
        <>
          <p className="cu-lede">Check here first: if something's down, we've usually posted about it already.</p>
          {items.slice(0, 4).map((x) => <Post key={x.id} item={x} open={false} />)}
        </>
      ) : <p className="cu-lede">✅ No known issues right now.</p>}
    </section>
  );
}
