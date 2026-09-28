// CMTV local addition 2026-09-28: "Telegram alerts" panel on the dashboard. Connect = a one-time link that opens
// @Cmtv_support_bot (POST /api/cmtv/telegram/link); the bot links the chat, and this panel notices within a few
// seconds. Then: renewal reminders and service notices on/off, Disconnect. Backend: cmtv_telegram_alerts.py.
import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';

function Toggle({ on, label, note, onChange, busy }) {
  return (
    <button type="button" className="ca-toggle ca-tg-toggle" aria-pressed={!!on} disabled={busy} onClick={() => onChange(!on)}>
      <span className="ca-switch" aria-hidden="true" />
      <span><b>{label}</b><small>{note}</small></span>
    </button>
  );
}

export default function TelegramAlerts() {
  const qc = useQueryClient();
  const [waiting, setWaiting] = useState(false);
  const [busy, setBusy] = useState(false);
  const until = useRef(0);
  const me = useQuery({
    queryKey: ['cmtv-telegram-me'], queryFn: async () => (await api.get('/api/cmtv/telegram/me')).data,
    refetchInterval: waiting ? 4000 : false, staleTime: 30000,
  });
  const d = me.data;

  useEffect(() => {
    if (waiting && d?.linked) { setWaiting(false); toast.success('Telegram connected. Alerts will arrive there.'); }
    if (waiting && Date.now() > until.current) setWaiting(false);
  }, [waiting, d]);

  const connect = async () => {
    // open the tab first (a click-started window isn't blocked), then point it at the one-time link
    const win = window.open('about:blank', '_blank');
    try {
      const { url } = (await api.post('/api/cmtv/telegram/link')).data;
      if (win) win.location.href = url; else window.location.href = url;
      until.current = Date.now() + 5 * 60 * 1000;
      setWaiting(true);
    } catch {
      if (win) win.close();
      toast.error('Could not start the connection. Try again.');
    }
  };
  const setPref = async (key, value) => {
    setBusy(true);
    try { qc.setQueryData(['cmtv-telegram-me'], (await api.post('/api/cmtv/telegram/prefs', { [key]: value })).data); }
    catch { toast.error('Could not save that. Try again.'); }
    finally { setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true);
    try { qc.setQueryData(['cmtv-telegram-me'], (await api.post('/api/cmtv/telegram/unlink')).data); toast.success('Telegram alerts are off.'); }
    catch { toast.error('Could not disconnect. Try again.'); }
    finally { setBusy(false); }
  };

  if (!d) return null;
  return (
    <div className="ca-panel ca-tg">
      <h2 className="ca-h2">Telegram alerts</h2>
      {!d.linked ? (
        <>
          <p>Get a heads-up <b>before a service ends</b> (with a one-tap Renew) and <b>service notices</b> if your server has an outage.</p>
          <div className="ca-help">
            <button type="button" className="ca-btn ca-glow" onClick={connect}>{waiting ? 'Waiting for Telegram…' : 'Connect Telegram'}</button>
          </div>
          {waiting && <p className="ca-tg-note">In Telegram, tap <b>Start</b>. This updates by itself once you're connected.</p>}
        </>
      ) : (
        <>
          <p>Connected{d.username ? <> as <b>@{d.username}</b></> : d.name ? <> as <b>{d.name}</b></> : ''}.</p>
          <div className="ca-tg-prefs">
            <Toggle on={d.prefs?.renewals} busy={busy} label="Renewal reminders" note="3 days and 1 day before a service ends" onChange={(v) => setPref('renewals', v)} />
            <Toggle on={d.prefs?.notices} busy={busy} label="Service notices" note="Outages and important updates" onChange={(v) => setPref('notices', v)} />
          </div>
          <button type="button" className="ca-linkbtn" onClick={disconnect} disabled={busy}>Disconnect Telegram</button>
        </>
      )}
    </div>
  );
}
