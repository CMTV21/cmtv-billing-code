// CMTV local addition 2026-09-26: the customer area's header and menu (same look as the storefront), and
// CmtvAccountFrame, which puts the developer's customer pages (Services, Orders, ...) in the same navy frame.
import React, { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import { BRAND } from './brand';
import { WEBPLAYER } from './webPlayer';
import './cmtv-account.css';

const TABS = [
  ['/dashboard', 'Home'], ['/services', 'Services'], ['/orders', 'Orders'], ['/invoices', 'Invoices'],
  ['/tickets', 'Support'], ['/referrals', 'Referrals'], ['/knowledge-base', 'Guides'], ['/downloads', 'Downloads'],
];
// 2026-09-27: visitors who aren't signed in (public Guides / Terms) get these instead of account tabs
const GUEST_TABS = [['/', 'Plans'], ['/knowledge-base', 'Guides'], ['/terms', 'Terms']];

export function AccountHeader() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const { data: credit } = useQuery({
    queryKey: ['credit-balance'],
    queryFn: async () => (await api.get('/api/credits/balance')).data,
    enabled: !!user,
    staleTime: 60000,
  });
  // 2026-09-28: customers with a reseller panel get a "Reseller" tab and menu item (same query as the dashboard box)
  const { data: rp } = useQuery({
    queryKey: ['my-reseller-panels'],
    queryFn: async () => (await api.get('/api/cmtv/reseller/mine')).data,
    enabled: !!user && user.role === 'user',
    staleTime: 60000,
  });
  const isReseller = (rp?.panels || []).length > 0;
  const tabs = user ? (isReseller ? [...TABS.slice(0, 1), ['/reseller', 'Reseller'], ...TABS.slice(1)] : TABS) : GUEST_TABS;
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, []);
  const initial = (user?.name || user?.email || '?').trim().slice(0, 1).toUpperCase();
  return (
    <header className="ca-bar">
      <div className="ca-bar-in">
        <Link className="ca-brand" to="/" aria-label="CMTV home"><img src={BRAND.siteLogo} alt="" /><span>CMTV</span></Link>
        <nav className="ca-tabs" aria-label="Account">
          {tabs.map(([to, label]) => <NavLink key={to} to={to} end={to === '/dashboard' || to === '/'}>{label}</NavLink>)}
          {/* 2026-10-01: the CMTV Web Player (each TV line's card has a one-tap "Watch in browser" too) */}
          {user && <a href={WEBPLAYER} target="_blank" rel="noopener noreferrer" title="Watch in your browser">Web Player</a>}
        </nav>
        {user ? (
          <div className="ca-who" ref={ref}>
            <Link className="ca-credit" to="/referrals" title="Account credit, used automatically at checkout if you choose">
              Credit <b>${Number(credit?.balance || 0).toFixed(2)}</b>
            </Link>
            <button type="button" className="ca-avatar" aria-label="Account menu" aria-expanded={open} onClick={() => setOpen(!open)}>{initial}</button>
            {open && (
              <div className="ca-menu" role="menu">
                <p>{user.name || user.email}</p>
                <Link to="/" role="menuitem">Shop plans</Link>
                {isReseller && <Link to="/reseller" role="menuitem">Reseller tools</Link>}
                <a href={WEBPLAYER} target="_blank" rel="noopener noreferrer" role="menuitem">Web Player</a>
                <button type="button" role="menuitem" onClick={() => { logout(); navigate('/login'); }}>Log out</button>
              </div>
            )}
          </div>
        ) : (
          <div className="ca-who"><Link className="ca-btn ca-glow" to="/login">Sign in</Link></div>
        )}
      </div>
      {/* 2026-09-28: signed in with a TV line login and no email yet */}
      {user?.needs_email_link && user.role !== 'admin' && (
        <div style={{ background: 'rgba(34,230,242,.1)', borderTop: '1px solid rgba(34,230,242,.3)', padding: '8px 16px', textAlign: 'center', fontSize: 14 }}>
          Add your email so you get renewal reminders and can reset your password.{' '}
          <Link to="/link-email" style={{ color: 'var(--cyan, #22e6f2)', fontWeight: 700 }}>Finish setting up &rarr;</Link>
        </div>
      )}
    </header>
  );
}

// Wrap a developer page: navy look + this header. The page's own "Back to Dashboard" link is hidden by CSS.
export function CmtvAccountFrame({ children }) {
  return (
    <div className="cmtv-acct ca-frame dark">
      <AccountHeader />
      <div style={{ maxWidth: 1160, margin: '0 auto' }}>{children}</div>
    </div>
  );
}
