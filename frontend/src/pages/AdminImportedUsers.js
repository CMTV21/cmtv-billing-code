import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { ArrowLeft, Users, Filter, Ban, CheckCircle, Server, UserCog, CreditCard, Search, ChevronLeft, ChevronRight, Trash2, Plus, X, RefreshCw, Clock, Download, ArrowUpDown, ArrowUp, ArrowDown, Calendar } from 'lucide-react';
import { useTimezone, formatDateTime, formatDate } from '../utils/timezone';
import { toast } from 'sonner';

export default function AdminImportedUsers() {
  const queryClient = useQueryClient();
  const timezone = useTimezone();
  const [selectedPanel, setSelectedPanel] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState('subscribers');

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setSelectedUsers(new Set());
  };
  const [currentPage, setCurrentPage] = useState(1);
  const [entriesPerPage, setEntriesPerPage] = useState(10);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showExtendModal, setShowExtendModal] = useState(false);
  const [selectedUserForExtend, setSelectedUserForExtend] = useState(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [showCreditsModal, setShowCreditsModal] = useState(false);
  const [selectedUserForCredits, setSelectedUserForCredits] = useState(null);
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });
  const [selectedUsers, setSelectedUsers] = useState(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);

  // Fetch imported users (get all, filter on frontend)
  const { data: allUsers, isLoading } = useQuery({
    queryKey: ['imported-users'],
    queryFn: async () => {
      const response = await adminAPI.getImportedUsers();  // Get all users
      return response.data;
    },
  });

  // Fetch settings for panel names
  const { data: settings } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: async () => {
      const response = await adminAPI.getSettings();
      return response.data;
    },
  });

  const xtreamPanels = settings?.xtream?.panels || [];
  const xuionePanels = settings?.xuione?.panels || [];
  const onestreamPanels = settings?.onestream?.panels || [];
  const nxtdashPanels = settings?.nxtdash?.panels || [];
  const ghostsurfPanels = settings?.ghostsurf?.panels || [];
  
  // Combine all panel types for filter dropdown
  const allPanels = [
    ...xtreamPanels.map((panel, index) => ({ 
      ...panel, 
      type: 'xtream', 
      index: index,
      value: `xtream-${index}`,
      label: `${panel.name} (XtreamUI)`
    })),
    ...xuionePanels.map((panel, index) => ({ 
      ...panel, 
      type: 'xuione', 
      index: index,
      value: `xuione-${index}`,
      label: `${panel.name} (XuiOne)`
    })),
    ...onestreamPanels.map((panel, index) => ({ 
      ...panel, 
      type: 'onestream', 
      index: index,
      value: `onestream-${index}`,
      label: `${panel.name} (1-Stream)`
    })),
    ...nxtdashPanels.map((panel, index) => ({ 
      ...panel, 
      type: 'nxtdash', 
      index: index,
      value: `nxtdash-${index}`,
      label: `${panel.name} (NXT Dash)`
    })),
    ...(settings?.aether?.panels || []).map((panel, index) => ({ 
      ...panel, 
      type: 'aether', 
      index: index,
      value: `aether-${index}`,
      label: `${panel.name || 'Aether'} (Aether)`
    })),
    ...(settings?.gold?.panels || []).map((panel, index) => ({ 
      ...panel, 
      type: 'gold', 
      index: index,
      value: `gold-${index}`,
      label: `${panel.name || 'Gold'} (Gold Panel)`
    })),
    ...ghostsurfPanels.map((panel, index) => ({ 
      ...panel, 
      type: 'ghostsurf', 
      index: index,
      value: `ghostsurf-${index}`,
      label: `${panel.name || 'GhostSurf VPN'} (GhostSurf)`
    }))
  ];
  
  const panels = allPanels;

  const suspendMutation = useMutation({
    mutationFn: (id) => adminAPI.suspendImportedUser(id),
    onSuccess: (response) => {
      queryClient.invalidateQueries(['imported-users']);
      const msg = response?.data?.message || 'User suspended successfully!';
      if (msg.includes('NXT Dash')) {
        toast.warning(msg, { duration: 6000 });
      } else {
        toast.success(msg);
      }
    },
    onError: (error) => {
      toast.error('Failed to suspend user: ' + (error.response?.data?.detail || error.message));
    },
  });

  const activateMutation = useMutation({
    mutationFn: (id) => adminAPI.activateImportedUser(id),
    onSuccess: (response) => {
      queryClient.invalidateQueries(['imported-users']);
      const msg = response?.data?.message || 'User activated successfully!';
      if (msg.includes('NXT Dash')) {
        toast.warning(msg, { duration: 6000 });
      } else {
        toast.success(msg);
      }
    },
    onError: (error) => {
      toast.error('Failed to activate user: ' + (error.response?.data?.detail || error.message));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => adminAPI.deleteImportedUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['imported-users']);
      toast.success('User removed from billing panel');
    },
    onError: (error) => {
      toast.error('Failed to remove user: ' + (error.response?.data?.detail || error.message));
    },
  });

  const handleDelete = (user) => {
    if (window.confirm(`Remove "${user.username}" from billing panel?\n\nNote: This only removes from the billing panel, NOT from XtreamUI.`)) {
      deleteMutation.mutate(user.id);
    }
  };

  // Bulk selection helpers
  const toggleSelectUser = (id) => {
    setSelectedUsers(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedUsers.size === paginatedData?.length) {
      setSelectedUsers(new Set());
    } else {
      setSelectedUsers(new Set((paginatedData || []).map(u => u.id)));
    }
  };

  const handleBulkAction = async (action) => {
    const count = selectedUsers.size;
    const label = action === 'delete' ? 'DELETE' : action === 'suspend' ? 'SUSPEND' : 'ACTIVATE';
    if (!window.confirm(`${label} ${count} selected user${count !== 1 ? 's' : ''}?`)) return;
    setBulkProcessing(true);
    try {
      const resp = await adminAPI.bulkActionImportedUsers(action, Array.from(selectedUsers));
      toast.success(`Bulk ${action}: ${resp.data.processed} succeeded, ${resp.data.failed} failed`);
      setSelectedUsers(new Set());
      queryClient.invalidateQueries(['imported-users']);
    } catch (err) {
      toast.error('Bulk action failed: ' + (err.response?.data?.detail || err.message));
    }
    setBulkProcessing(false);
  };

  // Filter users by panel selection
  const users = React.useMemo(() => {
    if (!allUsers) return null;
    
    if (selectedPanel === 'all') {
      return allUsers;
    }
    
    // Parse panel selection: "xtream-0" or "xuione-0"
    const [panelType, panelIndexStr] = selectedPanel.split('-');
    const panelIndex = parseInt(panelIndexStr);
    
    return allUsers.filter(u => 
      (u.panel_type || 'xtream') === panelType && u.panel_index === panelIndex
    );
  }, [allUsers, selectedPanel]);

  // Separate users by account type
  const subscribers = users?.filter(u => u.account_type === 'subscriber') || [];
  const resellers = users?.filter(u => u.account_type === 'reseller') || [];

  // Filter users by status and search query
  const filterUsers = (userList) => {
    let filtered = userList;
    
    // Filter by status
    if (statusFilter !== 'all') {
      filtered = filtered.filter(u => u.status === statusFilter);
    }
    
    // Filter by search query (username, password, owner)
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase().trim();
      filtered = filtered.filter(u => 
        u.username?.toLowerCase().includes(query) ||
        u.password?.toLowerCase().includes(query) ||
        u.owner?.toLowerCase().includes(query) ||
        u.member_group?.toLowerCase().includes(query)
      );
    }
    
    return filtered;
  };

  const filteredSubscribers = filterUsers(subscribers);
  const filteredResellers = filterUsers(resellers);

  // Sort handler
  const handleSort = (key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
    setCurrentPage(1);
  };

  const SortIcon = ({ column }) => {
    if (sortConfig.key !== column) return <ArrowUpDown className="w-3 h-3 opacity-40" />;
    return sortConfig.direction === 'asc' 
      ? <ArrowUp className="w-3 h-3 text-blue-500" /> 
      : <ArrowDown className="w-3 h-3 text-blue-500" />;
  };

  const sortData = (data) => {
    if (!sortConfig.key) return data;
    return [...data].sort((a, b) => {
      let aVal = a[sortConfig.key];
      let bVal = b[sortConfig.key];
      // Handle dates
      if (sortConfig.key === 'expiry_date' || sortConfig.key === 'last_synced') {
        aVal = aVal ? new Date(aVal).getTime() : 0;
        bVal = bVal ? new Date(bVal).getTime() : 0;
      }
      // Handle numbers
      else if (sortConfig.key === 'max_connections' || sortConfig.key === 'credits') {
        aVal = parseFloat(aVal) || 0;
        bVal = parseFloat(bVal) || 0;
      }
      // Handle strings
      else {
        aVal = String(aVal || '').toLowerCase();
        bVal = String(bVal || '').toLowerCase();
      }
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  };

  // Pagination logic
  const getCurrentData = () => {
    const raw = activeTab === 'subscribers' ? filteredSubscribers : filteredResellers;
    const data = sortData(raw);
    const totalPages = Math.ceil(data.length / entriesPerPage);
    const startIndex = (currentPage - 1) * entriesPerPage;
    const endIndex = startIndex + entriesPerPage;
    const paginatedData = data.slice(startIndex, endIndex);
    
    return {
      data: paginatedData,
      totalItems: data.length,
      totalPages,
      startIndex: startIndex + 1,
      endIndex: Math.min(endIndex, data.length)
    };
  };

  const { data: paginatedData, totalItems, totalPages, startIndex, endIndex } = getCurrentData();

  const goToPage = (page) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    }
  };

  // Generate page numbers to display
  const getPageNumbers = () => {
    const pages = [];
    const maxVisiblePages = 5;
    
    if (totalPages <= maxVisiblePages) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i);
      }
    } else {
      if (currentPage <= 3) {
        for (let i = 1; i <= 4; i++) pages.push(i);
        pages.push('...');
        pages.push(totalPages);
      } else if (currentPage >= totalPages - 2) {
        pages.push(1);
        pages.push('...');
        for (let i = totalPages - 3; i <= totalPages; i++) pages.push(i);
      } else {
        pages.push(1);
        pages.push('...');
        for (let i = currentPage - 1; i <= currentPage + 1; i++) pages.push(i);
        pages.push('...');
        pages.push(totalPages);
      }
    }
    
    return pages;
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
      case 'suspended':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
      case 'expired':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200';
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400">
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">Imported Users</h1>
            <p className="text-gray-600 dark:text-gray-400 mt-1 text-sm">
              Users and resellers synced from XtreamUI, XuiOne, 1-Stream, NXT Dash, and GhostSurf panels
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                setIsSyncing(true);
                setSyncResult(null);
                try {
                  // Deduplicate first, then sync
                  await adminAPI.deduplicateImportedUsers();
                  const response = await adminAPI.syncAllUsers({ timeout: 120000 });
                  setSyncResult(response.data);
                  queryClient.invalidateQueries(['imported-users']);
                } catch (error) {
                  const status = error.response?.status;
                  const msg = error.response?.data?.detail || error.message;
                  if (status === 520 || status === 504 || error.code === 'ECONNABORTED' || msg.includes('timeout')) {
                    setSyncResult({ success: true, message: 'Sync is processing in the background. Panels behind Cloudflare may take longer. Please refresh in a moment.' });
                    queryClient.invalidateQueries(['imported-users']);
                  } else {
                    setSyncResult({ success: false, error: msg });
                  }
                } finally {
                  setIsSyncing(false);
                }
              }}
              disabled={isSyncing}
              className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 transition font-semibold disabled:opacity-50"
              data-testid="sync-users-btn"
            >
              <Download className={`w-5 h-5 ${isSyncing ? 'animate-spin' : ''}`} />
              {isSyncing ? 'Syncing...' : 'Sync Users'}
            </button>
            <button
              onClick={async () => {
                setIsSyncing(true);
                setSyncResult(null);
                try {
                  const response = await adminAPI.resyncServicesExpiry();
                  setSyncResult({ success: true, message: `Checked ${response.data.checked} services — ${response.data.updated} expiry date${response.data.updated === 1 ? '' : 's'} corrected from panel data.` });
                } catch (error) {
                  setSyncResult({ success: false, error: error.response?.data?.detail || error.message });
                } finally {
                  setIsSyncing(false);
                }
              }}
              disabled={isSyncing}
              title="Re-copy each panel user's real expiry onto their service card"
              className="flex items-center gap-2 bg-amber-600 text-white px-4 py-2 rounded-lg hover:bg-amber-700 transition font-semibold disabled:opacity-50"
              data-testid="resync-expiry-btn"
            >
              <Calendar className="w-5 h-5" />
              Fix Service Expiry
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition font-semibold"
              data-testid="create-user-btn"
            >
              <Plus className="w-5 h-5" />
              Create User
            </button>
          </div>
        </div>

        {/* Sync Result Banner */}
        {syncResult && (
          <div className={`mb-6 p-4 rounded-lg ${syncResult.success ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'}`}>
            <div className="flex items-center justify-between">
              <div>
                {syncResult.success ? (
                  <>
                    <p className="font-semibold text-green-800 dark:text-green-200" data-testid="sync-result-text">
                      {syncResult.message ? syncResult.message : (
                        <>
                          Sync Complete: {syncResult.total_synced} new users, {syncResult.total_updated} updated
                          {syncResult.total_removed > 0 && `, ${syncResult.total_removed} removed (from deleted panels)`}
                          {syncResult.services_expiry && `, ${syncResult.services_expiry.updated} service expiry date${syncResult.services_expiry.updated === 1 ? '' : 's'} corrected`}
                        </>
                      )}
                    </p>
                    {syncResult.panels_synced?.length > 0 && (
                      <p className="text-sm text-green-600 dark:text-green-300 mt-1">
                        Panels: {syncResult.panels_synced.map(p => `${p.name} (${p.synced} new, ${p.updated} updated)`).join(', ')}
                      </p>
                    )}
                    {syncResult.errors?.length > 0 && (
                      <p className="text-sm text-yellow-600 dark:text-yellow-400 mt-1">
                        Warnings: {syncResult.errors.join(', ')}
                      </p>
                    )}
                    {syncResult.accounts_created > 0 && (
                      <p className="text-sm text-blue-600 dark:text-blue-300 mt-1">
                        Customer accounts created: {syncResult.accounts_created}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="font-semibold text-red-800 dark:text-red-200">
                    Sync Failed: {syncResult.error}
                  </p>
                )}
              </div>
              <button
                onClick={() => setSyncResult(null)}
                className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        )}

        {/* Orphaned Users Warning */}
        {syncResult?.orphaned_users > 0 && (
          <div className="mb-6 p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
            <div className="flex items-start justify-between">
              <div>
                <p className="font-semibold text-amber-800 dark:text-amber-200">
                  {syncResult.orphaned_users} imported users from removed panels detected
                </p>
                <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                  Panels: {syncResult.orphaned_panels?.map(p => `${p.panel_name} (${p.panel_type}, ${p.user_count} users)`).join(', ')}
                </p>
                <div className="flex gap-3 mt-3">
                  <button
                    onClick={async () => {
                      try {
                        const resp = await adminAPI.cleanupOrphanedUsers(false);
                        toast.success(`Removed ${resp.data.removed_imported_users} imported users. Customer accounts kept.`);
                        setSyncResult(null);
                        queryClient.invalidateQueries(['imported-users']);
                      } catch (err) { toast.error('Cleanup failed: ' + (err.response?.data?.detail || err.message)); }
                    }}
                    className="px-3 py-1.5 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700 font-medium"
                  >
                    Remove Imported Users Only
                  </button>
                  <button
                    onClick={async () => {
                      if (!window.confirm('This will also delete linked customer accounts and their services. Are you sure?')) return;
                      try {
                        const resp = await adminAPI.cleanupOrphanedUsers(true);
                        toast.success(`Removed ${resp.data.removed_imported_users} imported users, ${resp.data.removed_customers} customers, ${resp.data.removed_services} services.`);
                        setSyncResult(null);
                        queryClient.invalidateQueries(['imported-users']);
                      } catch (err) { toast.error('Cleanup failed: ' + (err.response?.data?.detail || err.message)); }
                    }}
                    className="px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 font-medium"
                  >
                    Remove Users + Linked Customers
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6 mb-6">
          <div className="grid md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                <Search className="w-4 h-4 inline mr-1" />
                Search Users
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by username, password..."
                  className="w-full px-4 py-2 pl-10 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400"
                  data-testid="search-input"
                />
                <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                <Server className="w-4 h-4 inline mr-1" />
                Filter by Panel
              </label>
              <select
                value={selectedPanel}
                onChange={(e) => setSelectedPanel(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                data-testid="panel-filter"
              >
                <option value="all">All Panels</option>
                {panels.map((panel, idx) => (
                  <option key={idx} value={panel.value}>
                    {panel.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                <Filter className="w-4 h-4 inline mr-1" />
                Filter by Status
              </label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                data-testid="status-filter"
              >
                <option value="all">All Status</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
                <option value="expired">Expired</option>
              </select>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">Total Imported</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{users?.length || 0}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
            <p className="text-sm text-blue-600">Subscribers</p>
            <p className="text-2xl font-bold text-blue-600">{subscribers.length}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
            <p className="text-sm text-purple-600">Resellers</p>
            <p className="text-2xl font-bold text-purple-600">{resellers.length}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
            <p className="text-sm text-green-600">Active</p>
            <p className="text-2xl font-bold text-green-600">{users?.filter(u => u.status === 'active').length || 0}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
            <p className="text-sm text-red-600">Expired</p>
            <p className="text-2xl font-bold text-red-600">{users?.filter(u => u.status === 'expired').length || 0}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4 md:col-span-5">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Last Synced: {(() => {
                const latest = users?.reduce((max, u) => {
                  const d = u.last_synced ? new Date(u.last_synced) : null;
                  return d && (!max || d > max) ? d : max;
                }, null);
                return latest ? formatDateTime(latest, timezone) : 'Never';
              })()}
              <span className="text-xs text-gray-400 ml-2">(auto-syncs every hour)</span>
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow mb-6">
          <div className="border-b border-gray-200 dark:border-gray-700">
            <nav className="flex -mb-px">
              <button
                onClick={() => handleTabChange('subscribers')}
                className={`py-4 px-6 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'subscribers'
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                }`}
                data-testid="subscribers-tab"
              >
                <Users className="w-4 h-4 inline mr-2" />
                Subscribers ({filteredSubscribers.length})
              </button>
              <button
                onClick={() => handleTabChange('resellers')}
                className={`py-4 px-6 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'resellers'
                    ? 'border-purple-500 text-purple-600 dark:text-purple-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                }`}
                data-testid="resellers-tab"
              >
                <UserCog className="w-4 h-4 inline mr-2" />
                Resellers ({filteredResellers.length})
              </button>
            </nav>
          </div>
        </div>

        {/* Content based on active tab */}
        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : activeTab === 'subscribers' ? (
          // Subscribers Table
          filteredSubscribers.length === 0 ? (
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
              <Users className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">No subscribers found</h3>
              <p className="text-gray-600 dark:text-gray-400">
                Sync users from XtreamUI panel to see them here
              </p>
            </div>
          ) : (
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
              {/* Bulk Action Bar */}
              {selectedUsers.size > 0 && (
                <div className="px-6 py-3 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-700 flex items-center justify-between">
                  <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                    {selectedUsers.size} user{selectedUsers.size !== 1 ? 's' : ''} selected
                  </span>
                  <div className="flex items-center gap-2">
                    <button onClick={() => handleBulkAction('activate')} disabled={bulkProcessing}
                      className="px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-1">
                      <CheckCircle className="w-3.5 h-3.5" /> Activate
                    </button>
                    <button onClick={() => handleBulkAction('suspend')} disabled={bulkProcessing}
                      className="px-3 py-1.5 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1">
                      <Ban className="w-3.5 h-3.5" /> Suspend
                    </button>
                    <button onClick={() => handleBulkAction('delete')} disabled={bulkProcessing}
                      className="px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center gap-1">
                      <Trash2 className="w-3.5 h-3.5" /> Delete
                    </button>
                    <button onClick={() => setSelectedUsers(new Set())}
                      className="px-3 py-1.5 text-gray-600 dark:text-gray-400 text-sm hover:text-gray-800">
                      Clear
                    </button>
                  </div>
                </div>
              )}
              <div className="overflow-x-auto hidden md:block">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700" data-testid="subscribers-table">
                  <thead className="bg-gray-50 dark:bg-gray-800">
                    <tr>
                      <th className="px-3 py-3 w-10">
                        <input type="checkbox" checked={paginatedData?.length > 0 && selectedUsers.size === paginatedData?.length}
                          onChange={toggleSelectAll} className="w-4 h-4 text-blue-600 rounded" />
                      </th>
                      <th onClick={() => handleSort('username')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer hover:text-gray-900 dark:hover:text-white select-none"><span className="flex items-center gap-1">Username <SortIcon column="username" /></span></th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Password</th>
                      <th onClick={() => handleSort('panel_name')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer hover:text-gray-900 dark:hover:text-white select-none"><span className="flex items-center gap-1">Panel <SortIcon column="panel_name" /></span></th>
                      <th onClick={() => handleSort('expiry_date')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer hover:text-gray-900 dark:hover:text-white select-none"><span className="flex items-center gap-1">Expiry <SortIcon column="expiry_date" /></span></th>
                      <th onClick={() => handleSort('max_connections')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer hover:text-gray-900 dark:hover:text-white select-none"><span className="flex items-center gap-1">Conn <SortIcon column="max_connections" /></span></th>
                      <th onClick={() => handleSort('status')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer hover:text-gray-900 dark:hover:text-white select-none"><span className="flex items-center gap-1">Status <SortIcon column="status" /></span></th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                    {paginatedData.map((user) => (
                      <tr key={user.id} className={`hover:bg-gray-50 dark:hover:bg-gray-800 ${selectedUsers.has(user.id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}`}>
                        <td className="px-3 py-4 w-10">
                          <input type="checkbox" checked={selectedUsers.has(user.id)}
                            onChange={() => toggleSelectUser(user.id)} className="w-4 h-4 text-blue-600 rounded" />
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-gray-900 dark:text-white">{user.username}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-mono text-gray-600 dark:text-gray-300">{user.password || '••••••'}</div>
                          {user.ghostapk_code && (
                            <div className="text-xs font-mono font-semibold tracking-[0.15em] text-violet-700 dark:text-violet-300" title="GhostAPK login pin" data-testid={`imported-ghostapk-pin-${user.id}`}>
                              Pin {user.ghostapk_code}
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">
                          {user.panel_name}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">
                          {user.expiry_date ? formatDate(user.expiry_date, timezone) : 'Unlimited'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">
                          {user.max_connections || 1}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(user.status)}`}>
                            {user.status}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                          <div className="flex items-center gap-2 justify-end">
                            <button
                              onClick={() => {
                                setSelectedUserForExtend(user);
                                setShowExtendModal(true);
                              }}
                              className="text-blue-600 hover:text-blue-900 dark:hover:text-blue-400"
                              data-testid={`extend-${user.username}`}
                              title="Extend subscription"
                            >
                              <Clock className="w-4 h-4 inline mr-1" />
                              Extend
                            </button>
                            {user.status === 'active' ? (
                              <button
                                onClick={() => suspendMutation.mutate(user.id)}
                                disabled={suspendMutation.isPending}
                                className="text-yellow-600 hover:text-yellow-900 dark:hover:text-yellow-400"
                                data-testid={`suspend-${user.username}`}
                              >
                                <Ban className="w-4 h-4 inline mr-1" />
                                Suspend
                              </button>
                            ) : user.status === 'suspended' ? (
                              <button
                                onClick={() => activateMutation.mutate(user.id)}
                                disabled={activateMutation.isPending}
                                className="text-green-600 hover:text-green-900 dark:hover:text-green-400"
                                data-testid={`activate-${user.username}`}
                              >
                                <CheckCircle className="w-4 h-4 inline mr-1" />
                                Activate
                              </button>
                            ) : null}
                            <button
                              onClick={() => handleDelete(user)}
                              disabled={deleteMutation.isPending}
                              className="text-red-600 hover:text-red-900 dark:hover:text-red-400 ml-2"
                              data-testid={`delete-${user.username}`}
                              title="Remove from billing panel"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Mobile card view */}
              <div className="md:hidden divide-y divide-gray-200 dark:divide-gray-700">
                {paginatedData.map((user) => (
                  <div key={user.id} className={`p-4 ${selectedUsers.has(user.id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <input type="checkbox" checked={selectedUsers.has(user.id)}
                          onChange={() => toggleSelectUser(user.id)} className="w-4 h-4 text-blue-600 rounded flex-shrink-0 mt-1" />
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-gray-900 dark:text-white truncate">{user.username}</div>
                          <div className="text-xs font-mono text-gray-500 dark:text-gray-400">{user.password || '••••••'}</div>
                          {user.ghostapk_code && (
                            <div className="text-xs font-mono font-semibold tracking-[0.15em] text-violet-700 dark:text-violet-300">Pin {user.ghostapk_code}</div>
                          )}
                        </div>
                      </div>
                      <span className={`px-2 py-0.5 text-xs font-semibold rounded-full flex-shrink-0 ${getStatusColor(user.status)}`}>
                        {user.status}
                      </span>
                    </div>
                    <div className="mt-2 ml-7 grid grid-cols-2 gap-1 text-xs text-gray-500 dark:text-gray-400">
                      <span>Panel: {user.panel_name}</span>
                      <span>Conn: {user.max_connections || 1}</span>
                      <span>Expiry: {user.expiry_date ? formatDate(user.expiry_date, timezone) : 'Unlimited'}</span>
                    </div>
                    <div className="mt-3 ml-7 flex items-center gap-3">
                      <button onClick={() => { setSelectedUserForExtend(user); setShowExtendModal(true); }}
                        className="text-xs text-blue-600 font-medium" data-testid={`extend-${user.username}`}>
                        <Clock className="w-3.5 h-3.5 inline mr-0.5" />Extend
                      </button>
                      {user.status === 'active' ? (
                        <button onClick={() => suspendMutation.mutate(user.id)} className="text-xs text-yellow-600 font-medium">
                          <Ban className="w-3.5 h-3.5 inline mr-0.5" />Suspend
                        </button>
                      ) : user.status === 'suspended' ? (
                        <button onClick={() => activateMutation.mutate(user.id)} className="text-xs text-green-600 font-medium">
                          <CheckCircle className="w-3.5 h-3.5 inline mr-0.5" />Activate
                        </button>
                      ) : null}
                      <button onClick={() => handleDelete(user)} className="text-xs text-red-600 font-medium ml-auto">
                        <Trash2 className="w-3.5 h-3.5 inline mr-0.5" />Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              
              {/* Pagination */}
              <div className="px-4 sm:px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex flex-col sm:flex-row items-center justify-between gap-3">
                <div className="flex items-center gap-2 sm:gap-4">
                  <span className="text-xs sm:text-sm text-gray-600 dark:text-gray-400">
                    {startIndex}-{endIndex} of {totalItems}
                  </span>
                  <select
                    value={entriesPerPage}
                    onChange={(e) => {
                      setEntriesPerPage(Number(e.target.value));
                      setCurrentPage(1);
                    }}
                    className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-xs sm:text-sm text-gray-900 dark:text-white"
                    data-testid="entries-per-page"
                  >
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                </div>
                
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => goToPage(currentPage - 1)}
                    disabled={currentPage === 1}
                    className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="prev-page"
                  >
                    <ChevronLeft className="w-5 h-5 text-gray-600 dark:text-gray-300" />
                  </button>
                  
                  {getPageNumbers().map((page, index) => (
                    page === '...' ? (
                      <span key={`ellipsis-${index}`} className="px-2 text-gray-400">...</span>
                    ) : (
                      <button
                        key={page}
                        onClick={() => goToPage(page)}
                        className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                          currentPage === page
                            ? 'bg-blue-600 text-white'
                            : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }`}
                        data-testid={`page-${page}`}
                      >
                        {page}
                      </button>
                    )
                  ))}
                  
                  <button
                    onClick={() => goToPage(currentPage + 1)}
                    disabled={currentPage === totalPages}
                    className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="next-page"
                  >
                    <ChevronRight className="w-5 h-5 text-gray-600 dark:text-gray-300" />
                  </button>
                </div>
              </div>
            </div>
          )
        ) : (
          // Resellers Table
          filteredResellers.length === 0 ? (
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
              <UserCog className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">No resellers found</h3>
              <p className="text-gray-600 dark:text-gray-400">
                Sync users from XtreamUI panel to see resellers here
              </p>
            </div>
          ) : (
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
              {/* Bulk Action Bar for Resellers */}
              {selectedUsers.size > 0 && (
                <div className="px-6 py-3 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-700 flex items-center justify-between">
                  <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                    {selectedUsers.size} user{selectedUsers.size !== 1 ? 's' : ''} selected
                  </span>
                  <div className="flex items-center gap-2">
                    <button onClick={() => handleBulkAction('activate')} disabled={bulkProcessing}
                      className="px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-1">
                      <CheckCircle className="w-3.5 h-3.5" /> Activate
                    </button>
                    <button onClick={() => handleBulkAction('suspend')} disabled={bulkProcessing}
                      className="px-3 py-1.5 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1">
                      <Ban className="w-3.5 h-3.5" /> Suspend
                    </button>
                    <button onClick={() => handleBulkAction('delete')} disabled={bulkProcessing}
                      className="px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center gap-1">
                      <Trash2 className="w-3.5 h-3.5" /> Delete
                    </button>
                    <button onClick={() => setSelectedUsers(new Set())}
                      className="px-3 py-1.5 text-gray-600 dark:text-gray-400 text-sm hover:text-gray-800">
                      Clear
                    </button>
                  </div>
                </div>
              )}
              <div className="overflow-x-auto hidden md:block">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700" data-testid="resellers-table">
                  <thead className="bg-gray-50 dark:bg-gray-800">
                    <tr>
                      <th className="px-3 py-3 w-10">
                        <input type="checkbox" checked={paginatedData?.length > 0 && selectedUsers.size === paginatedData?.length}
                          onChange={toggleSelectAll} className="w-4 h-4 text-blue-600 rounded" />
                      </th>
                      <th onClick={() => handleSort('username')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer"><span className="flex items-center gap-1">Username <SortIcon column="username" /></span></th>
                      <th onClick={() => handleSort('panel_name')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer"><span className="flex items-center gap-1">Panel <SortIcon column="panel_name" /></span></th>
                      <th onClick={() => handleSort('credits')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer"><span className="flex items-center gap-1">Credits <SortIcon column="credits" /></span></th>
                      <th onClick={() => handleSort('status')} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase cursor-pointer"><span className="flex items-center gap-1">Status <SortIcon column="status" /></span></th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                    {paginatedData.map((user) => (
                      <tr key={user.id} className={`hover:bg-gray-50 dark:hover:bg-gray-800 ${selectedUsers.has(user.id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}`}>
                        <td className="px-3 py-4 w-10">
                          <input type="checkbox" checked={selectedUsers.has(user.id)}
                            onChange={() => toggleSelectUser(user.id)} className="w-4 h-4 text-blue-600 rounded" />
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            <UserCog className="w-4 h-4 text-purple-500 mr-2" />
                            <div className="text-sm font-medium text-gray-900 dark:text-white">{user.username}</div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">{user.panel_name}</td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center text-sm text-gray-900 dark:text-white">
                            <CreditCard className="w-4 h-4 text-green-500 mr-1" />{user.credits || 0}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(user.status)}`}>{user.status}</span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                          <div className="flex items-center gap-2 justify-end">
                            <button onClick={() => { setSelectedUserForCredits(user); setShowCreditsModal(true); }}
                              className="text-green-600 hover:text-green-900 dark:hover:text-green-400" title="Add credits">
                              <CreditCard className="w-4 h-4 inline mr-1" />Credits
                            </button>
                            <button onClick={() => handleDelete(user)} disabled={deleteMutation.isPending}
                              className="text-red-600 hover:text-red-900 dark:hover:text-red-400" data-testid={`delete-reseller-${user.username}`}>
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Mobile card view for resellers */}
              <div className="md:hidden divide-y divide-gray-200 dark:divide-gray-700">
                {paginatedData.map((user) => (
                  <div key={user.id} className={`p-4 ${selectedUsers.has(user.id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <input type="checkbox" checked={selectedUsers.has(user.id)}
                          onChange={() => toggleSelectUser(user.id)} className="w-4 h-4 text-blue-600 rounded flex-shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <div className="flex items-center gap-1">
                            <UserCog className="w-3.5 h-3.5 text-purple-500 flex-shrink-0" />
                            <span className="text-sm font-semibold text-gray-900 dark:text-white truncate">{user.username}</span>
                          </div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">{user.panel_name}</div>
                        </div>
                      </div>
                      <span className={`px-2 py-0.5 text-xs font-semibold rounded-full flex-shrink-0 ${getStatusColor(user.status)}`}>{user.status}</span>
                    </div>
                    <div className="mt-2 ml-7 flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
                      <span className="flex items-center gap-1"><CreditCard className="w-3 h-3 text-green-500" />{user.credits || 0} credits</span>
                      <span>{user.member_group || 'Reseller'}</span>
                    </div>
                    <div className="mt-3 ml-7 flex items-center gap-3">
                      <button onClick={() => { setSelectedUserForCredits(user); setShowCreditsModal(true); }}
                        className="text-xs text-green-600 font-medium"><CreditCard className="w-3.5 h-3.5 inline mr-0.5" />Credits</button>
                      <button onClick={() => handleDelete(user)} className="text-xs text-red-600 font-medium ml-auto">
                        <Trash2 className="w-3.5 h-3.5 inline mr-0.5" />Delete</button>
                    </div>
                  </div>
                ))}
              </div>
              
              {/* Pagination */}
              <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    Showing {startIndex} to {endIndex} of {totalItems} entries
                  </span>
                  <select
                    value={entriesPerPage}
                    onChange={(e) => {
                      setEntriesPerPage(Number(e.target.value));
                      setCurrentPage(1);
                    }}
                    className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                    data-testid="entries-per-page-resellers"
                  >
                    <option value={10}>10 per page</option>
                    <option value={15}>15 per page</option>
                    <option value={25}>25 per page</option>
                    <option value={50}>50 per page</option>
                    <option value={100}>100 per page</option>
                  </select>
                </div>
                
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => goToPage(currentPage - 1)}
                    disabled={currentPage === 1}
                    className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="w-5 h-5 text-gray-600 dark:text-gray-300" />
                  </button>
                  
                  {getPageNumbers().map((page, index) => (
                    page === '...' ? (
                      <span key={`ellipsis-${index}`} className="px-2 text-gray-400">...</span>
                    ) : (
                      <button
                        key={page}
                        onClick={() => goToPage(page)}
                        className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                          currentPage === page
                            ? 'bg-purple-600 text-white'
                            : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }`}
                      >
                        {page}
                      </button>
                    )
                  ))}
                  
                  <button
                    onClick={() => goToPage(currentPage + 1)}
                    disabled={currentPage === totalPages}
                    className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronRight className="w-5 h-5 text-gray-600 dark:text-gray-300" />
                  </button>
                </div>
              </div>
            </div>
          )
        )}
      </main>

      {/* Create User Modal */}
      {showCreateModal && (
        <CreateUserModal
          panels={panels}
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            queryClient.invalidateQueries(['imported-users']);
            setShowCreateModal(false);
          }}
        />
      )}

      {/* Extend User Modal */}
      {showExtendModal && selectedUserForExtend && (
        <ExtendUserModal
          user={selectedUserForExtend}
          onClose={() => {
            setShowExtendModal(false);
            setSelectedUserForExtend(null);
          }}
          onSuccess={() => {
            queryClient.invalidateQueries(['imported-users']);
            setShowExtendModal(false);
            setSelectedUserForExtend(null);
          }}
        />
      )}

      {/* Add Credits Modal */}
      {showCreditsModal && selectedUserForCredits && (
        <AddCreditsModal
          user={selectedUserForCredits}
          onClose={() => {
            setShowCreditsModal(false);
            setSelectedUserForCredits(null);
          }}
          onSuccess={() => {
            queryClient.invalidateQueries(['imported-users']);
            setShowCreditsModal(false);
            setSelectedUserForCredits(null);
          }}
        />
      )}
    </div>
  );
}

// Create User Modal Component
function CreateUserModal({ panels, onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    panel_type: 'xtream',
    panel_index: 0,
    account_type: 'subscriber',
    username: '',
    password: '',
    package_id: '',
    duration_months: 1,
    max_connections: 1,
    credits: 0,
    member_group_id: 2
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createdUser, setCreatedUser] = useState(null);

  // Fetch packages for the selected panel
  const { data: settings } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: async () => {
      const response = await adminAPI.getSettings();
      return response.data;
    },
  });

  // Get the panel list based on panel_type
  const getPanelList = () => {
    if (formData.panel_type === 'xtream') {
      return settings?.xtream?.panels?.map((p, i) => ({ ...p, index: i, label: `${p.name} (XtreamUI)` })) || [];
    } else if (formData.panel_type === 'onestream') {
      return settings?.onestream?.panels?.map((p, i) => ({ ...p, index: i, label: `${p.name} (1-Stream)` })) || [];
    } else if (formData.panel_type === 'nxtdash') {
      return settings?.nxtdash?.panels?.map((p, i) => ({ ...p, index: i, label: `${p.name} (NXT Dash)` })) || [];
    } else if (formData.panel_type === 'aether') {
      return settings?.aether?.panels?.map((p, i) => ({ ...p, index: i, label: `${p.name || 'Aether'} (Aether)` })) || [];
    } else if (formData.panel_type === 'gold') {
      return settings?.gold?.panels?.map((p, i) => ({ ...p, index: i, label: `${p.name || 'Gold'} (Gold Panel)` })) || [];
    } else {
      return settings?.xuione?.panels?.map((p, i) => ({ ...p, index: i, label: `${p.name} (XuiOne)` })) || [];
    }
  };

  const panelList = getPanelList();

  // Fetch packages for XtreamUI
  const { data: xtreamPackages } = useQuery({
    queryKey: ['xtream-packages', formData.panel_index],
    queryFn: async () => {
      const response = await adminAPI.syncPackagesFromPanel(formData.panel_index);
      return response.data;
    },
    enabled: formData.panel_type === 'xtream' && formData.account_type === 'subscriber',
  });

  // Fetch packages for XuiOne
  const { data: xuionePackages } = useQuery({
    queryKey: ['xuione-packages', formData.panel_index],
    queryFn: async () => {
      const response = await adminAPI.syncXuiOnePackages(formData.panel_index);
      return response.data;
    },
    enabled: formData.panel_type === 'xuione' && formData.account_type === 'subscriber',
  });

  // Fetch packages for 1-Stream
  const { data: onestreamPackages } = useQuery({
    queryKey: ['onestream-packages', formData.panel_index],
    queryFn: async () => {
      const response = await adminAPI.syncOneStreamPackages(formData.panel_index);
      return response.data;
    },
    enabled: formData.panel_type === 'onestream' && formData.account_type === 'subscriber',
  });

  // Fetch packages for NXT Dash
  const { data: nxtdashPackages } = useQuery({
    queryKey: ['nxtdash-packages', formData.panel_index],
    queryFn: async () => {
      const response = await adminAPI.getNxtDashPackages(formData.panel_index);
      return response.data;
    },
    enabled: formData.panel_type === 'nxtdash' && formData.account_type === 'subscriber',
  });

  // Fetch packages for Aether
  const { data: aetherPackages } = useQuery({
    queryKey: ['aether-packages', formData.panel_index],
    queryFn: async () => {
      const response = await adminAPI.getAetherPackages(formData.panel_index);
      return response.data;
    },
    enabled: formData.panel_type === 'aether' && formData.account_type === 'subscriber',
  });

  // Fetch packages (bouquets) for Gold Panel — the term is chosen separately
  const { data: goldPackages } = useQuery({
    queryKey: ['gold-packages-full', formData.panel_index],
    queryFn: async () => (await adminAPI.getGoldPackages(formData.panel_index)).data,
    enabled: formData.panel_type === 'gold' && formData.account_type === 'subscriber',
  });

  const packages = formData.panel_type === 'xtream' ? (xtreamPackages?.packages || []) 
    : formData.panel_type === 'onestream' ? (onestreamPackages?.packages || [])
    : formData.panel_type === 'nxtdash' ? (nxtdashPackages?.packages || [])
    : formData.panel_type === 'aether' ? ([...(aetherPackages?.packages || []), ...(aetherPackages?.trial_packages || [])])
    : formData.panel_type === 'gold' ? ((goldPackages?.bouquets || []).map((b) => ({ id: b.id, name: b.name, duration: formData.duration_months, duration_unit: 'months', max_connections: 1 })))
    : (xuionePackages?.packages || []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      const submitData = {
        panel_type: formData.panel_type,
        panel_index: parseInt(formData.panel_index),
        account_type: formData.account_type,
        username: formData.username || null,
        password: formData.password || null,
      };

      if (formData.account_type === 'subscriber') {
        submitData.package_id = formData.panel_type === 'gold' ? String(formData.package_id) : parseInt(formData.package_id);
        submitData.duration_months = parseInt(formData.duration_months);
        submitData.max_connections = parseInt(formData.max_connections);
      } else {
        submitData.credits = parseFloat(formData.credits);
        submitData.member_group_id = parseInt(formData.member_group_id);
      }

      const response = await adminAPI.createImportedUser(submitData);
      setCreatedUser(response.data.user);
      
    } catch (error) {
      toast.error('Failed to create user: ' + (error.response?.data?.detail || error.message));
    } finally {
      setIsSubmitting(false);
    }
  };

  // If user was created, show success view
  if (createdUser) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full">
          <div className="bg-green-600 text-white px-6 py-4 rounded-t-lg flex justify-between items-center">
            <h3 className="text-xl font-bold flex items-center gap-2">
              <CheckCircle className="w-6 h-6" />
              User Created Successfully
            </h3>
            <button onClick={onSuccess} className="text-white hover:text-gray-200">
              <X className="w-6 h-6" />
            </button>
          </div>

          <div className="p-6 space-y-4">
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 space-y-3">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Panel</p>
                <p className="font-semibold text-gray-900 dark:text-white">{createdUser.panel_name}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Account Type</p>
                <p className="font-semibold text-gray-900 dark:text-white capitalize">{createdUser.account_type}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Username</p>
                <p className="font-mono font-semibold text-gray-900 dark:text-white">{createdUser.username}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Password</p>
                <p className="font-mono font-semibold text-gray-900 dark:text-white">{createdUser.password}</p>
              </div>
              {createdUser.ghostapk_code && (
                <div data-testid="created-user-ghostapk-pin">
                  <p className="text-sm text-gray-500 dark:text-gray-400">GhostAPK Login Pin</p>
                  <p className="font-mono font-semibold tracking-[0.2em] text-violet-700 dark:text-violet-300">{createdUser.ghostapk_code}</p>
                </div>
              )}
              {createdUser.expiry_date && (
                <div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Expiry Date</p>
                  <p className="font-semibold text-gray-900 dark:text-white">
                    {formatDate(createdUser.expiry_date, timezone)}
                  </p>
                </div>
              )}
              {createdUser.max_connections && (
                <div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Max Connections</p>
                  <p className="font-semibold text-gray-900 dark:text-white">{createdUser.max_connections}</p>
                </div>
              )}
              {createdUser.duration_months && (
                <div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Duration</p>
                  <p className="font-semibold text-gray-900 dark:text-white">{createdUser.duration_months} month(s)</p>
                </div>
              )}
              {createdUser.m3u_url && (
                <div className="col-span-2">
                  <p className="text-sm text-gray-500 dark:text-gray-400">M3U URL</p>
                  <p className="font-mono text-xs break-all text-gray-900 dark:text-white" data-testid="created-m3u-url">{createdUser.m3u_url}</p>
                </div>
              )}
              {createdUser.credits !== undefined && (
                <div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Credits</p>
                  <p className="font-semibold text-gray-900 dark:text-white">{createdUser.credits}</p>
                </div>
              )}
            </div>

            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
              <p className="text-sm text-yellow-800 dark:text-yellow-200">
                <strong>Important:</strong> Save these credentials. The password will not be shown again.
              </p>
            </div>

            <button
              onClick={onSuccess}
              className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 font-semibold"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white">Create Panel User</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Panel Type Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Panel Type *
            </label>
            <select
              value={formData.panel_type}
              onChange={(e) => setFormData({ ...formData, panel_type: e.target.value, panel_index: 0, package_id: '' })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="panel-type-select"
            >
              <option value="xtream">XtreamUI</option>
              <option value="xuione">XuiOne</option>
              <option value="onestream">1-Stream</option>
              <option value="nxtdash">NXT Dash</option>
              <option value="aether">Aether</option>
              <option value="gold">Gold Panel</option>
            </select>
          </div>

          {/* Panel Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Panel *
            </label>
            <select
              value={formData.panel_index}
              onChange={(e) => setFormData({ ...formData, panel_index: parseInt(e.target.value), package_id: '' })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="panel-select"
            >
              {panelList.length === 0 ? (
                <option value="">No panels configured</option>
              ) : (
                panelList.map((panel) => (
                  <option key={panel.index} value={panel.index}>{panel.label || panel.name}</option>
                ))
              )}
            </select>
          </div>

          {/* Account Type Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Account Type *
            </label>
            <select
              value={formData.account_type}
              onChange={(e) => setFormData({ ...formData, account_type: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="account-type-select"
            >
              <option value="subscriber">Subscriber</option>
              {(formData.panel_type === 'xtream' || formData.panel_type === 'onestream') && <option value="reseller">Reseller</option>}
            </select>
            {(formData.panel_type === 'xuione' || formData.panel_type === 'nxtdash' || formData.panel_type === 'aether' || formData.panel_type === 'gold') && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Note: {({ xuione: 'XuiOne', aether: 'Aether', gold: 'Gold Panel', nxtdash: 'NXT Dash' })[formData.panel_type]} reseller creation is not supported via API
              </p>
            )}
          </div>

          {formData.panel_type === 'gold' && (
            <p className="text-xs text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-3" data-testid="gold-create-hint">
              Gold Panel generates the M3U username and password itself — the fields below are ignored for Gold devices.
            </p>
          )}

          {/* Username (optional) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Username <span className="text-gray-400">(leave blank to auto-generate)</span>
            </label>
            <input
              type="text"
              value={formData.username}
              onChange={(e) => setFormData({ ...formData, username: e.target.value })}
              placeholder="Auto-generate if blank"
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="username-input"
            />
          </div>

          {/* Password (optional) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Password <span className="text-gray-400">(leave blank to auto-generate)</span>
            </label>
            <input
              type="text"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              placeholder="Auto-generate if blank"
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="password-input"
            />
          </div>

          {/* Subscriber-specific fields */}
          {formData.account_type === 'subscriber' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Package *
                </label>
                <select
                  required
                  value={formData.package_id}
                  onChange={(e) => setFormData({ ...formData, package_id: e.target.value })}
                  className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                  data-testid="package-select"
                >
                  <option value="">Select a package...</option>
                  {packages.map((pkg) => (
                    <option key={pkg.id} value={pkg.id}>{pkg.name}</option>
                  ))}
                </select>
                {packages.length === 0 && (
                  <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                    No packages found. Click sync to fetch packages from the panel.
                  </p>
                )}
              </div>

              {formData.panel_type === 'gold' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Subscription length *</label>
                  <select
                    value={formData.duration_months}
                    onChange={(e) => setFormData({ ...formData, duration_months: parseInt(e.target.value) })}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                    data-testid="gold-term-select"
                  >
                    {[1, 3, 6, 12].map((m) => (<option key={m} value={m}>{m} month{m > 1 ? 's' : ''}</option>))}
                  </select>
                </div>
              )}

              {/* Show selected package details */}
              {formData.package_id && (() => {
                const selectedPkg = packages.find(p => String(p.id) === String(formData.package_id));
                if (selectedPkg) {
                  return (
                    <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 space-y-2">
                      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">Package Details</h4>
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <span className="text-gray-500 dark:text-gray-400">Duration:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {selectedPkg.duration} {selectedPkg.duration_unit || 'months'}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500 dark:text-gray-400">Max Connections:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {selectedPkg.max_connections || '1'}
                          </span>
                        </div>
                        {selectedPkg.credits && (
                          <div>
                            <span className="text-gray-500 dark:text-gray-400">Credits Cost:</span>
                            <span className="ml-2 font-medium text-gray-900 dark:text-white">
                              {selectedPkg.credits}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                }
                return null;
              })()}
            </>
          )}

          {/* Reseller-specific fields */}
          {formData.account_type === 'reseller' && formData.panel_type === 'xtream' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Credits
              </label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={formData.credits}
                onChange={(e) => setFormData({ ...formData, credits: parseFloat(e.target.value) })}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                data-testid="credits-input"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Initial credits to assign to the reseller
              </p>
            </div>
          )}

          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
            <p className="text-sm text-blue-800 dark:text-blue-200">
              <strong>Note:</strong> This will create a user directly on the panel. The user will not be linked to any customer account in the billing system.
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || (formData.account_type === 'subscriber' && !formData.package_id)}
              className="flex-1 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
              data-testid="create-user-submit"
            >
              {isSubmitting ? (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Plus className="w-5 h-5" />
                  Create User
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Extend User Modal Component
function ExtendUserModal({ user, onClose, onSuccess }) {
  const timezone = useTimezone();
  const [selectedPackageId, setSelectedPackageId] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  // Fetch ALL packages for the user's panel — exclude trial packages (can't extend WITH trial)
  const { data: packages, isLoading: packagesLoading } = useQuery({
    queryKey: ['all-packages', user.panel_type, user.panel_index],
    queryFn: async () => {
      const panelType = user.panel_type || 'xtream';
      
      if (panelType === 'xtream') {
        const response = await adminAPI.syncPackagesFromPanel(user.panel_index || 0);
        // Only return regular packages — trial packages can't be used to extend
        return response.data?.packages || [];
      } else if (panelType === 'onestream') {
        const response = await adminAPI.syncOneStreamPackages(user.panel_index || 0);
        return (response.data?.packages || []).filter(p => !p.is_trial);
      } else if (panelType === 'nxtdash') {
        const response = await adminAPI.getNxtDashPackages(user.panel_index || 0);
        return response.data?.packages || [];
      } else if (panelType === 'aether') {
        const response = await adminAPI.getAetherPackages(user.panel_index || 0);
        return [...(response.data?.packages || []), ...(response.data?.extension_packages || [])];
      } else if (panelType === 'gold') {
        const response = await adminAPI.getGoldPackages(user.panel_index || 0);
        return response.data?.terms || [];
      } else {
        const response = await adminAPI.syncXuiOnePackages(user.panel_index || 0);
        return (response.data?.packages || []).filter(p => !p.is_trial);
      }
    },
  });

  // Get selected package details
  const selectedPackage = packages?.find(p => String(p.id) === String(selectedPackageId));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedPackageId) {
      toast.error('Please select a package');
      return;
    }
    setIsSubmitting(true);

    try {
      const response = await adminAPI.extendImportedUser(user.id, {
        package_id: parseInt(selectedPackageId)
      });
      setResult(response.data);
    } catch (error) {
      toast.error('Failed to extend user: ' + (error.response?.data?.detail || error.message));
    } finally {
      setIsSubmitting(false);
    }
  };

  // Success view
  if (result) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full">
          <div className="bg-green-600 text-white px-6 py-4 rounded-t-lg flex justify-between items-center">
            <h3 className="text-xl font-bold flex items-center gap-2">
              <CheckCircle className="w-6 h-6" />
              Subscription Extended
            </h3>
            <button onClick={onSuccess} className="text-white hover:text-gray-200">
              <X className="w-6 h-6" />
            </button>
          </div>

          <div className="p-6 space-y-4">
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 space-y-3">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Username</p>
                <p className="font-mono font-semibold text-gray-900 dark:text-white">{user.username}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Previous Expiry</p>
                <p className="font-semibold text-gray-900 dark:text-white">
                  {result.previous_expiry ? formatDate(result.previous_expiry, timezone) : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">New Expiry</p>
                <p className="font-semibold text-green-600 dark:text-green-400">
                  {formatDate(result.new_expiry, timezone)}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Days Added</p>
                <p className="font-semibold text-gray-900 dark:text-white">{result.days_added} days</p>
              </div>
            </div>

            <button
              onClick={onSuccess}
              className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 font-semibold"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full">
        <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white">Extend Subscription</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* User Info */}
          <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500 dark:text-gray-400">Username:</span>
                <span className="ml-2 font-mono font-medium text-gray-900 dark:text-white">{user.username}</span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Panel:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">{user.panel_name}</span>
              </div>
              <div className="col-span-2">
                <span className="text-gray-500 dark:text-gray-400">Current Expiry:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">
                  {user.expiry_date ? formatDate(user.expiry_date, timezone) : 'N/A'}
                </span>
              </div>
            </div>
          </div>

          {/* Package Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Select Package to Extend *
            </label>
            {packagesLoading ? (
              <div className="flex items-center gap-2 text-gray-500">
                <RefreshCw className="w-4 h-4 animate-spin" />
                Loading packages...
              </div>
            ) : (
              <select
                required
                value={selectedPackageId}
                onChange={(e) => setSelectedPackageId(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                data-testid="extend-package-select"
              >
                <option value="">Select a package...</option>
                {packages?.map((pkg) => (
                  <option key={pkg.id} value={pkg.id}>
                    {pkg.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Show selected package details */}
          {selectedPackage && (
            <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
              <h4 className="text-sm font-medium text-blue-800 dark:text-blue-200 mb-2">Package Details</h4>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-blue-600 dark:text-blue-300">Duration:</span>
                  <span className="ml-2 font-medium text-blue-900 dark:text-blue-100">
                    {selectedPackage.duration} {selectedPackage.duration_unit || 'months'}
                  </span>
                </div>
                <div>
                  <span className="text-blue-600 dark:text-blue-300">Max Connections:</span>
                  <span className="ml-2 font-medium text-blue-900 dark:text-blue-100">
                    {selectedPackage.max_connections || '1'}
                  </span>
                </div>
                {selectedPackage.credits && (
                  <div className="col-span-2">
                    <span className="text-blue-600 dark:text-blue-300">Credit Cost:</span>
                    <span className="ml-2 font-medium text-blue-900 dark:text-blue-100">
                      {selectedPackage.credits} credits
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
            <p className="text-sm text-green-800 dark:text-green-200">
              <strong>Note:</strong> This will extend the subscription on both the billing system and the {({ xtream: 'XtreamUI', onestream: '1-Stream', nxtdash: 'NXT Dash', aether: 'Aether', gold: 'Gold' })[user.panel_type] || 'XuiOne'} panel.
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !selectedPackageId}
              className="flex-1 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
              data-testid="extend-user-submit"
            >
              {isSubmitting ? (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin" />
                  Extending...
                </>
              ) : (
                <>
                  <Clock className="w-5 h-5" />
                  Extend Subscription
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Add Credits Modal Component
function AddCreditsModal({ user, onClose, onSuccess }) {
  const [credits, setCredits] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const amount = parseFloat(credits);
    if (!amount || amount <= 0) {
      toast.error('Please enter a valid credit amount');
      return;
    }
    setIsSubmitting(true);
    try {
      const response = await adminAPI.addCreditsToImportedUser(user.id, amount);
      setResult(response.data);
    } catch (error) {
      toast.error('Failed to add credits: ' + (error.response?.data?.detail || error.message));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (result) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full">
          <div className="bg-green-600 text-white px-6 py-4 rounded-t-lg flex justify-between items-center">
            <h3 className="text-xl font-bold flex items-center gap-2">
              <CheckCircle className="w-6 h-6" />
              Credits Added
            </h3>
            <button onClick={onSuccess} className="text-white hover:text-gray-200">
              <X className="w-6 h-6" />
            </button>
          </div>
          <div className="p-6 space-y-4">
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 space-y-3">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Reseller</p>
                <p className="font-semibold text-gray-900 dark:text-white">{user.username}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">New Credit Balance</p>
                <p className="font-semibold text-green-600 dark:text-green-400">{result.new_credits}</p>
              </div>
            </div>
            <button onClick={onSuccess} className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 font-semibold">
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full">
        <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white">Add Credits</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-6 h-6" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500 dark:text-gray-400">Reseller:</span>
                <span className="ml-2 font-mono font-medium text-gray-900 dark:text-white">{user.username}</span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Panel:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">{user.panel_name}</span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Current Credits:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">{user.credits || 0}</span>
              </div>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Credits to Add *</label>
            <input
              type="number" required min="0.01" step="0.01"
              value={credits}
              onChange={(e) => setCredits(e.target.value)}
              placeholder="Enter credit amount"
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500 text-lg"
              autoFocus
            />
          </div>

          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
            <p className="text-sm text-yellow-800 dark:text-yellow-200">
              <strong>Note:</strong> Credits will be added directly on the {user.panel_type === 'onestream' ? '1-Stream' : user.panel_type === 'xuione' ? 'XuiOne' : 'XtreamUI'} panel.
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <button type="button" onClick={onClose}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700">
              Cancel
            </button>
            <button type="submit" disabled={isSubmitting || !credits}
              className="flex-1 bg-green-600 text-white px-6 py-3 rounded-lg hover:bg-green-700 font-semibold disabled:opacity-50 flex items-center justify-center gap-2">
              {isSubmitting ? (
                <><RefreshCw className="w-5 h-5 animate-spin" /> Adding...</>
              ) : (
                <><CreditCard className="w-5 h-5" /> Add Credits</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

