import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { productsAPI, panelsAPI } from '../api/api';
import { useAuthStore, useCartStore } from '../store/store';
import { useBrandingStore } from '../store/branding';
import { useCurrencyStore } from '../store/currency';
import { ShoppingCart, LogIn, UserPlus, Server, Users, Info, X, Filter, Grid, Package } from 'lucide-react';
import { getPanelGradient, getPanelColor } from '../utils/panelColors';
import CurrencySwitcher from '../components/CurrencySwitcher';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

export default function HomePage() {
  const { user } = useAuthStore();
  const { items } = useCartStore();
  const { branding, fetchBranding } = useBrandingStore();
  const { symbol: currencySymbol, convertPrice } = useCurrencyStore();
  
  const [selectedPanel, setSelectedPanel] = useState('all');
  const [priceFilter, setPriceFilter] = useState('all');
  const [accountTypeFilter, setAccountTypeFilter] = useState('all');
  const [connectionFilter, setConnectionFilter] = useState('all');
  
  // Fetch branding when component mounts
  React.useEffect(() => {
    fetchBranding();
  }, []);
  
  const { data: products, isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: async () => {
      const response = await productsAPI.getAll();
      return response.data;
    },
  });

  // Fetch panel names (public endpoint)
  const { data: panelData } = useQuery({
    queryKey: ['panel-names'],
    queryFn: async () => {
      const response = await panelsAPI.getNames();
      return response.data;
    },
  });

  // Group products by panel type and index
  const productsByPanel = useMemo(() => {
    if (!products) return {};
    
    const grouped = {};
    products.forEach(product => {
      const panelType = product.panel_type || 'xtream';
      const panelIndex = product.panel_index ?? 0;
      const panelKey = `${panelType}-${panelIndex}`;
      
      if (!grouped[panelKey]) {
        grouped[panelKey] = {
          products: [],
          panelType: panelType,
          panelIndex: panelIndex
        };
      }
      grouped[panelKey].products.push(product);
    });
    
    return grouped;
  }, [products]);

  // Get panel name with type
  const getPanelName = (panelIndex, panelType = 'xtream') => {
    const panels = panelData?.panels || [];
    const xuionePanels = panelData?.xuione_panels || [];
    const onestreamPanels = panelData?.onestream_panels || [];
    const nxtdashPanels = panelData?.nxtdash_panels || [];
    
    let panel;
    if (panelType === 'manual') {
      return 'Other Products';
    } else if (panelType === 'xuione') {
      panel = xuionePanels.find(p => p.index === Number(panelIndex));
      return panel?.name || `Panel ${Number(panelIndex) + 1}`;
    } else if (panelType === 'onestream') {
      panel = onestreamPanels.find(p => p.index === Number(panelIndex));
      return panel?.name || `1-Stream ${Number(panelIndex) + 1}`;
    } else if (panelType === 'nxtdash') {
      panel = nxtdashPanels.find(p => p.index === Number(panelIndex));
      return panel?.name || `NXT Dash ${Number(panelIndex) + 1}`;
    } else if (panelType === 'aether') {
      panel = (panelData?.aether_panels || []).find(p => p.index === Number(panelIndex));
      return panel?.name || `Aether ${Number(panelIndex) + 1}`;
    } else {
      panel = panels.find(p => p.index === Number(panelIndex));
      return panel?.name || `Server ${Number(panelIndex) + 1}`;
    }
  };

  // Get all unique panel options for filter
  const panelOptions = useMemo(() => {
    const options = [{ key: 'all', name: 'All Panels' }];
    
    Object.entries(productsByPanel).forEach(([panelKey, panelGroup]) => {
      const { panelType, panelIndex } = panelGroup;
      const panelName = getPanelName(panelIndex, panelType);
      options.push({
        key: panelKey,
        name: panelName
      });
    });
    
    return options;
  }, [productsByPanel, panelData]);

  // Fetch product groups
  const { data: productGroups } = useQuery({
    queryKey: ['product-groups-public'],
    queryFn: async () => {
      const r = await axios.get(`${API_URL}/api/product-groups`);
      return r.data;
    },
  });

  // Flat ordered products list with group support
  const orderedProducts = useMemo(() => {
    if (!products) return [];
    let list = [...products];
    
    // Apply filters
    if (selectedPanel !== 'all') {
      const [pType, pIndex] = selectedPanel.split('-');
      list = list.filter(p => (p.panel_type || 'xtream') === pType && (p.panel_index ?? 0) === Number(pIndex));
    }
    if (accountTypeFilter !== 'all') {
      list = list.filter(p => {
        if (accountTypeFilter === 'subscriber') return p.account_type === 'subscriber' || !p.account_type;
        if (accountTypeFilter === 'reseller') return p.account_type === 'reseller';
        return true;
      });
    }
    if (priceFilter !== 'all') {
      list = list.filter(p => {
        const prices = Object.values(p.prices || {});
        const minPrice = prices.length ? Math.min(...prices) : 0;
        if (priceFilter === 'free') return minPrice === 0;
        if (priceFilter === 'under10') return minPrice > 0 && minPrice < 10;
        if (priceFilter === 'under25') return minPrice >= 10 && minPrice < 25;
        if (priceFilter === 'over25') return minPrice >= 25;
        return true;
      });
    }
    if (connectionFilter !== 'all') {
      const connNum = parseInt(connectionFilter);
      list = list.filter(p => p.account_type === 'reseller' || (p.max_connections || 1) === connNum);
    }

    // Build grouped structure using subgroups
    const grps = productGroups || [];
    const result = [];
    const allGids = new Set(grps.map(g => g.id));

    grps.forEach(g => {
      const subs = g.subgroups || [];
      const groupProds = list.filter(p => p.group_id === g.id);
      if (groupProds.length === 0) return;

      if (subs.length > 0) {
        const subCards = [];
        subs.forEach(sg => {
          const prods = groupProds.filter(p => p.subgroup_id === sg.id).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
          if (prods.length > 0) subCards.push({ ...sg, products: prods });
        });
        // Products in group but no subgroup
        const sgIds = new Set(subs.map(s => s.id));
        const noSub = groupProds.filter(p => !p.subgroup_id || !sgIds.has(p.subgroup_id)).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
        noSub.forEach(p => subCards.push({ id: p.id, name: p.name, products: [p] }));
        if (subCards.length > 0) result.push({ ...g, subCards });
      } else {
        // No subgroups — each product is its own card
        const cards = groupProds.sort((a, b) => (a.display_order || 0) - (b.display_order || 0))
          .map(p => ({ id: p.id, name: p.name, products: [p] }));
        result.push({ ...g, subCards: cards });
      }
    });

    // Ungrouped products
    const ungrouped = list.filter(p => !p.group_id || !allGids.has(p.group_id)).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
    if (ungrouped.length > 0) {
      const cards = ungrouped.map(p => ({ id: p.id, name: p.name, products: [p] }));
      result.push({ id: '', name: '', subCards: cards });
    }

    return result;
  }, [products, productGroups, selectedPanel, priceFilter, accountTypeFilter, connectionFilter]);

  return (
    <div 
      className="min-h-screen"
      style={{ backgroundColor: branding.homepage_bg_color || (document.documentElement.classList.contains('dark') ? '#111827' : '#ffffff') }}
    >
      {/* Navigation */}
      <nav className="bg-white dark:bg-gray-900 shadow-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <Link to="/" className="flex items-center gap-2">
              <Server className="w-8 h-8" style={{ color: branding.primary_color || '#3b82f6' }} />
              <span className="text-xl font-bold dark:text-white">{branding.site_name || 'IPTV Billing'}</span>
            </Link>
            
            <div className="flex items-center gap-4">
              <CurrencySwitcher />
              {user ? (
                <>
                  <Link 
                    to="/checkout" 
                    className="relative flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-white"
                  >
                    <ShoppingCart className="w-5 h-5" />
                    {items.length > 0 && (
                      <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs font-bold rounded-full flex items-center justify-center">
                        {items.length}
                      </span>
                    )}
                  </Link>
                  <Link 
                    to="/dashboard" 
                    className="px-4 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-white"
                  >
                    Dashboard
                  </Link>
                </>
              ) : (
                <>
                  <Link 
                    to="/login" 
                    className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-white"
                  >
                    <LogIn className="w-5 h-5" />
                    Sign In
                  </Link>
                  <Link 
                    to="/register" 
                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-white"
                    style={{ backgroundColor: branding.primary_color || '#3b82f6' }}
                  >
                    <UserPlus className="w-5 h-5" />
                    Sign Up
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section 
        className="py-20 text-white relative overflow-hidden"
        style={{ 
          background: branding.hero_background_image 
            ? `url(${branding.hero_background_image}) center/cover no-repeat`
            : branding.homepage_bg_color
            ? branding.homepage_bg_color
            : `linear-gradient(135deg, ${branding.primary_color || '#3b82f6'} 0%, ${branding.secondary_color || '#1d4ed8'} 100%)`,
        }}
      >
        {/* Dark overlay for better text readability on images */}
        {branding.hero_background_image && (
          <div className="absolute inset-0 bg-black bg-opacity-40 z-0"></div>
        )}
        
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative z-10">
          <h1 className="text-3xl sm:text-5xl font-bold mb-4 sm:mb-6 drop-shadow-lg">{branding.hero_title || 'Premium IPTV Services'}</h1>
          <p className="text-xl mb-8 opacity-90 drop-shadow-md">{branding.hero_description || 'Stream thousands of channels in HD quality'}</p>
          <a 
            href="#pricing" 
            className="inline-block px-8 py-4 bg-white text-blue-600 rounded-lg font-semibold hover:bg-gray-100 transition shadow-lg"
          >
            View Plans
          </a>
        </div>
      </section>

      {/* Features */}
      <section className="">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid md:grid-cols-3 gap-8">
          <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-md">
            <div className="w-12 h-12 rounded-lg flex items-center justify-center mb-4" style={{ backgroundColor: `${branding.primary_color}20` }}>
              <Server className="w-6 h-6" style={{ color: branding.primary_color }} />
            </div>
            <h3 className="text-xl font-semibold mb-2 dark:text-white">{branding.feature_1_title || 'Instant Activation'}</h3>
            <p className="text-gray-600 dark:text-gray-300">
              {branding.feature_1_description || 'Get your credentials immediately after payment. Start watching within minutes.'}
            </p>
          </div>
          <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-md">
            <div className="w-12 h-12 rounded-lg flex items-center justify-center mb-4" style={{ backgroundColor: `${branding.primary_color}20` }}>
              <Users className="w-6 h-6" style={{ color: branding.primary_color }} />
            </div>
            <h3 className="text-xl font-semibold mb-2 dark:text-white">{branding.feature_2_title || 'Multiple Connections'}</h3>
            <p className="text-gray-600 dark:text-gray-300">
              {branding.feature_2_description || 'Watch on multiple devices simultaneously. Perfect for families.'}
            </p>
          </div>
          <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-md">
            <div className="w-12 h-12 rounded-lg flex items-center justify-center mb-4" style={{ backgroundColor: `${branding.primary_color}20` }}>
              <ShoppingCart className="w-6 h-6" style={{ color: branding.primary_color }} />
            </div>
            <h3 className="text-xl font-semibold mb-2 dark:text-white">{branding.feature_3_title || 'Flexible Plans'}</h3>
            <p className="text-gray-600 dark:text-gray-300">
              {branding.feature_3_description || 'Choose from 1, 3, 6, or 12-month plans. Save more with longer subscriptions.'}
            </p>
          </div>
        </div>
        </div>
      </section>

      {/* Products Section with Sidebar */}
      <section id="pricing" className="">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <h2 className="text-2xl sm:text-4xl font-bold text-center mb-6 sm:mb-12 dark:text-white">Choose Your Plan</h2>

        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : (
          <div className="grid lg:grid-cols-4 gap-8">
            {/* Sidebar Filters */}
            <div className="lg:col-span-1">
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow-md p-6 sticky top-24">
                <div className="flex items-center justify-between mb-5">
                  <div className="flex items-center gap-2">
                    <Filter className="w-5 h-5 text-gray-700 dark:text-gray-300" />
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Filters</h3>
                  </div>
                  {(selectedPanel !== 'all' || priceFilter !== 'all' || accountTypeFilter !== 'all' || connectionFilter !== 'all') && (
                    <button
                      onClick={() => { setSelectedPanel('all'); setPriceFilter('all'); setAccountTypeFilter('all'); setConnectionFilter('all'); }}
                      className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      Clear all
                    </button>
                  )}
                </div>

                <div className="space-y-4">
                  {/* Panel Filter */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Service</label>
                    <select value={selectedPanel}
                      onChange={(e) => { setSelectedPanel(e.target.value); if (e.target.value !== 'all') setPriceFilter('all'); }}
                      className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                      style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' }}
                    >
                      {panelOptions.map(opt => (
                        <option key={opt.key} value={opt.key}>{opt.name}</option>
                      ))}
                    </select>
                  </div>

                  {/* Product Type Filter */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Product Type</label>
                    <select value={accountTypeFilter}
                      onChange={(e) => setAccountTypeFilter(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                      style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' }}
                    >
                      <option value="all">All Products</option>
                      <option value="subscriber">Subscription Plans</option>
                      <option value="reseller">Reseller Packages</option>
                    </select>
                  </div>

                  {/* Price Range Filter */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Price Range</label>
                    <select value={priceFilter}
                      onChange={(e) => setPriceFilter(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                      style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' }}
                    >
                      <option value="all">All Prices</option>
                      <option value="free">Free Trials</option>
                      <option value="under10">Under $10</option>
                      <option value="under25">$10 - $25</option>
                      <option value="over25">$25+</option>
                    </select>
                  </div>

                  {/* Connections Filter */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Connections</label>
                    <select value={connectionFilter}
                      onChange={(e) => setConnectionFilter(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                      style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' }}
                    >
                      <option value="all">All Connections</option>
                      {[1,2,3,4,5,6].map(n => (
                        <option key={n} value={String(n)}>{n} Connection{n > 1 ? 's' : ''}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            </div>

            {/* Main Content */}
            <div className="lg:col-span-3">
              {orderedProducts.length > 0 ? (
                <div className="space-y-10">
                  {orderedProducts.map((group) => (
                    <div key={group.id || 'ungrouped'}>
                      {group.name && (
                        <div className="flex items-center gap-4 mb-4">
                          <div className="h-px flex-1 bg-gray-300 dark:bg-gray-600"></div>
                          <h3 className="text-xl font-bold text-gray-800 dark:text-white">{group.name}</h3>
                          <div className="h-px flex-1 bg-gray-300 dark:bg-gray-600"></div>
                        </div>
                      )}
                      <div className="space-y-4">
                        {(group.subCards || []).map((subCard) => (
                          <GroupCard key={subCard.id} group={subCard} allProducts={products} />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-16">
                  <Grid className="w-16 h-16 text-gray-400 mx-auto mb-4" />
                  <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">No products found</h3>
                  <p className="text-gray-600 dark:text-gray-400 mb-4">Try adjusting your filters</p>
                  <button
                    onClick={() => { setSelectedPanel('all'); setPriceFilter('all'); setAccountTypeFilter('all'); setConnectionFilter('all'); }}
                    className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                  >
                    Clear Filters
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-white py-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <h3 className="text-2xl font-bold mb-4">{branding.site_name}</h3>
            <p className="text-gray-400">{branding.footer_text || 'Premium IPTV Services'}</p>
            <p className="text-gray-500 mt-4 text-sm">
              © {new Date().getFullYear()} {branding.site_name}. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

function GroupedProductCard({ products, connections }) {
  const { user } = useAuthStore();
  const { addItem } = useCartStore();
  const { branding } = useBrandingStore();
  const { symbol: currencySymbol, convertPrice } = useCurrencyStore();
  const [showChannels, setShowChannels] = React.useState(false);
  const [channels, setChannels] = React.useState([]);
  const [loadingChannels, setLoadingChannels] = React.useState(false);

  const sorted = [...products].sort((a, b) => {
    const aMonths = parseInt(Object.keys(a.prices)[0]) || 1;
    const bMonths = parseInt(Object.keys(b.prices)[0]) || 1;
    return aMonths - bMonths;
  });

  const handleAddToCart = (product, termMonths, price) => {
    if (!user) { window.location.href = '/login'; return; }
    addItem({ product_id: product.id, product_name: product.name, term_months: termMonths, price, account_type: product.account_type });
    window.location.href = '/checkout';
  };

  const handleShowChannels = async () => {
    setShowChannels(true);
    setLoadingChannels(true);
    try {
      const response = await axios.get(`${API_URL}/api/products/${sorted[0].id}/channels`);
      setChannels(response.data.channels || []);
    } catch { setChannels([]); }
    finally { setLoadingChannels(false); }
  };

  const cardColor = branding.product_card_color || '#2563eb';
  const darkenColor = (hex, pct) => {
    const num = parseInt(hex.replace('#',''),16), amt = Math.round(2.55*pct);
    const R=Math.max(0,(num>>16)-amt), G=Math.max(0,(num>>8&0xFF)-amt), B=Math.max(0,(num&0xFF)-amt);
    return '#'+(0x1000000+R*0x10000+G*0x100+B).toString(16).slice(1);
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg shadow-md overflow-hidden hover:shadow-lg transition border border-gray-200 dark:border-gray-700">
      <div className="flex flex-col md:flex-row">
        <div className="md:w-1/3 p-4 text-white relative" style={{ background: `linear-gradient(135deg, ${cardColor} 0%, ${darkenColor(cardColor, 15)} 100%)` }}>
          <h3 className="text-lg font-bold mb-1">{connections} Connection{connections > 1 ? 's' : ''}</h3>
          <p className="text-white text-xs opacity-90">{sorted.length} plan{sorted.length > 1 ? 's' : ''} available</p>
          <div className="mt-3 pt-3 border-t border-white border-opacity-20">
            <div className="flex items-center gap-2 text-xs">
              <Server className="w-3.5 h-3.5" />
              <span>{connections} connection{connections > 1 ? 's' : ''}</span>
            </div>
          </div>
        </div>

        <div className="md:w-2/3 p-4 flex flex-col justify-between">
          <div className="space-y-2">
            {sorted.map((product) => {
              const [term, price] = Object.entries(product.prices)[0] || ['1', 0];
              return (
                <button key={product.id}
                  onClick={() => handleAddToCart(product, parseInt(term), parseFloat(price))}
                  className="w-full flex items-center justify-between bg-gray-50 dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-gray-700 p-3 rounded-lg transition border-2 border-gray-200 dark:border-gray-600 hover:border-blue-400 group"
                >
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{product.name}</span>
                  <span className="text-lg font-bold text-blue-600 dark:text-blue-400 group-hover:scale-105 transition-transform">
                    {parseFloat(price) === 0 ? 'FREE' : `${currencySymbol}${convertPrice(price).toFixed(2)}`}
                  </span>
                </button>
              );
            })}
          </div>
          {sorted.some((p) => p.show_channels !== false) && (
          <button onClick={handleShowChannels}
            className="mt-3 w-full flex items-center justify-center gap-2 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 px-3 py-2 rounded-lg hover:border-blue-400 hover:text-blue-600 dark:hover:text-blue-400 transition text-sm font-medium">
            <Info className="w-4 h-4" /> View Channels
          </button>
          )}
        </div>
      </div>

      {showChannels && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4" onClick={() => setShowChannels(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg max-w-2xl w-full max-h-[80vh] overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
              <div>
                <h3 className="text-2xl font-bold text-gray-900 dark:text-white">{connections} Connection{connections > 1 ? 's' : ''}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Live TV Channel Packages</p>
              </div>
              <button onClick={() => setShowChannels(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <X className="w-6 h-6" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {loadingChannels ? (
                <div className="text-center py-8"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto" /></div>
              ) : channels.length > 0 ? (
                <div className="grid grid-cols-2 gap-2">
                  {channels.map(ch => (
                    <div key={ch.id} className="p-2 bg-gray-50 dark:bg-gray-700 rounded text-sm text-gray-800 dark:text-gray-200">{ch.name}</div>
                  ))}
                </div>
              ) : (
                <p className="text-center text-gray-500 py-8">Channel list not available</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function GroupCard({ group, allProducts }) {
  const { user } = useAuthStore();
  const { addItem } = useCartStore();
  const { branding } = useBrandingStore();
  const { symbol: currencySymbol, convertPrice } = useCurrencyStore();
  const [showChannels, setShowChannels] = React.useState(false);
  const [channels, setChannels] = React.useState([]);
  const [loadingChannels, setLoadingChannels] = React.useState(false);

  const products = group.products || [];
  const firstProduct = products[0];
  const conns = firstProduct?.max_connections || 1;
  const isReseller = firstProduct?.account_type === 'reseller';
  const isTrial = products.length === 1 && firstProduct?.is_trial;

  const handleAddToCart = (product) => {
    if (!user) { window.location.href = '/login'; return; }
    const [term, price] = Object.entries(product.prices || {})[0] || ['1', 0];
    addItem({ product_id: product.id, product_name: product.name, term_months: parseInt(term), price: parseFloat(price), account_type: product.account_type });
    window.location.href = '/checkout';
  };

  const handleShowChannels = async () => {
    setShowChannels(true);
    setLoadingChannels(true);
    try {
      const response = await axios.get(`${API_URL}/api/products/${firstProduct.id}/channels`);
      setChannels(response.data.channels || []);
    } catch { setChannels([]); }
    finally { setLoadingChannels(false); }
  };

  const cardColor = branding.product_card_color || '#2563eb';
  const darken = (hex, pct) => {
    const n = parseInt(hex.replace('#',''),16), a = Math.round(2.55*pct);
    return '#'+(0x1000000+Math.max(0,(n>>16)-a)*0x10000+Math.max(0,(n>>8&0xFF)-a)*0x100+Math.max(0,(n&0xFF)-a)).toString(16).slice(1);
  };

  return (
    <>
      <div className={`bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden hover:shadow-md transition ${isTrial ? 'border-yellow-300 dark:border-yellow-700' : ''}`}>
        <div className="flex flex-col md:flex-row">
          {/* Left Panel */}
          <div className="md:w-56 shrink-0 p-5 text-white relative flex flex-col justify-center"
            style={{ background: isTrial ? `linear-gradient(135deg, #d97706 0%, #92400e 100%)` : `linear-gradient(135deg, ${cardColor} 0%, ${darken(cardColor, 20)} 100%)` }}>
            {isTrial && <span className="absolute top-2 right-2 px-2 py-0.5 bg-yellow-400 text-yellow-900 text-[10px] font-bold rounded-full">TRIAL</span>}
            <h3 className="text-xl font-bold">{group.name || firstProduct?.name}</h3>
            <p className="text-white/70 text-xs mt-1">{products.length} plan{products.length !== 1 ? 's' : ''} available</p>
            <div className="mt-4 pt-3 border-t border-white/20 text-xs flex items-center gap-2">
              <Server className="w-4 h-4" />
              {isReseller ? <span>{firstProduct?.reseller_credits} credits</span> : <span>{conns} connection{conns !== 1 ? 's' : ''}</span>}
            </div>
          </div>

          {/* Right: Product Rows */}
          <div className="flex-1 divide-y divide-gray-100 dark:divide-gray-800">
            {products.map((product) => {
              const [term, price] = Object.entries(product.prices || {})[0] || ['1', 0];
              const displayPrice = product.is_trial && parseFloat(price) === 0 ? 'FREE' : `${currencySymbol}${convertPrice(price).toFixed(2)}`;
              return (
                <div key={product.id}>
                  <button onClick={() => handleAddToCart(product)}
                    className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-blue-50 dark:hover:bg-gray-800 transition text-left group">
                    <div>
                      <span className="text-sm font-medium text-gray-800 dark:text-gray-200 group-hover:text-blue-700">{product.name}</span>
                      {product.is_bundle && <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400 rounded-full font-semibold">BUNDLE</span>}
                    </div>
                    <span className="text-lg font-bold text-blue-600 dark:text-blue-400">{displayPrice}</span>
                  </button>
                  {product.is_bundle && product.bundle_product_ids?.length > 0 && (
                    <div className="px-5 pb-2 -mt-1">
                      <p className="text-[10px] text-gray-400 mb-0.5">Includes:</p>
                      <div className="flex flex-wrap gap-1">
                        {product.bundle_product_ids.map(bId => {
                          const bp = allProducts?.find(p => p.id === bId);
                          return bp ? <span key={bId} className="text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded">{bp.name}</span> : null;
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
            {/* View Channels */}
            {firstProduct?.account_type === 'subscriber' && firstProduct?.show_channels !== false && (
              <button onClick={handleShowChannels}
                className="w-full flex items-center justify-center gap-2 px-5 py-2.5 text-xs text-gray-500 hover:text-blue-600 transition">
                <Info className="w-3.5 h-3.5" /> View Channels
              </button>
            )}
          </div>
        </div>
      </div>

      {showChannels && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setShowChannels(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg max-w-2xl w-full max-h-[80vh] overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
              <div>
                <h3 className="text-xl font-bold text-gray-900 dark:text-white">{group.name}</h3>
                <p className="text-sm text-gray-500 mt-1">Channel Packages</p>
              </div>
              <button onClick={() => setShowChannels(false)} className="text-gray-400 hover:text-gray-600"><X className="w-6 h-6" /></button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {loadingChannels ? (
                <div className="text-center py-8"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto" /></div>
              ) : channels.length > 0 ? (
                <div className="grid grid-cols-2 gap-2">
                  {channels.map(ch => <div key={ch.id} className="p-2 bg-gray-50 dark:bg-gray-700 rounded text-sm">{ch.name}</div>)}
                </div>
              ) : <p className="text-center text-gray-500 py-8">Channel list not available</p>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ProductCard({ product, allProducts }) {
  return <GroupCard group={{ id: product.id, name: product.name, products: [product] }} allProducts={allProducts} />;
}
