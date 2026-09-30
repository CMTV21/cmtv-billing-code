import React, { useEffect, useRef } from 'react';
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { physicalItemsAPI } from '../api/api';
import { useAuthStore, useCartStore } from '../store/store';
import { ShoppingCart, ArrowLeft } from 'lucide-react';
import { PhysicalItemCard } from '../components/PhysicalItemCard';

export default function OrderItemPage() {
  const { itemId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { items, addItem, clearCart } = useCartStore();
  const autoAdded = useRef(false);
  const qty = Math.max(1, parseInt(params.get('qty') || '1', 10) || 1);

  const { data: item, isLoading, error } = useQuery({
    queryKey: ['physical-item', itemId],
    queryFn: async () => (await physicalItemsAPI.getOne(itemId)).data,
    retry: false,
  });

  useEffect(() => {
    if (!item || autoAdded.current) return;
    if (!user) { navigate(`/login?redirect=/order/item/${itemId}${qty > 1 ? `?qty=${qty}` : ''}`); return; }
    if (!item.in_stock) return;
    const quantity = item.track_stock ? Math.min(qty, item.stock_quantity) : qty;
    clearCart();
    addItem({ product_id: item.id, product_name: item.name, price: item.price, account_type: 'physical', item_type: 'physical', quantity, image: item.images?.[0] || '' });
    autoAdded.current = true;
    navigate('/checkout');
  }, [item, user, itemId, qty, navigate, addItem, clearCart]);

  if (isLoading) {
    return <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" /></div>;
  }
  if (error || !item) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center" data-testid="order-item-not-found">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Item Not Found</h1>
          <p className="text-gray-600 dark:text-gray-400 mb-4">This item may no longer be available.</p>
          <Link to="/" className="text-blue-600 hover:underline">Back to store</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950" data-testid="order-item-page">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <Link to="/" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600"><ArrowLeft className="w-5 h-5" /> Back to store</Link>
          {items.length > 0 && (
            <Link to="/checkout" className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"><ShoppingCart className="w-5 h-5" /> Cart ({items.length})</Link>
          )}
        </div>
      </header>
      <main className="max-w-md mx-auto px-4 py-12">
        <PhysicalItemCard item={item} />
        {!user && (
          <p className="mt-6 text-sm text-center text-yellow-800 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <Link to={`/login?redirect=/order/item/${itemId}`} className="font-semibold underline">Log in</Link> or <Link to="/register" className="font-semibold underline">create an account</Link> to complete your purchase.
          </p>
        )}
      </main>
    </div>
  );
}
