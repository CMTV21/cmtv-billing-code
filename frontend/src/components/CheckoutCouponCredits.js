import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../api/api';
import { Tag, Wallet, Check, X } from 'lucide-react';
import { toast } from 'sonner';

// CMTV local change 2026-10-16 (owner, batch 2): one small "Have a code?" box for a coupon, a gift card (CMTV-XXXX-XXXX-XXXX:
// redeemed to account credit, then used on this order) or a friend's referral code (POST /api/cmtv/referral/claim, new
// customers only). The credits box only shows when the customer has credit.
const GIFT_CODE = /^CMTV-?[A-Z0-9]{4}-?[A-Z0-9]{4}-?[A-Z0-9]{4}$/;
const errText = (e, fallback) => e?.response?.data?.detail || fallback;

const CheckoutCouponCredits = ({ subtotal, onDiscountChange, onCreditsChange }) => {
  const queryClient = useQueryClient();
  const [codeOpen, setCodeOpen] = useState(false);
  const [codeBusy, setCodeBusy] = useState(false);
  const [codeNote, setCodeNote] = useState('');
  const [useAfterGift, setUseAfterGift] = useState(false);
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
        const err = response.data.error || 'Invalid coupon';
        if (/not found/i.test(err)) tryReferral(); else toast.error(err);   // CMTV 2026-10-16: not a coupon: maybe a referral code
      }
    },
    onError: (error) => {
      toast.error('Coupon validation failed');
    },
  });

  // CMTV 2026-10-16: a friend's referral code
  const tryReferral = async () => {
    setCodeBusy(true);
    try {
      const { data } = await api.post('/api/cmtv/referral/claim', { code: couponCode.trim() });
      const min = Number(data.minimum || 0);
      setCodeNote(`Referral code added.${data.welcome_credit > 0 ? ` $${Number(data.welcome_credit).toFixed(2)} welcome credit is on your account.` : ''}`
        + (min > 0 ? ` Your friend gets their reward when your order is $${min % 1 ? min.toFixed(2) : min} or more.` : ''));
      setCouponCode('');
      if (data.welcome_credit > 0) { setUseAfterGift(true); queryClient.invalidateQueries({ queryKey: ['credit-balance'] }); }
      toast.success('Referral code added');
    } catch (e) {
      const msg = errText(e, '');
      toast.error(msg || "That code isn't a coupon, gift card or referral code we know. Check it and try again.");
    } finally {
      setCodeBusy(false);
    }
  };

  // CMTV 2026-10-16: a gift card code becomes account credit, used on this order
  const redeemGift = async (code) => {
    setCodeBusy(true);
    try {
      const { data } = await api.post('/api/cmtv/gifts/redeem', { code });
      setCodeNote(`Gift card added: $${Number(data.amount).toFixed(2)} credit${data.from_name ? ` from ${data.from_name}` : ''}, used on this order below.`);
      setCouponCode('');
      setUseAfterGift(true);
      await queryClient.invalidateQueries({ queryKey: ['credit-balance'] });
      toast.success('Gift card added to your credit');
    } catch (e) {
      toast.error(errText(e, "Couldn't add that gift card. Please try again."));
    } finally {
      setCodeBusy(false);
    }
  };

  const handleApplyCoupon = () => {
    const code = couponCode.trim().toUpperCase();
    if (!code) return;
    setCodeNote('');
    if (GIFT_CODE.test(code)) { redeemGift(code); return; }
    validateCouponMutation.mutate(code);
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

  // CMTV 2026-10-16: after a gift card (or a referral welcome credit), use the new credit on this order
  useEffect(() => {
    if (!useAfterGift || !(availableCredits > 0)) return;
    setUseAfterGift(false);
    handleToggleCredits(true);
  }, [useAfterGift, availableCredits]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      {/* Coupon Section (CMTV 2026-10-16: one "Have a code?" box for coupons, gift cards and referral codes) */}
      {!appliedCoupon && !codeOpen ? (
        <div>
          <button type="button" onClick={() => setCodeOpen(true)} className="flex items-center gap-2 text-sm font-semibold text-blue-600 hover:underline" data-testid="have-a-code">
            <Tag className="w-4 h-4" /> Have a code? (coupon, gift card or referral)
          </button>
          {codeNote && <p className="mt-2 text-sm text-green-700 dark:text-green-400">{codeNote}</p>}
        </div>
      ) : (
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Tag className="w-5 h-5 text-blue-600" />
          <h3 className="font-semibold text-gray-900 dark:text-white">Have a code?</h3>
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
              placeholder="Coupon, gift card or referral"
              className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              data-testid="coupon-input"
            />
            <button
              onClick={handleApplyCoupon}
              disabled={!couponCode.trim() || validateCouponMutation.isLoading || codeBusy}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              data-testid="apply-coupon-btn"
            >
              {validateCouponMutation.isLoading || codeBusy ? 'Checking...' : 'Apply'}
            </button>
          </div>
        )}
        {codeNote && <p className="mt-2 text-sm text-green-700 dark:text-green-400">{codeNote}</p>}
      </div>
      )}

      {/* Credits Section (CMTV 2026-10-16: only when the customer has credit) */}
      {availableCredits > 0 && (
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
        ) : null}
      </div>
      )}
    </div>
  );
};

export default CheckoutCouponCredits;
