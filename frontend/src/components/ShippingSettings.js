import React, { useEffect, useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Save, Plus, Trash2, Truck, Calculator, KeyRound } from 'lucide-react';
import { toast } from 'sonner';
import { shippingAPI } from '../api/api';
import { COUNTRIES } from '../utils/countries';

const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';
const labelCls = 'block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-1';
const CARRIER_ORDER = ['ups', 'fedex', 'purolator', 'canadapost', 'usps', 'other'];

const newMethod = () => ({
  id: '', carrier: 'ups', service_name: '', zone: 'domestic', countries: [], pricing_type: 'flat',
  base_rate: '', rate_per_unit: '', brackets: [], max_weight: '', free_shipping_over: '', delivery_days: '', enabled: true,
});

export default function ShippingSettings() {
  const { data, isLoading } = useQuery({ queryKey: ['shipping-settings'], queryFn: async () => (await shippingAPI.adminSettings()).data });
  const [form, setForm] = useState(null);
  useEffect(() => { if (data) setForm(data); }, [data]);

  const save = useMutation({
    mutationFn: (payload) => shippingAPI.adminSaveSettings(payload),
    onSuccess: (res) => { toast.success('Shipping settings saved'); setForm({ ...res.data, carrier_catalog: form.carrier_catalog }); },
    onError: (e) => toast.error(e.response?.data?.detail || 'Save failed'),
  });

  if (isLoading || !form) return <div className="p-8 text-center text-gray-500">Loading shipping settings…</div>;

  const catalog = form.carrier_catalog || {};
  const setFrom = (k, v) => setForm({ ...form, ship_from: { ...form.ship_from, [k]: v } });
  const setCarrier = (code, patch) => setForm({ ...form, carriers: { ...form.carriers, [code]: { ...form.carriers[code], ...patch } } });
  const setCred = (code, field, value) => setCarrier(code, { credentials: { ...(form.carriers[code]?.credentials || {}), [field]: value } });
  const setMethod = (i, patch) => setForm({ ...form, methods: form.methods.map((m, j) => (j === i ? { ...m, ...patch } : m)) });

  const submit = () => {
    const num = (v) => (v === '' || v === null || v === undefined ? 0 : Number(v));
    const methods = form.methods.map((m) => ({
      ...m, base_rate: num(m.base_rate), rate_per_unit: num(m.rate_per_unit), max_weight: num(m.max_weight), free_shipping_over: num(m.free_shipping_over),
      brackets: (m.brackets || []).map((b) => ({ max_weight: num(b.max_weight), price: num(b.price) })).filter((b) => b.max_weight > 0),
      countries: (m.countries || []).map((c) => c.toUpperCase()),
    }));
    if (methods.some((m) => !m.service_name)) { toast.error('Every shipping method needs a service name'); return; }
    save.mutate({ ...form, methods });
  };

  return (
    <div className="space-y-8" data-testid="shipping-settings">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2"><Truck className="w-5 h-5" /> Shipping</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Ship-from address, your shipping rate table, and carrier accounts for live rates.</p>
        </div>
        <button onClick={submit} disabled={save.isPending} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50" data-testid="shipping-save-btn">
          <Save className="w-4 h-4" /> {save.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>

      {/* Ship-from */}
      <section className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-5 border border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white mb-3">Ship-from address</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <div><label className={labelCls}>Contact name</label><input className={inputCls} value={form.ship_from.name} onChange={(e) => setFrom('name', e.target.value)} data-testid="shipfrom-name" /></div>
          <div><label className={labelCls}>Company</label><input className={inputCls} value={form.ship_from.company} onChange={(e) => setFrom('company', e.target.value)} /></div>
          <div><label className={labelCls}>Phone</label><input className={inputCls} value={form.ship_from.phone} onChange={(e) => setFrom('phone', e.target.value)} /></div>
          <div className="sm:col-span-2"><label className={labelCls}>Address line 1</label><input className={inputCls} value={form.ship_from.address1} onChange={(e) => setFrom('address1', e.target.value)} data-testid="shipfrom-address1" /></div>
          <div><label className={labelCls}>Address line 2</label><input className={inputCls} value={form.ship_from.address2} onChange={(e) => setFrom('address2', e.target.value)} /></div>
          <div><label className={labelCls}>City</label><input className={inputCls} value={form.ship_from.city} onChange={(e) => setFrom('city', e.target.value)} data-testid="shipfrom-city" /></div>
          <div><label className={labelCls}>State / Province</label><input className={inputCls} value={form.ship_from.state} onChange={(e) => setFrom('state', e.target.value)} /></div>
          <div><label className={labelCls}>Postal code</label><input className={inputCls} value={form.ship_from.postal_code} onChange={(e) => setFrom('postal_code', e.target.value)} data-testid="shipfrom-postal" /></div>
          <div><label className={labelCls}>Country</label>
            <select className={inputCls} value={form.ship_from.country} onChange={(e) => setFrom('country', e.target.value)} data-testid="shipfrom-country">
              {COUNTRIES.map(([c, n]) => (<option key={c} value={c}>{n}</option>))}
            </select>
          </div>
          <div><label className={labelCls}>Weight unit (rate table)</label>
            <select className={inputCls} value={form.weight_unit} onChange={(e) => setForm({ ...form, weight_unit: e.target.value })} data-testid="shipping-weight-unit"><option value="kg">Kilograms (kg)</option><option value="lb">Pounds (lb)</option></select>
          </div>
        </div>
      </section>

      {/* Rate table */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Shipping methods (rate table)</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Each row is an option customers can pick at checkout. Weights use {form.weight_unit}. Free-over and max-weight are optional.</p>
          </div>
          <button onClick={() => setForm({ ...form, methods: [...form.methods, newMethod()] })} className="flex items-center gap-1.5 text-sm bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-2 rounded-lg" data-testid="add-shipping-method-btn"><Plus className="w-4 h-4" /> Add method</button>
        </div>
        {form.methods.length === 0 && <p className="text-sm text-gray-500 italic bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4 border border-dashed border-gray-300 dark:border-gray-600">No shipping methods yet — customers won't be able to check out with physical items until you add at least one.</p>}
        <div className="space-y-3">
          {form.methods.map((m, i) => (
            <div key={m.id || i} className={`rounded-lg border p-4 ${m.enabled ? 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900' : 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 opacity-70'}`} data-testid={`shipping-method-${i}`}>
              <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                <div><label className={labelCls}>Carrier</label>
                  <select className={inputCls} value={m.carrier} onChange={(e) => setMethod(i, { carrier: e.target.value })} data-testid={`method-carrier-${i}`}>
                    {CARRIER_ORDER.map((c) => (<option key={c} value={c}>{catalog[c]?.name || c}</option>))}
                  </select>
                </div>
                <div className="col-span-2 md:col-span-2"><label className={labelCls}>Service name *</label><input className={inputCls} placeholder="e.g. Ground, Expedited Parcel, Priority Mail" value={m.service_name} onChange={(e) => setMethod(i, { service_name: e.target.value })} data-testid={`method-name-${i}`} /></div>
                <div><label className={labelCls}>Zone</label>
                  <select className={inputCls} value={m.zone} onChange={(e) => setMethod(i, { zone: e.target.value })} data-testid={`method-zone-${i}`}>
                    <option value="domestic">Domestic (same country as ship-from)</option>
                    <option value="international">International (all other countries)</option>
                    <option value="countries">Specific countries</option>
                    <option value="worldwide">Worldwide</option>
                  </select>
                </div>
                <div><label className={labelCls}>Pricing</label>
                  <select className={inputCls} value={m.pricing_type} onChange={(e) => setMethod(i, { pricing_type: e.target.value })} data-testid={`method-pricing-${i}`}>
                    <option value="flat">Flat rate</option>
                    <option value="per_weight">Base + per {form.weight_unit}</option>
                    <option value="brackets">Weight brackets</option>
                  </select>
                </div>
                <div><label className={labelCls}>Est. days</label><input className={inputCls} placeholder="e.g. 3-5" value={m.delivery_days} onChange={(e) => setMethod(i, { delivery_days: e.target.value })} /></div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mt-3">
                {m.zone === 'countries' && (
                  <div className="col-span-2 md:col-span-3"><label className={labelCls}>Country codes (comma separated, ISO-2)</label><input className={inputCls} placeholder="US, CA, GB" value={(m.countries || []).join(', ')} onChange={(e) => setMethod(i, { countries: e.target.value.split(',').map((c) => c.trim()).filter(Boolean) })} /></div>
                )}
                {m.pricing_type !== 'brackets' && (
                  <div><label className={labelCls}>{m.pricing_type === 'flat' ? 'Rate' : 'Base rate'}</label><input type="number" step="0.01" min="0" className={inputCls} value={m.base_rate} onChange={(e) => setMethod(i, { base_rate: e.target.value })} data-testid={`method-rate-${i}`} /></div>
                )}
                {m.pricing_type === 'per_weight' && (
                  <div><label className={labelCls}>Per {form.weight_unit} (rounded up)</label><input type="number" step="0.01" min="0" className={inputCls} value={m.rate_per_unit} onChange={(e) => setMethod(i, { rate_per_unit: e.target.value })} /></div>
                )}
                <div><label className={labelCls}>Max weight ({form.weight_unit})</label><input type="number" step="0.01" min="0" className={inputCls} placeholder="none" value={m.max_weight} onChange={(e) => setMethod(i, { max_weight: e.target.value })} /></div>
                <div><label className={labelCls}>Free over ($)</label><input type="number" step="0.01" min="0" className={inputCls} placeholder="none" value={m.free_shipping_over} onChange={(e) => setMethod(i, { free_shipping_over: e.target.value })} /></div>
                <div className="flex items-end justify-between gap-2 col-span-2 md:col-span-1">
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 pb-2"><input type="checkbox" checked={m.enabled} onChange={(e) => setMethod(i, { enabled: e.target.checked })} className="w-4 h-4" /> Enabled</label>
                  <button onClick={() => setForm({ ...form, methods: form.methods.filter((_, j) => j !== i) })} className="p-2 text-gray-400 hover:text-red-600" title="Remove" data-testid={`method-remove-${i}`}><Trash2 className="w-4 h-4" /></button>
                </div>
              </div>
              {m.pricing_type === 'brackets' && (
                <div className="mt-3 space-y-2">
                  <p className={labelCls}>Weight brackets (up to X {form.weight_unit} → price)</p>
                  {(m.brackets || []).map((b, bi) => (
                    <div key={bi} className="flex gap-2 items-center">
                      <span className="text-xs text-gray-500">Up to</span>
                      <input type="number" step="0.01" min="0" className={`${inputCls} w-28`} value={b.max_weight} onChange={(e) => setMethod(i, { brackets: m.brackets.map((x, j) => (j === bi ? { ...x, max_weight: e.target.value } : x)) })} />
                      <span className="text-xs text-gray-500">{form.weight_unit} →</span>
                      <input type="number" step="0.01" min="0" className={`${inputCls} w-28`} placeholder="price" value={b.price} onChange={(e) => setMethod(i, { brackets: m.brackets.map((x, j) => (j === bi ? { ...x, price: e.target.value } : x)) })} />
                      <button onClick={() => setMethod(i, { brackets: m.brackets.filter((_, j) => j !== bi) })} className="p-1 text-gray-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                  <button onClick={() => setMethod(i, { brackets: [...(m.brackets || []), { max_weight: '', price: '' }] })} className="text-xs text-blue-600 hover:underline">+ Add bracket</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <RateTester weightUnit={form.weight_unit} />

      {/* Carrier accounts */}
      <section>
        <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2"><KeyRound className="w-4 h-4" /> Carrier accounts (live rates)</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 mb-3">Rates come from your table above. When you add a carrier's API credentials and switch it to <em>Live API</em>, real-time quotes will replace the table for that carrier once the carrier connector is enabled. Disabling a carrier hides all of its methods at checkout.</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {CARRIER_ORDER.filter((c) => c !== 'other').map((code) => {
            const cfg = form.carriers[code] || { enabled: true, mode: 'table', credentials: {} };
            const fields = catalog[code]?.credential_fields || [];
            return (
              <div key={code} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4" data-testid={`carrier-card-${code}`}>
                <div className="flex items-center justify-between mb-3">
                  <p className="font-semibold text-gray-900 dark:text-white">{catalog[code]?.name || code}</p>
                  <div className="flex items-center gap-3">
                    <select className="text-xs px-2 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200" value={cfg.mode || 'table'} onChange={(e) => setCarrier(code, { mode: e.target.value })} data-testid={`carrier-mode-${code}`}>
                      <option value="table">Rate table</option>
                      <option value="api">Live API</option>
                    </select>
                    <label className="flex items-center gap-1.5 text-xs text-gray-700 dark:text-gray-300"><input type="checkbox" checked={cfg.enabled !== false} onChange={(e) => setCarrier(code, { enabled: e.target.checked })} className="w-4 h-4" /> Enabled</label>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {fields.map((f) => (
                    <div key={f}>
                      <label className={labelCls}>{f.replace(/_/g, ' ')}</label>
                      <input type={/secret|password/.test(f) ? 'password' : 'text'} className={inputCls} value={cfg.credentials?.[f] || ''} onChange={(e) => setCred(code, f, e.target.value)} autoComplete="off" />
                    </div>
                  ))}
                </div>
                {cfg.mode === 'api' && (
                  <p className="text-[11px] text-amber-700 dark:text-amber-300 mt-2">Live API connector for {catalog[code]?.name} is not active yet — the rate table is used as fallback.</p>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function RateTester({ weightUnit }) {
  const [input, setInput] = useState({ weight: '1', subtotal: '100', country: 'US' });
  const [result, setResult] = useState(null);
  const test = useMutation({
    mutationFn: () => shippingAPI.adminTestRates({ weight: Number(input.weight), subtotal: Number(input.subtotal), country: input.country }),
    onSuccess: (res) => setResult(res.data),
    onError: (e) => toast.error(e.response?.data?.detail || 'Test failed'),
  });
  return (
    <section className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-5 border border-gray-200 dark:border-gray-700">
      <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-1"><Calculator className="w-4 h-4" /> Rate tester</h3>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">Uses the <strong>saved</strong> settings — save first, then test what a customer would see.</p>
      <div className="flex flex-wrap items-end gap-3">
        <div><label className={labelCls}>Weight ({weightUnit})</label><input type="number" step="0.01" className={`${inputCls} w-28`} value={input.weight} onChange={(e) => setInput({ ...input, weight: e.target.value })} data-testid="rate-test-weight" /></div>
        <div><label className={labelCls}>Order value ($)</label><input type="number" step="0.01" className={`${inputCls} w-28`} value={input.subtotal} onChange={(e) => setInput({ ...input, subtotal: e.target.value })} /></div>
        <div><label className={labelCls}>Destination</label>
          <select className={`${inputCls} w-48`} value={input.country} onChange={(e) => setInput({ ...input, country: e.target.value })} data-testid="rate-test-country">{COUNTRIES.map(([c, n]) => (<option key={c} value={c}>{n}</option>))}</select>
        </div>
        <button onClick={() => test.mutate()} disabled={test.isPending} className="px-4 py-2 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-sm font-semibold disabled:opacity-50" data-testid="rate-test-btn">{test.isPending ? 'Testing…' : 'Test rates'}</button>
      </div>
      {result && (
        <div className="mt-3 text-sm" data-testid="rate-test-result">
          {result.options.length === 0 ? <p className="text-red-600">No methods match this destination/weight.</p> : (
            <ul className="divide-y divide-gray-200 dark:divide-gray-700 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
              {result.options.map((o) => (<li key={o.method_id} className="flex justify-between px-3 py-2"><span className="text-gray-800 dark:text-gray-200">{o.carrier_name} · {o.service_name}{o.delivery_days ? ` (${o.delivery_days} days)` : ''}</span><span className="font-semibold text-gray-900 dark:text-white">{o.price === 0 ? 'Free' : `$${o.price.toFixed(2)}`}</span></li>))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
