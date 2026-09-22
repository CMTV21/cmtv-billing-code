import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { Save, Plus, Trash2, Server, X, Check, Package, Users, Layers, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

export default function AetherPanelManagement({ settings }) {
  const queryClient = useQueryClient();
  const [panels, setPanels] = useState(settings?.aether?.panels || []);
  const [showModal, setShowModal] = useState(false);
  const [editingPanel, setEditingPanel] = useState(null);
  const [busy, setBusy] = useState({});
  const [tokenInfo, setTokenInfo] = useState({});

  React.useEffect(() => {
    const serverPanels = settings?.aether?.panels || [];
    if (serverPanels.length > 0) setPanels(serverPanels);
  }, [settings?.aether?.panels]);

  const setBusyFor = (index, action) => setBusy((b) => ({ ...b, [index]: action }));
  const persist = async () => {
    await adminAPI.updateSettings({ ...settings, aether: { panels } });
    queryClient.invalidateQueries(['admin-settings']);
  };

  const updateMutation = useMutation({
    mutationFn: (data) => adminAPI.updateSettings({ ...settings, aether: { panels: data } }),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-settings']);
      toast.success('Aether panels saved!');
    },
    onError: (error) => toast.error('Failed to save: ' + (error.response?.data?.detail || error.message)),
  });

  const handleTest = async (index) => {
    setBusyFor(index, 'test');
    try {
      await persist();
      const resp = await adminAPI.testAether(index);
      setTokenInfo((t) => ({ ...t, [index]: resp.data }));
      if (resp.data.missing_scopes?.length) {
        toast.warning(resp.data.message);
      } else {
        toast.success(resp.data.message || 'Connection successful!');
      }
    } catch (err) {
      toast.error('Connection failed: ' + (err.response?.data?.detail || err.message));
    }
    setBusyFor(index, null);
  };

  const handlePackages = async (index) => {
    setBusyFor(index, 'packages');
    try {
      await persist();
      const resp = await adminAPI.getAetherPackages(index);
      toast.info(`Packages: ${resp.data.count} official, ${resp.data.trial_count} trial, ${resp.data.extension_packages?.length || 0} extension`);
    } catch (err) {
      toast.error('Failed: ' + (err.response?.data?.detail || err.message));
    }
    setBusyFor(index, null);
  };

  const handleSyncBouquets = async (index) => {
    setBusyFor(index, 'bouquets');
    try {
      await persist();
      const resp = await adminAPI.getAetherBouquets(index);
      queryClient.invalidateQueries(['admin-settings']);
      queryClient.invalidateQueries(['bouquets']);
      toast.success(`${resp.data.count} bouquets synced from Aether packages`);
    } catch (err) {
      toast.error('Failed: ' + (err.response?.data?.detail || err.message));
    }
    setBusyFor(index, null);
  };

  const handleSyncUsers = async (index) => {
    setBusyFor(index, 'users');
    try {
      await persist();
      const resp = await adminAPI.syncAetherUsers(index);
      toast.success(`Lines synced: ${resp.data.synced} new, ${resp.data.updated} updated (${resp.data.total} total)`);
      queryClient.invalidateQueries(['imported-users']);
    } catch (err) {
      toast.error('Failed: ' + (err.response?.data?.detail || err.message));
    }
    setBusyFor(index, null);
  };

  const handleAddPanel = (panelData) => {
    if (editingPanel !== null) {
      const updated = [...panels];
      updated[editingPanel] = { ...updated[editingPanel], ...panelData };
      setPanels(updated);
    } else {
      setPanels([...panels, panelData]);
    }
    setShowModal(false);
    setEditingPanel(null);
  };

  const handleRemovePanel = (index) => {
    if (window.confirm('Remove this Aether panel?')) {
      setPanels(panels.filter((_, i) => i !== index));
    }
  };

  const btn = {
    violet: 'px-3 py-1.5 bg-violet-600 text-white text-sm rounded hover:bg-violet-700 disabled:opacity-50',
    blue: 'px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50',
    indigo: 'px-3 py-1.5 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50',
    green: 'px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50',
    gray: 'px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 disabled:opacity-50',
    red: 'px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50',
  };

  return (
    <div className="space-y-6" data-testid="aether-panel-management">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
          <Server className="w-5 h-5 text-violet-600" />
          Aether Panel Integration
        </h3>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Connect Aether panels via their <code>/api/v1</code> Reseller API. Create an API token on the panel's
          <strong> API Tokens</strong> page with scopes: <code>lines:read</code>, <code>lines:create</code>, <code>lines:renew</code>,
          <code> lines:update</code>, <code>lines:credentials</code>, <code>packages:read</code> (plus <code>credits:read</code> for balance alerts).
        </p>
      </div>

      {panels.map((panel, index) => (
        <div key={index} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-5" data-testid={`aether-panel-card-${index}`}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <Server className="w-5 h-5 text-violet-600" />
              <div>
                <h4 className="font-semibold text-gray-900 dark:text-white">{panel.name || `Aether Panel ${index + 1}`}</h4>
                <p className="text-xs text-gray-500 dark:text-gray-400">{panel.panel_url}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={() => handleTest(index)} disabled={!!busy[index]} className={btn.violet} data-testid={`aether-test-btn-${index}`}>
                {busy[index] === 'test' ? 'Testing...' : 'Test'}
              </button>
              <button onClick={() => handlePackages(index)} disabled={!!busy[index]} className={btn.blue} data-testid={`aether-packages-btn-${index}`}>
                <Package className="w-4 h-4 inline mr-1" />{busy[index] === 'packages' ? '...' : 'Packages'}
              </button>
              <button onClick={() => handleSyncBouquets(index)} disabled={!!busy[index]} className={btn.indigo} data-testid={`aether-bouquets-btn-${index}`}>
                <Layers className="w-4 h-4 inline mr-1" />{busy[index] === 'bouquets' ? '...' : 'Bouquets'}
              </button>
              <button onClick={() => handleSyncUsers(index)} disabled={!!busy[index]} className={btn.green} data-testid={`aether-sync-users-btn-${index}`}>
                <Users className="w-4 h-4 inline mr-1" />{busy[index] === 'users' ? 'Syncing...' : 'Sync Users'}
              </button>
              <button onClick={() => { setEditingPanel(index); setShowModal(true); }} className={btn.gray} data-testid={`aether-edit-btn-${index}`}>Edit</button>
              <button onClick={() => handleRemovePanel(index)} className={btn.red} data-testid={`aether-remove-btn-${index}`}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm text-gray-600 dark:text-gray-400">
            <div>Token: <span className="font-mono text-gray-900 dark:text-white">{panel.api_token ? panel.api_token.slice(0, 12) + '…' : 'Not set'}</span></div>
            <div>Streaming DNS: <span className="font-medium text-gray-900 dark:text-white">{panel.streaming_url || 'Auto (from line credentials)'}</span></div>
            {panel.bouquets?.length > 0 && <div>Bouquets: <span className="font-medium text-gray-900 dark:text-white">{panel.bouquets.length} synced</span></div>}
          </div>
          {tokenInfo[index] && (
            <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 flex flex-wrap gap-x-4 gap-y-1" data-testid={`aether-token-info-${index}`}>
              <span className="flex items-center gap-1"><ShieldCheck className="w-3.5 h-3.5 text-green-600" /> {tokenInfo[index].data?.kind} token · {tokenInfo[index].data?.subject?.username}</span>
              {tokenInfo[index].data?.balance != null && <span>Balance: <strong>{parseFloat(tokenInfo[index].data.balance).toFixed(2)}</strong> credits</span>}
              <span>Scopes: {tokenInfo[index].data?.scopes?.length || 0}</span>
              {tokenInfo[index].missing_scopes?.length > 0 && (
                <span className="text-amber-600 dark:text-amber-400">Missing: {tokenInfo[index].missing_scopes.join(', ')}</span>
              )}
            </div>
          )}
        </div>
      ))}

      <div className="flex gap-3">
        <button onClick={() => { setEditingPanel(null); setShowModal(true); }}
          className="flex items-center gap-2 bg-violet-600 text-white px-4 py-2.5 rounded-lg hover:bg-violet-700 font-semibold" data-testid="aether-add-panel-btn">
          <Plus className="w-5 h-5" /> Add Aether Panel
        </button>
        {panels.length > 0 && (
          <button onClick={() => updateMutation.mutate(panels)} disabled={updateMutation.isPending}
            className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 font-semibold disabled:opacity-50" data-testid="aether-save-panels-btn">
            <Save className="w-5 h-5" /> {updateMutation.isPending ? 'Saving...' : 'Save Panels'}
          </button>
        )}
      </div>

      {showModal && (
        <PanelModal
          panel={editingPanel !== null ? panels[editingPanel] : null}
          onSave={handleAddPanel}
          onClose={() => { setShowModal(false); setEditingPanel(null); }}
        />
      )}
    </div>
  );
}

