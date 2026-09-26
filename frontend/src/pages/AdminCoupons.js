import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { ArrowLeft, Plus, Tag, Trash2, Calendar, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';

export default function AdminCoupons() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [formData, setFormData] = useState({
    code: '',
    coupon_type: 'percentage',
    value: 0,
    min_purchase: 0,
    max_uses: null,
    valid_until: '',
    applies_to: 'all',
    product_ids: []
  });

  const { data: coupons, isLoading } = useQuery({
    queryKey: ['coupons'],
    queryFn: async () => {
      const response = await adminAPI.getCoupons();
      return response.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: (data) => adminAPI.createCoupon(data),
    onSuccess: () => {
      queryClient.invalidateQueries(['coupons']);
      setShowModal(false);
      resetForm();
      toast.success('Coupon created successfully!');
    },
    onError: (error) => {
      toast.error('Error: ' + (error.response?.data?.detail || 'Failed to create coupon'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => adminAPI.deleteCoupon(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['coupons']);
      toast.success('Coupon deleted'); // CMTV local change 2026-09-26: delete really removes it now
    },
    onError: () => toast.error("Couldn't delete that coupon"),
  });

  const resetForm = () => {
    setFormData({
      code: '',
      coupon_type: 'percentage',
      value: 0,
      min_purchase: 0,
      max_uses: null,
      valid_until: '',
      applies_to: 'all',
      product_ids: []
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    createMutation.mutate(formData);
  };

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
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">Coupon Management</h1>
            <p className="text-gray-600 dark:text-gray-400">Create and manage discount coupons</p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            data-testid="create-coupon-btn"
          >
            <Plus className="w-5 h-5" />
            Create Coupon
          </button>
        </div>

        {/* Coupons List */}
        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {coupons?.map((coupon) => (
              <div key={coupon.id} className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Tag className="w-5 h-5 text-blue-600" />
                    <code className="text-xl font-bold text-gray-900 dark:text-white">
                      {coupon.code}
                    </code>
                  </div>
                  <span className={`px-2 py-1 rounded text-xs font-semibold ${
                    coupon.active 
                      ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' 
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {coupon.active ? 'Active' : 'Inactive'}
                  </span>
                </div>

                <div className="space-y-2 mb-4">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600 dark:text-gray-400">Discount:</span>
                    <span className="font-semibold text-gray-900 dark:text-white">
                      {coupon.coupon_type === 'percentage' ? `${coupon.value}%` : `$${coupon.value}`}
                    </span>
                  </div>
                  
                  {coupon.min_purchase > 0 && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600 dark:text-gray-400">Min Purchase:</span>
                      <span className="text-gray-900 dark:text-white">${coupon.min_purchase}</span>
                    </div>
                  )}
                  
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600 dark:text-gray-400">Used:</span>
                    <span className="text-gray-900 dark:text-white">
                      {coupon.usage_count || coupon.used_count || 0}
                      {coupon.max_uses && ` / ${coupon.max_uses}`}
                    </span>
                  </div>
                  
                  {coupon.total_discount > 0 && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600 dark:text-gray-400">Total Saved:</span>
                      <span className="font-semibold text-green-600">${coupon.total_discount.toFixed(2)}</span>
                    </div>
                  )}
                  
                  {coupon.valid_until && (
                    <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                      <Calendar className="w-4 h-4" />
                      Expires: {new Date(coupon.valid_until).toLocaleDateString()}
                    </div>
                  )}
                </div>

                <button
                  onClick={() => {
                    if (window.confirm(`Delete coupon ${coupon.code}? It stops working straight away. Orders that used it keep their discount history.`)) {
                      deleteMutation.mutate(coupon.id);
                    }
                  }}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-red-50 text-red-600 rounded-lg hover:bg-red-100"
                  data-testid={`delete-coupon-${coupon.code}`}
                >
                  <Trash2 className="w-4 h-4" />
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Create Modal */}
        {showModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
              <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                <h3 className="text-xl font-bold text-gray-900 dark:text-white">Create New Coupon</h3>
                <button onClick={() => { setShowModal(false); resetForm(); }} className="text-gray-500 hover:text-gray-700">
                  ✕
                </button>
              </div>

              <form onSubmit={handleSubmit} className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Coupon Code *</label>
                  <input
                    type="text"
                    required
                    value={formData.code}
                    onChange={(e) => setFormData({...formData, code: e.target.value.toUpperCase()})}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                    placeholder="SAVE20"
                    data-testid="coupon-code-input"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Type *</label>
                    <select
                      value={formData.coupon_type}
                      onChange={(e) => setFormData({...formData, coupon_type: e.target.value})}
                      className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                    >
                      <option value="percentage">Percentage</option>
                      <option value="fixed">Fixed Amount</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Value * {formData.coupon_type === 'percentage' ? '(%)' : '($)'}
                    </label>
                    <input
                      type="number"
                      required
                      min="0"
                      step="0.01"
                      value={formData.value}
                      onChange={(e) => setFormData({...formData, value: parseFloat(e.target.value)})}
                      className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                      placeholder="20"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Min Purchase ($)</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={formData.min_purchase}
                      onChange={(e) => setFormData({...formData, min_purchase: parseFloat(e.target.value)})}
                      className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Max Uses</label>
                    <input
                      type="number"
                      min="1"
                      value={formData.max_uses || ''}
                      onChange={(e) => setFormData({...formData, max_uses: e.target.value ? parseInt(e.target.value) : null})}
                      className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                      placeholder="Unlimited"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Expiry Date</label>
                  <input
                    type="date"
                    value={formData.valid_until}
                    onChange={(e) => setFormData({...formData, valid_until: e.target.value})}
                    min={new Date().toISOString().split('T')[0]}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                  />
                </div>

                <div className="flex gap-3 pt-4">
                  <button
                    type="button"
                    onClick={() => { setShowModal(false); resetForm(); }}
                    className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                    data-testid="submit-coupon-btn"
                  >
                    Create Coupon
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
