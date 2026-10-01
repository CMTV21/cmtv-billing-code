// CMTV local addition 2026-09-28: /reseller "Reseller tools" for customers with an active reseller panel.
// Notices from CMTV, their own brand (name, contact, colour, server addresses, apps), a setup guide + flyer for their
// customers without the CMTV name (/g/<slug>, served by the backend), and a marketing kit: social images drawn on a
// canvas with their brand (PNG download) and ready-to-post captions. Backend: cmtv_reseller_kit.py (/api/cmtv/reseller/*).
import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { QRCodeSVG } from 'qrcode.react';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/reseller-credits.css';
import NuvioReseller from '../../components/cmtv/NuvioReseller'; // 2026-10-01

const copy = (text, what) => navigator.clipboard.writeText(text).then(() => toast.success(`${what} copied`)).catch(() => toast.error('Copy failed'));
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const HEADLINES = ['Live TV, movies & series on every screen', 'Cut the cable bill, keep the channels', 'Sports, PPV & more. Set up in minutes'];
const FORMATS = { square: [1080, 1080, 'Square post'], story: [1080, 1920, 'Story'] };

function wrap(ctx, text, maxW) {
  const words = text.split(' ');
  const lines = [];
  let line = '';
  words.forEach((w) => {
    const t = line ? `${line} ${w}` : w;
    if (ctx.measureText(t).width > maxW && line) { lines.push(line); line = w; } else line = t;
  });
  if (line) lines.push(line);
  return lines;
}

// 2026-09-28: the reseller's logo (same-origin PNG, so the canvas can still be downloaded)
function useLogoImage(url) {
  const [img, setImg] = useState(null);
  useEffect(() => {
    if (!url) { setImg(null); return undefined; }
    const im = new Image();
    let live = true;
    im.onload = () => { if (live) setImg(im); };
    im.onerror = () => { if (live) setImg(null); };
    im.src = url;
    return () => { live = false; };
  }, [url]);
  return img;
}

function draw(canvas, fmt, b, facts, headline, logo) {
  const [W, H] = FORMATS[fmt];
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  const F = (w, s) => `${w} ${s}px Figtree, system-ui, sans-serif`;
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, '#0d111c'); g.addColorStop(1, '#1b2338');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  const glow = ctx.createRadialGradient(W * 0.85, H * 0.12, 10, W * 0.85, H * 0.12, W * 0.7);
  glow.addColorStop(0, `${b.color}88`); glow.addColorStop(1, `${b.color}00`);
  ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
  const pad = 80;
  let y = fmt === 'story' ? 260 : 140;
  ctx.fillStyle = b.color; ctx.fillRect(pad, y - 50, 90, 10);
  let nameX = pad;
  if (logo) {
    const ratio = logo.width / logo.height;
    let lh = 110;
    let lw = lh * ratio;
    if (lw > 260) { lw = 260; lh = lw / ratio; }
    ctx.drawImage(logo, pad, y - 20 + (110 - lh) / 2, lw, lh);
    nameX = pad + lw + 28;
  }
  ctx.fillStyle = '#fff';
  let size = 64;
  ctx.font = F(800, size);
  while (size > 34 && ctx.measureText(b.name || 'Your name').width > W - nameX - pad) { size -= 4; ctx.font = F(800, size); }
  ctx.fillText(b.name || 'Your name', nameX, y + 60);
  y += fmt === 'story' ? 230 : 190;
  ctx.font = F(800, fmt === 'story' ? 92 : 78);
  wrap(ctx, headline, W - pad * 2).forEach((l) => { ctx.fillText(l, pad, y); y += fmt === 'story' ? 108 : 92; });
  y += 40;
  if (facts) {
    const labels = ['live channels', 'movies', 'series'];
    const bw = (W - pad * 2 - 40) / 3;
    facts.forEach((n, i) => {
      const x = pad + i * (bw + 20);
      ctx.fillStyle = 'rgba(255,255,255,.07)'; ctx.fillRect(x, y, bw, 170);
      ctx.fillStyle = b.color; ctx.font = F(800, 56); ctx.fillText(`${n}+`, x + 24, y + 80);
      ctx.fillStyle = '#c9d2e3'; ctx.font = F(600, 32); ctx.fillText(labels[i], x + 24, y + 130);
    });
    y += 230;
  }
  ctx.fillStyle = '#c9d2e3'; ctx.font = F(600, 38);
  ['Canadian & US channels, sports & PPV', 'Firestick, Android TV, phones & tablets'].forEach((l) => { ctx.fillText(`•  ${l}`, pad, y); y += 60; });
  const contact = b.contact ? `Get started: ${b.contact}` : 'Message me to get started';
  ctx.font = F(800, 42);
  const lines = wrap(ctx, contact, W - pad * 2 - 60);
  const boxH = lines.length * 56 + 44;
  const by = H - pad - boxH;
  ctx.fillStyle = b.color; ctx.fillRect(pad, by, W - pad * 2, boxH);
  ctx.fillStyle = '#fff';
  lines.forEach((l, i) => ctx.fillText(l, pad + 30, by + 66 + i * 56));
}

