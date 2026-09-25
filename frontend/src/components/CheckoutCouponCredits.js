import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import api from '../api/api';
import { Tag, Wallet, Check, X } from 'lucide-react';
import { toast } from 'sonner';

const CheckoutCouponCredits = ({ subtotal, onDiscountChange, onCreditsChange }) => {
  const [couponCode, setCouponCode] = useState('');
  const [appliedCoupon, setAppliedCoupon] = useState(null);
  const [useCredits, setUseCredits] = useState(false);
  const [creditAmount, setCreditAmount] = useState(0);

  const { data: balance } = useQuery({
    queryKey: ['credit-balance'],
    queryFn: async () => {
      const response = await api.get('/api/credits/balance');
      return response.data;
    },
  });

  const validateCouponMutation = useMutation({
    mutationFn: (code) => api.post('/api/coupon/validate', { code, order_total: subtotal }),
    onSuccess: (response) => {
      if (response.data.valid) {
        setAppliedCoupon(response.data);
        onDiscountChange(response.data.discount, response.data.code);
        toast.info(`Coupon applied! $${response.data.discount} discount`);
      } else {
        toast.error(response.data.error || 'Invalid coupon');
      }
    },
    onError: (error) => {
      toast.error('Coupon validation failed');
    },
  });

  const handleApplyCoupon = () => {
    if (!couponCode.trim()) return;
    validateCouponMutation.mutate(couponCode.toUpperCase());
  };

  const handleRemoveCoupon = () => {
    setAppliedCoupon(null);
    setCouponCode('');
    onDiscountChange(0, null);
  };

  const handleToggleCredits = (checked) => {
    setUseCredits(checked);
    if (checked) {
      const maxCredits = Math.min(balance?.balance || 0, subtotal - (appliedCoupon?.discount || 0));
      setCreditAmount(maxCredits);
      onCreditsChange(maxCredits);
    } else {
      setCreditAmount(0);
      onCreditsChange(0);
    }
  };

  const handleCreditAmountChange = (value) => {
    const maxCredits = Math.min(balance?.balance || 0, subtotal - (appliedCoupon?.discount || 0));
    const amount = Math.min(Math.max(0, parseFloat(value) || 0), maxCredits);
    setCreditAmount(amount);
    onCreditsChange(amount);
  };

  const availableCredits = balance?.balance || 0;

  return (
    <div className="space-y-4">
      {/* Coupon Section */}
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Tag className="w-5 h-5 text-blue-600" />
          <h3 className="font-semibold text-gray-900 dark:text-white">Discount Coupon</h3>
        </div>

        {appliedCoupon ? (
          <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Check className="w-5 h-5 text-green-600" />
                <div>
                  <p className="font-bold text-green-900 dark:text-green-200">{appliedCoupon.code}</p>
                  <p className="text-sm text-green-700 dark:text-green-300">-${appliedCoupon.discount.toFixed(2)} discount</p>
                </div>
              </div>
              <button
                onClick={handleRemoveCoupon}
                className="p-1 hover:bg-green-100 dark:hover:bg-green-800 rounded"
                data-testid="remove-coupon-btn"
              >
                <X className="w-4 h-4 text-green-600" />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <input
              type="text"
              value={couponCode}
              onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
              placeholder="Enter coupon code"
              className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="coupon-input"
            />
            <button
              onClick={handleApplyCoupon}
              disabled={!couponCode.trim() || validateCouponMutation.isLoading}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              data-testid="apply-coupon-btn"
            >
              {validateCouponMutation.isLoading ? 'Checking...' : 'Apply'}
            </button>
          </div>
        )}
      </div>

      {/* Credits Section */}
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Wallet className="w-5 h-5 text-green-600" />
          <h3 className="font-semibold text-gray-900 dark:text-white">Use Credits</h3>
          <span className="ml-auto text-sm text-gray-600 dark:text-gray-400">
            Available: <span className="font-bold text-green-600">${availableCredits.toFixed(2)}</span>
          </span>
        </div>

        {availableCredits > 0 ? (
          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={useCredits}
                onChange={(e) => handleToggleCredits(e.target.checked)}
                className="w-5 h-5 text-blue-600 rounded"
                data-testid="use-credits-toggle"
              />
              <span className="text-gray-900 dark:text-white">Apply credits to this order</span>
            </label>

            {useCredits && (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="0"
                    max={Math.min(availableCredits, subtotal - (appliedCoupon?.discount || 0))}
                    step="0.01"
                    value={creditAmount}
                    onChange={(e) => handleCreditAmountChange(e.target.value)}
                    className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                    data-testid="credit-amount-input"
                  />
                  <button
                    onClick={() => {
                      const max = Math.min(availableCredits, subtotal - (appliedCoupon?.discount || 0));
                      setCreditAmount(max);
                      onCreditsChange(max);
                    }}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 whitespace-nowrap"
                    data-testid="use-max-credits-btn"
                  >
                    Use Max
                  </button>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Max: ${Math.min(availableCredits, subtotal - (appliedCoupon?.discount || 0)).toFixed(2)}
                </p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            You don't have any credits yet. Refer friends to earn credits!{/* CMTV local change 2026-09-25: was a hard-coded $10 */}
          </p>
        )}
      </div>
    </div>
  );
};

export default CheckoutCouponCredits;
