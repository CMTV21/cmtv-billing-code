// CMTV local addition 2026-09-26: the admin area's navy frame and grouped sidebar. Used by the admin home and, in App.js,
// wrapped around every admin tab (the developer's pages are unchanged; cmtv-admin.css re-colours them while the frame is shown).
import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import './cmtv-admin.css';
import { CustomerSearch } from '../../pages/cmtv/AdminCustomerPage';   // 2026-09-27: find a customer from any admin page

// perm = the staff permission that shows the item to staff (items without one are admin-only), like the developer's sidebar
const NAV = [
  { group: null, items: [{ label: 'Overview', to: '/admin', perm: 'dashboard' }] },
  { group: 'Money', items: [
    { label: 'Orders', to: '/admin/orders', count: 'pending', perm: 'orders' }, { label: 'Finances', to: '/admin/finances' },
    { label: 'Analytics', to: '/admin/analytics' }, { label: 'Invoices', to: '/admin/invoices', perm: 'orders' },
    { label: 'Refunds', to: '/admin/refunds' }, { label: 'Coupons', to: '/admin/coupons' },
  ] },
  { group: 'Customers', items: [
    { label: 'Customers', to: '/admin/customers', perm: 'customers' }, { label: 'Customer profile', to: '/admin/customer' },
    { label: 'Support', to: '/admin/tickets', count: 'tickets', crit: true, perm: 'tickets' },
    { label: 'Referrals', to: '/admin/referrals' }, { label: 'Reviews', to: '/admin/reviews' }, { label: 'Survey', to: '/admin/survey' }, { label: 'Resellers', to: '/admin/resellers' }, { label: 'Notices', to: '/admin/notices' }, { label: 'Imported users', to: '/admin/imported-users', perm: 'imported_users' },
  ] },
  { group: 'Services', items: [
    { label: 'Products', to: '/admin/products' }, { label: 'Stremio', to: '/admin/stremio' }, { label: 'Nuvio', to: '/admin/nuvio' }, { label: 'CMTVpn', to: '/admin/cmtvpn' },
    { label: 'Audiobooks', to: '/admin/audiobooks', count: 'stuck' },
    { label: 'Launcher', to: '/admin/launcher' }, { label: 'Downloads', to: '/admin/downloads' },
    { label: 'Knowledge base', to: '/admin/knowledge-base' },
  ] },
  { group: 'System', items: [
    { label: 'Mass email', to: '/admin/mass-email' }, { label: 'Email templates', to: '/admin/email-templates' },
    { label: 'Staff', to: '/admin/staff' }, { label: 'Settings', to: '/admin/settings' },
  ] },
];

// Shared with the admin home (same query keys, so one fetch serves both)
export const useAdminOverview = (enabled = true) => useQuery({
  queryKey: ['cmtv-admin-overview'],
  queryFn: async () => (await api.get('/api/cmtv/admin/overview')).data,
  refetchInterval: 120000, staleTime: 60000, enabled,
});
// Stuck audiobook requests come from the Asus server and can be slow: never blocks anything.
export const useStuckAudiobooks = (enabled = true) => useQuery({
  queryKey: ['ab-stuck'],
  queryFn: async () => (await api.get('/api/cmtv/audiobooks/stuck')).data,
  staleTime: 600000, retry: false, enabled,
});

function AdminSidebar() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const isStaff = user?.role === 'staff';
  const perms = user?.permissions || [];
  const { data: ov } = useAdminOverview(!isStaff);
  const { data: stuck } = useStuckAudiobooks(!isStaff);
  const counts = {
    pending: ov?.needs?.pending_payment?.length || 0,
    tickets: ov?.needs?.tickets_waiting?.length || 0,
    stuck: stuck?.requests?.length || 0,
  };
  useEffect(() => { setOpen(false); }, [pathname]);
  const isOn = (to) => (to === '/admin' ? pathname === '/admin' : pathname === to || pathname.startsWith(`${to}/`));
  const groups = NAV.map((g) => ({ ...g, items: g.items.filter((it) => !isStaff || (it.perm && perms.includes(it.perm))) }))
    .filter((g) => g.items.length);
  return (
    <nav className={`side ${open ? 'open' : ''}`} aria-label="Admin">
      <div className="brand">
        <img src="/cmtv/cmtv-logo.png" alt="" />
        <div><b>CMTV</b><small>{isStaff ? 'Staff' : 'Admin'}</small></div>
        <button type="button" className="menu-btn" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close' : 'Menu'}</button>
      </div>
      <div className="links">
        {!isStaff && <CustomerSearch compact />}
        {groups.map((g) => (
          <React.Fragment key={g.group || 'top'}>
            {g.group && <div className="grp">{g.group}</div>}
            {g.items.map((it) => (
              <Link key={it.to} to={it.to} className={isOn(it.to) ? 'on' : ''} aria-current={isOn(it.to) ? 'page' : undefined}>
                {it.label}
                {counts[it.count] > 0 && <span className={`count ${it.crit ? 'crit' : ''}`}>{counts[it.count]}</span>}
              </Link>
            ))}
          </React.Fragment>
        ))}
        <div className="grp">You</div>
        <Link to="/">View the store</Link>
        <button type="button" className="as-link" onClick={() => { logout(); navigate('/login'); }}>Log out</button>
      </div>
    </nav>
  );
}

// While an admin page is on screen, <html> carries "cmtv-adm-on" so pop-ups rendered outside the page
// (dialogs, dropdowns, selects) get the navy colours too.
export function CmtvAdminFrame({ children }) {
  useEffect(() => {
    document.documentElement.classList.add('cmtv-adm-on');
    return () => document.documentElement.classList.remove('cmtv-adm-on');
  }, []);
  return (
    <div className="cmtv-adm dark">
      <div className="app">
        <AdminSidebar />
        <main className="adm-main">{children}</main>
      </div>
    </div>
  );
}