function SocialImage({ brand, facts }) {
  const ref = useRef(null);
  const [fmt, setFmt] = useState('square');
  const [h, setH] = useState(0);
  const logo = useLogoImage(brand.logo);
  useEffect(() => {
    let live = true;
    const go = () => { if (live && ref.current) draw(ref.current, fmt, brand, facts, HEADLINES[h], logo); };
    go();
    if (document.fonts?.ready) document.fonts.ready.then(go);
    return () => { live = false; };
  }, [fmt, h, brand, facts, logo]);
  const download = () => {
    const a = document.createElement('a');
    a.download = `${(brand.name || 'post').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${fmt}.png`;
    a.href = ref.current.toDataURL('image/png');
    a.click();
  };
  return (
    <div className="rt-social">
      <div className="rt-canvas"><canvas ref={ref} style={{ aspectRatio: `${FORMATS[fmt][0]} / ${FORMATS[fmt][1]}` }} /></div>
      <div className="rt-social-opts">
        <b>Size</b>
        <div className="rt-seg">{Object.entries(FORMATS).map(([k, v]) => (
          <button type="button" key={k} className={fmt === k ? 'on' : ''} onClick={() => setFmt(k)}>{v[2]}</button>))}</div>
        <b>Headline</b>
        <div className="rt-seg col">{HEADLINES.map((t, i) => (
          <button type="button" key={t} className={h === i ? 'on' : ''} onClick={() => setH(i)}>{t}</button>))}</div>
        <button type="button" className="ca-btn ca-glow" onClick={download}>Download image</button>
      </div>
    </div>
  );
}

function captions(b, facts) {
  const who = b.contact ? `Message ${b.contact}` : 'Message me';
  const nums = facts ? `${facts[0]}+ live channels, ${facts[1]}+ movies and ${facts[2]}+ series. ` : '';
  return [
    `📺 Live TV, movies & series on every screen with ${b.name}. ${nums}Works on Firestick, Android TV, phones & tablets. ${who} to get started.`,
    `Tired of paying for cable? ${b.name} has Canadian & US channels, sports and PPV${facts ? `, with ${facts[0]}+ live channels` : ''}. Set up in minutes. ${who}.`,
    `New to ${b.name}? I'll help you set up on your Firestick, Android TV or phone, step by step. ${who}.`,
  ];
}

const EMPTY_SERVER = { name: '', url: '' };

// 2026-09-28: logo upload (PNG/JPG/WebP up to 2 MB; the server re-saves it as a PNG, max 600 px)
function LogoPicker({ logo, onChange }) {
  const [busy, setBusy] = useState(false);
  const upload = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const r = await api.post('/api/cmtv/reseller/brand/logo', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      onChange(r.data.logo);
      toast.success('Logo saved');
    } catch (err) { toast.error(err.response?.data?.detail || 'Could not upload that image'); }
    setBusy(false);
  };
  const remove = async () => {
    try { await api.delete('/api/cmtv/reseller/brand/logo'); onChange(null); } catch { toast.error('Could not remove it'); }
  };
  return (
    <div className="rt-logo">
      <div className="rt-logo-box">{logo ? <img src={logo} alt="Your logo" /> : <span>No logo</span>}</div>
      <div>
        <label className="ca-btn ca-ghost rt-file">{busy ? 'Uploading…' : logo ? 'Change logo' : 'Upload your logo'}
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={upload} disabled={busy} /></label>
        {logo && <button type="button" className="ca-icon" onClick={remove}>Remove</button>}
        <p className="rt-note" style={{ margin: '6px 0 0' }}>PNG, JPG or WebP, up to 2 MB. It shows on your guide, flyer and images.</p>
      </div>
    </div>
  );
}

