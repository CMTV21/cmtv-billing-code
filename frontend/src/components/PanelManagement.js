import React, { useState, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import api from '../api/api';
import { Save, Plus, Edit, Trash2, Server, X, Check, Package, BookOpen, Users, Upload, Smartphone } from 'lucide-react';
import { toast } from 'sonner';

export default function PanelManagement({ settings }) {
  const queryClient = useQueryClient();
  const [panels, setPanels] = useState(settings?.xtream?.panels || []);
  const [showModal, setShowModal] = useState(false);
  const [editingPanel, setEditingPanel] = useState(null);
  const [testingPanelId, setTestingPanelId] = useState(null);
  const [syncingPackages, setSyncingPackages] = useState(null);
  const [syncingBouquets, setSyncingBouquets] = useState(null);
  const [syncingUsers, setSyncingUsers] = useState(null);
  const [ghostApkSyncing, setGhostApkSyncing] = useState(null);
  const [showImportModal, setShowImportModal] = useState(null); // panel index

  const updateMutation = useMutation({
    mutationFn: (data) => {
      const settingsUpdate = {
        ...settings,
        xtream: { panels: data }
      };
      return adminAPI.updateSettings(settingsUpdate);
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-settings']);
      toast.success('Panels saved successfully!');
    },
  });

  const testMutation = useMutation({
    mutationFn: (panelIndex) => adminAPI.testXtreamUI(panelIndex),
    onSuccess: () => {
      toast.success('Connection successful!');
      setTestingPanelId(null);
    },
    onError: (error) => {
      toast.error('Connection failed: ' + (error.response?.data?.error || 'Unknown error'));
      setTestingPanelId(null);
    },
  });

  const syncPackagesMutation = useMutation({
    mutationFn: (panelIndex) => adminAPI.syncPackagesFromPanel(panelIndex),
    onSuccess: (response, panelIndex) => {
      const regularCount = response.data?.count || 0;
      const trialCount = response.data?.trial_count || 0;
      const panelName = response.data?.panel_name || 'panel';
      toast.success(`✓ Synced from ${panelName}:\n• ${regularCount} regular packages\n• ${trialCount} trial packages`);
      setSyncingPackages(null);
    },
    onError: (error, panelIndex) => {
      toast.error('Sync failed: ' + (error.response?.data?.detail || 'Unknown error'));
      setSyncingPackages(null);
    },
  });

  const syncBouquetsMutation = useMutation({
    mutationFn: (panelIndex) => adminAPI.syncBouquetsFromPanel(panelIndex),
    onSuccess: (response, panelIndex) => {
      const count = response.data?.bouquets?.length || 0;
      const panelName = response.data?.panel_name || 'panel';
      toast.success(`✓ Synced ${count} bouquets from ${panelName}!`);
      setSyncingBouquets(null);
    },
    onError: (error, panelIndex) => {
      toast.error('Sync failed: ' + (error.response?.data?.detail || 'Unknown error'));
      setSyncingBouquets(null);
    },
  });

  const syncUsersMutation = useMutation({
    mutationFn: (panelIndex) => adminAPI.syncUsersFromPanel(panelIndex),
    onSuccess: (response, panelIndex) => {
      const syncedCount = response.data?.synced || 0;
      const updatedCount = response.data?.updated || 0;
      const panelName = response.data?.panel_name || 'panel';
      toast.success(`✓ User sync from ${panelName} complete:\n• ${syncedCount} new users imported\n• ${updatedCount} existing users updated`);
      setSyncingUsers(null);
    },
    onError: (error, panelIndex) => {
      toast.error(`Failed to sync users: ${error.response?.data?.detail || error.message}`);
      setSyncingUsers(null);
    },
  });

  const pollGhostApkSync = (panelIndex, panelName, attempt = 0) => {
    setTimeout(async () => {
      try {
        const res = await adminAPI.xtreamGhostApkSyncStatus(panelIndex);
        const job = res.data;
        if (job.status === 'running' && attempt < 120) {
          pollGhostApkSync(panelIndex, panelName, attempt + 1);
          return;
        }
        setGhostApkSyncing(null);
        if (job.status === 'completed') {
          const errs = job.errors?.length ? `\n• ${job.errors.length} errors` : '';
          toast.success(`✓ GhostAPK sync for ${panelName}:\n• ${job.created} lines created\n• ${job.updated} updated\n• ${job.codes_generated} pins generated${errs}`);
        } else if (job.status === 'failed') {
          toast.error(`GhostAPK sync failed: ${job.error || 'Unknown error'}`);
        } else {
          toast.info('GhostAPK sync is still running in the background. Pins will appear when it finishes.');
        }
      } catch (error) {
        setGhostApkSyncing(null);
        toast.error(`GhostAPK status check failed: ${error.response?.data?.detail || error.message}`);
      }
    }, 5000);
  };

  const handleGhostApkSyncAll = async (panel, index) => {
    if (!window.confirm(`Sync ALL lines of "${panel.admin_username}" on ${panel.name} to GhostAPK? This generates login pins for every line and may take a few minutes.`)) {
      return;
    }
    setGhostApkSyncing(index);
    try {
      await adminAPI.xtreamGhostApkSyncAll(index);
      toast.info(`GhostAPK sync started for ${panel.name}…`);
      pollGhostApkSync(index, panel.name);
    } catch (error) {
      toast.error(error.response?.data?.detail || `GhostAPK sync failed: ${error.message}`);
      setGhostApkSyncing(null);
    }
  };

  const handleAddPanel = () => {
    setEditingPanel({
      name: '',
      panel_url: '',
      admin_username: '',
      admin_password: '',
      ssl_verify: false,
      active: true
    });
    setShowModal(true);
  };

  const handleEditPanel = (panel, index) => {
    setEditingPanel({ ...panel, index });
    setShowModal(true);
  };

  const handleDeletePanel = (index) => {
    if (window.confirm('Delete this panel? This cannot be undone.')) {
      const newPanels = panels.filter((_, i) => i !== index);
      setPanels(newPanels);
      updateMutation.mutate(newPanels);
    }
  };

  const handleSavePanel = (panelData) => {
    let newPanels;
    if (panelData.index !== undefined) {
      // Edit existing
      newPanels = [...panels];
      newPanels[panelData.index] = panelData;
    } else {
      // Add new
      newPanels = [...panels, panelData];
    }
    
    setPanels(newPanels);
    updateMutation.mutate(newPanels);
    setShowModal(false);
    setEditingPanel(null);
  };

  const handleSyncUsers = (index) => {
    setSyncingUsers(index);
    syncUsersMutation.mutate(index);
  };

  const handleTestPanel = (panel, index) => {
    setTestingPanelId(index);
    testMutation.mutate(index);
  };

  const handleSyncPackages = (index) => {
    setSyncingPackages(index);
    syncPackagesMutation.mutate(index);
  };

  const handleSyncBouquets = (index) => {
    setSyncingBouquets(index);
    syncBouquetsMutation.mutate(index);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">XtreamUI Panels</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Manage multiple XtreamUI panel connections for different reseller accounts
          </p>
        </div>
        <button
          type="button"
          onClick={handleAddPanel}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
        >
          <Plus className="w-5 h-5" />
          Add Panel
        </button>
      </div>

      {/* Panels List */}
      <div className="space-y-3">
        {panels.map((panel, index) => (
          <div key={index} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <h4 className="font-semibold text-gray-900 dark:text-white">{panel.name}</h4>
                  {panel.active ? (
                    <span className="px-2 py-1 bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 text-xs rounded-full flex items-center gap-1">
                      <Check className="w-3 h-3" />
                      Active
                    </span>
                  ) : (
                    <span className="px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 text-xs rounded-full">
                      Inactive
                    </span>
                  )}
                </div>
                <div className="text-sm text-gray-600 dark:text-gray-300 space-y-1">
                  <p><strong>Panel URL:</strong> {panel.panel_url}</p>
                  <p><strong>Streaming URL:</strong> {panel.streaming_url || 'Not set'}</p>
                  <p><strong>Username:</strong> {panel.admin_username}</p>
                  <p><strong>Password:</strong> ••••••••</p>
                </div>
                
                {/* Action buttons for each panel */}
                <div className="flex flex-wrap gap-2 mt-4">
                  <button
                    onClick={() => handleTestPanel(panel, index)}
                    disabled={testingPanelId === index}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 disabled:opacity-50 border border-blue-200"
                    title="Test Connection"
                  >
                    <Server className="w-4 h-4" />
                    {testingPanelId === index ? 'Testing...' : 'Test'}
                  </button>
                  <button
                    onClick={() => handleSyncPackages(index)}
                    disabled={syncingPackages === index}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-50 text-green-700 rounded-lg hover:bg-green-100 disabled:opacity-50 border border-green-200"
                    title="Sync Packages"
                  >
                    <Package className="w-4 h-4" />
                    {syncingPackages === index ? 'Syncing...' : 'Sync Packages'}
                  </button>
                  <button
                    onClick={() => handleSyncBouquets(index)}
                    disabled={syncingBouquets === index}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-purple-50 text-purple-700 rounded-lg hover:bg-purple-100 disabled:opacity-50 border border-purple-200"
                    title="Sync Bouquets"
                  >
                    <BookOpen className="w-4 h-4" />
                    {syncingBouquets === index ? 'Syncing...' : 'Sync Bouquets'}
                  </button>
                  <button
                    onClick={() => handleSyncUsers(index)}
                    disabled={syncingUsers === index}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100 disabled:opacity-50 border border-indigo-200"
                    title="Sync Users"
                  >
                    <Users className="w-4 h-4" />
                    {syncingUsers === index ? 'Syncing...' : 'Sync Users'}
                  </button>
                  <button
                    onClick={() => handleGhostApkSyncAll(panel, index)}
                    disabled={ghostApkSyncing === index}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-50 text-violet-700 rounded-lg hover:bg-violet-100 disabled:opacity-50 border border-violet-200"
                    title="Sync all of this reseller's lines to GhostAPK and pull the login pins"
                    data-testid={`ghostapk-sync-all-btn-${index}`}
                  >
                    <Smartphone className="w-4 h-4" />
                    {ghostApkSyncing === index ? 'Syncing...' : 'Sync GhostAPK'}
                  </button>
                  {panel.api_key && (
                    <button
                      onClick={() => setShowImportModal(index)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-teal-50 text-teal-700 rounded-lg hover:bg-teal-100 border border-teal-200"
                      title="Import users by username or CSV"
                    >
                      <Upload className="w-4 h-4" />
                      Import Users
                    </button>
                  )}

                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleEditPanel(panel, index)}
                  className="p-2 text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400"
                  title="Edit"
                >
                  <Edit className="w-5 h-5" />
                </button>
                <button
                  onClick={() => handleDeletePanel(index)}
                  className="p-2 text-gray-600 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400"
                  title="Delete"
                >
                  <Trash2 className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>
        ))}
        
        {panels.length === 0 && (
          <div className="text-center py-12 bg-gray-50 dark:bg-gray-800 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600">
            <Server className="w-12 h-12 text-gray-400 dark:text-gray-500 mx-auto mb-3" />
            <p className="text-gray-600 dark:text-gray-300 mb-4">No panels configured</p>
            <button
              onClick={handleAddPanel}
              className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
            >
              <Plus className="w-5 h-5" />
              Add Your First Panel
            </button>
          </div>
        )}
      </div>

      {/* Panel Form Modal */}
      {showModal && (
        <PanelFormModal
          panel={editingPanel}
          onClose={() => {
            setShowModal(false);
            setEditingPanel(null);
          }}
          onSave={handleSavePanel}
        />
      )}

      {/* Import Users Modal */}
      {showImportModal !== null && (
        <ImportUsernamesModal
          panelIndex={showImportModal}
          panelName={panels[showImportModal]?.name || 'Panel'}
          onClose={() => setShowImportModal(null)}
        />
      )}
    </div>
  );
}

function ImportUsernamesModal({ panelIndex, panelName, onClose }) {
  const [input, setInput] = useState('');
  const [importing, setImporting] = useState(false);
  const [results, setResults] = useState(null);
  const fileRef = useRef(null);
  const queryClient = useQueryClient();

  const handleImport = async () => {
    if (!input.trim()) { toast.error('Enter at least one username'); return; }
    setImporting(true);
    setResults(null);
    try {
      const resp = await api.post(`/api/admin/xtream/import-usernames?panel_index=${panelIndex}`, {
        usernames: input
      });
      setResults(resp.data);
      queryClient.invalidateQueries(['imported-users']);
      if (resp.data.imported > 0 || resp.data.updated > 0) {
        toast.success(resp.data.message);
      } else if (resp.data.not_found?.length > 0) {
        toast.warning(`${resp.data.not_found.length} username(s) not found on panel`);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  const handleCSV = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target.result;
      // Parse CSV: split by commas, newlines, semicolons — each cell is a username
      const usernames = text.split(/[,;\n\r\t]+/).map(u => u.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
      setInput(usernames.join(', '));
      toast.success(`Loaded ${usernames.length} usernames from CSV`);
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-lg w-full max-h-[85vh] overflow-y-auto">
        <div className="sticky top-0 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">Import Users — {panelName}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-6 space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Enter usernames to look up on the panel and import. Each username will be verified via the panel API.
          </p>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Usernames</label>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={5}
              placeholder={"user1, user2, user3\nor one per line:\nuser1\nuser2\nuser3"}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white font-mono text-sm"
              data-testid="import-usernames-input"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Separate with commas, newlines, or semicolons</p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex items-center gap-2 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 text-sm"
            >
              <Upload className="w-4 h-4" />
              Upload CSV
            </button>
            <input ref={fileRef} type="file" accept=".csv,.txt" onChange={handleCSV} className="hidden" />
            <span className="text-xs text-gray-500 dark:text-gray-400">CSV with usernames in cells</span>
          </div>

          {results && (
            <div className="p-4 bg-gray-50 dark:bg-gray-900 rounded-lg text-sm space-y-2">
              <p className="font-medium text-gray-900 dark:text-white">{results.message}</p>
              <div className="flex gap-4 text-xs">
                <span className="text-green-600">Imported: {results.imported}</span>
                <span className="text-blue-600">Updated: {results.updated}</span>
                <span className="text-red-600">Not found: {results.not_found?.length || 0}</span>
              </div>
              {results.not_found?.length > 0 && (
                <div>
                  <p className="text-xs text-red-600 font-medium mt-1">Not found on panel:</p>
                  <p className="text-xs text-red-500 font-mono">{results.not_found.join(', ')}</p>
                </div>
              )}
              {results.errors?.length > 0 && (
                <div>
                  <p className="text-xs text-red-600 font-medium mt-1">Errors:</p>
                  {results.errors.map((e, i) => <p key={i} className="text-xs text-red-500">{e}</p>)}
                </div>
              )}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button onClick={onClose} className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700">Close</button>
            <button
              onClick={handleImport}
              disabled={importing || !input.trim()}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 font-medium"
              data-testid="import-usernames-submit"
            >
              <Upload className="w-4 h-4" />
              {importing ? 'Importing...' : 'Import'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PanelFormModal({ panel, onClose, onSave }) {
  const [formData, setFormData] = useState(panel || {
    name: '',
    panel_url: '',
    streaming_url: '',
    admin_username: '',
    admin_password: '',
    ssl_verify: false,
    active: true
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave(formData);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="sticky top-0 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white">
            {panel.index !== undefined ? 'Edit Panel' : 'Add New Panel'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Panel Name *
            </label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Main Panel, Backup Panel, etc."
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Panel URL *
            </label>
            <input
              type="url"
              required
              value={formData.panel_url}
              onChange={(e) => setFormData({ ...formData, panel_url: e.target.value })}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="https://yourpanel.com:port"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              API endpoint for panel management (include HTTP auth if needed)
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Streaming URL (Customer Connection) *
            </label>
            <input
              type="url"
              required
              value={formData.streaming_url}
              onChange={(e) => setFormData({ ...formData, streaming_url: e.target.value })}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="https://streaming.example.com:8000"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              URL sent to customers for their IPTV player connections (without auth)
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Username *
            </label>
            <input
              type="text"
              required
              value={formData.admin_username}
              onChange={(e) => setFormData({ ...formData, admin_username: e.target.value })}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="username"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Password *
            </label>
            <input
              type="password"
              required
              value={formData.admin_password}
              onChange={(e) => setFormData({ ...formData, admin_password: e.target.value })}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="password"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Reseller API Key <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="password"
              value={formData.api_key || ''}
              onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Leave blank if panel doesn't require API key"
              data-testid="panel-api-key"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Some XtreamUI panels require a reseller API key for all requests. Leave blank for standard username/password auth.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="active"
              checked={formData.active}
              onChange={(e) => setFormData({ ...formData, active: e.target.checked })}
              className="w-4 h-4 text-blue-600 border-gray-300 dark:border-gray-600 rounded focus:ring-blue-500"
            />
            <label htmlFor="active" className="text-sm text-gray-700 dark:text-gray-300">
              Active (use this panel for new products)
            </label>
          </div>

          {/* Advanced: Proxy & HTTP Basic Auth */}
          <details className="border border-gray-200 dark:border-gray-600 rounded-lg">
            <summary className="px-4 py-3 cursor-pointer text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg">
              Advanced Settings (Proxy / HTTP Basic Auth)
            </summary>
            <div className="px-4 pb-4 pt-2 space-y-4 border-t border-gray-200 dark:border-gray-600">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Proxy URL</label>
                <input
                  type="text"
                  value={formData.proxy_url || ''}
                  onChange={(e) => setFormData({ ...formData, proxy_url: e.target.value })}
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                  placeholder="http://user:pass@proxy.example.com:port"
                  data-testid="panel-proxy-url"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Residential proxy to bypass Cloudflare WAF (optional)</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">HTTP Basic Auth User</label>
                  <input
                    type="text"
                    value={formData.http_basic_user || ''}
                    onChange={(e) => setFormData({ ...formData, http_basic_user: e.target.value })}
                    className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                    placeholder="Leave blank if same as panel user"
                    data-testid="panel-http-basic-user"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">HTTP Basic Auth Pass</label>
                  <input
                    type="password"
                    value={formData.http_basic_pass || ''}
                    onChange={(e) => setFormData({ ...formData, http_basic_pass: e.target.value })}
                    className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                    placeholder="Leave blank if same as panel pass"
                    data-testid="panel-http-basic-pass"
                  />
                </div>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">If the panel has a separate nginx basic auth popup (different from panel login), enter those credentials here.</p>
            </div>
          </details>

          <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-semibold"
            >
              {panel.index !== undefined ? 'Update Panel' : 'Add Panel'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
