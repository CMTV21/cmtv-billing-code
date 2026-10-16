// CMTV local addition 2026-09-25: "Complete your setup" add-on offer at checkout, plus the list of add-on products
// (so an add-on in the cart only offers to extend the same add-on, and a TV plan never offers to extend an add-on).
import React, { useState } from 'react';
import { usePlusOffer } from './Promo'; // 2026-10-05: holiday CMTV+ price
import { useQuery } from '@tanstack/react-query';
import { Plus, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import api, { productsAPI, servicesAPI } from '../../api/api';
import { isRunningTvTrial, isRealTvTrial } from './KeepTrialLogin'; // 2026-10-11/13: ended TV trials can't be extended
import { BRAND, lookup, bundlePartsFor, replacedBy, partsText } from './brand';

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

// Trial product id -> the paid product it's a trial of (products carry `cmtv_trial_of`)
export function useTrialOf() {
  const { data } = useQuery({
    queryKey: ['cmtv-products-all'],
    queryFn: async () => (await productsAPI.getAll()).data || [],
    staleTime: 300000,
  });
  const map = {};
  (data || []).forEach((p) => { if (p.cmtv_trial_of) map[p.id] = p.cmtv_trial_of; });
  return map;
}

// Which of the customer's services an item may extend. An add-on extends the same add-on or its trial
// (so buying Stremio after the trial keeps the same login); a TV plan never extends an add-on.
export function extendChoices(item, services, addonIds, trialOf = {}) {
  const isAddon = addonIds.has(item.product_id);
  // 2026-10-11 (owner): a CCTV/Imperium trial that ended MORE than 7 days ago isn't offered (it's often deleted on the panel by
  // then; renewing it fails). [2026-10-13: superseded below, no ended trial is offered.]
  // 2026-10-13 (owner, option B): billing now gives ANY ended real trial a new line, so ended trials aren't offered at all
  const endedTvTrial = (s) => isRealTvTrial(s) && !isRunningTvTrial(s);
  return (services || []).filter((s) => !endedTvTrial(s)).filter((s) => (isAddon
    ? s.product_id === item.product_id || trialOf[s.product_id] === item.product_id
    : !addonIds.has(s.product_id) && !trialOf[s.product_id]));
}

const DISMISS_KEY = 'cmtv-addons-dismissed';
const readDismissed = () => { try { return sessionStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; } };

export default function CheckoutAddons({ items, addItem, removeItem, currencySymbol = '$', convertPrice = (n) => n }) {
  const [dismissed, setDismissed] = useState(readDismissed);
  const [more, setMore] = useState(false);   // CMTV 2026-10-16: "Other add-ons"
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

  const plusOffer = usePlusOffer(items);   // 2026-10-05
  if (dismissed || addons.length === 0) return null;
  const addonIds = new Set(addons.map((a) => a.id));
  const hasMainPlan = items.some((i) => !addonIds.has(i.product_id) && i.account_type !== 'reseller' && Number(i.price) > 0 && !i.gift); // 2026-10-05: not gift cards
  if (!hasMainPlan) return null;

  const bundleName = Object.keys(BRAND.bundles || {})[0];
  const bundle = addons.find((a) => norm(a.name) === norm(bundleName));
  const onSale = addons.map((a) => a.name);   // 2026-09-30: Nuvio replaces Stremio once it's on sale
  const partNames = bundlePartsFor(bundleName, onSale);
  const parts = partNames.map(norm);
  const replaced = replacedBy(onSale);
  const inCart = new Set(items.map((i) => i.product_id));
  const owned = new Set((services || []).filter((s) => ['active', 'suspended'].includes(s.status)).map((s) => s.product_id));
  const haveBundle = bundle && (inCart.has(bundle.id) || owned.has(bundle.id));
  const offers = addons.filter((a) => !inCart.has(a.id) && !owned.has(a.id) && !(haveBundle && parts.includes(norm(a.name)))
    && !replaced.includes(norm(a.name)));
  if (offers.length === 0) return null;

  const partsTotal = addons.filter((a) => parts.includes(norm(a.name))).reduce((s, a) => s + firstPrice(a).price, 0);
  const freeForMe = !!tier?.free_cmtv_plus;

  const add = (p) => {
    const { term, price: listPrice } = firstPrice(p);
    const price = plusOffer && p.id === plusOffer.id ? Math.min(plusOffer.price, listPrice) : listPrice;   // 2026-10-05
    if (bundle && p.id === bundle.id) {
      // The bundle replaces any of its parts already in the cart
      items.filter((i) => parts.includes(norm(i.product_name)) && !i.renewal_service_id)
        .forEach((i) => removeItem(i.product_id, i.term_months));
    }
    addItem({ product_id: p.id, product_name: p.name, term_months: term, price, account_type: p.account_type || 'subscriber' });
    toast.success(`${p.name} added`);
  };
  const dismiss = () => { setDismissed(true); try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch (e) { /* private mode */ } };

  // CMTV local change 2026-10-16 (owner, batch 3: "keep the add-on prompt, but quiet"): one line with the best offer (the
  // bundle if it's on offer) + Add; the other add-ons behind "Other add-ons"; "No thanks" hides it for this visit.
  const priceOf = (p) => (plusOffer && p.id === plusOffer.id ? Math.min(plusOffer.price, firstPrice(p).price) : firstPrice(p).price);
  const label = (p) => {
    const isBundle = bundle && p.id === bundle.id;
    const saving = isBundle ? Math.max(0, partsTotal - priceOf(p)) : 0;
    const what = isBundle ? ` (${partsText(partNames)})` : '';
    const cost = freeForMe ? 'free for you' : `${currencySymbol}${convertPrice(priceOf(p)).toFixed(2)} / ${termText(firstPrice(p).term)}`;
    return <>{p.name}{what} · {cost}{saving > 0 && !freeForMe ? ` · save ${currencySymbol}${convertPrice(saving).toFixed(2)}` : ''}</>;
  };
  const top = offers.find((p) => bundle && p.id === bundle.id) || offers[0];
  const rest = offers.filter((p) => p.id !== top.id);
  const addBtn = (p) => (
    <button type="button" onClick={() => add(p)} data-testid={`add-addon-${p.id}`}
      className="flex items-center gap-1 px-2.5 py-1 bg-blue-600 text-white rounded-md text-xs font-semibold hover:bg-blue-700">
      <Plus className="w-3.5 h-3.5" /> Add
    </button>
  );
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 mt-6 px-4 py-3 text-sm" data-testid="checkout-addons">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Sparkles className="w-4 h-4 text-cyan-500 flex-shrink-0" aria-hidden="true" />
        <span className="text-gray-700 dark:text-gray-300 flex-1 min-w-[12rem]">Add to your order: {label(top)}</span>
        {addBtn(top)}
        {rest.length > 0 && (
          <button type="button" onClick={() => setMore(!more)} aria-expanded={more} className="text-xs text-blue-600 hover:underline">
            {more ? 'Hide' : 'Other add-ons'}
          </button>
        )}
        <button type="button" onClick={dismiss} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">No thanks</button>
      </div>
      {more && rest.map((p) => (
        <div key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 pl-7">
          <span className="text-gray-700 dark:text-gray-300 flex-1 min-w-[12rem]">{label(p)}</span>
          {addBtn(p)}
        </div>
      ))}
    </div>
  );
}
