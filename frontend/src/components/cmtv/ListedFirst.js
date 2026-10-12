// CMTV local addition 2026-10-12 (the owner: customers pick, Canada First by default): Imperium "listed first" =
// which country's channel groups come first in the playlist (the panel's category profiles; backend cmtv_listed_first.py).
//   ListedFirstSelect  checkout, new Imperium lines: value = profile id (undefined = the default, Canada First)
//   ListedFirstControl dashboard, an existing Imperium line: reads the line's current choice from the panel, saves at once
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../../api/api';

export function useListedFirstOptions() {
  const { data } = useQuery({
    queryKey: ['cmtv-listed-first'],
    queryFn: async () => (await api.get('/api/cmtv/imperium/listed-first')).data,
    staleTime: 3600000,
  });
  return data || { options: [], default_id: 0 };
}

const HELP = 'Which country\'s channels appear at the top of your channel list. You can change it any time on your dashboard.';

export function ListedFirstSelect({ value, onChange }) {
  const { options, default_id: def } = useListedFirstOptions();
  if (!options.length) return null;
  const current = value === undefined || value === null ? def : value;
  return (
    <label className="block">
      <span className="text-sm font-semibold text-gray-900 dark:text-white">Channels listed first</span>
      <select className="mt-1 block w-full sm:w-72 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white p-2"
        value={current} onChange={(e) => onChange(Number(e.target.value))}>
        {options.map((o) => <option key={o.id} value={o.id}>{o.name}{o.id === def ? ' (recommended)' : ''}</option>)}
      </select>
      <span className="block text-xs text-gray-500 dark:text-gray-400 mt-1">{HELP}</span>
    </label>
  );
}

export function ListedFirstControl({ service }) {
  const qc = useQueryClient();
  const id = service.id || service._id;
  const key = ['cmtv-listed-first-line', id];
  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get(`/api/cmtv/imperium/listed-first/${id}`)).data,
    staleTime: 300000,
    retry: 1,
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  if (isLoading || !data || !(data.options || []).length) return null;
  const change = async (e) => {
    const pid = Number(e.target.value);
    setBusy(true); setMsg('');
    try {
      const r = (await api.post(`/api/cmtv/imperium/listed-first/${id}`, { profile_id: pid })).data;
      qc.setQueryData(key, { ...data, id: r.id, name: r.name });
      setMsg('Saved. Your app shows the new order next time it refreshes its channel list (or restart the app).');
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'That didn\'t save. Please try again in a minute.');
    } finally { setBusy(false); }
  };
  return (
    <div className="ca-field">
      <label htmlFor={`lf-${id}`}>Channels listed first</label>
      <div className="val">
        <select id={`lf-${id}`} value={data.id} onChange={change} disabled={busy}
          style={{ background: 'transparent', color: 'inherit', border: '1px solid var(--line, #334)', borderRadius: 8, padding: '6px 8px', font: 'inherit' }}>
          {data.options.map((o) => <option key={o.id} value={o.id} style={{ color: '#111' }}>{o.name}</option>)}
        </select>
      </div>
      <small style={{ display: 'block', color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>{msg || 'Which country\'s channels appear at the top of your list.'}</small>
    </div>
  );
}
