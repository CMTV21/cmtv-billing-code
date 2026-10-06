// CMTV local addition 2026-10-06: /audiobooks/top, the New York Times bestseller lists (backend cmtv_booklists.py; the
// owner: ReadMeABook's "Popular" is Audible's own list, not real bestsellers). Each book: "Request it" opens the request
// site's search for that title. Tabs: Audio fiction / Audio nonfiction (NYT monthly audio lists), Fiction / Nonfiction (weekly).
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { usePageMeta } from '../../components/cmtv/CmtvSEO';
import '../../components/cmtv/cmtv-kb.css';

const chip = (on) => ({ flex: 'none', font: 'inherit', fontSize: 13.5, fontWeight: 700, borderRadius: 999, padding: '7px 12px', cursor: 'pointer',
  border: '1px solid #27345a', background: on ? '#22e6f2' : '#141d33', color: on ? '#07101f' : '#e9edf8' });

export default function TopAudiobooksPage() {
  usePageMeta({ title: 'Top audiobooks: New York Times bestsellers | CMTV', description: 'This month\'s New York Times audiobook bestsellers and this week\'s top fiction and nonfiction. Request any of them for CMTV Audiobooks.' });
  const { data, isLoading } = useQuery({ queryKey: ['cmtv-booklists'], queryFn: async () => (await api.get('/api/cmtv/booklists')).data, staleTime: 3600000 });
  const [tab, setTab] = useState(null);
  const lists = data?.lists || [];
  const cur = lists.find((l) => l.id === tab) || lists[0];
  const when = (d) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' }) : '');
  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12 }}>
        <h1 style={{ marginBottom: 4 }}>Top audiobooks 📚</h1>
        <p className="kb-lede" style={{ marginBottom: 12 }}>The New York Times bestsellers. Tap <b>Request it</b> and we'll add it to CMTV Audiobooks.</p>
        {isLoading ? <p className="kb-lede">Loading…</p> : !data?.ready ? <p className="kb-lede">The bestseller lists are coming soon.</p> : (
          <>
            <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 6, marginBottom: 6 }}>
              {lists.map((l) => <button key={l.id} type="button" style={chip(cur?.id === l.id)} onClick={() => setTab(l.id)}>{l.label}</button>)}
            </div>
            <p style={{ fontSize: 13, color: '#8391b5', margin: '0 0 10px' }}>
              {cur?.display_name} · {cur?.how === 'monthly' ? 'monthly list' : 'weekly list'}{cur?.published_date ? ` · ${when(cur.published_date)}` : ''}
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {(cur?.books || []).map((b) => (
                <div key={`${b.rank}-${b.title}`} style={{ display: 'flex', gap: 12, background: '#141d33', border: '1px solid #27345a', borderRadius: 14, padding: 10 }}>
                  <div style={{ position: 'relative', flex: 'none' }}>
                    {b.cover ? <img src={b.cover} alt="" width="72" height="108" loading="lazy" style={{ objectFit: 'cover', borderRadius: 6, display: 'block' }} />
                      : <div style={{ width: 72, height: 108, borderRadius: 6, background: '#0a1020' }} />}
                    <span style={{ position: 'absolute', top: -6, left: -6, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f',
                      fontWeight: 900, fontSize: 13, borderRadius: 999, minWidth: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{b.rank}</span>
                  </div>
                  <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                    <b style={{ fontSize: 16, lineHeight: 1.25 }}>{b.title}</b>
                    <span style={{ fontSize: 13.5, color: '#c7d2ee' }}>{b.author}</span>
                    {b.weeks > 1 && <span style={{ fontSize: 12, color: '#8391b5' }}>{b.weeks} {cur?.how === 'monthly' ? 'months' : 'weeks'} on the list</span>}
                    {b.description && <p style={{ margin: '4px 0 8px', fontSize: 13.5, color: '#9aa6c6', lineHeight: 1.45 }}>{b.description}</p>}
                    <a href={b.request} target="_blank" rel="noopener noreferrer" className="kb-btn glow" style={{ alignSelf: 'flex-start', marginTop: 'auto', fontSize: 13.5, padding: '6px 12px' }}>Request it</a>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        <div style={{ background: '#141d33', border: '1px solid #27345a', borderRadius: 14, marginTop: 14, padding: 14, fontSize: 14, color: '#c7d2ee' }}>
          <b style={{ color: '#e9edf8' }}>How requesting works:</b> sign in at requests.cmtv.info with your Audiobooks login, tap Request, and it shows up
          in your library when it's ready. Not a CMTV Audiobooks member yet? <Link to="/?tab=addons">Add it for $30 a year</Link>.
        </div>
      </article>
    </div>
  );
}
