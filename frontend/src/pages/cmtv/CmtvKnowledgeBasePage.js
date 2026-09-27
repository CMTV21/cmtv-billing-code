// CMTV local addition 2026-09-27: the customer help centre on /knowledge-base ("Guides"). Replaces the developer's
// KnowledgeBasePage (still in the code, unused). Articles come from the same kb_articles (GET /api/kb); admins also see
// unpublished drafts (GET /api/admin/kb), marked "Draft". Light markup: "## " heading, "1. " steps, "- " bullets,
// "**bold**", "> Tip:" / "> Important:" callouts, [image:url] / [video:url], bare https:// links.
import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import '../../components/cmtv/cmtv-kb.css';

const CATEGORY_ORDER = ['Getting started', 'Set up your device', 'Add-ons', 'Your account', 'Troubleshooting', 'Contact us'];
const DEVICES = [
  { key: 'firestick', label: 'Firestick & Android TV', article: 'cmtv-firestick-android-tv', icon: '📺' },
  { key: 'onn', label: 'ONN 4K & Google TV', article: 'cmtv-onn-4k-google-tv', icon: '📦' },
  { key: 'android', label: 'Android phone or tablet', article: 'cmtv-cmtvghost', icon: '📱' },
  { key: 'iphone', label: 'iPhone or iPad', article: 'cmtv-iphone-ipad', icon: '🍎' },
  { key: 'pc', label: 'PC or Mac', article: 'cmtv-web-player', icon: '💻' },
];

