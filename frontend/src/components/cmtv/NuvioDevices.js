// CMTV local addition 2026-09-29: "Devices" box on a Nuvio service card (dashboard). Lists the TVs/phones signed in to
// the customer's Nuvio account (max 4) and lets them sign one out to free a slot. Backend: cmtv_nuvio.py /mine/...
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const ago = (d) => {
  if (!d) return '';
  const m = Math.round((Date.now() - new Date(d).getTime()) / 60000);
  if (m < 2) return 'in use now';
  if (m < 60) return `used ${m} min ago`;
  if (m < 48 * 60) return `used ${Math.round(m / 60)} h ago`;
  return `used ${Math.round(m / 1440)} days ago`;
};

export default function NuvioDevices({ username }) {
  const { data, refetch, isLoading, isError } = useQuery({
    queryKey: ['nuvio-my-devices', username],
    queryFn: async () => (await api.get(`/api/cmtv/nuvio/mine/${encodeURIComponent(username)}/devices`)).data,
    staleTime: 30000,
  });
  const signOut = async (d) => {
    if (!window.confirm(`Sign out ${d.device || d.app || 'this device'}? It will need your username and password again.`)) return;
    try { await api.post(`/api/cmtv/nuvio/mine/${encodeURIComponent(username)}/devices/sign-out`, { session_id: d.session_id }); toast.success('Signed out'); refetch(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'That did not work'); }
  };
  if (isLoading || isError || !data) return null;
  const devs = data.devices || [];
  return (
    <div className="ca-field" style={{ marginTop: 10 }}>
      <label>Devices · {data.in_use} of {data.max_devices} in use</label>
      {devs.length === 0 ? (
        <div className="val" style={{ color: 'var(--muted)' }}>Not signed in anywhere yet.</div>
      ) : devs.map((d) => (
        <div className="val" key={d.session_id} style={{ justifyContent: 'space-between', opacity: d.counts ? 1 : 0.6 }}>
          <span>
            <b>{d.device || d.app || 'Device'}</b>
            <small style={{ color: 'var(--muted)', marginLeft: 6 }}>{[d.platform, ago(d.last_used_at)].filter(Boolean).join(' · ')}</small>
          </span>
          <button type="button" className="ca-icon" onClick={() => signOut(d)}>Sign out</button>
        </div>
      ))}
      {data.in_use >= data.max_devices && (
        <small style={{ display: 'block', color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
          All {data.max_devices} slots are in use. Sign out a device you no longer use to add a new one.</small>
      )}
    </div>
  );
}
