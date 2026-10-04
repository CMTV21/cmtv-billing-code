// CMTV local addition 2026-10-01: the site menu at the top of the public pages (storefront, and Guides / Terms / Privacy
// for visitors): Plans (drop-down) · Free trials · Guides · Web Player · Support (drop-down) · Resellers. Store links use
// ?tab= / &go= (CmtvHomePage switches tab and scrolls). Under 1080 px it folds into a ☰ panel.
import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronDown, Menu, X } from 'lucide-react';
import { useAuthStore } from '../../store/store';
import { WEBPLAYER } from './webPlayer';
import './site-nav.css';

const PLANS = [
  ['CCTV', '/?tab=cctv'], ['Imperium', '/?tab=imperium'], ['Add-ons', '/?tab=addons'],
  ['Compare CCTV & Imperium', '/?tab=all&go=compare'],
];
const supportItems = (signedIn) => [
  ...(signedIn ? [['My support tickets', '/tickets']] : []),
  ['Devices & apps', '/devices'],   // 2026-10-04
  ['Service status', '/status'],   // 2026-10-02
  ['Buffering? Quick fixes', '/knowledge-base/cmtv-buffering'],
  ['Telegram support', 'https://t.me/Cmtv_support_bot', true],
  ['Email cmtv@pm.me', 'mailto:cmtv@pm.me', true],
];

function Item({ to, ext, children, onClick }) {
  if (ext) {
    const blank = to.startsWith('http');
    return <a href={to} onClick={onClick} {...(blank ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>{children}</a>;
  }
  return <Link to={to} onClick={onClick}>{children}</Link>;
}

function Drop({ label, items, active }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('click', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('click', close); document.removeEventListener('keydown', esc); };
  }, []);
  return (
    <div className="sn-drop" ref={ref}>
      <button type="button" className={`sn-link${active ? ' on' : ''}`} aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)}>
        {label} <ChevronDown className="sn-chev" aria-hidden="true" />
      </button>
      {open && (
        <div className="sn-menu" role="menu">
          {items.map(([t, to, ext]) => <Item key={t} to={to} ext={ext} onClick={() => setOpen(false)}>{t}</Item>)}
        </div>
      )}
    </div>
  );
}

export default function SiteNav() {
  const { user } = useAuthStore();
  const location = useLocation();
  const [mobile, setMobile] = useState(false);
  useEffect(() => { setMobile(false); }, [location.key]);
  const q = new URLSearchParams(location.search);
  const onStore = location.pathname === '/';
  const tab = q.get('tab');
  const on = {
    plans: onStore && ['cctv', 'imperium', 'addons'].includes(tab),
    trials: onStore && tab === 'trials',
    resellers: onStore && tab === 'resellers',
    guides: location.pathname.startsWith('/knowledge-base'),
  };
  const support = supportItems(!!user);
  return (
    <nav className="cmtv-nav" aria-label="Site">
      <div className="sn-links">
        <Drop label="Plans" items={PLANS} active={on.plans} />
        <Link className={`sn-link${on.trials ? ' on' : ''}`} to="/?tab=trials">Free trials</Link>
        <Link className={`sn-link${on.guides ? ' on' : ''}`} to="/knowledge-base">Guides</Link>
        <a className="sn-link" href={WEBPLAYER} target="_blank" rel="noopener noreferrer">Web Player</a>
        <Drop label="Support" items={support} />
        <Link className={`sn-link${on.resellers ? ' on' : ''}`} to="/?tab=resellers&go=resellers">Resellers</Link>
      </div>
      <button type="button" className="sn-burger" aria-label={mobile ? 'Close menu' : 'Open menu'} aria-expanded={mobile} onClick={() => setMobile(!mobile)}>
        {mobile ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
      </button>
      {mobile && (
        <div className="sn-panel">
          <b>Plans</b>
          {PLANS.map(([t, to]) => <Link key={t} to={to}>{t}</Link>)}
          <b>Explore</b>
          <Link to="/?tab=trials">Free trials</Link>
          <Link to="/knowledge-base">Setup guides</Link>
          <a href={WEBPLAYER} target="_blank" rel="noopener noreferrer">Web Player</a>
          <Link to="/?tab=resellers&go=resellers">Resellers</Link>
          <b>Support</b>
          {support.map(([t, to, ext]) => <Item key={t} to={to} ext={ext}>{t}</Item>)}
        </div>
      )}
    </nav>
  );
}
