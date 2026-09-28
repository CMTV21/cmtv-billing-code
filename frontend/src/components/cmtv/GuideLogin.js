// CMTV local addition 2026-09-28: "Your details" on the setup guides. A signed-in customer sees the login for the guide
// they're reading (TV guides -> their TV lines; Stremio / CMTVpn / Audiobooks guides -> that add-on), with copy buttons,
// the server to pick in the app (and its address for apps that ask for one), a QR code that opens this guide on a phone
// (the page link only, never the login), and "Email me these steps" (POST /api/cmtv/kb/email-guide, cmtv_kb_email.py).
// Visitors who aren't signed in get a "sign in to see your login here" line instead.
import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { QRCodeSVG } from 'qrcode.react';
import { toast } from 'sonner';
import api from '../../api/api';

export const TV_GUIDES = new Set(['cmtv-firestick-android-tv', 'cmtv-onn-4k-google-tv', 'cmtv-cmtvghost', 'cmtv-iphone-ipad',
  'cmtv-web-player', 'cmtv-find-your-login', 'cmtv-login-problems', 'cmtv-channels-guide-movies', 'cmtv-getting-started']);
export const ADDON_GUIDES = { 'cmtv-stremio': 'nuvio', 'cmtv-cmtvpn': 'vpn', 'cmtv-audiobooks': 'audiobooks' };
const URL_FIRST = new Set(['cmtv-iphone-ipad']);   // apps there ask for the server address, not a server name
const LIVE = ['active', 'suspended', 'expired'];

// the server a TV line is on: the name the apps list, and the address for apps that want a URL
export function serverOf(s) {
  const name = String(s.product_name || '').toLowerCase();
  const url = String(s.streaming_url || '').replace(/^https?:\/\//i, (m) => m.toLowerCase()).replace(/\/+$/, '');
  if (name.includes('amethyst')) return { name: 'Amethyst', url: url || 'http://amethystc.live' };
  if (s.panel_type === 'onestream' || name.includes('extreme')) return { name: 'Extreme', url: url || 'https://tv.extremeiptv.net' };
  if (['aether', 'nxtdash'].includes(s.panel_type) || name.includes('imperium')) return { name: 'Imperium', url: url || 'https://imperium.esq' };
  return { name: 'CCTV', url: url || 'https://portal.cmtv.info' };
}

const login = (s) => ({ user: s.xtream_username || s.username || '', pass: s.xtream_password || s.password || '' });

function eligible(services, articleId) {
  const mod = ADDON_GUIDES[articleId];
  return (services || []).filter((s) => LIVE.includes(s.status) && login(s).user && (mod
    ? s.cockpit_module === mod
    : !s.cockpit_module && s.panel_type !== 'manual' && s.account_type !== 'reseller'))
    .sort((a, b) => (a.status === 'active' ? 0 : 1) - (b.status === 'active' ? 0 : 1));
}

function day(v) {
  if (!v) return '';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function Copy({ text, label }) {
  const [done, setDone] = useState(false);
  const go = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }
    catch { toast.error('Copy failed. Press and hold to copy instead.'); }
  };
  return <button type="button" className="kb-copy" onClick={go} aria-label={`Copy ${label}`}>{done ? 'Copied' : 'Copy'}</button>;
}

export default function GuideLogin({ articleId, user }) {
  const relevant = TV_GUIDES.has(articleId) || !!ADDON_GUIDES[articleId];
  const { data: services } = useQuery({
    queryKey: ['services'], queryFn: async () => (await api.get('/api/services')).data || [],
    enabled: !!user && relevant, staleTime: 30000,
  });
  const list = useMemo(() => eligible(services, articleId), [services, articleId]);
  const [pick, setPick] = useState(null);
  const [show, setShow] = useState(false);
  const [qr, setQr] = useState(false);
  const [sending, setSending] = useState(false);
  useEffect(() => { setShow(false); }, [pick, articleId]);

  if (!relevant) return null;
  if (!user) {
    return (
      <p className="kb-mine-guest">
        Already a customer? <Link to="/login">Sign in</Link> and this guide shows your own login, ready to copy.
      </p>
    );
  }
  if (!list.length) return null;
  const s = list.find((x) => x.id === pick) || list[0];
  const { user: u, pass: p } = login(s);
  const addon = !!ADDON_GUIDES[articleId];
  const srv = addon ? null : serverOf(s);
  const pageUrl = window.location.origin + window.location.pathname;

  const email = async () => {
    setSending(true);
    try {
      await api.post('/api/cmtv/kb/email-guide', { article_id: articleId, service_id: s.id });
      toast.success(`Sent to ${user.email}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not send the email. Try again in a minute.');
    } finally { setSending(false); }
  };

  return (
    <section className="kb-mine" aria-label="Your details for this guide">
      <header>
        <b>Your details</b>
        <span>Only you can see this. Copy them into the app.</span>
      </header>
      {list.length > 1 && (
        <div className="kb-mine-pick" role="group" aria-label="Choose a service">
          {list.map((x) => (
            <button type="button" key={x.id} className={x.id === s.id ? 'on' : ''} aria-pressed={x.id === s.id} onClick={() => setPick(x.id)}>
              {x.product_name}<small>{login(x).user}</small>
            </button>
          ))}
        </div>
      )}
      <dl>
        {srv && !URL_FIRST.has(articleId) && (<><dt>Server</dt><dd><strong>{srv.name}</strong><small>pick this in the app</small></dd></>)}
        {srv && (<><dt>{URL_FIRST.has(articleId) ? 'Server URL' : 'Server address'}</dt><dd><code>{srv.url}</code><Copy text={srv.url} label="server address" /></dd></>)}
        <dt>Username</dt><dd><code>{u}</code><Copy text={u} label="username" /></dd>
        <dt>Password</dt>
        <dd>
          <code>{show ? p : '•'.repeat(Math.min(Math.max(p.length, 8), 14))}</code>
          <button type="button" className="kb-copy" onClick={() => setShow((v) => !v)}>{show ? 'Hide' : 'Show'}</button>
          <Copy text={p} label="password" />
        </dd>
        {!addon && s.max_connections ? (<><dt>Devices at once</dt><dd>{s.max_connections}</dd></>) : null}
        {s.expiry_date && (<><dt>{s.status === 'active' ? 'Ends' : 'Ended'}</dt><dd>{day(s.expiry_date)}{s.status !== 'active' && <em> · {s.status}</em>}</dd></>)}
      </dl>
      <div className="kb-mine-actions">
        <button type="button" className="kb-btn glow" onClick={email} disabled={sending}>{sending ? 'Sending…' : 'Email me these steps'}</button>
        <button type="button" className="kb-btn" onClick={() => setQr((v) => !v)} aria-expanded={qr}>{qr ? 'Hide QR code' : 'Open on my phone'}</button>
      </div>
      {qr && (
        <div className="kb-mine-qr">
          <QRCodeSVG value={pageUrl} size={148} bgColor="#ffffff" fgColor="#0a1020" includeMargin />
          <span>Scan with your phone's camera to open this guide there. It links to the page only; sign in on your phone to see your login.</span>
        </div>
      )}
    </section>
  );
}
