import { useTimezone, formatDate } from "../utils/timezone";
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { servicesAPI, productsAPI } from '../api/api';
import { useCartStore } from '../store/store';
import { ArrowLeft, Tv, Copy, Check, Eye, EyeOff, Package, X, Link2, Monitor, Radio, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { AutoRenewControl, AutoRenewReturn } from '../components/cmtv/AutoRenew'; // CMTV local change 2026-09-25

export default function ServicesPage() {
  const navigate = useNavigate();
  
  const { data: services, isLoading } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const response = await servicesAPI.getAll();
      return response.data;
    },
  });

  // Fetch products for renewal pricing
  const { data: products } = useQuery({
    queryKey: ['products'],
    queryFn: async () => {
      const response = await productsAPI.getAll();
      return response.data;
    },
  });

  // Fetch refunds setting (public endpoint, no auth required)
  const { data: refundsData, isLoading: refundsLoading } = useQuery({
    queryKey: ['refunds-enabled'],
    queryFn: async () => {
      // Use axios directly without auth interceptor for public endpoint
      const response = await fetch(`${process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001'}/api/refunds/enabled`);
      return response.json();
    },
  });

  // Show button if loading (optimistic) or if explicitly enabled
  const refundsEnabled = refundsLoading || refundsData?.enabled === true;
  
  // Debug log
  console.log('Refunds loading:', refundsLoading, 'Refunds data:', refundsData, 'Button visible:', refundsEnabled);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <AutoRenewReturn />{/* CMTV local change 2026-09-25: finishes auto-renew after PayPal approval */}
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/dashboard" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400">
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-8">My Services</h1>

        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : (() => {
          // Filter out credit add-ons (only show main reseller accounts and subscribers)
          const mainServices = services?.filter(s => !s.is_credit_addon) || [];
          
          return mainServices.length === 0 ? (
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
              <Tv className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">No services yet</h3>
              <p className="text-gray-600 dark:text-gray-400 mb-6">Purchase a subscription to get started</p>
              <Link to="/" className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700">
                Browse Products
              </Link>
            </div>
          ) : (
            <div className="space-y-6">
              {mainServices.map((service) => (
                <ServiceCard key={service.id} service={service} navigate={navigate} products={products} refundsEnabled={refundsEnabled} />
              ))}
            </div>
          );
        })()}
      </main>
    </div>
  );
}

