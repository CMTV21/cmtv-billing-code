import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Truck, X, ExternalLink, PackageCheck } from 'lucide-react';
import { toast } from 'sonner';
import { shippingAPI } from '../api/api';
import { countryName } from '../utils/countries';
import { formatDate } from '../utils/timezone';

const CARRIERS = [['ups', 'UPS'], ['fedex', 'FedEx'], ['purolator', 'Purolator'], ['canadapost', 'Canada Post'], ['usps', 'USPS'], ['other', 'Other']];
const STATUSES = ['pending', 'processing', 'shipped', 'delivered', 'cancelled'];
const statusCls = {
  pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
  processing: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  shipped: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300',
  delivered: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  cancelled: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
};
const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';

export const formatAddress = (a) => a ? [a.name, a.address1, a.address2, [a.city, a.state, a.postal_code].filter(Boolean).join(' '), countryName(a.country), a.phone].filter(Boolean) : [];

export default function AdminShipments() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('all');
  const [editing, setEditing] = useState(null);

  const { data: shipments = [], isLoading } = useQuery({
    queryKey: ['admin-shipments', filter],
    queryFn: async () => (await shippingAPI.adminShipments(filter === 'all' ? undefined : filter)).data,
  });

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="bg-white dark:bg-gray-900 shadow-sm border-b border-gray-200 dark:border-gray-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600"><ArrowLeft className="w-5 h-5" />Back to Dashboard</Link>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-2"><Truck className="w-7 h-7" /> Shipments</h1>
          <div className="flex gap-1 bg-white dark:bg-gray-900 rounded-lg p-1 border border-gray-200 dark:border-gray-700">
            {['all', ...STATUSES].map((s) => (
              <button key={s} onClick={() => setFilter(s)} className={`px-3 py-1.5 text-xs font-semibold rounded-md capitalize ${filter === s ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}`} data-testid={`shipments-filter-${s}`}>{s}</button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="text-center py-12"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto" /></div>
        ) : shipments.length === 0 ? (
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
            <PackageCheck className="w-14 h-14 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-600 dark:text-gray-300">No shipments{filter !== 'all' ? ` with status "${filter}"` : ''}.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {shipments.map((s) => (
              <div key={s.id} className="bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-5 grid grid-cols-1 md:grid-cols-12 gap-4" data-testid={`shipment-row-${s.id}`}>
                <div className="md:col-span-3">
                  <p className="text-xs text-gray-500 dark:text-gray-400">Order #{s.order_id.slice(-8).toUpperCase()} · {formatDate(s.created_at)}</p>
                  <p className="font-semibold text-gray-900 dark:text-white mt-1">{s.customer_name}</p>
                  <p className="text-sm text-gray-600 dark:text-gray-300">{s.customer_email}</p>
                  <span className={`inline-block mt-2 px-2 py-0.5 rounded-full text-xs font-semibold capitalize ${statusCls[s.status] || statusCls.pending}`}>{s.status}</span>
                </div>
                <div className="md:col-span-3">
                  <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1">Items</p>
                  <ul className="text-sm text-gray-800 dark:text-gray-200 space-y-0.5">
                    {s.items.map((i, idx) => (<li key={idx}>{i.quantity} × {i.name}</li>))}
                  </ul>
                </div>
                <div className="md:col-span-3">
                  <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1">Ship to</p>
                  <p className="text-sm text-gray-800 dark:text-gray-200 leading-snug">{formatAddress(s.shipping_address).map((l, i) => (<span key={i}>{l}<br /></span>))}</p>
                  <p className="text-xs text-gray-500 mt-1">{s.shipping_method?.carrier_name} · {s.shipping_method?.service_name} · ${Number(s.shipping_cost || 0).toFixed(2)}</p>
                </div>
                <div className="md:col-span-3 flex flex-col items-start md:items-end justify-between gap-2">
                  {s.tracking_number ? (
                    <div className="text-sm text-right">
                      <p className="text-xs text-gray-500 uppercase">Tracking</p>
                      {s.tracking_url ? (
                        <a href={s.tracking_url} target="_blank" rel="noreferrer" className="font-mono text-blue-600 hover:underline inline-flex items-center gap-1">{s.tracking_number}<ExternalLink className="w-3 h-3" /></a>
                      ) : <span className="font-mono text-gray-800 dark:text-gray-200">{s.tracking_number}</span>}
                    </div>
                  ) : <p className="text-xs text-gray-400 italic">No tracking yet</p>}
                  <button onClick={() => setEditing(s)} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700" data-testid={`update-shipment-${s.id}`}>Update</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
      {editing && <ShipmentModal shipment={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); queryClient.invalidateQueries(['admin-shipments']); }} />}
    </div>
  );
}

function ShipmentModal({ shipment, onClose, onSaved }) {
  const [form, setForm] = useState({
    status: shipment.status, carrier: shipment.carrier || shipment.shipping_method?.carrier || 'other',
    tracking_number: shipment.tracking_number || '', notes: shipment.notes || '',
  });
  const mutation = useMutation({
    mutationFn: (payload) => shippingAPI.adminUpdateShipment(shipment.id, payload),
    onSuccess: () => { toast.success(form.status === 'shipped' && shipment.status !== 'shipped' ? 'Marked shipped — customer notified by email' : 'Shipment updated'); onSaved(); },
    onError: (e) => toast.error(e.response?.data?.detail || 'Update failed'),
  });
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-lg w-full" data-testid="shipment-modal">
        <div className="border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white">Update Shipment · Order #{shipment.order_id.slice(-8).toUpperCase()}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-6 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-1">Status</label>
            <select className={inputCls} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} data-testid="shipment-status">
              {STATUSES.map((s) => (<option key={s} value={s} className="capitalize">{s}</option>))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-1">Carrier</label>
              <select className={inputCls} value={form.carrier} onChange={(e) => setForm({ ...form, carrier: e.target.value })} data-testid="shipment-carrier">
                {CARRIERS.map(([c, n]) => (<option key={c} value={c}>{n}</option>))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-1">Tracking number</label>
              <input className={inputCls} value={form.tracking_number} onChange={(e) => setForm({ ...form, tracking_number: e.target.value })} data-testid="shipment-tracking" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-1">Internal notes</label>
            <textarea rows={2} className={inputCls} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          {form.status === 'shipped' && shipment.status !== 'shipped' && (
            <p className="text-xs text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-900/30 rounded-lg p-3">Saving as <strong>shipped</strong> emails the customer their tracking details.</p>
          )}
        </div>
        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">Cancel</button>
          <button onClick={() => mutation.mutate(form)} disabled={mutation.isPending} className="px-5 py-2 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:opacity-50" data-testid="shipment-save-btn">{mutation.isPending ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  );
}
