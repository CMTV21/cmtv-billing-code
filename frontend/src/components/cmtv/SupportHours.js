// CMTV local addition 2026-10-05: support hours (8 am - 9 pm Eastern, set in Admin > Notices; backend cmtv_hours.py).
// Shown at checkout when e-Transfer is picked, in the new-ticket window, and on the Tickets and Status pages, so a customer
// who pays or writes in after hours knows when a person will see it.
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';

export function useHours() {
  const { data } = useQuery({
    queryKey: ['cmtv-hours'],
    queryFn: async () => (await api.get('/api/cmtv/hours')).data,
    staleTime: 60000, refetchInterval: 300000, retry: 1,
  });
  return data;
}

const away = (h) => (h.away && h.away_note ? ` (${h.away_note})` : '');

// One line for the e-Transfer choice at checkout ("Confirmed by hand · ready by 8 am Eastern tomorrow")
export function EmtHoursHint() {
  const h = useHours();
  if (!h) return null;
  return (
    <p className={`text-xs mt-0.5 ${h.open_now ? 'text-gray-500 dark:text-gray-400' : 'text-amber-700 dark:text-amber-300 font-medium'}`}>
      {h.open_now ? `Confirmed by hand, ${h.hours}` : `After hours: set up by about ${h.next_open_text}`}
    </p>
  );
}

// The e-Transfer instructions panel at checkout
export function EmtHoursNotice() {
  const h = useHours();
  if (!h) return null;
  if (h.open_now) {
    return (
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
        🕗 We confirm e-Transfers by hand, <b>{h.hours}</b>. We're online now, so you'll be set up soon after your e-Transfer arrives.
      </p>
    );
  }
  return (
    <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg p-4 mb-4 text-sm text-amber-900 dark:text-amber-200">
      <p className="font-semibold mb-1">🌙 It's after hours{away(h)}</p>
      <p>
        We confirm e-Transfers by hand, <b>{h.hours}</b>, so this order will be set up by about <b>{h.next_open_text}</b>.
      </p>
      <p className="mt-2">Want it working now? Pick <b>PayPal</b> above and you're set up instantly.</p>
    </div>
  );
}

// The new-ticket window
export function TicketHoursNotice() {
  const h = useHours();
  if (!h) return null;
  if (h.open_now) {
    return (
      <div className="mx-6 mt-4 rounded-lg border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 px-4 py-3 text-sm text-emerald-900 dark:text-emerald-200">
        🟢 We're online now. Support hours: <b>{h.hours}</b>.
      </div>
    );
  }
  return (
    <div className="mx-6 mt-4 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
      🌙 We're offline until <b>{h.next_open_text}</b>{away(h)}. Send your ticket now and we'll reply first thing.
      <span className="block mt-1 opacity-80">Support hours: {h.hours}.</span>
    </div>
  );
}

// A small badge for the Tickets and Status pages
export function HoursBadge({ style }) {
  const h = useHours();
  if (!h) return null;
  const on = h.open_now;
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '6px 12px', borderRadius: 999, fontSize: 14,
      border: `1px solid ${on ? 'rgba(52,211,153,.5)' : 'rgba(251,191,36,.55)'}`, background: on ? 'rgba(52,211,153,.12)' : 'rgba(251,191,36,.12)', ...style }}>
      <span style={{ width: 9, height: 9, borderRadius: 9, background: on ? '#34d399' : '#fbbf24', flex: 'none' }} />
      <b>{on ? 'Support is online now' : `Support is back at ${h.next_open_text}`}</b>
      <span style={{ opacity: 0.75 }}>· Hours {h.hours}</span>
    </div>
  );
}
