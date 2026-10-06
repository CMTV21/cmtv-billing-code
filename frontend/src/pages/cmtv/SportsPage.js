// CMTV local addition 2026-10-05: /sports "What's on tonight" (backend cmtv_sports.py, the owner's TheSportsDB key).
// Today / Tomorrow, league chips, a card per game (Eastern time, logos, live / final score), and a trial button.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { usePageMeta } from '../../components/cmtv/CmtvSEO';
import '../../components/cmtv/cmtv-kb.css';

const card = { background: '#141d33', border: '1px solid #27345a', borderRadius: 14, padding: '10px 12px' };
const chip = (on) => ({ flex: 'none', font: 'inherit', fontSize: 13.5, fontWeight: 700, borderRadius: 999, padding: '7px 12px', cursor: 'pointer',
  border: '1px solid #27345a', background: on ? '#22e6f2' : '#141d33', color: on ? '#07101f' : '#e9edf8' });

// 2026-10-06: one team per line (full names fit on a phone), score on the right
function Team({ name, badge, score, win }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
      {badge ? <img src={`${badge}/tiny`} alt="" width="26" height="26" loading="lazy" style={{ flex: 'none', objectFit: 'contain' }}
        onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} /> : <span style={{ width: 26, flex: 'none' }} />}
      <span style={{ fontWeight: 700, flex: 1, minWidth: 0, lineHeight: 1.25 }}>{name}</span>
      {score != null && <b style={{ flex: 'none', fontSize: 17, color: win ? '#e9edf8' : '#8391b5' }}>{score}</b>}
    </div>
  );
}

export default function SportsPage() {
  usePageMeta({ title: "What's on tonight: sports schedule | CMTV", description: 'Tonight\'s NHL, NFL, NBA, MLB, CFL, soccer, UFC and F1 games in Eastern time. Watch them all on CMTV.' });
  const [day, setDay] = useState('today');
  const [league, setLeague] = useState('all');
  const { data, isLoading } = useQuery({ queryKey: ['cmtv-sports', day], queryFn: async () => (await api.get('/api/cmtv/sports/schedule', { params: { day } })).data,
    staleTime: 300000, refetchInterval: day === 'today' ? 300000 : false });
  const leagues = data?.leagues || [];
  const shown = league === 'all' ? leagues : leagues.filter((l) => l.name === league);
  const total = leagues.reduce((n, l) => n + l.games.length, 0);
  const dateText = data?.date ? new Date(`${data.date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' }) : '';
  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12 }}>
        <h1 style={{ marginBottom: 4 }}>What's on {day === 'today' ? 'tonight' : 'tomorrow'} 🏟️</h1>
        <p className="kb-lede" style={{ marginBottom: 12 }}>{dateText}{total ? ` · ${total} game${total === 1 ? '' : 's'}` : ''} · times are Eastern</p>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          {[['today', 'Today'], ['tomorrow', 'Tomorrow']].map(([k, l]) => (
            <button key={k} type="button" style={chip(day === k)} onClick={() => { setDay(k); setLeague('all'); }}>{l}</button>
          ))}
        </div>
        {leagues.length > 1 && (
          <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 6, marginBottom: 8 }}>
            <button type="button" style={chip(league === 'all')} onClick={() => setLeague('all')}>All</button>
            {leagues.map((l) => <button key={l.name} type="button" style={chip(league === l.name)} onClick={() => setLeague(l.name)}>{l.emoji} {l.name} · {l.games.length}</button>)}
          </div>
        )}
        {isLoading ? <p className="kb-lede">Loading the schedule…</p>
          : data && data.ready === false ? <p className="kb-lede">The schedule is coming soon.</p>
          : shown.length === 0 ? <p className="kb-lede">No big games {day === 'today' ? 'today' : 'tomorrow'} in the leagues we follow.</p>
          : shown.map((l) => (
            <section key={l.name} style={{ marginBottom: 18 }}>
              <h2 style={{ fontSize: 18, margin: '6px 0 8px' }}>{l.emoji} {l.name}</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {l.games.map((g) => (
                  <div key={g.id || g.start + g.event} style={card}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6, color: '#8391b5' }}>
                      <span style={{ fontWeight: 800, color: g.status === 'live' ? '#fca5a5' : '#c7d2ee' }}>
                        {g.status === 'live' ? '● LIVE' : g.status === 'final' ? 'Final' : g.time}</span>
                      {g.tv && <span>{g.tv}</span>}
                    </div>
                    {g.home && g.away ? (() => {
                      const [a, h] = g.score ? g.score.split('–').map(Number) : [null, null];
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          <Team name={g.away} badge={g.away_badge} score={g.score ? a : null} win={a > h} />
                          <Team name={`@ ${g.home}`} badge={g.home_badge} score={g.score ? h : null} win={h > a} />
                        </div>
                      );
                    })() : <b>{g.event}</b>}
                  </div>
                ))}
              </div>
            </section>
          ))}
        <div style={{ ...card, marginTop: 10, textAlign: 'center', padding: 16 }}>
          <b style={{ fontSize: 16 }}>Watch every game on CMTV</b>
          <p style={{ margin: '4px 0 10px', color: '#c7d2ee', fontSize: 14 }}>All the sports channels, on your TV, phone or computer.</p>
          <Link className="kb-btn glow" to="/?tab=trials">Try it free</Link>
        </div>
      </article>
    </div>
  );
}
