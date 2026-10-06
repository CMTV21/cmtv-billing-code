// CMTV local addition 2026-10-06: Admin > Notices "Top audiobooks (NYT)": the owner pastes the free NYT Books API key here
// (never shown again: only its last 4 characters). Backend cmtv_booklists.py.
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

export default function NytKeyBox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-nyt-admin'], queryFn: async () => (await api.get('/api/cmtv/booklists/admin')).data, refetchInterval: 20000 });
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/booklists/admin/key', { key });
      setKey(''); qc.invalidateQueries({ queryKey: ['cmtv-nyt-admin'] });
      toast.success('Key works. The lists will be ready in about a minute.');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not save the key.'); }
    setBusy(false);
  };
  const lists = data?.lists || {};
  return (
    <div className="rc-box" style={{ marginTop: 18 }}>
      <h2 style={{ margin: '0 0 4px' }}>Top audiobooks (New York Times)</h2>
      <p style={{ margin: '0 0 10px', opacity: 0.8 }}>Your free NYT Books API key powers the <a href="/audiobooks/top" style={{ color: '#22e6f2' }}>Top audiobooks</a> page.
        The key is stored on the server and never shown again.</p>
      <p style={{ margin: '0 0 8px' }}>{data?.has_key ? <>Key saved: <b>…{data.key_end}</b></> : 'No key saved yet.'}
        {Object.keys(lists).length > 0 && <> · lists: {Object.entries(lists).map(([k, n]) => `${k.replace('combined-print-and-e-book-', '')} ${n}`).join(', ')}</>}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="NYT Books API key"
          style={{ flex: 1, minWidth: 220, font: 'inherit', padding: '8px 10px', borderRadius: 10, border: '1px solid #27345a', background: '#0a1020', color: '#e9edf8' }} />
        <button type="button" disabled={busy || !key.trim()} onClick={save}
          style={{ font: 'inherit', fontWeight: 700, borderRadius: 10, padding: '8px 14px', border: 0, background: 'linear-gradient(135deg,#22e6f2,#8b5cf6)', color: '#07101f', cursor: 'pointer' }}>
          {busy ? 'Testing…' : 'Save & test'}
        </button>
      </div>
    </div>
  );
}
