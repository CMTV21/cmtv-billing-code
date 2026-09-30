import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import api from '../api/api';
import { ArrowLeft } from 'lucide-react';
import BrandingSettings from '../components/BrandingSettings';
import PanelManagement from '../components/PanelManagement';
import XuiOnePanelManagement from '../components/XuiOnePanelManagement';
import PaymentGatewaySettings from '../components/PaymentGatewaySettings';
import EmailProviderSettings from '../components/EmailProviderSettings';
import CreditReferralSettings from '../components/CreditReferralSettings';
import LicenseSettings from '../components/LicenseSettings';
import AdminPasswordChange from '../components/AdminPasswordChange';
import TwoFactorSetup from '../components/TwoFactorSetup';
import ChatbotSettings from '../components/ChatbotSettings';
import TimezoneSettings from '../components/TimezoneSettings';
import RefundSettings from '../components/RefundSettings';
import UpdateManager from '../components/UpdateManager';
import BackupManager from '../components/BackupManager';
import RecaptchaSettings from '../components/RecaptchaSettings';
import NotificationSettings from '../components/NotificationSettings';
import OneStreamPanelManagement from '../components/OneStreamPanelManagement';
import NxtDashPanelManagement from '../components/NxtDashPanelManagement';
import GhostSurfPanelManagement from '../components/GhostSurfPanelManagement';
import AetherPanelManagement from '../components/AetherPanelManagement';
import GoldPanelManagement from '../components/GoldPanelManagement';
import InvoiceSettings from '../components/InvoiceSettings';
import SEOSettings from '../components/SEOSettings';
import ShippingSettings from '../components/ShippingSettings';
import { toast } from 'sonner';

