// CMTV local addition 2026-10-04 (the owner: "prompt users to select their TV channel package before completing").
// Checkout step for every NEW TV line in the cart (Imperium / CCTV subscriber plans and trials; never renewals or
// "extend"): Imperium = pick one of the 3 line-ups (nothing pre-selected) + optional custom groups; CCTV = all channel
// groups or pick my own. Payment stays locked until each line has a confirmed choice (useChannelsReady). Choices are
// stored on the cart item (lineup, bouquets, product_name, channels_confirmed); checkout already sends lineup + bouquets.
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { productsAPI } from '../../api/api';
import { useCartStore } from '../../store/store';
import { LINEUPS, lineupName } from './lineups';
import ChannelPicker, { customName } from './ChannelPicker';

const isExtend = (i) => ['extend', 'renew'].includes(i.action_type) && i.renewal_service_id;
const baseName = (i, p) => i.base_name || (p && p.name) || String(i.product_name || '')
  .replace(/ · custom channels \(\d+ groups\)$/, '').replace(/ \((no adult|North America)\)$/, '');

function useProducts() {
  const { data } = useQuery({ queryKey: ['cmtv-products-all'], queryFn: async () => (await productsAPI.getAll()).data || [], staleTime: 300000 });
  return data || [];
}

export function channelSteps(items, products) {
  const byId = Object.fromEntries((products || []).map((p) => [p.id || p._id, p]));
  return items.map((item, index) => ({ item, index, p: byId[item.product_id] }))
    .filter(({ item, p }) => p && p.account_type === 'subscriber' && ['aether', 'xtream'].includes(p.panel_type) && !isExtend(item));
}

export function useChannelsReady(items) {
  const products = useProducts();
  const steps = channelSteps(items, products);
  return { ready: steps.every((s) => s.item.channels_confirmed), count: steps.length };
}

export default function CheckoutChannels({ items }) {
  const products = useProducts();
  const steps = channelSteps(items, products);
  if (!steps.length) return null;
  const done = steps.every((s) => s.item.channels_confirmed);
  return (
    <div id="channel-package" className={`bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-6 border-2 ${done ? 'border-transparent' : 'border-amber-400'}`}>
      <h2 className="text-xl font-bold text-gray-900 dark:text-white">Choose your channel package</h2>
      <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 mb-4">
        Same price whichever you pick. {done ? 'All set: you can change it until you pay.' : 'Pick one to continue to payment.'}
      </p>
      {steps.map((s) => <Step key={`${s.index}-${s.item.product_id}`} {...s} />)}
    </div>
  );
}

function Step({ item, index, p }) {
  const update = (fields) => useCartStore.setState((st) => ({ items: st.items.map((it, i) => (i === index ? { ...it, ...fields } : it)) }));
  const base = baseName(item, p);
  const imperium = p.panel_type === 'aether';
  const [custom, setCustom] = useState(false);
  const [cctvMode, setCctvMode] = useState(item.channels_confirmed ? (item.bouquets ? 'pick' : 'all') : '');

  const setLineup = (key) => update({ base_name: base, lineup: key, bouquets: null, channels_confirmed: true, product_name: lineupName(base, key) });
  const setGroups = (ids) => update({ base_name: base, bouquets: ids || null,
    product_name: customName(imperium ? lineupName(base, item.lineup) : base, ids) });

  return (
    <div className="mb-5 last:mb-0">
      <p className="font-semibold text-gray-900 dark:text-white mb-2">{base}{p.is_trial ? ' · free trial' : ''}</p>
      {imperium ? (
        <>
          <div className="space-y-2">
            {LINEUPS.map((l) => (
              <label key={l.key} className={`flex gap-3 p-3 rounded-lg border-2 cursor-pointer ${item.channels_confirmed && item.lineup === l.key ? 'border-blue-500' : 'border-gray-200 dark:border-gray-700'}`}>
                <input type="radio" name={`lineup-${index}`} className="mt-1" checked={!!item.channels_confirmed && item.lineup === l.key} onChange={() => setLineup(l.key)} />
                <span><b className="text-gray-900 dark:text-white">{l.label}</b>
                  <span className="block text-sm text-gray-600 dark:text-gray-400">{l.note}</span></span>
              </label>
            ))}
          </div>
          {item.channels_confirmed && (
            item.bouquets && !custom ? (
              <p className="text-sm mt-2 text-gray-600 dark:text-gray-400">Custom channels: {item.bouquets.length} groups ·{' '}
                <button type="button" className="underline" onClick={() => setCustom(true)}>change</button></p>
            ) : (
              <div className="mt-3"><ChannelPicker productId={item.product_id} lineup={item.lineup} value={item.bouquets || null} onChange={setGroups} /></div>
            )
          )}
        </>
      ) : (
        <>
          <div className="space-y-2">
            {[['all', 'All channel groups', 'Every channel group in this plan. Most people pick this.'],
              ['pick', 'Choose my channel groups', 'Keep only the countries and categories you want, so your app is easier to scroll.']].map(([k, t, n]) => (
              <label key={k} className={`flex gap-3 p-3 rounded-lg border-2 cursor-pointer ${cctvMode === k ? 'border-blue-500' : 'border-gray-200 dark:border-gray-700'}`}>
                <input type="radio" name={`cctv-${index}`} className="mt-1" checked={cctvMode === k}
                  onChange={() => { setCctvMode(k); update({ base_name: base, channels_confirmed: true, ...(k === 'all' ? { bouquets: null, product_name: base } : {}) }); }} />
                <span><b className="text-gray-900 dark:text-white">{t}</b><span className="block text-sm text-gray-600 dark:text-gray-400">{n}</span></span>
              </label>
            ))}
          </div>
          {cctvMode === 'pick' && (
            <div className="mt-3"><ChannelPicker source="cctv" productId={item.product_id} value={item.bouquets || null} onChange={setGroups} /></div>
          )}
        </>
      )}
    </div>
  );
}
