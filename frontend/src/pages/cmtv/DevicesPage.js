// CMTV local addition 2026-10-04: public "Devices & apps" page (/devices). The owner's recommended devices and apps:
// pick what you watch on -> the apps for it, why, the setup guide; then "Buying a new device?" with the three picks.
// Plain links only (no affiliate tags: Amazon Associates would likely refuse an IPTV site). Apps link to official stores /
// project pages or CMTV's own apps; modified copies of paid apps are never linked here.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { usePageMeta } from '../../components/cmtv/CmtvSEO';
import '../../components/cmtv/cmtv-kb.css';
import '../../components/cmtv/devices.css';

const DL = 'https://apk-downloader.cmtv.workers.dev';
const APPS = {
  ghost: { name: 'CMTVGhost', tag: 'Our app · recommended', what: 'Live TV, movies and series in one app, made for CMTV. Sign in with a simple code from your dashboard.',
    how: 'Downloader app → code 5883394 → CMTVGhost', link: `${DL}/ghost`, linkText: 'Download', guide: 'cmtv-cmtvghost' },
  tivimate: { name: 'TiviMate', tag: 'Live TV', what: 'A popular live-TV app with a great TV guide. Install the official app from your device\'s app store.',
    how: 'Google Play / Amazon Appstore → search "TiviMate"', link: 'https://play.google.com/store/apps/details?id=ar.tvplayer.tv', linkText: 'Google Play', guide: 'cmtv-firestick-android-tv' },
  mytv: { name: 'MYTVOnline+', tag: 'Live TV', what: 'Our pick for iPhone, iPad and Apple TV (and built into Formuler boxes as MYTVOnline).',
    how: 'App Store → search "MYTVOnline+"', link: 'https://apps.apple.com/search?term=MYTVOnline%2B', linkText: 'App Store', guide: 'cmtv-iphone-ipad' },
  nuvio: { name: 'Nuvio', tag: 'Movies & series', what: 'Movies and series with profiles and your progress saved. Part of the Nuvio add-on and CMTV+.',
    how: 'Downloader app → code 5883394 → Nuvio', link: `${DL}/nuvio`, linkText: 'Download', plan: '/?tab=addons' },
  stremio: { name: 'Stremio', tag: 'Movies & series', what: 'The classic movies & series app, if you prefer it to Nuvio.',
    how: 'stremio.com or your device\'s app store', link: 'https://www.stremio.com/downloads', linkText: 'stremio.com', guide: 'cmtv-stremio' },
  smarttube: { name: 'SmartTube', tag: 'YouTube', what: 'YouTube for Android TV and Google TV without the ads. Free and open source.',
    how: 'Install steps are on its official page', link: 'https://github.com/yuliskov/SmartTube', linkText: 'Official page' },
  tizentube: { name: 'TizenTube', tag: 'YouTube', what: 'Ad-free YouTube for Samsung (Tizen) smart TVs. Free and open source.',
    how: 'Follow the install steps on its official page', link: 'https://github.com/reisxd/TizenTube', linkText: 'Official page' },
  cmtvpn: { name: 'CMTVpn', tag: 'VPN · add-on', what: 'Keeps your streaming private. Available as a CMTV add-on (or use your own VPN).',
    how: 'Add it to your account, then follow the guide', link: '/?tab=addons', linkText: 'See the add-on', guide: 'cmtv-cmtvpn' },
  // 2026-10-05 (owner): audiobooks: Audiobookshelf on Android and computers, Prologue on iPhone / iPad
  abs: { name: 'Audiobookshelf', tag: 'Audiobooks · add-on', what: 'Our pick for CMTV Audiobooks on Android: download books to listen offline, and your place is saved on every device.',
    how: 'Google Play → "Audiobookshelf" → server address audiobooks.cmtv.info', link: 'https://play.google.com/store/apps/details?id=com.audiobookshelf.app', linkText: 'Google Play', plan: '/?tab=addons' },
  prologue: { name: 'Prologue', tag: 'Audiobooks · add-on', what: 'Our pick for CMTV Audiobooks on iPhone and iPad. Free (an optional $5 unlock adds offline downloads).',
    how: 'App Store → "Prologue" → add an Audiobookshelf server: audiobooks.cmtv.info', link: 'https://apps.apple.com/app/id1459223267', linkText: 'App Store', plan: '/?tab=addons' },
  absweb: { name: 'Audiobookshelf (browser)', tag: 'Audiobooks · add-on', what: 'On a computer there\'s nothing to install: listen to CMTV Audiobooks right in your browser.',
    how: 'Open audiobooks.cmtv.info and log in', link: 'https://audiobooks.cmtv.info', linkText: 'Open Audiobooks', plan: '/?tab=addons' },
  fast: { name: 'Fast Speed Test', tag: 'Speed test', what: 'One tap to check your internet speed. You want 25 Mbps or more for HD.',
    how: 'fast.com, or "Fast Speed Test" in your app store', link: 'https://fast.com', linkText: 'fast.com' },
  ookla: { name: 'Speedtest by Ookla', tag: 'Speed test', what: 'A more detailed speed test (speed, ping, jitter): handy when talking to your internet provider.',
    how: 'Your device\'s app store → "Speedtest"', link: 'https://www.speedtest.net/apps', linkText: 'speedtest.net' },
};

