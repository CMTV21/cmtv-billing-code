// CMTV local addition 2026-09-25: "Complete your setup" add-on offer at checkout, plus the list of add-on products
// (so an add-on in the cart only offers to extend the same add-on, and a TV plan never offers to extend an add-on).
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import api, { productsAPI, servicesAPI } from '../../api/api';
import { BRAND, lookup } from './brand';

const norm = (s) => String(s || '').trim().toLowerCase();
const firstPrice = (p) => {
  const [term, price] = Object.entries(p?.prices || {})[0] || ['1', 0];
  return { term: parseInt(term, 10) || 1, price: parseFloat(price) || 0 };
};
const termText = (t) => (t === 12 ? 'year' : t === 1 ? 'month' : `${t} months`);

// Active add-on products, in BRAND.addons order
export function useAddonProducts() {
  const { data } = useQuery({
    queryKey: ['cmtv-products-all'],
    queryFn: async () => (await productsAPI.getAll()).data || [],
    staleTime: 300000,
  });
  const names = (BRAND.addons || []).map(norm);
  return (data || [])
    .filter((p) => names.includes(norm(p.name)) && !p.is_trial)
    .sort((a, b) => names.indexOf(norm(a.name)) - names.indexOf(norm(b.name)));
}

// Which of the customer's services an item may extend
export function extendChoices(item, services, addonIds) {
  const isAddon = addonIds.has(item.product_id);
  return (services || []).filter((s) => (isAddon ? s.product_id === item.product_id : !addonIds.has(s.product_id)));
}

const DISMISS_KEY = 'cmtv-addons-dismissed';
const readDismissed = () => { try { return sessionStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; } };

export default function CheckoutAddons({ items, addItem, removeItem, currencySymbol = '$', convertPrice = (n) => n }) {
  const [dismissed, setDismissed] = useState(readDismissed);
  const addons = useAddonProducts();
  const { data: services } = useQuery({
    queryKey: ['cmtv-my-services-all'],
    queryFn: async () => (await servicesAPI.getAll()).data || [],
    staleTime: 60000,
  });
  const { data: tier } = useQuery({
    queryKey: ['cmtv-tier-me'],
    queryFn: async () => (await api.get('/api/cmtv/referral/me')).data,
    staleTime: 60000,
  });

  if (dismissed || addons.length === 0) return null;
  const addonIds = new Set(addons.map((a) => a.id));
  const hasMainPlan = items.some((i) => !addonIds.has(i.product_id) && i.account_type !== 'reseller' && Number(i.price) > 0);
  if (!hasMainPlan) return null;

  const bundleName = Object.keys(BRAND.bundles || {})[0];
  const bundle = addons.find((a) => norm(a.name) === norm(bundleName));
  const parts = (lookup(BRAND.bundles || {}, bundleName) || []).map(norm);
  const inCart = new Set(items.map((i) => i.product_id));
  const owned = new Set((services || []).filter((s) => ['active', 'suspended'].includes(s.status)).map((s) => s.product_id));
  const haveBundle = bundle && (inCart.has(bundle.id) || owned.has(bundle.id));
  const offers = addons.filter((a) => !inCart.has(a.id) && !owned.has(a.id) && !(haveBundle && parts.includes(norm(a.name))));
  if (offers.length === 0) return null;

  const partsTotal = addons.filter((a) => parts.includes(norm(a.name))).reduce((s, a) => s + firstPrice(a).price, 0);
  const freeForMe = !!tier?.free_cmtv_plus;

  const add = (p) => {
    const { term, price } = firstPrice(p);
    if (bundle && p.id === bundle.id) {
      // The bundle replaces any of its parts already in the cart
      items.filter((i) => parts.includes(norm(i.product_name)) && !i.renewal_service_id)
        .forEach((i) => removeItem(i.product_id, i.term_months));
    }
    addItem({ product_id: p.id, product_name: p.name, term_months: term, price, account_type: p.account_type || 'subscriber' });
    toast.success(`${p.name} added`);
  };
  const dismiss = () => { setDismissed(true); try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch (e) { /* private mode */ } };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg shadow mt-6" data-testid="checkout-addons">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-cyan-500" /> Complete your setup
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Add these to your order{freeForMe ? '. As an Ambassador, they\'re free for you.' : '.'}
          </p>
        </div>
        <button type="button" onClick={dismiss} className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 flex items-center gap-1">
          <X className="w-4 h-4" /> No thanks
        </button>
      </div>
      <div className="p-4 grid sm:grid-cols-2 gap-3">
        {offers.map((p) => {
          const { term, price } = firstPrice(p);
          const isBundle = bundle && p.id === bundle.id;
          const saving = isBundle ? Math.max(0, partsTotal - price) : 0;
          const logo = lookup(BRAND.logos || {}, p.name);
          return (
            <div key={p.id} className={`rounded-lg border p-4 flex gap-3 items-start ${isBundle
              ? 'sm:col-span-2 border-cyan-400 bg-cyan-50/60 dark:bg-cyan-900/10' : 'border-gray-200 dark:border-gray-700'}`}>
              {logo ? (
                <img src={logo} alt="" className="w-12 h-12 rounded-lg object-contain bg-gray-900 p-1 flex-shrink-0" />
              ) : (
                <div className="w-12 h-12 rounded-lg flex-shrink-0 bg-gradient-to-br from-cyan-500 to-violet-600 flex items-center justify-center text-white font-bold">
                  {p.name.slice(0, 1)}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-gray-900 dark:text-white">
                  {p.name}
                  {isBundle && saving > 0 && (
                    <span className="ml-2 text-xs font-semibold px-2 py-0.5 rounded-full bg-cyan-600 text-white">
                      save {currencySymbol}{convertPrice(saving).toFixed(2)}
                    </span>
                  )}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {isBundle ? 'Stremio, CMTVpn and Audiobooks together' : (lookup(BRAND.taglines || {}, p.name) || '')}
                </p>
                <p className="text-sm font-semibold text-gray-900 dark:text-white mt-1">
                  {freeForMe ? <><span className="line-through text-gray-400 mr-1">{currencySymbol}{convertPrice(price).toFixed(2)}</span>Free</>
                    : <>{currencySymbol}{convertPrice(price).toFixed(2)}</>}
                  <span className="font-normal text-gray-500 dark:text-gray-400"> / {termText(term)}</span>
                </p>
              </div>
              <button type="button" onClick={() => add(p)} data-testid={`add-addon-${p.id}`}
                className="self-center flex items-center gap-1 px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700">
                <Plus className="w-4 h-4" /> Add
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
