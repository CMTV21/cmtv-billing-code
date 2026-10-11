import { formatDate } from "../utils/timezone";
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import axios from 'axios';
import { ArrowLeft, Search, Plus, FileText, Trash2, CheckCircle, X, Edit, Download, Eye } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const getToken = () => JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;

export default function AdminInvoices() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editInvoice, setEditInvoice] = useState(null);

  const { data: invoices, isLoading } = useQuery({
    queryKey: ['admin-invoices', statusFilter],
    queryFn: async () => {
      const res = await axios.get(`${API_URL}/api/admin/invoices?status=${statusFilter}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      return res.data;
    },
  });

  const filtered = (invoices || []).filter(inv => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (inv.invoice_number || '').toLowerCase().includes(s) ||
      (inv.customer_name || '').toLowerCase().includes(s) ||
      (inv.customer_email || '').toLowerCase().includes(s) ||
      (inv.line_username || '').toLowerCase().includes(s) ||
      (inv.order_id || '').toLowerCase().includes(s);
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => axios.delete(`${API_URL}/api/admin/invoices/${id}`, { headers: { Authorization: `Bearer ${getToken()}` } }),
    onSuccess: () => { queryClient.invalidateQueries(['admin-invoices']); toast.success('Invoice deleted'); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => axios.put(`${API_URL}/api/admin/invoices/${id}`, data, { headers: { Authorization: `Bearer ${getToken()}` } }),
    onSuccess: () => { queryClient.invalidateQueries(['admin-invoices']); toast.success('Invoice updated'); setEditInvoice(null); },
  });

  const handleDownloadPdf = async (invoiceId, invoiceNumber) => {
    try {
      const res = await axios.get(`${API_URL}/api/admin/invoices/${invoiceId}/pdf`, {
        headers: { Authorization: `Bearer ${getToken()}` },
        responseType: 'blob'
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${invoiceNumber || 'invoice'}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch { toast.error('Failed to download PDF'); }
  };

  const handleViewPdf = async (invoiceId) => {
    try {
      const res = await axios.get(`${API_URL}/api/admin/invoices/${invoiceId}/pdf`, {
        headers: { Authorization: `Bearer ${getToken()}` },
        responseType: 'blob'
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      window.open(url, '_blank');
    } catch { toast.error('Failed to view PDF'); }
  };

  const statusColors = {
    paid: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    cancelled: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    overdue: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <Link to="/admin" className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">Invoices</h1>
            <p className="text-gray-600 dark:text-gray-400 text-sm mt-1">Manage all customer invoices</p>
            </div>
          </div>
          <button onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-semibold"
            data-testid="create-invoice-btn">
            <Plus className="w-4 h-4" /> Create Invoice
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search by invoice #, customer, email, username, order ID..."
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
              data-testid="invoice-search" />
          </div>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm">
            <option value="">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="paid">Paid</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-gray-200 dark:border-gray-700">
            <div className="text-xs text-gray-500">Total</div>
            <div className="text-lg font-bold text-gray-900 dark:text-white">{(invoices || []).length}</div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-gray-200 dark:border-gray-700">
            <div className="text-xs text-gray-500">Paid</div>
            <div className="text-lg font-bold text-green-600">{(invoices || []).filter(i => i.status === 'paid').length}</div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-gray-200 dark:border-gray-700">
            <div className="text-xs text-gray-500">Pending</div>
            <div className="text-lg font-bold text-yellow-600">{(invoices || []).filter(i => i.status === 'pending').length}</div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-gray-200 dark:border-gray-700">
            <div className="text-xs text-gray-500">Revenue</div>
            <div className="text-lg font-bold text-blue-600">${(invoices || []).filter(i => i.status === 'paid').reduce((sum, i) => sum + (i.total || 0), 0).toFixed(2)}</div>
          </div>
        </div>

        {/* Table (desktop) */}
        {isLoading ? (
          <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>
        ) : (
          <>
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="overflow-x-auto hidden md:block">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700" data-testid="invoices-table">
                  <thead className="bg-gray-50 dark:bg-gray-900">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Invoice #</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Username</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Amount</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Due</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {filtered.map(inv => (
                      <tr key={inv.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                        <td className="px-4 py-3 text-sm font-mono text-gray-900 dark:text-white">{inv.invoice_number}</td>
                        <td className="px-4 py-3">
                          <div className="text-sm text-gray-900 dark:text-white">{inv.customer_name}</div>
                          <div className="text-xs text-gray-500">{inv.customer_email}</div>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300 font-mono">{inv.line_username || '-'}</td>
                        <td className="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-white">${inv.total?.toFixed(2)}</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 text-xs font-semibold rounded-full ${statusColors[inv.status] || 'bg-gray-100 text-gray-800'}`}>{inv.status}</span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">{inv.created_at ? formatDate(inv.created_at) : '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{inv.due_date ? formatDate(inv.due_date) : '-'}</td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center gap-2 justify-end">
                            <button onClick={() => handleViewPdf(inv.id)} className="text-gray-500 hover:text-blue-600" title="View PDF"><Eye className="w-4 h-4" /></button>
                            <button onClick={() => handleDownloadPdf(inv.id, inv.invoice_number)} className="text-gray-500 hover:text-blue-600" title="Download PDF"><Download className="w-4 h-4" /></button>
                            {inv.status === 'pending' && (
                              <button onClick={() => updateMutation.mutate({ id: inv.id, data: { status: 'paid' } })}
                                className="text-green-600 hover:text-green-800" title="Mark paid"><CheckCircle className="w-4 h-4" /></button>
                            )}
                            <button onClick={() => setEditInvoice(inv)} className="text-blue-600 hover:text-blue-800" title="Edit"><Edit className="w-4 h-4" /></button>
                            {/* CMTV 2026-10-11: Delete removed (permanent; the owner's rule is to cancel/retire instead) */}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr><td colSpan="8" className="px-4 py-8 text-center text-gray-500">No invoices found</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden divide-y divide-gray-200 dark:divide-gray-700">
                {filtered.map(inv => (
                  <div key={inv.id} className="p-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-sm font-mono font-semibold text-gray-900 dark:text-white">{inv.invoice_number}</div>
                        <div className="text-xs text-gray-500">{inv.customer_name} {inv.customer_email ? `(${inv.customer_email})` : ''}</div>
                        {inv.line_username && <div className="text-xs text-gray-400 font-mono mt-0.5">{inv.line_username}</div>}
                      </div>
                      <span className={`px-2 py-0.5 text-xs font-semibold rounded-full ${statusColors[inv.status] || 'bg-gray-100'}`}>{inv.status}</span>
                    </div>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="font-bold text-gray-900 dark:text-white">${inv.total?.toFixed(2)}</span>
                      <div className="flex gap-2">
                        <button onClick={() => handleViewPdf(inv.id)} className="text-xs text-gray-500">View PDF</button>
                        <button onClick={() => handleDownloadPdf(inv.id, inv.invoice_number)} className="text-xs text-blue-600">Download</button>
                        {inv.status === 'pending' && <button onClick={() => updateMutation.mutate({ id: inv.id, data: { status: 'paid' } })} className="text-xs text-green-600">Mark Paid</button>}
                        <button onClick={() => setEditInvoice(inv)} className="text-xs text-blue-600">Edit</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </main>

      {/* Create Invoice Modal */}
      {showCreateModal && <CreateInvoiceModal onClose={() => setShowCreateModal(false)} onCreated={() => { queryClient.invalidateQueries(['admin-invoices']); setShowCreateModal(false); }} />}

      {/* Edit Invoice Modal */}
      {editInvoice && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setEditInvoice(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Edit Invoice</h3>
              <button onClick={() => setEditInvoice(null)} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
            </div>
            <EditInvoiceForm invoice={editInvoice} onSave={(data) => updateMutation.mutate({ id: editInvoice.id, data })} />
          </div>
        </div>
      )}
    </div>
  );
}

function EditInvoiceForm({ invoice, onSave }) {
  const [status, setStatus] = useState(invoice.status);
  const [amount, setAmount] = useState(invoice.total || 0);
  const [description, setDescription] = useState(invoice.description || '');
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Status</label>
        <select value={status} onChange={e => setStatus(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm">
          <option value="pending">Pending</option>
          <option value="paid">Paid</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Amount</label>
        <input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
        <input type="text" value={description} onChange={e => setDescription(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" />
      </div>
      <button onClick={() => onSave({ status, amount: parseFloat(amount), description })}
        className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 text-sm font-semibold">Save Changes</button>
    </div>
  );
}

function CreateInvoiceModal({ onClose, onCreated }) {
  const [userId, setUserId] = useState('');
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [status, setStatus] = useState('pending');
  const [sendEmail, setSendEmail] = useState(true);
  const [search, setSearch] = useState('');
  const [users, setUsers] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [creating, setCreating] = useState(false);

  const searchUsers = async (q) => {
    setSearch(q);
    if (q.length < 2) { setUsers([]); return; }
    try {
      const res = await axios.get(`${API_URL}/api/admin/customers?search=${q}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setUsers((res.data || []).slice(0, 10));
    } catch { setUsers([]); }
  };

  const handleCreate = async () => {
    if (!userId || !amount) { toast.error('Select a customer and enter amount'); return; }
    setCreating(true);
    try {
      await axios.post(`${API_URL}/api/admin/invoices`, {
        user_id: userId, amount: parseFloat(amount), description, due_date: dueDate, status, send_email: sendEmail
      }, { headers: { Authorization: `Bearer ${getToken()}` } });
      toast.success('Invoice created');
      onCreated();
    } catch (err) { toast.error(err.response?.data?.detail || 'Failed to create'); }
    setCreating(false);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Create Invoice</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Customer *</label>
            {selectedUser ? (
              <div className="flex items-center justify-between p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg">
                <div><div className="text-sm font-medium">{selectedUser.name}</div><div className="text-xs text-gray-500">{selectedUser.email}</div></div>
                <button onClick={() => { setSelectedUser(null); setUserId(''); setSearch(''); }} className="text-gray-400"><X className="w-4 h-4" /></button>
              </div>
            ) : (
              <div className="relative">
                <input type="text" value={search} onChange={e => searchUsers(e.target.value)} placeholder="Search customer..."
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" />
                {users.length > 0 && (
                  <div className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-800 border rounded-lg shadow-lg max-h-40 overflow-y-auto">
                    {users.map(u => (
                      <button key={u.id} onClick={() => { setUserId(u.id); setSelectedUser(u); setUsers([]); }}
                        className="w-full text-left px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 text-sm">
                        <div className="font-medium">{u.name}</div><div className="text-xs text-gray-500">{u.email}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Amount *</label>
              <input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00"
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Due Date</label>
              <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <input type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="Service credits, custom work, etc."
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Status</label>
            <select value={status} onChange={e => setStatus(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm">
              <option value="pending">Pending</option>
              <option value="paid">Paid</option>
            </select>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}
              className="w-4 h-4 text-blue-600 rounded" />
            <span className="text-sm text-gray-700 dark:text-gray-300">Send invoice email to customer</span>
          </label>
          <button onClick={handleCreate} disabled={creating}
            className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 text-sm font-semibold disabled:opacity-50">
            {creating ? 'Creating...' : 'Create Invoice'}
          </button>
        </div>
      </div>
    </div>
  );
}
