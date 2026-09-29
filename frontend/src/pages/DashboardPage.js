import { formatDate } from "../utils/timezone";
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { servicesAPI, ordersAPI } from '../api/api';
import { useAuthStore, useCartStore } from '../store/store';
import { useBrandingStore } from '../store/branding';
import { useCurrencyStore } from '../store/currency';
import { Server, ShoppingBag, FileText, LogOut, Tv, MessageSquare, Gift, Download, ShoppingCart, Clock, AlertTriangle, RefreshCw, Copy, Check, Eye, EyeOff, BookOpen } from 'lucide-react';
import CreditBalance from '../components/CreditBalance';
import CurrencySwitcher from '../components/CurrencySwitcher';
import { toast } from 'sonner';
import api from '../api/api';

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { branding } = useBrandingStore();

  const { data: services } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const response = await servicesAPI.getAll();
      return response.data;
    },
  });

  const { data: orders } = useQuery({
    queryKey: ['orders'],
    queryFn: async () => {
      const response = await ordersAPI.getAll();
      return response.data;
    },
  });

  const { data: referralSettings } = useQuery({
    queryKey: ['my-referral-quick'],
    queryFn: async () => {
      const response = await api.get('/api/referral/my-code');
      return response.data;
    },
  });

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const allServices = services?.filter((s) => !s.is_credit_addon) || [];
  const activeServices = allServices.filter((s) => s.status === 'active');
  const expiredServices = allServices.filter((s) => s.status !== 'active');
  const pendingOrders = orders?.filter((o) => o.status === 'pending') || [];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:py-4">
          <div className="flex justify-between items-center">
            <Link to="/" className="flex items-center gap-2">
              {branding.logo_url ? (
                <img src={branding.logo_url} alt={branding.site_name} className="h-7 sm:h-8" />
              ) : (
                <Server className="w-7 h-7 sm:w-8 sm:h-8" style={{ color: branding.primary_color }} />
              )}
              <h1 className="text-lg sm:text-2xl font-bold text-gray-900 dark:text-white">{branding.site_name}</h1>
            </Link>
            <div className="flex items-center gap-2 sm:gap-4">
              <CurrencySwitcher />
              <span className="text-gray-700 dark:text-gray-200 hidden sm:inline text-sm">Welcome, {user?.name}</span>
              <button onClick={handleLogout} className="flex items-center gap-2 text-gray-600 hover:text-red-600">
                <LogOut className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-8">
        {/* Mobile Quick Links */}
        <div className="md:hidden grid grid-cols-4 gap-2 mb-4">
          {[
            { to: '/', icon: ShoppingCart, label: 'Shop', color: 'text-purple-600' },
            { to: '/orders', icon: ShoppingBag, label: 'Orders', color: 'text-amber-600' },
            { to: '/invoices', icon: FileText, label: 'Invoices', color: 'text-green-600' },
            { to: '/services', icon: Tv, label: 'Services', color: 'text-blue-600' },
            { to: '/downloads', icon: Download, label: 'Downloads', color: 'text-cyan-600' },
            { to: '/knowledge-base', icon: BookOpen, label: 'Guides', color: 'text-teal-600' },
            { to: '/tickets', icon: MessageSquare, label: 'Support', color: 'text-red-600' },
            { to: '/referrals', icon: Gift, label: 'Referrals', color: 'text-indigo-600' },
          ].map((link) => (
            <Link key={link.to} to={link.to}
              className="bg-white dark:bg-gray-900 rounded-lg shadow p-3 hover:shadow-md transition text-center">
              <link.icon className={`w-5 h-5 ${link.color} mx-auto mb-1`} />
              <p className="text-[10px] font-medium text-gray-700 dark:text-gray-300">{link.label}</p>
            </Link>
          ))}
        </div>

        <div className="flex gap-6">
          {/* Sidebar Navigation */}
          <aside className="hidden md:block w-52 flex-shrink-0">
            <nav className="bg-white dark:bg-gray-900 rounded-lg shadow p-2 space-y-1 sticky top-20" data-testid="dashboard-sidebar">
              {[
                { to: '/', icon: ShoppingCart, label: 'Shop', color: 'text-purple-600' },
                { to: '/orders', icon: ShoppingBag, label: 'Orders', color: 'text-amber-600' },
                { to: '/invoices', icon: FileText, label: 'Invoices', color: 'text-green-600' },
                { to: '/services', icon: Tv, label: 'Services', color: 'text-blue-600' },
                { to: '/downloads', icon: Download, label: 'Downloads', color: 'text-cyan-600' },
                { to: '/knowledge-base', icon: BookOpen, label: 'Guides', color: 'text-teal-600' },
                { to: '/tickets', icon: MessageSquare, label: 'Support', color: 'text-red-600' },
                { to: '/referrals', icon: Gift, label: 'Referrals', color: 'text-indigo-600' },
              ].map((link) => (
                <Link key={link.to} to={link.to}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-sm"
                  data-testid={`sidebar-link-${link.label.toLowerCase()}`}>
                  <link.icon className={`w-4 h-4 ${link.color} flex-shrink-0`} />
                  <span className="text-gray-700 dark:text-gray-300 font-medium">{link.label}</span>
                </Link>
              ))}
            </nav>
          </aside>

          {/* Main Content */}
          <div className="flex-1 min-w-0">
            {/* Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 mb-6 sm:mb-8">
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-3 sm:p-4 flex items-center gap-2 sm:gap-3">
                <div className="w-10 h-10 bg-green-100 dark:bg-green-900/30 rounded-lg flex items-center justify-center">
                  <Tv className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Active</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{activeServices.length}</p>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-3 sm:p-4 flex items-center gap-2 sm:gap-3">
                <div className="w-10 h-10 bg-amber-100 dark:bg-amber-900/30 rounded-lg flex items-center justify-center">
                  <ShoppingBag className="w-5 h-5 text-amber-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Pending</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{pendingOrders.length}</p>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-3 sm:p-4 flex items-center gap-2 sm:gap-3">
                <div className="w-10 h-10 bg-blue-100 dark:bg-blue-900/30 rounded-lg flex items-center justify-center">
                  <FileText className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Orders</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{orders?.length || 0}</p>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
                <CreditBalance showHistory={false} />
              </div>
            </div>

        {/* Active Services - Visual Cards */}
        {activeServices.length > 0 && (
          <div className="mb-6 sm:mb-8">
            <h2 className="text-lg sm:text-xl font-bold text-gray-900 dark:text-white mb-3 sm:mb-4">My Services</h2>
            <div className="grid md:grid-cols-2 gap-3 sm:gap-4">
              {activeServices.map((service) => (
                <ServiceCard key={service.id} service={service} navigate={navigate} />
              ))}
            </div>
          </div>
        )}

        {/* Expired/Suspended Services */}
        {expiredServices.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold text-gray-600 dark:text-gray-400 mb-3">Expired / Suspended</h2>
            <div className="grid md:grid-cols-2 gap-4">
              {expiredServices.map((service) => (
                <ServiceCard key={service.id} service={service} navigate={navigate} expired />
              ))}
            </div>
          </div>
        )}

        {/* No Services */}
        {allServices.length === 0 && (
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow p-12 text-center mb-8">
            <Tv className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">No Services Yet</h3>
            <p className="text-gray-500 dark:text-gray-400 mb-6">Browse our plans and get started!</p>
            <Link to="/" className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-semibold">
              <ShoppingCart className="w-5 h-5" /> Browse Plans
            </Link>
          </div>
        )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ServiceCard({ service, navigate, expired }) {
  const { addItem } = useCartStore();
  const [copied, setCopied] = useState('');
  const [showPass, setShowPass] = useState(false);

  const copy = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopied(key);
    toast.success('Copied!');
    setTimeout(() => setCopied(''), 2000);
  };

  const handleQuickRenew = () => {
    if (service.product_id) {
      addItem({
        product_id: service.product_id,
        product_name: service.product_name,
        term_months: 1,
        price: 0,
        account_type: service.account_type,
      }, service.id, 'extend');
      navigate('/checkout');
    } else {
      navigate('/services');
    }
  };

  // Countdown logic
  const expiryDate = service.expiry_date ? new Date(service.expiry_date) : null;
  const now = new Date();
  const diffMs = expiryDate ? expiryDate - now : 0;
  const daysLeft = Math.max(0, Math.ceil(diffMs / (1000 * 60 * 60 * 24)));
  const hoursLeft = Math.max(0, Math.ceil(diffMs / (1000 * 60 * 60)));
  const isExpiringSoon = daysLeft <= 7 && daysLeft > 0;
  const isExpired = diffMs <= 0;

  const countdownText = isExpired ? 'Expired' : daysLeft > 1 ? `${daysLeft} day${daysLeft !== 1 ? 's' : ''} left` : hoursLeft > 0 ? `${hoursLeft}h left` : 'Expiring soon';
  const countdownColor = isExpired ? 'text-red-600 bg-red-50 dark:bg-red-900/20' : isExpiringSoon ? 'text-amber-600 bg-amber-50 dark:bg-amber-900/20' : 'text-green-600 bg-green-50 dark:bg-green-900/20';

  const streamUrl = service.streaming_url;
  const isVPN = service.panel_type === 'ghostsurf';
  const user = isVPN ? service.vpn_username : service.xtream_username;
  const pass = isVPN ? service.vpn_password : service.xtream_password;

  return (
    <div className={`bg-white dark:bg-gray-900 rounded-xl shadow-sm border overflow-hidden ${expired ? 'opacity-70 border-gray-200 dark:border-gray-700' : 'border-gray-200 dark:border-gray-700'}`}>
      {/* Header */}
      <div className={`px-5 py-3 flex items-center justify-between ${expired ? 'bg-gray-100 dark:bg-gray-800' : isVPN ? 'bg-gradient-to-r from-teal-600 to-cyan-700' : 'bg-gradient-to-r from-blue-600 to-blue-700'}`}>
        <div>
          <h3 className={`font-bold ${expired ? 'text-gray-700 dark:text-gray-300' : 'text-white'}`}>{service.product_name}</h3>
          <p className={`text-xs ${expired ? 'text-gray-500' : isVPN ? 'text-teal-100' : 'text-blue-100'}`}>
            {isVPN ? 'VPN Service' : service.account_type === 'reseller' ? 'Reseller' : 'Subscriber'} — {service.panel_name || 'Panel'}
          </p>
        </div>
        <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${countdownColor}`}>
          {countdownText}
        </span>
      </div>

      {/* Body */}
      <div className="p-5 space-y-3">
        {/* Credentials Row */}
        {user && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Username</p>
              <div className="flex items-center gap-1">
                <code className="text-sm font-mono text-gray-900 dark:text-white truncate">{user}</code>
                <button onClick={() => copy(user, `u-${service.id}`)} className="text-gray-400 hover:text-blue-600 shrink-0">
                  {copied === `u-${service.id}` ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Password</p>
              <div className="flex items-center gap-1">
                <code className="text-sm font-mono text-gray-900 dark:text-white truncate">{showPass ? pass : '••••••'}</code>
                <button onClick={() => setShowPass(!showPass)} className="text-gray-400 hover:text-blue-600 shrink-0">
                  {showPass ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
                <button onClick={() => copy(pass, `p-${service.id}`)} className="text-gray-400 hover:text-blue-600 shrink-0">
                  {copied === `p-${service.id}` ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Server URL (IPTV) */}
        {streamUrl && !isVPN && (
          <div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Server</p>
            <div className="flex items-center gap-1">
              <code className="text-sm font-mono text-gray-900 dark:text-white truncate">{streamUrl}</code>
              <button onClick={() => copy(streamUrl, `s-${service.id}`)} className="text-gray-400 hover:text-blue-600 shrink-0">
                {copied === `s-${service.id}` ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
        )}

        {/* GhostAPK Login Pin */}
        {service.ghostapk_code && (
          <div data-testid={`dashboard-ghostapk-pin-${service.id}`}>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">GhostAPK Login Pin</p>
            <div className="flex items-center gap-1">
              <code className="text-sm font-mono font-semibold tracking-[0.2em] text-violet-700 dark:text-violet-300">{service.ghostapk_code}</code>
              <button onClick={() => copy(service.ghostapk_code, `g-${service.id}`)} className="text-gray-400 hover:text-blue-600 shrink-0">
                {copied === `g-${service.id}` ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
        )}

        {/* VPN Download Links */}
        {isVPN && (
          <div className="pt-1">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Download VPN Client</p>
            <div className="flex flex-wrap gap-1.5">
              {[
                { label: 'Windows', href: 'https://vpnclient.app/current/vpnclient/vpnclient.exe' },
                { label: 'Mac', href: 'https://vpnclient.app/current/vpnclient/vpnclient.dmg' },
                { label: 'Linux', href: 'https://vpnclient.app/current/vpnclient/vpnclient.run' },
                { label: 'iOS', href: 'https://apps.apple.com/app/id1506797696' },
                { label: 'Android', href: 'https://play.google.com/store/apps/details?id=com.vpn.client' },
              ].map(l => (
                <a key={l.label} href={l.href} target="_blank" rel="noopener noreferrer"
                  className="px-2.5 py-1 text-xs font-medium bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 rounded-md hover:bg-teal-100 dark:hover:bg-teal-900/50 transition">
                  {l.label}
                </a>
              ))}
            </div>
          </div>
        )}

        {/* Info Row */}
        <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 pt-2 border-t border-gray-100 dark:border-gray-800">
          <span>{service.max_connections || '?'} {isVPN ? 'device' : 'connection'}{(service.max_connections || 0) !== 1 ? 's' : ''}</span>
          <span>{expiryDate ? formatDate(expiryDate) : 'No expiry'}</span>
        </div>

        {/* Countdown Bar */}
        {expiryDate && !isExpired && (
          <CountdownBar expiryDate={expiryDate} />
        )}

        {/* Quick Renew */}
        {service.account_type === 'subscriber' && (
          <div className="flex gap-2 pt-1">
            <button onClick={handleQuickRenew}
              className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition ${
                isExpiringSoon || isExpired
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}>
              <RefreshCw className="w-4 h-4" />
              {isExpired ? 'Renew Now' : isExpiringSoon ? 'Renew Soon' : 'Renew'}
            </button>
            <Link to="/services" className="px-4 py-2 rounded-lg text-sm bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700">
              Details
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

function CountdownBar({ expiryDate }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  const now = new Date();
  const diffMs = expiryDate - now;
  const totalDays = 30; // Assume 30-day cycle for the progress bar
  const daysLeft = Math.max(0, diffMs / (1000 * 60 * 60 * 24));
  const percent = Math.min(100, Math.max(0, (daysLeft / totalDays) * 100));

  const barColor = percent > 50 ? 'bg-green-500' : percent > 20 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
      <div className={`h-1.5 rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${percent}%` }} />
    </div>
  );
}
