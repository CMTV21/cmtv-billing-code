import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { Save, Plus, Trash2, Server, X, Check, Package, RefreshCw, Coins, Info } from 'lucide-react';
import { toast } from 'sonner';

export default function GoldPanelManagement({ settings }) {
  const queryClient = useQueryClient();
  const [panels, setPanels] = useState(settings?.gold?.panels || []);
  const [showModal, setShowModal] = useState(false);
  const [editingPanel, setEditingPanel] = useState(null);
  const [busy, setBusy] = useState({});
  const [info, setInfo] = useState({});

  React.useEffect(() => {
    const serverPanels = settings?.gold?.panels || [];
    if (serverPanels.length > 0) setPanels(serverPanels);
  }, [settings?.gold?.panels]);

  const setBusyFor = (index, action) => setBusy((b) => ({ ...b, [index]: action }));
  const persist = async () => {
    await adminAPI.updateSettings({ ...settings, gold: { panels } });
    queryClient.invalidateQueries(['admin-settings']);
  };

  const updateMutation = useMutation({
    mutationFn: (data) => adminAPI.updateSettings({ ...settings, gold: { panels: data } }),
    onSuccess: () => { queryClient.invalidateQueries(['admin-settings']); toast.success('Gold panels saved!'); },
    onError: (error) => toast.error('Failed to save: ' + (error.response?.data?.detail || error.message)),
  });

  const run = async (index, action, fn) => {
    setBusyFor(index, action);
    try { await persist(); await fn(); } catch (err) { toast.error('Failed: ' + (err.response?.data?.detail || err.message)); }
    setBusyFor(index, null);
  };

  const handleTest = (index) => run(index, 'test', async () => {
    const resp = await adminAPI.testGold(index);
    setInfo((t) => ({ ...t, [index]: resp.data }));
    toast.success(resp.data.message || 'Connection successful!');
  });
  const handlePackages = (index) => run(index, 'packages', async () => {
    const resp = await adminAPI.getGoldPackages(index);
    queryClient.invalidateQueries(['gold-packages']);
    toast.info(`${resp.data.bouquets.length} Gold packages × 4 terms = ${resp.data.count} sellable options`);
  });
  const handleRefresh = (index) => run(index, 'refresh', async () => {
    const resp = await adminAPI.refreshGoldUsers(index);
    queryClient.invalidateQueries(['imported-users']);
    toast.success(`Devices refreshed: ${resp.data.synced} new, ${resp.data.updated} updated (${resp.data.total} known${resp.data.errors ? `, ${resp.data.errors} not found` : ''})`);
  });

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

  const handleRemovePanel = async (index) => {
    const panel = panels[index];
    if (!window.confirm(`Remove Gold panel "${panel?.name || panel?.panel_url || index + 1}"? Its imported users and their service records will be deleted from billing.`)) return;
    const remaining = panels.filter((_, i) => i !== index);
    setBusyFor(index, 'remove');
    try {
      await adminAPI.updateSettings({ ...settings, gold: { panels: remaining } });
      setPanels(remaining);
      queryClient.invalidateQueries(['admin-settings']);
      toast.success('Gold panel removed');
    } catch (error) {
      toast.error('Failed to remove panel: ' + (error.response?.data?.detail || error.message));
    }
    setBusyFor(index, null);
  };

  const btn = {
    amber: 'px-3 py-1.5 bg-amber-600 text-white text-sm rounded hover:bg-amber-700 disabled:opacity-50',
    blue: 'px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50',
    green: 'px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50',
    gray: 'px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 disabled:opacity-50',
    red: 'px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50',
  };

  return (
    <div className="space-y-6" data-testid="gold-panel-management">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
          <Server className="w-5 h-5 text-amber-600" /> Gold Panel Integration
        </h3>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Connect Gold panels via their reseller <code>api.php</code> key. Products are sold as <strong>M3U devices</strong>: pick a Gold package and a 1 / 3 / 6 / 12-month term; the panel generates the username & password and we email the customer their playlist.
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2 flex items-start gap-1.5"><Info className="w-3.5 h-3.5 mt-0.5 shrink-0" /> The Gold API cannot list existing users or delete devices — "Refresh" re-reads every device billing already knows, and cancelling a service disables the device.</p>
      </div>

      {panels.map((panel, index) => (
        <div key={index} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-5" data-testid={`gold-panel-card-${index}`}>
          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <div className="flex items-center gap-3">
              <Server className="w-5 h-5 text-amber-600" />
              <div>
                <h4 className="font-semibold text-gray-900 dark:text-white">{panel.name || `Gold Panel ${index + 1}`}</h4>
                <p className="text-xs text-gray-500 dark:text-gray-400">{panel.panel_url}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={() => handleTest(index)} disabled={!!busy[index]} className={btn.amber} data-testid={`gold-test-btn-${index}`}>{busy[index] === 'test' ? 'Testing...' : 'Test'}</button>
              <button onClick={() => handlePackages(index)} disabled={!!busy[index]} className={btn.blue} data-testid={`gold-packages-btn-${index}`}><Package className="w-4 h-4 inline mr-1" />{busy[index] === 'packages' ? '...' : 'Packages'}</button>
              <button onClick={() => handleRefresh(index)} disabled={!!busy[index]} className={btn.green} data-testid={`gold-refresh-btn-${index}`}><RefreshCw className={`w-4 h-4 inline mr-1 ${busy[index] === 'refresh' ? 'animate-spin' : ''}`} />{busy[index] === 'refresh' ? 'Refreshing...' : 'Refresh Devices'}</button>
              <button onClick={() => { setEditingPanel(index); setShowModal(true); }} className={btn.gray} data-testid={`gold-edit-btn-${index}`}>Edit</button>
              <button onClick={() => handleRemovePanel(index)} disabled={!!busy[index]} className={btn.red} title="Remove panel" data-testid={`gold-remove-btn-${index}`}>{busy[index] === 'remove' ? <span className="text-xs">Removing…</span> : <Trash2 className="w-4 h-4" />}</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm text-gray-600 dark:text-gray-400">
            <div>API key: <span className="font-mono text-gray-900 dark:text-white">{panel.api_key ? panel.api_key.slice(0, 8) + '…' : 'Not set'}</span></div>
            <div>Streaming DNS: <span className="font-medium text-gray-900 dark:text-white">{panel.streaming_url || 'Auto (from M3U URL)'}</span></div>
          </div>
          {info[index] && (
            <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 flex flex-wrap gap-x-4 gap-y-1" data-testid={`gold-info-${index}`}>
              <span className="flex items-center gap-1"><Check className="w-3.5 h-3.5 text-green-600" /> Reseller <strong>{info[index].data?.username}</strong></span>
              {info[index].data?.credits != null && <span className="flex items-center gap-1"><Coins className="w-3.5 h-3.5 text-amber-600" /> Balance: <strong>{Number(info[index].data.credits).toLocaleString()}</strong> credits</span>}
            </div>
          )}
        </div>
      ))}

      <div className="flex gap-3">
        <button onClick={() => { setEditingPanel(null); setShowModal(true); }} className="flex items-center gap-2 bg-amber-600 text-white px-4 py-2.5 rounded-lg hover:bg-amber-700 font-semibold" data-testid="gold-add-panel-btn">
          <Plus className="w-5 h-5" /> Add Gold Panel
        </button>
        {panels.length > 0 && (
          <button onClick={() => updateMutation.mutate(panels)} disabled={updateMutation.isPending} className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 font-semibold disabled:opacity-50" data-testid="gold-save-panels-btn">
            <Save className="w-5 h-5" /> {updateMutation.isPending ? 'Saving...' : 'Save Panels'}
          </button>
        )}
      </div>

      {showModal && <PanelModal panel={editingPanel !== null ? panels[editingPanel] : null} onSave={handleAddPanel} onClose={() => { setShowModal(false); setEditingPanel(null); }} />}
    </div>
  );
}