function ServiceCard({ service, navigate, products, refundsEnabled }) {
  const [showPassword, setShowPassword] = useState(false);
  const [copied, setCopied] = useState(null);
  const [showRefundModal, setShowRefundModal] = useState(false);
  const [showRenewPicker, setShowRenewPicker] = useState(false);
  const { addRenewalItem } = useCartStore();

  // Get compatible products for this service (same panel type, subscriber products, not bundles/trials)
  // Get compatible products — try exact panel_index match first, fallback to same panel_type
  const exactMatch = (products || []).filter(p =>
    (!service.panel_type || p.panel_type === service.panel_type) &&
    p.panel_index === service.panel_index &&
    p.account_type === 'subscriber' && !p.is_bundle && !p.is_trial
  );
  const typeMatch = (products || []).filter(p =>
    (!service.panel_type || p.panel_type === service.panel_type) &&
    p.account_type === 'subscriber' && !p.is_bundle && !p.is_trial
  );
  const compatibleProducts = exactMatch.length > 0 ? exactMatch : typeMatch;
  
  const handleRenew = () => {
    const product = products?.find(p => p.id === service.product_id);
    
    if (product) {
      // Get the first available price (price keys may not match term_months)
      const priceEntries = Object.entries(product.prices || {});
      const termKey = priceEntries.length > 0 ? Number(priceEntries[0][0]) : 1;
      const price = priceEntries.length > 0 ? priceEntries[0][1] : 0;
      
      if (price <= 0) {
        // Price not found — show product picker instead
        if (compatibleProducts.length > 0) {
          setShowRenewPicker(true);
        } else {
          toast.error('No compatible products found. Please contact support.');
        }
        return;
      }
      
      addRenewalItem({
        product_id: service.product_id,
        product_name: service.product_name,
        term_months: termKey,
        price: price,
        account_type: service.account_type
      }, service.id, 'extend');
      
      navigate('/checkout');
    } else if (compatibleProducts.length > 0) {
      setShowRenewPicker(true);
    } else {
      toast.error('No compatible products found. Please contact support.');
    }
  };

  const handlePickProduct = (product, termKey, price) => {
    addRenewalItem({
      product_id: product.id,
      product_name: product.name,
      term_months: termKey,
      price: price,
      account_type: service.account_type
    }, service.id, 'extend');
    
    setShowRenewPicker(false);
    navigate('/checkout');
  };

  const copyToClipboard = (text, field) => {
    navigator.clipboard.writeText(text);
    setCopied(field);
    setTimeout(() => setCopied(null), 2000);
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
      case 'suspended':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
      case 'cancelled':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
      case 'refunded':
        return 'bg-gray-400 text-gray-800 dark:bg-gray-600 dark:text-gray-200';
      default:
        return 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200';
    }
  };

  return (
    <div className={`rounded-lg shadow-lg overflow-hidden ${
      service.status === 'refunded' 
        ? 'bg-gray-200 dark:bg-gray-800 opacity-75' 
        : 'bg-white dark:bg-gray-900'
    } ${
      service.account_type === 'reseller' ? 'border-2 border-purple-200 dark:border-purple-700' : ''
    }`}>
      <div className={`bg-gradient-to-r ${
        service.status === 'refunded'
          ? 'from-gray-500 to-gray-600'
          : service.account_type === 'reseller' 
            ? 'from-purple-600 to-purple-700' 
            : 'from-blue-600 to-blue-700'
      } p-4 sm:p-6 text-white`}>
        <div className="flex justify-between items-start">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg sm:text-2xl font-bold mb-1 sm:mb-2 truncate">
              {service.account_type === 'reseller' 
                ? (service.panel_name || `Server ${(service.panel_index || 0) + 1}`)
                : service.product_name
              }
            </h2>
            <p className={`text-sm ${service.account_type === 'reseller' ? 'text-purple-100' : 'text-blue-100'}`}>
              {service.account_type === 'subscriber' ? 'Subscriber Account' : 'Reseller Panel'}
            </p>
          </div>
          <span className={`px-2 sm:px-3 py-1 rounded-full text-xs sm:text-sm font-semibold flex-shrink-0 ${getStatusColor(service.status)}`}>
            {service.status}
          </span>
        </div>
      </div>

      <div className="p-4 sm:p-6">
        <div className="grid md:grid-cols-2 gap-4 sm:gap-6">
          {/* Connection Details */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {service.account_type === 'reseller' ? 'Reseller Panel Access' : 'Connection Details'}
            </h3>
            <div className="space-y-3">
              {/* Panel URL for resellers */}
              {service.account_type === 'reseller' && (
                <div>
                  <label className="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">Panel URL</label>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-gray-100 dark:bg-gray-800 px-3 py-2 rounded text-sm font-mono break-all">
                      {service.panel_url || 'Contact support for panel URL'}
                    </code>
                    {service.panel_url && (
                      <button
                        onClick={() => copyToClipboard(service.panel_url, 'panelurl')}
                        className="p-2 text-gray-600 dark:text-gray-400 hover:text-blue-600"
                      >
                        {copied === 'panelurl' ? <Check className="w-5 h-5 text-green-600" /> : <Copy className="w-5 h-5" />}
                      </button>
                    )}
                  </div>
                </div>
              )}
              
              <div>
                <label className="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">Username</label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-gray-100 dark:bg-gray-800 px-3 py-2 rounded text-sm font-mono">
                    {service.vpn_username || service.xtream_username || 'N/A'}
                  </code>
                  <button
                    onClick={() => copyToClipboard(service.vpn_username || service.xtream_username, 'username')}
                    className="p-2 text-gray-600 dark:text-gray-400 hover:text-blue-600"
                  >
                    {copied === 'username' ? <Check className="w-5 h-5 text-green-600" /> : <Copy className="w-5 h-5" />}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">Password</label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-gray-100 dark:bg-gray-800 px-3 py-2 rounded text-sm font-mono">
                    {showPassword ? (service.vpn_password || service.xtream_password) : '••••••••'}
                  </code>
                  <button
                    onClick={() => setShowPassword(!showPassword)}
                    className="p-2 text-gray-600 dark:text-gray-400 hover:text-blue-600"
                  >
                    {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                  <button
                    onClick={() => copyToClipboard(service.vpn_password || service.xtream_password, 'password')}
                    className="p-2 text-gray-600 dark:text-gray-400 hover:text-blue-600"
                  >
                    {copied === 'password' ? <Check className="w-5 h-5 text-green-600" /> : <Copy className="w-5 h-5" />}
                  </button>
                </div>
              </div>

              {/* Streaming Server URL (IPTV only) */}
              {service.streaming_url && service.panel_type !== 'ghostsurf' && (
                <div>
                  <label className="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">Server URL</label>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-gray-100 dark:bg-gray-800 px-3 py-2 rounded text-sm font-mono break-all">
                      {service.streaming_url}
                    </code>
                    <button
                      onClick={() => copyToClipboard(service.streaming_url, 'serverurl')}
                      className="p-2 text-gray-600 dark:text-gray-400 hover:text-blue-600"
                    >
                      {copied === 'serverurl' ? <Check className="w-5 h-5 text-green-600" /> : <Copy className="w-5 h-5" />}
                    </button>
                  </div>
                </div>
              )}

              {/* VPN Download Links */}
              {service.panel_type === 'ghostsurf' && (
                <div>
                  <label className="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">Download VPN Client</label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { label: 'Windows', href: 'https://vpnclient.app/current/vpnclient/vpnclient.exe' },
                      { label: 'Mac', href: 'https://vpnclient.app/current/vpnclient/vpnclient.dmg' },
                      { label: 'Linux', href: 'https://vpnclient.app/current/vpnclient/vpnclient.run' },
                      { label: 'iOS', href: 'https://apps.apple.com/app/id1506797696' },
                      { label: 'Google Play', href: 'https://play.google.com/store/apps/details?id=com.vpn.client' },
                      { label: 'Android APK', href: 'https://vpnclient.app/apk/VPNClient.apk' },
                    ].map(l => (
                      <a key={l.label} href={l.href} target="_blank" rel="noopener noreferrer"
                        className="px-3 py-2 text-sm font-medium bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 rounded-lg hover:bg-teal-100 dark:hover:bg-teal-900/50 border border-teal-200 dark:border-teal-800 transition">
                        {l.label}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Service Info (only for subscribers) */}
          {service.account_type === 'subscriber' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Service Information</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-600 dark:text-gray-400">Max Connections</label>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">{service.max_connections || 'N/A'}</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-600 dark:text-gray-400">Expiry Date</label>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    {service.expiry_date ? formatDate(service.expiry_date) : 'Lifetime'}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Renew and Refund buttons for subscribers */}
        {service.account_type === 'subscriber' && ['active', 'expired', 'suspended'].includes(service.status) && (
          <div className="mt-4 sm:mt-6 pt-4 sm:pt-6 border-t border-gray-200 dark:border-gray-700 flex flex-col sm:flex-row gap-3">
            <button
              onClick={handleRenew}
              className={`inline-flex items-center justify-center gap-2 px-4 sm:px-6 py-2.5 sm:py-3 text-white rounded-lg font-semibold text-sm sm:text-base ${service.status === 'active' ? 'bg-blue-600 hover:bg-blue-700' : 'bg-green-600 hover:bg-green-700'}`}
              data-testid="renew-service-btn"
            >
              <Package className="w-5 h-5" />
              {service.status === 'active' ? 'Renew Service' : 'Renew Now'}
            </button>
            {refundsEnabled && service.status === 'active' && (
              <button
                onClick={() => setShowRefundModal(true)}
                className="inline-flex items-center gap-2 px-6 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 font-semibold"
              >
                Request Refund
              </button>
            )}
          </div>
        )}
        
        {/* CMTV local change 2026-09-25: PayPal auto-renew */}
        {service.account_type === 'subscriber' && <AutoRenewControl service={service} products={products} />}

        {/* Refunded status message */}
        {service.status === 'refunded' && (
          <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
            <div className="bg-gray-100 dark:bg-gray-800 rounded-lg p-4 text-center">
              <p className="text-gray-700 dark:text-gray-300 font-semibold">
                💰 This service has been refunded
              </p>
              {service.refund_reason && (
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                  Reason: {service.refund_reason}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Setup Instructions (only for subscribers) */}
        {service.account_type !== 'reseller' && (
          <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Setup Instructions</h3>
            {service.setup_instructions ? (
              <div className="text-gray-700 dark:text-gray-200 whitespace-pre-wrap">
                {service.setup_instructions}
              </div>
            ) : (
              <ol className="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-200">
                <li>Download an IPTV player (IPTV Smarters Pro, TiviMate, etc.)</li>
                <li>Enter the server URL, username, and password above</li>
                <li>Start watching your favorite channels!</li>
              </ol>
            )}
          </div>
        )}

        {/* M3U / Playlist Links */}
        {service.account_type === 'subscriber' && service.streaming_url && service.xtream_username && (
          <PlaylistLinks service={service} />
        )}
      </div>
      
      {/* Refund Request Modal */}
      {showRefundModal && (
        <RefundRequestModal
          service={service}
          onClose={() => setShowRefundModal(false)}
        />
      )}

      {/* Renewal Product Picker Modal */}
      {showRenewPicker && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setShowRenewPicker(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()} data-testid="renew-picker-modal">
            <div className="p-5 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Select Renewal Package</h3>
              <button onClick={() => setShowRenewPicker(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">Choose a package to renew <strong>{service.xtream_username || service.product_name}</strong>:</p>
              {compatibleProducts.map(product => {
                const priceEntries = Object.entries(product.prices || {});
                const price = priceEntries.length > 0 ? priceEntries[0][1] : 0;
                const termKey = priceEntries.length > 0 ? Number(priceEntries[0][0]) : 1;
                return (
                  <button
                    key={product.id}
                    onClick={() => handlePickProduct(product, termKey, price)}
                    className="w-full text-left p-4 border border-gray-200 dark:border-gray-600 rounded-lg hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                    data-testid={`renew-product-${product.id}`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium text-gray-900 dark:text-white text-sm">{product.name}</div>
                        <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{product.max_connections || 1} connection{(product.max_connections || 1) > 1 ? 's' : ''}</div>
                      </div>
                      <div className="text-blue-600 dark:text-blue-400 font-bold">${Number(price).toFixed(2)}</div>
                    </div>
                  </button>
                );
              })}
              {compatibleProducts.length === 0 && (
                <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">No compatible packages found.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Refund Request Modal Component
function RefundRequestModal({ service, onClose }) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!reason.trim()) {
      toast.error('Please provide a reason for the refund request');
      return;
    }

    setSubmitting(true);
    
    try {
      // Get the product to find the actual price paid
      // For now, request the full order amount (backend will validate)
      // We'll use a reasonable default amount
      const refundAmount = 10.00; // Default amount, backend will validate against actual order
      
      await servicesAPI.requestRefund(service.order_id, refundAmount, reason);
      toast.success('Refund request submitted successfully! Our team will review it shortly.');
      onClose();
      window.location.reload(); // Refresh to show updated status
    } catch (error) {
      const errorMsg = error.response?.data?.detail || error.message;
      toast.error('Failed to submit refund request: ' + errorMsg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full">
        <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white">Request Refund</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
            <p className="text-sm text-yellow-800 dark:text-yellow-200">
              <strong>Service:</strong> {service.product_name}<br />
              <strong>Username:</strong> {service.xtream_username}
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Reason for Refund *
            </label>
            <textarea
              required
              rows="4"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Please explain why you're requesting a refund..."
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white resize-none"
            />
          </div>

          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
            <p className="text-sm text-blue-800 dark:text-blue-200">
              Your refund request will be reviewed by our team. You'll be notified via email once a decision is made.
            </p>
          </div>

          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 bg-red-600 text-white px-6 py-3 rounded-lg hover:bg-red-700 font-semibold disabled:opacity-50"
            >
              {submitting ? 'Submitting...' : 'Submit Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


function PlaylistLinks({ service }) {
  const [copied, setCopied] = useState('');
  const [showLinks, setShowLinks] = useState(false);

  const baseUrl = service.streaming_url?.replace(/\/$/, '');
  const fullBase = baseUrl?.startsWith('http') ? baseUrl : `http://${baseUrl}`;
  const user = service.xtream_username;
  const pass = service.xtream_password;

  const links = [
    {
      key: 'm3u',
      label: 'M3U Playlist',
      icon: FileText,
      url: `${fullBase}/get.php?username=${user}&password=${pass}&type=m3u_plus&output=ts`,
      desc: 'For VLC, IPTV Smarters, TiviMate, GSE Smart IPTV',
      color: 'text-green-600',
    },
    {
      key: 'epg',
      label: 'EPG / XMLTV',
      icon: Radio,
      url: `${fullBase}/xmltv.php?username=${user}&password=${pass}`,
      desc: 'Electronic Program Guide for your player',
      color: 'text-blue-600',
    },
  ];

  const copyLink = (url, key) => {
    navigator.clipboard.writeText(url);
    setCopied(key);
    toast.success('Link copied!');
    setTimeout(() => setCopied(''), 2000);
  };

  return (
    <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
      <button
        onClick={() => setShowLinks(!showLinks)}
        className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white mb-3 hover:text-blue-600 transition"
      >
        <Link2 className="w-5 h-5" />
        Playlist Links
        <span className="text-xs font-normal text-gray-500 ml-1">{showLinks ? '(hide)' : '(show)'}</span>
      </button>

      {showLinks && (
        <div className="space-y-3">
          {links.map((link) => {
            const Icon = link.icon;
            return (
              <div key={link.key} className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <Icon className={`w-4 h-4 ${link.color}`} />
                    <span className="font-medium text-gray-900 dark:text-white text-sm">{link.label}</span>
                  </div>
                  <button
                    onClick={() => copyLink(link.url, link.key)}
                    className="flex items-center gap-1 px-3 py-1 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700"
                  >
                    {copied === link.key ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                    {copied === link.key ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{link.desc}</p>
                <code className="block text-xs bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded px-2 py-1.5 font-mono break-all text-gray-700 dark:text-gray-300">
                  {link.url}
                </code>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