export default function AdminSettings() {
  const [activeTab, setActiveTab] = useState('panels');
  
  const { data: settings, isLoading } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: async () => {
      const response = await adminAPI.getSettings();
      return response.data;
    },
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600">
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-8">System Settings</h1>

        <div className="grid lg:grid-cols-4 gap-6">
          {/* Sidebar Navigation */}
          <div className="lg:col-span-1">
            <nav className="bg-white dark:bg-gray-900 rounded-lg shadow p-2 space-y-1">
              <button
                onClick={() => setActiveTab('panels')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'panels' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                XtreamUI Panels
              </button>
              <button
                onClick={() => setActiveTab('xuione')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'xuione' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                XuiOne Panels
              </button>
              <button
                onClick={() => setActiveTab('onestream')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium flex items-center justify-between ${
                  activeTab === 'onestream' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                1-Stream Panels
              </button>
              <button
                onClick={() => setActiveTab('nxtdash')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'nxtdash' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                NXT Dash Panels
              </button>
              <button
                onClick={() => setActiveTab('aether')}
                data-testid="settings-tab-aether"
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium flex items-center justify-between ${
                  activeTab === 'aether' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Aether Panels
                <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                  activeTab === 'aether' ? 'bg-white/20 text-white' : 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300'
                }`}>New</span>
              </button>
              <button
                onClick={() => setActiveTab('gold')}
                data-testid="settings-tab-gold"
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium flex items-center justify-between ${
                  activeTab === 'gold' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Gold Panels
                <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                  activeTab === 'gold' ? 'bg-white/20 text-white' : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                }`}>New</span>
              </button>
              <button
                onClick={() => setActiveTab('ghostsurf')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'ghostsurf' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                GhostSurf VPN
              </button>
              <button
                onClick={() => setActiveTab('shipping')}
                data-testid="settings-tab-shipping"
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium flex items-center justify-between ${
                  activeTab === 'shipping' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Shipping
                <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                  activeTab === 'shipping' ? 'bg-white/20 text-white' : 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300'
                }`}>New</span>
              </button>
              <button
                onClick={() => setActiveTab('branding')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'branding' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Branding
              </button>
              <button
                onClick={() => setActiveTab('payment')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'payment' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Payment Gateways
              </button>
              <button
                onClick={() => setActiveTab('email')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'email' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Email
              </button>
              <button
                onClick={() => setActiveTab('credits')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'credits' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Credits & Referrals
              </button>
              <button
                onClick={() => setActiveTab('notifications')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'notifications' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Notifications
              </button>
              <button
                onClick={() => setActiveTab('refunds')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'refunds' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Refunds
              </button>
              <button
                onClick={() => setActiveTab('invoices')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'invoices' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Invoices
              </button>
              <button
                onClick={() => setActiveTab('account')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'account' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                My Account
              </button>
              <button
                onClick={() => setActiveTab('2fa')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === '2fa' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Two-Factor Auth
              </button>
              <button
                onClick={() => setActiveTab('recaptcha')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'recaptcha' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                reCAPTCHA
              </button>
              <button
                onClick={() => setActiveTab('currency')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'currency' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Currency
              </button>
              <button
                onClick={() => setActiveTab('timezone')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'timezone' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Timezone
              </button>
              <button
                onClick={() => setActiveTab('license')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'license' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                License
              </button>
              <button
                onClick={() => setActiveTab('updates')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'updates' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Updates
              </button>
              <button
                onClick={() => setActiveTab('backups')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'backups' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Backups
              </button>
              <button
                onClick={() => setActiveTab('seo')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'seo' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                SEO
              </button>
              <button
                onClick={() => setActiveTab('chatbot')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'chatbot' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                AI Chatbot
              </button>
              <button
                onClick={() => setActiveTab('launcher')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium flex items-center justify-between ${
                  activeTab === 'launcher' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Launcher API
                <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                  activeTab === 'launcher' ? 'bg-white/20 text-white' : 'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300'
                }`}>New</span>
              </button>
              <button
                onClick={() => setActiveTab('terms')}
                className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium ${
                  activeTab === 'terms' ? 'bg-blue-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                Terms & Conditions
              </button>
            </nav>
          </div>

          {/* Content Area */}
          <div className="lg:col-span-3 bg-white dark:bg-gray-900 rounded-lg shadow">
            <div className="p-6">
            {/* Panels Tab - Uses PanelManagement component */}
            {activeTab === 'panels' && (
              <PanelManagement settings={settings} />
            )}

            {/* XuiOne Panels Tab */}
            {activeTab === 'xuione' && (
              <XuiOnePanelManagement settings={settings} />
            )}

            {/* 1-Stream Panels Tab */}
            {activeTab === 'onestream' && (
              <OneStreamPanelManagement settings={settings} />
            )}

            {/* NXT Dash Panels Tab */}
            {activeTab === 'nxtdash' && (
              <NxtDashPanelManagement settings={settings} />
            )}

            {/* GhostSurf VPN Tab */}
            {activeTab === 'ghostsurf' && (
              <GhostSurfPanelManagement settings={settings} />
            )}

            {/* Aether Tab */}
            {activeTab === 'aether' && (
              <AetherPanelManagement settings={settings} />
            )}

            {/* Gold Tab */}
            {activeTab === 'gold' && (
              <GoldPanelManagement settings={settings} />
            )}

            {/* Shipping Tab */}
            {activeTab === 'shipping' && (
              <ShippingSettings onGoToCurrency={() => setActiveTab('currency')} />
            )}

            {/* Branding Tab */}
            {activeTab === 'branding' && (
              <BrandingSettings settings={settings} />
            )}

            {/* Payment Gateway Tab */}
            {activeTab === 'payment' && (
              <PaymentGatewaySettings settings={settings} />
            )}

            {/* Email Tab (combined SMTP + Provider) */}
            {activeTab === 'email' && (
              <EmailProviderSettings settings={settings} />
            )}

            {/* Credits & Referrals Tab */}
            {activeTab === 'credits' && (
              <CreditReferralSettings settings={settings} />
            )}

            {/* Notifications Tab */}
            {activeTab === 'notifications' && (
              <NotificationSettings settings={settings} />
            )}
            
            {/* Refunds Tab */}
            {activeTab === 'refunds' && (
              <RefundSettings settings={settings} />
            )}

            {/* Invoices Tab */}
            {activeTab === 'invoices' && (
              <InvoiceSettings settings={settings} />
            )}
            
            {/* My Account Tab */}
            {activeTab === 'account' && (
              <AdminPasswordChange />
            )}
            
            {/* Two-Factor Auth Tab */}
            {activeTab === '2fa' && (
              <TwoFactorSetup />
            )}
            
            {/* reCAPTCHA Tab */}
            {activeTab === 'recaptcha' && (
              <RecaptchaSettings settings={settings} />
            )}

            {/* Currency Tab */}
            {activeTab === 'currency' && (
              <CurrencySettings settings={settings} />
            )}

            {/* License Tab */}
            {activeTab === 'license' && (
              <LicenseSettings settings={settings} />
            )}
            
            {/* Updates Tab */}
            {activeTab === 'updates' && (
              <UpdateManager />
            )}
            
            {/* Backups Tab */}
            {activeTab === 'backups' && (
              <BackupManager />
            )}

            {/* SEO Tab */}
            {activeTab === 'seo' && (
              <SEOSettings settings={settings} />
            )}

            {activeTab === 'timezone' && (
              <TimezoneSettings settings={settings} />
            )}

            {activeTab === 'chatbot' && (
              <ChatbotSettings settings={settings} />
            )}

            {activeTab === 'launcher' && (
              <LauncherKeySettings />
            )}

            {activeTab === 'terms' && (
              <TermsSettings settings={settings} />
            )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}


function LauncherKeySettings() {
  const [keys, setKeys] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [label, setLabel] = React.useState('');
  const [newKey, setNewKey] = React.useState(null);

  const fetchKeys = async () => {
    try {
      const resp = await api.get('/api/launcher/admin/keys');
      setKeys(resp.data);
    } catch (err) {
      console.error('Failed to fetch launcher keys:', err);
    }
    setLoading(false);
  };

  React.useEffect(() => { fetchKeys(); }, []);

  const createKey = async () => {
    setCreating(true);
    try {
      const resp = await api.post('/api/launcher/admin/keys', { label: label || 'Launcher Key' });
      setNewKey(resp.data.api_key);
      setLabel('');
      fetchKeys();
    } catch (err) {
      console.error('Failed to create launcher key:', err);
      alert('Failed to create key: ' + (err.response?.data?.detail || err.message));
    }
    setCreating(false);
  };

  const revokeKey = async (keyId) => {
    if (!window.confirm('Revoke this API key? Launchers using it will stop working.')) return;
    try {
      await api.delete(`/api/launcher/admin/keys/${keyId}`);
      fetchKeys();
    } catch (err) {
      console.error('Failed to revoke key:', err);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Launcher API Keys</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400">Generate API keys for TV/STB launcher apps. Keys authenticate all launcher API requests.</p>
      </div>

      {/* Create new key */}
      <div className="flex gap-3">
        <input
          type="text" value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder="Key label (e.g. Android Launcher)"
          className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm"
          data-testid="launcher-key-label"
        />
        <button onClick={createKey} disabled={creating}
          className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 text-sm font-medium"
          data-testid="create-launcher-key-btn"
        >
          {creating ? 'Generating...' : 'Generate Key'}
        </button>
      </div>

      {/* New key display */}
      {newKey && (
        <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-300 dark:border-green-700 rounded-lg">
          <p className="text-sm font-bold text-green-800 dark:text-green-300 mb-2">New API Key — copy it now (shown only once):</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm font-mono bg-white dark:bg-gray-800 px-3 py-2 rounded border border-green-300 dark:border-green-600 text-gray-900 dark:text-white break-all select-all">{newKey}</code>
            <button onClick={() => { navigator.clipboard.writeText(newKey); }}
              className="px-3 py-2 bg-green-600 text-white rounded text-sm hover:bg-green-700">Copy</button>
          </div>
          <button onClick={() => setNewKey(null)} className="text-xs text-green-600 dark:text-green-400 mt-2 hover:underline">Dismiss</button>
        </div>
      )}

      {/* Keys list */}
      {loading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : keys.length === 0 ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg">
          No API keys yet. Generate one to enable the launcher API.
        </div>
      ) : (
        <div className="space-y-3">
          {keys.map((k) => (
            <div key={k.id} className={`flex items-center justify-between p-4 rounded-lg border ${k.status === 'revoked' ? 'bg-red-50 dark:bg-red-900/10 border-red-200 dark:border-red-800 opacity-60' : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700'}`}>
              <div>
                <p className="font-medium text-gray-900 dark:text-white">{k.label || 'Unnamed Key'}</p>
                <p className="text-xs text-gray-500 font-mono">{k.prefix}</p>
                <p className="text-xs text-gray-400">{k.status === 'revoked' ? 'Revoked' : `Last used: ${k.last_used ? new Date(k.last_used).toLocaleString() : 'Never'}`}</p>
              </div>
              {k.status !== 'revoked' && (
                <button onClick={() => revokeKey(k.id)} className="px-3 py-1 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded border border-red-300 dark:border-red-700">Revoke</button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* API docs summary */}
      <div className="mt-6 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <h4 className="text-sm font-bold text-gray-900 dark:text-white mb-2">Launcher API Endpoints</h4>
        <div className="text-xs text-gray-600 dark:text-gray-400 font-mono space-y-1">
          <p><span className="text-blue-600">GET</span> /api/launcher/config — Enabled gateways & branding</p>
          <p><span className="text-blue-600">GET</span> /api/launcher/packages — Purchasable packages</p>
          <p><span className="text-green-600">POST</span> /api/launcher/checkout — Create order → checkout URL</p>
          <p><span className="text-blue-600">GET</span> /api/launcher/order/:id — Poll payment status</p>
          <p><span className="text-blue-600">GET</span> /api/launcher/account — Device line status</p>
          <p className="mt-2 text-gray-500">All require <code>X-Launcher-Key</code> header</p>
        </div>
      </div>
    </div>
  );
}



function TermsSettings({ settings }) {
  const [enabled, setEnabled] = React.useState(settings?.terms?.enabled || false);
  const [title, setTitle] = React.useState(settings?.terms?.title || 'Terms and Conditions');
  const [content, setContent] = React.useState(settings?.terms?.content || '');
  const [saving, setSaving] = React.useState(false);
  const [sourceMode, setSourceMode] = React.useState(false);
  const editorRef = React.useRef(null);

  React.useEffect(() => {
    if (settings?.terms) {
      setEnabled(settings.terms.enabled || false);
      setTitle(settings.terms.title || 'Terms and Conditions');
      setContent(settings.terms.content || '');
    }
  }, [settings]);

  React.useEffect(() => {
    if (!sourceMode && editorRef.current && editorRef.current.innerHTML !== content) {
      editorRef.current.innerHTML = content || '';
    }
  }, [content, sourceMode]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put('/api/admin/settings', {
        ...settings,
        terms: { enabled, title, content }
      });
      alert('Terms saved!');
    } catch (err) {
      alert('Failed to save: ' + (err.response?.data?.detail || err.message));
    }
    setSaving(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Terms & Conditions</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400">When enabled, customers must agree to these terms before completing checkout.</p>
      </div>

      {/* Enable toggle */}
      <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <div>
          <p className="font-medium text-gray-900 dark:text-white">Require Terms Agreement</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">Show checkbox on checkout that customers must accept</p>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="sr-only peer" data-testid="terms-enabled-toggle" />
          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>

      {/* Title */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Title</label>
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
          className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          data-testid="terms-title-input" />
      </div>

      {/* Content editor */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Content</label>
          <button type="button" onClick={() => setSourceMode(!sourceMode)}
            className={`px-3 py-1 text-xs rounded font-medium ${sourceMode ? 'bg-blue-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>
            {sourceMode ? 'Visual' : 'HTML'}
          </button>
        </div>
        {sourceMode ? (
          <textarea value={content} onChange={(e) => setContent(e.target.value)}
            className="w-full px-4 py-3 bg-gray-950 text-green-400 font-mono text-sm border border-gray-300 dark:border-gray-600 rounded-lg outline-none resize-none"
            rows={15} spellCheck={false} placeholder="<h2>Terms and Conditions</h2><p>...</p>" data-testid="terms-html-editor" />
        ) : (
          <div
            ref={editorRef}
            contentEditable
            onInput={() => setContent(editorRef.current?.innerHTML || '')}
            className="w-full min-h-[300px] px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white outline-none overflow-auto prose dark:prose-invert max-w-none"
            data-testid="terms-visual-editor"
            suppressContentEditableWarning
          />
        )}
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Supports HTML. Use headings, lists, links, etc.</p>
      </div>

      <button onClick={handleSave} disabled={saving}
        className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
        data-testid="save-terms-btn">
        {saving ? 'Saving...' : 'Save Terms'}
      </button>
    </div>
  );
}



function CurrencySettings({ settings }) {
  const [selected, setSelected] = React.useState(settings?.currency || 'USD');
  const [loading, setLoading] = React.useState(false);
  const queryClient = React.useMemo(() => require('@tanstack/react-query').useQueryClient, []);

  const currencies = [
    { code: 'USD', symbol: '$', name: 'US Dollar' },
    { code: 'CAD', symbol: 'C$', name: 'Canadian Dollar' },
    { code: 'EUR', symbol: '\u20ac', name: 'Euro' },
  ];

  const current = settings?.currency || 'USD';

  const handleChange = async () => {
    if (selected === current) return;
    if (!window.confirm(`Change currency from ${current} to ${selected}?\n\nThis will convert ALL existing product prices and shipping rates (rate table + Shippo flat markup) using current exchange rates. Live carrier quotes will be shown in ${selected} from now on. This action cannot be easily undone.`)) return;
    setLoading(true);
    try {
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/admin/currency`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ currency: selected })
      });
      const data = await res.json();
      if (res.ok) {
        toast.info(`${data.message}\n\nConversion factor: ${data.conversion_factor}`);
        window.location.reload();
      } else {
        toast.error('Error: ' + (data.detail || 'Failed'));
      }
    } catch (e) {
      toast.error('Error: ' + e.message);
    }
    setLoading(false);
  };

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Currency</h2>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">Set the system-wide currency for all prices, invoices and shipping (shipping rates inherit this setting).</p>

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        <div className="mb-4">
          <p className="text-sm text-gray-700 dark:text-gray-300">Current currency: <span className="font-bold text-lg">{current}</span></p>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-6">
          {currencies.map((c) => (
            <button key={c.code} type="button"
              onClick={() => setSelected(c.code)}
              className={`p-4 rounded-lg border-2 text-center transition ${
                selected === c.code
                  ? 'border-blue-600 bg-blue-50 dark:bg-blue-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-400'
              }`}>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{c.symbol}</p>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">{c.code}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">{c.name}</p>
            </button>
          ))}
        </div>

        {selected !== current && (
          <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-4">
            <p className="text-sm text-amber-800 dark:text-amber-200">
              <strong>Warning:</strong> Changing currency will convert all existing product prices from {current} to {selected} using current exchange rates. Review your prices after conversion.
            </p>
          </div>
        )}

        <button onClick={handleChange}
          disabled={loading || selected === current}
          className="flex items-center gap-2 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-semibold disabled:opacity-50">
          {loading ? 'Converting...' : selected === current ? `Current: ${current}` : `Switch to ${selected}`}
        </button>
      </div>
    </div>
  );
}
