// CMTV local addition 2026-10-04: Admin > Notices "Sports schedule": the owner pastes their TheSportsDB key here (never
// shown again: only its last 4 characters), and sees how many games it found per league in the last 3 days.
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

export default function SportsKeyBox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-sports-admin'], queryFn: async () => (await api.get('/api/cmtv/sports/admin')).data });
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/sports/admin/key', { key });
      setKey(''); qc.invalidateQueries({ queryKey: ['cmtv-sports-admin'] }); toast.success('Key saved and tested.');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not save the key.'); }
    setBusy(false);
  };
  const probe = data?.probe || {};
  return (
    <div className="rc-box" style={{ marginTop: 18 }}>
      <h2 style={{ margin: '0 0 4px' }}>Sports schedule</h2>
      <p style={{ margin: '0 0 10px', opacity: 0.8 }}>Paste your TheSportsDB key to power the "What's on tonight" page and daily post.
        The key is stored on the server and never shown again.</p>
      <p style={{ margin: '0 0 8px' }}>{data?.has_key ? <>Key saved: <b>…{data.key_end}</b></> : 'No key saved yet.'}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="TheSportsDB API key"
          style={{ flex: 1, minWidth: 220, font: 'inherit', padding: '8px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' }} />
        <button type="button" className="rv-btn glow" disabled={busy || !key.trim()} onClick={save}
          style={{ font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f', cursor: 'pointer' }}>
          {busy ? 'Testing…' : 'Save & test'}
        </button>
      </div>
      {Object.keys(probe).length > 0 && (
        <div style={{ marginTop: 10, fontSize: 13.5 }}>
          Games this key found (last 3 days):{' '}
          {Object.entries(probe).map(([l, n]) => <span key={l} style={{ marginRight: 10 }}>{l} <b>{n}</b></span>)}
        </div>
      )}
    </div>
  );
}
