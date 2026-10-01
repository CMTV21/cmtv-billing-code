// CMTV local addition 2026-10-01: the admin's remembered devices for 2FA (backend: cmtv_trusted_devices.py), shown in the
// 2FA box in Admin > Settings when 2FA is on. Remove one, or all.
import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

const when = (d) => (d ? new Date(d).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '');

export default function RememberedDevices() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['cmtv-trusted-devices'], queryFn: async () => (await api.get('/api/cmtv/trusted-devices')).data });
  const devices = data?.devices || [];
  const refresh = () => qc.invalidateQueries({ queryKey: ['cmtv-trusted-devices'] });
  const remove = async (id) => {
    try { await api.post(`/api/cmtv/trusted-devices/${id}/revoke`); toast.success('Device removed: it will ask for the code next time'); refresh(); }
    catch (e) { toast.error(e.response?.data?.detail || "Couldn't remove it"); }
  };
  const removeAll = async () => {
    if (!window.confirm('Forget every remembered device? Each one will ask for the 2FA code at the next sign-in.')) return;
    try { await api.post('/api/cmtv/trusted-devices/revoke-all'); toast.success('All devices forgotten'); refresh(); }
    catch (e) { toast.error(e.response?.data?.detail || "Couldn't remove them"); }
  };
  return (
    <div className="mt-4 border-t border-green-200 dark:border-green-800 pt-4">
      <div className="flex items-center justify-between gap-3 mb-2">
        <h5 className="font-semibold text-sm text-green-900 dark:text-green-100">Remembered devices</h5>
        {devices.length > 1 && <button type="button" onClick={removeAll} className="text-xs underline text-red-600">Forget all</button>}
      </div>
      {!devices.length ? (
        <p className="text-sm text-green-700 dark:text-green-300">None. Tick "Remember this device" at the code step to skip it for {data?.days || 30} days.</p>
      ) : (
        <ul className="space-y-2">
          {devices.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="text-green-900 dark:text-green-100">
                <b>{d.label}</b> · last used {when(d.last_used_at)} · until {when(d.expires_at)}
              </span>
              <button type="button" onClick={() => remove(d.id)} className="px-3 py-1 rounded-md border border-red-300 text-red-600 text-xs">Remove</button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs mt-2 text-green-700 dark:text-green-300">Changing your password or turning 2FA off forgets every device.</p>
    </div>
  );
}
