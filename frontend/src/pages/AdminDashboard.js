import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { useAuthStore } from '../store/store';
import { useCurrencyStore } from '../store/currency';
import { 
  Home, ShoppingCart, Users, Server, MessageSquare, FileText, 
  BarChart3, Settings, LogOut, DollarSign, TrendingUp, Plus, Shield, 
  UserPlus, Menu, X, Package, Mail, Download, Tag, RefreshCw, ChevronDown, ChevronRight, BookOpen, Smartphone, Truck, Box } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { toast } from 'sonner';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { symbol: currencySymbol } = useCurrencyStore();
  const [activeSection, setActiveSection] = useState('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [expandedMenus, setExpandedMenus] = useState({});
  
  const isStaff = user?.role === 'staff';
  const staffPerms = user?.permissions || [];
  const hasPermission = (perm) => !isStaff || staffPerms.includes(perm);

  const { data: stats, isLoading } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: async () => {
      const response = await adminAPI.getStats();
      return response.data;
    },
  });

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const toggleMenu = (menuId) => {
    setExpandedMenus(prev => ({
      ...prev,
      [menuId]: !prev[menuId]
    }));
  };

  const sidebarItems = [
    { id: 'dashboard', label: 'Dashboard', icon: Home, path: '/admin' },
    { id: 'analytics', label: 'Analytics', icon: BarChart3, path: '/admin/analytics' },
    { id: 'launcher', label: 'Launcher', icon: Smartphone, path: '/admin/launcher' },
    { 
      id: 'customers', 
      label: 'Customers', 
      icon: Users, 
      path: '/admin/customers',
      subItems: [
        { id: 'customers-list', label: 'Customers', icon: Users, path: '/admin/customers' },
        { id: 'orders', label: 'Orders', icon: ShoppingCart, path: '/admin/orders' },
        { id: 'invoices', label: 'Invoices', icon: FileText, path: '/admin/invoices' },
        { id: 'imported-users', label: 'Imported Users', icon: Users, path: '/admin/imported-users' },
        { id: 'shipments', label: 'Shipments', icon: Truck, path: '/admin/shipments' }
      ]
    },
    { 
      id: 'products', 
      label: 'Products', 
      icon: Package, 
      path: '/admin/products',
      subItems: [
        { id: 'products-list', label: 'Services & Plans', icon: Package, path: '/admin/products' },
        { id: 'physical-items', label: 'Physical Items', icon: Box, path: '/admin/physical-items' }
      ]
    },
    { 
      id: 'email', 
      label: 'Email', 
      icon: Mail, 
      subItems: [
        { id: 'mass-email', label: 'Mass Email', icon: Mail, path: '/admin/mass-email' },
        { id: 'email-templates', label: 'Email Templates', icon: FileText, path: '/admin/email-templates' }
      ]
    },
    { id: 'knowledge-base', label: 'Knowledge Base', icon: BookOpen, path: '/admin/knowledge-base' },
    { id: 'downloads', label: 'Downloads', icon: Download, path: '/admin/downloads' },
    { id: 'coupons', label: 'Coupons', icon: Tag, path: '/admin/coupons' },
    { id: 'refunds', label: 'Refunds', icon: RefreshCw, path: '/admin/refunds' },
    { id: 'tickets', label: 'Tickets', icon: MessageSquare, path: '/admin/tickets' },
    { id: 'staff', label: 'Staff', icon: Shield, path: '/admin/staff' },
    { id: 'settings', label: 'Settings', icon: Settings, path: '/admin/settings' },
  ].filter(item => {
    // Staff users only see items matching their permissions
    if (!isStaff) return true;
    const permMap = {
      'dashboard': 'dashboard', 'customers-section': 'customers', 'customers-list': 'customers',
      'imported-users': 'imported_users', 'orders': 'orders', 'invoices': 'orders', 'shipments': 'orders',
      'services': 'services', 'tickets': 'tickets',
    };
    const perm = permMap[item.id];
    if (!perm) return false; // hide settings, products, staff, etc. from staff
    return staffPerms.includes(perm);
  });

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 shadow-sm sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="lg:hidden p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                data-testid="mobile-menu-toggle"
              >
                {sidebarOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>
              <Server className="w-8 h-8 text-blue-600" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Admin Dashboard</h1>
                <p className="text-sm text-gray-600 dark:text-gray-400">IPTV Billing System</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <button
                onClick={async () => {
                  try {
                    const response = await adminAPI.downloadUserGuide();
                    const url = window.URL.createObjectURL(new Blob([response.data]));
                    const link = document.createElement('a');
                    link.href = url;
                    link.setAttribute('download', 'IPTV_Billing_Admin_User_Guide.pdf');
                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                    window.URL.revokeObjectURL(url);
                  } catch (err) {
                    toast.error('Failed to download user guide');
                  }
                }}
                className="flex items-center gap-2 text-gray-600 hover:text-blue-600 transition-colors text-sm"
                title="Download Admin User Guide"
              >
                <BookOpen className="w-5 h-5" />
                <span className="hidden md:inline">User Guide</span>
              </button>
              <span className="text-gray-700 dark:text-gray-200 text-sm hidden sm:inline">Admin: {user?.name}</span>
              <button
                onClick={handleLogout}
                className="flex items-center gap-2 text-gray-600 hover:text-red-600 transition-colors"
                data-testid="logout-button"
              >
                <LogOut className="w-5 h-5" />
                <span className="hidden sm:inline">Logout</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid lg:grid-cols-4 gap-6">
          {/* Sidebar Navigation */}
          <div className={`lg:col-span-1 ${sidebarOpen ? 'block' : 'hidden'} lg:block`}>
            <nav className="bg-white dark:bg-gray-800 rounded-lg shadow p-2 space-y-1" data-testid="sidebar-navigation">
              {sidebarItems.map((item) => {
                const Icon = item.icon;
                const isActive = item.id === activeSection;
                const hasSubItems = item.subItems && item.subItems.length > 0;
                const isExpanded = expandedMenus[item.id];
                
                return (
                  <div key={item.id}>
                    {/* Main Menu Item */}
                    {hasSubItems ? (
                      <button
                        onClick={() => toggleMenu(item.id)}
                        className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium transition-colors flex items-center justify-between ${
                          isActive
                            ? 'bg-blue-600 text-white'
                            : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }`}
                        data-testid={`sidebar-${item.id}-button`}
                      >
                        <div className="flex items-center gap-3">
                          <Icon className="w-5 h-5" />
                          <span>{item.label}</span>
                        </div>
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4" />
                        ) : (
                          <ChevronRight className="w-4 h-4" />
                        )}
                      </button>
                    ) : (
                      <Link
                        to={item.path}
                        onClick={() => setActiveSection(item.id)}
                        className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium transition-colors flex items-center gap-3 ${
                          isActive
                            ? 'bg-blue-600 text-white'
                            : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }`}
                        data-testid={`sidebar-${item.id}-button`}
                      >
                        <Icon className="w-5 h-5" />
                        <span>{item.label}</span>
                      </Link>
                    )}

                    {/* Sub Menu Items */}
                    {hasSubItems && isExpanded && (
                      <div className="ml-4 mt-1 space-y-1">
                        {item.subItems.map((subItem) => {
                          const SubIcon = subItem.icon;
                          const isSubActive = subItem.id === activeSection;
                          
                          return (
                            <Link
                              key={subItem.id}
                              to={subItem.path}
                              onClick={() => setActiveSection(subItem.id)}
                              className={`w-full text-left px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-3 ${
                                isSubActive
                                  ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 font-medium'
                                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
                              }`}
                              data-testid={`sidebar-${subItem.id}-button`}
                            >
                              <SubIcon className="w-4 h-4" />
                              <span>{subItem.label}</span>
                            </Link>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </nav>
          </div>

          {/* Dashboard Content */}
          <div className="lg:col-span-3 space-y-6">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
              </div>
            ) : (
              <>
                {/* Stats Cards */}
                <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
                  {/* Total Customers */}
                  <Card 
                    className="hover:shadow-lg transition-all duration-300 hover:-translate-y-1" 
                    data-testid="stat-card-customers"
                  >
                    <CardContent className="p-6">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                            Total Customers
                          </p>
                          <p className="text-xl sm:text-3xl font-bold text-gray-900 dark:text-white mt-2">
                            {stats?.total_customers || 0}
                          </p>
                          <p className="text-sm text-green-600 dark:text-green-400 mt-1 flex items-center gap-1">
                            <TrendingUp className="w-4 h-4" />
                            Active accounts
                          </p>
                        </div>
                        <div className="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                          <Users className="w-8 h-8 text-blue-600 dark:text-blue-400" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Active Services */}
                  <Card 
                    className="hover:shadow-lg transition-all duration-300 hover:-translate-y-1" 
                    data-testid="stat-card-services"
                  >
                    <CardContent className="p-6">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                            Active Services
                          </p>
                          <p className="text-xl sm:text-3xl font-bold text-gray-900 dark:text-white mt-2">
                            {stats?.active_services || 0}
                          </p>
                          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                            of {stats?.total_services || 0} total
                          </p>
                        </div>
                        <div className="p-3 bg-green-100 dark:bg-green-900/30 rounded-lg">
                          <Server className="w-8 h-8 text-green-600 dark:text-green-400" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Total Revenue */}
                  <Card 
                    className="hover:shadow-lg transition-all duration-300 hover:-translate-y-1" 
                    data-testid="stat-card-revenue"
                  >
                    <CardContent className="p-6">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                            Total Revenue
                          </p>
                          <p className="text-xl sm:text-3xl font-bold text-gray-900 dark:text-white mt-2">
                            {currencySymbol}{stats?.total_revenue?.toFixed(2) || '0.00'}
                          </p>
                          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                            All time earnings
                          </p>
                        </div>
                        <div className="p-3 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
                          <DollarSign className="w-8 h-8 text-purple-600 dark:text-purple-400" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Tickets Awaiting Reply */}
                  <Card 
                    className="hover:shadow-lg transition-all duration-300 hover:-translate-y-1" 
                    data-testid="stat-card-tickets"
                  >
                    <CardContent className="p-6">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                            Awaiting Reply
                          </p>
                          <p className="text-xl sm:text-3xl font-bold text-gray-900 dark:text-white mt-2">
                            {stats?.ticket_status?.awaiting_reply || 0}
                          </p>
                          <p className="text-sm text-orange-600 dark:text-orange-400 mt-1">
                            Tickets need attention
                          </p>
                        </div>
                        <div className="p-3 bg-orange-100 dark:bg-orange-900/30 rounded-lg">
                          <MessageSquare className="w-8 h-8 text-orange-600 dark:text-orange-400" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Charts and Ticket Status */}
                <div className="grid lg:grid-cols-2 gap-6">
                  {/* Revenue Chart */}
                  <Card data-testid="revenue-chart-card">
                    <CardHeader>
                      <CardTitle className="text-xl font-semibold">Revenue Overview</CardTitle>
                      <CardDescription>Last 7 days</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ResponsiveContainer width="100%" height={300}>
                        <AreaChart data={stats?.revenue_data || []}>
                          <defs>
                            <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#2563eb" stopOpacity={0.3}/>
                              <stop offset="95%" stopColor="#2563eb" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" className="dark:stroke-gray-700" />
                          <XAxis 
                            dataKey="date" 
                            stroke="#6b7280"
                            style={{ fontSize: '12px' }}
                          />
                          <YAxis 
                            stroke="#6b7280"
                            style={{ fontSize: '12px' }}
                          />
                          <Tooltip 
                            contentStyle={{
                              backgroundColor: '#ffffff',
                              border: '1px solid #e5e7eb',
                              borderRadius: '8px',
                              boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
                            }}
                            formatter={(value) => [`${currencySymbol}${value.toFixed(2)}`, 'Revenue']}
                          />
                          <Area 
                            type="monotone" 
                            dataKey="revenue" 
                            stroke="#2563eb" 
                            strokeWidth={2}
                            fillOpacity={1} 
                            fill="url(#colorRevenue)" 
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>

                  {/* Ticket Status Card */}
                  <Card data-testid="ticket-status-card">
                    <CardHeader>
                      <CardTitle className="text-xl font-semibold">Ticket Status</CardTitle>
                      <CardDescription>Overview of support tickets</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {/* Awaiting Reply */}
                        <Link to="/admin/tickets" className="block">
                          <div className="flex items-center justify-between p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors">
                            <div className="flex items-center gap-3">
                              <div className="p-2 bg-blue-600 rounded-lg">
                                <MessageSquare className="w-5 h-5 text-white" />
                              </div>
                              <div>
                                <p className="text-sm font-medium text-gray-900 dark:text-white">
                                  Awaiting Reply
                                </p>
                                <p className="text-xs text-gray-600 dark:text-gray-400">
                                  Requires attention
                                </p>
                              </div>
                            </div>
                            <span className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                              {stats?.ticket_status?.awaiting_reply || 0}
                            </span>
                          </div>
                        </Link>

                        {/* Open */}
                        <div className="flex items-center justify-between p-3 bg-green-50 dark:bg-green-900/20 rounded-lg">
                          <div className="flex items-center gap-3">
                            <div className="p-2 bg-green-600 rounded-lg">
                              <MessageSquare className="w-5 h-5 text-white" />
                            </div>
                            <div>
                              <p className="text-sm font-medium text-gray-900 dark:text-white">
                                Open
                              </p>
                              <p className="text-xs text-gray-600 dark:text-gray-400">
                                New tickets
                              </p>
                            </div>
                          </div>
                          <span className="text-2xl font-bold text-green-600 dark:text-green-400">
                            {stats?.ticket_status?.open || 0}
                          </span>
                        </div>

                        {/* In Progress */}
                        <div className="flex items-center justify-between p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                          <div className="flex items-center gap-3">
                            <div className="p-2 bg-yellow-600 rounded-lg">
                              <MessageSquare className="w-5 h-5 text-white" />
                            </div>
                            <div>
                              <p className="text-sm font-medium text-gray-900 dark:text-white">
                                In Progress
                              </p>
                              <p className="text-xs text-gray-600 dark:text-gray-400">
                                Being handled
                              </p>
                            </div>
                          </div>
                          <span className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
                            {stats?.ticket_status?.in_progress || 0}
                          </span>
                        </div>

                        {/* Closed */}
                        <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
                          <div className="flex items-center gap-3">
                            <div className="p-2 bg-gray-600 rounded-lg">
                              <MessageSquare className="w-5 h-5 text-white" />
                            </div>
                            <div>
                              <p className="text-sm font-medium text-gray-900 dark:text-white">
                                Closed
                              </p>
                              <p className="text-xs text-gray-600 dark:text-gray-400">
                                Resolved tickets
                              </p>
                            </div>
                          </div>
                          <span className="text-2xl font-bold text-gray-600 dark:text-gray-400">
                            {stats?.ticket_status?.closed || 0}
                          </span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Recent Orders */}
                {stats?.recent_orders && stats.recent_orders.length > 0 && (
                  <Card data-testid="recent-orders-card">
                    <CardHeader>
                      <CardTitle className="text-xl font-semibold">Recent Orders</CardTitle>
                      <CardDescription>Latest customer orders</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Order ID</TableHead>
                            <TableHead>Customer</TableHead>
                            <TableHead>Total</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead>Date</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {stats.recent_orders.slice(0, 5).map((order) => (
                            <TableRow key={order.id} data-testid={`order-row-${order.id}`}>
                              <TableCell className="font-medium font-mono">
                                #{order.id.substring(0, 8)}
                              </TableCell>
                              <TableCell>{order.customer_name}</TableCell>
                              <TableCell className="font-semibold">
                                {currencySymbol}{order.total.toFixed(2)}
                              </TableCell>
                              <TableCell>
                                <Badge 
                                  className={
                                    order.status === 'paid' 
                                      ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' 
                                      : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                                  }
                                >
                                  {order.status}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-sm text-gray-600 dark:text-gray-300">
                                {new Date(order.created_at).toLocaleDateString()}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                      <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                        <Link 
                          to="/admin/orders" 
                          className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-semibold text-sm"
                        >
                          View all orders →
                        </Link>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
