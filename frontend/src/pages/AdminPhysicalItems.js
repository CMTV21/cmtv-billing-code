import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Plus, Edit, Trash2, Package, X, Upload, Image as ImageIcon } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { physicalItemsAPI } from '../api/api';
import { SPEC_FIELDS, resolveImage } from '../components/PhysicalItemCard';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';
const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';
const labelCls = 'block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-1';

const EMPTY_ITEM = {
  name: '', description: '', price: '', compare_at_price: '', sku: '', images: [],
  weight: '', weight_unit: 'kg', length: '', width: '', height: '', dimension_unit: 'cm',
  stock_quantity: 0, track_stock: true, active: true, display_order: 0,
  specs: { cpu: '', gpu: '', ram: '', storage: '', ethernet: '', wifi: '', bluetooth: '' }, extra_specs: [],
};

export default function AdminPhysicalItems() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(null);

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['admin-physical-items'],
    queryFn: async () => (await physicalItemsAPI.adminList()).data,
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => physicalItemsAPI.adminDelete(id),
    onSuccess: () => { toast.success('Item deleted'); queryClient.invalidateQueries(['admin-physical-items']); },
    onError: (e) => toast.error(e.response?.data?.detail || 'Delete failed'),
  });

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="bg-white dark:bg-gray-900 shadow-sm border-b border-gray-200 dark:border-gray-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600"><ArrowLeft className="w-5 h-5" />Back to Dashboard</Link>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">Physical Items</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Devices and hardware shipped to customers. Shipping rates are configured under Settings → Shipping.</p>
          </div>
          <button onClick={() => setEditing({ ...EMPTY_ITEM })} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700" data-testid="add-physical-item-btn">
            <Plus className="w-4 h-4" /> Add Item
          </button>
        </div>

        {isLoading ? (
          <div className="text-center py-12"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto" /></div>
        ) : items.length === 0 ? (
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
            <Package className="w-14 h-14 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-600 dark:text-gray-300">No physical items yet. Add your first device.</p>
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-800">
                <tr>
                  {['Item', 'SKU', 'Price', 'Weight', 'Stock', 'Status', ''].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {items.map((item) => (
                  <tr key={item.id} data-testid={`physical-item-row-${item.id}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-12 h-12 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center overflow-hidden shrink-0">
                          {item.images?.[0] ? <img src={resolveImage(item.images[0])} alt="" className="w-full h-full object-cover" /> : <ImageIcon className="w-5 h-5 text-gray-400" />}
                        </div>
                        <div>
                          <p className="font-semibold text-gray-900 dark:text-white">{item.name}</p>
                          <p className="text-xs text-gray-500 truncate max-w-xs">{[item.specs?.cpu, item.specs?.ram, item.specs?.storage].filter(Boolean).join(' · ')}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-gray-600 dark:text-gray-300">{item.sku || '—'}</td>
                    <td className="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-white">${Number(item.price).toFixed(2)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">{item.weight} {item.weight_unit}</td>
                    <td className="px-4 py-3 text-sm">
                      {item.track_stock ? (
                        <span className={`font-semibold ${item.stock_quantity <= 0 ? 'text-red-600' : item.stock_quantity <= 5 ? 'text-amber-600' : 'text-green-600'}`}>{item.stock_quantity}</span>
                      ) : <span className="text-gray-500">Not tracked</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${item.active ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'}`}>{item.active ? 'Active' : 'Hidden'}</span>
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <button onClick={() => setEditing({ ...EMPTY_ITEM, ...item, specs: { ...EMPTY_ITEM.specs, ...(item.specs || {}) } })} className="p-2 text-gray-500 hover:text-blue-600" data-testid={`edit-physical-item-${item.id}`}><Edit className="w-4 h-4" /></button>
                      <button onClick={() => window.confirm(`Delete "${item.name}"?`) && deleteMutation.mutate(item.id)} className="p-2 text-gray-500 hover:text-red-600" data-testid={`delete-physical-item-${item.id}`}><Trash2 className="w-4 h-4" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {editing && <PhysicalItemModal item={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); queryClient.invalidateQueries(['admin-physical-items']); }} />}
    </div>
  );
}

function PhysicalItemModal({ item, onClose, onSaved }) {
  const [form, setForm] = useState(item);
  const [uploading, setUploading] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setSpec = (k, v) => setForm((f) => ({ ...f, specs: { ...f.specs, [k]: v } }));

  const saveMutation = useMutation({
    mutationFn: (payload) => (item.id ? physicalItemsAPI.adminUpdate(item.id, payload) : physicalItemsAPI.adminCreate(payload)),
    onSuccess: () => { toast.success(item.id ? 'Item updated' : 'Item created'); onSaved(); },
    onError: (e) => toast.error(e.response?.data?.detail || 'Save failed'),
  });

  const uploadImage = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const res = await axios.post(`${API_URL}/api/admin/kb/upload`, fd, { headers: { Authorization: `Bearer ${token}` } });
      set('images', [...(form.images || []), res.data.url]);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Image upload failed');
    } finally {
      setUploading(false);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    if (!form.name || form.price === '') { toast.error('Name and price are required'); return; }
    const num = (v, d = 0) => (v === '' || v === null || v === undefined ? d : Number(v));
    saveMutation.mutate({
      ...form,
      price: num(form.price), compare_at_price: form.compare_at_price === '' ? null : num(form.compare_at_price),
      weight: num(form.weight), length: num(form.length), width: num(form.width), height: num(form.height),
      stock_quantity: num(form.stock_quantity), display_order: num(form.display_order),
      extra_specs: (form.extra_specs || []).filter((s) => s.label && s.value),
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form onSubmit={submit} className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-3xl w-full max-h-[92vh] overflow-y-auto" data-testid="physical-item-modal">
        <div className="sticky top-0 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center z-10">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">{item.id ? 'Edit Physical Item' : 'New Physical Item'}</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-6 h-6" /></button>
        </div>
        <div className="p-6 space-y-6">
          <section className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2"><label className={labelCls}>Name *</label><input className={inputCls} value={form.name} onChange={(e) => set('name', e.target.value)} data-testid="pi-name" /></div>
            <div className="sm:col-span-2"><label className={labelCls}>Description</label><textarea rows={3} className={inputCls} value={form.description} onChange={(e) => set('description', e.target.value)} data-testid="pi-description" /></div>
            <div><label className={labelCls}>Price *</label><input type="number" step="0.01" min="0" className={inputCls} value={form.price} onChange={(e) => set('price', e.target.value)} data-testid="pi-price" /></div>
            <div><label className={labelCls}>Compare-at price</label><input type="number" step="0.01" min="0" className={inputCls} value={form.compare_at_price ?? ''} onChange={(e) => set('compare_at_price', e.target.value)} data-testid="pi-compare-price" /></div>
            <div><label className={labelCls}>SKU</label><input className={inputCls} value={form.sku} onChange={(e) => set('sku', e.target.value)} data-testid="pi-sku" /></div>
            <div><label className={labelCls}>Display order</label><input type="number" className={inputCls} value={form.display_order} onChange={(e) => set('display_order', e.target.value)} /></div>
          </section>

          <section>
            <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-3">Specifications</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {SPEC_FIELDS.map(({ key, label, icon: Icon }) => (
                <div key={key}>
                  <label className={`${labelCls} flex items-center gap-1`}><Icon className="w-3.5 h-3.5" />{label}</label>
                  <input className={inputCls} value={form.specs?.[key] || ''} onChange={(e) => setSpec(key, e.target.value)} placeholder={key === 'ethernet' ? 'e.g. 1x Gigabit' : key === 'wifi' ? 'e.g. Wi-Fi 6 (802.11ax)' : key === 'bluetooth' ? 'e.g. 5.2' : ''} data-testid={`pi-spec-${key}`} />
                </div>
              ))}
            </div>
            <div className="mt-3 space-y-2">
              {(form.extra_specs || []).map((s, i) => (
                <div key={i} className="flex gap-2">
                  <input className={inputCls} placeholder="Label (e.g. OS)" value={s.label} onChange={(e) => set('extra_specs', form.extra_specs.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
                  <input className={inputCls} placeholder="Value (e.g. Android TV 12)" value={s.value} onChange={(e) => set('extra_specs', form.extra_specs.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                  <button type="button" onClick={() => set('extra_specs', form.extra_specs.filter((_, j) => j !== i))} className="text-red-500 p-2"><X className="w-4 h-4" /></button>
                </div>
              ))}
              <button type="button" onClick={() => set('extra_specs', [...(form.extra_specs || []), { label: '', value: '' }])} className="text-xs text-blue-600 hover:underline">+ Add another spec</button>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-3">Shipping details</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div><label className={labelCls}>Weight *</label><input type="number" step="0.001" min="0" className={inputCls} value={form.weight} onChange={(e) => set('weight', e.target.value)} data-testid="pi-weight" /></div>
              <div><label className={labelCls}>Unit</label><select className={inputCls} value={form.weight_unit} onChange={(e) => set('weight_unit', e.target.value)}><option value="kg">kg</option><option value="lb">lb</option></select></div>
              <div><label className={labelCls}>L × W × H</label>
                <div className="flex gap-1">
                  {['length', 'width', 'height'].map((d) => (<input key={d} type="number" step="0.1" min="0" className={inputCls} placeholder={d[0].toUpperCase()} value={form[d]} onChange={(e) => set(d, e.target.value)} />))}
                </div>
              </div>
              <div><label className={labelCls}>Unit</label><select className={inputCls} value={form.dimension_unit} onChange={(e) => set('dimension_unit', e.target.value)}><option value="cm">cm</option><option value="in">in</option></select></div>
            </div>
          </section>

          <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
            <div><label className={labelCls}>Stock quantity</label><input type="number" min="0" className={inputCls} value={form.stock_quantity} onChange={(e) => set('stock_quantity', e.target.value)} disabled={!form.track_stock} data-testid="pi-stock" /></div>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 pb-2"><input type="checkbox" checked={form.track_stock} onChange={(e) => set('track_stock', e.target.checked)} className="w-4 h-4" /> Track stock</label>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 pb-2"><input type="checkbox" checked={form.active} onChange={(e) => set('active', e.target.checked)} className="w-4 h-4" data-testid="pi-active" /> Visible in store</label>
          </section>

          <section>
            <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-3">Images</h3>
            <div className="flex flex-wrap gap-3">
              {(form.images || []).map((url, i) => (
                <div key={i} className="relative w-24 h-24 rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                  <img src={resolveImage(url)} alt="" className="w-full h-full object-cover" />
                  <button type="button" onClick={() => set('images', form.images.filter((_, j) => j !== i))} className="absolute top-1 right-1 bg-black/60 text-white rounded-full p-0.5"><X className="w-3 h-3" /></button>
                </div>
              ))}
              <label className="w-24 h-24 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 flex flex-col items-center justify-center text-xs text-gray-500 cursor-pointer hover:border-blue-500">
                <Upload className="w-5 h-5 mb-1" />{uploading ? 'Uploading…' : 'Upload'}
                <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadImage(e.target.files?.[0])} disabled={uploading} data-testid="pi-image-upload" />
              </label>
            </div>
          </section>
        </div>
        <div className="sticky bottom-0 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">Cancel</button>
          <button type="submit" disabled={saveMutation.isPending} className="px-5 py-2 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:opacity-50" data-testid="pi-save-btn">{saveMutation.isPending ? 'Saving…' : 'Save Item'}</button>
        </div>
      </form>
    </div>
  );
}