function PanelModal({ panel, onSave, onClose }) {
  const [form, setForm] = useState({
    name: panel?.name || '',
    panel_url: panel?.panel_url || '',
    api_token: panel?.api_token || '',
    streaming_url: panel?.streaming_url || '',
    ssl_verify: panel?.ssl_verify !== false,
    active: panel?.active !== false,
  });
  const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white';

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.panel_url || !form.api_token) {
      toast.error('Panel URL and API Token are required');
      return;
    }
    onSave(form);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" data-testid="aether-panel-modal">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-lg p-6 m-4">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{panel ? 'Edit Aether Panel' : 'Add Aether Panel'}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Panel Name</label>
            <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="My Aether Panel" className={inputCls} data-testid="aether-panel-name-input" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Panel URL *</label>
            <input type="text" value={form.panel_url} onChange={(e) => setForm({ ...form, panel_url: e.target.value })} placeholder="https://bestpanel.xyz" required className={inputCls} data-testid="aether-panel-url-input" />
            <p className="text-xs text-gray-500 mt-1">The address you use to sign in to the panel (the API lives at <code>/api/v1</code>)</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">API Token *</label>
            <input type="password" value={form.api_token} onChange={(e) => setForm({ ...form, api_token: e.target.value })} placeholder="pmk_..." required className={inputCls} data-testid="aether-api-token-input" />
            <p className="text-xs text-gray-500 mt-1">Created on the panel's API Tokens page — shown once at creation. Reseller and admin tokens both work.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Streaming DNS (optional)</label>
            <input type="text" value={form.streaming_url} onChange={(e) => setForm({ ...form, streaming_url: e.target.value })} placeholder="http://stream.example.com" className={inputCls} data-testid="aether-streaming-url-input" />
            <p className="text-xs text-gray-500 mt-1">Leave blank to use the host the panel reports in each line's connection details</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={form.ssl_verify} onChange={(e) => setForm({ ...form, ssl_verify: e.target.checked })} data-testid="aether-ssl-verify-checkbox" />
            Verify TLS certificate (recommended)
          </label>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700">Cancel</button>
            <button type="submit" className="flex items-center gap-2 bg-violet-600 text-white px-4 py-2 rounded-lg hover:bg-violet-700 font-semibold" data-testid="aether-panel-submit-btn">
              <Check className="w-4 h-4" /> {panel ? 'Update Panel' : 'Add Panel'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
