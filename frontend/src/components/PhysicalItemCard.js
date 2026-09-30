import React, { useState } from 'react';
import { Cpu, MonitorCog, MemoryStick, HardDrive, Network, Wifi, Bluetooth, ShoppingCart, Minus, Plus, Package } from 'lucide-react';
import { useCartStore, useAuthStore } from '../store/store';
import { useCurrencyStore } from '../store/currency';
import { toast } from 'sonner';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

export const SPEC_FIELDS = [
  { key: 'cpu', label: 'CPU', icon: Cpu },
  { key: 'gpu', label: 'GPU', icon: MonitorCog },
  { key: 'ram', label: 'RAM', icon: MemoryStick },
  { key: 'storage', label: 'ROM / Storage', icon: HardDrive },
  { key: 'ethernet', label: 'Ethernet', icon: Network },
  { key: 'wifi', label: 'Wi-Fi', icon: Wifi },
  { key: 'bluetooth', label: 'Bluetooth', icon: Bluetooth },
];

export const resolveImage = (url) => (url && url.startsWith('/') ? `${API_URL}${url}` : url);

export function PhysicalItemCard({ item }) {
  const { user } = useAuthStore();
  const { addItem } = useCartStore();
  const { symbol, convertPrice } = useCurrencyStore();
  const [qty, setQty] = useState(1);
  const specs = SPEC_FIELDS.filter((f) => item.specs?.[f.key]);
  const maxQty = item.track_stock ? Math.max(0, item.stock_quantity || 0) : 99;

  const addToCart = () => {
    if (!user) { window.location.href = '/login'; return; }
    addItem({ product_id: item.id, product_name: item.name, price: item.price, account_type: 'physical', item_type: 'physical', quantity: qty, image: item.images?.[0] || '' });
    toast.success(`${item.name} added to cart`);
    window.location.href = '/checkout';
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl shadow-md overflow-hidden border border-gray-200 dark:border-gray-700 hover:shadow-xl transition-shadow flex flex-col" data-testid={`physical-item-card-${item.id}`}>
      <div className="relative aspect-[4/3] bg-gray-100 dark:bg-gray-800 flex items-center justify-center overflow-hidden">
        {item.images?.[0] ? (
          <img src={resolveImage(item.images[0])} alt={item.name} className="w-full h-full object-cover" />
        ) : (
          <Package className="w-16 h-16 text-gray-300 dark:text-gray-600" />
        )}
        {item.compare_at_price > item.price && (
          <span className="absolute top-3 left-3 bg-red-600 text-white text-xs font-bold px-2 py-1 rounded-full">
            Save {Math.round(100 - (item.price / item.compare_at_price) * 100)}%
          </span>
        )}
        {!item.in_stock && (
          <span className="absolute top-3 right-3 bg-gray-900/80 text-white text-xs font-semibold px-2 py-1 rounded-full">Out of stock</span>
        )}
      </div>
      <div className="p-5 flex flex-col flex-1">
        <h3 className="text-lg font-bold text-gray-900 dark:text-white">{item.name}</h3>
        {item.description && <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 line-clamp-3">{item.description}</p>}
        {specs.length > 0 && (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 mt-4 text-xs">
            {specs.map(({ key, label, icon: Icon }) => (
              <div key={key} className="flex items-start gap-1.5">
                <Icon className="w-3.5 h-3.5 mt-0.5 text-blue-600 dark:text-blue-400 shrink-0" />
                <div className="min-w-0">
                  <dt className="text-gray-500 dark:text-gray-400 uppercase tracking-wide text-[10px]">{label}</dt>
                  <dd className="text-gray-800 dark:text-gray-200 font-medium truncate" title={item.specs[key]}>{item.specs[key]}</dd>
                </div>
              </div>
            ))}
          </dl>
        )}
        {item.extra_specs?.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-gray-600 dark:text-gray-400">
            {item.extra_specs.map((s, i) => (<li key={i}><span className="font-medium text-gray-800 dark:text-gray-200">{s.label}:</span> {s.value}</li>))}
          </ul>
        )}
        <div className="mt-auto pt-5 flex items-end justify-between gap-3">
          <div>
            {item.compare_at_price > item.price && (
              <p className="text-xs text-gray-400 line-through">{symbol}{convertPrice(item.compare_at_price).toFixed(2)}</p>
            )}
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{symbol}{convertPrice(item.price).toFixed(2)}</p>
            {item.track_stock && item.in_stock && item.stock_quantity <= 5 && (
              <p className="text-xs text-amber-600 font-medium">Only {item.stock_quantity} left</p>
            )}
          </div>
          {item.in_stock ? (
            <div className="flex items-center gap-2">
              <div className="flex items-center border border-gray-300 dark:border-gray-600 rounded-lg">
                <button type="button" onClick={() => setQty(Math.max(1, qty - 1))} className="p-1.5 text-gray-600 dark:text-gray-300 hover:text-blue-600" data-testid={`qty-minus-${item.id}`}><Minus className="w-4 h-4" /></button>
                <span className="w-7 text-center text-sm font-semibold text-gray-900 dark:text-white" data-testid={`qty-value-${item.id}`}>{qty}</span>
                <button type="button" onClick={() => setQty(Math.min(maxQty, qty + 1))} className="p-1.5 text-gray-600 dark:text-gray-300 hover:text-blue-600" data-testid={`qty-plus-${item.id}`}><Plus className="w-4 h-4" /></button>
              </div>
              <button onClick={addToCart} className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold" data-testid={`add-physical-${item.id}`}>
                <ShoppingCart className="w-4 h-4" /> Add
              </button>
            </div>
          ) : (
            <button disabled className="bg-gray-300 dark:bg-gray-700 text-gray-500 px-4 py-2 rounded-lg text-sm font-semibold cursor-not-allowed">Sold out</button>
          )}
        </div>
      </div>
    </div>
  );
}
