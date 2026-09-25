import { formatDate } from "../utils/timezone";
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api, { adminAPI } from '../api/api';
import { PaymentBadge, PAYMENT_LABELS, ADMIN_PAID_BY } from '../components/cmtv/paymentMethod'; // CMTV local change 2026-09-25
import axios from 'axios';
import { ArrowLeft, Check, Search, Filter, ChevronLeft, ChevronRight, X, CheckSquare, Square, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

export default function AdminOrders() {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all'); // all, pending, paid, cancelled
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedOrders, setSelectedOrders] = useState(new Set());
  
  const { data: orders, isLoading } = useQuery({
    queryKey: ['admin-orders'],
    queryFn: async () => {
      const response = await adminAPI.getOrders();
      return response.data;
    },
  });

  // Filter orders based on search term and status
  const filteredOrders = orders?.filter(order => {
    const matchesSearch = 
      order.customer_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      order.customer_email?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      order.id?.toLowerCase().includes(searchTerm.toLowerCase());
    
    const matchesStatus = statusFilter === 'all' || order.status === statusFilter;
    
    return matchesSearch && matchesStatus;
  }) || [];

  // Pagination calculations
  const totalOrders = filteredOrders.length;
  const totalPages = Math.ceil(totalOrders / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = startIndex + pageSize;
  const paginatedOrders = filteredOrders.slice(startIndex, endIndex);

  // Reset to page 1 when filters change
  React.useEffect(() => {
    setCurrentPage(1);
    setSelectedOrders(new Set()); // Clear selection when filters change
  }, [searchTerm, statusFilter, pageSize]);

  // Selection handlers
  const toggleSelectOrder = (orderId) => {
    const newSelected = new Set(selectedOrders);
    if (newSelected.has(orderId)) {
      newSelected.delete(orderId);
    } else {
      newSelected.add(orderId);
    }
    setSelectedOrders(newSelected);
  };

  const toggleSelectAll = () => {
    if (selectedOrders.size === paginatedOrders.length) {
      setSelectedOrders(new Set());
    } else {
      setSelectedOrders(new Set(paginatedOrders.map(o => o.id)));
    }
  };

  const selectAllPending = () => {
    const pendingIds = paginatedOrders.filter(o => o.status === 'pending').map(o => o.id);
    setSelectedOrders(new Set(pendingIds));
  };

  const clearSelection = () => {
    setSelectedOrders(new Set());
  };

  // Get selected orders that are pending (for bulk actions)
  const selectedPendingOrders = Array.from(selectedOrders).filter(id => {
    const order = orders?.find(o => o.id === id);
    return order?.status === 'pending';
  });

  // CMTV local change 2026-09-25: "Paid by" choice per pending order (defaults to what the customer picked)
  const [paidBy, setPaidBy] = useState({});
  const markPaidMutation = useMutation({
    mutationFn: (orderId) => (paidBy[orderId]
      ? api.post(`/api/admin/orders/${orderId}/mark-paid`, { payment_method: paidBy[orderId] })
      : adminAPI.markOrderPaid(orderId)),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-orders']);
    },
  });

  const cancelOrderMutation = useMutation({
    mutationFn: (orderId) => adminAPI.cancelOrder(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-orders']);
      toast.success('Order cancelled');
    },
  });

  const deleteOrderMutation = useMutation({
    mutationFn: (orderId) => axios.delete(`${process.env.REACT_APP_BACKEND_URL}/api/admin/orders/${orderId}`, {
      headers: { Authorization: `Bearer ${JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token}` }
    }),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-orders']);
      toast.success('Order deleted');
    },
    onError: (err) => toast.error(err.response?.data?.detail || 'Failed to delete order'),
  });

  const handleMarkPaid = (orderId) => {
    const o = orders?.find((x) => x.id === orderId);
    const by = PAYMENT_LABELS[paidBy[orderId] || o?.payment_method] || 'Manual';
    if (window.confirm(`Mark this order as paid (${by}) and provision services?`)) {
      markPaidMutation.mutate(orderId);
    }
  };

  const handleCancelOrder = (orderId) => {
    if (window.confirm('Are you sure you want to cancel this order?\n\nThis action cannot be undone.')) {
      cancelOrderMutation.mutate(orderId);
    }
  };

  const handleDeleteOrder = (orderId) => {
    if (window.confirm('Permanently delete this order? This removes the order, invoice, and payment records.\n\nThis cannot be undone.')) {
      deleteOrderMutation.mutate(orderId);
    }
  };

  // Bulk action handlers
  const [bulkProcessing, setBulkProcessing] = useState(false);

  const handleBulkMarkPaid = async () => {
    if (selectedPendingOrders.length === 0) {
      toast.info('No pending orders selected');
      return;
    }
    
    if (!window.confirm(`Mark ${selectedPendingOrders.length} order(s) as paid?\n\nThis will provision services for all selected orders.`)) {
      return;
    }

    setBulkProcessing(true);
    let successCount = 0;
    let failCount = 0;

    for (const orderId of selectedPendingOrders) {
      try {
        await adminAPI.markOrderPaid(orderId);
        successCount++;
      } catch (error) {
        failCount++;
        console.error(`Failed to mark order ${orderId} as paid:`, error);
      }
    }

    setBulkProcessing(false);
    queryClient.invalidateQueries(['admin-orders']);
    setSelectedOrders(new Set());
    
    if (failCount > 0) {
      toast.info(`Completed: ${successCount} successful, ${failCount} failed`);
    } else {
      toast.success(`Successfully marked ${successCount} order(s) as paid!`);
    }
  };

  const handleBulkCancel = async () => {
    if (selectedPendingOrders.length === 0) {
      toast.info('No pending orders selected');
      return;
    }
    
    if (!window.confirm(`Cancel ${selectedPendingOrders.length} order(s)?\n\nThis action cannot be undone.`)) {
      return;
    }

    setBulkProcessing(true);
    let successCount = 0;
    let failCount = 0;

    for (const orderId of selectedPendingOrders) {
      try {
        await adminAPI.cancelOrder(orderId);
        successCount++;
      } catch (error) {
        failCount++;
        console.error(`Failed to cancel order ${orderId}:`, error);
      }
    }

    setBulkProcessing(false);
    queryClient.invalidateQueries(['admin-orders']);
    setSelectedOrders(new Set());
    
    if (failCount > 0) {
      toast.info(`Completed: ${successCount} cancelled, ${failCount} failed`);
    } else {
      toast.success(`Successfully cancelled ${successCount} order(s)!`);
    }
  };

  // Get counts for filter badges
  const pendingCount = orders?.filter(o => o.status === 'pending').length || 0;
  const paidCount = orders?.filter(o => o.status === 'paid').length || 0;
  const cancelledCount = orders?.filter(o => o.status === 'cancelled').length || 0;

  const isAllSelected = paginatedOrders.length > 0 && selectedOrders.size === paginatedOrders.length;
  const isSomeSelected = selectedOrders.size > 0 && selectedOrders.size < paginatedOrders.length;

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
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Manage Orders</h1>
          <div className="text-sm text-gray-600 dark:text-gray-400">
            Showing {paginatedOrders.length} of {totalOrders} orders
          </div>
        </div>

        {/* Filters Row */}
        <div className="flex flex-col md:flex-row gap-4 mb-6">
          {/* Search Bar */}
          <div className="flex-1">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
              <input
                type="text"
                placeholder="Search by customer name, email, or order ID..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-5 h-5 text-gray-400" />
            <div className="flex rounded-lg border border-gray-300 dark:border-gray-600 overflow-hidden">
              <button
                onClick={() => setStatusFilter('all')}
                className={`px-4 py-2.5 text-sm font-medium transition ${
                  statusFilter === 'all'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                All ({orders?.length || 0})
              </button>
              <button
                onClick={() => setStatusFilter('pending')}
                className={`px-4 py-2.5 text-sm font-medium transition border-l border-gray-300 dark:border-gray-600 ${
                  statusFilter === 'pending'
                    ? 'bg-yellow-500 text-white'
                    : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                Pending ({pendingCount})
              </button>
              <button
                onClick={() => setStatusFilter('paid')}
                className={`px-4 py-2.5 text-sm font-medium transition border-l border-gray-300 dark:border-gray-600 ${
                  statusFilter === 'paid'
                    ? 'bg-green-600 text-white'
                    : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                Paid ({paidCount})
              </button>
              <button
                onClick={() => setStatusFilter('cancelled')}
                className={`px-4 py-2.5 text-sm font-medium transition border-l border-gray-300 dark:border-gray-600 ${
                  statusFilter === 'cancelled'
                    ? 'bg-red-600 text-white'
                    : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                Cancelled ({cancelledCount})
              </button>
            </div>
          </div>
        </div>

        {/* Bulk Actions Bar */}
        {selectedOrders.size > 0 && (
          <div className="mb-4 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700 rounded-lg p-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                {selectedOrders.size} order(s) selected
                {selectedPendingOrders.length > 0 && selectedPendingOrders.length !== selectedOrders.size && (
                  <span className="text-blue-600 dark:text-blue-300"> ({selectedPendingOrders.length} pending)</span>
                )}
              </span>
              <button
                onClick={clearSelection}
                className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                Clear selection
              </button>
              <button
                onClick={selectAllPending}
                className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                Select all pending
              </button>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleBulkMarkPaid}
                disabled={bulkProcessing || selectedPendingOrders.length === 0}
                className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold"
              >
                <Check className="w-4 h-4" />
                Mark Paid ({selectedPendingOrders.length})
              </button>
              <button
                onClick={handleBulkCancel}
                disabled={bulkProcessing || selectedPendingOrders.length === 0}
                className="flex items-center gap-2 bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold"
              >
                <X className="w-4 h-4" />
                Cancel ({selectedPendingOrders.length})
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="text-center py-12 dark:text-white">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : (
          <>
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-800">
                  <tr>
                    <th className="px-4 py-3 text-left">
                      <button
                        onClick={toggleSelectAll}
                        className="flex items-center justify-center w-6 h-6 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                      >
                        {isAllSelected ? (
                          <CheckSquare className="w-5 h-5 text-blue-600" />
                        ) : isSomeSelected ? (
                          <div className="w-5 h-5 border-2 border-blue-600 rounded flex items-center justify-center">
                            <div className="w-2 h-2 bg-blue-600 rounded-sm"></div>
                          </div>
                        ) : (
                          <Square className="w-5 h-5 text-gray-400" />
                        )}
                      </button>
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Order ID</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Customer</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Items</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Total</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Payment</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                  {paginatedOrders.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                        No orders found matching your filters
                      </td>
                    </tr>
                  ) : (
                    paginatedOrders.map((order) => (
                      <tr 
                        key={order.id} 
                        className={`hover:bg-gray-50 dark:hover:bg-gray-800 ${
                          selectedOrders.has(order.id) ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                        }`}
                      >
                        <td className="px-4 py-4">
                          <button
                            onClick={() => toggleSelectOrder(order.id)}
                            className="flex items-center justify-center w-6 h-6 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                          >
                            {selectedOrders.has(order.id) ? (
                              <CheckSquare className="w-5 h-5 text-blue-600" />
                            ) : (
                              <Square className="w-5 h-5 text-gray-400" />
                            )}
                          </button>
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm font-mono text-gray-900 dark:text-white">
                          #{order.id.substring(0, 8)}
                        </td>
                        <td className="px-4 py-4">
                          <div className="text-sm">
                            <div className="font-medium text-gray-900 dark:text-white">{order.customer_name}</div>
                            <div className="text-gray-500 dark:text-gray-400">{order.customer_email}</div>
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <div className="text-sm text-gray-900 dark:text-white">
                            {order.items?.map((item, idx) => (
                              <div key={idx}>{item.product_name} ({item.term_months}m)</div>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm font-semibold text-gray-900 dark:text-white">
                          ${order.total?.toFixed(2)}
                        </td>
                        {/* CMTV local change 2026-09-25: how it was (or will be) paid; pending orders can be corrected */}
                        <td className="px-4 py-4 whitespace-nowrap">
                          {order.status === 'pending' ? (
                            <select
                              value={paidBy[order.id] || order.payment_method || 'manual'}
                              onChange={(e) => setPaidBy({ ...paidBy, [order.id]: e.target.value })}
                              title="How the customer paid (used when you click Paid)"
                              className="text-xs rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white px-2 py-1"
                              data-testid={`paid-by-${order.id}`}
                            >
                              {[...new Set([order.payment_method || 'manual', ...ADMIN_PAID_BY])].map((m) => (
                                <option key={m} value={m}>{PAYMENT_LABELS[m] || m}</option>
                              ))}
                            </select>
                          ) : (
                            <PaymentBadge order={order} />
                          )}
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap">
                          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                            order.status === 'paid' ? 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200' : 
                            order.status === 'pending' ? 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200' :
                            order.status === 'cancelled' ? 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200' :
                            'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200'
                          }`}>
                            {order.status}
                          </span>
                          {/* CMTV local change 2026-09-24: paid but the panel line wasn't created/extended (bug report 2.3) */}
                          {order.status === 'paid' && ['failed', 'partial'].includes(order.provisioning_status) && (
                            <span
                              title={(order.provisioning_errors || []).join('\n')}
                              className="ml-2 px-2 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 cursor-help"
                            >
                              ⚠ {order.provisioning_status === 'partial' ? 'Partly provisioned' : 'Not provisioned'}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">
                          {formatDate(order.created_at)}
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap">
                          {order.status === 'pending' ? (
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => handleMarkPaid(order.id)}
                                disabled={markPaidMutation.isPending}
                                className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm font-semibold"
                              >
                                <Check className="w-4 h-4" />
                                Paid
                              </button>
                              <button
                                onClick={() => handleCancelOrder(order.id)}
                                disabled={cancelOrderMutation.isPending}
                                className="flex items-center gap-1 bg-red-600 text-white px-3 py-1.5 rounded-lg hover:bg-red-700 disabled:opacity-50 text-sm font-semibold"
                              >
                                <X className="w-4 h-4" />
                                Cancel
                              </button>
                              <button onClick={() => handleDeleteOrder(order.id)} title="Delete order"
                                className="text-gray-400 hover:text-red-500 transition">
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          ) : order.status === 'paid' ? (
                            <div className="flex items-center gap-2">
                              <span className="text-green-600 dark:text-green-400 font-semibold text-sm">Processed</span>
                              <button onClick={() => handleDeleteOrder(order.id)} title="Delete order"
                                className="text-gray-400 hover:text-red-500 transition" data-testid={`delete-order-${order.id}`}>
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          ) : order.status === 'cancelled' ? (
                            <div className="flex items-center gap-2">
                              <span className="text-red-600 dark:text-red-400 font-semibold text-sm">Cancelled</span>
                              <button onClick={() => handleDeleteOrder(order.id)} title="Delete order"
                                className="text-gray-400 hover:text-red-500 transition" data-testid={`delete-order-${order.id}`}>
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          ) : (
                            <span className="text-gray-500 text-sm">{order.status}</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {totalOrders > 0 && (
              <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-4 bg-white dark:bg-gray-900 rounded-lg shadow px-6 py-4">
                {/* Page Size Selector */}
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-600 dark:text-gray-400">Show</span>
                  <select
                    value={pageSize}
                    onChange={(e) => setPageSize(Number(e.target.value))}
                    className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-blue-500"
                  >
                    <option value={10}>10</option>
                    <option value={15}>15</option>
                    <option value={20}>20</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                  <span className="text-sm text-gray-600 dark:text-gray-400">per page</span>
                </div>

                {/* Page Info */}
                <div className="text-sm text-gray-600 dark:text-gray-400">
                  Page {currentPage} of {totalPages} ({totalOrders} total orders)
                </div>

                {/* Page Navigation */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCurrentPage(1)}
                    disabled={currentPage === 1}
                    className="px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    First
                  </button>
                  <button
                    onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                    disabled={currentPage === 1}
                    className="p-2 text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="w-5 h-5" />
                  </button>
                  
                  {/* Page Numbers */}
                  <div className="flex items-center gap-1">
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      let pageNum;
                      if (totalPages <= 5) {
                        pageNum = i + 1;
                      } else if (currentPage <= 3) {
                        pageNum = i + 1;
                      } else if (currentPage >= totalPages - 2) {
                        pageNum = totalPages - 4 + i;
                      } else {
                        pageNum = currentPage - 2 + i;
                      }
                      
                      return (
                        <button
                          key={pageNum}
                          onClick={() => setCurrentPage(pageNum)}
                          className={`w-10 h-10 text-sm font-medium rounded-lg transition ${
                            currentPage === pageNum
                              ? 'bg-blue-600 text-white'
                              : 'text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700'
                          }`}
                        >
                          {pageNum}
                        </button>
                      );
                    })}
                  </div>

                  <button
                    onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                    disabled={currentPage === totalPages}
                    className="p-2 text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronRight className="w-5 h-5" />
                  </button>
                  <button
                    onClick={() => setCurrentPage(totalPages)}
                    disabled={currentPage === totalPages}
                    className="px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Last
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
