import FormattedText from '../components/cmtv/FormattedText'; // CMTV local change 2026-09-24
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { productsAPI } from '../api/api';
import { useAuthStore, useCartStore } from '../store/store';
import { useCurrencyStore } from '../store/currency';
import { ShoppingCart, ArrowLeft, Tv, Users } from 'lucide-react';

export default function ProductsPage() {
  const { user } = useAuthStore();
  const { items, addItem } = useCartStore();
  const { data: products, isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: async () => {
      const response = await productsAPI.getAll();
      return response.data;
    },
  });

  const handleAddToCart = (product, termMonths, price) => {
    if (!user) {
      window.location.href = '/login';
      return;
    }

    addItem({
      product_id: product.id,
      product_name: product.name,
      term_months: termMonths,
      price: price,
      account_type: product.account_type,
    });
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">{/* CMTV local change 2026-09-24: dark background (headings were white on light grey) */}
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <Link to="/" className="flex items-center gap-2 text-gray-600 hover:text-blue-600">
              <ArrowLeft className="w-5 h-5" />
              Back to Home
            </Link>
            {items.length > 0 && (
              <Link
                to="/checkout"
                className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
              >
                <ShoppingCart className="w-5 h-5" />
                Cart ({items.length})
              </Link>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <h1 className="text-4xl font-bold text-gray-900 dark:text-white mb-8">All Products</h1>

        {isLoading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          </div>
        ) : (
          <div className="space-y-12">
            {/* Subscriber Packages */}
            {products?.filter(p => p.account_type !== 'reseller').length > 0 && (
              <div>
                <div className="flex items-center gap-3 mb-6">
                  <Tv className="w-6 h-6 text-blue-600" />
                  <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Subscription Plans</h2>
                </div>
                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
                  {products
                    ?.filter(p => p.account_type !== 'reseller')
                    .sort((a, b) => (a.display_order || 0) - (b.display_order || 0))
                    .map((product) => (
                      <ProductCard key={product.id} product={product} onAddToCart={handleAddToCart} />
                    ))}
                </div>
              </div>
            )}

            {/* Reseller Packages */}
            {products?.filter(p => p.account_type === 'reseller').length > 0 && (
              <div>
                <div className="flex items-center gap-3 mb-6">
                  <Users className="w-6 h-6 text-purple-600" />
                  <h2 className="text-2xl font-bold text-purple-900 dark:text-purple-300">Reseller Packages</h2>
                </div>
                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
                  {products
                    ?.filter(p => p.account_type === 'reseller')
                    .sort((a, b) => (a.display_order || 0) - (b.display_order || 0))
                    .map((product) => (
                      <ProductCard key={product.id} product={product} onAddToCart={handleAddToCart} />
                    ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function ProductCard({ product, onAddToCart }) {
  const { symbol } = useCurrencyStore();
  const isReseller = product.account_type === 'reseller';
  
  return (
    <div className={`bg-white dark:bg-gray-900 rounded-lg shadow-lg overflow-hidden ${isReseller ? 'border-2 border-purple-200 dark:border-purple-700' : ''}`}>
      <div className={`${isReseller ? 'bg-gradient-to-r from-purple-600 to-purple-700' : 'bg-gradient-to-r from-blue-600 to-blue-700'} p-6 text-white`}>
        <h3 className="text-2xl font-bold mb-2">{product.name}</h3>
        <FormattedText text={product.description} className={isReseller ? 'text-purple-100' : 'text-blue-100'} />
      </div>
      <div className="p-6">
        {product.account_type === 'subscriber' && (
          <div className="mb-4">
            <p className="text-sm text-gray-600">Max Connections: {product.max_connections}</p>
          </div>
        )}
        {product.account_type === 'reseller' && (
          <div className="mb-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              <span className="font-semibold">Reseller Credits:</span> {product.reseller_credits} credits
            </p>
          </div>
        )}
        <div className="space-y-3">
          {Object.entries(product.prices).map(([term, price]) => (
            <button
              key={term}
              onClick={() => onAddToCart(product, parseInt(term), price)}
              className="w-full flex justify-between items-center bg-gray-50 hover:bg-blue-50 dark:bg-gray-800 dark:hover:bg-blue-900 p-4 rounded-lg transition border border-gray-200 dark:border-gray-700 hover:border-blue-300"
            >
              <span className="font-semibold text-gray-900 dark:text-white">
                {product.account_type === 'reseller' ? 'Purchase' : `${term} ${parseInt(term) === 1 ? 'Month' : 'Months'}`}
              </span>
              <span className="text-2xl font-bold text-blue-600">{symbol}{price}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
