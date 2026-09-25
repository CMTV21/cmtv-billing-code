import FormattedText from '../components/cmtv/FormattedText'; // CMTV local change 2026-09-24
import React, { useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { productsAPI } from '../api/api';
import { useAuthStore, useCartStore } from '../store/store';
import { ShoppingCart, ArrowLeft, Tv, Users, Check } from 'lucide-react';

export default function OrderProductPage() {
  const { productId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { items, addItem, clearCart } = useCartStore();
  const autoAdded = useRef(false);

  const { data: product, isLoading, error } = useQuery({
    queryKey: ['product', productId],
    queryFn: async () => {
      const response = await productsAPI.getOne(productId);
      return response.data;
    },
  });

  // Auto-add to cart and redirect to checkout
  useEffect(() => {
    if (!product || autoAdded.current) return;
    
    const prices = Object.entries(product.prices || {});
    if (prices.length === 0) return;
    
    // If not logged in, redirect to login with redirect back
    if (!user) {
      navigate(`/login?redirect=/order/${productId}`);
      return;
    }

    // Clear cart and add this product with the first price option
    const [term, price] = prices[0];
    clearCart();
    addItem({
      product_id: product.id,
      product_name: product.name,
      term_months: parseInt(term),
      price: parseFloat(price),
      account_type: product.account_type,
    });
    autoAdded.current = true;
    navigate('/checkout');
  }, [product, user, productId, navigate, addItem, clearCart]);

  const handleAddToCart = (termMonths, price) => {
    if (!user) {
      navigate(`/login?redirect=/order/${productId}`);
      return;
    }
    clearCart();
    addItem({
      product_id: product.id,
      product_name: product.name,
      term_months: termMonths,
      price: price,
      account_type: product.account_type,
    });
    navigate('/checkout');
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Product Not Found</h1>
          <p className="text-gray-600 mb-4">This product may no longer be available.</p>
          <Link to="/products" className="text-blue-600 hover:underline">View all products</Link>
        </div>
      </div>
    );
  }

  const isReseller = product.account_type === 'reseller';

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">{/* CMTV local change 2026-09-24: dark background */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <Link to="/products" className="flex items-center gap-2 text-gray-600 hover:text-blue-600">
              <ArrowLeft className="w-5 h-5" />
              All Products
            </Link>
            {items.length > 0 && (
              <Link to="/checkout" className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
                <ShoppingCart className="w-5 h-5" />
                Cart ({items.length})
              </Link>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
          {/* Header */}
          <div className={`${isReseller ? 'bg-gradient-to-r from-purple-600 to-purple-700' : 'bg-gradient-to-r from-blue-600 to-blue-700'} p-8 text-white`}>
            <div className="flex items-center gap-3 mb-3">
              {isReseller ? <Users className="w-7 h-7" /> : <Tv className="w-7 h-7" />}
              <span className="text-sm font-medium uppercase tracking-wider opacity-80">
                {isReseller ? 'Reseller Package' : 'Subscription Plan'}
              </span>
            </div>
            <h1 className="text-3xl font-bold mb-2">{product.name}</h1>
            <FormattedText text={product.description} className={`${isReseller ? 'text-purple-100' : 'text-blue-100'} text-lg`} />
          </div>

          {/* Details */}
          <div className="p-8">
            {/* Features */}
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">What's Included</h2>
              <div className="grid grid-cols-2 gap-3">
                {product.account_type === 'subscriber' && (
                  <>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>{product.max_connections} Connection{product.max_connections > 1 ? 's' : ''}</span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>Full Channel Access</span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>All Devices Supported</span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>24/7 Support</span>
                    </div>
                  </>
                )}
                {product.account_type === 'reseller' && (
                  <>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>{product.reseller_credits} Credits</span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>Reseller Panel Access</span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>Lifetime Access</span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-700">
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                      <span>Create & Manage Lines</span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Pricing / Order Buttons */}
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                {isReseller ? 'Order Now' : 'Choose Your Plan'}
              </h2>
              <div className="space-y-3">
                {Object.entries(product.prices).map(([term, price]) => (
                  <button
                    key={term}
                    onClick={() => handleAddToCart(parseInt(term), price)}
                    className={`w-full flex justify-between items-center p-5 rounded-xl transition border-2 ${
                      isReseller
                        ? 'bg-purple-50 hover:bg-purple-100 border-purple-200 hover:border-purple-400'
                        : 'bg-blue-50 hover:bg-blue-100 border-blue-200 hover:border-blue-400'
                    }`}
                  >
                    <div className="text-left">
                      <span className="font-bold text-gray-900 text-lg">
                        {isReseller ? 'Purchase Now' : `${term} ${parseInt(term) === 1 ? 'Month' : 'Months'}`}
                      </span>
                      {!isReseller && (
                        <p className="text-sm text-gray-500 mt-0.5">
                          ${(price / parseInt(term)).toFixed(2)}/month
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <span className={`text-3xl font-bold ${isReseller ? 'text-purple-600' : 'text-blue-600'}`}>
                        ${price}
                      </span>
                      {isReseller && <p className="text-xs text-gray-500">one-time</p>}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {!user && (
              <div className="mt-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
                <p className="text-sm text-yellow-800">
                  You'll need to <Link to={`/login?redirect=/order/${productId}`} className="font-semibold underline">log in</Link> or{' '}
                  <Link to="/register" className="font-semibold underline">create an account</Link> to complete your purchase.
                </p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
