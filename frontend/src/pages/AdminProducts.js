import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import api from '../api/api';
import { ArrowLeft, Plus, Edit, Trash2, X, Save, Package, ChevronUp, ChevronDown, Tv, Users, LinkIcon, Check } from 'lucide-react';
import { getPanelGradient, getPanelColor } from '../utils/panelColors';
import { toast } from 'sonner';

export default function AdminProducts() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [showResellerModal, setShowResellerModal] = useState(false);
  const [showManualModal, setShowManualModal] = useState(false);
  const [showBundleModal, setShowBundleModal] = useState(false);
  const [editingProduct, setEditingProduct] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  
  // Filters for list view
  const [searchQuery, setSearchQuery] = useState('');
  const [panelFilter, setPanelFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  
  const { data: products, isLoading } = useQuery({
    queryKey: ['admin-products'],
    queryFn: async () => {
      const response = await adminAPI.getProducts();
      return response.data;
    },
  });

  // Fetch settings to get panel names
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
  const aetherPanels = settings?.aether?.panels || [];
  
  // Combine all panel types with a type indicator
  const allPanels = [
    ...xtreamPanels.map((panel, index) => ({ ...panel, type: 'xtream', originalIndex: index })),
    ...xuionePanels.map((panel, index) => ({ ...panel, type: 'xuione', originalIndex: index })),
    ...onestreamPanels.map((panel, index) => ({ ...panel, type: 'onestream', originalIndex: index })),
    ...nxtdashPanels.map((panel, index) => ({ ...panel, type: 'nxtdash', originalIndex: index })),
    ...ghostsurfPanels.map((panel, index) => ({ ...panel, type: 'ghostsurf', originalIndex: index })),
    ...aetherPanels.map((panel, index) => ({ ...panel, type: 'aether', originalIndex: index }))
  ];
  
  // For components that need just XtreamUI panels (like ResellerPackageModal)
  const panels = xtreamPanels;
  
  const getPanelName = (panelIndex, panelType = 'xtream') => {
    if (panelIndex === undefined || panelIndex === null) return 'Default Panel';
    
    if (panelType === 'xuione') {
      return xuionePanels[panelIndex]?.name || `XuiOne Panel ${panelIndex}`;
    }
    if (panelType === 'onestream') {
      return onestreamPanels[panelIndex]?.name || `1-Stream Panel ${panelIndex}`;
    }
    if (panelType === 'nxtdash') {
      return nxtdashPanels[panelIndex]?.name || `NXT Dash Panel ${panelIndex}`;
    }
    if (panelType === 'ghostsurf') {
      return ghostsurfPanels[panelIndex]?.name || `GhostSurf VPN ${panelIndex}`;
    }
    if (panelType === 'aether') {
      return aetherPanels[panelIndex]?.name || `Aether Panel ${panelIndex}`;
    }
    return xtreamPanels[panelIndex]?.name || `Panel ${panelIndex}`;
  };

  // Group products by panel (using both panel_type and panel_index)
  const productsByPanel = React.useMemo(() => {
    if (!products) return {};
    
    const grouped = {};
    products.forEach(product => {
      const panelType = product.panel_type || 'xtream';
      const panelIndex = product.panel_index ?? 0;
      const panelKey = `${panelType}-${panelIndex}`;
      
      if (!grouped[panelKey]) {
        grouped[panelKey] = [];
      }
      grouped[panelKey].push(product);
    });
    
    return grouped;
  }, [products]);

  const handleAddNew = () => {
    setEditingProduct(null);
    setShowModal(true);
  };

  const handleEdit = (product) => {
    setEditingProduct(product);
    
    if (product.is_bundle) {
      setShowBundleModal(true);
    } else if (product.account_type === 'reseller') {
      setShowResellerModal(true);
    } else if (product.panel_type === 'manual') {
      setShowManualModal(true);
    } else {
      setShowModal(true);
    }
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setShowResellerModal(false);
    setEditingProduct(null);
  };

  const deleteMutation = useMutation({
    mutationFn: (id) => adminAPI.deleteProduct(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-products']);
      toast.success('Product deleted successfully!');
    },
  });

  const handleDelete = (product) => {
    if (window.confirm(`Delete "${product.name}"? This cannot be undone.`)) {
      deleteMutation.mutate(product.id);
    }
  };

  const reorderMutation = useMutation({
    mutationFn: ({ id, direction }) => adminAPI.reorderProduct(id, direction),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-products']);
    },
  });

  const handleReorder = (product, direction) => {
    reorderMutation.mutate({ id: product.id, direction });
  };

  // Product Groups
  const { data: productGroups } = useQuery({
    queryKey: ['product-groups'],
    queryFn: async () => { const r = await adminAPI.getProductGroups(); return r.data; },
  });
  const [showGroupManager, setShowGroupManager] = useState(false);
  const [groups, setGroups] = useState([]);
  const [newGroupName, setNewGroupName] = useState('');
  const [newSubgroupName, setNewSubgroupName] = useState({});

  React.useEffect(() => {
    if (productGroups) setGroups(productGroups);
  }, [productGroups]);

  const saveGroups = async (updatedGroups) => {
    try {
      await adminAPI.saveProductGroups(updatedGroups);
      setGroups(updatedGroups);
      queryClient.invalidateQueries(['product-groups']);
      toast.success('Groups saved');
    } catch (e) { toast.error('Failed to save groups'); }
  };

  const addGroup = () => {
    if (!newGroupName.trim()) return;
    const id = 'grp_' + Date.now();
    const updated = [...groups, { id, name: newGroupName.trim(), display_order: groups.length, subgroups: [] }];
    saveGroups(updated);
    setNewGroupName('');
  };

  const moveGroup = (index, direction) => {
    const updated = [...groups];
    const swapIdx = direction === 'up' ? index - 1 : index + 1;
    if (swapIdx < 0 || swapIdx >= updated.length) return;
    [updated[index], updated[swapIdx]] = [updated[swapIdx], updated[index]];
    updated.forEach((g, i) => g.display_order = i);
    saveGroups(updated);
  };

  const removeGroup = (index) => {
    if (!window.confirm('Remove this group? Products will become ungrouped.')) return;
    const gid = groups[index].id;
    const sgIds = (groups[index].subgroups || []).map(s => s.id);
    const updated = groups.filter((_, i) => i !== index);
    products?.forEach(p => {
      if (p.group_id === gid) adminAPI.setProductGroup(p.id, '', '');
    });
    saveGroups(updated);
    queryClient.invalidateQueries(['admin-products']);
  };

  const addSubgroup = (groupIndex) => {
    const name = (newSubgroupName[groupIndex] || '').trim();
    if (!name) return;
    const updated = [...groups];
    const subs = updated[groupIndex].subgroups || [];
    subs.push({ id: 'sg_' + Date.now(), name, display_order: subs.length });
    updated[groupIndex].subgroups = subs;
    saveGroups(updated);
    setNewSubgroupName({ ...newSubgroupName, [groupIndex]: '' });
  };

  const moveSubgroup = (groupIndex, subIndex, direction) => {
    const updated = [...groups];
    const subs = [...(updated[groupIndex].subgroups || [])];
    const swapIdx = direction === 'up' ? subIndex - 1 : subIndex + 1;
    if (swapIdx < 0 || swapIdx >= subs.length) return;
    [subs[subIndex], subs[swapIdx]] = [subs[swapIdx], subs[subIndex]];
    subs.forEach((s, i) => s.display_order = i);
    updated[groupIndex].subgroups = subs;
    saveGroups(updated);
  };

  const removeSubgroup = (groupIndex, subIndex) => {
    if (!window.confirm('Remove this sub-group?')) return;
    const updated = [...groups];
    const sgId = updated[groupIndex].subgroups[subIndex].id;
    updated[groupIndex].subgroups = updated[groupIndex].subgroups.filter((_, i) => i !== subIndex);
    products?.forEach(p => {
      if (p.subgroup_id === sgId) adminAPI.setProductGroup(p.id, p.group_id, '');
    });
    saveGroups(updated);
    queryClient.invalidateQueries(['admin-products']);
  };

  const setProductGroupAndSub = async (productId, groupId, subgroupId) => {
    try {
      await adminAPI.setProductGroup(productId, groupId, subgroupId);
      queryClient.invalidateQueries(['admin-products']);
    } catch (e) { toast.error('Failed'); }
  };

  // All subgroups flat list for the product table dropdowns
  const allSubgroups = React.useMemo(() => {
    const result = [];
    (groups || []).forEach(g => {
      (g.subgroups || []).forEach(sg => {
        result.push({ ...sg, groupId: g.id, groupName: g.name, label: `${g.name} > ${sg.name}` });
      });
    });
    return result;
  }, [groups]);

  // Group products for admin table display using subgroups
  const groupedProducts = React.useMemo(() => {
    if (!products) return [];
    const result = [];
    const groupList = groups || [];
    groupList.forEach(g => {
      const subs = g.subgroups || [];
      if (subs.length > 0) {
        subs.forEach(sg => {
          const prods = products.filter(p => p.group_id === g.id && p.subgroup_id === sg.id).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
          result.push({ id: sg.id, name: `${g.name} > ${sg.name}`, products: prods });
        });
        // Products in group but no subgroup
        const sgIds = new Set(subs.map(s => s.id));
        const noSub = products.filter(p => p.group_id === g.id && (!p.subgroup_id || !sgIds.has(p.subgroup_id))).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
        if (noSub.length > 0) result.push({ id: g.id + '_unsub', name: `${g.name} > (unassigned)`, products: noSub });
      } else {
        const prods = products.filter(p => p.group_id === g.id).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
        result.push({ id: g.id, name: g.name, products: prods });
      }
    });
    // Ungrouped
    const allGids = new Set(groupList.map(g => g.id));
    const ungrouped = products.filter(p => !p.group_id || !allGids.has(p.group_id)).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
    if (ungrouped.length > 0) result.push({ id: '', name: 'Ungrouped', products: ungrouped });
    return result;
  }, [products, groups]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400">
              <ArrowLeft className="w-5 h-5" />
              Back to Dashboard
            </Link>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Manage Products</h1>
          
          {/* Add New Product Buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleAddNew}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <Plus className="w-5 h-5" />
              Add Subscriber Package
            </button>
            <button
              onClick={() => setShowResellerModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700"
            >
              <Plus className="w-5 h-5" />
              Add Reseller Package
            </button>
            <button
              onClick={() => setShowManualModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700"
            >
              <Plus className="w-5 h-5" />
              Add Manual Product
            </button>
            <button
              onClick={() => { setEditingProduct(null); setShowBundleModal(true); }}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700"
              data-testid="add-bundle-btn"
            >
              <Plus className="w-5 h-5" />
              Add Bundle
            </button>
          </div>
        </div>

        {/* Manual Product Modal */}
        {showManualModal && (
          <ManualProductModal
            onClose={() => { setShowManualModal(false); setEditingProduct(null); }}
            onSuccess={() => {
              setShowManualModal(false);
              setEditingProduct(null);
              queryClient.invalidateQueries(['admin-products']);
            }}
            editingProduct={editingProduct}
          />
        )}

        {/* Bundle Product Modal */}
        {showBundleModal && (
          <BundleProductModal
            onClose={() => { setShowBundleModal(false); setEditingProduct(null); }}
            onSuccess={() => {
              setShowBundleModal(false);
              setEditingProduct(null);
              queryClient.invalidateQueries(['admin-products']);
            }}
            products={products || []}
            editingProduct={editingProduct}
            getPanelName={getPanelName}
          />
        )}


        {/* Reseller Package Modal */}
        {showResellerModal && (
          <ResellerPackageModal
            onClose={() => {
              setShowResellerModal(false);
              setEditingProduct(null);
            }}
            onSuccess={() => {
              setShowResellerModal(false);
              setEditingProduct(null);
              queryClient.invalidateQueries(['admin-products']);
            }}
            panels={allPanels}
            xtreamPanels={xtreamPanels}
            xuionePanels={xuionePanels}
            editingProduct={editingProduct}
          />
        )}

        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : (
          /* List View */
          <div className="space-y-4">
            {/* Filters for List View */}
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
              <div className="grid md:grid-cols-4 gap-4">
                {/* Search */}
                <div className="md:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Search
                  </label>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search by name or description..."
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                  />
                </div>
                
                {/* Panel Filter */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Panel
                  </label>
                  <select
                    value={panelFilter}
                    onChange={(e) => setPanelFilter(e.target.value)}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                  >
                    <option value="all">All Panels</option>
                    {allPanels.map((panel, idx) => (
                      <option key={idx} value={`${panel.type}-${panel.originalIndex}`}>
                        {panel.name || `${panel.type === 'xuione' ? 'XuiOne' : panel.type === 'onestream' ? '1-Stream' : panel.type === 'nxtdash' ? 'NXT Dash' : panel.type === 'ghostsurf' ? 'GhostSurf VPN' : panel.type === 'aether' ? 'Aether' : 'XtreamUI'} Panel ${panel.originalIndex + 1}`}
                      </option>
                    ))}
                  </select>
                </div>
                
                {/* Type Filter */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Product Type
                  </label>
                  <select
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                  >
                    <option value="all">All Types</option>
                    <option value="subscriber">Subscriber</option>
                    <option value="reseller">Reseller</option>
                  </select>
                </div>
              </div>
              
              {/* Active Filters Summary */}
              {(searchQuery || panelFilter !== 'all' || typeFilter !== 'all') && (
                <div className="mt-3 flex items-center justify-between">
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    {products?.filter(p => {
                      const matchesSearch = !searchQuery || 
                        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        p.description?.toLowerCase().includes(searchQuery.toLowerCase());
                      const matchesPanel = panelFilter === 'all' || 
                        `${p.panel_type || 'xtream'}-${p.panel_index ?? 0}` === panelFilter;
                      const matchesType = typeFilter === 'all' || p.account_type === typeFilter;
                      return matchesSearch && matchesPanel && matchesType;
                    }).length || 0} products found
                  </p>
                  <button
                    onClick={() => {
                      setSearchQuery('');
                      setPanelFilter('all');
                      setTypeFilter('all');
                    }}
                    className="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-700"
                  >
                    Clear filters
                  </button>
                </div>
              )}
            </div>
            
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">

            {/* Group Manager Toggle */}
            <div className="px-6 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <button onClick={() => setShowGroupManager(!showGroupManager)}
                className="text-sm font-medium text-blue-600 hover:text-blue-800">
                {showGroupManager ? 'Hide Group Manager' : 'Manage Groups'}
              </button>
              <span className="text-xs text-gray-500">{groups.length} group{groups.length !== 1 ? 's' : ''}</span>
            </div>

            {showGroupManager && (
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-blue-50 dark:bg-blue-900/10">
                <div className="flex gap-2 mb-4">
                  <input value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} placeholder="New group name (e.g. CCTV, NXT Dash)"
                    onKeyDown={(e) => e.key === 'Enter' && addGroup()}
                    className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white" />
                  <button onClick={addGroup} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">Add Group</button>
                </div>
                <div className="space-y-3">
                  {groups.map((g, gi) => (
                    <div key={g.id} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="flex gap-0.5">
                          <button onClick={() => moveGroup(gi, 'up')} disabled={gi === 0} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-30"><ChevronUp className="w-3.5 h-3.5" /></button>
                          <button onClick={() => moveGroup(gi, 'down')} disabled={gi === groups.length - 1} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-30"><ChevronDown className="w-3.5 h-3.5" /></button>
                        </div>
                        <span className="font-bold text-gray-900 dark:text-white flex-1">{g.name}</span>
                        <span className="text-xs text-gray-500">{(g.subgroups || []).length} sub-groups</span>
                        <button onClick={() => removeGroup(gi)} className="text-red-500 hover:text-red-700 p-1"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                      {/* Subgroups */}
                      <div className="ml-8 space-y-1">
                        {(g.subgroups || []).map((sg, si) => (
                          <div key={sg.id} className="flex items-center gap-2 py-1 text-sm">
                            <div className="flex gap-0.5">
                              <button onClick={() => moveSubgroup(gi, si, 'up')} disabled={si === 0} className="p-0.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-30"><ChevronUp className="w-3 h-3" /></button>
                              <button onClick={() => moveSubgroup(gi, si, 'down')} disabled={si === (g.subgroups || []).length - 1} className="p-0.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-30"><ChevronDown className="w-3 h-3" /></button>
                            </div>
                            <span className="text-gray-700 dark:text-gray-300 flex-1">{sg.name}</span>
                            <span className="text-xs text-gray-400">{products?.filter(p => p.subgroup_id === sg.id).length || 0} products</span>
                            <button onClick={() => removeSubgroup(gi, si)} className="text-red-400 hover:text-red-600 p-0.5"><Trash2 className="w-3 h-3" /></button>
                          </div>
                        ))}
                        <div className="flex gap-1 mt-1">
                          <input value={newSubgroupName[gi] || ''} onChange={(e) => setNewSubgroupName({ ...newSubgroupName, [gi]: e.target.value })}
                            placeholder="Add sub-group (e.g. 1 Connection)"
                            onKeyDown={(e) => e.key === 'Enter' && addSubgroup(gi)}
                            className="flex-1 px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-900 text-gray-900 dark:text-white" />
                          <button onClick={() => addSubgroup(gi)} className="px-2 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700">Add</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Grouped Products */}
            <div>
              {groupedProducts.map((group) => {
                const filteredProds = group.products.filter(product => {
                  const matchesSearch = !searchQuery || product.name.toLowerCase().includes(searchQuery.toLowerCase()) || product.description?.toLowerCase().includes(searchQuery.toLowerCase());
                  const matchesPanel = panelFilter === 'all' || `${product.panel_type || 'xtream'}-${product.panel_index ?? 0}` === panelFilter;
                  const matchesType = typeFilter === 'all' || product.account_type === typeFilter;
                  return matchesSearch && matchesPanel && matchesType;
                });
                if (filteredProds.length === 0) return null;
                return (
                  <div key={group.id || 'ungrouped'}>
                    <div className="px-6 py-2 bg-gray-100 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                      <h3 className="text-sm font-bold text-gray-700 dark:text-gray-300">{group.name}</h3>
                      <span className="text-xs text-gray-500">{filteredProds.length} product{filteredProds.length !== 1 ? 's' : ''}</span>
                    </div>
                    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                      <thead className="bg-gray-50 dark:bg-gray-800">
                        <tr>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-20">Order</th>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Product</th>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-24">Type</th>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-28">Panel</th>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-24">Pricing</th>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-20">Group</th>
                          <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-20">Status</th>
                          <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase w-32">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                        {filteredProds.map((product, index) => (
                          <tr key={product.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                            <td className="px-4 py-3">
                              <div className="flex gap-0.5">
                                <button onClick={() => handleReorder(product, 'up')} disabled={index === 0} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-30"><ChevronUp className="w-4 h-4" /></button>
                                <button onClick={() => handleReorder(product, 'down')} disabled={index === filteredProds.length - 1} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-30"><ChevronDown className="w-4 h-4" /></button>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="text-sm font-medium text-gray-900 dark:text-white">{product.name}</div>
                              <div className="text-xs text-gray-500">{product.description?.substring(0, 50)}</div>
                            </td>
                            <td className="px-4 py-3">
                              <span className={`inline-flex px-2 py-0.5 text-xs font-semibold rounded-full ${product.is_bundle ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300' : product.account_type === 'reseller' ? 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300' : product.account_type === 'manual' ? 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300' : 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'}`}>
                                {product.is_bundle ? 'Bundle' : product.account_type === 'subscriber' ? 'Sub' : product.account_type === 'reseller' ? 'Reseller' : 'Manual'}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400">{getPanelName(product.panel_index, product.panel_type)}</td>
                            <td className="px-4 py-3 text-sm">{product.prices && Object.values(product.prices).map((p, i) => <div key={i}>${p}</div>)}</td>
                            <td className="px-4 py-3">
                              <select value={product.subgroup_id ? `${product.group_id}|${product.subgroup_id}` : product.group_id || ''}
                                onChange={(e) => {
                                  const val = e.target.value;
                                  if (val.includes('|')) {
                                    const [gid, sgid] = val.split('|');
                                    setProductGroupAndSub(product.id, gid, sgid);
                                  } else {
                                    setProductGroupAndSub(product.id, val, '');
                                  }
                                }}
                                className="text-xs px-1.5 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 w-full">
                                <option value="">None</option>
                                {groups.map(g => (
                                  <React.Fragment key={g.id}>
                                    {(g.subgroups || []).length === 0 && <option value={g.id}>{g.name}</option>}
                                    {(g.subgroups || []).map(sg => (
                                      <option key={sg.id} value={`${g.id}|${sg.id}`}>{g.name} &gt; {sg.name}</option>
                                    ))}
                                  </React.Fragment>
                                ))}
                              </select>
                            </td>
                            <td className="px-4 py-3">
                              <span className={`inline-flex px-2 py-0.5 text-xs rounded-full ${product.is_active !== false ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                {product.is_active !== false ? 'Active' : 'Inactive'}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right">
                              <div className="flex items-center justify-end gap-1">
                                <button onClick={() => { navigator.clipboard.writeText(`${window.location.origin}/order/${product.id}`); toast.success('Link copied to clipboard!'); }} className="text-xs text-blue-600 hover:underline">Link</button>
                                <button onClick={() => handleEdit(product)} className="text-xs text-gray-600 hover:text-blue-600">Edit</button>
                                <button onClick={() => handleDelete(product)} className="text-xs text-red-600 hover:text-red-800">Delete</button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })}
            </div>
            </div>
          </div>
        )}
      </main>

      {/* Product Form Modal */}
      {showModal && (
        <ProductFormModal
          product={editingProduct}
          onClose={handleCloseModal}
          onSuccess={() => {
            queryClient.invalidateQueries(['admin-products']);
            handleCloseModal();
          }}
        />
      )}
    </div>
  );
}

function ProductFormModal({ product, onClose, onSuccess }) {
  const isEditing = !!product;
  const [selectedPanelInfo, setSelectedPanelInfo] = useState({ 
    type: product?.panel_type || 'xtream', 
    index: product?.panel_index || 0 
  });
  const [selectedPackage, setSelectedPackage] = useState(null);
  const [packageType, setPackageType] = useState(product?.is_trial ? 'trial' : 'regular');
  
  // For editing: determine the existing price term
  const existingPriceTerm = product ? (Object.keys(product.prices || {})[0] || '1') : '1';
  const existingPrice = product ? (Object.values(product.prices || {})[0] || '') : '';
  
  const [formData, setFormData] = useState({
    name: product?.name || '',
    description: product?.description || '',
    account_type: product?.account_type || 'subscriber',
    bouquets: product?.bouquets || [],
    max_connections: product?.max_connections || 2,
    reseller_credits: product?.reseller_credits || 500,
    reseller_max_lines: product?.reseller_max_lines || 50,
    trial_days: product?.trial_days || 0,
    active: product?.active ?? true,
    price_1: product?.prices?.['1'] || '',
    price_3: product?.prices?.['3'] || '',
    price_6: product?.prices?.['6'] || '',
    price_12: product?.prices?.['12'] || '',
    // For editing: store the current price in a generic field
    edit_price: existingPrice,
    edit_term: existingPriceTerm,
    panel_index: product?.panel_index || 0,
    panel_type: product?.panel_type || 'xtream',
    is_trial: product?.is_trial || false,
    setup_instructions: product?.setup_instructions || '',
    show_channels: product?.show_channels !== false,
    duration: product?.duration || null,
    duration_unit: product?.duration_unit || 'months',
  });

  // Fetch settings to get panels list
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
  const aetherPanels = settings?.aether?.panels || [];
  
  // Combine all panel types with a type indicator
  const allPanels = [
    ...xtreamPanels.map((panel, index) => ({ ...panel, type: 'xtream', originalIndex: index, label: `${panel.name} (XtreamUI)` })),
    ...xuionePanels.map((panel, index) => ({ ...panel, type: 'xuione', originalIndex: index, label: `${panel.name} (XuiOne)` })),
    ...onestreamPanels.map((panel, index) => ({ ...panel, type: 'onestream', originalIndex: index, label: `${panel.name} (1-Stream)` })),
    ...nxtdashPanels.map((panel, index) => ({ ...panel, type: 'nxtdash', originalIndex: index, label: `${panel.name} (NXT Dash)` })),
    ...aetherPanels.map((panel, index) => ({ ...panel, type: 'aether', originalIndex: index, label: `${panel.name || 'Aether'} (Aether)` })),
    ...ghostsurfPanels.map((panel, index) => ({ ...panel, type: 'ghostsurf', originalIndex: index, label: `${panel.name || 'GhostSurf VPN'} (GhostSurf)` }))
  ];
  
  const panels = allPanels;

  // For new products, sync selectedPanelInfo to the first available panel
  React.useEffect(() => {
    if (!isEditing && panels.length > 0) {
      const first = panels[0];
      const currentKey = `${selectedPanelInfo.type}-${selectedPanelInfo.index}`;
      const firstKey = `${first.type}-${first.originalIndex}`;
      if (currentKey !== firstKey) {
        setSelectedPanelInfo({ type: first.type, index: first.originalIndex });
        setFormData(prev => ({ ...prev, panel_type: first.type, panel_index: first.originalIndex }));
      }
    }
  }, [panels.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch available bouquets for selected panel
  const { data: availableBouquets } = useQuery({
    queryKey: ['bouquets', selectedPanelInfo.type, selectedPanelInfo.index],
    queryFn: async () => {
      const response = await adminAPI.getBouquets(selectedPanelInfo.index, selectedPanelInfo.type);
      return response.data;
    },
    enabled: panels.length > 0,
  });

  // Fetch regular packages from selected panel (XtreamUI or XuiOne)
  const { data: packagesData, isLoading: packagesLoading } = useQuery({
    queryKey: [`${selectedPanelInfo.type}-packages`, selectedPanelInfo.index],
    queryFn: async () => {
      if (selectedPanelInfo.type === 'xuione') {
        const response = await adminAPI.syncXuiOnePackages(selectedPanelInfo.index);
        return response.data.packages || [];
      } else if (selectedPanelInfo.type === 'onestream') {
        const response = await adminAPI.syncOneStreamPackages(selectedPanelInfo.index);
        return response.data.packages || [];
      } else if (selectedPanelInfo.type === 'nxtdash') {
        const response = await adminAPI.getNxtDashPackages(selectedPanelInfo.index);
        return response.data.packages || [];
      } else if (selectedPanelInfo.type === 'ghostsurf') {
        const response = await api.get(`/api/admin/ghostsurf/plans/${selectedPanelInfo.index}`);
        return response.data.packages || [];
      } else if (selectedPanelInfo.type === 'aether') {
        const response = await adminAPI.getAetherPackages(selectedPanelInfo.index);
        return response.data.packages || [];
      } else {
        const response = await adminAPI.syncPackagesFromPanel(selectedPanelInfo.index);
        return response.data.packages || [];
      }
    },
    enabled: !isEditing && panels.length > 0 && packageType === 'regular',
  });

  // Fetch trial packages from selected panel (XtreamUI, XuiOne, 1-Stream, or NXT Dash)
  const { data: trialPackagesData, isLoading: trialPackagesLoading } = useQuery({
    queryKey: [`${selectedPanelInfo.type}-trial-packages`, selectedPanelInfo.index],
    queryFn: async () => {
      if (selectedPanelInfo.type === 'xuione') {
        const response = await adminAPI.syncXuiOnePackages(selectedPanelInfo.index);
        return response.data.trial_packages || [];
      } else if (selectedPanelInfo.type === 'onestream') {
        const response = await adminAPI.syncOneStreamPackages(selectedPanelInfo.index);
        return response.data.trial_packages || [];
      } else if (selectedPanelInfo.type === 'nxtdash') {
        const response = await adminAPI.getNxtDashPackages(selectedPanelInfo.index);
        return response.data.trial_packages || [];
      } else if (selectedPanelInfo.type === 'ghostsurf') {
        return []; // GhostSurf doesn't have trial packages
      } else if (selectedPanelInfo.type === 'aether') {
        const response = await adminAPI.getAetherPackages(selectedPanelInfo.index);
        return response.data.trial_packages || [];
      } else {
        const response = await adminAPI.syncTrialPackagesFromPanel(selectedPanelInfo.index);
        return response.data.packages || [];
      }
    },
    enabled: !isEditing && panels.length > 0 && packageType === 'trial',
  });

  // Get current packages based on type
  const currentPackages = packageType === 'trial' ? trialPackagesData : packagesData;
  const currentLoading = packageType === 'trial' ? trialPackagesLoading : packagesLoading;

  // Handle package selection
  const handlePackageSelect = (packageId) => {
    const pkg = currentPackages?.find(p => String(p.id) === String(packageId) || p.id === parseInt(packageId));
    
    if (pkg) {
      setSelectedPackage(pkg);
      
      // NXT Dash uses duration_in, others use duration_unit
      const durationUnit = pkg.duration_unit || pkg.duration_in || 'months';
      const maxConn = pkg.max_connections || pkg.connections || 1;
      
      // Convert duration to months
      const durationMonths = convertDurationToMonths(pkg.duration, durationUnit);
      
      // Extract bouquet IDs — XtreamUI has objects with .id, NXT Dash may not have bouquets
      const bouquets = pkg.bouquets || [];
      let packageBouquetIds = bouquets.map(b => {
        const id = parseInt(typeof b === 'object' ? b.id : b);
        return id;
      }).filter(id => !isNaN(id));
      
      // For NXT Dash: packages don't carry bouquets — auto-select ALL available bouquets
      if (selectedPanelInfo.type === 'nxtdash' && packageBouquetIds.length === 0 && availableBouquets?.length > 0) {
        packageBouquetIds = availableBouquets.map(b => parseInt(b.id)).filter(id => !isNaN(id));
      }

      // For Aether: fetch the package's own bouquet list and pre-select the default-included ones
      if (selectedPanelInfo.type === 'aether') {
        adminAPI.getAetherPackageBouquets(pkg.id, selectedPanelInfo.index).then((resp) => {
          const defaults = (resp.data?.bouquets || []).filter(b => b.default_included !== false).map(b => parseInt(b.id)).filter(id => !isNaN(id));
          if (defaults.length > 0) setFormData(prev => ({ ...prev, bouquets: defaults }));
        }).catch(() => {});
      }
      
      console.log('Package bouquet IDs:', packageBouquetIds);
      
      // Auto-fill form from package
      setFormData(prev => ({
        ...prev,
        name: pkg.name,
        description: `${pkg.name} - ${maxConn} connection(s), ${pkg.duration} ${durationUnit}`,
        max_connections: parseInt(maxConn),
        bouquets: packageBouquetIds,
        is_trial: pkg.is_trial || packageType === 'trial',
        trial_duration: pkg.duration,
        trial_duration_unit: durationUnit,
        [`price_${durationMonths}`]: pkg.is_trial || packageType === 'trial' ? '0' : '',
      }));
    }
  };

  const convertDurationToMonths = (duration, unit) => {
    switch (unit) {
      case 'hours': return Math.max(1, Math.ceil(duration / 720));
      case 'days': return Math.max(1, Math.ceil(duration / 30));
      case 'months': return duration;
      case 'years': return duration * 12;
      default: return duration || 1;
    }
  };

  const saveMutation = useMutation({
    mutationFn: async (data) => {
      // For editing: use the existing term and edited price
      // For new: parse from the selected package
      let prices = {};
      let actualDuration = null;
      let actualDurationUnit = 'months';
      
      if (isEditing) {
        // Use the existing term key and the edited price value
        const term = data.edit_term || existingPriceTerm || '1';
        const price = parseFloat(data.edit_price) || 0;
        prices[String(term)] = price;
        actualDuration = data.duration || product?.duration || parseInt(term);
        actualDurationUnit = data.duration_unit || product?.duration_unit || 'months';
      } else {
        const pkg = selectedPackage;
        if (pkg) {
          let rawDur = pkg.duration;
          let rawUnit = pkg.duration_unit || pkg.duration_in || 'months';
          if (typeof rawDur === 'string') {
            const parts = rawDur.trim().split(/\s+/);
            rawDur = parseInt(parts[0]) || 1;
            if (parts.length > 1) rawUnit = parts[1];
          }
          actualDuration = parseInt(rawDur) || 1;
          actualDurationUnit = rawUnit;
        }
        const durationMonths = selectedPackage ? convertDurationToMonths(actualDuration || 1, actualDurationUnit) : 1;
        const priceValue = data[`price_${durationMonths}`] || data.price_1 || data.price_3 || data.price_6 || data.price_12 || '0';
        prices[String(durationMonths)] = parseFloat(priceValue);
      }

      const productData = {
        name: data.name,
        description: data.description,
        account_type: data.account_type,
        bouquets: data.bouquets,
        max_connections: parseInt(data.max_connections),
        reseller_credits: parseFloat(data.reseller_credits),
        reseller_max_lines: parseInt(data.reseller_max_lines),
        trial_days: parseInt(data.trial_days),
        prices: prices,
        active: data.active,
        xtream_package_id: selectedPackage ? selectedPackage.id : (product?.xtream_package_id || null),
        ghostsurf_plan_id: (selectedPanelInfo.type === 'ghostsurf' && selectedPackage) ? (selectedPackage.plan_id || selectedPackage.id) : (product?.ghostsurf_plan_id || null),
        panel_index: isEditing ? (product?.panel_index ?? selectedPanelInfo.index) : selectedPanelInfo.index,
        panel_type: isEditing ? (product?.panel_type ?? selectedPanelInfo.type) : selectedPanelInfo.type,
        is_trial: data.is_trial || false,
        trial_duration: data.trial_duration || 0,
        trial_duration_unit: data.trial_duration_unit || 'days',
        setup_instructions: data.setup_instructions || '',
        duration: actualDuration || (product?.duration ? parseInt(product.duration) : null),
        duration_unit: actualDurationUnit || product?.duration_unit || 'months',
        show_channels: data.show_channels,
      };

      if (isEditing) {
        return adminAPI.updateProduct(product.id, productData);
      } else {
        return adminAPI.createProduct(productData);
      }
    },
    onSuccess: () => {
      toast.success(isEditing ? 'Product updated successfully!' : 'Product created successfully!');
      onSuccess();
    },
    onError: (error) => {
      toast.error('Failed to save product: ' + (error.response?.data?.detail || error.message));
    },
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    saveMutation.mutate(formData);
  };

  const handleBouquetToggle = (bouquetId) => {
    const id = parseInt(bouquetId);
    setFormData(prev => {
      const current = prev.bouquets.map(b => parseInt(b));
      const newBouquets = current.includes(id)
        ? current.filter(b => b !== id)
        : [...current, id];
      return { ...prev, bouquets: newBouquets };
    });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isEditing ? 'Edit Product' : 'Add New Product'}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 dark:bg-gray-900">
          <div className="grid md:grid-cols-2 gap-6">
            {/* Panel Selection - Show for new products or when editing if multiple panels */}
            {panels.length > 1 && (
              <div className="md:col-span-2">
                <div className={`border rounded-lg p-4 mb-4 ${isEditing ? 'bg-gray-50 dark:bg-gray-800 border-gray-300 dark:border-gray-600' : 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-600'}`}>
                  <label className={`block text-sm font-semibold mb-3 ${isEditing ? 'text-gray-700 dark:text-gray-300' : 'text-blue-900 dark:text-blue-200'}`}>
                    {isEditing ? 'Product Panel' : 'Select Panel *'}
                  </label>
                  <select
                    value={`${selectedPanelInfo.type}-${selectedPanelInfo.index}`}
                    onChange={(e) => {
                      const [type, index] = e.target.value.split('-');
                      const panelIndex = parseInt(index);
                      setSelectedPanelInfo({ type, index: panelIndex });
                      setFormData(prev => ({ 
                        ...prev, 
                        panel_index: panelIndex,
                        panel_type: type
                      }));
                      setSelectedPackage(null); // Reset package when panel changes
                    }}
                    disabled={isEditing}
                    className={`w-full px-4 py-3 border-2 rounded-lg focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-base font-medium ${
                      isEditing ? 'border-gray-300 opacity-75 cursor-not-allowed' : 'border-blue-400'
                    }`}
                  >
                    {panels.map((panel, idx) => (
                      <option key={idx} value={`${panel.type}-${panel.originalIndex}`}>
                        {panel.label} - {panel.panel_url}
                      </option>
                    ))}
                  </select>
                  <p className={`text-xs mt-2 ${isEditing ? 'text-gray-600' : 'text-blue-700 dark:text-blue-300'}`}>
                    {isEditing ? 'Panel cannot be changed after product creation' : 'Choose which panel to load packages from'}
                  </p>
                </div>
              </div>
            )}

            {/* Package Selection - REQUIRED for new products */}
            {!isEditing && (
              <div className="md:col-span-2">
                <div className="bg-gradient-to-r from-green-50 to-blue-50 dark:from-green-900/20 dark:to-blue-900/20 border-2 border-green-400 dark:border-green-600 rounded-lg p-6 mb-6">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                    <Package className="w-5 h-5 text-green-600" />
                    Select Package * {panels.length > 1 && `(from ${panels.find(p => p.type === selectedPanelInfo.type && p.originalIndex === selectedPanelInfo.index)?.label || 'selected panel'})`}
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                    <strong>Required:</strong> Choose a package to set pricing, duration, connections, and bouquets.
                  </p>
                  
                  {/* Package Type Toggle */}
                  <div className="mb-6 flex gap-2 bg-white dark:bg-gray-800 p-1 rounded-lg border-2 border-green-400 dark:border-green-600 dark:border-green-600 w-fit">
                    <button
                      type="button"
                      onClick={() => {
                        setPackageType('regular');
                        setSelectedPackage(null);
                      }}
                      className={`px-4 py-2 rounded-md text-sm font-semibold transition ${
                        packageType === 'regular' 
                          ? 'bg-green-600 text-white' 
                          : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                    >
                      Regular Packages
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setPackageType('trial');
                        setSelectedPackage(null);
                      }}
                      className={`px-4 py-2 rounded-md text-sm font-semibold transition ${
                        packageType === 'trial' 
                          ? 'bg-purple-600 text-white' 
                          : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                    >
                      Trial Packages
                    </button>
                  </div>
                  
                  {currentLoading ? (
                    <div className="text-center py-6">
                      <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-green-600 mx-auto"></div>
                      <p className="text-sm text-gray-600 mt-3">
                        Loading {packageType} packages from panel...
                      </p>
                    </div>
                  ) : currentPackages && currentPackages.length > 0 ? (
                    <select
                      required
                      value={selectedPackage?.id || ''}
                      onChange={(e) => handlePackageSelect(e.target.value)}
                      className="w-full px-4 py-3 border-2 border-green-400 dark:border-green-600 rounded-lg focus:ring-2 focus:ring-green-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-base font-medium"
                    >
                      <option value="">-- Select a {packageType} package --</option>
                      {currentPackages.map((pkg) => (
                        <option key={pkg.id} value={pkg.id}>
                          {pkg.name} | ${pkg.credits} | {pkg.duration} {pkg.duration_unit} | {pkg.max_connections} connection(s)
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg p-4">
                      <p className="text-sm text-red-800 dark:text-red-300 font-semibold mb-2">⚠ No {packageType} packages found!</p>
                      <p className="text-sm text-red-700 dark:text-red-400">
                        No {packageType} packages available from this panel. {packageType === 'trial' ? 'Try selecting "Regular Packages" instead.' : 'Please sync packages from the panel.'}
                      </p>
                    </div>
                  )}
                  
                  {selectedPackage && (
                    <div className="mt-4 p-4 bg-white dark:bg-gray-800 rounded-lg border-2 border-green-400 dark:border-green-600 dark:border-green-600 shadow-sm">
                      <p className="text-sm font-semibold text-green-900 dark:text-green-200 mb-3">
                        ✓ Selected Package: {selectedPackage.name}
                      </p>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                        <div className="bg-green-50 dark:bg-green-900/20 p-3 rounded">
                          <span className="text-gray-600 dark:text-gray-400 block mb-1">Price:</span>
                          <span className="font-bold text-green-700 dark:text-green-300 text-lg">${selectedPackage.credits}</span>
                        </div>
                        <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded">
                          <span className="text-gray-600 dark:text-gray-400 block mb-1">Duration:</span>
                          <span className="font-bold text-blue-700 dark:text-blue-300 text-lg">{selectedPackage.duration} {selectedPackage.duration_unit}</span>
                        </div>
                        <div className="bg-purple-50 dark:bg-purple-900/20 p-3 rounded">
                          <span className="text-gray-600 dark:text-gray-400 block mb-1">Connections:</span>
                          <span className="font-bold text-purple-700 text-lg">{selectedPackage.max_connections}</span>
                        </div>
                        <div className="bg-orange-50 dark:bg-orange-900/20 p-3 rounded">
                          <span className="text-gray-600 dark:text-gray-400 block mb-1">Bouquets:</span>
                          <span className="font-bold text-orange-700 text-lg">{selectedPackage.bouquets?.length || 0}</span>
                        </div>
                      </div>
                    </div>
                  )}
                  
                  {!selectedPackage && packagesData && packagesData.length > 0 && (
                    <div className="mt-4 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 dark:border-yellow-600 rounded-lg p-3">
                      <p className="text-sm text-yellow-800 dark:text-yellow-200">
                        ⚠ Please select a package to continue
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
            
            {/* Show fields only if package selected OR editing existing */}
            {(selectedPackage || isEditing) ? (
            <>
            {/* Basic Information */}
            <div className="md:col-span-2">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Basic Information</h3>
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Product Name *
              </label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                placeholder="IPTV Subscriber - 1 Month"
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Description *
              </label>
              <textarea
                required
                rows={3}
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                placeholder="Monthly IPTV subscription with full channel access"
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Setup Instructions (Optional)
              </label>
              <textarea
                rows={4}
                value={formData.setup_instructions}
                onChange={(e) => setFormData({ ...formData, setup_instructions: e.target.value })}
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                placeholder="1. Download Panel 1 App from Downloads section&#10;2. Enter credentials shown above&#10;3. Enjoy streaming!"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Custom instructions shown to customers. Leave blank for default instructions.
              </p>
            </div>

            {/* View Channels Toggle - hide for VPN panels */}
            {selectedPanelInfo.type !== 'ghostsurf' && (
            <div className="md:col-span-2 flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
              <div>
                <span className="text-sm font-medium text-gray-900 dark:text-white">Show "View Channels" on Storefront</span>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Allow customers to preview channel packages (bouquets) before purchase</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" checked={formData.show_channels}
                  onChange={(e) => setFormData({ ...formData, show_channels: e.target.checked })}
                  className="sr-only peer" data-testid="show-channels-toggle" />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>
            )}

            {/* Account type fixed to subscriber for regular products */}
            <input type="hidden" name="account_type" value="subscriber" />

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Active
              </label>
              <select
                value={formData.active}
                onChange={(e) => setFormData({ ...formData, active: e.target.value === 'true' })}
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              >
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </div>

            {/* Subscriber Settings - hide bouquets for VPN panels */}
            <>
              <div className="md:col-span-2">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 mt-4">
                    {selectedPanelInfo.type === 'ghostsurf' ? 'VPN Settings' : 'Subscriber Settings'}
                  </h3>
                </div>

                {selectedPanelInfo.type !== 'ghostsurf' && (
                <div className="md:col-span-2">
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                      Bouquets (Channel Packages)
                    </label>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => {
                        if (availableBouquets) {
                          setFormData(prev => ({ ...prev, bouquets: availableBouquets.map(b => parseInt(b.id)).filter(id => !isNaN(id)) }));
                        }
                      }} className="text-xs text-blue-600 hover:underline">Select All</button>
                      <button type="button" onClick={() => setFormData(prev => ({ ...prev, bouquets: [] }))}
                        className="text-xs text-red-600 hover:underline">Deselect All</button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                    Uncheck bouquets you don't want included when provisioning.
                  </p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2 p-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 max-h-64 overflow-y-auto">
                    {availableBouquets?.map((bouquet) => {
                      const checked = formData.bouquets.map(b => parseInt(b)).includes(parseInt(bouquet.id));
                      return (
                        <label key={bouquet.id}
                          className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition text-sm ${checked ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-600' : 'bg-white dark:bg-gray-700 border-gray-200 dark:border-gray-600 opacity-60'}`}>
                          <input type="checkbox" checked={checked}
                            onChange={() => handleBouquetToggle(bouquet.id)}
                            className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500" />
                          <span className="font-medium text-gray-900 dark:text-white truncate">{bouquet.name}</span>
                        </label>
                      );
                    })}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    {formData.bouquets.length} of {availableBouquets?.length || 0} bouquets selected
                  </p>
                </div>
                )}

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    {selectedPanelInfo.type === 'ghostsurf' ? 'Max Devices' : 'Max Connections'}
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={formData.max_connections}
                    onChange={(e) => setFormData({ ...formData, max_connections: e.target.value })}
                    disabled={selectedPackage !== null && !isEditing}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 dark:disabled:bg-gray-800 disabled:cursor-not-allowed"
                  />
                  {selectedPackage && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                      ✓ Set by package: {formData.max_connections} connection(s)
                    </p>
                  )}
                </div>
              </>

            {/* Pricing */}
            <div className="md:col-span-2">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 mt-4">Pricing</h3>
              {isEditing && product?.duration && (
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                  Duration: <strong>{product.duration} {product.duration_unit || 'months'}</strong>
                </p>
              )}
              {!isEditing && selectedPackage && (
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                  Package duration: <strong>{selectedPackage.duration} {selectedPackage.duration_unit}</strong>
                </p>
              )}
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Price {isEditing ? `(${existingPriceTerm} month${existingPriceTerm !== '1' ? 's' : ''} term)` : selectedPackage ? `(${selectedPackage.duration} ${selectedPackage.duration_unit})` : ''}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-3 text-gray-500 dark:text-gray-400">$</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  required
                  value={isEditing ? formData.edit_price :
                    selectedPackage ? 
                    (formData[`price_${convertDurationToMonths(selectedPackage.duration, selectedPackage.duration_unit)}`] || selectedPackage.credits) :
                    (formData.price_1 || formData.price_3 || formData.price_6 || formData.price_12 || '')
                  }
                  onChange={(e) => {
                    if (isEditing) {
                      setFormData({ ...formData, edit_price: e.target.value });
                    } else if (selectedPackage) {
                      const months = convertDurationToMonths(selectedPackage.duration, selectedPackage.duration_unit);
                      setFormData({ ...formData, [`price_${months}`]: e.target.value });
                    } else {
                      setFormData({ ...formData, price_1: e.target.value });
                    }
                  }}
                  className="w-full pl-8 pr-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                  placeholder="15.00"
                />
              </div>
              {isEditing && (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Duration</label>
                    <input type="number" min="1" value={formData.duration || ''} onChange={(e) => setFormData({...formData, duration: parseInt(e.target.value) || null})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" placeholder="12" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Duration Unit</label>
                    <select value={formData.duration_unit} onChange={(e) => setFormData({...formData, duration_unit: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm">
                      <option value="months">Months</option>
                      <option value="days">Days</option>
                      <option value="hours">Hours</option>
                      <option value="years">Years</option>
                    </select>
                  </div>
                </div>
              )}
              {!isEditing && selectedPackage && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Package cost: ${selectedPackage.credits} | Set your selling price above
                </p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Trial Days
              </label>
              <input
                type="number"
                min="0"
                value={formData.trial_days}
                onChange={(e) => setFormData({ ...formData, trial_days: e.target.value })}
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
                placeholder="0"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Free trial period in days (0 = no trial)</p>
            </div>

          {/* Form Actions */}
          <div className="md:col-span-2 flex gap-4 mt-8 pt-6 border-t">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saveMutation.isPending || (!isEditing && !selectedPackage)}
              className="flex-1 flex items-center justify-center gap-2 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-5 h-5" />
              {saveMutation.isPending ? 'Saving...' : (isEditing ? 'Update Product' : selectedPackage ? 'Create Product' : 'Select Package First')}
            </button>
          </div>
          </>
          ) : null}
          </div>
        </form>
      </div>
    </div>
  );
}


// Reseller Package Modal Component
function ResellerPackageModal({ onClose, onSuccess, panels, xtreamPanels, xuionePanels, editingProduct }) {
  const [formData, setFormData] = useState({
    name: editingProduct?.name || '',
    description: editingProduct?.description || '',
    reseller_credits: editingProduct?.reseller_credits || 500,
    price: editingProduct?.prices ? Object.values(editingProduct.prices)[0] || '' : '',
    panel_index: editingProduct?.panel_index || 0,
    panel_type: editingProduct?.panel_type || 'xtream',
    custom_panel_url: editingProduct?.custom_panel_url || ''
  });
  
  const isEditing = !!editingProduct;

  const saveMutation = useMutation({
    mutationFn: async (data) => {
      const prices = {
        '1': parseFloat(data.price)  // Store as 1-month for compatibility, but it's lifetime
      };
      
      const productData = {
        name: data.name,
        description: data.description,
        account_type: 'reseller',
        bouquets: [],
        max_connections: 0,
        reseller_credits: parseFloat(data.reseller_credits),
        reseller_max_lines: 0,
        trial_days: 0,
        prices: prices,
        active: true,
        panel_index: data.panel_index,
        panel_type: data.panel_type,
        custom_panel_url: data.custom_panel_url || '',
        setup_instructions: '',
        is_trial: false
      };
      
      // Update if editing, create if new
      if (isEditing) {
        return adminAPI.updateProduct(editingProduct.id, productData);
      } else {
        return adminAPI.createProduct(productData);
      }
    },
    onSuccess: () => {
      toast.success(isEditing ? 'Reseller package updated successfully!' : 'Reseller package created successfully!');
      onSuccess();
    },
    onError: (error) => {
      toast.error('Error: ' + (error.response?.data?.detail || error.message));
    },
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    saveMutation.mutate(formData);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center sticky top-0 bg-white dark:bg-gray-800">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{isEditing ? 'Edit Reseller Package' : 'Add Reseller Package'}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div className="col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Package Name *
              </label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({...formData, name: e.target.value})}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                placeholder="Reseller Panel - 500 Credits"
              />
            </div>

            <div className="col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Description *
              </label>
              <textarea
                required
                rows={3}
                value={formData.description}
                onChange={(e) => setFormData({...formData, description: e.target.value})}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                placeholder="Reseller panel with 500 credits"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Reseller Credits *
              </label>
              <input
                type="number"
                required
                min="0"
                step="0.01"
                value={formData.reseller_credits}
                onChange={(e) => setFormData({...formData, reseller_credits: e.target.value})}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Credits allocated to reseller</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Panel *
              </label>
              <select
                value={`${formData.panel_type}-${formData.panel_index}`}
                onChange={(e) => {
                  const [type, index] = e.target.value.split('-');
                  setFormData({...formData, panel_type: type, panel_index: parseInt(index)});
                }}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              >
                {panels.map((panel, idx) => (
                  <option key={idx} value={`${panel.type}-${panel.originalIndex}`}>
                    {panel.label || panel.name}
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Selected panel: {panels[formData.panel_index]?.panel_url || 'Not set'}
              </p>
            </div>

            <div className="col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Panel URL for Customers *
              </label>
              <input
                type="url"
                required
                value={formData.custom_panel_url || ''}
                onChange={(e) => setFormData({...formData, custom_panel_url: e.target.value})}
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                placeholder="https://panel.example.com"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                The panel URL that customers will use to access their reseller panel.
              </p>
            </div>

            {/* Pricing - One-time payment */}
            <div className="col-span-2 border-t pt-4 mt-2">
              <h4 className="font-semibold text-gray-900 dark:text-white mb-3">Pricing (One-Time Payment) *</h4>
              <div>
                <label className="block text-sm text-gray-700 dark:text-gray-300 mb-2">Price ($) *</label>
                <input
                  type="number"
                  required
                  step="0.01"
                  min="0"
                  value={formData.price}
                  onChange={(e) => setFormData({...formData, price: e.target.value})}
                  className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg"
                  placeholder="500.00"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                  ℹ️ Lifetime access - One-time payment, no recurring charges
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="col-span-2 flex gap-4 pt-4">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saveMutation.isPending}
                className="flex-1 px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 flex items-center justify-center gap-2"
              >
                <Save className="w-5 h-5" />
                {saveMutation.isPending ? (isEditing ? 'Updating...' : 'Creating...') : (isEditing ? 'Update Package' : 'Create Package')}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}


// CMTV local change 2026-09-24: the modal could only create (Edit opened a blank form); it now edits too, and a
// manual product can be linked to Cockpit so paid orders create/renew the customer's account automatically.
const COCKPIT_MODULES = [
  { value: '', label: 'No, I fulfil orders by hand' },
  { value: 'nuvio', label: 'Yes: Stremio (Cockpit Nuvio)' },
  { value: 'vpn', label: 'Yes: CMTVpn (Cockpit IPVanish)' },
  { value: 'audiobooks', label: 'Yes: Audiobooks (abadmin on the Asus server)' }, // CMTV local change 2026-09-25
  { value: 'nuviocloud', label: "Yes: Nuvio (CMTV's own Nuvio server)" }, // CMTV local change 2026-09-29
];

function ManualProductModal({ onClose, onSuccess, editingProduct }) {
  const isEditing = !!editingProduct;
  const [formData, setFormData] = useState({
    name: editingProduct?.name || '',
    description: editingProduct?.description || '',
    price: editingProduct?.prices ? String(Object.values(editingProduct.prices)[0] ?? '') : '',
    setup_instructions: editingProduct?.setup_instructions || '',
    cockpit_module: editingProduct?.cockpit_module || '',
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name || !formData.price) {
      toast.error('Name and price are required');
      return;
    }
    setSaving(true);
    try {
      const fields = {
        name: formData.name,
        description: formData.description,
        setup_instructions: formData.setup_instructions,
        cockpit_module: formData.cockpit_module || null,
      };
      if (isEditing) {
        // Saving replaces the whole product, so send its current values back and change only the edited fields
        const { id, _id, created_at, ...current } = editingProduct;
        const priceKey = Object.keys(editingProduct.prices || {})[0] || '1';
        await adminAPI.updateProduct(editingProduct.id, {
          ...current, ...fields, prices: { [priceKey]: parseFloat(formData.price) },
        });
      } else {
        await adminAPI.createProduct({
          ...fields,
          account_type: 'manual',
          panel_type: 'manual',
          panel_index: 0,
          prices: { '1': parseFloat(formData.price) },
          max_connections: 0,
          bouquets: [],
          xtream_package_id: null,
          is_trial: false,
        });
      }
      onSuccess();
    } catch (err) {
      toast.error('Failed to create: ' + (err.response?.data?.detail?.[0]?.msg || err.response?.data?.detail || err.message));
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-lg w-full">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">{isEditing ? 'Edit Manual Product' : 'Add Manual Product'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X className="w-6 h-6" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-sm text-gray-600 dark:text-gray-400">
            {formData.cockpit_module
              ? `When an order is paid, the customer's account is created (or renewed) in ${formData.cockpit_module === 'audiobooks' ? 'Audiobookshelf and the requests app (through abadmin)' : formData.cockpit_module === 'nuviocloud' ? "CMTV's own Nuvio server" : 'Cockpit'} automatically and they are emailed their login and the setup instructions below.`
              : 'Manual products are not linked to any IPTV panel. Orders require manual fulfillment by the admin.'}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Create accounts automatically in Cockpit?</label>
            <select value={formData.cockpit_module}
              onChange={(e) => setFormData({ ...formData, cockpit_module: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
              {COCKPIT_MODULES.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Product Name *</label>
            <input type="text" required value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., VPN Subscription, Setup Service"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <textarea rows={2} value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Brief description of the product"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Price *</label>
            <div className="relative">
              <span className="absolute left-3 top-2.5 text-gray-500 dark:text-gray-400">$</span>
              <input type="number" required min="0" step="0.01" value={formData.price}
                onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                placeholder="0.00"
                className="w-full pl-7 pr-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Setup Instructions (shown to customer after purchase)</label>
            <textarea rows={3} value={formData.setup_instructions}
              onChange={(e) => setFormData({ ...formData, setup_instructions: e.target.value })}
              placeholder="Instructions the customer will see after their order is fulfilled"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white" />
          </div>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 px-4 py-2.5 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="flex-1 px-4 py-2.5 bg-gray-700 text-white rounded-lg hover:bg-gray-800 font-semibold disabled:opacity-50">
              {saving ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Product'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


function BundleProductModal({ onClose, onSuccess, products, editingProduct, getPanelName }) {
  const [saving, setSaving] = React.useState(false);
  const [name, setName] = React.useState(editingProduct?.name || '');
  const [description, setDescription] = React.useState(editingProduct?.description || '');
  const [selectedIds, setSelectedIds] = React.useState(editingProduct?.bundle_product_ids || []);
  const [prices, setPrices] = React.useState(() => {
    if (editingProduct?.prices) {
      const firstVal = Object.values(editingProduct.prices)[0];
      return firstVal ?? '';
    }
    return '';
  });
  const [groupId, setGroupId] = React.useState(editingProduct?.group_id || '');
  const [subgroupId, setSubgroupId] = React.useState(editingProduct?.subgroup_id || '');
  const [search, setSearch] = React.useState('');

  // Available products (exclude other bundles and this bundle itself)
  const available = (products || []).filter(p =>
    !p.is_bundle && p.id !== editingProduct?.id &&
    (p.name.toLowerCase().includes(search.toLowerCase()) || (getPanelName(p.panel_index, p.panel_type) || '').toLowerCase().includes(search.toLowerCase()))
  );

  const toggleProduct = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const selectedProducts = selectedIds.map(id => products.find(p => p.id === id)).filter(Boolean);

  // Calculate sum of individual prices for comparison
  const individualTotal = selectedProducts.reduce((sum, p) => {
    const firstPrice = p.prices ? Object.values(p.prices)[0] : 0;
    return sum + (parseFloat(firstPrice) || 0);
  }, 0);

  const handleSave = async () => {
    if (!name || selectedIds.length < 2) {
      toast.error('Bundle needs a name and at least 2 products');
      return;
    }
    if (!prices || parseFloat(prices) <= 0) {
      toast.error('Set a bundle price');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name,
        description,
        account_type: 'subscriber',
        is_bundle: true,
        bundle_product_ids: selectedIds,
        prices: { 1: parseFloat(prices) },
        bouquets: [1],
        max_connections: 1,
        active: true,
        panel_type: 'manual',
        panel_index: 0,
        group_id: groupId,
        subgroup_id: subgroupId,
      };
      if (editingProduct) {
        await adminAPI.updateProduct(editingProduct.id, payload);
      } else {
        await adminAPI.createProduct(payload);
      }
      toast.success(editingProduct ? 'Bundle updated!' : 'Bundle created!');
      onSuccess();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to save bundle');
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b dark:border-gray-700">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white">
            {editingProduct ? 'Edit Bundle' : 'Create Bundle Product'}
          </h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-4 space-y-4">
          {/* Name & Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Bundle Name</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white text-sm"
              placeholder="e.g. Ultimate IPTV Bundle" data-testid="bundle-name-input" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <input type="text" value={description} onChange={e => setDescription(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white text-sm"
              placeholder="e.g. Get Panel 1 + Panel 2 at a discounted price" data-testid="bundle-desc-input" />
          </div>

          {/* Select Products */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Select Products to Bundle ({selectedIds.length} selected)
            </label>
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white text-sm mb-2"
              placeholder="Search products..." data-testid="bundle-search-products" />
            <div className="border dark:border-gray-600 rounded-lg max-h-48 overflow-y-auto">
              {available.length === 0 ? (
                <p className="text-sm text-gray-400 p-3 text-center">No products found</p>
              ) : available.map(p => (
                <label key={p.id} className={`flex items-center gap-3 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer border-b dark:border-gray-700 last:border-0 ${selectedIds.includes(p.id) ? 'bg-emerald-50 dark:bg-emerald-900/20' : ''}`}>
                  <input type="checkbox" checked={selectedIds.includes(p.id)} onChange={() => toggleProduct(p.id)}
                    className="rounded text-emerald-600" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{p.name}</p>
                    <p className="text-xs text-gray-500">{getPanelName(p.panel_index, p.panel_type)} — {p.prices ? `$${Object.values(p.prices)[0]}` : 'No price'}</p>
                  </div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${p.account_type === 'reseller' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                    {p.account_type === 'subscriber' ? 'Sub' : p.account_type}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Selected summary */}
          {selectedProducts.length > 0 && (
            <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-700 rounded-lg p-3">
              <p className="text-xs font-semibold text-emerald-800 dark:text-emerald-300 mb-2">Bundle includes:</p>
              <div className="space-y-1">
                {selectedProducts.map(p => (
                  <div key={p.id} className="flex justify-between text-xs">
                    <span className="text-gray-700 dark:text-gray-300">{p.name}</span>
                    <span className="text-gray-500">${Object.values(p.prices || {})[0] || '—'}</span>
                  </div>
                ))}
                <div className="border-t dark:border-emerald-700 pt-1 mt-1 flex justify-between text-xs font-semibold">
                  <span className="text-gray-700 dark:text-gray-300">Individual total</span>
                  <span className="text-gray-700 dark:text-gray-300">${individualTotal.toFixed(2)}</span>
                </div>
              </div>
            </div>
          )}

          {/* Bundle Price */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Bundle Price</label>
            <div className="relative w-48">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
              <input type="number" step="0.01" min="0" value={prices}
                onChange={e => setPrices(e.target.value)}
                className="w-full pl-7 pr-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white text-sm"
                placeholder="0.00" data-testid="bundle-price-input" />
            </div>
            {prices && individualTotal > 0 && parseFloat(prices) < individualTotal && (
              <p className="text-xs text-emerald-600 mt-1">
                Savings: ${(individualTotal - parseFloat(prices)).toFixed(2)} ({((1 - parseFloat(prices) / individualTotal) * 100).toFixed(0)}% off)
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button onClick={onClose} className="flex-1 px-4 py-2 border rounded-lg text-gray-700 dark:text-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 text-sm">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving || selectedIds.length < 2}
              className="flex-1 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 text-sm font-medium disabled:opacity-50"
              data-testid="bundle-save-btn">
              {saving ? 'Saving...' : editingProduct ? 'Update Bundle' : 'Create Bundle'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

