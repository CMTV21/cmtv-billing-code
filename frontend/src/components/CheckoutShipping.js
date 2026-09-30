import React, { useState } from 'react';
import { Truck, Loader2, MapPin } from 'lucide-react';
import { shippingAPI } from '../api/api';
import { COUNTRIES } from '../utils/countries';
import { useCurrencyStore } from '../store/currency';

export const EMPTY_ADDRESS = { name: '', phone: '', address1: '', address2: '', city: '', state: '', postal_code: '', country: 'US' };

const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-blue-500';

export function CheckoutShipping({ items, address, setAddress, rates, setRates, selectedMethod, setSelectedMethod }) {
  const { symbol, convertPrice } = useCurrencyStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const physical = items.filter((i) => i.item_type === 'physical');

  const update = (field, value) => {
    setAddress({ ...address, [field]: value });
    setRates(null);
    setSelectedMethod(null);
  };

  const addressComplete = address.name && address.address1 && address.city && address.postal_code && address.country;

  const fetchRates = async () => {
    setError('');
    if (!addressComplete) { setError('Please fill in name, address, city, postal code and country first.'); return; }
    setLoading(true);
    try {
      const res = await shippingAPI.rates({
        items: physical.map((i) => ({ physical_item_id: i.product_id, quantity: i.quantity || 1 })),
        ship_to: { country: address.country, state: address.state, postal_code: address.postal_code, city: address.city },
      });
      setRates(res.data);
      if (res.data.options?.length === 1) setSelectedMethod(res.data.options[0]);
      if (!res.data.options?.length) setError('No shipping options are available for this address. Please contact support.');
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not calculate shipping. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg shadow mb-6" data-testid="checkout-shipping-section">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        <Truck className="w-5 h-5 text-blue-600" />
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Shipping</h2>
      </div>
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input className={inputCls} placeholder="Full name *" value={address.name} onChange={(e) => update('name', e.target.value)} data-testid="ship-name" />
          <input className={inputCls} placeholder="Phone" value={address.phone} onChange={(e) => update('phone', e.target.value)} data-testid="ship-phone" />
          <input className={`${inputCls} sm:col-span-2`} placeholder="Address line 1 *" value={address.address1} onChange={(e) => update('address1', e.target.value)} data-testid="ship-address1" />
          <input className={`${inputCls} sm:col-span-2`} placeholder="Address line 2 (apt, suite…)" value={address.address2} onChange={(e) => update('address2', e.target.value)} data-testid="ship-address2" />
          <input className={inputCls} placeholder="City *" value={address.city} onChange={(e) => update('city', e.target.value)} data-testid="ship-city" />
          <input className={inputCls} placeholder="State / Province" value={address.state} onChange={(e) => update('state', e.target.value)} data-testid="ship-state" />
          <input className={inputCls} placeholder="Postal / ZIP code *" value={address.postal_code} onChange={(e) => update('postal_code', e.target.value)} data-testid="ship-postal" />
          <select className={inputCls} value={address.country} onChange={(e) => update('country', e.target.value)} data-testid="ship-country">
            {COUNTRIES.map(([code, name]) => (<option key={code} value={code}>{name}</option>))}
          </select>
        </div>

        <button type="button" onClick={fetchRates} disabled={loading}
          className="w-full sm:w-auto flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
          data-testid="get-shipping-rates-btn">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <MapPin className="w-4 h-4" />}
          {rates ? 'Recalculate shipping' : 'Calculate shipping'}
        </button>

        {error && <p className="text-sm text-red-600" data-testid="shipping-error">{error}</p>}

        {rates?.options?.length > 0 && (
          <div className="space-y-2" data-testid="shipping-options">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Package: {rates.package.item_count} item{rates.package.item_count !== 1 ? 's' : ''} · {rates.package.weight} {rates.package.weight_unit}
            </p>
            {rates.options.map((opt) => {
              const selected = selectedMethod?.method_id === opt.method_id;
              return (
                <label key={opt.method_id} className={`flex items-center justify-between gap-3 p-3 rounded-lg border-2 cursor-pointer transition ${selected ? 'border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'border-gray-200 dark:border-gray-700 hover:border-blue-300'}`}
                  data-testid={`shipping-option-${opt.method_id}`}>
                  <div className="flex items-center gap-3">
                    <input type="radio" name="shipping-method" checked={selected} onChange={() => setSelectedMethod(opt)} className="w-4 h-4 text-blue-600" />
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white text-sm">{opt.carrier_name} · {opt.service_name}</p>
                      {opt.delivery_days && <p className="text-xs text-gray-500 dark:text-gray-400">Est. {opt.delivery_days} business day{String(opt.delivery_days) === '1' ? '' : 's'}</p>}
                    </div>
                  </div>
                  <span className="font-semibold text-gray-900 dark:text-white text-sm">{opt.price === 0 ? 'Free' : `${symbol}${convertPrice(opt.price).toFixed(2)}`}</span>
                </label>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