function PanelModal({ panel, onSave, onClose }) {
  const [form, setForm] = useState({
    name: panel?.name || '', panel_url: panel?.panel_url || '', api_key: panel?.api_key || '',
    streaming_url: panel?.streaming_url || '', ssl_verify: panel?.ssl_verify !== false, active: panel?.active !== false,
  });
  const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white';

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.panel_url || !form.api_key) { toast.error('Panel URL and API key are required'); return; }
    onSave(form);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" data-testid="gold-panel-modal">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-lg p-6 m-4">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{panel ? 'Edit Gold Panel' : 'Add Gold Panel'}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Panel Name</label>
            <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Gold Panel" className={inputCls} data-testid="gold-panel-name-input" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Panel URL *</label>
            <input type="text" value={form.panel_url} onChange={(e) => setForm({ ...form, panel_url: e.target.value })} placeholder="https://your-panel.com" required className={inputCls} data-testid="gold-panel-url-input" />
            <p className="text-xs text-gray-500 mt-1">The address you sign in to (the API lives at <code>/api/api.php</code>)</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">API Key *</label>
            <input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} required className={inputCls} data-testid="gold-api-key-input" />
            <p className="text-xs text-gray-500 mt-1">Your reseller API key from the Gold panel</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Streaming DNS (optional)</label>
            <input type="text" value={form.streaming_url} onChange={(e) => setForm({ ...form, streaming_url: e.target.value })} placeholder="http://stream.example.com:8080" className={inputCls} data-testid="gold-streaming-url-input" />
            <p className="text-xs text-gray-500 mt-1">Leave blank to use the host from the M3U URL the panel returns</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={form.ssl_verify} onChange={(e) => setForm({ ...form, ssl_verify: e.target.checked })} data-testid="gold-ssl-verify-checkbox" /> Verify TLS certificate (recommended)
          </label>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700">Cancel</button>
            <button type="submit" className="flex items-center gap-2 bg-amber-600 text-white px-4 py-2 rounded-lg hover:bg-amber-700 font-semibold" data-testid="gold-panel-submit-btn"><Check className="w-4 h-4" /> {panel ? 'Update Panel' : 'Add Panel'}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