export default function ResellerToolsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ['reseller-tools'], queryFn: async () => (await api.get('/api/cmtv/reseller/tools')).data, retry: false });
  const [b, setB] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (data?.brand) setB(data.brand); }, [data]);

  if (isLoading) return <div className="rt"><p>Loading…</p></div>;
  if (error || !data) {
    return <div className="rt"><div className="ca-panel"><h1 className="ca-h2">Reseller tools</h1><p>These tools are for CMTV resellers. Interested? <Link to="/?tab=resellers">See reseller credits</Link>.</p></div></div>;
  }
  if (!b) return null;
  const set = (k) => (e) => setB({ ...b, [k]: e.target.value });
  const setSrv = (i, k, v) => setB({ ...b, servers: b.servers.map((s, j) => (j === i ? { ...s, [k]: v } : s)) });
  const facts = data.facts?.[b.facts] || null;
  const showsCmtv = b.servers.some((s) => /cmtv/i.test(s.url || ''));

  const save = async () => {
    setSaving(true);
    try {
      await api.put('/api/cmtv/reseller/brand', b);
      await qc.invalidateQueries({ queryKey: ['reseller-tools'] });
      toast.success('Saved');
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not save'); }
    setSaving(false);
  };

  return (
    <div className="rt">
      <h1 className="rt-title">Reseller tools</h1>
      <p className="rt-sub">Your own setup guide and marketing material for your customers, with your name on it and no mention of CMTV.</p>

      {data.notices?.length > 0 && (
        <section className="ca-panel rt-notices" aria-label="Notices from CMTV">
          <h2 className="ca-h2">Notices from CMTV</h2>
          {data.notices.map((n) => <div key={n.id} className="rt-notice"><small>{day(n.created_at)}</small><p>{n.text}</p></div>)}
        </section>
      )}

      <NuvioReseller />{/* 2026-10-01: Nuvio accounts for resellers switched on for it (shows nothing otherwise) */}

      <section className="ca-panel">
        <h2 className="ca-h2">1. Your brand</h2>
        <LogoPicker logo={b.logo} onChange={(logo) => setB({ ...b, logo })} />
        <div className="rt-form">
          <label>Business name<input value={b.name} maxLength={40} onChange={set('name')} placeholder="e.g. Northern Streams" /></label>
          <label>How customers reach you<input value={b.contact} maxLength={120} onChange={set('contact')} placeholder="e.g. Telegram @northernstreams or text 555-123-4567" /></label>
          <label>Colour<span className="rt-color"><input type="color" value={b.color} onChange={set('color')} /><code>{b.color}</code></span></label>
          <label>Figures to show<select value={b.facts} onChange={set('facts')}>
            <option value="cctv">CCTV (11,000+ live, 20,000+ movies, 6,000+ series)</option>
            <option value="imperium">Imperium (40,000+ live, 30,000+ movies, 8,000+ series)</option>
            <option value="none">No figures</option>
          </select></label>
        </div>
        <h3 className="rt-h3">Server addresses your customers enter</h3>
        {b.servers.map((s, i) => (
          <div key={i} className="rt-srv">
            <input value={s.name} maxLength={30} onChange={(e) => setSrv(i, 'name', e.target.value)} placeholder="Name (optional)" aria-label="Server name" />
            <input value={s.url} maxLength={120} onChange={(e) => setSrv(i, 'url', e.target.value)} placeholder="https://tv.example.com" aria-label="Server address" />
            {b.servers.length > 1 && <button type="button" className="ca-icon" onClick={() => setB({ ...b, servers: b.servers.filter((_, j) => j !== i) })}>Remove</button>}
          </div>
        ))}
        {b.servers.length < 3 && <button type="button" className="ca-icon" onClick={() => setB({ ...b, servers: [...b.servers, EMPTY_SERVER] })}>+ Add a server</button>}
        {showsCmtv && <p className="rt-warn">Your customers will see "cmtv" in this address. Want your own address instead? We can set up your own DNS: message us.</p>}
        <h3 className="rt-h3">Apps</h3>
        <div className="rt-form">
          <label>TV app name<input value={b.tv_app} maxLength={30} onChange={set('tv_app')} placeholder="TiviMate" /></label>
          <label>Your Downloader code (optional)<input value={b.downloader} maxLength={10} inputMode="numeric" onChange={set('downloader')} placeholder="e.g. 1234567" /></label>
          <label>Android phone app (optional)<input value={b.phone_app} maxLength={30} onChange={set('phone_app')} placeholder="App name" /></label>
          <label>Phone app download link<input value={b.phone_link} maxLength={300} onChange={set('phone_link')} placeholder="https://..." /></label>
        </div>
        <p className="rt-note">Want your own branded apps, a website or your own DNS? Ask us about partner services.</p>
        <button type="button" className="ca-btn ca-glow" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save'}</button>
      </section>

      <section className="ca-panel">
        <h2 className="ca-h2">2. Setup guide for your customers</h2>
        {data.guide_url ? (
          <div className="rt-guide">
            <div>
              <p>Send this link to your customers. It has the setup steps for their device, your server address and how to reach you.</p>
              <div className="rt-link"><code>{data.guide_url}</code></div>
              <div className="rp-actions">
                <button type="button" className="ca-btn ca-glow" onClick={() => copy(data.guide_url, 'Link')}>Copy link</button>
                <a className="ca-btn ca-ghost" href={data.guide_url} target="_blank" rel="noopener noreferrer">Open</a>
                <a className="ca-btn ca-ghost" href={data.flyer_url} target="_blank" rel="noopener noreferrer">Printable flyer</a>
              </div>
              <p className="rt-note">The link itself shows billing.cmtv.info. For a link on your own domain, message us.</p>
            </div>
            <div className="rt-qr"><QRCodeSVG value={data.guide_url} size={132} /></div>
          </div>
        ) : <p>Save your brand above and your guide link appears here.</p>}
      </section>

      <section className="ca-panel">
        <h2 className="ca-h2">3. Marketing kit</h2>
        <p className="rt-note">Images for Facebook, Instagram, Marketplace or WhatsApp status, made with your brand{data.saved ? '' : ' (save your brand first so your name shows)'}.</p>
        <SocialImage brand={b} facts={facts} />
        <h3 className="rt-h3">Ready-to-post text</h3>
        {captions({ ...b, name: b.name || 'us' }, facts).map((t) => (
          <div key={t} className="rt-caption"><p>{t}</p><button type="button" className="ca-icon" onClick={() => copy(t, 'Text')}>Copy</button></div>
        ))}
      </section>
    </div>
  );
}