// ---- tiny, safe renderer (React elements only, no HTML injection) ----
function inline(text, keyBase) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|https?:\/\/[^\s)]+[^\s).,])/g;
  let last = 0, m, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith('**')) out.push(<b key={`${keyBase}-${i++}`}>{t.slice(2, -2)}</b>);
    else out.push(<a key={`${keyBase}-${i++}`} href={t} target="_blank" rel="noopener noreferrer">{t.replace(/^https?:\/\//, '')}</a>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function renderContent(content) {
  const lines = String(content || '').replace(/\r/g, '').split('\n');
  const blocks = [];
  let list = null;
  const flush = () => { if (list) { blocks.push(list); list = null; } };
  lines.forEach((raw) => {
    const line = raw.trim();
    const media = line.match(/^\[(image|video):(.+)\]$/);
    const step = line.match(/^(\d+)[.)]\s*(.+)$/);
    const bullet = line.match(/^[-•]\s*(.+)$/);
    if (!line) { flush(); return; }
    if (media) { flush(); blocks.push({ type: media[1], src: media[2].trim() }); return; }
    if (line.startsWith('## ')) { flush(); blocks.push({ type: 'h', text: line.slice(3) }); return; }
    if (line.startsWith('> ')) {
      flush();
      const body = line.slice(2);
      const kind = /^important:/i.test(body) ? 'warn' : 'tip';
      blocks.push({ type: 'callout', kind, text: body.replace(/^(tip|important):\s*/i, '') });
      return;
    }
    if (step) {
      if (!list || list.type !== 'ol') { flush(); list = { type: 'ol', start: Number(step[1]), items: [] }; }
      list.items.push({ text: step[2], sub: [] });
      return;
    }
    if (bullet) {
      // bullets right under a numbered step belong to that step (e.g. "4. Enter the details:" then "- Username")
      if (list && list.type === 'ol' && list.items.length) { list.items[list.items.length - 1].sub.push(bullet[1]); return; }
      if (!list || list.type !== 'ul') { flush(); list = { type: 'ul', items: [] }; }
      list.items.push({ text: bullet[1], sub: [] });
      return;
    }
    flush();
    blocks.push({ type: 'p', text: line });
  });
  flush();
  return blocks.map((b, i) => {
    if (b.type === 'h') return <h2 key={i}>{inline(b.text, i)}</h2>;
    if (b.type === 'p') return <p key={i}>{inline(b.text, i)}</p>;
    if (b.type === 'image') return <img key={i} src={b.src} alt="" loading="lazy" />;
    if (b.type === 'video') return <video key={i} src={b.src} controls />;
    if (b.type === 'callout') return <div key={i} className={`kb-callout ${b.kind}`}><b>{b.kind === 'warn' ? 'Important' : 'Tip'}</b><span>{inline(b.text, i)}</span></div>;
    const Tag = b.type === 'ol' ? 'ol' : 'ul';
    return (
      <Tag key={i} start={b.start}>
        {b.items.map((it, j) => (
          <li key={j}>{inline(it.text, `${i}-${j}`)}
            {it.sub.length > 0 && <ul>{it.sub.map((s, k) => <li key={k}>{inline(s, `${i}-${j}-${k}`)}</li>)}</ul>}
          </li>
        ))}
      </Tag>
    );
  });
}

const summaryOf = (a) => a.cmtv_summary || String(a.content || '').replace(/\[(image|video):[^\]]+\]/g, '').replace(/[#*>]/g, '').trim().split('\n')[0].slice(0, 140);

export default function CmtvKnowledgeBasePage() {
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';
  const [params, setParams] = useSearchParams();
  const openId = params.get('a');
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const { data: published, isLoading } = useQuery({ queryKey: ['kb-public'], queryFn: async () => (await api.get('/api/kb')).data });
  const { data: all } = useQuery({ queryKey: ['kb-admin'], queryFn: async () => (await api.get('/api/admin/kb')).data, enabled: isAdmin });

  const articles = useMemo(() => {
    const list = isAdmin && all ? all.filter((a) => a.is_published || String(a.id).startsWith('cmtv-')) : (published || []);
    // while the new articles are drafts, admins preview them instead of the old ones they replace
    const hasNew = list.some((a) => String(a.id).startsWith('cmtv-'));
    return list.filter((a) => !(isAdmin && hasNew && !String(a.id).startsWith('cmtv-') && ['Knowledge Base', 'Using the Webplayer'].includes(a.title)))
      .sort((a, b) => (a.display_order ?? 999) - (b.display_order ?? 999));
  }, [published, all, isAdmin]);
  const byId = useMemo(() => Object.fromEntries(articles.map((a) => [a.id, a])), [articles]);
  const cats = useMemo(() => {
    const present = [...new Set(articles.map((a) => a.category || 'General'))];
    return [...CATEGORY_ORDER.filter((c) => present.includes(c)), ...present.filter((c) => !CATEGORY_ORDER.includes(c))];
  }, [articles]);
  const term = q.trim().toLowerCase();
  const shown = articles.filter((a) => (!cat || (a.category || 'General') === cat)
    && (!term || `${a.title} ${summaryOf(a)} ${a.content}`.toLowerCase().includes(term)));
  const open = openId ? byId[openId] : null;
  const go = (id) => { setParams(id ? { a: id } : {}); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const drafts = isAdmin && articles.some((a) => !a.is_published);

  if (open) {
    const siblings = articles.filter((a) => a.category === open.category && a.id !== open.id).slice(0, 4);
    return (
      <div className="cmtv-kb">
        <nav className="kb-crumbs" aria-label="Breadcrumb">
          <button type="button" onClick={() => go(null)}>Guides</button><span>›</span><span>{open.category || 'General'}</span>
        </nav>
        <article className="kb-article">
          <h1>{open.title}{!open.is_published && <span className="kb-draft">Draft</span>}</h1>
          {open.cmtv_summary && <p className="kb-lede">{open.cmtv_summary}</p>}
          <div className="kb-body">{renderContent(open.content)}</div>
        </article>
        <div className="kb-help">
          <div><b>Still stuck?</b><span>Open a ticket or message us on Telegram, and we'll sort it out.</span></div>
          <Link className="kb-btn glow" to="/tickets">Contact support</Link>
          <Link className="kb-btn" to="/downloads">Downloads</Link>
        </div>
        {siblings.length > 0 && (
          <section className="kb-related">
            <h2>More in {open.category}</h2>
            <div className="kb-grid">{siblings.map((a) => (
              <button type="button" key={a.id} className="kb-card" onClick={() => go(a.id)}><b>{a.title}</b><span>{summaryOf(a)}</span></button>
            ))}</div>
          </section>
        )}
      </div>
    );
  }

  const deviceTiles = DEVICES.filter((dv) => byId[dv.article]);
  return (
    <div className="cmtv-kb">
      <section className="kb-hero">
        <h1>How can we help?</h1>
        <p>Setup guides, fixes and answers about your account.</p>
        <label className="kb-search">
          <Search size={18} aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search, e.g. buffering, Firestick, renew" aria-label="Search the guides" />
        </label>
        {drafts && <p className="kb-admin-note">Admin preview: articles marked Draft aren't visible to customers yet.</p>}
      </section>

      {!term && !cat && deviceTiles.length > 0 && (
        <section className="kb-devices" aria-label="Set up your device">
          <h2>What are you watching on?</h2>
          <div className="kb-device-row">
            {deviceTiles.map((dv) => (
              <button type="button" key={dv.key} className="kb-device" onClick={() => go(dv.article)}>
                <span className="kb-device-icon" aria-hidden="true">{dv.icon}</span><b>{dv.label}</b>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="kb-chips" role="group" aria-label="Categories">
        <button type="button" className={!cat ? 'on' : ''} aria-pressed={!cat} onClick={() => setCat('')}>All</button>
        {cats.map((c) => <button type="button" key={c} className={cat === c ? 'on' : ''} aria-pressed={cat === c} onClick={() => setCat(c)}>{c}</button>)}
      </div>

      {isLoading && !articles.length ? <p className="kb-empty">Loading guides…</p> : shown.length === 0 ? (
        <p className="kb-empty">No guides match "{q}". Try another word, or <Link to="/tickets">ask us</Link>.</p>
      ) : (
        (cat ? [cat] : cats).map((c) => {
          const items = shown.filter((a) => (a.category || 'General') === c);
          if (!items.length) return null;
          return (
            <section key={c} className="kb-section">
              <h2>{c}</h2>
              <div className="kb-grid">{items.map((a) => (
                <button type="button" key={a.id} className="kb-card" onClick={() => go(a.id)}>
                  <b>{a.title}{!a.is_published && <span className="kb-draft">Draft</span>}</b><span>{summaryOf(a)}</span>
                </button>
              ))}</div>
            </section>
          );
        })
      )}
    </div>
  );
}
