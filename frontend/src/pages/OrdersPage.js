import { formatDate } from "../utils/timezone";
import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ordersAPI } from '../api/api';
import { ArrowLeft, ShoppingBag, Clock, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

export default function OrdersPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const returnedOrderId = searchParams.get('payment') === 'ghostpay' ? searchParams.get('order_id') : null;
  const [checkingPayment, setCheckingPayment] = useState(!!returnedOrderId);

  const { data: orders, isLoading } = useQuery({
    queryKey: ['orders'],
    queryFn: async () => {
      const response = await ordersAPI.getAll();
      return response.data;
    },
  });

  // Returning from GhostPay: re-check the invoice a few times so the order flips to paid without waiting for the webhook
  useEffect(() => {
    if (!returnedOrderId) return;
    let attempts = 0;
    let cancelled = false;
    const check = async () => {
      attempts += 1;
      try {
        const res = await ordersAPI.checkGhostPay(returnedOrderId);
        if (cancelled) return;
        if (res.data.order_status === 'paid') {
          toast.success('Crypto payment confirmed! Your service is being activated.');
          queryClient.invalidateQueries(['orders']);
          setCheckingPayment(false);
          setSearchParams({}, { replace: true });
          return;
        }
      } catch (e) { /* keep polling */ }
      if (attempts < 12) {
        setTimeout(check, 5000);
      } else {
        setCheckingPayment(false);
        toast.info('Payment not confirmed yet. We keep checking in the background and will activate your order automatically once it confirms.');
      }
    };
    check();
    return () => { cancelled = true; };
  }, [returnedOrderId, queryClient, setSearchParams]);

  const getStatusIcon = (status) => {
    switch (status) {
      case 'paid':
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-600" />;
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-600" />;
      default:
        return <Clock className="w-5 h-5 text-gray-600 dark:text-gray-400" />;
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'paid':
        return 'bg-green-100 text-green-800';
      case 'pending':
        return 'bg-yellow-100 text-yellow-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/dashboard" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600">
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white mb-4 sm:mb-8">My Orders</h1>

        {checkingPayment && (
          <div className="mb-6 flex items-center gap-3 bg-purple-50 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-800 text-purple-800 dark:text-purple-200 rounded-lg px-4 py-3" data-testid="ghostpay-confirming-banner">
            <Loader2 className="w-5 h-5 animate-spin shrink-0" />
            <p className="text-sm">Confirming your crypto payment with GhostPay… your order will activate automatically once the payment is confirmed.</p>
          </div>
        )}

        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : orders?.length === 0 ? (
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
            <ShoppingBag className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">No orders yet</h3>
            <p className="text-gray-600 mb-6">Start shopping to see your orders here</p>
            <Link to="/" className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700">
              Browse Products
            </Link>
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
            {/* Desktop table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-800">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Order</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Items</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Total</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {orders?.map((order) => (
                    <tr key={order.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900 dark:text-white">#{order.id.substring(0, 8)}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{formatDate(order.created_at)}</td>
                      <td className="px-4 py-3 text-sm text-gray-900 dark:text-white">
                        {order.items.map((item, idx) => <div key={idx}>{item.product_name}</div>)}
                      </td>
                      <td className="px-4 py-3 text-sm font-semibold">${order.total.toFixed(2)}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 text-xs font-semibold rounded-full ${
                          order.status === 'paid' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' :
                          order.status === 'pending' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' :
                          'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                        }`}>{order.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Mobile cards */}
            <div className="sm:hidden divide-y divide-gray-200 dark:divide-gray-700">
              {orders?.map((order) => (
                <div key={order.id} className="p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-sm font-mono font-semibold text-gray-900 dark:text-white">#{order.id.substring(0, 8)}</span>
                      <span className="text-xs text-gray-500 ml-2">{formatDate(order.created_at)}</span>
                    </div>
                    <span className={`px-2 py-0.5 text-xs font-semibold rounded-full ${
                      order.status === 'paid' ? 'bg-green-100 text-green-800' :
                      order.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                      'bg-red-100 text-red-800'
                    }`}>{order.status}</span>
                  </div>
                  <div className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                    {order.items.map((item, idx) => <span key={idx}>{item.product_name}{idx < order.items.length - 1 ? ', ' : ''}</span>)}
                  </div>
                  <div className="mt-1 text-sm font-bold text-gray-900 dark:text-white">${order.total.toFixed(2)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {orders?.some((o) => o.status === 'pending') && (
          <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-sm text-blue-800">
              <strong>Pending orders:</strong> Please contact support to complete payment for pending orders.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