const DEVICES = [
  { key: 'androidtv', label: 'Android TV / Google TV box', sub: 'Onn 4K Pro, Formuler, Nvidia Shield, Chromecast with Google TV',
    apps: ['ghost', 'tivimate', 'nuvio', 'stremio', 'smarttube', 'cmtvpn', 'fast', 'ookla'], guide: 'cmtv-onn-4k-google-tv',
    note: 'Formuler boxes also come with MYTVOnline built in, which works great with CMTV.' },
  { key: 'fire', label: 'Amazon Firestick / Fire TV', sub: 'Fire TV Stick, Fire TV Cube', apps: ['ghost', 'tivimate', 'nuvio', 'stremio', 'smarttube', 'cmtvpn', 'fast', 'ookla'],
    guide: 'cmtv-firestick-android-tv',
    note: 'Already have a Firestick? Most current ones still run these apps. Buying a new device? We don\'t recommend a Firestick, especially the newest models.' },
  { key: 'apple', label: 'iPhone, iPad or Apple TV', sub: 'iOS / tvOS', apps: ['mytv', 'prologue', 'cmtvpn', 'ookla'], guide: 'cmtv-iphone-ipad',
    note: 'Nuvio isn\'t on iPhone yet; use the Web Player in Safari for movies and series in the meantime.' },
  { key: 'phone', label: 'Android phone or tablet', sub: 'Samsung, Pixel and others', apps: ['ghost', 'abs', 'cmtvpn', 'fast', 'ookla'], guide: 'cmtv-cmtvghost' },
  { key: 'samsung', label: 'Samsung or LG smart TV', sub: 'Built-in TV apps', apps: ['tizentube', 'fast'],
    note: 'Smart TVs\' own apps are limited for live TV. Plug in one of the devices below (from about $50) for the best picture, guide and fewest problems.' },
  { key: 'computer', label: 'Computer', sub: 'Windows, Mac, Chromebook', apps: ['absweb', 'ookla'], guide: 'cmtv-web-player', web: true },
];

const PICKS = [
  { name: 'Onn 4K Pro', badge: 'Best value', why: 'Google TV box with a fast processor, ethernet port and voice remote. Runs every app we recommend, smoothly.',
    where: [['Walmart.ca', 'https://www.walmart.ca/en/search?q=onn%204k%20pro']] },
  { name: 'Formuler Z11 Pro (or newer)', badge: 'Made for live TV', why: 'Built for IPTV: MYTVOnline built in, a great channel guide, ethernet and a remote with live-TV buttons.',
    where: [['Formuler', 'https://formuler.tv']] },
  { name: 'Nvidia Shield TV Pro', badge: 'Best overall', why: 'The fastest Android TV box there is. Pricier, but it handles 4K and everything else without breaking a sweat.',
    where: [['Best Buy', 'https://www.bestbuy.ca/en-ca/search?search=nvidia%20shield%20tv%20pro'], ['Nvidia', 'https://www.nvidia.com/en-us/shield/']] },
];

