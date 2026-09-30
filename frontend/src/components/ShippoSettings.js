import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Zap, PlugZap, Webhook, CheckCircle2, AlertTriangle, Copy } from 'lucide-react';
import { toast } from 'sonner';
import { shippingAPI } from '../api/api';

const inputCls = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm';
const labelCls = 'block text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-1';
const CARRIER_CHOICES = [['ups', 'UPS'], ['fedex', 'FedEx'], ['usps', 'USPS'], ['canadapost', 'Canada Post'], ['purolator', 'Purolator'], ['other', 'Other carriers (DHL, etc.)']];
const SHIPPO_CARRIER_LABEL = { ups: 'UPS', fedex: 'FedEx', usps: 'USPS', canada_post: 'Canada Post', purolator: 'Purolator', dhl_express: 'DHL Express' };

export function ShippoSettings({ shippo, onChange, currency = { code: 'USD', symbol: '$' } }) {
  const [carriers, setCarriers] = useState(null);
  const set = (patch) => onChange({ ...shippo, ...patch });
  const setParcel = (k, v) => set({ default_parcel: { ...shippo.default_parcel, [k]: v } });
  const toggleCarrier = (code) => {
    const cur = shippo.allowed_carriers || [];
    set({ allowed_carriers: cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code] });
  };

  const test = useMutation({
    mutationFn: () => shippingAPI.shippoTest(),
    onSuccess: (res) => { setCarriers(res.data); toast.success(res.data.message); },
    onError: (e) => { setCarriers(null); toast.error(e.response?.data?.detail || 'Connection failed'); },
  });
  const registerHook = useMutation({
    mutationFn: () => shippingAPI.shippoRegisterWebhook(),
    onSuccess: (res) => toast.success(`Webhook registered with Shippo (${res.data.is_test ? 'test' : 'live'} mode)`),
    onError: (e) => toast.error(e.response?.data?.detail || 'Webhook registration failed'),
  });

  return (
    <section className="rounded-lg border border-violet-200 dark:border-violet-900/60 bg-violet-50/40 dark:bg-violet-950/20 p-5" data-testid="shippo-settings">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2"><Zap className="w-4 h-4 text-violet-600" /> Shippo — live multi-carrier rates &amp; labels</h3>
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1 max-w-2xl">
            One API key for UPS, FedEx, USPS, Canada Post, Purolator and more. Customers see real-time quotes at checkout (your rate table stays as a fallback / extra options), and you can buy the label + tracking number with one click from Shipments.
            Carrier quotes are converted into your store currency (<strong>{currency.code}</strong>) before markup, so customers always pay in one currency.
            Connect your carrier accounts at <span className="font-mono">portal.goshippo.com</span>.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200">
          <input type="checkbox" className="w-4 h-4" checked={!!shippo.enabled} onChange={(e) => set({ enabled: e.target.checked })} data-testid="shippo-enabled" /> Enabled
        </label>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="md:col-span-2">
          <label className={labelCls}>API token {shippo.mode && <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] ${shippo.mode === 'test' ? 'bg-amber-100 text-amber-800' : 'bg-green-100 text-green-800'}`}>{shippo.mode} mode</span>}</label>
          <input type="password" className={inputCls} placeholder={shippo.api_token_set ? shippo.api_token : 'shippo_test_… or shippo_live_…'} value={shippo.api_token || ''}
            onChange={(e) => set({ api_token: e.target.value })} autoComplete="off" data-testid="shippo-token" />
          <p className="text-[11px] text-gray-500 mt-1">{shippo.api_token_set ? 'A key is saved. Leave blank to keep it, or paste a new one to replace it.' : 'Paste a test key first — test labels are free and can’t be used to ship.'}</p>
        </div>
        <div className="flex items-end">
          <button type="button" onClick={() => test.mutate()} disabled={test.isPending} className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50" data-testid="shippo-test-btn">
            <PlugZap className="w-4 h-4" /> {test.isPending ? 'Testing…' : 'Test connection'}
          </button>
        </div>
      </div>
      <p className="text-[11px] text-gray-500 mt-1">Test connection uses the <strong>saved</strong> key — save first after pasting a new key.</p>

      {carriers && (
        <div className="mt-3 rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-3 text-sm" data-testid="shippo-carriers">
          <p className="font-medium text-gray-900 dark:text-white flex items-center gap-1.5"><CheckCircle2 className="w-4 h-4 text-green-600" /> {carriers.message}</p>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {carriers.carriers.map((c) => (
              <span key={c.carrier} className={`px-2 py-0.5 rounded-full text-xs ${c.active ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-500'}`}>{SHIPPO_CARRIER_LABEL[c.carrier] || c.carrier}{c.accounts > 1 ? ` ×${c.accounts}` : ''}</span>
            ))}
          </div>
          {carriers.missing_preferred?.length > 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-2 flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" /> Not connected in Shippo: {carriers.missing_preferred.map((c) => SHIPPO_CARRIER_LABEL[c] || c).join(', ')} — add them under Carriers in your Shippo account.</p>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mt-4">
        <div className="col-span-2 md:col-span-3">
          <label className={labelCls}>Default box (used when items have no dimensions)</label>
          <div className="flex items-center gap-2">
            <input type="number" min="1" className={inputCls} placeholder="L" value={shippo.default_parcel?.length ?? ''} onChange={(e) => setParcel('length', e.target.value)} data-testid="shippo-parcel-l" />
            <span className="text-gray-400">×</span>
            <input type="number" min="1" className={inputCls} placeholder="W" value={shippo.default_parcel?.width ?? ''} onChange={(e) => setParcel('width', e.target.value)} />
            <span className="text-gray-400">×</span>
            <input type="number" min="1" className={inputCls} placeholder="H" value={shippo.default_parcel?.height ?? ''} onChange={(e) => setParcel('height', e.target.value)} />
            <select className={`${inputCls} w-20`} value={shippo.default_parcel?.unit || 'cm'} onChange={(e) => setParcel('unit', e.target.value)}><option value="cm">cm</option><option value="in">in</option></select>
          </div>
        </div>
        <div><label className={labelCls}>Markup %</label><input type="number" step="0.1" min="0" className={inputCls} value={shippo.markup_percent ?? 0} onChange={(e) => set({ markup_percent: e.target.value })} data-testid="shippo-markup-pct" /></div>
        <div><label className={labelCls}>Markup flat ({currency.symbol})</label><input type="number" step="0.01" min="0" className={inputCls} value={shippo.markup_flat ?? 0} onChange={(e) => set({ markup_flat: e.target.value })} data-testid="shippo-markup-flat" /></div>
        <div className="col-span-2 md:col-span-1"><label className={labelCls}>Offer carriers</label>
          <div className="flex flex-col gap-1 text-xs text-gray-700 dark:text-gray-300">
            {CARRIER_CHOICES.map(([code, name]) => (
              <label key={code} className="flex items-center gap-1.5"><input type="checkbox" className="w-3.5 h-3.5" checked={!shippo.allowed_carriers?.length || shippo.allowed_carriers.includes(code)} onChange={() => toggleCarrier(code)} /> {name}</label>
            ))}
          </div>
          <p className="text-[10px] text-gray-500 mt-1">Untick everything = offer all.</p>
        </div>
      </div>

      <div className="mt-4 rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-3">
        <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5"><Webhook className="w-4 h-4" /> Tracking updates</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Shippo pushes delivery progress to this URL so shipments flip to <em>delivered</em> automatically. Register it from here (uses your saved key) or paste it under API → Webhooks in Shippo with event <span className="font-mono">track_updated</span>.</p>
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <code className="text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 px-2 py-1 rounded break-all flex-1 min-w-[240px]" data-testid="shippo-webhook-url">{shippo.webhook_url || 'Save settings to generate the webhook URL'}</code>
          {shippo.webhook_url && (
            <button type="button" onClick={() => { navigator.clipboard?.writeText(shippo.webhook_url); toast.success('Webhook URL copied'); }} className="p-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300" title="Copy"><Copy className="w-4 h-4" /></button>
          )}
          <button type="button" onClick={() => registerHook.mutate()} disabled={registerHook.isPending || !shippo.webhook_url} className="px-3 py-2 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-semibold disabled:opacity-50" data-testid="shippo-register-webhook-btn">
            {registerHook.isPending ? 'Registering…' : shippo.webhook_registered_id ? 'Re-register webhook' : 'Register webhook'}
          </button>
        </div>
        {shippo.webhook_registered_id && <p className="text-[11px] text-green-700 dark:text-green-300 mt-1">Registered with Shippo (id {shippo.webhook_registered_id.slice(0, 8)}…)</p>}
      </div>
    </section>
  );
}
