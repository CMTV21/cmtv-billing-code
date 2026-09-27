// CMTV local addition 2026-09-26: the customer area's header and menu (same look as the storefront), and
// CmtvAccountFrame, which puts the developer's customer pages (Services, Orders, ...) in the same navy frame.
import React, { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import { BRAND } from './brand';
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
          {(user ? TABS : GUEST_TABS).map(([to, label]) => <NavLink key={to} to={to} end={to === '/dashboard' || to === '/'}>{label}</NavLink>)}
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
                <button type="button" role="menuitem" onClick={() => { logout(); navigate('/login'); }}>Log out</button>
              </div>
            )}
          </div>
        ) : (
          <div className="ca-who"><Link className="ca-btn ca-glow" to="/login">Sign in</Link></div>
        )}
      </div>
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