export default function DevicesPage() {
  usePageMeta({ title: 'Devices & apps | CMTV', description: 'Which app to use on your TV, phone or computer, and the streaming devices we recommend for CMTV.' });
  const [pick, setPick] = useState('androidtv');
  const d = DEVICES.find((x) => x.key === pick);
  // 2026-10-04: /devices#picks (dashboard link) and the Fire TV note jump to the picks
  const toPicks = () => document.getElementById('picks')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  React.useEffect(() => { if (window.location.hash === '#picks') setTimeout(toPicks, 300); }, []);
  return (
    <div className="cmtv-kb dv">
      <article className="kb-article" style={{ marginTop: 12 }}>
        <h1>Devices &amp; apps</h1>
        <p className="kb-lede">What are you watching on? Pick your device to see the apps we recommend and how to set them up.</p>
        <div className="dv-devs" role="tablist">
          {DEVICES.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={pick === x.key} className={pick === x.key ? 'on' : ''} onClick={() => setPick(x.key)}>
              <b>{x.label}</b><small>{x.sub}</small>
            </button>
          ))}
        </div>
        <div className="dv-panel">
          {d.note && <p className="dv-note">{d.note}{d.key === 'fire' && <>{' '}<button type="button" className="dv-linkbtn" onClick={toPicks}>See our recommended devices →</button></>}</p>}
          {d.web && (
            <div className="dv-app">
              <div className="dv-app-head"><b>CMTV Web Player</b><span className="dv-tag">Watch in your browser</span></div>
              <p>No install needed: sign in with your TV login at webplayer.cmtv.info (Imperium plays in the apps only).</p>
              <div className="dv-links"><a className="kb-btn glow" href="https://webplayer.cmtv.info" target="_blank" rel="noopener noreferrer">Open the Web Player</a>
                <Link className="kb-btn" to="/knowledge-base/cmtv-web-player">Setup guide</Link></div>
            </div>
          )}
          {d.apps.map((k) => {
            const a = APPS[k];
            const ext = a.link.startsWith('http');
            return (
              <div key={k} className="dv-app">
                <div className="dv-app-head"><b>{a.name}</b><span className="dv-tag">{a.tag}</span></div>
                <p>{a.what}</p>
                <small className="dv-how">How to get it: {a.how}</small>
                <div className="dv-links">
                  {ext ? <a className="kb-btn" href={a.link} target="_blank" rel="noopener noreferrer">{a.linkText}</a>
                    : <Link className="kb-btn" to={a.link}>{a.linkText}</Link>}
                  {a.guide && <Link className="kb-btn" to={`/knowledge-base/${a.guide}`}>Setup guide</Link>}
                  {a.plan && <Link className="kb-btn" to={a.plan}>Get Nuvio</Link>}
                </div>
              </div>
            );
          })}
          {d.guide && !d.web && <p className="dv-more">Step-by-step: <Link to={`/knowledge-base/${d.guide}`}>setup guide for this device</Link></p>}
        </div>

        <h2 id="picks">Buying a new device? Our picks</h2>
        <div className="dv-warn">
          <b>We don't recommend buying a Firestick, especially the newest models.</b>
          <p>Amazon's newest Fire TV sticks are moving to its own new system (Vega OS), which doesn't run the Android apps CMTV uses
            (CMTVGhost, TiviMate, Nuvio), and Amazon keeps restricting apps installed from outside its store. Firesticks also have
            little memory and storage, so they slow down over time. Any of the boxes below is a better buy.</p>
        </div>
        <p>All three run CMTVGhost, TiviMate and Nuvio. Plug them in with an ethernet cable if you can: it's the single biggest fix for buffering.</p>
        <div className="dv-picks">
          {PICKS.map((p) => (
            <div key={p.name} className="dv-pick">
              <span className="dv-badge">{p.badge}</span>
              <b>{p.name}</b>
              <p>{p.why}</p>
              <div className="dv-links">{p.where.map(([t, u]) => <a key={t} className="kb-btn" href={u} target="_blank" rel="noopener noreferrer">{t}</a>)}</div>
            </div>
          ))}
        </div>
        <p className="dv-more">Still stuck? <Link to="/knowledge-base/cmtv-buffering">Buffering fixes</Link> · <a href="https://t.me/Cmtv_support_bot" target="_blank" rel="noopener noreferrer">Message support</a></p>
      </article>
    </div>
  );
}
