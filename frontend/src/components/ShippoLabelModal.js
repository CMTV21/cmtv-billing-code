import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { X, Tag, Download, AlertTriangle, Star, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { shippingAPI } from '../api/api';

export const downloadLabel = async (shipment) => {
  try {
    const res = await shippingAPI.shipmentLabel(shipment.id);
    const url = URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url; a.download = `label-${shipment.order_id.slice(-8).toUpperCase()}.pdf`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) {
    toast.error('Could not download label');
  }
};

export function ShippoLabelModal({ shipment, onClose, onPurchased }) {
  const [selected, setSelected] = useState(null);
  const rates = useQuery({
    queryKey: ['shippo-rates', shipment.id],
    queryFn: async () => (await shippingAPI.shipmentShippoRates(shipment.id)).data,
    retry: false, staleTime: 0,
  });
  const buy = useMutation({
    mutationFn: () => shippingAPI.shipmentBuyLabel(shipment.id, selected),
    onSuccess: (res) => { toast.success(`Label purchased — tracking ${res.data.tracking_number || 'pending'}`); onPurchased(res.data); },
    onError: (e) => toast.error(e.response?.data?.detail || 'Label purchase failed'),
  });
  const options = rates.data?.options || [];
  const chosen = options.find((o) => o.method_id === selected);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] flex flex-col" data-testid="shippo-label-modal">
        <div className="border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2"><Tag className="w-5 h-5 text-violet-600" /> Buy label · Order #{shipment.order_id.slice(-8).toUpperCase()}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" data-testid="shippo-label-close"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-6 overflow-y-auto space-y-4">
          {rates.data && (
            <div className="flex flex-wrap gap-4 text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/60 rounded-lg p-3">
              <span>Parcel: <strong>{rates.data.parcel.length}×{rates.data.parcel.width}×{rates.data.parcel.height} {rates.data.parcel.distance_unit}</strong>, {rates.data.parcel.weight} {rates.data.parcel.mass_unit}</span>
              <span>Customer paid: <strong>{rates.data.currency_symbol || '$'}{Number(rates.data.customer_paid || 0).toFixed(2)} {rates.data.currency}</strong>{rates.data.customer_choice?.provider ? ` (${rates.data.customer_choice.provider})` : ''}</span>
              <span className="text-gray-500">Carrier prices below are what Shippo charges you{options[0] && options[0].currency !== rates.data.currency ? ` (${options[0].currency}; ≈ ${rates.data.currency} shown)` : ''}.</span>
            </div>
          )}
          {rates.isLoading && <div className="text-center py-10 text-sm text-gray-500"><RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />Fetching live rates from Shippo…</div>}
          {rates.isError && <p className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 rounded-lg p-3" data-testid="shippo-rates-error">{rates.error.response?.data?.detail || 'Could not fetch rates'}</p>}
          {rates.data && options.length === 0 && <p className="text-sm text-amber-700 bg-amber-50 dark:bg-amber-900/20 rounded-lg p-3">No carrier returned a rate for this parcel.</p>}
          {options.length > 0 && (
            <ul className="divide-y divide-gray-200 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg" data-testid="shippo-rate-list">
              {options.map((o) => (
                <li key={o.method_id}>
                  <label className={`flex items-center gap-3 px-4 py-3 cursor-pointer ${selected === o.method_id ? 'bg-violet-50 dark:bg-violet-900/20' : 'hover:bg-gray-50 dark:hover:bg-gray-800/60'}`}>
                    <input type="radio" name="shippo-rate" className="w-4 h-4" checked={selected === o.method_id} onChange={() => setSelected(o.method_id)} data-testid={`shippo-rate-${o.shippo.rate_id}`} />
                    <span className="flex-1 text-sm text-gray-900 dark:text-white">
                      <span className="font-medium">{o.carrier_name}</span> · {o.service_name}
                      {o.delivery_days && <span className="text-gray-500"> · {o.delivery_days} day{o.delivery_days === '1' ? '' : 's'}</span>}
                      {o.recommended && <span className="ml-2 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"><Star className="w-3 h-3" /> customer's choice</span>}
                      {o.shippo.test && <span className="ml-2 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">test</span>}
                    </span>
                    <span className="text-right whitespace-nowrap">
                      <span className="font-semibold text-gray-900 dark:text-white">{o.price.toFixed(2)} {o.currency}</span>
                      {o.store_amount != null && o.currency !== rates.data.currency && <span className="block text-[11px] text-gray-500">≈ {rates.data.currency_symbol}{o.store_amount.toFixed(2)} {rates.data.currency}</span>}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {rates.data?.messages?.length > 0 && (
            <ul className="text-xs text-amber-700 dark:text-amber-300 space-y-0.5" data-testid="shippo-rate-messages">{rates.data.messages.map((m, i) => (<li key={i} className="flex gap-1"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />{m}</li>))}</ul>
          )}
        </div>
        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between gap-3">
          <button onClick={() => rates.refetch()} disabled={rates.isFetching} className="text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 inline-flex items-center gap-1"><RefreshCw className={`w-3.5 h-3.5 ${rates.isFetching ? 'animate-spin' : ''}`} /> Refresh rates</button>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">Cancel</button>
            <button onClick={() => buy.mutate()} disabled={!selected || buy.isPending} className="px-5 py-2 rounded-lg bg-violet-600 text-white font-semibold hover:bg-violet-700 disabled:opacity-50 inline-flex items-center gap-2" data-testid="shippo-buy-label-btn">
              <Download className="w-4 h-4" /> {buy.isPending ? 'Purchasing…' : chosen ? `Buy label · ${chosen.price.toFixed(2)} ${chosen.currency}` : 'Buy label'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
